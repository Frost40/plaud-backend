import pytest

from app import pipeline, vault


def recording(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "BASE", tmp_path)
    vault.seed()
    rec = vault.new_recording({"id": "of_" + "a" * 32, "title": "Notes",
                               "date": "2026-11-17", "duration": "2m"})
    rec.update(stage="done", speakers={"S1": {"name": ""}, "S2": {"name": "Alice"}},
               words=[{"s": i, "e": i + .5, "w": f" word{i}."} for i in range(100)])
    rec["diarization"]["turns"] = [[0, 50, "S1"], [50, 100, "S2"]]
    pipeline._assign(rec)
    vault.save(rec)
    monkeypatch.setattr(pipeline.llm, "run", lambda *a: "## Core theme ## Tasks ## Ideas\nSpeaker 1 and Alice. Speaker 12 stays.")
    pipeline.generate(rec["id"], "Voice memo", "claude", lambda _: None)
    return vault.find(rec["id"])


def read_note(rec):
    return vault._frontmatter((rec["_dir"] / rec["notes"][0]["file"]).read_text(encoding="utf-8"))


def no_provider(*args):
    pytest.fail("speaker edits must not call a provider")


def test_rename_rewrites_labels_without_llm(tmp_path, monkeypatch):
    rec = recording(tmp_path, monkeypatch)
    meta, _ = read_note(rec)
    assert meta["speakers"] == {"S1": "Speaker 1", "S2": "Alice"}
    assert meta["transcript_rev"] == rec["transcript"]["rev"]
    monkeypatch.setattr(pipeline.llm, "run", no_provider)
    pipeline.rename_speakers(rec["id"], {"S1": "Alice", "S2": "Speaker 1"})
    current = vault.find(rec["id"])
    meta, body = read_note(current)
    assert "Alice and Speaker 1." in body  # simultaneous substitution, no cascading
    assert meta["speakers"] == {"S1": "Alice", "S2": "Speaker 1"}
    assert meta["speakers_rev"] == current["notes"][0]["speakers_rev"] == current["speakers_rev"]


def test_merge_rewrites_labels_without_llm(tmp_path, monkeypatch):
    from app import notes
    rec = recording(tmp_path, monkeypatch)
    monkeypatch.setattr(pipeline.llm, "run", no_provider)
    pipeline.merge(rec["id"], "S1", "S2")
    current = vault.find(rec["id"])
    assert "Alice and Alice." in read_note(current)[1]
    assert notes.state(current, current["notes"][0]) == "current"
    pipeline.unmerge(rec["id"], "S1")
    current = vault.find(rec["id"])
    assert notes.state(current, current["notes"][0]) == "out_of_date"


def test_speaker_12_not_touched_by_speaker_1(tmp_path, monkeypatch):
    rec = recording(tmp_path, monkeypatch)
    pipeline.rename_speakers(rec["id"], {"S1": "Docente", "S2": "Alice"})
    assert "Docente and Alice. Speaker 12 stays." in read_note(rec)[1]


def test_small_retranscribe_keeps_note(tmp_path, monkeypatch):
    from app import notes, speech
    rec = recording(tmp_path, monkeypatch)
    before = read_note(rec)[1]
    words = [w.copy() for w in rec["words"]]
    words[0]["w"] = " replacement."
    monkeypatch.setattr(pipeline.llm, "run", no_provider)
    monkeypatch.setattr(speech, "load_audio", lambda _: [])
    monkeypatch.setattr(speech, "transcribe", lambda *a: (words, "en"))
    pipeline.retranscribe(rec["id"], "large-v3-turbo", 0, lambda _: None)
    current = vault.find(rec["id"])
    meta, body = read_note(current)
    assert current["history"][-1]["changed"] == .01
    assert meta["minor_change"] is True and body == before
    assert meta["transcript_rev"] == current["notes"][0]["transcript_rev"] == current["transcript"]["rev"]
    assert notes.state(current, current["notes"][0]) == "current"


