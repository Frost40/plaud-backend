"""Score pyannote on the same full recordings as merge_eval.py (agreement with Plaud's labels).

usage: eval/pyannote_eval.py <name=audio=plaud.txt=k> ...
"""
import json
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import speech
from eval import merge_eval as me


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: eval/pyannote_eval.py <name=audio=plaud.txt=k> ...")
    for item in sys.argv[1:]:
        name, audio_path, plaud_path, k = item.split("=")
        audio = speech.load_audio(Path(audio_path))
        theirs = me.plaud(plaud_path, int(len(audio) / 16000))
        print(f"\n== {name}: {len(audio)/16000/60:.0f} min; Plaud {[round(v/60,1) for _, v in Counter(x for x in theirs if x).most_common()]}", flush=True)
        with tempfile.TemporaryDirectory() as tmp:
            np.save(f"{tmp}/a.npy", audio)
            for count in (0, int(k)):
                t0 = time.time()
                r = subprocess.run(
                    [str(ROOT / ".venv-pyannote/Scripts/python.exe"), str(ROOT / "app/pyannote_worker.py"),
                     f"{tmp}/a.npy", f"{tmp}/o.json"] + ([str(count)] if count else []),
                    capture_output=True, text=True,
                )
                if r.returncode:
                    print("   FAILED:", r.stderr[-600:])
                    break
                raw = json.loads(Path(f"{tmp}/o.json").read_text(encoding="utf-8"))
                turns = [tuple(t) for t in (raw["turns"] if isinstance(raw, dict) else raw)]
                tidy = speech.tidy_turns(turns, keep_all=bool(count))
                print(f"   {'auto' if not count else f'k={count}'}: {len({t[2] for t in turns})} speakers raw, "
                      f"{len({t[2] for t in tidy})} after tidy {me.talk(tidy)} agreement {me.score(tidy, theirs)*100:.0f}% "
                      f"in {time.time()-t0:.0f}s (incl. model load)", flush=True)


if __name__ == "__main__":
    main()
