"""Sandbox setup uses only disposable vaults and settings."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_config_override_and_data_dir(tmp_path, monkeypatch):
    alternate = tmp_path / "alternate.json"
    alternate.write_text(json.dumps({"port": 8378, "data_dir": "data/sandbox/state"}))
    monkeypatch.setenv("PLAUD_CONFIG", str(alternate))
    settings = runpy.run_path(str(ROOT / "app/config.py"))
    assert settings["cfg"]["port"] == 8378
    assert settings["DATA"] == ROOT / "data/sandbox/state"
    alternate.write_text(json.dumps({"data_dir": str(tmp_path / "state")}))
    assert runpy.run_path(str(ROOT / "app/config.py"))["DATA"] == tmp_path / "state"


def test_explicit_missing_config_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAUD_CONFIG", str(tmp_path / "missing.json"))
    with pytest.raises(FileNotFoundError):
        runpy.run_path(str(ROOT / "app/config.py"))


def test_server_selects_config_before_vault_import(tmp_path, monkeypatch):
    alternate = tmp_path / "server.json"
    alternate.write_text(json.dumps({"vault": str(tmp_path / "isolated"),
                                     "data_dir": str(tmp_path / "state")}))
    monkeypatch.setenv("PLAUD_CONFIG", str(tmp_path / "wrong.json"))
    check = ("import sys; expected = sys.argv[2]; sys.argv = ['server', '--config', sys.argv[1]]; "
             "from app import server, vault; "
             "assert server.cfg['port'] == 8377; "
             "assert str(vault.BASE.parent) == expected; "
             "assert server.DATA.name == 'state'")
    result = subprocess.run([sys.executable, "-c", check, str(alternate), str(tmp_path / "isolated")], cwd=ROOT,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "isolated").exists()


def test_sandbox_copies_normal_config_and_replaces_previous(tmp_path, monkeypatch):
    from scripts.make_sandbox import make_sandbox

    source = tmp_path / "owner/Plaud/Inbox/meeting"
    source.mkdir(parents=True)
    recording = source / "recording.json"
    recording.write_text('{"id": "test"}')
    (source / "note.md").write_text("owner's note")
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in source.iterdir()}
    config = {"vault": str(tmp_path / "owner"), "host": "127.0.0.1", "poll_minutes": 17}
    (tmp_path / "config.json").write_text(json.dumps(config))
    monkeypatch.setenv("PLAUD_CONFIG", str(tmp_path / "nonexistent.json"))
    sandbox = tmp_path / "data/sandbox"
    sandbox.mkdir(parents=True)
    (sandbox / "stale.txt").write_text("old sandbox")

    assert make_sandbox(tmp_path) == (1, 2)
    assert not (sandbox / "stale.txt").exists()
    assert (sandbox / "vault/Plaud/Inbox/meeting/note.md").read_text() == "owner's note"
    settings = json.loads((sandbox / "config.json").read_text())
    assert settings == config | {"vault": str(sandbox / "vault"), "port": 8378,
                                "auto_process": False, "data_dir": "data/sandbox/state"}
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in source.iterdir()} == before


def test_sandbox_uses_defaults_without_normal_config(tmp_path, monkeypatch):
    from scripts.make_sandbox import make_sandbox

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / "Documents/Obsidian Vault/Plaud").mkdir(parents=True)
    monkeypatch.setenv("PLAUD_CONFIG", str(tmp_path / "invalid.json"))
    (tmp_path / "invalid.json").write_text("not json")
    assert make_sandbox(tmp_path) == (0, 0)
    assert os.environ["PLAUD_CONFIG"] == str(tmp_path / "invalid.json")


def test_missing_source_keeps_previous_sandbox(tmp_path):
    from scripts.make_sandbox import make_sandbox

    (tmp_path / "config.json").write_text(json.dumps({"vault": str(tmp_path / "missing")}))
    sandbox = tmp_path / "data/sandbox"
    sandbox.mkdir(parents=True)
    marker = sandbox / "keep.txt"
    marker.write_text("previous copy")
    with pytest.raises(FileNotFoundError):
        make_sandbox(tmp_path)
    assert marker.read_text() == "previous copy"


def test_sandbox_rejects_overlapping_source(tmp_path):
    from scripts.make_sandbox import make_sandbox

    sandbox = tmp_path / "data/sandbox"
    source = sandbox / "vault/Plaud"
    source.mkdir(parents=True)
    marker = source / "keep.txt"
    marker.write_text("do not delete")
    (tmp_path / "config.json").write_text(json.dumps({"vault": str(source.parent)}))
    with pytest.raises(ValueError):
        make_sandbox(tmp_path)
    assert marker.read_text() == "do not delete"


@pytest.mark.parametrize("linked", ["source", "destination", "nested_destination", "data"])
def test_sandbox_rejects_links(tmp_path, linked):
    from scripts.make_sandbox import make_sandbox

    owner = tmp_path / "owner/Plaud"
    owner.mkdir(parents=True)
    marker = owner / "keep.txt"
    marker.write_text("do not delete")
    (tmp_path / "config.json").write_text(json.dumps({"vault": str(owner.parent)}))
    target = {"source": owner / "linked", "destination": tmp_path / "data/sandbox",
              "nested_destination": tmp_path / "data/sandbox/vault/linked",
              "data": tmp_path / "data"}[linked]
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        # Junctions need no Windows developer mode or symlink privilege.
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(target), str(owner)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    else:
        target.symlink_to(owner, target_is_directory=True)
    try:
        with pytest.raises(ValueError, match="link|reparse"):
            make_sandbox(tmp_path)
        assert marker.read_text() == "do not delete"
    finally:
        if os.name == "nt":
            target.rmdir()  # Remove only this test junction, never its target.
        else:
            target.unlink()