def test_large_change_marks_out_of_date(tmp_path, monkeypatch):
    from app import notes
    rec = recording(tmp_path, monkeypatch)
    note = rec["notes"][0]
    rec["history"] = [{"kind": "transcript", "rev": 1, "changed": .012},
                      {"kind": "speakers", "rev": 1, "changed": .009}]
    rec["transcript"]["rev"] = rec["speakers_rev"] = 1
    assert notes.state(rec, note) == "out_of_date"
    rec["history"][1]["changed"] = .008
    assert notes.state(rec, note) == "out_of_date"  # exactly 2% is not minor
    rec["history"][1]["changed"] = .007
    assert notes.state(rec, note) == "minor"
    vault.save(rec)
    pipeline.rename_speakers(rec["id"], {"S1": "Docente", "S2": "Alice"})
    current = vault.find(rec["id"])
    assert notes.state(current, current["notes"][0]) == "minor"  # relabel must retain pending changes


def test_regenerate_keeps_owner_edit(tmp_path, monkeypatch):
    from app import notes
    rec = recording(tmp_path, monkeypatch)
    path = rec["_dir"] / rec["notes"][0]["file"]
    path.write_text(path.read_text(encoding="utf-8") + "My own words about Speaker 1.\n", encoding="utf-8")
    pipeline.rename_speakers(rec["id"], {"S1": "Docente", "S2": "Alice"})
    owner_text = path.read_text(encoding="utf-8")
    assert "My own words about Docente." in owner_text
    monkeypatch.setattr(pipeline.llm, "run", lambda *a: "## Core theme ## Tasks ## Ideas\nFresh note")
    notes.regenerate(rec["id"], path.name, lambda _: None)
    current = vault.find(rec["id"])
    assert len(current["notes"]) == 1 and "Fresh note" in path.read_text(encoding="utf-8")
    assert path.with_name(path.stem + " (your edit 1).md").read_text(encoding="utf-8") == owner_text
    notes.regenerate(rec["id"], path.name, lambda _: None)
    assert not path.with_name(path.stem + " (your edit 2).md").exists()


def test_missing_note_is_not_a_broken_hub_link(tmp_path, monkeypatch, caplog):
    rec = recording(tmp_path, monkeypatch)
    file = rec["notes"][0]["file"]
    (rec["_dir"] / file).unlink()
    vault.render(rec)
    hub = (rec["_dir"] / (rec["stem"] + ".md")).read_text(encoding="utf-8")
    assert f"(missing: {file})" in hub and f"[[{file[:-3]}]]" not in hub
    assert file in caplog.text


def test_fix_and_rename_do_not_hide_stale_speaker_content(tmp_path, monkeypatch):
    from app import notes
    rec = recording(tmp_path, monkeypatch)
    monkeypatch.setattr(pipeline.llm, "run", no_provider)
    pipeline.add_fix(rec["id"], 0, 10, "S2")
    current = vault.find(rec["id"])
    assert notes.state(current, current["notes"][0]) == "out_of_date"
    pipeline.rename_speakers(rec["id"], {"S1": "Docente", "S2": "Alice"})
    current = vault.find(rec["id"])
    assert "Docente" in read_note(current)[1]
    assert notes.state(current, current["notes"][0]) == "out_of_date"


def test_minor_redo_updates_note_without_claiming_owner_edit(tmp_path, monkeypatch):
    from app import notes, speech
    rec = recording(tmp_path, monkeypatch)
    path = rec["_dir"] / rec["notes"][0]["file"]
    path.write_text(path.read_text(encoding="utf-8") + "My edit\n", encoding="utf-8")
    monkeypatch.setattr(pipeline.llm, "run", no_provider)
    monkeypatch.setattr(speech, "load_audio", lambda _: [])
    monkeypatch.setattr(speech, "diarize", lambda *a: {
        "engine": "fake", "turns": [[0, 49, 0], [49, 100, 1]], "overlap": [], "embeddings": {}})
    pipeline.respeak(rec["id"], 0, lambda _: None)
    current = vault.find(rec["id"])
    assert current["history"][-1]["changed"] == .01
    assert read_note(current)[0]["minor_change"] is True
    assert notes.state(current, current["notes"][0]) == "current"
    assert current["written"][path.name] != vault._hash(path.read_text(encoding="utf-8"))


