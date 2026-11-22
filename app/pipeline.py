"""The jobs the dashboard can start. Each takes a `log(msg)` callback for progress."""
import datetime as dt
import math
import re
from difflib import SequenceMatcher
from pathlib import Path

import yaml

from app import glossary, llm, notes, plaud, vault, voices
from app.config import ROOT, cfg
from app.pipeline_filters import clean


def _audio(rec: dict) -> Path:
    return rec["_dir"] / f"{rec['stem']}.ogg"


def match_speakers(old_turns, new_turns, old_speakers, fixes) -> dict:
    """Greedy one-to-one matches by shared seconds, with a 50% inheritance floor."""
    old = sorted(old_turns, key=lambda t: t[0])
    totals, shared, i = {}, {}, 0
    for s, e, spk in sorted(new_turns, key=lambda t: t[0]):
        totals[spk] = totals.get(spk, 0) + e - s
        while i < len(old) and old[i][1] <= s:
            i += 1
        for j in range(i, len(old)):
            a, b, previous = old[j]
            if a >= e:
                break
            seconds = max(0, min(e, b) - max(s, a))
            if seconds:
                key = (spk, previous)
                shared[key] = shared.get(key, 0) + seconds
    matches, used = {}, set()
    for (spk, previous), seconds in sorted(shared.items(), key=lambda item: (-item[1], item[0])):
        if spk not in matches and previous not in used and seconds >= totals[spk] * 0.5:
            matches[spk] = previous
            used.add(previous)
    reserved = set(old_speakers) | {t[2] for t in old_turns} | {f["spk"] for f in fixes}
    next_id = max((int(s[1:]) for s in reserved), default=0) + 1
    for spk in sorted(totals):
        if spk not in matches:
            matches[spk] = f"S{next_id}"
            next_id += 1
    return matches


def _assign(rec: dict) -> None:
    from app import speech
    diar = rec["diarization"]
    turns = [[s, e, speaker_target(rec, k)] for s, e, k in diar["turns"]]
    fixes = [f | {"spk": speaker_target(rec, f["spk"])} for f in rec["fixes"]]
    utts = speech.utterances(rec["words"], turns, overlap=diar["overlap"], fixes=fixes)
    for u in utts:
        u["text"] = clean(u["text"], cfg["hallucination_blocklist"])
        rec["speakers"].setdefault(u["spk"], {"name": ""})
    rec["utterances"] = [u for u in utts if u["text"].strip()]


def _word_speakers(rec: dict) -> list:
    ids, i = [], 0
    utts = rec["utterances"]
    for word in rec["words"]:
        t = (word["s"] + word["e"]) / 2
        while i < len(utts) and utts[i]["e"] < t:
            i += 1
        ids.append(utts[i]["spk"] if i < len(utts) and utts[i]["s"] <= t else None)
    return ids


def _speakers(rec: dict, audio, num_speakers: int, log) -> None:
    vault.writable(rec)
    from app import speech
    log("separating speakers")
    data = speech.diarize(audio, num_speakers, log)
    before = _word_speakers(rec)
    # Zero-length entries reserve ids for voices heard only in overlapping speech.
    mapping = match_speakers(rec["diarization"]["turns"],
                             [*data["turns"], *((0, 0, k) for k in data["embeddings"])],
                             rec["speakers"], rec["fixes"])
    for spk in mapping.values():
        rec["speakers"].setdefault(spk, {"name": ""})
    rec["num_speakers"] = num_speakers
    rec["speaker_engine"] = data["engine"]
    rec["diarization"] = {"engine": data["engine"], "rev": rec["diarization"]["rev"] + 1,
                          "at": dt.datetime.now().isoformat(timespec="seconds"),
                          "asked": {"num": num_speakers, "min": 0, "max": 0},
                          "turns": [[s, e, mapping[k]] for s, e, k in data["turns"]],
                          "overlap": data["overlap"],
                          "embeddings": {mapping[k]: v for k, v in data["embeddings"].items()}}
    rec["suggestions"] = voices.suggest(rec)
    _assign(rec)
    rec["speakers_rev"] += 1
    rec["history"].append({"kind": "speakers", "rev": rec["speakers_rev"],
                           "changed": sum(a != b for a, b in zip(before, _word_speakers(rec))) / max(len(before), 1)})
    notes.keep_minor(rec)


