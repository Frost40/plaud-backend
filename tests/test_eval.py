import json
import subprocess
import sys
from pathlib import Path

import pytest

from eval import metrics, plaud_labels


ROOT = Path(__file__).resolve().parents[1]


def test_wer_normalisation():
    assert metrics.normalise("Don't stop, L'acqua è 42!") == "dont stop lacqua è 42"
    assert metrics.normalise("Hello-world; test.") == "hello world test"
    assert metrics.wer("Don't stop, L'acqua è 42!", "dont stop lacqua è 42") == 0.0
    assert metrics.wer("one two three four", "one TWO five four.") == pytest.approx(0.25)


def test_attribution_error_on_synthetic_words():
    ref = [{"w": f"w{i}", "spk": "A" if i < 5 else "B"} for i in range(10)]
    hyp = [{"w": f"w{i}", "spk": "S2" if i < 7 else "S1"} for i in range(10)]
    # Best greedy 1-to-1 map: A->S2 (5), B->S1 (3); 2 words (w5, w6) misattributed -> 2/10 = 0.2.
    assert metrics.attribution_error(ref, hyp) == pytest.approx(0.2)


def test_assignment_loss_zero_when_turns_equal_utterances():
    words = [{"s": float(i), "e": i + 0.8, "w": f" w{i}"} for i in range(6)]
    ref_words = [{"w": f"w{i}", "spk": "A" if i < 3 else "B"} for i in range(6)]
    turns = [[0.0, 2.9, "S1"], [3.0, 5.9, "S2"]]
    same_utts = [{"s": 0.0, "e": 2.9, "spk": "S1"}, {"s": 3.0, "e": 5.9, "spk": "S2"}]
    assert metrics.assignment_loss(ref_words, words, turns, same_utts) == 0.0

    # Merging turn S2 into S1's utterance moves words 3..5 away from S2 -> positive assignment loss.
    merged_utts = [{"s": 0.0, "e": 5.9, "spk": "S1"}]
    assert metrics.assignment_loss(ref_words, words, turns, merged_utts) == pytest.approx(0.5)


def test_count_error():
    assert metrics.count_error(3, 3) == 0
    assert metrics.count_error(9, 10) == 1
    assert metrics.count_error(2, 5) == 3
    assert metrics.count_error(["S1", "S2"], 4) == 2
    assert metrics.count_error(3, None) is None


def test_plaud_label_lines_parsed(tmp_path):
    sample = (
        "[00:00 - 00:37] Speaker 1: First sentence.\n"
        "[01:05] Speaker 2: Single timestamp reply.\n"
        "[1:02:03 - 1:02:10] Kara Swisher: Hour mark.\n"
    )
    segs = plaud_labels.parse_lines(sample)
    assert segs == [
        {"s": 0, "e": 37, "spk": "Speaker 1", "text": "First sentence."},
        {"s": 65, "e": 66, "spk": "Speaker 2", "text": "Single timestamp reply."},
        {"s": 3723, "e": 3730, "spk": "Kara Swisher", "text": "Hour mark."},
    ]
    labels = plaud_labels.per_second(segs, 70)
    assert labels[0] == "Speaker 1" and labels[36] == "Speaker 1" and labels[37] is None
    assert labels[65] == "Speaker 2" and labels[66] is None

    rec_file = tmp_path / "recording.json"
    rec_file.write_text(json.dumps({"id": "of_" + "a" * 32, "words": [], "utterances": [], "diarization": {"turns": []}}), encoding="utf-8")
    res = subprocess.run([sys.executable, str(ROOT / "eval/run.py"), str(rec_file)], capture_output=True, text=True)
    assert res.returncode != 0
    assert "Traceback" not in res.stderr and "Traceback" not in res.stdout
    assert "no matching Plaud file" in (res.stderr + res.stdout)
