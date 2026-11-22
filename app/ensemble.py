"""Fuse two transcripts of the same audio: an LLM picks, 30 s at a time, between the candidates.

Guard: a fused segment may only contain words present in a candidate (same or neighbouring
segment) or in the glossary, and must be of similar length; otherwise the first candidate's
raw text is kept. So the LLM can choose and drop, never invent.
"""
import re
from collections import Counter
from difflib import SequenceMatcher

from app import llm
from app.config import cfg

WIN, BATCH = 30, 20  # seconds per segment, segments per LLM call


def norm(text: str) -> list[str]:
    return re.findall(r"[a-zà-ÿ0-9]+", text.lower())


PROMPT = """You are fixing an automatic transcript of a recorded conversation. It may mix languages (often Italian with English technical terms); keep each word in the language it was spoken.
Each numbered segment below shows the same 30 seconds of audio as transcribed by {n} speech recognisers, labelled {labels}. They make different mistakes; none is always right.

For every segment write the words most likely spoken:
- Decide word by word, using the meaning of the surrounding conversation and the glossary.
- You may ONLY use words that appear in a candidate for that segment or in the glossary. Never paraphrase, summarise, translate, add or drop content.
- Keep filler and repetitions only if most candidates have them.

Glossary: {glossary}

Output exactly one line per segment, in order, formatted as:  <number>|<text>
No other text.

{segments}"""


def _windows(words: list[dict], n: int) -> list[str]:
    out = [[] for _ in range(n)]
    for w in words:
        out[min(int(w["s"] // WIN), n - 1)].append(w["w"])
    return ["".join(x).strip() for x in out]


def retime(text: str, ref: list[dict], t0: float) -> list[dict]:
    """Give the fused words timestamps by aligning them to the reference words of that segment."""
    toks = text.split()
    times: list[tuple[float, float] | None] = [None] * len(toks)
    a, b = [" ".join(norm(w["w"])) for w in ref], [" ".join(norm(t)) for t in toks]
    for blk in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            times[blk.b + k] = (ref[blk.a + k]["s"], ref[blk.a + k]["e"])
    out, last = [], t0
    for tok, t in zip(toks, times):
        s, e = t or (last, last + 0.01)  # unmatched word: sits right after the previous one
        out.append({"s": s, "e": e, "w": " " + tok})
        last = e
    return out


def common_words(language):
    from app import vault
    counts = Counter(w for rec in vault.scan() if rec.get("language") == language
                     for word in rec["words"] for w in norm(word["w"]))
    # ponytail: top 100 vault words approximate common vocabulary; tune with a larger labelled corpus.
    return {w for w, _ in counts.most_common(100)}


def fuse(cands: list[list[dict]], glossary: list[str], provider: str | None = None, log=lambda m: None, common=frozenset()) -> tuple[list[dict], dict, list]:
    """cands[0] is the reference (its timestamps and raw text are the fallback).
    Returns fused words, rejection counts by reason, and glossary candidates."""
    provider = provider or cfg["arbiter_provider"] or cfg["default_provider"]
    labels = "ABCDE"[: len(cands)]
    n = int(max(w["e"] for c in cands for w in c) // WIN) + 1
    wins = [_windows(c, n) for c in cands]
    gloss = set(norm(" ".join(glossary)))
    candidates = []
    words: list[dict] = []
    rejected: dict[str, int] = {}
    for start in range(0, n, BATCH):
        idx = range(start, min(start + BATCH, n))
        log(f"arbitrating between models with {provider} ({start + 1}-{idx[-1] + 1} of {n} segments)")
        if on_progress := getattr(log, "progress", None):
            on_progress(start / n)
        segs = "\n\n".join(f"#{i + 1}\n" + "\n".join(f"{l}: {wins[k][i]}" for k, l in enumerate(labels)) for i in idx)
        try:
            out = llm.run(provider, PROMPT.format(n=len(cands), labels=", ".join(labels),
                                                  glossary=", ".join(glossary) or "(none)", segments=segs))
        except Exception:
            out = ""  # provider failed: this batch keeps the reference transcript
        got = {int(m[1]): m[2].strip() for m in re.finditer(r"^#?(\d+)\|(.*)$", out, re.M)}
        for i in idx:
            ref = [w for w in cands[0] if min(int(w["s"] // WIN), n - 1) == i]
            raw, text = wins[0][i], got.get(i + 1)
            allowed = gloss | {w for win in wins for j in (i - 1, i, i + 1) if 0 <= j < n for w in norm(win[j])}
            why = ("no answer" if text is None else
                   "invented words" if any(w not in allowed for w in norm(text)) else
                   "length changed" if not 0.6 <= (len(norm(text)) + 1) / (len(norm(raw)) + 1) <= 1.5 else None)
            if why:
                words += ref
                rejected[why] = rejected.get(why, 0) + 1
            else:
                words += retime(text, ref, i * WIN)
                tokens = re.findall(r"[^\W_]+", text)
                second = set(norm(wins[1][i]))
                for tag, _, _, a, b in SequenceMatcher(None, norm(raw), [w.lower() for w in tokens]).get_opcodes():
                    if tag != "equal":
                        candidates.extend(w for w in tokens[a:b] if w.lower() in second
                                          and (w[:1].isupper() or w.lower() not in common))
    return words, rejected, candidates