def _transcribe(rec: dict, model: str, log) -> None:
    vault.writable(rec)
    before = [w["w"].strip() for w in rec["words"]]
    if model == "ensemble" and not (ROOT / cfg["parakeet_dir"]).is_dir():
        raise RuntimeError(f"Parakeet model folder is missing: {cfg['parakeet_dir']}")
    from app import speech
    audio = speech.load_audio(_audio(rec))
    terms = glossary.active(rec["group"], rec["id"])
    whisper = cfg["whisper_model"] if model == "ensemble" else model
    hints, dropped, sent = "", [], []
    if terms:
        tokenizer = speech._whisper(whisper).hf_tokenizer
        hints, dropped = glossary.hotwords(rec["group"], rec["id"], tokenizer)
        if dropped and rec["group"] == cfg["inbox"]:
            # More words than Whisper takes, from every folder: listen to a few slices first so the
            # folder this recording is about makes the cut. About 3 minutes of audio, a few seconds.
            log("transcribing samples to pick glossary words")
            text = " ".join(w["w"] for w in speech.transcribe(speech.samples(audio), whisper)[0])
            if lead := glossary.leading(rec["group"], text):
                log(f"glossary: {', '.join(lead)} words first (heard in the samples)")
                terms = glossary.active(rec["group"], rec["id"], text)
                hints, dropped = glossary.hotwords(rec["group"], rec["id"], tokenizer, text)
        # A single owner term may itself contain the comma separator.
        length = 0
        for term in terms:
            length += len(term) + (2 if sent else 0)
            if length > len(hints):
                break
            sent.append(term)
    log(f"transcribing with {whisper} ({len(sent)} glossary terms)")
    on_prog = getattr(log, "progress", None)
    if on_prog is not None:
        rec["words"], rec["language"] = speech.transcribe(audio, whisper, hints, on_progress=on_prog)
    else:
        rec["words"], rec["language"] = speech.transcribe(audio, whisper, hints)
    if model == "ensemble":  # second model + LLM arbiter; slower, measurably fewer errors
        if rec["language"] in cfg["ensemble_languages"]:
            from app import ensemble
            log("transcribing with the second model (Parakeet)")
            second = speech.transcribe_parakeet(audio, **({"on_progress": on_prog} if on_prog else {}))
            rec["words"], rec["ensemble_rejected"], candidates = ensemble.fuse(
                [rec["words"], second], terms, cfg.get("arbiter_provider") or cfg["default_provider"],
                log, ensemble.common_words(rec["language"]))
            glossary.add_candidates(rec["group"], candidates, rec["id"], "ensemble", rec["date"])
        else:
            log(f"ensemble skipped for {rec['language']}")
            rec.pop("ensemble_rejected", None)
    rec["model"] = model
    rec["transcript"] = {"model": model, "rev": rec["transcript"]["rev"] + 1,
                         "at": dt.datetime.now().isoformat(timespec="seconds"), "glossary": sent,
                         "glossary_dropped": dropped}
    after = [w["w"].strip() for w in rec["words"]]
    changed = sum(max(j - i, b - a) for tag, i, j, a, b
                  in SequenceMatcher(None, before, after, autojunk=False).get_opcodes() if tag != "equal")
    rec["history"].append({"kind": "transcript", "rev": rec["transcript"]["rev"],
                           "changed": min(1.0, changed / max(len(before), len(after), 1))})
    if rec["diarization"]["turns"] or rec["diarization"].get("engine"):
        _assign(rec)
    notes.keep_minor(rec)


