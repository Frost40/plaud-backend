import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app import jobs, server, vault


def test_note_states_and_queued_regeneration(tmp_path, monkeypatch):
    from app import notes, pipeline
    monkeypatch.setattr(vault, "BASE", tmp_path / "Plaud")
    monkeypatch.setattr(server, "VAULT", tmp_path)
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    monkeypatch.setattr(server.llm, "available", lambda: ["claude"])
    vault.seed()
    rec = vault.new_recording({"id": "of_" + "a" * 32, "title": "States", "date": "2026-11-17", "duration": "1m"})
    monkeypatch.setattr(pipeline.llm, "run", lambda *a: "## Core theme ## Tasks ## Ideas\nFresh")
    name = pipeline.generate(rec["id"], "Voice memo", "claude", lambda _: None)
    rec = vault.find(rec["id"])
    rec["history"] = [{"kind": "transcript", "rev": 1, "changed": .1}]
    rec["transcript"]["rev"] = 1
    vault.save(rec)
    with TestClient(server.app) as client:
        note = client.get("/api/state").json()["recordings"][0]["notes"][0]
        assert note["file"] == name + ".md" and note["state"] == "out_of_date" and not note["missing"]
        for file in ("../outside.md", "..\\outside.md", "recording.json", "not indexed.md", None, 5):
            assert client.post("/api/regenerate", json={"id": rec["id"], "file": file}).status_code == 400
        result = client.post("/api/regenerate", json={"id": rec["id"], "file": note["file"]})
        assert result.status_code == 200 and result.json()["kind"] == "regenerate"
        assert result.json()["args"] == {"file": note["file"]}
        server._run_job(jobs.next_job())
        assert jobs.recent()[0]["status"] == "done"
        current = vault.find(rec["id"])
        assert notes.state(current, current["notes"][0]) == "current"
        url = f"/api/notes/{rec['id']}/"
        body = client.get(url + note["file"])
        assert body.status_code == 200 and "Fresh" in body.json()["text"] and "blueprint:" not in body.json()["text"]
        for file in ("..%2Foutside.md", "..%5Coutside.md", "recording.json", "not indexed.md"):
            assert client.get(url + file).status_code in (400, 404), file
        assert client.get("/api/notes/bad/" + note["file"]).status_code == 400
        (rec["_dir"] / note["file"]).unlink()
        assert client.get("/api/state").json()["recordings"][0]["notes"][0]["missing"]
        assert client.get(url + note["file"]).status_code == 404


def test_state_cache_and_speaker_api(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "BASE", tmp_path / "Plaud")
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    monkeypatch.setattr(server, "VAULT", tmp_path)
    monkeypatch.setattr(server.llm, "available", lambda: ["claude"])
    vault.seed()
    rec = vault.new_recording({"id": "of_" + "a" * 32, "title": "Example",
                               "date": "2026-11-17", "duration": "1m"})
    rec["utterances"] = [{"s": 0, "e": 1, "spk": "S1", "text": "private text"}]
    rec["speakers"] = {"S1": {"name": ""}}
    vault.render(rec)
    rec["transcript"]["glossary_dropped"] = ["overflow"]
    vault.save(rec)
    original_read = Path.read_text
    reads = []
    def read(path, *args, **kwargs):
        if path.name == "recording.json":
            reads.append(path)
        return original_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read)
    with TestClient(server.app) as client:
        first = client.get("/api/state").json()
        assert first["recordings"][0]["glossary_dropped"] == 1
        assert client.get("/api/state").json() == first
        assert len(reads) == 1
        assert "words" not in json.dumps(first) and "private text" not in json.dumps(first)
        assert "utterances" not in first["recordings"][0]
        extra = rec["_dir"] / "Owner note.md"
        extra.write_text("Added in Obsidian", encoding="utf-8")
        assert client.get("/api/state").json()["recordings"][0]["notes"] == []  # only indexed notes
        extra.unlink()
        assert client.get("/api/state").json()["recordings"][0]["notes"] == []
        assert len(reads) == 1
        path = rec["_dir"] / "recording.json"
        data = json.loads(original_read(path, encoding="utf-8"))
        data["title"] = "Edited in Obsidian"
        before = path.stat().st_mtime_ns
        path.write_text(json.dumps(data), encoding="utf-8")
        os.utime(path, ns=(before + 1_000_000, before + 1_000_000))
        assert client.get("/api/state").json()["recordings"][0]["title"] == "Edited in Obsidian"
        assert len(reads) == 2
        for names in ({"0": "Bad"}, {"S99": "Unknown"}, ["bad"], {"S1": 5}, {"S1": "x" * 61}):
            assert client.post("/api/speakers", json={"id": rec["id"], "names": names}).status_code == 400
        assert client.post("/api/speakers", json={"id": rec["id"], "names": {"S1": "Test name"}}).status_code == 200
        state = client.get("/api/state").json()
        assert state["recordings"][0]["speakers"] == {"S1": "Test name"}
        assert state["glossaries"]["Inbox"] == [1, 1]
        assert client.post("/api/speakers", json={"id": rec["id"], "names": {"S1": ""}}).status_code == 200
        assert vault.find(rec["id"])["speakers"] == {"S1": {"name": ""}}
        vault.move(rec["id"], "Moved")
        assert client.get("/api/state").json()["recordings"][0]["group"] == "Moved"
        assert len(server._recording_cache) == 1


