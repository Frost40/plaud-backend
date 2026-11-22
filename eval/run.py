"""Score a recording.json against a Plaud transcript file (proxy, not ground truth).

usage: eval/run.py <recording.json> [plaud.txt]
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval import metrics, plaud_labels


def _find_plaud(rec_id: str) -> Path | None:
    eval_dir = ROOT / "data" / "speaker-eval"
    if not eval_dir.is_dir():
        return None
    matches = [p for p in sorted(eval_dir.glob("*.plaud.txt")) if rec_id.startswith(p.name.split(".", 1)[0])]
    return matches[0] if len(matches) == 1 else None


def _target(speakers: dict, spk: str) -> str:
    seen = set()
    while spk in speakers and spk not in seen and speakers[spk].get("merged_into"):
        seen.add(spk)
        spk = speakers[spk]["merged_into"]
    return spk


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not 1 <= len(args) <= 2:
        sys.exit("usage: eval/run.py <recording.json> [plaud.txt]")
    rec_path = Path(args[0])
    if not rec_path.is_file():
        sys.exit(f"recording file not found: {rec_path}")
    try:
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"cannot read recording {rec_path}: {exc}")

    rec_id = rec.get("id", "")
    if len(args) == 2:
        plaud_path = Path(args[1])
        if not plaud_path.is_file():
            sys.exit(f"no matching Plaud file: {plaud_path}")
        if plaud_path.name.startswith("of_") and not rec_id.startswith(plaud_path.name.split(".", 1)[0]):
            sys.exit(f"no matching Plaud file: {plaud_path.name} does not match {rec_id}")
    else:
        plaud_path = _find_plaud(rec_id)
        if plaud_path is None:
            sys.exit(f"no matching Plaud file for {rec_id or rec_path.name}")

    segs = plaud_labels.load(plaud_path)
    if not segs:
        sys.exit(f"no Plaud labels found in {plaud_path}")

    ref_words = [{"w": tok, "spk": seg["spk"]} for seg in segs for tok in metrics.normalise(seg["text"]).split()]
    words = rec.get("words") or []
    speakers_map = rec.get("speakers") or {}
    turns = [[s, e, _target(speakers_map, k)] for s, e, k in (rec.get("diarization") or {}).get("turns", [])]
    utts = rec.get("utterances") or []
    hyp_words = [w | {"spk": metrics.speaker_at(utts, (w["s"] + w["e"]) / 2)} for w in words]

    wer_val = metrics.wer(ref_words, words)
    attr_val = metrics.attribution_error(ref_words, hyp_words)
    loss_val = metrics.assignment_loss(ref_words, words, turns, utts) if turns else 0.0
    found_spk = len({u["spk"] for u in utts}) if utts else len({t[2] for t in turns})
    ref_spk = rec.get("true_speakers") if rec.get("true_speakers") is not None else len({s["spk"] for s in segs})
    cnt_err = metrics.count_error(found_spk, ref_spk)

    model = (rec.get("transcript") or {}).get("model") or rec.get("model")
    engine = rec.get("speaker_engine") or (rec.get("diarization") or {}).get("engine")
    print(f"recording: {rec.get('title')} ({rec_id}) | model: {model} | engine: {engine}")
    print(f"wer: {wer_val * 100:.2f}%")
    print(f"attribution_error: {attr_val * 100:.2f}%")
    print(f"assignment_loss: {loss_val * 100:+.2f}%")
    print(f"count_error: {cnt_err} (found {found_spk}, ref {ref_spk})")

    out_path = ROOT / "data" / "eval" / "results.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "date": dt.datetime.now().isoformat(timespec="seconds"),
        "recording": rec_id,
        "title": rec.get("title"),
        "model": model,
        "engine": engine,
        "wer": round(wer_val, 6),
        "attribution_error": round(attr_val, 6),
        "assignment_loss": round(loss_val, 6),
        "count_error": cnt_err,
        "found_speakers": found_spk,
        "ref_speakers": ref_spk,
        "count_source": "true_speakers" if rec.get("true_speakers") is not None else "plaud_labels",
    }
    with out_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