def error_kind(error) -> str:
    if isinstance(error, llm.ProviderError):
        return error.kind
    text = str(error)
    low = text.lower()
    if "auth_failed" in low or "sign-in expired" in low or re.search(r"sign in to \S+ again", text, re.I):
        return "auth"
    if "cuda" in low and ("out of memory" in low or "out-of-memory" in low):
        return "gpu"
    if (m := re.search(r"(?:^|:\s*|;\s*)(\S+)\s+limit\b", text)) and m[1] in cfg["providers"]:
        return "limit"
    if (m := re.search(r"(?:^|:\s*|;\s*)(\S+)\s+failed\b", text)) and m[1] in cfg["providers"]:
        return llm.classify(m[1], None, text)
    if any(p in low for p in ("usage limit", "rate limit", "rate_limit", "quota")):
        return "limit"
    return "other"


def retry_delay(error, attempts: int) -> int | None:
    delays = (300, 1800, 7200)
    if attempts >= len(delays):
        return None
    kind = error_kind(error)
    if kind == "limit":
        return 7200
    return delays[attempts] if kind == "other" else None


def ingest(rec_id: str, model: str, num_speakers: int, log, group: str | None = None) -> None:
    existing = next((r for r in vault.scan() if r["id"] == rec_id), None)
    if existing is not None:
        resume(rec_id, log)
        return
    meta = next((r for r in plaud.list_recordings() if r["id"] == rec_id), None)
    if not meta:
        raise RuntimeError("recording not found in your Plaud account")
    rec = vault.new_recording(meta, group)
    rec.update(model=model, num_speakers=num_speakers)
    vault.save(rec)
    resume(rec_id, log)


def _synthesize_words(utterances: list[dict]) -> list[dict]:
    words: list[dict] = []
    for u in utterances:
        tokens = u["text"].split()
        if not tokens:
            continue
        s0, e0 = float(u["s"]), float(u["e"])
        step = max((e0 - s0) / len(tokens), 0.01)
        for i, tok in enumerate(tokens):
            ws = round(s0 + i * step, 2)
            we = round(e0 if i == len(tokens) - 1 else s0 + (i + 1) * step, 2)
            if we <= ws:
                we = round(ws + 0.01, 2)
            words.append({"s": ws, "e": we, "w": " " + tok})
    return words