def test_controls_queue_and_dispatch_arguments(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    monkeypatch.setattr(vault, "BASE", tmp_path / "vault")
    monkeypatch.setattr(server.llm, "available", lambda: ["claude"])
    vault.seed()
    rec = vault.new_recording({"id": "of_" + "b" * 32, "title": "Example", "date": "2026-11-17", "duration": "1m"})
    rec.update(stage="done", speakers={"S1": {"name": ""}})
    vault.save(rec)
    seen = []
    for name in ("ingest", "resume", "retranscribe", "respeak", "generate", "rename_speakers"):
        monkeypatch.setattr(server.pipeline, name, lambda rec_id, _name=name, **kw: seen.append((_name, rec_id, kw)))
    monkeypatch.setattr(vault, "move", lambda rec_id, **kw: seen.append(("move", rec_id, kw)))
    new_id = "of_" + "c" * 32
    with TestClient(server.app) as client:
        controls = [
            ("import", new_id, {"model": "ensemble", "speakers": 2, "group": "Topic"}, "ingest",
             {"model": "ensemble", "num_speakers": 2, "group": "Topic"}),
            ("retranscribe", rec["id"], {"model": "large-v3", "speakers": 3}, "retranscribe", {"model": "large-v3", "num_speakers": 3}),
            ("respeak", rec["id"], {"speakers": 4}, "respeak", {"num_speakers": 4}),
            ("move", rec["id"], {"group": "Topic"}, "move", {"group": "Topic"}),
            ("speakers", rec["id"], {"names": {"S1": "Alice"}}, "rename_speakers", {"names": {"S1": "Alice"}}),
            ("generate", rec["id"], {"blueprint": "Voice memo", "provider": "claude"}, "generate", {"blueprint": "Voice memo", "provider": "claude"}),
        ]
        for route, rec_id, body, function, args in controls:
            response = client.post("/api/" + route, json={"id": rec_id, **body})
            assert response.status_code == 200, response.text
            if route != "speakers":
                assert response.json()["args"] == args
                server._run_job(jobs.next_job())
            actual, actual_id, kwargs = seen.pop()
            kwargs.pop("log", None)
            assert (actual, actual_id, kwargs) == (function, rec_id, args)
        for body in ({"id": 5}, {"id": "bad"}, {"id": rec["id"], "model": "unknown"},
                     {"id": rec["id"], "speakers": 13}, {"id": rec["id"], "speakers": "oops"},
                     {"id": rec["id"], "speakers": 1.5}):
            assert client.post("/api/import", json=body).status_code == 400
        assert client.post("/api/import", json={"id": rec["id"]}).status_code == 400
        rec["stage"] = "transcribed"
        vault.save(rec)
        result = client.post("/api/import", json={"id": rec["id"]}).json()
        assert result["kind"] == "resume"
        jobs.fail(result["id"], "CUDA out of memory", None)
        assert client.post("/api/retry", json={"job": result["id"]}).json()["status"] == "queued"
        for job in ("1", None, 999):
            assert client.post("/api/retry", json={"job": job}).status_code == 400


def test_doctor_is_read_only_and_state_uses_cached_result(tmp_path, monkeypatch):
    import ctranslate2
    from app import config, doctor, plaud
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "VAULT", tmp_path)
    monkeypatch.setattr(vault, "BASE", tmp_path / "vault")
    monkeypatch.setattr(server, "VAULT", tmp_path)
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 1)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: name if name == "claude" else None)
    calls = []
    monkeypatch.setattr(plaud, "me", lambda: calls.append(True))
    report = doctor.check()
    assert report["checks"]["plaud"] == report["checks"]["GPU"] == "ok"
    assert report["checks"]["ffmpeg"] == "not needed"
    assert report["checks"]["providers"] == "ok: claude"
    assert "missing" in report["checks"]["parakeet_dir"] and "fetch model" in report["checks"]["diar_embedding"]
    assert not list(tmp_path.iterdir())
    monkeypatch.setattr(server, "_doctor_cache", report)
    with TestClient(server.app) as client:
        assert client.get("/api/state").json()["doctor"] == report
        assert client.get("/api/state").json()["doctor"] == report
    assert len(calls) == 1


