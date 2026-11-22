import copy
import json
from pathlib import Path

import numpy as np
import pytest

from app import pipeline, speech, vault


def test_long_whisper_features_match_reference_in_bounded_blocks(monkeypatch):
    reference = speech.FeatureExtractor(feature_size=128)
    bounded = speech._BlockFeatures(feature_size=128)
    audio = np.random.default_rng(12).normal(size=16000 * 61 + 79).astype(np.float32)
    audio[:16000 * 30] *= 1e-6  # Quiet first block must use the loud second block's clipping level.
    lengths = []
    def stft(block, *args, **kwargs):
        lengths.append(len(block))
        return reference.stft(block, *args, **kwargs)
    monkeypatch.setattr(bounded, "stft", stft)
    pad = np.pad
    def block_pad(array, *args, **kwargs):
        lengths.append(len(array))
        return pad(array, *args, **kwargs)
    for padding in (0, 160):
        with monkeypatch.context() as patch:
            patch.setattr(np, "pad", block_pad)
            actual = bounded(audio, padding, chunk_length=20)
        np.testing.assert_allclose(actual, reference(audio, padding, chunk_length=20), atol=2e-6)
    assert max(lengths) <= 3000 * bounded.hop_length + bounded.n_fft
    assert bounded.nb_max_frames == reference.nb_max_frames


def test_retranscribe_keeps_turns_and_names(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "BASE", tmp_path)
    rec = vault.new_recording({"id": "of_" + "a" * 32, "title": "Names", "date": "2026-11-17", "duration": "1m"})
    rec["speakers"] = {"S3": {"name": "Alice"}, "S8": {"name": "Bob"}}
    rec["diarization"].update(engine="migrated", turns=[[0, 2, "S3"], [2, 4, "S8"]])
    rec["fixes"] = [{"s": 2, "e": 3, "spk": "S3"}]
    rec["speakers_rev"] = 7
    vault.save(rec)
    monkeypatch.setattr(speech, "load_audio", lambda _: [])
    monkeypatch.setattr(speech, "transcribe", lambda *a: ([{"s": n, "e": n + 0.8, "w": " Hello."} for n in range(4)], "en"))
    def forbidden(*args):
        pytest.fail("retranscription ran diarization")
    monkeypatch.setattr(speech, "diarize", forbidden)
    pipeline.retranscribe(rec["id"], "large-v3-turbo", 2, lambda _: None)
    current = vault.find(rec["id"])
    for key in ("speakers", "diarization", "fixes", "speakers_rev"):
        assert current[key] == rec[key]
    assert [u["spk"] for u in current["utterances"]] == ["S3", "S8"]
    assert current["utterances"][0]["e"] == 2.8


def test_redo_keeps_names_by_overlap(monkeypatch):
    old = [[0, 10, "S1"], [10, 20, "S2"], [20, 30, "S3"]]
    new = [[0, 6, 2], [6, 10, 3], [10, 20, 0], [20, 30, 1], [35, 36, 4]]
    speakers = {"S1": {"name": "Uno"}, "S2": {"name": "Due"}, "S3": {"name": "Tre"}}
    mapping = pipeline.match_speakers(old, new, speakers, [])
    assert mapping == {0: "S2", 1: "S3", 2: "S1", 3: "S4", 4: "S5"}
    assert pipeline.match_speakers([[0, 4.9, "S1"]], [[0, 10, 0]], speakers, []) == {0: "S4"}
    assert pipeline.match_speakers([[0, 5, "S1"]], [[0, 10, 0]], speakers, []) == {0: "S1"}
    rec = {"diarization": {"turns": old, "rev": 1}, "speakers": copy.deepcopy(speakers),
           "words": [], "utterances": [], "fixes": [], "notes": [], "history": [], "speakers_rev": 1}
    monkeypatch.setattr(speech, "diarize", lambda *a: {
        "engine": "fake", "turns": new, "overlap": [[11, 12]], "embeddings": {i: [float(i), 1.] for i in range(5)}})
    pipeline._speakers(rec, [], 0, lambda _: None)
    assert all(rec["speakers"][s] == value for s, value in speakers.items())
    assert rec["diarization"]["embeddings"]["S2"] == [0., 1.]
    assert rec["diarization"]["turns"][0][2] == "S1"
    assert rec["diarization"]["overlap"] == [[11, 12]]


