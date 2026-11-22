import json

import pytest
from fastapi.testclient import TestClient

from app import jobs, pipeline, server, vault, voices


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "BASE", tmp_path)


def recording(embeddings):
    return {"id": "query", "diarization": {"engine": "pyannote", "embeddings": embeddings},
            "speakers": {key: {"name": ""} for key in embeddings}}


def enrol_three(engine="pyannote"):
    for name, vector in zip(("Ada", "Ben", "Cleo"), ([1, 0, 0], [0, 1, 0], [0, 0, 1])):
        for rec_id in ("first", "second"):
            voices.enrol(name, vector, engine, rec_id)


def test_enrol_on_naming():
    rec = vault.new_recording({"id": "query", "title": "Voices", "date": "2026-11-18", "duration": "1m"})
    rec["speakers"] = {"S1": {"name": ""}}
    rec["diarization"].update(engine="pyannote", embeddings={"S1": [1, 0]})
    vault.save(rec)
    pipeline.rename_speakers("query", {"S1": "Ada"})
    path = vault.BASE / "_Voices.json"
    assert json.loads(path.read_text())["Ada"]["pyannote"][0]["vector"] == [1, 0]
    pipeline.rename_speakers("query", {"S1": "Ben"})
    assert set(json.loads(path.read_text())) == {"Ben"}
    pipeline.rename_speakers("query", {})
    assert json.loads(path.read_text()) == {}


def test_suggestion_needs_threshold():
    enrol_three()
    voices.forget("Cleo", "first")
    assert voices.threshold("pyannote") is None
    assert voices.suggest(recording({"S1": [1, 0, 0]})) == {}


def test_no_two_speakers_get_the_same_suggestion():
    enrol_three()
    suggestions = voices.suggest(recording({"S1": [1, .2, 0], "S2": [1, 0, 0]}))
    assert suggestions == {"S2": {"name": "Ada", "score": 1.0}}


def test_threshold_from_leave_one_out():
    for name, vectors in {"Ada": ([1, 0], [0, 1]), "Ben": ([1, 0], [1, 0]),
                          "Cleo": ([-1, 0], [-1, 0])}.items():
        for rec_id, vector in zip(("first", "second"), vectors):
            voices.enrol(name, vector, "pyannote", rec_id)
    assert voices.threshold("pyannote") == 1


def test_engines_never_mixed():
    enrol_three()
    enrol_three("sherpa")
    voices.forget("Ada", "first")
    voices.enrol("Ada", [1, 0, 0], "pyannote", "first")
    voices.enrol("Ada", [-1, 0, 0], "sherpa", "first")
    voices.enrol("Ada", [-1, 0, 0], "sherpa", "second")
    assert voices.suggest(recording({"S1": [1, 0, 0]}))["S1"]["name"] == "Ada"


def test_refused_suggestion_not_repeated():
    enrol_three()
    rec = vault.new_recording({"id": "query", "title": "Voices", "date": "2026-11-18", "duration": "1m"})
    rec.update(recording({"S1": [1, 0, 0]}))
    vault.save(rec)
    pipeline.answer_suggestion("query", "S1", False)
    assert voices.suggest(vault.find("query")) == {}


def test_at_most_20_vectors():
    for i in range(25):
        voices.enrol("Ada", [1, i], "pyannote", str(i))
    path = vault.BASE / "_Voices.json"
    samples = json.loads(path.read_text())["Ada"]["pyannote"]
    assert [sample["rec_id"] for sample in samples] == [str(i) for i in range(5, 25)]


def test_accept_suggestion_through_api(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    enrol_three()
    rec_id = "of_" + "a" * 32
    rec = vault.new_recording({"id": rec_id, "title": "Voices", "date": "2026-11-18", "duration": "1m"})
    rec.update(recording({"S1": [1, 0, 0], "S2": [0, 1, 0]}), id=rec_id)
    vault.save(rec)
    with TestClient(server.app) as client:
        route = "/api/recordings/" + rec_id
        assert client.get(route).json()["voice_people_needed"] == 0
        body = {"id": rec_id, "spk": "S1", "accept": True}
        assert client.post("/api/suggestion", json=body | {"name": "Ben"}).status_code == 400
        assert client.post("/api/suggestion", json=body | {"accept": "true"}).status_code == 400
        assert client.post("/api/suggestion", json=body).status_code == 200
        result = client.get(route).json()
        assert result["speakers"]["S1"]["name"] == "Ada"
        assert result["suggestions"] == {"S2": {"name": "Ben", "score": 1.0}}
    assert voices._read()["Ada"]["pyannote"][-1]["rec_id"] == rec_id
    assert "Ada" in vault.glossary(rec["group"])
