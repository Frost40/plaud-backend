"""Cache raw sherpa turns + voice prints per full recording, then score merge settings vs Plaud's labels.

usage: eval/merge_eval.py <cmp_dir> <name=audio=plaud.txt=k> ...
"""
import pickle
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import speech
from eval import metrics, plaud_labels


def plaud(path, n):
    return plaud_labels.per_second(path, n)


def score(turns, theirs):
    ours = [None] * len(theirs)
    for s, e, spk in turns:
        for i in range(int(s), min(int(e) + 1, len(ours))):
            ours[i] = spk
    conf = defaultdict(Counter)
    for o, t in zip(ours, theirs):
        if o is not None and t is not None:
            conf[t][o] += 1
    agree, total, _ = metrics.match_confusion(conf)
    return agree / max(total, 1)


def talk(turns):
    d = Counter()
    for s, e, spk in turns:
        d[spk] += e - s
    return [round(v / 60, 1) for _, v in d.most_common()]


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit("usage: eval/merge_eval.py <cmp_dir> <name=audio=plaud.txt=k> ...")
    cmp_dir = Path(sys.argv[1])
    for spec in sys.argv[2:]:
        name, audio_path, plaud_path, k = spec.split("=")
        cache = cmp_dir / f"{name}.rawturns.pkl"
        if not cache.exists():
            audio = speech.load_audio(Path(audio_path))
            t0 = time.time()
            turns = speech.raw_turns(audio)
            t1 = time.time()
            prints = speech.voice_prints(audio, turns)
            with cache.open("wb") as fh:
                pickle.dump((turns, prints, len(audio) / 16000, t1 - t0, time.time() - t1), fh)
        with cache.open("rb") as fh:
            turns, prints, dur, t_seg, t_emb = pickle.load(fh)
        theirs = plaud(plaud_path, int(dur))
        pl = Counter(x for x in theirs if x)
        print(f"\n== {name}: {dur/60:.0f} min, sherpa {t_seg:.0f}s + prints {t_emb:.0f}s; raw clusters {len(prints)}; "
              f"Plaud {[round(v/60,1) for _, v in pl.most_common()]}", flush=True)
        print(f"   raw      -> {len(set(t[2] for t in speech.tidy_turns(turns)))} speakers after tidy, agreement {score(turns, theirs)*100:.0f}%")
        for same in (0.75, 0.78, 0.80, 0.82, 0.85, 0.88):
            m = speech.tidy_turns(speech.merge_voices(turns, prints, same))
            print(f"   auto {same} -> {len(set(t[2] for t in m))} speakers {talk(m)} agreement {score(m, theirs)*100:.0f}%")
        m = speech.tidy_turns(speech.merge_voices(turns, prints, 0.82, int(k)), keep_all=True)
        print(f"   fixed k={k} -> {talk(m)} agreement {score(m, theirs)*100:.0f}%", flush=True)


if __name__ == "__main__":
    main()