def ingest_plaud(rec_id: str, log=print, group: str | None = None) -> None:
    """Import audio, highlights, transcript, and notes directly from Plaud without local GPU/LLM."""
    existing = next((r for r in vault.scan() if r["id"] == rec_id), None)
    if existing is not None and existing.get("stage") == "done":
        return
    info = plaud.details(rec_id)
    if existing is None:
        if not info.get("has_transcript"):
            raise RuntimeError("this recording has not been transcribed in Plaud yet")
        meta = next((r for r in plaud.list_recordings() if r["id"] == rec_id), None)
        if not meta:
            raise RuntimeError("recording not found in your Plaud account")
        rec = vault.new_recording(meta, group)
        rec.update(source="plaud", model="plaud")
        vault.save(rec)
    else:
        rec = vault.find(rec_id)
        vault.writable(rec)
        if rec.get("source") != "plaud":
            rec["source"] = "plaud"
            vault.save(rec)

    stage = "download"
    try:
        if rec["stage"] == "new":
            start = info["start_at"]
            rec.update(title=info["title"] or rec["title"], start_at=(
                dt.datetime.fromisoformat(start).replace(tzinfo=None).isoformat(timespec="seconds") if start else None))
            log("downloading audio")
            plaud.download_audio(rec_id, _audio(rec), *[p for p in [getattr(log, "progress", None)] if p])
            rec["marks"] = plaud.marks(rec_id, rec["_dir"] / "marks.tmp.json")
            rec["stage"] = "downloaded"
            vault.save(rec)
        stage = "transcribe"
        if rec["stage"] in ("downloaded", "transcribed"):
            log("downloading transcript from Plaud")
            segs, _ = plaud.transcript(rec_id, rec["_dir"] / "plaud_transcript.tmp.txt")
            if not segs:
                raise RuntimeError("Plaud returned an empty transcript")
            spk_map: dict[str, str] = {}
            speakers: dict[str, dict] = {}
            utterances: list[dict] = []
            for seg in segs:
                label = seg["speaker"].strip()
                if label not in spk_map:
                    sid = f"S{len(spk_map) + 1}"
                    spk_map[label] = sid
                    clean_name = "" if re.fullmatch(r"Speaker\s+\d+", label, re.I) else label
                    speakers[sid] = {"name": clean_name}
                utterances.append({"s": float(seg["s"]), "e": float(seg["e"]),
                                   "spk": spk_map[label], "text": seg["text"].strip(), "overlap": False})
            now = dt.datetime.now().isoformat(timespec="seconds")
            max_e = max((u["e"] for u in utterances), default=0.0)
            rec["duration_s"] = max(float(rec.get("duration_s") or 0.0), max_e)
            rec["speakers"] = speakers
            rec["utterances"] = utterances
            rec["words"] = _synthesize_words(utterances)
            rec["model"] = "plaud"
            rec["speaker_engine"] = "plaud"
            rec["transcript"] = {"model": "plaud", "rev": rec["transcript"]["rev"] + 1, "at": now,
                                 "glossary": [], "glossary_dropped": []}
            rec["diarization"] = {"engine": "plaud", "rev": rec["diarization"]["rev"] + 1, "at": now,
                                  "asked": {"num": 0, "min": 0, "max": 0},
                                  "turns": [[u["s"], u["e"], u["spk"]] for u in utterances],
                                  "overlap": [], "embeddings": {}}
            rec["speakers_rev"] += 1
            rec["stage"] = "speakers"
            vault.render(rec)
        stage = "notes"
        if rec["stage"] == "speakers":
            if info.get("has_summary"):
                log("downloading notes from Plaud")
                plaud_notes = plaud.summaries(rec_id, rec["_dir"] / "plaud_summary.tmp.json")
                created = dt.datetime.now().isoformat(timespec="seconds")
                speaker_labels = notes.labels(rec)
                for pn in plaud_notes:
                    if any(n["blueprint"] == pn["title"] and n["provider"] == "plaud"
                           and (rec["_dir"] / n["file"]).is_file() for n in rec["notes"]):
                        continue
                    meta = {"recording_id": rec["id"], "blueprint": pn["title"], "provider": "plaud",
                            "source": "plaud", "created": created,
                            "transcript_rev": rec["transcript"]["rev"],
                            "speakers_rev": rec["speakers_rev"], "speakers": speaker_labels}
                    head = "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + f"---\nFrom [[{rec['stem']}]]\n\n"
                    name = vault.add_note(rec, f"{pn['title']} (plaud)", head + pn["content"] + "\n")
                    rec["notes"].append({"file": name + ".md", "blueprint": pn["title"], "provider": "plaud",
                                         "at": created, "transcript_rev": rec["transcript"]["rev"],
                                         "speakers_rev": rec["speakers_rev"], "check_failed": []})
            rec.update(stage="done", error=None)
            vault.render(rec)
    except Exception as e:
        rec = vault.find(rec_id)
        attempts = (rec.get("error") or {}).get("attempts", 0) + (error_kind(e) != "auth")
        rec["error"] = {"stage": stage, "message": str(e),
                        "at": dt.datetime.now().isoformat(timespec="seconds"), "attempts": attempts}
        vault.save(rec)
        raise