def test_named_speaker_never_dropped(monkeypatch):
    rec = {"diarization": {"turns": [[0, 2, "S1"]], "rev": 1},
           "speakers": {"S1": {"name": "Absent"}, "S5": {"name": ""}},
           "words": [{"s": 4, "e": 5, "w": " hello"}], "utterances": [],
           "fixes": [{"s": 4, "e": 5, "spk": "S5"}], "notes": [], "history": [], "speakers_rev": 1}
    monkeypatch.setattr(speech, "diarize", lambda *a: {
        "engine": "fake", "turns": [[3, 8, 0]], "overlap": [], "embeddings": {0: [1., 0.]}})
    pipeline._speakers(rec, [], 0, lambda _: None)
    assert rec["speakers"]["S1"]["name"] == "Absent" and "S5" in rec["speakers"]
    assert rec["utterances"][0]["spk"] == "S5"
    assert rec["diarization"]["turns"] == [[3, 8, "S6"]]


def test_overlap_flag_on_phrases(tmp_path, monkeypatch):
    # Whisper can return NumPy timestamps; overlap flags must still serialize to JSON.
    words = [{"s": np.float64(n), "e": np.float64(n + 0.9), "w": " Hello."} for n in range(3)]
    # Two separate 0.3 s touches must not flag a paragraph whose phrases never touch 0.5 s.
    utts = speech.utterances(words, [[0, 3, "S1"]], overlap=[[0, 0.3], [1, 1.3], [2, 2.5]])
    assert [(u["s"], u["overlap"]) for u in utts] == [(0, False), (2, True)]
    monkeypatch.setattr(vault, "BASE", tmp_path)
    rec = vault.new_recording({"id": "of_" + "b" * 32, "title": "Overlap", "date": "2026-11-17", "duration": "1m"})
    rec.update(utterances=utts, speakers={"S1": {"name": "Alice"}})
    vault.render(rec)
    text = (rec["_dir"] / f"{rec['stem']} - Transcript.md").read_text(encoding="utf-8")
    assert text.count("⇄") == 1 and "`00:02` ⇄" in text


class FakeWorker:
    """Stands in for the pyannote worker process: stdout lines, then an exit code (None = still running)."""
    def __init__(self, lines, returncode):
        self.stdout, self.returncode = iter(lines), returncode
    def kill(self): self.returncode = 1
    def poll(self): return self.returncode
    def wait(self): return self.returncode


def test_worker_output_is_parsed(tmp_path, monkeypatch):
    (tmp_path / ".venv-pyannote/Scripts").mkdir(parents=True)
    (tmp_path / ".venv-pyannote/Scripts/python.exe").touch()
    monkeypatch.setattr(speech, "ROOT", tmp_path)
    monkeypatch.setitem(speech.cfg, "diar_engine", "pyannote")
    # Labels and embeddings are label-ordered; tidy ranks by duration instead.
    saved = {"labels": ["A", "B", "C"], "turns": [[0, 2, 0], [2, 7, 2], [7, 10, 1]],
             "overlap_turns": [[0, 2, 0], [1, 2, 0], [1.234, 4, 2], [3, 5, 1], [5, 7, 2]],
             "embeddings": [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]}
    class Worker(FakeWorker):
        def __init__(self, command, **kwargs):
            Path(command[3]).write_text(json.dumps(saved), encoding="utf-8")
            super().__init__(["warming up\n", "progress 0.250\n", "progress 1.000\n"], 0)
    monkeypatch.setattr(speech.subprocess, "Popen", Worker)
    speech._model = ("large-v3-turbo", object())
    fracs = []
    log = lambda m: None
    log.progress = fracs.append
    result = speech.diarize(np.zeros(4), log=log)
    assert speech._model is None
    assert fracs == [0.25, 1.0]   # the worker's pyannote hook reaches the job's progress bar
    assert result == {"engine": "pyannote", "turns": [(0, 2, 2), (2, 7, 0), (7, 10, 1)],
                      "overlap": [[1.23, 2], [3, 4]],
                      "embeddings": {2: [1., 0., 0.], 1: [0., 1., 0.], 0: [0., 0., 1.]}}


def test_worker_timeout_falls_back_to_sherpa(tmp_path, monkeypatch):
    (tmp_path / ".venv-pyannote/Scripts").mkdir(parents=True)
    (tmp_path / ".venv-pyannote/Scripts/python.exe").touch()
    monkeypatch.setattr(speech, "ROOT", tmp_path)
    monkeypatch.setitem(speech.cfg, "diar_engine", "pyannote")
    limits = []
    monkeypatch.setattr(speech.subprocess, "Popen", lambda command, **kw: FakeWorker([], None))
    class Timer:   # fires at once: the worker overran its limit and is killed
        def __init__(self, interval, kill):
            limits.append(interval)
            self.kill = kill
        def start(self): self.kill()
        def is_alive(self): return False
        def cancel(self): pass
    monkeypatch.setattr(speech.threading, "Timer", Timer)
    class Pool:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def submit(self, fn, *a):
            return type("Done", (), {"result": lambda _: {"engine": "sherpa"}})()
    monkeypatch.setattr(speech, "ProcessPoolExecutor", Pool)
    logs = []
    assert speech.diarize(np.zeros(16000 * 3600), log=logs.append) == {"engine": "sherpa"}
    assert limits == [1800]  # an hour of audio gets half an hour, not a fixed hour
    assert "no result after 30 minutes" in logs[0]