def test_second_server_exits_before_touching_vault(monkeypatch, capsys):
    import errno
    class TakenSocket:
        def bind(self, address):
            raise OSError(errno.WSAEADDRINUSE, "taken")
        def close(self):
            pass
    monkeypatch.setattr(server.socket, "socket", TakenSocket)
    def forbidden():
        raise AssertionError("second server touched the vault")
    monkeypatch.setattr(vault, "seed", forbidden)
    server.main()
    assert "already running at" in capsys.readouterr().out


def test_confirm_speaker_count_preserves_names(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "BASE", tmp_path / "vault")
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    rec = vault.new_recording({"id": "of_" + "f" * 32, "title": "Count", "date": "2026-11-17", "duration": "1m"})
    rec["speakers"] = {"S1": {"name": "Alice"}}
    vault.save(rec)
    with TestClient(server.app) as client:
        for count, expected in ((3, 3), (20, 20), (0, None)):
            response = client.post("/api/speakers", json={"id": rec["id"], "true_speakers": count})
            assert response.status_code == 200
            current = vault.find(rec["id"])
            assert current["true_speakers"] == expected
            assert current["speakers"] == {"S1": {"name": "Alice"}}
            assert current["speakers_rev"] == rec["speakers_rev"]
        for count in (-1, 1.5, "3", None, True):
            assert client.post("/api/speakers", json={"id": rec["id"], "true_speakers": count}).status_code == 400
        assert client.post("/api/speakers", json={"id": rec["id"], "names": {"S1": "Bob"}, "true_speakers": 2}).status_code == 200
        current = vault.find(rec["id"])
        assert current["true_speakers"] == 2 and current["speakers"]["S1"]["name"] == "Bob"


def test_audio_route_serves_range(tmp_path, monkeypatch):
    from test_speakers import correction_recording
    rec = correction_recording(tmp_path, monkeypatch)
    (rec["_dir"] / (rec["stem"] + ".ogg")).write_bytes(b"0123456789")
    with TestClient(server.app) as client:
        response = client.get("/api/audio/" + rec["id"], headers={"Range": "bytes=2-5"})
        assert response.status_code == 206 and response.content == b"2345"
        assert response.headers["content-range"] == "bytes 2-5/10"
        assert response.headers["content-type"] == "audio/ogg"
        (rec["_dir"] / (rec["stem"] + ".ogg")).write_bytes(b"ID3-tutorial")
        response = client.get("/api/audio/" + rec["id"], headers={"Range": "bytes=0-2"})
        assert (response.status_code, response.content, response.headers["content-type"]) == (206, b"ID3", "audio/mpeg")
        detail = client.get("/api/recordings/" + rec["id"]).json()
        assert "words" not in detail and "_dir" not in detail
        assert detail["closest_voices"]["S1"] == "S2"
        assert client.get("/api/audio/bad").status_code == 400


