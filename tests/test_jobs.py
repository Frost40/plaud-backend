from concurrent.futures import ThreadPoolExecutor

import pytest

from app import jobs, pipeline, plaud, server, vault


def test_running_job_requeued_after_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DATA", tmp_path)
    job = jobs.submit("import", "one", {"model": "ensemble"})
    assert jobs.next_job()["id"] == job["id"]
    jobs.requeue_running()
    restarted = jobs.next_job()
    assert restarted["id"] == job["id"] and restarted["args"] == {"model": "ensemble"}
    assert restarted["attempts"] == 0
    jobs.finish(job["id"])
    assert jobs.next_job() is None and jobs.recent()[0]["status"] == "done"


def test_one_gpu_job_at_a_time(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DATA", tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        submitted = list(pool.map(lambda _: jobs.submit("import", "same", {}), range(8)))
    assert len({j["id"] for j in submitted}) == 1
    jobs.submit("respeak", "second", {"num_speakers": 2})
    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = [j for j in pool.map(lambda _: jobs.next_job(), range(8)) if j]
    assert len(claimed) == 1
    jobs.finish(claimed[0]["id"])
    assert jobs.next_job()["rec_id"] == "second"


def test_failed_import_resumes_from_its_stage(tmp_path, monkeypatch):
    from app import speech
    monkeypatch.setattr(vault, "BASE", tmp_path)
    vault.seed()
    meta = {"id": "of_" + "a" * 32, "title": "Example", "date": "2026-11-17", "duration": "1m"}
    downloads, transcriptions, notes = [], [], []
    monkeypatch.setattr(plaud, "list_recordings", lambda: [meta])
    monkeypatch.setattr(plaud, "details", lambda _: {"title": "Full title", "start_at": "2026-11-17T12:00:00.123456"})
    monkeypatch.setattr(plaud, "download_audio", lambda i, dest: downloads.append(i) or dest.write_bytes(b"audio"))
    monkeypatch.setattr(plaud, "marks", lambda *args: [{"t": 0, "kind": "memo", "text": "keep"}])
    monkeypatch.setattr(speech, "load_audio", lambda _: [])
    def transcribe(*args):
        transcriptions.append(True)
        if len(transcriptions) == 1:
            raise RuntimeError("transcription interrupted")
        return [{"s": 0, "e": 1, "w": "hello"}], "en"
    monkeypatch.setattr(speech, "transcribe", transcribe)
    monkeypatch.setattr(speech, "diarize", lambda *args: {
        "engine": "fake", "turns": [(0, 1, 0)], "overlap": [], "embeddings": {}})
    monkeypatch.setattr(pipeline.llm, "run", lambda *args: notes.append(True) or "## TL;DR\n## Decisions\n## Action items\n## Discussion")
    with pytest.raises(RuntimeError, match="interrupted"):
        pipeline.ingest(meta["id"], "large-v3-turbo", 2, lambda _: None)
    rec = vault.find(meta["id"])
    assert rec["stage"] == "downloaded" and rec["error"]["stage"] == "transcribe"
    assert rec["error"]["attempts"] == 1 and rec["marks"][0]["text"] == "keep"
    assert rec["start_at"] == "2026-11-17T12:00:00"
    pipeline.ingest(meta["id"], "large-v3", 5, lambda _: None)
    pipeline.resume(meta["id"], lambda _: None)
    rec = vault.find(meta["id"])
    assert rec["stage"] == "done" and rec["error"] is None
    assert len(downloads) == len(notes) == 1 and len(transcriptions) == 2
    assert rec["model"] == "large-v3-turbo" and rec["num_speakers"] == 2


def test_notes_retry_only_failed_blueprints(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "BASE", tmp_path)
    vault.seed()
    (tmp_path / "_Blueprints/_cascade.md").unlink(missing_ok=True)
    rec = vault.new_recording({"id": "of_" + "b" * 32, "title": "Notes", "date": "2026-11-17", "duration": "1m"})
    rec["stage"] = "speakers"
    vault.save(rec)
    (tmp_path / "_Blueprints/A failing.md").write_text("---\nauto: true\n---\nFAIL", encoding="utf-8")
    prompts = []
    def provider(_, prompt):
        prompts.append(prompt)
        if "FAIL" in prompt and len(prompts) == 1:
            raise RuntimeError("usage limit")
        return "## TL;DR\n## Decisions\n## Action items\n## Discussion"
    monkeypatch.setattr(pipeline.llm, "run", provider)
    with pytest.raises(RuntimeError, match="usage limit"):
        pipeline.resume(rec["id"], lambda _: None)
    assert len(vault.find(rec["id"])["notes"]) == 1 and len(prompts) == 2
    pipeline.resume(rec["id"], lambda _: None)
    assert len(prompts) == 3 and "FAIL" in prompts[-1]
    assert len(vault.find(rec["id"])["notes"]) == 2


def test_auth_failure_pauses_without_using_attempts(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    monkeypatch.setattr(vault, "BASE", tmp_path / "vault")
    monkeypatch.setattr(server, "_plaud_cache", {"list": [], "error": "", "at": 0})
    def expired(*args, **kwargs):
        raise RuntimeError("AUTH_FAILED")
    monkeypatch.setattr(pipeline, "ingest", expired)
    jobs.submit("import", "one", {})
    jobs.submit("import", "two", {})
    server._run_job(jobs.next_job())
    assert all(j["status"] == "paused" and j["attempts"] == 0 for j in jobs.recent())
    monkeypatch.setattr(plaud, "me", lambda: "ok")
    monkeypatch.setattr(plaud, "list_recordings", lambda date_from=None: [])
    server._poll_once("2026-11-17")
    assert all(j["status"] == "queued" and j["attempts"] == 0 for j in jobs.recent())


def test_gpu_error_is_not_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    monkeypatch.setattr(vault, "BASE", tmp_path / "vault")
    monkeypatch.setattr(server, "_plaud_cache", {"list": [], "error": "", "at": 0})
    monkeypatch.setattr(plaud, "list_recordings", lambda date_from=None: [])
    def oom(*args, **kwargs):
        raise RuntimeError("CUDA out of memory")
    monkeypatch.setattr(pipeline, "ingest", oom)
    job = jobs.submit("import", "one", {})
    server._run_job(jobs.next_job())
    server._poll_once("2026-11-17")
    assert jobs.recent()[0]["status"] == "failed" and jobs.next_job() is None
    assert jobs.retry(job["id"])["attempts"] == 0


def test_backoff_is_bounded_and_poller_does_not_bypass_it(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    monkeypatch.setattr(vault, "BASE", tmp_path / "vault")
    monkeypatch.setattr(server, "_plaud_cache", {"list": [], "error": "", "at": 0})
    monkeypatch.setattr(plaud, "list_recordings", lambda date_from=None: [])
    clock = [1000]
    monkeypatch.setattr(jobs.time, "time", lambda: clock[0])
    rec = vault.new_recording({"id": "of_" + "c" * 32, "title": "Retry", "date": "2026-11-17", "duration": "1m"})
    jobs.submit("resume", rec["id"], {})
    for delay in (300, 1800, 7200, None):
        job = jobs.next_job()
        assert pipeline.retry_delay("network failed", job["attempts"]) == delay
        jobs.fail(job["id"], "network failed", delay)
        server._poll_once("2026-11-17")
        assert len(jobs.recent()) == 1 and jobs.next_job() is None
        clock[0] += delay or 10000
    assert jobs.next_job() is None


def test_speakers_failure_keeps_saved_transcription(tmp_path, monkeypatch):
    from app import speech
    monkeypatch.setattr(vault, "BASE", tmp_path)
    rec = vault.new_recording({"id": "of_" + "d" * 32, "title": "Speakers", "date": "2026-11-17", "duration": "1m"})
    rec["stage"] = "downloaded"
    vault.save(rec)
    monkeypatch.setattr(speech, "load_audio", lambda _: [])
    monkeypatch.setattr(speech, "transcribe", lambda *args: ([{"s": 0, "e": 1, "w": "hello"}], "en"))
    def fail(*args):
        raise RuntimeError("speakers interrupted")
    monkeypatch.setattr(speech, "diarize", fail)
    with pytest.raises(RuntimeError):
        pipeline.resume(rec["id"], lambda _: None)
    assert vault.find(rec["id"])["stage"] == "transcribed"
    monkeypatch.setattr(speech, "transcribe", fail)
    monkeypatch.setattr(speech, "diarize", lambda *args: {
        "engine": "fake", "turns": [(0, 1, 0)], "overlap": [], "embeddings": {}})
    pipeline.resume(rec["id"], lambda _: None)
    assert vault.find(rec["id"])["stage"] == "done"


def test_expired_login_does_not_block_local_stages(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    monkeypatch.setattr(vault, "BASE", tmp_path / "vault")
    monkeypatch.setattr(server, "_plaud_cache", {"list": [], "error": "AUTH_FAILED", "at": 0})
    def expired():
        raise RuntimeError("AUTH_FAILED")
    monkeypatch.setattr(plaud, "me", expired)
    rec = vault.new_recording({"id": "of_" + "e" * 32, "title": "Local", "date": "2026-11-17", "duration": "1m"})
    rec["stage"] = "speakers"
    vault.save(rec)
    download = jobs.submit("import", "remote", {})
    server._poll_once("2026-11-17")
    assert next(j for j in jobs.recent() if j["id"] == download["id"])["status"] == "paused"
    local = jobs.next_job()
    assert local["rec_id"] == rec["id"]
    server._run_job(local)
    assert vault.find(rec["id"])["stage"] == "done"


def test_distinct_notes_are_not_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DATA", tmp_path)
    a = jobs.submit("generate", "one", {"blueprint": "A", "provider": "claude"})
    b = jobs.submit("generate", "one", {"blueprint": "B", "provider": "claude"})
    assert a["id"] != b["id"]
    assert jobs.submit("generate", "one", {"provider": "claude", "blueprint": "A"})["id"] == a["id"]
    assert len(jobs.recent(1)) == 2  # Live jobs stay visible even outside the history limit.


def test_job_progress_snapshot_and_speech_callback(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app import speech

    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    monkeypatch.setattr(vault, "BASE", tmp_path / "vault")
    monkeypatch.setattr(server, "_plaud_cache", {
        "list": [{"id": "of_" + "9" * 32, "title": "Long", "date": "2026-11-17", "duration": "10m"}],
        "error": "", "at": 0,
    })
    seen_snaps = []

    def fake_ingest(rec_id, model, num_speakers, log):
        log("downloading audio")
        seen_snaps.append(server._progress_snapshot(job["id"]))
        log("transcribing with large-v3-turbo (0 glossary terms)")
        log.progress(0.5)
        seen_snaps.append(server._progress_snapshot(job["id"]))

    monkeypatch.setattr(server.pipeline, "ingest", fake_ingest)
    job = jobs.submit("import", "of_" + "9" * 32, {"model": "large-v3-turbo", "num_speakers": 0})
    server._run_job(jobs.next_job())
    assert server._progress_snapshot(job["id"]) is None
    assert len(seen_snaps) == 2
    assert seen_snaps[0]["stage"] == "download" and seen_snaps[0]["steps"] == 4 and seen_snaps[0]["eta_s"] >= 1
    assert seen_snaps[1]["stage"] == "transcribe" and seen_snaps[1]["step"] == 2
    assert seen_snaps[1]["pct"] > seen_snaps[0]["pct"]

    class FakeModel:
        def transcribe(self, *args, **kwargs):
            segs = [SimpleNamespace(end=5.0, words=[SimpleNamespace(start=0.0, end=1.0, word=" hi")]),
                    SimpleNamespace(end=10.0, words=[SimpleNamespace(start=5.0, end=9.0, word=" there")])]
            return segs, SimpleNamespace(language="en")

    monkeypatch.setattr(speech, "_whisper", lambda name: FakeModel())
    fracs = []
    words, lang = speech.transcribe([0.0] * 160000, "large-v3-turbo", on_progress=fracs.append)
    assert lang == "en" and len(words) == 2 and fracs == [0.5, 1.0]


def test_progress_follows_measured_work_and_learns_speed(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DATA", tmp_path)
    monkeypatch.setattr(vault, "BASE", tmp_path / "vault")
    monkeypatch.setattr(server, "_rates", dict(server._DEFAULT_RATES, note=10.0))
    monkeypatch.setattr(server, "_plaud_cache", {"list": [{"id": "r", "duration": "10m"}], "error": "", "at": 0})
    clock = [1000.0]
    monkeypatch.setattr(server.time, "time", lambda: clock[0])
    snaps = []

    def fake_generate(rec_id, blueprint, provider, log):
        log("writing 'A' with claude")
        clock[0] += 5
        snaps.append(server._progress_snapshot(job["id"]))
        clock[0] += 25                           # past the usual 10 s, no signal from the AI call
        snaps.append(server._progress_snapshot(job["id"]))

    monkeypatch.setattr(server.pipeline, "generate", fake_generate)
    job = jobs.submit("generate", "r", {"blueprint": "A", "provider": "claude"})
    server._run_job(jobs.next_job())
    assert snaps[0]["eta_s"] == 5 and not snaps[0]["overdue"]
    assert snaps[1]["overdue"] and snaps[1]["pct"] >= snaps[0]["pct"]
    assert server._rates["note"] == 20.0         # halfway from 10 s to the 30 s it took
    assert '"note": 20.0' in (tmp_path / "timings.json").read_text()

    # Measured fraction: the ETA follows the real pace, and the bar never goes back.
    server._progress[99] = {"msg": "", "started": 0.0, "stage_started": 0.0, "entered": True, "notes_written": 0,
                            "stage_idx": 0, "stage_frac": None, "stages": [("transcribe", "T", 100.0, "x", 1)]}
    clock[0] = 20.0                                  # 20 s loading the model, no report yet
    before = server._progress_snapshot(99)
    server._set_progress_frac(99, 0.01)
    first = server._progress_snapshot(99)
    assert before["eta_s"] == first["eta_s"] == 80 and first["pct"] == before["pct"] == 20.0   # no jump
    clock[0] = 30.0
    server._set_progress_frac(99, 0.505)             # half the real work done in 10 s: about 10 s to go
    mid = server._progress_snapshot(99)
    assert 60 <= mid["pct"] <= 61 and mid["eta_s"] == 25   # halfway between the usual 40 s and the pace's 10 s
    server._set_progress_frac(99, 0.3)               # a late, smaller report is ignored
    assert server._progress_snapshot(99)["pct"] == mid["pct"]
    server._progress.pop(99)