def test_failed_regeneration_leaves_original_untouched(tmp_path, monkeypatch):
    from app import notes
    rec = recording(tmp_path, monkeypatch)
    path = rec["_dir"] / rec["notes"][0]["file"]
    original = path.read_bytes()
    def fail(*a):
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr(pipeline.llm, "run", fail)
    with pytest.raises(RuntimeError, match="unavailable"):
        notes.regenerate(rec["id"], path.name)
    assert path.read_bytes() == original
    assert not list(rec["_dir"].glob("*your edit*"))


def test_shared_name_rename_requires_regeneration(tmp_path, monkeypatch):
    from app import notes
    rec = recording(tmp_path, monkeypatch)
    pipeline.rename_speakers(rec["id"], {"S1": "Alice", "S2": "Alice"})
    pipeline.rename_speakers(rec["id"], {"S1": "Bob", "S2": "Alice"})
    current = vault.find(rec["id"])
    assert "Alice and Alice." in read_note(current)[1]
    assert notes.state(current, current["notes"][0]) == "out_of_date"
    assert read_note(current)[0]["speakers"] == {"S1": "Alice", "S2": "Alice"}
    notes.regenerate(rec["id"], current["notes"][0]["file"], lambda _: None)
    current = vault.find(rec["id"])
    assert notes.state(current, current["notes"][0]) == "current"


def test_minor_unmerge_does_not_hide_ambiguous_labels(tmp_path, monkeypatch):
    from app import notes
    rec = recording(tmp_path, monkeypatch)
    rec["diarization"]["turns"] = [[0, 1, "S1"], [1, 100, "S2"]]
    pipeline._assign(rec)
    vault.save(rec)
    pipeline.merge(rec["id"], "S1", "S2")
    pipeline.unmerge(rec["id"], "S1")
    current = vault.find(rec["id"])
    assert current["history"][-1]["changed"] == .01
    assert notes.state(current, current["notes"][0]) == "out_of_date"


def test_unchanged_longer_label_shields_its_prefix(tmp_path, monkeypatch):
    rec = recording(tmp_path, monkeypatch)
    pipeline.rename_speakers(rec["id"], {"S1": "Alice", "S2": "Alice Smith"})
    assert "Alice and Alice Smith." in read_note(rec)[1]
    pipeline.rename_speakers(rec["id"], {"S1": "Bob", "S2": "Alice Smith"})
    assert "Bob and Alice Smith." in read_note(rec)[1]


@pytest.mark.parametrize("file", ["../outside.md", "..\\outside.md", "recording.json", None, 5])
def test_regenerate_rejects_unindexed_files(tmp_path, monkeypatch, file):
    from app import notes
    rec = recording(tmp_path, monkeypatch)
    monkeypatch.setattr(pipeline.llm, "run", no_provider)
    with pytest.raises(ValueError):
        notes.regenerate(rec["id"], file)


def test_default_label_is_not_a_name(tmp_path, monkeypatch):
    # Settings sends back the shown "Speaker 1" for an unnamed speaker: it stays unnamed and is not learned.
    from app import glossary
    rec = recording(tmp_path, monkeypatch)
    pipeline.rename_speakers(rec["id"], {"S1": "Speaker 1", "S2": "Bob"})
    assert vault.find(rec["id"])["speakers"]["S1"]["name"] == ""
    glossary.add_candidates(rec["group"], ["Speaker 3"], "other", "note")
    assert [w["term"] for w in glossary.view(rec["group"], vault.find(rec["id"]))["words"]] == ["Bob"]