def resume(rec_id: str, log=print) -> None:
    rec = vault.find(rec_id)
    if rec.get("source") == "plaud":
        ingest_plaud(rec_id, log=log)
        return
    vault.writable(rec)
    stage = "download"
    try:
        if rec["stage"] == "new":
            info = plaud.details(rec_id)
            start = info["start_at"]
            rec.update(title=info["title"] or rec["title"], start_at=(
                dt.datetime.fromisoformat(start).replace(tzinfo=None).isoformat(timespec="seconds") if start else None))
            log("downloading audio")
            plaud.download_audio(rec_id, _audio(rec), *[p for p in [getattr(log, "progress", None)] if p])
            rec["marks"] = plaud.marks(rec_id, rec["_dir"] / "marks.tmp.json")
            rec["stage"] = "downloaded"
            vault.save(rec)
        stage = "transcribe"
        if rec["stage"] == "downloaded":
            _transcribe(rec, rec.get("model") or cfg["whisper_model"], log)
            rec["stage"] = "transcribed"
            vault.save(rec)
        stage = "speakers"
        if rec["stage"] == "transcribed":
            from app import speech
            _speakers(rec, speech.load_audio(_audio(rec)), rec.get("num_speakers", 0), log)
            rec["stage"] = "speakers"
            vault.render(rec)
        stage = "notes"
        if rec["stage"] == "speakers":
            errors, caught = [], []
            auto = [bp for bp in vault.blueprints() if bp["auto"]]
            for k, bp in enumerate(auto):
                if prog := getattr(log, "progress", None):
                    prog(k / len(auto))
                candidates = _auto_candidates(bp)
                allowed_providers = {p for p, _, _ in candidates}
                if any(
                    n["blueprint"] == bp["name"] and n["provider"] in allowed_providers
                    and n["transcript_rev"] == rec["transcript"]["rev"]
                    and n["speakers_rev"] == rec["speakers_rev"]
                    and (rec["_dir"] / n["file"]).is_file() for n in rec["notes"]
                ):
                    continue
                bp_errors, bp_caught, wrote = [], [], False
                for provider, model, effort in candidates:
                    if len(candidates) > 1 and not llm.is_installed(provider):
                        log(f"skipping {provider} for '{bp['name']}': not installed")
                        continue
                    try:
                        generate(rec_id, bp["name"], provider, log, model=model, effort=effort)
                        wrote = True
                        break
                    except Exception as e:
                        bp_errors.append(f"{bp['name']} ({provider}): {e}")
                        bp_caught.append(e)
                        if len(candidates) > 1:
                            log(f"{provider} failed for '{bp['name']}' ({e}); trying next in cascade")
                if not wrote:
                    if bp_errors:
                        errors.extend(bp_errors)
                        caught.extend(bp_caught)
                    else:
                        errors.append(f"{bp['name']}: no cascade provider installed")
                rec = vault.find(rec_id)
            if errors:
                picked = (next((e for e in caught if isinstance(e, llm.ProviderError) and e.kind == "auth"), None)
                          or next((e for e in caught if isinstance(e, llm.ProviderError) and e.kind == "limit"), None)
                          or next((e for e in caught if isinstance(e, llm.ProviderError)), None))
                if picked is not None:
                    raise llm.ProviderError(picked.provider, picked.kind, "; ".join(errors), picked.exit_code) from picked
                raise RuntimeError("; ".join(errors))
            rec.update(stage="done", error=None)
            vault.save(rec)
    except Exception as e:
        rec = vault.find(rec_id)  # Keep only completed stages, not partial in-memory results.
        attempts = (rec.get("error") or {}).get("attempts", 0) + (error_kind(e) != "auth")
        rec["error"] = {"stage": stage, "message": str(e),
                        "at": dt.datetime.now().isoformat(timespec="seconds"), "attempts": attempts}
        vault.save(rec)
        raise


def retranscribe(rec_id: str, model: str, num_speakers: int, log) -> None:
    # Retain num_speakers for jobs queued before ticket 03; only Redo speakers uses it.
    rec = vault.find(rec_id)
    _transcribe(rec, model, log)
    vault.render(rec)


def respeak(rec_id: str, num_speakers: int, log) -> None:
    """Redo only the speaker separation (e.g. with a fixed number of speakers)."""
    from app import speech
    rec = vault.find(rec_id)
    vault.writable(rec)
    _speakers(rec, speech.load_audio(_audio(rec)), num_speakers, log)
    vault.render(rec)


