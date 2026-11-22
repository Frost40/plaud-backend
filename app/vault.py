"""Everything the pipeline knows lives in the Obsidian vault:

<vault>/Plaud/<Group>/<date title>/recording.json   machine state (id, words, speakers, marks)
                                  /<date title>.md   hub note linking everything
                                  /<date title> - Transcript.md
                                  /<date title> - <Blueprint> (<provider>).md
<vault>/Plaud/<Group>/Glossary.md                    terms for that group, one per line
<vault>/Plaud/_Glossary.md                           always-on terms
<vault>/Plaud/_Blueprints/*.md                       prompts (+ _rules.md shared by all)

A group is a real folder; moving a recording moves its whole folder. Recordings are found
by the id inside recording.json, never by path, and note names are unique so links survive moves.
"""
import copy
import datetime as dt
import hashlib
import json
import logging
import os
import re
import shutil
from pathlib import Path

import yaml

from app.config import BASE, cfg

_BAD = re.compile(r'[\\/:*?"<>|#^\[\]]')
KEEP = "%% Anything you write below this line is kept when this note is regenerated. %%"
ICON = {"highlight": "⭐", "memo": "✏️", "photo": "📷"}


def safe(name: str) -> str:
    return re.sub(r"\s+", " ", _BAD.sub(" ", name)).strip(" .")[:80]


def group_ok(name: str) -> bool:
    return bool(name) and name == safe(name) and not name.startswith("_")


