"""Thin wrapper over Plaud's official CLI (`npm i -g @plaud-ai/cli`, then `plaud login`).

We shell out instead of calling the API: the CLI owns OAuth refresh, and Plaud's
Cloudflare rejects non-CLI clients. ponytail: parses human-readable output; if a CLI
update changes the layout, fix the regexes here.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import httpx

ID_RE = re.compile(r"^of_[0-9a-f]{32}$")
_ROW = re.compile(r"^\s*(of_[0-9a-f]{32})\s{2,}(.*?)\s{2,}(\d{4}-\d{2}-\d{2})\s{2,}(\S+)\s*$")


def _run(*args: str) -> str:
    exe = shutil.which("plaud")
    if not exe:
        raise RuntimeError("Plaud CLI not found. Install with: npm install -g @plaud-ai/cli")
    res = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=120,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                         env={**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0"})
    out = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", res.stdout + res.stderr)  # strip ANSI colour codes
    if "AUTH_FAILED" in out:
        raise RuntimeError("Plaud sign-in expired. Run `plaud login` in a terminal.")
    if res.returncode:
        raise RuntimeError(out.strip() or f"Plaud exited with code {res.returncode}")
    return out


def _check(rec_id: str) -> str:
    if not ID_RE.match(rec_id):
        raise ValueError(f"bad recording id: {rec_id!r}")
    return rec_id


def parse_list(text: str) -> list[dict]:
    return [{"id": m[1], "title": m[2].strip(), "date": m[3], "duration": m[4]}
            for m in map(_ROW.match, text.splitlines()) if m]


def me() -> str:
    return _run("me")


def list_recordings(date_from: str | None = None) -> list[dict]:
    rows, page = [], 1
    while True:
        batch = parse_list(_run("files", "-s", "100", "-p", str(page),
                                *(["--date-from", date_from] if date_from else [])))
        rows.extend(batch)
        if len(batch) < 100:
            return rows
        page += 1


def details(rec_id: str) -> dict:
    """Full title (the listing truncates long ones), start time, and Plaud transcript/summary flags."""
    out = _run("file", _check(rec_id))
    name = re.search(r"^\s*name:\s+(.+?)\s*$", out, re.M)
    start = re.search(r"^\s*start_at:\s+(\S+)", out, re.M)
    tr = re.search(r"^\s*transcript:\s+(\S+)", out, re.M)
    su = re.search(r"^\s*summary:\s+(\S+)", out, re.M)
    return {
        "title": name[1] if name else "",
        "start_at": start[1] if start else "",
        "has_transcript": bool(tr and tr[1].lower() == "available"),
        "has_summary": bool(su and su[1].lower() == "available"),
    }


def download_audio(rec_id: str, dest: Path, on_progress=None) -> Path:
    m = re.search(r"https://\S+", _run("audio", _check(rec_id)))
    if not m:
        raise RuntimeError("Plaud returned no audio link for this recording.")
    partial = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", m[0], timeout=300, follow_redirects=True) as r:
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Audio download failed (HTTP {exc.response.status_code})") from None
        size, got = (int(r.headers.get("content-length") or 0) if on_progress else 0), 0
        with open(partial, "wb") as f:
            for chunk in r.iter_bytes(1 << 16):
                f.write(chunk)
                got += len(chunk)
                if on_progress and size:
                    on_progress(got / size)
    if partial.stat().st_size == 0:
        raise RuntimeError("Downloaded audio is empty.")
    partial.replace(dest)
    return dest


_KIND = {1: "highlight", 4: "highlight", 3: "memo", 2: "photo"}


def marks(rec_id: str, tmp: Path) -> list[dict]:
    """Button highlights, typed memos and photo markers: [{t (seconds), kind, text}]."""
    tmp.unlink(missing_ok=True)
    _run("transcript", _check(rec_id), "--highlights", "-o", str(tmp))
    if not tmp.exists():
        return []
    raw = json.loads(tmp.read_text(encoding="utf-8"))
    tmp.unlink()
    out = []
    for m in raw if isinstance(raw, list) else []:
        text = (m.get("mark_content") or "").strip()
        if m.get("mark_type") == 4 and m.get("mark_status") == 0:
            text = ""  # Plaud's "available after transcription" placeholder
        out.append({"t": (m.get("timestamp") or 0) / 1000, "kind": _KIND.get(m.get("mark_type"), "highlight"),
                    "text": text})
    return sorted(out, key=lambda x: x["t"])


_TR_LINE = re.compile(r"^\[([\d:]+)(?:\s*-\s*([\d:]+))?\]\s*([^:]{1,80}):\s*(.*)$")


def _secs(timestamp: str) -> float:
    return float(sum(int(x) * 60 ** i for i, x in enumerate(reversed(timestamp.split(":")))))


def parse_transcript(text: str) -> list[dict]:
    """Parse Plaud transcript lines (`[mm:ss - mm:ss] Speaker: text`) into segments."""
    out: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _TR_LINE.match(line)
        if m:
            s = _secs(m.group(1))
            e = max(_secs(m.group(2)) if m.group(2) else s, s + 0.1)
            out.append({"s": s, "e": e, "speaker": m.group(3).strip(), "text": m.group(4).strip()})
        elif out and not line.startswith(("Transcript:", "- Fetching")):
            out[-1]["text"] = (out[-1]["text"] + " " + line).strip()
    return [seg for seg in out if seg["text"]]


def transcript(rec_id: str, tmp: Path) -> tuple[list[dict], bool]:
    """Download Plaud's transcript (prefers --polished for speaker names, falls back to raw)."""
    rec_id = _check(rec_id)
    for polished, extra in ((True, ["--polished"]), (False, [])):
        tmp.unlink(missing_ok=True)
        try:
            out = _run("transcript", rec_id, *extra, "-o", str(tmp))
        except RuntimeError as exc:
            if "sign-in expired" in str(exc).lower() or not polished:
                raise
            continue
        raw = tmp.read_text(encoding="utf-8", errors="replace") if tmp.exists() else out
        tmp.unlink(missing_ok=True)
        segs = parse_transcript(raw)
        if segs:
            return segs, polished
    return [], False


def _clean_summary(content: str) -> str:
    content = re.sub(r"<mark\b[^>]*>(.*?)</mark>", r"==\1==", content, flags=re.S | re.I)
    content = re.sub(r"\n*## Related Photos\s*\n+(?:\[\]\(plaud://[^)]+\)\s*)+$", "", content)
    content = re.sub(r"\[\]\(plaud://[^)]+\)", "", content)
    return content.strip()


def summaries(rec_id: str, tmp: Path) -> list[dict]:
    """Download Plaud's generated notes/summaries as [{title, type, content}]."""
    rec_id = _check(rec_id)
    tmp.unlink(missing_ok=True)
    out = _run("summary", rec_id, "--json", "-o", str(tmp))
    if tmp.exists():
        raw_text = tmp.read_text(encoding="utf-8", errors="replace")
        tmp.unlink(missing_ok=True)
    else:
        idx = out.find("[")
        raw_text = out[idx:] if idx >= 0 else "[]"
    try:
        items = json.loads(raw_text)
    except ValueError:
        return []
    notes = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        content = _clean_summary(item.get("data_content") or "")
        if not content:
            continue
        title = (item.get("data_tab_name") or item.get("data_title") or "Summary").strip()
        notes.append({"title": title, "type": str(item.get("data_type") or ""), "content": content})
    return notes
