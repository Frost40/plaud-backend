"""Parse Plaud transcript exports (`[mm:ss - mm:ss] Name: text`)."""
import re
from pathlib import Path

LINE_RE = re.compile(r"\[([\d:]+)(?: - ([\d:]+))?\]\s*([^:]{1,40}):\s*(.*)")


def secs(timestamp: str) -> int:
    return sum(int(x) * 60 ** i for i, x in enumerate(reversed(timestamp.split(":"))))


def parse_lines(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        m = LINE_RE.match(line)
        if m:
            s = secs(m.group(1))
            e = max(secs(m.group(2) or m.group(1)), s + 1)
            out.append({"s": s, "e": e, "spk": m.group(3), "text": m.group(4)})
    return out


def load(path: str | Path) -> list[dict]:
    return parse_lines(Path(path).read_text(encoding="utf-8"))


def per_second(segments_or_path, n: int) -> list[str | None]:
    segs = load(segments_or_path) if isinstance(segments_or_path, (str, Path)) else segments_or_path
    labels: list[str | None] = [None] * n
    for seg in segs:
        for i in range(seg["s"], min(seg["e"], n)):
            labels[i] = seg["spk"]
    return labels