def mmss(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


# ---------- reading ----------

def scan() -> list[dict]:
    out = []
    for p in BASE.glob("*/*/recording.json"):
        if p.parent.parent.name.startswith("_"):
            continue
        rec = json.loads(p.read_text(encoding="utf-8"))
        rec["group"], rec["_dir"] = p.parent.parent.name, p.parent
        out.append(rec)
    return out


def find(rec_id: str) -> dict:
    for rec in scan():
        if rec["id"] == rec_id:
            return rec
    raise KeyError(f"recording {rec_id} is not in the vault")


def groups() -> list[str]:
    BASE.mkdir(parents=True, exist_ok=True)
    (BASE / cfg["inbox"]).mkdir(exist_ok=True)
    return sorted(d.name for d in BASE.iterdir() if d.is_dir() and not d.name.startswith("_"))


def _frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    return (yaml.safe_load(m[1]) or {}, m[2]) if m else ({}, text)


def blueprints() -> list[dict]:
    out = []
    for p in sorted((BASE / "_Blueprints").glob("*.md")):
        if p.stem.startswith("_"):
            continue
        meta, body = _frontmatter(p.read_text(encoding="utf-8"))
        out.append({"name": p.stem, "auto": bool(meta.get("auto")), "provider": meta.get("provider"),
                    "requires": meta.get("requires") or [], "body": body.strip()})
    return sorted(out, key=lambda b: not b["auto"])  # the dashboard preselects the first one


def rules() -> str:
    p = BASE / "_Blueprints" / "_rules.md"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


_EFFORTS = {"low", "medium", "high", "xhigh", "max"}


def cascade() -> list[tuple[str, str | None, str | None]]:
    p = BASE / "_Blueprints" / "_cascade.md"
    if not p.exists():
        return []
    out: list[tuple[str, str | None, str | None]] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith((">", "#")):
            continue
        line = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", line).strip()
        if not line:
            continue
        if ":" in line:
            prov, rest = line.split(":", 1)
            prov, rest = prov.strip(), rest.strip()
            effort = None
            if ":" in rest:
                head, tail = rest.rsplit(":", 1)
                if tail.strip().lower() in _EFFORTS:
                    rest, effort = head.strip(), tail.strip().lower()
            model = rest or None
        else:
            prov, model, effort = line, None, None
        if prov:
            out.append((prov, model, effort))
    return out


def glossary(group: str) -> list[str]:
    from app.glossary import active
    return active(group)


# ---------- writing ----------

def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def save(rec: dict) -> None:
    writable(rec)
    data = {k: v for k, v in rec.items() if not k.startswith("_") and k != "group"}
    _atomic_text(rec["_dir"] / "recording.json", json.dumps(data, ensure_ascii=False))


def _atomic_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def writable(rec: dict) -> None:
    if rec.get("schema", 1) > 2:
        raise ValueError(f"recording schema {rec['schema']} is newer than supported schema 2")


def migrate_v1(data: dict, note_files: dict[str, dict]) -> dict:
    """Convert legacy data without touching it or the filesystem."""
    rec = copy.deepcopy(data)
    duration = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", rec["duration"])
    if not duration or not any(duration.groups()):
        raise ValueError(f"invalid duration: {rec['duration']!r}")
    rec["duration_s"] = sum(float(v or 0) * scale for v, scale in zip(duration.groups(), (3600, 60, 1)))
    start = rec.get("start_at")
    rec["start_at"] = dt.datetime.fromisoformat(start).replace(tzinfo=None).isoformat(timespec="seconds") if start else None
    rec["speakers"] = {f"S{int(k) + 1}": {"name": v} for k, v in rec.get("speakers", {}).items()}
    for u in rec.get("utterances", []):
        u["spk"] = f"S{int(u['spk']) + 1}"
        u["overlap"] = False
        rec["speakers"].setdefault(u["spk"], {"name": ""})
    rec.update(schema=2, stage="done", error=None, history=[], true_speakers=None,
               fixes=[], speakers_rev=1,
               transcript={"model": rec.get("model"), "rev": 1, "at": None, "glossary": [], "glossary_dropped": []},
               diarization={"engine": "migrated", "rev": 1, "at": None,
                            "asked": {"num": rec.get("num_speakers", 0), "min": 0, "max": 0},
                            "turns": [[u["s"], u["e"], u["spk"]] for u in rec.get("utterances", [])],
                            "overlap": [], "embeddings": {}},
               notes=[{"file": name, "blueprint": meta.get("blueprint"), "provider": meta.get("provider"),
                       "at": str(meta["created"]) if meta.get("created") is not None else None,
                       "transcript_rev": 1, "speakers_rev": 1, "check_failed": meta.get("check_failed") or []}
                      for name, meta in note_files.items()])
    return rec


def migrate_all() -> None:
    for path in BASE.glob("*/*/recording.json"):
        if path.parent.parent.name.startswith("_"):
            continue
        try:
            original = path.read_bytes()
            data = json.loads(original)
            if "schema" in data:
                continue
            note_files = {p.name: _frontmatter(p.read_text(encoding="utf-8"))[0]
                          for p in sorted(path.parent.glob("*.md"))
                          if p.stem not in (data["stem"], f"{data['stem']} - Transcript")}
            rec = migrate_v1(data, note_files)
            backup = path.with_name("recording.v1.json")
            if not backup.exists():
                with backup.open("xb") as f:
                    f.write(original)
            if backup.read_bytes() != original or json.loads(backup.read_bytes()) != data:
                raise ValueError("version 1 backup does not match recording.json")
            save(rec | {"_dir": path.parent})
        except Exception:
            logging.getLogger(__name__).exception("Migration left %s unchanged", path)


def _write_owned(rec: dict, name: str, text: str) -> None:
    """Write a note the pipeline regenerates. If you edited it, your version is kept as a copy."""
    path = rec["_dir"] / name
    written = rec.setdefault("written", {})
    if path.exists() and _hash(path.read_text(encoding="utf-8")) != written.get(name):
        if name == f"{rec['stem']} - Transcript.md":
            from app.glossary import add_candidates, replacements
            previous = json.loads((rec["_dir"] / "recording.json").read_bytes())
            original = " ".join(u["text"] for u in previous["utterances"])
            edited = path.read_text(encoding="utf-8")
            passages = re.findall(r"^\*\*[^\n]+\*\* `[\d:]+`(?: ⇄)?\n(.*?)(?=\n\s*\n|\Z)", edited, re.M | re.S)
            add_candidates(rec["group"], replacements(original, " ".join(passages)), rec["id"], "correction", rec["date"])
        n = 1
        while (backup := path.with_name(f"{path.stem} (your edit {n}).md")).exists():
            n += 1
        path.rename(backup)
    path.write_text(text, encoding="utf-8")
    written[name] = _hash(text)


def new_recording(meta: dict, group: str | None = None) -> dict:
    """Create the folder for a recording in `group` (default: the inbox); returns the rec dict.
    Filing it before transcription lets that folder's glossary guide the transcript."""
    group = group or cfg["inbox"]
    if not group_ok(group):
        raise ValueError(f"invalid folder name: {group!r}")
    # 60 characters: the stem appears twice in every note's path and Windows stops at 260
    stem = safe(f"{meta['date']} {meta['title']}")[:60].strip(" .") or meta["id"]
    d = BASE / group / stem
    if d.exists():  # same date+title, different recording
        stem = f"{stem} {meta['id'][-4:]}"
        d = BASE / group / stem
    d.mkdir(parents=True)
    rec = migrate_v1({**meta, "stem": stem, "speakers": {}, "marks": [], "utterances": [], "words": []}, {})
    rec.update(_dir=d, group=group, stage="new", speakers_rev=0)
    rec["transcript"]["rev"] = rec["diarization"]["rev"] = 0
    rec["diarization"]["engine"] = None
    save(rec)
    return rec


def move(rec_id: str, group: str) -> None:
    if not group_ok(group):
        raise ValueError(f"invalid folder name: {group!r}")
    rec = find(rec_id)
    writable(rec)
    dest = BASE / group / rec["_dir"].name
    if dest.exists():
        raise ValueError("a recording with the same name is already in that folder")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(rec["_dir"]), str(dest))
    from app.glossary import relocate
    relocate()


