"""Check first-half voice templates against the second half of the sandbox recording."""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import speech, vault, voices
from app.config import ROOT
from eval import plaud_labels

STAGE = {"Steve Jobs", "Bill Gates", "Walt Mossberg", "Kara Swisher"}
SANDBOX = ROOT / "data/sandbox"
RATE = 16000
SPLIT = 40 * 60


def labelled(data, labels, offset):
    shared = defaultdict(Counter)
    for start, end, spk in data["turns"]:
        shared[spk].update(label for label in labels[offset + round(start):offset + round(end)] if label)
    return {spk: counts.most_common(1)[0][0] for spk, counts in shared.items() if counts}


def main():
    vault.BASE = Path(json.loads((SANDBOX / "config.json").read_bytes())["vault"]) / "Plaud"
    if not vault.BASE.resolve().is_relative_to(SANDBOX.resolve()):
        raise ValueError("Expected a sandbox vault")
    rec = vault.find("of_8a437ab8b8c5a3b75c07c8889272bc32")
    audio = speech.load_audio(rec["_dir"] / f"{rec['stem']}.ogg")
    labels = plaud_labels.per_second(ROOT / "data/speaker-eval/of_8a43.plaud.txt", len(audio) // RATE + 1)
    first, second = [speech.diarize(part, log=lambda msg: print(msg, flush=True))
                     for part in (audio[:SPLIT * RATE], audio[SPLIT * RATE:])]
    if first["engine"] != second["engine"]:
        raise RuntimeError("The two halves used different embedding engines")
    names = labelled(first, labels, 0)
    templates = {name: first["embeddings"][k] for k, name in names.items() if name in STAGE}
    if set(templates) != STAGE:
        raise RuntimeError(f"Expected all four on-stage templates, found {sorted(templates)}")
    cutoff = max(voices._best(vector, {k: v for k, v in templates.items() if k != name})[0]
                 for name, vector in templates.items())
    speakers = {k: {"name": ""} for k in second["embeddings"]}
    suggestions = voices.match({"speakers": speakers, "diarization": second}, templates, cutoff)
    truth = labelled(second, labels, SPLIT)
    print(f"Engine {first['engine']}, first-half impostor cutoff {cutoff:.6f}")
    print("| Speaker | Plaud name | Best match | Cosine | Suggested |\n|---|---|---|---:|---|")
    for k, vector in second["embeddings"].items():
        score, best = voices._best(vector, templates)
        print(f"| {k} | {truth.get(k, 'Unlabelled')} | {best} | {score:.6f} | "
              f"{suggestions.get(k, {}).get('name', '')} |")
    correct = {s["name"] for k, s in suggestions.items() if truth.get(k) == s["name"]}
    wrong = [s["score"] for k, s in suggestions.items() if truth.get(k) != s["name"]]
    print(f"{len(correct)}/4 correct, {len(wrong)} wrong, max wrong {max(wrong, default=None)}")


if __name__ == "__main__":
    main()