def test_same_name_offers_merge(tmp_path, monkeypatch):
    from test_speakers import correction_recording
    rec = correction_recording(tmp_path, monkeypatch)
    monkeypatch.setattr(jobs, "DATA", tmp_path / "jobs")
    with TestClient(server.app) as client:
        result = client.post("/api/speakers", json={"id": rec["id"], "names": {"S1": "Alice", "S2": "Alice"}})
        assert result.json() == {"ok": True, "merge_offer": ["S2", "S1"]}
        assert vault.find(rec["id"])["speakers"]["S2"]["name"] == "Alice"
        assert not jobs.recent()
        # The edited voice is the source even when it occurs first in the stored map.
        result = client.post("/api/speakers", json={"id": rec["id"], "names": {"S1": "Bob", "S2": "Bob"}})
        assert result.json()["merge_offer"] == ["S2", "S1"]
        result = client.post("/api/speakers", json={"id": rec["id"], "names": {"S1": "Alice", "S2": "Bob"}})
        result = client.post("/api/speakers", json={"id": rec["id"], "names": {"S1": "Bob", "S2": "Bob"}})
        assert result.json()["merge_offer"] == ["S1", "S2"]


def test_fix_rejects_bad_span(tmp_path, monkeypatch):
    from test_speakers import correction_recording
    rec = correction_recording(tmp_path, monkeypatch)
    monkeypatch.setattr(jobs, "DATA", tmp_path / "jobs")
    with TestClient(server.app) as client:
        for data in ({"s": 0, "e": 61, "spk": "S1"}, {"s": 0, "e": 1, "spk": []}, {"s": 3, "e": 2, "spk": "S1"}):
            assert client.post("/api/fix", json={"id": rec["id"], **data}).status_code == 400
        assert client.post("/api/fix", json={"id": rec["id"], "s": 2, "e": 3, "spk": "new"}).status_code == 200
        assert client.post("/api/unfix", json={"id": rec["id"], "index": 0}).status_code == 200
        assert client.post("/api/merge", json={"id": rec["id"], "src": "S2", "dst": "S1"}).status_code == 200
        assert client.post("/api/unmerge", json={"id": rec["id"], "src": "S2"}).status_code == 200
        job = jobs.submit("respeak", rec["id"], {"num_speakers": 0})
        jobs.next_job()
        for route, data in (("fix", {"s": 0, "e": 1, "spk": "S1"}), ("speakers", {"true_speakers": 2}), ("merge", {"src": "S2", "dst": "S1"})):
            response = client.post("/api/" + route, json={"id": rec["id"], **data})
            assert response.status_code == 409 and response.json()["detail"] == "busy"
        jobs.finish(job["id"])


DASHBOARD = Path(server.__file__).parent / "dashboard.html"


def test_dashboard_calls_every_route():
    html = DASHBOARD.read_text(encoding="utf-8")
    # every API path the page used before the redesign (ticket 10, Part B), plus note reader, glossary, and provider/plaud controls
    for path in ("/api/state", "/api/recordings/", "/api/audio/", "/api/notes/", "/api/check_providers",
                 "/api/generate", "/api/import", "/api/merge", "/api/move", "/api/refresh", "/api/regenerate",
                 "/api/respeak", "/api/retranscribe", "/api/retry", "/api/speakers", "/glossary`",
                 "/api/plaud/", "/api/provider_key", "/api/provider_model", "/favicon.svg"):
        assert path in html, path
    for route in ("suggestion", "unmerge", "fix", "unfix"):  # sent through edit(route, ...) by the speaker controls
        assert f'edit("{route}"' in html, route


def test_favicon_and_recording_list_no_hover():
    html = DASHBOARD.read_text(encoding="utf-8")
    assert '<link rel="icon" type="image/svg+xml" href="/favicon.svg">' in html
    assert 'id="theme-btn"' in html and 'data-theme="dark"' in html
    assert 'data-pmodel=' not in html  # top-bar AI popover is status-only; model choice lives in '+' New note
    assert ".rec[draggable=true]:hover" not in html
    assert ".rec:hover { background:none; }" in html
    assert ".rec.on, .rec.on:hover { background:var(--acc-soft); }" in html
    with TestClient(server.app) as client:
        res = client.get("/favicon.svg")
        assert res.status_code == 200
        assert "image/svg+xml" in res.headers["content-type"]
        assert "<svg" in res.text