def speaker_name(rec: dict, spk: str) -> str:
    return rec["speakers"].get(spk, {}).get("name") or f"Speaker {spk[1:]}"


def render(rec: dict) -> None:
    """(Re)write the hub and transcript notes from recording.json."""
    writable(rec)
    stem, marks = rec["stem"], rec.get("marks", [])
    fm = lambda d: "---\n" + yaml.safe_dump(d, allow_unicode=True, sort_keys=False) + "---\n"

    # transcript: marks become callouts placed before the utterance they fall in
    lines, pending = [fm({"recording_id": rec["id"], "type": "transcript", "model": rec.get("model")}),
                      f"Back to [[{stem}]]\n"], list(marks)

    def flush(until: float) -> None:
        while pending and pending[0]["t"] <= until:
            m = pending.pop(0)
            kind = {"highlight": "important", "memo": "note", "photo": "example"}[m["kind"]]
            lines.append(f"> [!{kind}] {ICON[m['kind']]} {mmss(m['t'])} {m['kind'].title()}"
                         + (f"\n> {m['text']}" if m["text"] else "") + "\n")

    for u in rec.get("utterances", []):
        flush(u["e"])
        lines.append(f"**{speaker_name(rec, u['spk'])}** `{mmss(u['s'])}`"
                     + (" ⇄" if u.get("overlap") else "") + f"\n{u['text'].strip()}\n")
    flush(float("inf"))
    _write_owned(rec, f"{stem} - Transcript.md", "\n".join(lines))

    # hub: keep whatever the user wrote below the marker
    hub = rec["_dir"] / f"{stem}.md"
    tail = hub.read_text(encoding="utf-8").split(KEEP, 1)[1] if hub.exists() and KEEP in hub.read_text(encoding="utf-8") else "\n"
    talk = {}
    for u in rec.get("utterances", []):
        talk[u["spk"]] = talk.get(u["spk"], 0) + u["e"] - u["s"]
    spk_ids = sorted(talk, key=lambda s: (-talk[s], int(s[1:])))
    body = [fm({"recording_id": rec["id"], "date": rec["date"], "duration": rec["duration"],
                "language": rec.get("language"), "model": rec.get("model"),
                "speakers": [speaker_name(rec, s) for s in spk_ids], "tags": ["plaud"]}),
            f"# {rec['title']}\n", f"![[{stem}.ogg]]\n", f"- [[{stem} - Transcript]]"]
    for note in rec["notes"]:
        file = note["file"]
        if (rec["_dir"] / file).is_file():
            body.append(f"- [[{file[:-3]}]]")
        else:
            body.append(f"- (missing: {file})")
            logging.getLogger(__name__).warning("Missing note: %s", rec["_dir"] / file)
    if marks:
        body += ["\n## Highlights and memos"] + [
            f"- `{mmss(m['t'])}` {ICON[m['kind']]} {m['text'] or m['kind']}" for m in marks]
    text = "\n".join(body) + f"\n\n{KEEP}{tail}"
    hub.write_text(text, encoding="utf-8")
    save(rec)


def add_note(rec: dict, title: str, text: str) -> str:
    """Write a generated note; never overwrites an existing one."""
    writable(rec)
    # only the title is cleaned: cutting the whole name to safe()'s length gave back the bare
    # stem (the hub note) for long titles, and this loop then never ended
    base, n = f"{rec['stem']} - {safe(title)}", 1
    name = base
    while (rec["_dir"] / f"{name}.md").exists():
        n += 1
        name = f"{base} {n}"
    _write_owned(rec, f"{name}.md", text)
    return name


# ---------- first-run content ----------

SEED = {
    "_Glossary.md": "> Terms that should always be recognised, one per line (names, tools, acronyms).\n"
                    "> A folder can have its own `Glossary.md` for its topic.\n\n",
}
# Default blueprints ship as files in app/blueprints; seed() adds missing ones, never overwrites.
SEED.update({f"_Blueprints/{p.name}": p.read_text(encoding="utf-8")
             for p in sorted((Path(__file__).parent / "blueprints").glob("*.md"))})


def seed() -> None:
    groups()
    for rel, text in SEED.items():
        p = BASE / rel
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