def rename_speakers(rec_id: str, names: dict[str, str] | None = None, true_speakers: int | None = None) -> None:
    """Replace display names while preserving speaker identities."""
    rec = vault.find(rec_id)
    vault.writable(rec)
    if names is not None and (not isinstance(names, dict) or any(
        k not in rec["speakers"] or not isinstance(v, str) or len(v) > 60 for k, v in names.items()
    )):
        raise ValueError("bad speaker names")
    if true_speakers is not None and (type(true_speakers) is not int or true_speakers < 0):
        raise ValueError("true_speakers must be a non-negative integer")
    if names is not None:
        old_map = notes.labels(rec)
        changed_names = []
        affected = {}
        for k, speaker in rec["speakers"].items():
            name = names.get(k, "").strip()
            if name == f"Speaker {k[1:]}":  # the shown default (Settings sends it back): no name
                name = ""
            if name != speaker["name"]:
                affected[k] = speaker["name"]
                if name:
                    changed_names.append(name)
            speaker["name"] = name
        voices.update_names(rec, affected)
        rec["suggestions"] = voices.suggest(rec)
        rec["speakers_rev"] += 1
        rec["history"].append({"kind": "speakers", "rev": rec["speakers_rev"], "changed": 0.0,
                               "renamed": {k: s["name"] for k, s in rec["speakers"].items()}})
        notes.relabel(rec, old_map, notes.labels(rec))
        glossary.add_candidates(rec["group"], changed_names, rec_id, "name", rec["date"])
    if true_speakers is not None:
        rec["true_speakers"] = true_speakers or None
    vault.render(rec)


def answer_suggestion(rec_id: str, spk: str, accept: bool, expected: str | None = None) -> None:
    rec = vault.find(rec_id)
    vault.writable(rec)
    suggestion = voices.suggest(rec).get(spk)
    if suggestion is None or (expected is not None and suggestion["name"] != expected):
        raise ValueError("voice suggestion changed; reopen the speaker view")
    if accept:
        names = {k: s["name"] for k, s in rec["speakers"].items()}
        rename_speakers(rec_id, names | {spk: suggestion["name"]})
    else:
        rec["speakers"][spk]["voice_refused"] = True
        rec["suggestions"] = voices.suggest(rec)
        vault.save(rec)


def speaker_target(rec: dict, spk: str) -> str:
    seen = set()
    while True:
        if not isinstance(spk, str) or spk not in rec["speakers"] or spk in seen:
            raise ValueError("unknown speaker or merge cycle")
        seen.add(spk)
        target = rec["speakers"][spk].get("merged_into")
        if not target:
            return spk
        spk = target


def _save_speakers(rec: dict, before: list, old_map: dict | None = None) -> None:
    _assign(rec)
    rec["suggestions"] = voices.suggest(rec)
    rec["speakers_rev"] += 1
    rec["history"].append({"kind": "speakers", "rev": rec["speakers_rev"],
                           "changed": sum(a != b for a, b in zip(before, _word_speakers(rec))) / max(len(before), 1)})
    if old_map is not None:
        notes.relabel(rec, old_map, notes.labels(rec))
    notes.keep_minor(rec)
    vault.render(rec)


def merge(rec_id: str, src: str, dst: str) -> None:
    rec = vault.find(rec_id)
    vault.writable(rec)
    speaker_target(rec, src)
    dst = speaker_target(rec, dst)
    if src == dst or rec["speakers"][src].get("merged_into"):
        raise ValueError("speaker already merged or merge cycle")
    before = _word_speakers(rec)
    old_map = notes.labels(rec)
    rec["speakers"][src]["merged_into"] = dst
    _save_speakers(rec, before, old_map)


