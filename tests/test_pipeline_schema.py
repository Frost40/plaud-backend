import pytest

from app import pipeline, vault


@pytest.mark.parametrize("turns", [[(0, 1, 0)], []])
def test_pipeline_writes_schema_two_and_note_provenance(tmp_path, monkeypatch, turns):
    from app import speech
    monkeypatch.setattr(vault, "BASE", tmp_path)
    vault.seed()
    rec = vault.new_recording({"id": "of_" + "a" * 32, "title": "Example",
                               "date": "2026-11-17", "duration": "1m"})
    monkeypatch.setattr(speech, "load_audio", lambda path: [])
    monkeypatch.setattr(speech, "transcribe", lambda *args: ([{"s": 0, "e": 1, "w": "hello"}], "en"))
    monkeypatch.setattr(speech, "diarize", lambda *args: {
        "engine": "fake", "turns": turns, "overlap": [], "embeddings": {}})
    rec.update(stage="downloaded", num_speakers=1)
    vault.save(rec)
    with monkeypatch.context() as initial:
        initial.setattr(vault, "blueprints", lambda: [])
        pipeline.resume(rec["id"], lambda msg: None)
    rec = vault.find(rec["id"])
    assert rec["utterances"][0]["spk"] == "S1"
    assert rec["diarization"]["turns"] == ([[0, 1, "S1"]] if turns else [])
    assert rec["diarization"]["asked"]["num"] == 1
    assert rec["diarization"]["rev"] == rec["transcript"]["rev"] == rec["speakers_rev"] == 1
    pipeline.rename_speakers(rec["id"], {"S1": " Test name "})
    rec = vault.find(rec["id"])
    assert rec["speakers"] == {"S1": {"name": "Test name"}}
    assert rec["speakers_rev"] == 2
    monkeypatch.setattr(pipeline.llm, "run", lambda *args: "## Core theme ## Tasks ## Ideas\nhello")
    name = pipeline.generate(rec["id"], "Voice memo", "claude", lambda msg: None)
    rec = vault.find(rec["id"])
    note = rec["notes"][0]
    assert note["file"] == name + ".md" and note["blueprint"] == "Voice memo"
    assert note["provider"] == "claude" and note["at"]
    assert note["transcript_rev"] == 1 and note["speakers_rev"] == 2
    pipeline.respeak(rec["id"], 0, lambda msg: None)
    rec = vault.find(rec["id"])
    assert rec["speakers"] == {"S1": {"name": "Test name"}}
    assert rec["diarization"]["rev"] == 2 and rec["speakers_rev"] == 3
    assert rec["transcript"]["rev"] == 1 and rec["notes"] == [note]


def test_generate_preserves_changes_made_during_provider_call(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "BASE", tmp_path)
    vault.seed()
    rec = vault.new_recording({"id": "of_" + "c" * 32, "title": "Example",
                               "date": "2026-11-17", "duration": "1m"})
    rec["speakers"] = {"S1": {"name": "Before"}}
    vault.save(rec)
    def provider(*args):
        pipeline.rename_speakers(rec["id"], {"S1": "After"})
        return "## Core theme ## Tasks ## Ideas\nhello"
    monkeypatch.setattr(pipeline.llm, "run", provider)
    pipeline.generate(rec["id"], "Voice memo", "claude", lambda msg: None)
    current = vault.find(rec["id"])
    assert current["speakers"]["S1"]["name"] == "After" and current["speakers_rev"] == 1
    assert current["notes"][0]["speakers_rev"] == 0


def test_first_note_titles_a_timestamp_recording_but_never_an_owner_title(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "BASE", tmp_path)
    vault.seed()
    rec = vault.new_recording({"id": "of_" + "d" * 32, "title": "2026-10-27 16:02:50",
                               "date": "2026-10-27", "duration": "1m"})
    prompts = []
    def provider(_p, prompt, *rest):
        prompts.append(prompt)
        return "## Core theme ## Tasks ## Ideas\nhello\n```title\n**Riunione sul GS**\n```\n```glossary\nGS\n```"
    monkeypatch.setattr(pipeline.llm, "run", provider)
    name = pipeline.generate(rec["id"], "Voice memo", "claude", lambda msg: None)
    rec = vault.find(rec["id"])
    body = (rec["_dir"] / (name + ".md")).read_text(encoding="utf-8")
    assert rec["title"] == "Riunione sul GS" and "```title" not in body and "```glossary" not in body
    assert "# Riunione sul GS" in (rec["_dir"] / f"{rec['stem']}.md").read_text(encoding="utf-8")
    pipeline.generate(rec["id"], "Voice memo", "claude", lambda msg: None)   # titled: not asked again
    assert "```title" in prompts[0] and "```title" not in prompts[1]
    with pytest.raises(ValueError):
        pipeline.rename(rec["id"], " 12:00 ")
    pipeline.rename(rec["id"], "  My   meeting ")
    rec = vault.find(rec["id"])
    assert rec["title"] == "My meeting" and rec["title_by_user"]
    rec["title"] = "2026-10-27"          # even a timestamp-like title the owner typed stays
    vault.save(rec)
    assert not pipeline.needs_title(vault.find(rec["id"]))
