"""Speaker turns with pyannote (GPU). Runs in its own environment (.venv-pyannote), started by
app.speech, because pyannote needs PyTorch and the main environment does not.

usage: pyannote_worker.py <audio.npy: 16 kHz mono float32> <out.json> [number of speakers]
"""
import json
import sys

import numpy as np
import torch
from pyannote.audio import Pipeline

MODEL = "pyannote/speaker-diarization-community-1"  # gated: needs `hf auth login` and accepted terms

audio = np.load(sys.argv[1])
k = int(sys.argv[3]) if len(sys.argv) > 3 else 0
if torch.cuda.is_available():
    # Without a cap, cuDNN picks a voice-embedding method needing ~9 GiB on this 8 GiB card; Windows
    # spills the rest into RAM, so a 30 min recording ran for hours and froze the desktop. Capped, it
    # picks a lean method that is just as fast (measured: 0.7 GiB, 58 s for 30 min).
    torch.cuda.set_per_process_memory_fraction(0.4)
pipe =Pipeline.from_pretrained(MODEL).to(torch.device("cuda" if torch.cuda.is_available() else "cpu"))
# The model defaults to 32 windows per batch, which crowds the desktop on an 8 GiB GPU.
pipe.segmentation_batch_size = pipe.embedding_batch_size = 8
# ponytail: share of the run per step is a guess (embeddings dominate); measure it if the bar jumps
SPAN = {"segmentation": (0.0, 0.2), "embeddings": (0.2, 1.0)}
def hook(step, _artefact, file=None, completed=None, total=None):
    if step in SPAN and completed is not None and total:
        a, b = SPAN[step]
        print(f"progress {a + (b - a) * min(completed, total) / total:.3f}", flush=True)   # read by app.speech
out = pipe({"waveform": torch.from_numpy(audio)[None], "sample_rate": 16000}, hook=hook,
           **({"num_speakers": k} if k else {}))
# Embedding rows follow these labels, not first appearance or talk-time rank.
labels = out.speaker_diarization.labels()
ids = {label: i for i, label in enumerate(labels)}
def turns(annotation):
    return [[round(seg.start, 2), round(seg.end, 2), ids[label]]
            for seg, _, label in annotation.itertracks(yield_label=True)]
with open(sys.argv[2], "w", encoding="utf-8") as target:
    json.dump({"labels": labels, "turns": turns(out.exclusive_speaker_diarization),
               "overlap_turns": turns(out.speaker_diarization),
               "embeddings": out.speaker_embeddings.tolist()}, target, allow_nan=False)