def unmerge(rec_id: str, src: str) -> None:
    rec = vault.find(rec_id)
    vault.writable(rec)
    speaker_target(rec, src)
    if not rec["speakers"][src].get("merged_into"):
        raise ValueError("speaker is not merged")
    before = _word_speakers(rec)
    old_map = notes.labels(rec)
    del rec["speakers"][src]["merged_into"]
    _save_speakers(rec, before, old_map)


def add_fix(rec_id: str, s: float, e: float, spk: str) -> None:
    rec = vault.find(rec_id)
    vault.writable(rec)
    if any(type(t) not in (int, float) or not math.isfinite(t) for t in (s, e)) or not 0 <= s < e <= rec["duration_s"]:
        raise ValueError("span must satisfy 0 <= s < e <= duration_s")
    if spk == "new":
        spk = f"S{max((int(k[1:]) for k in rec['speakers']), default=0) + 1}"
        rec["speakers"][spk] = {"name": ""}
    speaker_target(rec, spk)
    before = _word_speakers(rec)
    rec["fixes"].append({"s": s, "e": e, "spk": spk})
    _save_speakers(rec, before)


def remove_fix(rec_id: str, index: int) -> None:
    rec = vault.find(rec_id)
    vault.writable(rec)
    if type(index) is not int or not 0 <= index < len(rec["fixes"]):
        raise ValueError("bad fix index")
    before = _word_speakers(rec)
    rec["fixes"].pop(index)
    _save_speakers(rec, before)


def closest_voice(rec: dict, spk: str) -> str | None:
    embeddings = rec["diarization"]["embeddings"]
    if spk not in embeddings:
        return None
    voice = embeddings[spk]
    norm = math.hypot(*voice)
    scores = {}
    for k, vector in embeddings.items():
        if k != spk and not rec["speakers"][k].get("merged_into") and norm and math.hypot(*vector):
            scores[k] = sum(a * b for a, b in zip(voice, vector)) / (norm * math.hypot(*vector))
    return max(scores, key=scores.get) if scores else None


TITLE_INSTRUCTION = ("After the note, add a fenced block marked `title` holding a short title for this recording "
                     "(at most 10 words, in the language of the transcript):\n```title\n<title>\n```\n")
_TITLE_BLOCK = re.compile(r"^```title[ \t]*\r?\n(.*?)^```[ \t]*(?:\r?\n|$)", re.M | re.S)


def needs_title(rec: dict) -> bool:
    """Plaud's default title is only a timestamp; a title the owner typed is never replaced."""
    return not rec.get("title_by_user") and not re.search(r"[^\W\d_]", rec.get("title") or "")


def _clean_title(title: str) -> str:
    title = " ".join(title.split()).strip(" #*`\"'")[:120]
    if not title or not title.isprintable() or not re.search(r"[^\W\d_]", title):
        raise ValueError("a title needs at least one letter")
    return title


def _take_title(text: str) -> tuple[str, str | None]:
    found = [line for block in _TITLE_BLOCK.findall(text) for line in block.splitlines() if line.strip()]
    try:
        title = _clean_title(found[0]) if found else None
    except ValueError:
        title = None
    return _TITLE_BLOCK.sub("", text).rstrip(), title


def rename(rec_id: str, title: str) -> None:
    """The owner's own title: shown in the dashboard and the hub note; file names stay, so links survive."""
    if not isinstance(title, str):
        raise ValueError("bad title")
    rec = vault.find(rec_id)
    vault.writable(rec)
    rec.update(title=_clean_title(title), title_by_user=True)
    vault.render(rec)


def build_prompt(rec: dict, bp: dict, ask_title: bool = False) -> str:
    terms = vault.glossary(rec["group"])
    marks = "\n".join(f"- [{vault.mmss(m['t'])}] {m['kind']}: {m['text'] or '(no text)'}" for m in rec["marks"])
    transcript = "\n".join(f"[{vault.mmss(u['s'])}] {vault.speaker_name(rec, u['spk'])}: {u['text'].strip()}"
                           for u in rec["utterances"])
    return (f"{vault.rules()}\n\n{bp['body']}\n\n---\n"
            + (f"Spellings to use: {', '.join(terms)}\n\n" if terms else "")
            + f"Recording: {rec['title']} ({rec['date']}, {rec['duration']})\n\n"
            f"Moments the user flagged while recording:\n{marks or '(none)'}\n\n"
            f"Transcript:\n{transcript}\n\n---\n{TITLE_INSTRUCTION if ask_title else ''}{glossary.INSTRUCTION}\n")


