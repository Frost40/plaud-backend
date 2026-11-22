"""Pure evaluation metrics: WER, speaker attribution error, assignment loss, count error."""
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher


def normalise(text: str) -> str:
    """Lowercase, strip punctuation, leave numbers as written."""
    return " ".join(re.sub(r"[^\w\s]|_", " ", re.sub(r"['’`]", "", text.lower())).split())


def _token_text(item) -> str:
    return normalise(item["w"] if isinstance(item, dict) else str(item))


def _expand(items) -> list[dict]:
    if isinstance(items, str):
        return [{"w": tok} for tok in normalise(items).split()]
    out = []
    for item in items:
        base = item if isinstance(item, dict) else {"w": str(item)}
        for tok in normalise(base.get("w", "")).split():
            out.append(base | {"w": tok})
    return out


def align(ref_words, hyp_words) -> list[tuple[int, int]]:
    """Return matched index pairs (ref_idx, hyp_idx) on normalised word tokens."""
    r = [_token_text(w) for w in ref_words]
    h = [_token_text(w) for w in hyp_words]
    blocks = SequenceMatcher(None, r, h, autojunk=False).get_matching_blocks()
    return [(a + k, b + k) for a, b, n in blocks for k in range(n) if r[a + k]]


def wer(ref, hyp) -> float:
    """Word error rate on normalised tokens."""
    r = [w["w"] for w in _expand(ref)]
    h = [w["w"] for w in _expand(hyp)]
    if not r:
        return 0.0 if not h else 1.0
    opcodes = SequenceMatcher(None, r, h, autojunk=False).get_opcodes()
    edits = sum(max(j - i, b - a) for tag, i, j, a, b in opcodes if tag != "equal")
    return edits / len(r)


def match_confusion(conf: dict[str, Counter]) -> tuple[int, int, dict]:
    """Greedy one-to-one mapping maximising agreed count; returns (agree, total, ref->hyp map)."""
    total = sum(sum(c.values()) for c in conf.values())
    used_r, used_h, agree, mapping = set(), set(), 0, {}
    for c, r_spk, h_spk in sorted(
        ((c, r_spk, h_spk) for r_spk, row in conf.items() for h_spk, c in row.items()),
        reverse=True,
    ):
        if r_spk not in used_r and h_spk not in used_h:
            used_r.add(r_spk)
            used_h.add(h_spk)
            agree += c
            mapping[r_spk] = h_spk
    return agree, total, mapping


def speaker_at(spans, t: float) -> str | None:
    """Speaker covering timestamp t, falling back to nearest span when slightly between turns."""
    if not spans:
        return None
    best, best_dist = None, float("inf")
    for span in spans:
        s, e, spk = (span["s"], span["e"], span["spk"]) if isinstance(span, dict) else span[:3]
        if s <= t <= e:
            return spk
        dist = max(0.0, s - t, t - e)
        if dist < best_dist:
            best, best_dist = spk, dist
    return best


def attribution_error(ref_words, hyp_words) -> float:
    """Share of aligned words assigned to the wrong speaker under best 1-to-1 speaker map."""
    ref = _expand(ref_words)
    hyp = _expand(hyp_words)
    conf: dict[str, Counter] = defaultdict(Counter)
    for ri, hi in align(ref, hyp):
        r_spk, h_spk = ref[ri].get("spk"), hyp[hi].get("spk")
        if r_spk is not None and h_spk is not None:
            conf[r_spk][h_spk] += 1
    agree, total, _ = match_confusion(conf)
    return 0.0 if not total else 1.0 - agree / total


def assignment_loss(ref_words, words, turns, utterances) -> float:
    """Attribution error delta caused by grouping words into utterances vs raw exclusive turns."""
    turn_words = [w | {"spk": speaker_at(turns, (w["s"] + w["e"]) / 2)} for w in words]
    utt_words = [w | {"spk": speaker_at(utterances, (w["s"] + w["e"]) / 2)} for w in words]
    return attribution_error(ref_words, utt_words) - attribution_error(ref_words, turn_words)


def _count(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    items = list(value)
    if items and isinstance(items[0], dict):
        return len({x["spk"] for x in items})
    if items and isinstance(items[0], (list, tuple)):
        return len({x[2] for x in items})
    return len(set(items))


def count_error(found, true) -> int | None:
    """Absolute speaker count difference, or None when true count is unknown."""
    f, t = _count(found), _count(true)
    return None if f is None or t is None else abs(f - t)
