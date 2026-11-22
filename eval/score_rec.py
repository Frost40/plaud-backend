"""Score an imported recording's speakers against Plaud's labels, per second.

usage: eval/score_rec.py <recording.json> <plaud.txt>
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval import metrics, plaud_labels


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: eval/score_rec.py <recording.json> <plaud.txt>")
    rec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    utts = rec["utterances"]
    n = int(max(u["e"] for u in utts)) + 2
    theirs = plaud_labels.per_second(sys.argv[2], n)
    ours: list[str | int | None] = [None] * n
    for u in utts:
        for i in range(int(u["s"]), min(int(u["e"]) + 1, n)):
            ours[i] = u["spk"]

    conf: dict[str, Counter] = defaultdict(Counter)
    for o, t in zip(ours, theirs):
        if o is not None and t is not None:
            conf[t][o] += 1
    agree, total, mapping = metrics.match_confusion(conf)

    diar_engine = (rec.get("diarization") or {}).get("engine")
    engine = rec.get("speaker_engine") or diar_engine
    print(f"engine {engine}, language {rec.get('language')}, our speakers {len({u['spk'] for u in utts})}, "
          f"Plaud labels {len(conf)}, agreement {agree / max(total, 1) * 100:.1f}% of {total} s")
    ospk = sorted({o for row in conf.values() for o in row})
    label = lambda spk: spk if isinstance(spk, str) else f"S{spk + 1}"
    print(f"{'Plaud label (seconds)':34}" + "".join(f"{label(o):>6}" for o in ospk) + "   matched to")
    for t, row in sorted(conf.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"{t[:28]:28}{sum(row.values()):6}" + "".join(f"{row.get(o, 0):6}" for o in ospk)
              + (f"   {label(mapping[t])}" if t in mapping else "   -"))


if __name__ == "__main__":
    main()