def test_sherpa_keeps_pooled_embeddings_aligned(monkeypatch):
    turns = [(0, 30, 0), (30, 50, 1), (50, 90, 2)]
    monkeypatch.setattr(speech, "raw_turns", lambda _: turns)
    monkeypatch.setattr(speech, "voice_prints", lambda *a: {
        0: (30., np.array([1., 0.])), 1: (20., np.array([1., 0.])), 2: (40., np.array([0., 1.]))})
    result = speech._diarize([], 0)
    assert result["turns"] == [(0, 30, 0), (30, 50, 0), (50, 90, 1)]
    assert result["engine"] == "sherpa" and result["overlap"] == []
    assert result["embeddings"] == {0: [1., 0.], 1: [0., 1.]}


def test_sherpa_same_timestamps_do_not_mix_voices(monkeypatch):
    monkeypatch.setattr(speech, "raw_turns", lambda _: [(0, 30, 0), (0, 30, 1)])
    monkeypatch.setattr(speech, "voice_prints", lambda *a: {
        0: (30., np.array([1., 0.])), 1: (30., np.array([0., 1.]))})
    assert speech._diarize([], 0)["embeddings"] == {0: [1., 0.], 1: [0., 1.]}


def test_empty_speech_and_overlap_boundaries():
    assert speech.overlapping([]) == []
    assert speech.overlapping([[0, 2, 0], [1, 2, 0], [2, 3, 1]]) == []
    assert speech.overlapping([[0, 3, 0], [1, 2, 1], [2, 4, 2]]) == [[1, 3]]
    assert speech.utterances([], []) == []
    assert pipeline.match_speakers([], [], {"S1": {"name": "Kept"}}, []) == {}


def test_history_shares(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "BASE", tmp_path)
    words = [{"s": n, "e": n + 0.8, "w": f" word{n}."} for n in range(10)]
    rec = {"id": "test", "_dir": Path("unused"), "stem": "unused", "group": "unused", "words": words,
           "speakers": {"S1": {"name": "A"}, "S2": {"name": "B"}}, "fixes": [],
           "diarization": {"turns": [[0, 10, "S1"]], "overlap": [], "rev": 1},
           "utterances": speech.utterances(words, [[0, 10, "S1"]]),
           "transcript": {"rev": 1}, "notes": [], "history": [], "speakers_rev": 1}
    changed = copy.deepcopy(words)
    changed[4]["w"] = " changed."
    monkeypatch.setattr(speech, "load_audio", lambda _: [])
    monkeypatch.setattr(vault, "glossary", lambda _: [])
    monkeypatch.setattr(speech, "transcribe", lambda *a: (changed, "en"))
    pipeline._transcribe(rec, "large-v3-turbo", lambda _: None)
    assert rec["history"][-1] == {"kind": "transcript", "rev": 2, "changed": 0.1}
    monkeypatch.setattr(speech, "diarize", lambda *a: {
        "engine": "fake", "turns": [[0, 9, 0], [9, 10, 1]], "overlap": [], "embeddings": {}})
    pipeline._speakers(rec, [], 0, lambda _: None)
    assert rec["history"][-1] == {"kind": "speakers", "rev": 2, "changed": 0.1}


def correction_recording(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "BASE", tmp_path / "vault")
    rec = vault.new_recording({"id": "of_" + "d" * 32, "title": "Corrections", "date": "2026-11-17", "duration": "1m"})
    rec.update(duration_s=60, speakers={"S1": {"name": "Alice"}, "S2": {"name": "Bob"}, "S3": {"name": ""}},
               words=[{"s": n, "e": n + .8, "w": " Hello."} for n in range(6)])
    rec["diarization"].update(engine="fake", turns=[[0, 2, "S1"], [2, 4, "S2"], [4, 6, "S3"]],
                               embeddings={"S1": [2., 0.], "S2": [3., 1.], "S3": [0., 5.]})
    pipeline._assign(rec)
    vault.render(rec)
    return rec


def test_merge_joins_paragraphs_and_hub_lists_name_once(tmp_path, monkeypatch):
    rec = correction_recording(tmp_path, monkeypatch)
    pipeline.merge(rec["id"], "S2", "S1")
    current = vault.find(rec["id"])
    assert [u["spk"] for u in current["utterances"]] == ["S1", "S3"]
    assert current["utterances"][0]["e"] == 3.8
    assert current["diarization"] == rec["diarization"]
    assert current["history"][-1]["changed"] == pytest.approx(2 / 6)
    hub = (rec["_dir"] / (rec["stem"] + ".md")).read_text(encoding="utf-8")
    assert hub.count("Alice") == 1 and "Bob" not in hub


