"""Copy the normal vault into data/sandbox without writing to the source."""
import datetime as dt
import json
import os
from pathlib import Path
import runpy
import shutil
import stat


ROOT = Path(__file__).resolve().parents[1]


def _reject_link(path: Path) -> None:
    if path.is_symlink() or (path.exists() and
            getattr(path.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise ValueError(f"Refusing link or reparse point: {path}")


def source_snapshot(source: Path) -> dict:
    """Validate a tree without following links and collect source comparison metadata."""
    for path in (source, *source.parents):
        _reject_link(path)
    files = recordings = newest = 0
    for directory, dirs, names in os.walk(source):
        for name in dirs + names:
            _reject_link(Path(directory) / name)
        for name in names:
            files += 1
            recordings += name == "recording.json"
            newest = max(newest, (Path(directory) / name).stat().st_mtime_ns)
    return {"recordings": recordings, "files": files, "newest_mtime_ns": newest,
            "newest_utc": dt.datetime.fromtimestamp(newest / 1e9, dt.timezone.utc).isoformat()}


def make_sandbox(root: Path = ROOT) -> tuple[int, int]:
    root = root.resolve()
    # Load the normal config and its defaults even when launched from a sandbox shell.
    previous = os.environ.pop("PLAUD_CONFIG", None)
    try:
        defaults = runpy.run_path(str(ROOT / "app/config.py"))["DEFAULTS"]
    finally:
        if previous is not None:
            os.environ["PLAUD_CONFIG"] = previous
    normal = root / "config.json"
    config = json.loads(normal.read_text(encoding="utf-8")) if normal.exists() else {}
    settings = defaults | config
    folder = settings["base_folder"]
    if folder in ("", ".", "..") or Path(folder).name != folder:
        raise ValueError("base_folder must be one folder name")
    source = Path(settings["vault"]) / folder
    sandbox = root / "data/sandbox"
    for path in (sandbox, *sandbox.parents, source, *source.parents):
        _reject_link(path)
    source, sandbox = source.resolve(), sandbox.resolve()
    if sandbox != root / "data/sandbox" or source.is_relative_to(sandbox) or sandbox.is_relative_to(source):
        raise ValueError("Sandbox and source must be separate directories")
    if not source.is_dir():
        raise FileNotFoundError(f"Vault folder not found: {source}")
    before = source_snapshot(source)
    if sandbox.exists():
        source_snapshot(sandbox)  # Reject nested junctions before recursive removal.
        shutil.rmtree(sandbox)
    shutil.copytree(source, sandbox / "vault" / folder)
    config.update(vault=str(sandbox / "vault"), port=8378, auto_process=False,
                  data_dir="data/sandbox/state")
    (sandbox / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    after = source_snapshot(source)
    (sandbox / "source_snapshot.json").write_text(json.dumps(before, indent=2) + "\n", encoding="utf-8")
    print(f"Copied {before['recordings']} recordings and {before['files']} files to {sandbox}")
    print(f"Source newest file UTC before: {before['newest_utc']}; after: {after['newest_utc']}")
    if before != after:
        raise RuntimeError("Source changed while copying; run again when vault is idle")
    return before["recordings"], before["files"]


if __name__ == "__main__":
    make_sandbox()
