"""Offline unit tests and CLI injection checks for AI providers."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from fastapi.testclient import TestClient
import httpx
import pytest

from app import config, doctor, ensemble, jobs, llm, pipeline, plaud, server, vault


ROOT = Path(__file__).resolve().parents[1]
FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_cli.py"


def test_cli_provider_reads_stdin_and_output_file(tmp_path, monkeypatch):
    monkeypatch.setitem(
        config.cfg["providers"],
        "fake_file",
        {"type": "cli", "cmd": [sys.executable, str(FAKE_CLI), "--out", "{out}", "--echo-cwd"]},
    )
    monkeypatch.setitem(
        config.cfg["providers"],
        "fake_stdout",
        {"type": "cli", "cmd": [sys.executable, str(FAKE_CLI), "--echo-cwd"]},
    )

    out_file_res = llm.run("fake_file", "hello from stdin — è più ⭐")
    assert "PROMPT=hello from stdin — è più ⭐" in out_file_res
    cwd_part = out_file_res.split("|", 1)[0].removeprefix("CWD=")
    assert Path(cwd_part).resolve() != ROOT.resolve()

    stdout_res = llm.run("fake_stdout", "second prompt — ⇄")
    assert "PROMPT=second prompt — ⇄" in stdout_res


def test_openai_provider_with_mock_transport(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content.decode("utf-8"))
        if seen["body"]["messages"][0]["content"] == "rate":
            return httpx.Response(429, text='{"error": {"message": "Rate limit reached"}}')
        if seen["body"]["messages"][0]["content"] == "auth":
            return httpx.Response(401, text='{"error": {"message": "Incorrect API key provided"}}')
        if seen["body"]["messages"][0]["content"] == "empty":
            return httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "  OK from API  "}}]})

    monkeypatch.setenv("TEST_OPENAI_KEY", "sk-test-123")
    monkeypatch.setitem(
        config.cfg["providers"],
        "fake_api",
        {"type": "openai", "base_url": "https://api.example.invalid/v1/", "model": "gpt-test",
         "api_key_env": "TEST_OPENAI_KEY"},
    )
    monkeypatch.setattr(llm, "HTTP_TRANSPORT", httpx.MockTransport(handler))

    assert llm.run("fake_api", "Reply OK") == "OK from API"
    assert seen["url"] == "https://api.example.invalid/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test-123"
    assert seen["body"] == {"model": "gpt-test", "messages": [{"role": "user", "content": "Reply OK"}]}

    with pytest.raises(llm.ProviderError) as exc_limit:
        llm.run("fake_api", "rate")
    assert exc_limit.value.kind == "limit"

    with pytest.raises(llm.ProviderError) as exc_auth:
        llm.run("fake_api", "auth")
    assert exc_auth.value.kind == "auth"
    assert "sign in to fake_api again" in str(exc_auth.value)

    with pytest.raises(llm.ProviderError) as exc_empty:
        llm.run("fake_api", "empty")
    assert exc_empty.value.kind == "other"

    monkeypatch.delitem(config.cfg["providers"]["fake_api"], "api_key_env")
    assert llm.is_installed("fake_api")
    assert llm.run("fake_api", "Reply OK") == "OK from API"
    assert seen["auth"] is None


def test_ensemble_and_notes_use_the_chosen_provider(tmp_path, monkeypatch):
    from app import speech

    # 1. No module outside config.py hardwires a provider name.
    known_providers = set(config.DEFAULTS["providers"])
    for path in (ROOT / "app").glob("*.py"):
        if path.name == "config.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in known_providers, f"{path.name}:{node.lineno} names {node.value!r}"

    # 2. Config default for arbiter_provider tracks default_provider unless overridden.
    assert config.cfg["arbiter_provider"] == config.cfg["default_provider"]

    # 3. Runtime calls route ensemble to arbiter_provider and notes to default_provider / blueprint provider.
    monkeypatch.setattr(vault, "BASE", tmp_path)
    vault.seed()
    (tmp_path / "_Blueprints/_cascade.md").unlink(missing_ok=True)
    (tmp_path / "_Blueprints/Custom.md").write_text("---\nauto: true\nprovider: custom_bp_prov\n---\nWrite", encoding="utf-8")
    (tmp_path / "parakeet").mkdir()
    monkeypatch.setitem(pipeline.cfg, "parakeet_dir", str(tmp_path / "parakeet"))
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    monkeypatch.setitem(pipeline.cfg, "default_provider", "custom_notes_prov")
    monkeypatch.setitem(pipeline.cfg, "arbiter_provider", "custom_arbiter_prov")
    monkeypatch.setitem(ensemble.cfg, "arbiter_provider", "custom_arbiter_prov")
    monkeypatch.setitem(pipeline.cfg, "ensemble_languages", ["it"])

    calls = []
    def fake_run(provider, prompt):
        calls.append((provider, prompt))
        if "You are fixing an automatic transcript" in prompt:
            return "1|ciao mondo"
        return "## TL;DR\n## Decisions\n## Action items\n## Discussion"
    monkeypatch.setattr(llm, "run", fake_run)
    monkeypatch.setattr(speech, "load_audio", lambda _: [])
    monkeypatch.setattr(speech, "transcribe", lambda *a: ([{"s": 0.0, "e": 1.0, "w": " ciao"}, {"s": 1.0, "e": 2.0, "w": " mondo"}], "it"))
    monkeypatch.setattr(speech, "transcribe_parakeet", lambda _: [{"s": 0.0, "e": 1.0, "w": " ciao"}, {"s": 1.0, "e": 2.0, "w": " mondo"}])
    monkeypatch.setattr(speech, "diarize", lambda *a: {"engine": "fake", "turns": [(0.0, 2.0, 0)], "overlap": [], "embeddings": {}})

    rec = vault.new_recording({"id": "of_" + "a" * 32, "title": "Routing", "date": "2026-11-18", "duration": "1m"})
    rec["stage"] = "downloaded"
    rec["model"] = "ensemble"
    (rec["_dir"] / f"{rec['stem']}.ogg").write_bytes(b"audio")
    vault.save(rec)

    pipeline.resume(rec["id"], lambda _: None)
    assert calls[0][0] == "custom_arbiter_prov"
    assert sorted(p for p, _ in calls[1:]) == ["custom_bp_prov", "custom_notes_prov"]

    # Direct ensemble.fuse call without explicit provider also uses arbiter_provider.
    calls.clear()
    a = [{"s": 0.0, "e": 1.0, "w": " ciao"}]
    ensemble.fuse([a, a], [])
    assert calls[0][0] == "custom_arbiter_prov"


@pytest.mark.parametrize("provider,exit_code,text,expected", [
    # Claude saved / binary messages
    ("claude", 1, "You've hit your limit · resets 3pm (Europe/Rome)", "limit"),
    ("claude", 1, "API Error: 429 {\"type\":\"error\",\"error\":{\"type\":\"rate_limit_error\"}}", "limit"),
    ("claude", 1, "Credit balance is too low", "limit"),
    ("claude", 1, "Not logged in · Please run /login", "auth"),
    ("claude", 1, "Error: OAuth token revoked. Please run claude auth login.", "auth"),
    ("claude", 1, "Invalid API key · Fix external API key", "auth"),
    ("claude", 1, "Auth token expired or invalid", "auth"),
    ("claude", 1, "Credit balance too low", "limit"),
    # Codex saved / binary messages
    ("codex", 1, "ERROR: You've hit your usage limit. Try again later.", "limit"),
    ("codex", 1, "stream error: usage_limit_reached; rate_limit exceeded", "limit"),
    ("codex", 1, "Not logged in. Please run `codex login`.", "auth"),
    ("codex", 1, "Open Codex to sign in.", "auth"),
    ("codex", 1, "ChatGPT account ID not available, please re-run `codex login`", "auth"),
    ("codex", 1, "Your access token could not be refreshed. Please log out and sign in again.", "auth"),
    # Antigravity (agy) saved / binary messages
    ("antigravity", 1, 'AGY_ERROR: {"status":"RESOURCE_EXHAUSTED","message":"QUOTA_EXHAUSTED"}', "limit"),
    ("antigravity", 1, "Usage limit reached for current model.", "limit"),
    ("antigravity", 1, "Quota reached for model; MODEL_CAPACITY_EXHAUSTED", "limit"),
    ("antigravity", 1, 'AGY_ERROR: {"status":"UNAUTHENTICATED","message":"You are not logged into Antigravity."}', "auth"),
    ("antigravity", 1, "Sign in required: oauth2: token expired", "auth"),
    ("antigravity", 1, "Log in from the terminal to continue", "auth"),
    # OpenAI / multiline HTTP status codes
    ("api", 429, "Too Many Requests", "limit"),
    ("api", 401, "Unauthorized", "auth"),
    ("codex", 1, "request failed\n429", "limit"),
    ("claude", 1, "request failed\n401", "auth"),
    # Other errors must stay "other"
    ("antigravity", 3, 'AGY_ERROR: {"status":"DEADLINE_EXCEEDED","reason":"print_timeout"}', "other"),
    ("codex", 1, "network connection reset at line 429 of socket.rs", "other"),
    ("claude", 1, "upstream 529 overloaded", "other"),
])
def test_classify_limit_and_auth(provider, exit_code, text, expected):
    assert llm.classify(provider, exit_code, text) == expected


def test_provider_check_stores_status_and_filters_dashboard_menu(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(llm, "DATA", tmp_path / "state")
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    monkeypatch.setattr(vault, "BASE", tmp_path / "Plaud")
    monkeypatch.setattr(server, "VAULT", tmp_path)
    vault.seed()

    providers = {
        "good": {"type": "cli", "cmd": [sys.executable, str(FAKE_CLI), "--stdout", "OK"],
                 "check": "Reply with exactly: OK"},
        "bad_auth": {"type": "cli", "cmd": [sys.executable, str(FAKE_CLI), "--exit", "1", "--stderr", "Not logged in · Please run /login"]},
        "missing": {"type": "cli", "cmd": ["definitely-missing-cli-binary-xyz"]},
    }
    monkeypatch.setitem(config.cfg, "providers", providers)
    monkeypatch.setitem(config.cfg, "default_provider", "good")

    # Before any check, menu lists no providers.
    with TestClient(server.app) as client:
        assert client.get("/api/state").json()["providers"] == []

        # doctor --providers runs checks for installed providers and prints all configured ones.
        results = doctor.check_providers()
        assert results["good"]["ok"] is True and results["good"]["message"] == "OK"
        assert results["bad_auth"]["ok"] is False and "sign in to bad_auth again" in results["bad_auth"]["message"]
        assert results["missing"]["ok"] is False and results["missing"]["message"] == "not installed"

        saved = json.loads((tmp_path / "state" / "providers.json").read_text(encoding="utf-8"))
        assert set(saved) == {"good", "bad_auth", "missing"}
        assert saved["good"]["at"]

        state = client.get("/api/state").json()
        assert state["providers"] == ["good"]
        assert state["provider_checks"]["good"]["at"] == saved["good"]["at"]

        # Dashboard button queues a check_providers job and runs it.
        job = client.post("/api/check_providers").json()
        assert job["kind"] == "check_providers" and job["status"] == "queued"
        server._run_job(jobs.next_job())
        assert jobs.recent()[0]["status"] == "done"

    monkeypatch.setattr(sys, "argv", ["doctor", "--providers"])
    doctor.main()
    out = capsys.readouterr().out
    assert "good: ok" in out and "bad_auth: failed" in out and "missing: not installed" in out


def test_limit_waits_2h_and_auth_pauses_only_provider_note_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "DATA", tmp_path / "state")
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    monkeypatch.setattr(vault, "BASE", tmp_path / "Plaud")
    monkeypatch.setattr(server, "VAULT", tmp_path)
    monkeypatch.setattr(server, "_plaud_cache", {"list": [], "error": "", "at": 0.0})
    vault.seed()

    rec = vault.new_recording({"id": "of_" + "d" * 32, "title": "Retry Policy", "date": "2026-11-18", "duration": "1m"})
    rec["stage"] = "done"
    vault.save(rec)

    clock = [10_000.0]
    monkeypatch.setattr(jobs.time, "time", lambda: clock[0])

    providers = {
        "limit_p": {"type": "cli", "cmd": [sys.executable, str(FAKE_CLI), "--exit", "1", "--stderr", "You've hit your usage limit."]},
        "auth_p": {"type": "cli", "cmd": [sys.executable, str(FAKE_CLI), "--exit", "1", "--stderr", "Not logged in. Please run `codex login`."]},
        "ok_p": {"type": "cli", "cmd": [sys.executable, str(FAKE_CLI), "--stdout", "## TL;DR\n## Decisions\n## Action items\n## Discussion"]},
    }
    monkeypatch.setitem(config.cfg, "providers", providers)

    auth_command = providers["auth_p"]["cmd"]
    providers["auth_p"]["cmd"] = [sys.executable, str(FAKE_CLI), "--stdout", "OK"]
    assert llm.check("auth_p")["ok"]
    providers["auth_p"]["cmd"] = auth_command

    # 1. Usage limit waits 2h (7200s) and marks job with "limit".
    j_lim = jobs.submit("generate", rec["id"], {"blueprint": "Standard summary", "provider": "limit_p"})
    server._run_job(jobs.next_job())
    row_lim = next(j for j in jobs.recent() if j["id"] == j_lim["id"])
    assert row_lim["status"] == "queued"
    assert "limit" in row_lim["error"].lower()
    assert row_lim["not_before"] == clock[0] + 7200
    assert row_lim["attempts"] == 1

    # 2. Provider auth pauses only note jobs for that provider and shows "sign in to <provider> again".
    j_auth1 = jobs.submit("generate", rec["id"], {"blueprint": "Standard summary", "provider": "auth_p"})
    j_auth2 = jobs.submit("generate", rec["id"], {"blueprint": "Voice memo", "provider": "auth_p"})
    j_other = jobs.submit("generate", rec["id"], {"blueprint": "Standard summary", "provider": "ok_p"})
    j_dl = jobs.submit("import", "of_" + "e" * 32, {"model": "large-v3-turbo", "num_speakers": 0})

    # Run j_auth1 (note: j_lim has not_before > now, so next_job skips j_lim and picks j_auth1).
    server._run_job(jobs.next_job())
    recent = {j["id"]: j for j in jobs.recent()}
    assert recent[j_auth1["id"]]["status"] == "paused"
    assert recent[j_auth1["id"]]["attempts"] == 0
    assert "sign in to auth_p again" in recent[j_auth1["id"]]["error"]
    assert recent[j_auth2["id"]]["status"] == "paused"
    assert recent[j_other["id"]]["status"] == "queued"
    assert recent[j_dl["id"]]["status"] == "queued"
    assert server._plaud_cache["error"] == ""

    other_rec = vault.new_recording({"id": "of_" + "f" * 32, "title": "New note",
                                    "date": "2026-11-18", "duration": "1m"})
    with TestClient(server.app) as client:
        assert "auth_p" not in client.get("/api/state").json()["providers"]
        body = {"id": other_rec["id"], "blueprint": "Standard summary", "provider": "auth_p"}
        rejected = client.post("/api/generate", json=body)
        assert rejected.status_code == 409 and "sign in to auth_p again" in rejected.json()["detail"]
        assert client.post("/api/retry", json={"job": j_auth1["id"]}).status_code == 400
    assert not any(j["rec_id"] == other_rec["id"] for j in jobs.recent(-1))
    # Cover a job that slipped into the queue between the route's pause check and insertion.
    late = jobs.submit("generate", other_rec["id"], {"blueprint": "Standard summary", "provider": "auth_p"})

    # Plaud poll succeeding must NOT unpause provider-auth-paused jobs.
    monkeypatch.setattr(plaud, "me", lambda: "ok")
    monkeypatch.setattr(plaud, "list_recordings", lambda date_from=None: [])
    server._poll_once("2026-11-18")
    recent = {j["id"]: j for j in jobs.recent()}
    assert recent[j_auth1["id"]]["status"] == "paused"

    # Fixing auth and running check_providers unpauses those provider jobs.
    monkeypatch.setitem(providers["auth_p"], "cmd", [sys.executable, str(FAKE_CLI), "--stdout", "OK"])
    j_chk = jobs.submit("check_providers", "providers", {})
    while (next_j := jobs.next_job()) is not None:
        server._run_job(next_j)
        if next_j["id"] == j_chk["id"]:
            break
    recent = {j["id"]: j for j in jobs.recent()}
    assert recent[j_other["id"]]["status"] == "done"
    assert recent[j_chk["id"]]["status"] == "done"
    assert recent[j_auth1["id"]]["status"] == "queued"
    assert recent[j_auth2["id"]]["status"] == "queued"
    assert recent[late["id"]]["status"] == "queued"
    with TestClient(server.app) as client:
        assert "auth_p" in client.get("/api/state").json()["providers"]

    # Regenerate jobs for the failing auth provider are also paused, while other providers stay queued.
    note_ok = rec["_dir"] / f"{rec['stem']} - Voice memo (ok_p).md"
    note_auth = rec["_dir"] / f"{rec['stem']} - Standard summary (auth_p).md"
    note_ok.write_text("ok", encoding="utf-8")
    note_auth.write_text("auth", encoding="utf-8")
    rec["notes"] = [
        {"file": note_ok.name, "blueprint": "Voice memo", "provider": "ok_p", "at": "2026-11-18T10:00:00",
         "transcript_rev": 0, "speakers_rev": 0, "check_failed": []},
        {"file": note_auth.name, "blueprint": "Standard summary", "provider": "auth_p", "at": "2026-11-18T10:00:00",
         "transcript_rev": 0, "speakers_rev": 0, "check_failed": []},
    ]
    vault.save(rec)
    monkeypatch.setitem(providers["auth_p"], "cmd", [sys.executable, str(FAKE_CLI), "--exit", "1", "--stderr", "Not logged in. Please run `codex login`."])
    while next_j := jobs.next_job():
        server._run_job(next_j)
    j_regen_auth = jobs.submit("regenerate", rec["id"], {"file": note_auth.name})
    j_regen_ok = jobs.submit("regenerate", rec["id"], {"file": note_ok.name})
    server._run_job(jobs.next_job())  # runs j_regen_auth -> pauses j_regen_auth
    recent = {j["id"]: j for j in jobs.recent()}
    assert recent[j_regen_auth["id"]]["status"] == "paused"
    assert recent[j_regen_ok["id"]]["status"] == "queued"
    with TestClient(server.app) as client:
        assert client.post("/api/regenerate", json={"id": rec["id"], "file": note_auth.name}).status_code == 409

    # Limit retries are still bounded to 3 automatic retries after the initial failure.
    assert [pipeline.retry_delay(llm.ProviderError("limit_p", "limit", "limit_p limit"), a) for a in range(4)] == [7200, 7200, 7200, None]


def test_arbiter_provider_inherits_overridden_default_provider(tmp_path, monkeypatch):
    import runpy
    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text(json.dumps({"default_provider": "codex"}), encoding="utf-8")
    monkeypatch.setenv("PLAUD_CONFIG", str(cfg_file))
    loaded = runpy.run_path(str(ROOT / "app/config.py"))["cfg"]
    assert loaded["default_provider"] == "codex" and loaded["arbiter_provider"] == "codex"
    cfg_file.write_text(json.dumps({"default_provider": "codex", "arbiter_provider": "antigravity"}), encoding="utf-8")
    loaded = runpy.run_path(str(ROOT / "app/config.py"))["cfg"]
    assert loaded["default_provider"] == "codex" and loaded["arbiter_provider"] == "antigravity"


def test_resume_notes_stage_preserves_provider_error_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "DATA", tmp_path / "state")
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    monkeypatch.setattr(vault, "BASE", tmp_path / "Plaud")
    vault.seed()
    providers = {
        "limit_p": {"type": "cli", "cmd": [sys.executable, str(FAKE_CLI), "--exit", "1", "--stderr", "usage_limit_reached"]},
    }
    monkeypatch.setitem(config.cfg, "providers", providers)
    monkeypatch.setitem(config.cfg, "default_provider", "limit_p")
    rec = vault.new_recording({"id": "of_" + "f" * 32, "title": "Resume Limit", "date": "2026-11-18", "duration": "1m"})
    rec["stage"] = "speakers"
    vault.save(rec)
    j = jobs.submit("resume", rec["id"], {})
    server._run_job(jobs.next_job())
    row = jobs.recent()[0]
    assert row["status"] == "queued" and "limit" in row["error"].lower()
    assert row["not_before"] > 0 and row["attempts"] == 1
    assert vault.find(rec["id"])["stage"] == "speakers"


def test_resume_multiple_failed_blueprints_preserve_limit_and_auth(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "DATA", tmp_path / "state")
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    monkeypatch.setattr(vault, "BASE", tmp_path / "Plaud")
    vault.seed()
    (tmp_path / "Plaud/_Blueprints/Extra auto.md").write_text("---\nauto: true\n---\nExtra", encoding="utf-8")
    providers = {
        "claude_lim": {"type": "cli", "cmd": [sys.executable, str(FAKE_CLI), "--exit", "1", "--stderr", "You've hit your limit · resets 3pm"]},
        "auth_p": {"type": "cli", "cmd": [sys.executable, str(FAKE_CLI), "--exit", "1", "--stderr", "Not logged in · Please run /login"]},
        "err_p": {"type": "cli", "cmd": [sys.executable, str(FAKE_CLI), "--exit", "1", "--stderr", "upstream 529 overloaded"]},
    }
    monkeypatch.setitem(config.cfg, "providers", providers)
    monkeypatch.setitem(config.cfg, "default_provider", "claude_lim")
    clock = [20_000.0]
    monkeypatch.setattr(jobs.time, "time", lambda: clock[0])

    rec = vault.new_recording({"id": "of_" + "1" * 32, "title": "Multi Limit", "date": "2026-11-18", "duration": "1m"})
    rec["stage"] = "speakers"
    vault.save(rec)
    j1 = jobs.submit("resume", rec["id"], {})
    server._run_job(jobs.next_job())
    row = next(j for j in jobs.recent() if j["id"] == j1["id"])
    assert row["status"] == "queued" and row["not_before"] == clock[0] + 7200 and row["attempts"] == 1
    assert pipeline.error_kind("claude_lim limit reached") == "limit"
    assert pipeline.error_kind("Meeting minutes: claude_lim limit (You've hit your limit)") == "limit"

    # When one blueprint fails with "other" and another fails with "auth", pause for auth without bumping attempts.
    (tmp_path / "Plaud/_Blueprints/Extra auto.md").write_text("---\nauto: true\nprovider: auth_p\n---\nExtra", encoding="utf-8")
    monkeypatch.setitem(config.cfg, "default_provider", "err_p")
    rec2 = vault.new_recording({"id": "of_" + "2" * 32, "title": "Multi Auth", "date": "2026-11-18", "duration": "1m"})
    rec2["stage"] = "speakers"
    vault.save(rec2)
    j2 = jobs.submit("resume", rec2["id"], {})
    server._run_job(jobs.next_job())
    row2 = next(j for j in jobs.recent() if j["id"] == j2["id"])
    assert row2["status"] == "paused" and row2["error"] == "sign in to auth_p again" and row2["attempts"] == 0


def test_unpause_provider_ignores_sql_wildcards(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    j_under = jobs.submit("generate", "of_" + "1" * 32, {"blueprint": "A", "provider": "my_api"})
    j_other = jobs.submit("generate", "of_" + "2" * 32, {"blueprint": "A", "provider": "myXapi"})
    jobs.pause_provider("my_api", "sign in to my_api again")
    jobs.pause_provider("myXapi", "sign in to myXapi again")
    jobs.unpause_provider("my_api")
    recent = {j["id"]: j for j in jobs.recent()}
    assert recent[j_under["id"]]["status"] == "queued"
    assert recent[j_other["id"]]["status"] == "paused"


def test_cli_echoed_prompt_and_agy_stderr_handling(monkeypatch):
    huge_echo = "OpenAI Codex\nuser\nnot logged in usage limit\n" + ("speaker discussion text " * 200) + "\nERROR: connection timed out"
    monkeypatch.setitem(
        config.cfg["providers"],
        "echo_err",
        {"type": "cli", "cmd": [sys.executable, str(FAKE_CLI), "--exit", "1", "--stderr", huge_echo]},
    )
    with pytest.raises(llm.ProviderError) as exc_echo:
        llm.run("echo_err", "hello")
    assert exc_echo.value.kind == "other"

    monkeypatch.setitem(
        config.cfg["providers"],
        "agy_err",
        {
            "type": "cli",
            "format": "agy-stream-json",
            "cmd": [
                sys.executable,
                str(FAKE_CLI),
                "--stream-json",
                "--exit",
                "1",
                "--stderr",
                'AGY_ERROR: {"status":"RESOURCE_EXHAUSTED","message":"QUOTA_EXHAUSTED"}',
                "--stdout",
                '{"event":"result","result":{"status":"ERROR"}}',
            ],
        },
    )
    with pytest.raises(llm.ProviderError) as exc_agy:
        llm.run("agy_err", "hello")
    assert exc_agy.value.kind == "limit"
    assert "RESOURCE_EXHAUSTED" in str(exc_agy.value)


@pytest.mark.parametrize("provider", [name for name, p in config.DEFAULTS["providers"].items() if p["type"] == "cli"])
def test_injection_fixture_cannot_write_outside_temp(tmp_path, monkeypatch, provider):
    cmd0 = config.cfg["providers"][provider]["cmd"][0]
    if not shutil.which(cmd0):
        pytest.skip(f"{provider} CLI ({cmd0}) is not installed")

    user_temp = tmp_path / "user_temp"
    user_temp.mkdir()
    monkeypatch.setenv("TEMP", str(user_temp))
    monkeypatch.setenv("TMP", str(user_temp))
    monkeypatch.setenv("NODE_DISABLE_COMPILE_CACHE", "1")
    monkeypatch.setattr(tempfile, "tempdir", None)
    created_dirs: set[Path] = set()
    real_tempdir = tempfile.TemporaryDirectory

    class TrackingTempDir(real_tempdir):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created_dirs.add(Path(self.name).resolve())

    monkeypatch.setattr(llm.tempfile, "TemporaryDirectory", TrackingTempDir)

    def snapshot(folder: Path, ignore_runtime_cache: bool = False) -> set[tuple[str, str, int, bytes]]:
        out = set()
        skip = {"__pycache__", ".pytest_cache", "data", ".git", ".venv", ".venv-pyannote", "models"}
        for root_str, dirs, files in os.walk(folder):
            root_path = Path(root_str)
            dirs[:] = [d for d in sorted(dirs) if d not in skip]
            for d in list(dirs):
                p = root_path / d
                rel = p.relative_to(folder)
                if ignore_runtime_cache:
                    if rel.parts[0] == "node-compile-cache":
                        dirs.remove(d)
                        continue
                    if rel.parts == ("claude",):
                        continue
                    if p.resolve() in created_dirs and not any(p.iterdir()):
                        continue
                out.add((rel.as_posix(), "dir", 0, b""))
            for name in sorted(files):
                p = root_path / name
                rel = p.relative_to(folder)
                if ignore_runtime_cache and rel.parts[0] == "node-compile-cache":
                    continue
                try:
                    raw = p.read_bytes()
                    out.add((rel.as_posix(), "file", len(raw), hashlib.sha1(raw).digest()))
                except OSError:
                    pass
        return out

    project_before = snapshot(ROOT)
    temp_before = snapshot(user_temp)

    prompt = (Path(__file__).parent / "fixtures" / "injection_transcript.txt").read_text(encoding="utf-8")
    try:
        llm.run(provider, prompt)
    except llm.ProviderError as e:
        if e.kind in ("auth", "limit"):
            pytest.fail(f"{provider} failed with {e.kind}: {e}")
        # Other errors (e.g. CLI refused empty output after blocking tool) are acceptable as long as nothing wrote outside temp.

    assert snapshot(ROOT) == project_before
    assert snapshot(user_temp, ignore_runtime_cache=True) == temp_before


def test_five_providers_and_model_options():
    provs = config.DEFAULTS["providers"]
    assert list(provs) == ["claude", "codex", "antigravity", "api", "freellmapi"]
    assert provs["claude"]["models"] == ["opus", "sonnet", "haiku"]
    assert "fable" not in provs["claude"]["models"]
    for name in ("claude", "codex", "antigravity"):
        p = provs[name]
        assert p["type"] == "cli"
        assert p["models"] and p["model"] in p["models"]
        assert "{model}" in p["cmd"]
    assert provs["api"]["type"] == "openai" and provs["api"]["api_key_env"] == "OPENAI_API_KEY"
    assert provs["api"].get("dashboard_key") is True
    assert provs["freellmapi"]["type"] == "openai"
    assert provs["freellmapi"]["api_key_env"] == "FREELLMAPI_API_KEY"
    assert provs["freellmapi"]["model"] == "auto"
    assert not provs["freellmapi"].get("models")
    assert not provs["freellmapi"].get("dashboard_key")


def test_dotenv_loader_and_dashboard_api_key_management(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "DATA", tmp_path / "state")
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    monkeypatch.setattr(vault, "BASE", tmp_path / "Plaud")
    monkeypatch.setattr(server, "VAULT", tmp_path)
    monkeypatch.setattr(llm, "_ENV_STATE", None)
    env_file = tmp_path / ".env"
    env_file.write_text("# comment\nKEEP_ME=hello\nQUOTED='world'\n", encoding="utf-8")
    monkeypatch.setattr(llm, "ENV_FILE", env_file)
    monkeypatch.delenv("KEEP_ME", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    monkeypatch.delenv("TEST_DASH_KEY", raising=False)
    monkeypatch.delenv("TEST_ENV_ONLY_KEY", raising=False)
    config.load_dotenv(env_file)
    assert os.environ["KEEP_ME"] == "hello" and os.environ["QUOTED"] == "world"

    vault.seed()
    checked = []
    providers = {
        "cli_p": {"type": "cli", "cmd": [sys.executable, str(FAKE_CLI), "--stdout", "OK"]},
        "api_p": {"type": "openai", "base_url": "https://api.example.invalid/v1", "model": "gpt-5",
                  "api_key_env": "TEST_DASH_KEY", "dashboard_key": True},
        "env_only_p": {"type": "openai", "base_url": "http://localhost:3001/v1", "model": "auto",
                       "api_key_env": "TEST_ENV_ONLY_KEY"},
    }
    monkeypatch.setitem(config.cfg, "providers", providers)

    def handler(request: httpx.Request) -> httpx.Response:
        checked.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
    monkeypatch.setattr(llm, "HTTP_TRANSPORT", httpx.MockTransport(handler))

    with TestClient(server.app) as client:
        st = client.get("/api/state").json()
        assert st["provider_config"]["api_p"]["has_key"] is False
        assert st["provider_config"]["api_p"]["can_set_key"] is True
        assert st["provider_config"]["env_only_p"]["can_set_key"] is False
        assert client.post("/api/provider_key", json={"provider": "cli_p", "api_key": "abc"}).status_code == 400
        assert client.post("/api/provider_key", json={"provider": "env_only_p", "api_key": "abc"}).status_code == 400
        assert client.post("/api/provider_key", json={"provider": "api_p", "api_key": "bad\nkey"}).status_code == 400

        # Manually editing .env on disk is picked up live without restart.
        before_ns = env_file.stat().st_mtime_ns
        env_file.write_text("# comment\nKEEP_ME=hello\nTEST_ENV_ONLY_KEY=live-from-env\n", encoding="utf-8")
        os.utime(env_file, ns=(before_ns + 2_000_000, before_ns + 2_000_000))
        assert client.get("/api/state").json()["provider_config"]["env_only_p"]["has_key"] is True
        assert os.environ["TEST_ENV_ONLY_KEY"] == "live-from-env"

        res = client.post("/api/provider_key", json={"provider": "api_p", "api_key": "sk-secret-value"})
        assert res.status_code == 200 and res.json() == {"ok": True, "has_key": True}
        assert os.environ["TEST_DASH_KEY"] == "sk-secret-value"
        env_text = env_file.read_text(encoding="utf-8")
        assert "KEEP_ME=hello" in env_text and "TEST_DASH_KEY=sk-secret-value" in env_text

        # Only api_p should be queued for checking (not cli_p).
        job = jobs.next_job()
        assert job["kind"] == "check_providers" and job["args"] == {"provider": "api_p"}
        server._run_job(job)
        assert checked == ["Bearer sk-secret-value"]

        st = client.get("/api/state").json()
        assert st["provider_config"]["api_p"]["has_key"] is True
        assert "api_p" in st["providers"] and "cli_p" not in st["provider_checks"]
        assert "sk-secret-value" not in json.dumps(st)

        # Clearing removes key from env, .env, and marks provider missing key.
        clr = client.post("/api/provider_key", json={"provider": "api_p", "api_key": ""})
        assert clr.status_code == 200 and clr.json() == {"ok": True, "has_key": False}
        assert "TEST_DASH_KEY" not in os.environ
        assert "TEST_DASH_KEY" not in env_file.read_text(encoding="utf-8")
        st = client.get("/api/state").json()
        assert st["provider_config"]["api_p"]["has_key"] is False
        assert "api_p" not in st["providers"]


def test_dynamic_model_discovery_cache_and_cmd(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "DATA", tmp_path / "state")
    cache_file = tmp_path / "models_cache.json"
    cache_file.write_text(json.dumps({
        "models": [
            {"slug": "live-a", "visibility": "list"},
            {"slug": "hidden-b", "visibility": "hide"},
            {"slug": "live-c", "visibility": "list"},
        ]
    }), encoding="utf-8")
    providers = {
        "cached_p": {"type": "cli", "model": "fallback", "models": ["fallback"], "models_cache_file": str(cache_file), "cmd": ["x"]},
        "cmd_p": {"type": "cli", "model": "old", "models": ["old"],
                  "models_cmd": [sys.executable, "-c", "print('Fetching...\\nmodel-x\\tModel X\\ngemini-pro-orchestrator-x\\tOrch\\nmodel-y\\tModel Y')"],
                  "cmd": [sys.executable, str(FAKE_CLI), "--stdout", "OK"]},
    }
    monkeypatch.setitem(config.cfg, "providers", providers)
    assert llm.available_models("cached_p") == ["live-a", "live-c"]
    assert llm.selected_model("cached_p") == "live-a"
    assert llm.available_models("cmd_p") == ["old"]
    assert llm.check("cmd_p")["ok"] is True
    assert llm.available_models("cmd_p") == ["model-x", "model-y"]


def test_provider_model_selection_and_cli_flag_routing(tmp_path, monkeypatch):
    from app import notes
    monkeypatch.setattr(llm, "DATA", tmp_path / "state")
    monkeypatch.setattr(jobs, "DATA", tmp_path / "state")
    monkeypatch.setattr(vault, "BASE", tmp_path / "Plaud")
    monkeypatch.setattr(server, "VAULT", tmp_path)
    vault.seed()

    seen_cmds = []
    def fake_subproc(cmd, input, stdout, stderr, **kw):
        seen_cmds.append(cmd)
        stdout.write(b"## Core theme ## Tasks ## Ideas\nModel output")
        import subprocess
        return subprocess.CompletedProcess(cmd, 0)

    providers = {
        "cli_m": {
            "type": "cli",
            "model": "m1",
            "models": ["m1", "m2"],
            "cmd": ["fake-cli", "exec", "--model", "{model}", "-"],
        },
        "free_p": {
            "type": "openai",
            "base_url": "http://localhost:3001/v1",
            "model": "auto",
            "api_key_env": "FREELLMAPI_API_KEY",
        },
    }
    monkeypatch.setitem(config.cfg, "providers", providers)
    monkeypatch.setenv("FREELLMAPI_API_KEY", "freellmapi-test")
    monkeypatch.setattr(llm.shutil, "which", lambda name: name)
    monkeypatch.setattr(llm.subprocess, "run", fake_subproc)
    rec = vault.new_recording({"id": "of_" + "b" * 32, "title": "Models", "date": "2026-11-19", "duration": "1m"})
    rec["stage"] = "done"
    vault.save(rec)

    with TestClient(server.app) as client:
        # freellmapi-style provider without models rejects model selection.
        assert client.post("/api/provider_model", json={"provider": "free_p", "model": "auto"}).status_code == 400
        assert client.post("/api/provider_model", json={"provider": "cli_m", "model": "nope"}).status_code == 400
        assert client.post("/api/generate", json={"id": rec["id"], "blueprint": "Voice memo", "provider": "free_p", "model": "auto"}).status_code == 400

        # Selecting default model persists and flows to CLI cmd before trailing '-'.
        ok = client.post("/api/provider_model", json={"provider": "cli_m", "model": "m2"})
        assert ok.status_code == 200 and ok.json() == {"ok": True, "model": "m2"}
        assert client.get("/api/state").json()["provider_config"]["cli_m"]["selected_model"] == "m2"
        assert client.get("/api/state").json()["provider_config"]["free_p"]["models"] == []

        llm.run("cli_m", "hello")
        assert seen_cmds[-1] == ["fake-cli", "exec", "--model", "m2", "-"]

        # Per-note explicit model overrides default and is kept on regenerate.
        g = client.post("/api/generate", json={"id": rec["id"], "blueprint": "Voice memo", "provider": "cli_m", "model": "m1"})
        assert g.status_code == 200 and g.json()["args"] == {"blueprint": "Voice memo", "provider": "cli_m", "model": "m1"}
        server._run_job(jobs.next_job())
        assert seen_cmds[-1] == ["fake-cli", "exec", "--model", "m1", "-"]
        note = vault.find(rec["id"])["notes"][0]
        assert note["model"] == "m1"

        # Default is still m2, regenerating the m1 note still runs m1.
        notes.regenerate(rec["id"], note["file"], lambda _: None)
        assert seen_cmds[-1] == ["fake-cli", "exec", "--model", "m1", "-"]


def test_auto_note_cascade_fallthrough_and_parsing(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "BASE", tmp_path / "Plaud")
    vault.seed()
    assert vault.cascade() == [
        ("claude", "haiku", "medium"),
        ("codex", "gpt-6-luna", "medium"),
        ("antigravity", "gemini-4-hydrogen-medium", None),
        ("freellmapi", None, None),
    ]

    # Verify CLI reasoning effort flags are built cleanly for claude and codex.
    claude_cfg = config.DEFAULTS["providers"]["claude"]
    claude_cmd = llm._cli_cmd("claude", claude_cfg["cmd"][1:], tmp_path / "out.txt", "haiku", None, "medium", claude_cfg["effort_args"])
    assert claude_cmd[-2:] == ["--effort", "medium"]
    codex_cfg = config.DEFAULTS["providers"]["codex"]
    codex_cmd = llm._cli_cmd("codex", codex_cfg["cmd"][1:], tmp_path / "out.txt", "gpt-6-luna", None, "medium", codex_cfg["effort_args"])
    assert codex_cmd[-3:] == ["-c", 'model_reasoning_effort="medium"', "-"]

    # Bullet and numbered list formats in Obsidian also parse cleanly.
    (tmp_path / "Plaud/_Blueprints/_cascade.md").write_text(
        "# Cascade\n> comment\n\n1. claude: haiku: medium\n- codex: gpt-6-luna: medium\n* antigravity: gemini-4-hydrogen-medium\n4) freellmapi\n",
        encoding="utf-8",
    )
    assert vault.cascade() == [
        ("claude", "haiku", "medium"),
        ("codex", "gpt-6-luna", "medium"),
        ("antigravity", "gemini-4-hydrogen-medium", None),
        ("freellmapi", None, None),
    ]

    # Skip uninstalled codex, fall through claude limit -> antigravity succeeds -> freellmapi never called.
    monkeypatch.setattr(pipeline.llm, "is_installed", lambda p: p != "codex")
    tried = []
    def fake_run(provider, prompt, model=None, effort=None):
        tried.append((provider, model, effort))
        if provider == "claude":
            raise llm.ProviderError("claude", "limit", "claude limit reached")
        return "## TL;DR\nOk\n## Decisions\nNone\n## Action items\nNone\n## Discussion\nOk"
    monkeypatch.setattr(pipeline.llm, "run", fake_run)

    rec = vault.new_recording({"id": "of_" + "c" * 32, "title": "Cascade", "date": "2026-11-20", "duration": "1m"})
    rec["stage"] = "speakers"
    vault.save(rec)
    pipeline.resume(rec["id"], lambda _: None)

    assert tried == [("claude", "haiku", "medium"), ("antigravity", "gemini-4-hydrogen-medium", None)]
    done = vault.find(rec["id"])
    assert done["stage"] == "done" and len(done["notes"]) == 1
    assert done["notes"][0]["provider"] == "antigravity" and done["notes"][0]["model"] == "gemini-4-hydrogen-medium"

    # Re-running notes stage when a cascade provider already generated the note does not regenerate it.
    done["stage"] = "speakers"
    vault.save(done)
    tried.clear()
    pipeline.resume(rec["id"], lambda _: None)
    assert tried == [] and vault.find(rec["id"])["stage"] == "done"

    # If every cascade provider fails, the error propagates with ProviderError preserved.
    def all_limit(provider, prompt, model=None, effort=None):
        tried.append((provider, model, effort))
        raise llm.ProviderError(provider, "limit", f"{provider} limit reached")
    monkeypatch.setattr(pipeline.llm, "run", all_limit)
    rec2 = vault.new_recording({"id": "of_" + "d" * 32, "title": "AllFail", "date": "2026-11-20", "duration": "1m"})
    rec2["stage"] = "speakers"
    vault.save(rec2)
    with pytest.raises(llm.ProviderError) as exc:
        pipeline.resume(rec2["id"], lambda _: None)
    assert exc.value.kind == "limit"
    assert tried == [
        ("claude", "haiku", "medium"),
        ("antigravity", "gemini-4-hydrogen-medium", None),
        ("freellmapi", None, None),
    ]
