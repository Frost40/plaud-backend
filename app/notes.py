"""Note labels, revision freshness and explicit regeneration; no automatic AI calls."""
import math
import re

import yaml

from app import vault


def entry(rec: dict, file: str) -> dict:
    if (not isinstance(file, str) or not file.endswith(".md") or any(c in file for c in "\\/:")
            or (rec["_dir"] / file).resolve().parent != rec["_dir"].resolve()):
        raise ValueError("bad note file")
    note = next((n for n in rec["notes"] if n["file"] == file), None)
    if note is None:
        raise ValueError("note is not in this recording")
    return note


def labels(rec: dict) -> dict:
    from app.pipeline import speaker_target
    return {k: vault.speaker_name(rec, speaker_target(rec, k)) for k in rec["speakers"]}


def state(rec: dict, note: dict) -> str:
    if note.get("relabel_failed"):
        return "out_of_date"
    changed = math.fsum(h["changed"] for h in rec["history"]
                        if h["rev"] > note[h["kind"] + "_rev"])
    return "out_of_date" if changed >= .02 else "minor" if changed else "current"


def _rewrite(rec: dict, note: dict, meta: dict, body: str) -> None:
    path = rec["_dir"] / note["file"]
    owned = vault._hash(path.read_text(encoding="utf-8")) == rec.get("written", {}).get(path.name)
    text = "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n" + body
    path.write_text(text, encoding="utf-8")
    if owned:  # Relabelling an owner's edit must not claim ownership of their content.
        rec["written"][path.name] = vault._hash(text)


def relabel(rec: dict, old_map: dict, new_map: dict) -> None:
    for note in rec["notes"]:
        entry(rec, note["file"])
        path = rec["_dir"] / note["file"]
        if not path.is_file():
            continue
        meta, body = vault._frontmatter(path.read_text(encoding="utf-8"))
        previous = meta.get("speakers", old_map)
        targets = {}
        for k, old in previous.items():
            targets.setdefault(old, set()).add(new_map.get(k, old))
        ambiguous = any(len(names) > 1 for names in targets.values())
        if ambiguous:
            note["relabel_failed"] = meta["relabel_failed"] = True
        replacements = {old: next(iter(names)) if len(names) == 1 else old for old, names in targets.items()}
        if any(old != new for old, new in replacements.items()):
            pattern = r"(?<!\w)(?:" + "|".join(re.escape(s) for s in sorted(replacements, key=len, reverse=True)) + r")(?!\w)"
            body = re.sub(pattern, lambda m: replacements[m[0]], body)
        # Keep an older substantive change visible; an ambiguous unmerge needs regeneration.
        pending = any(h["kind"] == "speakers" and note["speakers_rev"] < h["rev"] < rec["speakers_rev"]
                      and h["changed"] for h in rec["history"])
        if not pending and not ambiguous:
            note["speakers_rev"] = rec["speakers_rev"]
        meta.update(speakers={k: new_map.get(k, v) if len(targets[v]) == 1 else v for k, v in previous.items()},
                    speakers_rev=note["speakers_rev"])
        _rewrite(rec, note, meta, body)


def keep_minor(rec: dict) -> None:
    for note in rec["notes"]:
        entry(rec, note["file"])
        path = rec["_dir"] / note["file"]
        if state(rec, note) != "minor" or not path.is_file():
            continue
        meta, body = vault._frontmatter(path.read_text(encoding="utf-8"))
        note.update(transcript_rev=rec["transcript"]["rev"], speakers_rev=rec["speakers_rev"])
        meta.update(transcript_rev=note["transcript_rev"], speakers_rev=note["speakers_rev"], minor_change=True)
        _rewrite(rec, note, meta, body)


def regenerate(rec_id: str, file: str, log=print) -> str:
    from app import llm, pipeline
    rec = vault.find(rec_id)
    note = entry(rec, file)
    model = note.get("model")
    allowed = llm.available_models(note["provider"])
    if model and model in allowed and model != llm.selected_model(note["provider"]):
        return pipeline.generate(rec_id, note["blueprint"], note["provider"], log, file=file, model=model)
    return pipeline.generate(rec_id, note["blueprint"], note["provider"], log, file=file)
