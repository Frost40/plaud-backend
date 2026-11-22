import copy
import json
import os
from pathlib import Path

import pytest

from app import vault


def legacy():
    return {"id": "of_" + "a" * 32, "title": "Example", "date": "2026-11-17",
            "stem": "Example", "duration": "1h2m3s", "start_at": "2026-11-17T12:34:56.123456",
            "model": "ensemble", "speakers": {"0": "Alice"}, "words": [], "marks": [],
            "utterances": [{"s": 0, "e": 2, "spk": 0, "text": "hello"},
                           {"s": 2, "e": 4, "spk": 1, "text": "world"}]}


def test_migration_fields():
    data = legacy()
    before = copy.deepcopy(data)
    note_files = {"Example - Minutes.md": {"blueprint": "Minutes", "provider": "claude",
                                          "created": "2026-11-17 13:00"}}
    rec = vault.migrate_v1(data, note_files)
    assert data == before
    assert rec["schema"] == 2 and rec["stage"] == "done"
    assert rec["duration_s"] == 3723 and rec["start_at"] == "2026-11-17T12:34:56"
    assert rec["speakers"] == {"S1": {"name": "Alice"}, "S2": {"name": ""}}
    assert [u["spk"] for u in rec["utterances"]] == ["S1", "S2"]
    assert rec["diarization"]["turns"] == [[0, 2, "S1"], [2, 4, "S2"]]
    assert rec["diarization"]["engine"] == "migrated"
    assert rec["diarization"]["overlap"] == [] and rec["diarization"]["embeddings"] == {}
    assert rec["notes"] == [{"file": "Example - Minutes.md", "blueprint": "Minutes",
                             "provider": "claude", "at": "2026-11-17 13:00",
                             "transcript_rev": 1, "speakers_rev": 1, "check_failed": []}]
    assert rec["transcript"]["rev"] == rec["speakers_rev"] == 1
    assert rec["true_speakers"] is None and rec["history"] == []


@pytest.mark.parametrize("number,seconds,speakers,notes", [(1, 4860, 9, 1), (2, 1307, 3, 1),
                                                         (3, 2996, 3, 1), (4, 226, 1, 2)])
def test_v1_migrates_to_v2(number, seconds, speakers, notes):
    fixture = json.loads((Path(__file__).parent / "fixtures" / f"recording-v1-{number}.json").read_text(encoding="utf-8"))
    original = fixture["recording"]
    before = copy.deepcopy(fixture)
    rec = vault.migrate_v1(original, fixture["note_files"])
    assert fixture == before and "words" not in original
    assert rec["schema"] == 2 and rec["stage"] == "done" and rec["duration_s"] == seconds
    assert rec["start_at"] == original["start_at"][:19]
    assert set(rec["speakers"]) == {f"S{k + 1}" for k in range(speakers)}
    for old, new in zip(original["utterances"], rec["utterances"]):
        assert new == old | {"spk": f"S{old['spk'] + 1}", "overlap": False}
    assert rec["diarization"]["turns"] == [[u["s"], u["e"], f"S{u['spk'] + 1}"] for u in original["utterances"]]
    assert rec["diarization"]["engine"] == "migrated"
    assert len(rec["notes"]) == notes
    for note in rec["notes"]:
        meta = fixture["note_files"][note["file"]]
        assert note["provider"] == meta["provider"] and note["blueprint"] == meta["blueprint"]
        assert note["transcript_rev"] == note["speakers_rev"] == 1
    assert rec["marks"] == original["marks"] and rec["written"] == original["written"]


def test_save_is_atomic(tmp_path, monkeypatch):
    path = tmp_path / "recording.json"
    path.write_text('{"old": true}', encoding="utf-8")
    def fail(*args):
        raise OSError("replace failed")
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        vault.save({"schema": 2, "_dir": tmp_path})
    assert json.loads(path.read_text()) == {"old": True}


def test_v2_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "BASE", tmp_path)
    folder = tmp_path / "Inbox" / "Example"
    folder.mkdir(parents=True)
    rec = vault.migrate_v1(legacy(), {}) | {"_dir": folder, "group": "Inbox"}
    vault.save(rec)
    assert vault.find(rec["id"]) == rec


def test_newer_schema_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "BASE", tmp_path)
    folder = tmp_path / "Inbox" / "Example"
    folder.mkdir(parents=True)
    rec = legacy() | {"schema": 3, "_dir": folder}
    path = folder / "recording.json"
    path.write_text('{"schema": 3}', encoding="utf-8")
    for write in (lambda: vault.save(rec), lambda: vault.render(rec),
                  lambda: vault.add_note(rec, "Note", "text")):
        with pytest.raises(ValueError, match="schema"):
            write()
    assert path.read_text() == '{"schema": 3}'
    assert list(folder.iterdir()) == [path]


def test_migrate_all_keeps_v1_copy_and_skips_on_error(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(vault, "BASE", tmp_path)
    good = tmp_path / "Inbox" / "Example"
    bad = tmp_path / "Inbox" / "Broken"
    good.mkdir(parents=True)
    bad.mkdir()
    original = json.dumps(legacy())
    (good / "recording.json").write_text(original)
    (bad / "recording.json").write_text("broken")
    vault.migrate_all()
    assert (good / "recording.v1.json").read_text() == original
    assert json.loads((good / "recording.json").read_text())["schema"] == 2
    assert (bad / "recording.json").read_text() == "broken"
    assert "Broken" in caplog.text
    vault.migrate_all()
    assert (good / "recording.v1.json").read_text() == original


def test_migration_does_not_overwrite_conflicting_backup(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(vault, "BASE", tmp_path)
    folder = tmp_path / "Inbox" / "Example"
    folder.mkdir(parents=True)
    original = json.dumps(legacy())
    (folder / "recording.json").write_text(original)
    (folder / "recording.v1.json").write_text('{"other": true}')
    vault.migrate_all()
    assert (folder / "recording.json").read_text() == original
    assert (folder / "recording.v1.json").read_text() == '{"other": true}'
    assert "backup" in caplog.text.lower()


@pytest.mark.parametrize("failure", ["backup", "verify", "replace"])
def test_migration_failure_leaves_original_and_can_retry(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(vault, "BASE", tmp_path)
    folder = tmp_path / "Inbox" / "Example"
    folder.mkdir(parents=True)
    path = folder / "recording.json"
    original = json.dumps(legacy()).encode()
    path.write_bytes(original)
    real_open, real_read = Path.open, Path.read_bytes
    with monkeypatch.context() as patch:
        if failure == "backup":
            def fail_open(p, *args, **kwargs):
                if p.name == "recording.v1.json":
                    raise OSError("backup denied")
                return real_open(p, *args, **kwargs)
            patch.setattr(Path, "open", fail_open)
        elif failure == "verify":
            patch.setattr(Path, "read_bytes", lambda p: b'{}' if p.name == "recording.v1.json" else real_read(p))
        else:
            def fail_replace(*args):
                raise OSError("replace denied")
            patch.setattr(os, "replace", fail_replace)
        vault.migrate_all()
    assert path.read_bytes() == original
    vault.migrate_all()
    assert json.loads(path.read_text())["schema"] == 2
    assert (folder / "recording.v1.json").read_bytes() == original