def _auto_candidates(bp: dict) -> list[tuple[str, str | None, str | None]]:
    if bp["provider"]:
        return [(bp["provider"], None, None)]
    configured = cfg["providers"]
    entries = [(p, m, e) for p, m, e in vault.cascade() if p in configured]
    return entries or [(cfg["default_provider"], None, None)]


def generate(rec_id: str, blueprint: str, provider: str, log, file: str | None = None,
             model: str | None = None, effort: str | None = None) -> str:
    rec = vault.find(rec_id)
    vault.writable(rec)
    if file is not None:
        notes.entry(rec, file)
    bp = next(b for b in vault.blueprints() if b["name"] == blueprint)
    ask_title = file is None and needs_title(rec)   # piggybacks on the note: no extra AI call
    prompt = build_prompt(rec, bp, ask_title)
    transcript_rev, speakers_rev = rec["transcript"]["rev"], rec["speakers_rev"]
    speakers = notes.labels(rec)
    used_model = model or (llm.selected_model(provider) if llm.available_models(provider) else None)
    detail = ", ".join(x for x in (used_model, f"effort={effort}" if effort else "") if x)
    log(f"writing '{blueprint}' with {provider}" + (f" ({detail})" if detail else ""))
    if effort:
        run_llm = lambda p_text: llm.run(provider, p_text, model, effort=effort)
    elif model:
        run_llm = lambda p_text: llm.run(provider, p_text, model)
    else:
        run_llm = lambda p_text: llm.run(provider, p_text)

    def call_llm(p_text):
        text, title = _take_title(run_llm(p_text))
        return glossary.strip_block(text) + (title,)

    text, terms, title = call_llm(prompt)
    missing = [r for r in bp["requires"] if r not in text]
    if missing:  # one retry, telling the model what the blueprint's checks found
        log(f"retrying '{blueprint}': missing {missing}")
        text, terms, retry_title = call_llm(f"{prompt}\n\nYour previous answer lacked these required parts: {missing}. "
                                            f"Write the full answer again including them.")
        title = retry_title or title
        missing = [r for r in bp["requires"] if r not in text]
    rec = vault.find(rec_id)  # Names, the title or the folder may change while the provider runs.
    vault.writable(rec)
    if ask_title and title and needs_title(rec):
        log(f"titled '{title}'")
        rec["title"] = title
    glossary.add_candidates(rec["group"], terms, rec_id, "note", rec["date"])
    created = dt.datetime.now().isoformat(timespec="seconds")
    meta = {"recording_id": rec["id"], "blueprint": blueprint, "provider": provider,
            **({"model": used_model} if used_model else {}), "created": created,
            "transcript_rev": transcript_rev, "speakers_rev": speakers_rev, "speakers": speakers}
    if missing:
        meta["check_failed"] = missing
    head = "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + f"---\nFrom [[{rec['stem']}]]\n\n"
    if file is None:
        name = vault.add_note(rec, f"{blueprint} ({provider})", head + text + "\n")
        note = {"file": name + ".md"}
        rec["notes"].append(note)
    else:
        note = notes.entry(rec, file)
        name = file[:-3]
        vault._write_owned(rec, file, head + text + "\n")
    note.update(blueprint=blueprint, provider=provider, at=created, transcript_rev=transcript_rev,
                speakers_rev=speakers_rev, check_failed=missing)
    if used_model:
        note["model"] = used_model
    else:
        note.pop("model", None)
    note.pop("relabel_failed", None)
    vault.render(rec)
    return name