def test_unmerge_restores(tmp_path, monkeypatch):
    rec = correction_recording(tmp_path, monkeypatch)
    pipeline.merge(rec["id"], "S2", "S1")
    pipeline.merge(rec["id"], "S1", "S3")
    with pytest.raises(ValueError):
        pipeline.merge(rec["id"], "S3", "S2")
    pipeline.unmerge(rec["id"], "S1")
    pipeline.unmerge(rec["id"], "S2")
    assert vault.find(rec["id"])["utterances"] == rec["utterances"]


def test_fix_reassigns_only_its_span_and_survives_redo(tmp_path, monkeypatch):
    rec = correction_recording(tmp_path, monkeypatch)
    pipeline.add_fix(rec["id"], 2, 3, "S1")
    current = vault.find(rec["id"])
    assert [(u["s"], u["spk"]) for u in current["utterances"]] == [(0, "S1"), (3, "S2"), (4, "S3")]
    pipeline.merge(rec["id"], "S1", "S3")
    monkeypatch.setattr(speech, "load_audio", lambda _: [])
    monkeypatch.setattr(speech, "diarize", lambda *a: {"engine": "fake", "turns": [[0, 2, 2], [2, 4, 1], [4, 6, 0]], "overlap": [], "embeddings": {}})
    pipeline.respeak(rec["id"], 0, lambda _: None)
    current = vault.find(rec["id"])
    assert current["fixes"] == [{"s": 2, "e": 3, "spk": "S1"}]
    assert current["utterances"][0]["spk"] == "S3" and current["utterances"][0]["e"] == 2.8
    pipeline.remove_fix(rec["id"], 0)
    pipeline.unmerge(rec["id"], "S1")
    assert vault.find(rec["id"])["utterances"] == rec["utterances"]


def test_fix_to_new_speaker_creates_id(tmp_path, monkeypatch):
    rec = correction_recording(tmp_path, monkeypatch)
    pipeline.add_fix(rec["id"], 2, 3, "new")
    current = vault.find(rec["id"])
    assert "S4" in current["speakers"] and current["fixes"][0]["spk"] == "S4"
    assert current["utterances"][1]["spk"] == "S4"
    for start, end, spk in ((-1, 2, "S1"), (2, 61, "S1"), (2, 2, "S1"), (0, 2, "S99"), (True, 2, "S1"), (0, float("nan"), "S1")):
        with pytest.raises(ValueError):
            pipeline.add_fix(rec["id"], start, end, spk)
    for index in (-1, True, 10):
        with pytest.raises(ValueError):
            pipeline.remove_fix(rec["id"], index)


def test_closest_voice_uses_embeddings(tmp_path, monkeypatch):
    rec = correction_recording(tmp_path, monkeypatch)
    assert pipeline.closest_voice(rec, "S1") == "S2"
    rec["speakers"]["S2"]["merged_into"] = "S1"
    assert pipeline.closest_voice(rec, "S1") == "S3"


def test_closest_voice_none_without_embeddings():
    assert pipeline.closest_voice({"diarization": {"embeddings": {}}}, "S1") is None


def test_ensemble_skipped_for_unlisted_language(tmp_path, monkeypatch):
    from app import config, ensemble, speech
    assert config.DEFAULTS["ensemble_languages"] == ["it"]
    monkeypatch.setattr(vault, "BASE", tmp_path)
    monkeypatch.setitem(pipeline.cfg, "ensemble_languages", ["it", "en"])
    (tmp_path / "parakeet").mkdir()
    monkeypatch.setitem(pipeline.cfg, "parakeet_dir", str(tmp_path / "parakeet"))
    rec = vault.new_recording({"id": "of_" + "e" * 32, "title": "French", "date": "2026-11-17", "duration": "1m"})
    rec["speakers"] = {"S1": {"name": ""}}
    rec["diarization"].update(engine="fake", turns=[[0, 2, "S1"]])
    monkeypatch.setattr(speech, "load_audio", lambda _: [])
    monkeypatch.setattr(speech, "transcribe", lambda *a: ([{"s": 0.0, "e": 1.0, "w": " bonjour"}], "fr"))
    monkeypatch.setattr(speech, "transcribe_parakeet", lambda *a: pytest.fail("parakeet ran for unlisted language"))
    monkeypatch.setattr(ensemble, "fuse", lambda *a: pytest.fail("arbiter ran for unlisted language"))
    logs = []
    pipeline._transcribe(rec, "ensemble", logs.append)
    assert any("ensemble skipped for fr" in msg for msg in logs)
    assert rec["language"] == "fr" and rec["model"] == "ensemble"
    assert [w["w"] for w in rec["words"]] == [" bonjour"]
