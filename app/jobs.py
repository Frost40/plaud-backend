"""Persistent single-worker queue. Connections belong to one call, never a thread pool."""
from contextlib import contextmanager
import json
import sqlite3
import time

from app.config import DATA


@contextmanager
def _db():
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA / "jobs.db", timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY, rec_id TEXT NOT NULL, kind TEXT NOT NULL,
            args_json TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            not_before REAL NOT NULL DEFAULT 0, error TEXT, created REAL NOT NULL, updated REAL NOT NULL)""")
        with con:
            yield con
    finally:
        con.close()


def _job(row):
    if row is None:
        return None
    job = dict(row)
    job["args"] = json.loads(job.pop("args_json"))
    return job


def submit(kind: str, rec_id: str, args: dict) -> dict:
    with _db() as con:
        con.execute("BEGIN IMMEDIATE")
        if kind in ("import", "import_plaud", "resume"):
            row = con.execute("""SELECT * FROM jobs WHERE rec_id=? AND kind IN ('import', 'import_plaud', 'resume')
                                 AND status IN ('queued', 'running', 'paused') ORDER BY id LIMIT 1""",
                              (rec_id,)).fetchone()
        else:
            row = con.execute("""SELECT * FROM jobs WHERE rec_id=? AND kind=? AND args_json=?
                                 AND status IN ('queued', 'running', 'paused') ORDER BY id LIMIT 1""",
                              (rec_id, kind, json.dumps(args, sort_keys=True))).fetchone()
        if row is None:
            now = time.time()
            cursor = con.execute("""INSERT INTO jobs(rec_id, kind, args_json, status, created, updated)
                                    VALUES (?, ?, ?, 'queued', ?, ?)""",
                                 (rec_id, kind, json.dumps(args, sort_keys=True), now, now))
            row = con.execute("SELECT * FROM jobs WHERE id=?", (cursor.lastrowid,)).fetchone()
        return _job(row)


def next_job() -> dict | None:
    with _db() as con:
        con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT 1 FROM jobs WHERE status='running' LIMIT 1").fetchone():
            return None
        row = con.execute("SELECT * FROM jobs WHERE status='queued' AND not_before<=? ORDER BY id LIMIT 1",
                          (time.time(),)).fetchone()
        if row is None:
            return None
        con.execute("UPDATE jobs SET status='running', updated=? WHERE id=?", (time.time(), row["id"]))
        return _job(row) | {"status": "running"}


def finish(job_id: int) -> None:
    with _db() as con:
        con.execute("UPDATE jobs SET status='done', error=NULL, updated=? WHERE id=?", (time.time(), job_id))


def fail(job_id: int, error: str, retry_after_s: float | None) -> None:
    with _db() as con:
        now = time.time()
        con.execute("""UPDATE jobs SET status=?, attempts=attempts+1, not_before=?, error=?, updated=?
                       WHERE id=?""", ("failed" if retry_after_s is None else "queued",
                                       now + (retry_after_s or 0), error, now, job_id))


def pause(kind: str, rec_id: str | None = None, error: str = "Plaud sign-in expired. Run `plaud login`.") -> None:
    with _db() as con:
        con.execute("""UPDATE jobs SET status='paused', error=?, updated=? WHERE kind=?
                       AND status IN ('queued', 'running') AND (? IS NULL OR rec_id=?)""",
                    (error, time.time(), kind, rec_id, rec_id))


def pause_provider(provider: str, error: str, extra_ids: list[int] | tuple[int, ...] = ()) -> None:
    extra = set(extra_ids)
    with _db() as con:
        con.execute("BEGIN IMMEDIATE")
        now = time.time()
        rows = con.execute("SELECT id, kind, args_json FROM jobs WHERE status IN ('queued', 'running')").fetchall()
        ids = [r["id"] for r in rows if r["id"] in extra
               or (r["kind"] == "generate" and json.loads(r["args_json"]).get("provider") == provider)]
        if ids:
            marks = ",".join("?" for _ in ids)
            con.execute(f"UPDATE jobs SET status='paused', error=?, updated=? WHERE id IN ({marks})",
                        (error, now, *ids))


def provider_auth_errors() -> set[str]:
    with _db() as con:
        return {row["error"] for row in con.execute(
            "SELECT DISTINCT error FROM jobs WHERE status='paused' AND error LIKE 'sign in to % again'")}


def unpause() -> None:
    with _db() as con:
        con.execute("""UPDATE jobs SET status='queued', error=NULL, updated=?
                       WHERE status='paused' AND (error IS NULL OR error NOT LIKE 'sign in to %')""",
                    (time.time(),))


def unpause_provider(provider: str) -> None:
    prefix = f"sign in to {provider} again"
    with _db() as con:
        con.execute("""UPDATE jobs SET status='queued', error=NULL, updated=?
                       WHERE status='paused' AND (error = ? OR substr(error, 1, ?) = ?)""",
                    (time.time(), prefix, len(prefix) + 1, prefix + " "))


def retry(job_id: int) -> dict:
    with _db() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None or row["status"] not in ("failed", "paused", "queued"):
            raise ValueError("job is not waiting or failed")
        if row["status"] == "paused" and (row["error"] or "").startswith("sign in to "):
            raise ValueError(f"{row['error']}, then check providers")
        if con.execute("""SELECT 1 FROM jobs WHERE rec_id=? AND id!=?
                          AND status IN ('queued', 'running', 'paused')""", (row["rec_id"], job_id)).fetchone():
            raise ValueError("this recording already has a live job")
        con.execute("""UPDATE jobs SET status='queued', attempts=0, not_before=0, error=NULL, updated=?
                       WHERE id=?""", (time.time(), job_id))
        return _job(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def recent(n: int = 12) -> list[dict]:
    """Recent history plus every live job, so a long job cannot vanish from the dashboard."""
    with _db() as con:
        return [_job(row) for row in con.execute("""SELECT * FROM jobs WHERE status IN ('queued', 'running', 'paused')
            OR id IN (SELECT id FROM jobs ORDER BY id DESC LIMIT ?) ORDER BY id DESC""", (n,))]


def requeue_running() -> None:
    with _db() as con:
        con.execute("UPDATE jobs SET status='queued', updated=? WHERE status='running'", (time.time(),))