def test_plaud_details_and_import_plaud_route(tmp_path, monkeypatch):
    from app import plaud
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    monkeypatch.setattr(vault, "BASE", tmp_path / "vault")
    monkeypatch.setattr(server, "_plaud_details_cache", {})
    vault.seed()
    rec_id = "of_" + "7" * 32
    calls = []
    monkeypatch.setattr(plaud, "details", lambda i: calls.append(i) or {
        "title": "Parsed", "start_at": "2026-11-10T10:00:00", "has_transcript": True, "has_summary": True
    })
    monkeypatch.setattr(plaud, "list_recordings", lambda date_from=None: [])
    seen = []
    monkeypatch.setattr(server.pipeline, "ingest_plaud", lambda i, **kw: seen.append(i))
    with TestClient(server.app) as client:
        assert client.get(f"/api/plaud/{rec_id}").json()["has_transcript"] is True
        assert client.get(f"/api/plaud/{rec_id}").json()["has_summary"] is True
        assert len(calls) == 1  # cached
        assert client.post("/api/refresh", json={}).status_code == 200
        assert client.get(f"/api/plaud/{rec_id}").status_code == 200
        assert len(calls) == 2  # cleared on refresh
        assert client.get("/api/plaud/bad").status_code == 400
        assert client.post("/api/import", json={"id": rec_id, "source": "nope"}).status_code == 400
        j = client.post("/api/import", json={"id": rec_id, "source": "plaud"})
        assert j.status_code == 200 and j.json()["kind"] == "import_plaud"
        # Duplicate local import while import_plaud is queued returns the same job.
        dup = client.post("/api/import", json={"id": rec_id})
        assert dup.status_code == 200 and dup.json()["id"] == j.json()["id"]
        server._run_job(jobs.next_job())
        assert seen == [rec_id]


def test_dashboard_loads_nothing_external():
    import re
    assert not re.findall(r"https?://", DASHBOARD.read_text(encoding="utf-8"))


def test_standard_summary_and_newnote_panel(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "BASE", tmp_path / "Plaud")
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    monkeypatch.setattr(server, "VAULT", tmp_path)
    vault.seed()
    with TestClient(server.app) as client:
        st = client.get("/api/state").json()
        assert st["blueprints"][0] == "Standard summary"
        assert "Meeting minutes" not in st["blueprints"]
        assert st["blueprint_meta"]["Standard summary"]["auto"] is True
    html = DASHBOARD.read_text(encoding="utf-8")
    assert '<span class="label">Provider</span>' in html
    assert "Written by</span>" not in html
    assert "stripProvider" in html and "nn-default" in html and "nn-scroll" in html


def test_player_waits_for_the_import_download():
    html = DASHBOARD.read_text(encoding="utf-8")
    start = html.index('if (r.stage !== "new")')
    assert 'player.src = `/api/audio/' in html[start:html.index('\n  }', start)]


def test_glossary_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "BASE", tmp_path / "Plaud")
    monkeypatch.setattr(server, "VAULT", tmp_path)
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    vault.seed()
    rec_id = "of_" + "d" * 32
    vault.new_recording({"id": rec_id, "title": "Words", "date": "2026-11-17", "duration": "1m"})
    url = f"/api/recordings/{rec_id}/glossary"
    with TestClient(server.app) as client:
        assert client.get(url).json() == {"folder": "Inbox", "inbox": True, "sent": 0, "words": []}
        added = client.post(url, json={"action": "add", "term": "CGH"})
        assert added.status_code == 200 and [(w["term"], w["group"]) for w in added.json()["words"]] == [("CGH", "added")]
        assert client.get("/api/state").json()["glossaries"]["Inbox"] == [1, 0]
        assert client.post(url, json={"action": "delete", "term": "CGH"}).status_code == 409   # not blocked: page is stale
        for bad in ({"action": "add", "term": "a · b"}, {"action": "add"}, {"action": "drop", "term": "CGH"}):
            assert client.post(url, json=bad).status_code == 400, bad
        assert client.get("/api/recordings/nope/glossary").status_code == 400
        assert client.get(f"/api/recordings/of_{'e' * 32}/glossary").status_code == 400
