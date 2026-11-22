"""Local dashboard + background worker. Run:  python -m app.server   then open http://127.0.0.1:8377"""
import datetime as dt
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
import re
import socket
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse

# Config must be selected before importing modules that capture vault paths.
_args = argparse.ArgumentParser(allow_abbrev=False)
_args.add_argument("--config")
_config, _ = _args.parse_known_args()
if _config.config:
    os.environ["PLAUD_CONFIG"] = _config.config

from app import doctor, glossary, jobs, llm, notes, pipeline, plaud, vault, voices
from app.config import DATA, VAULT, cfg

app = FastAPI(title="Plaud dashboard")
_progress: dict = {}
_recording_locks: dict = {}
_started_at = None
_doctor_cache = {"summary": "Checking setup...", "checks": {}, "at": None}
_plaud_cache: dict = {"list": [], "error": "", "at": 0.0}
_plaud_details_cache: dict = {}
_recording_cache: dict = {}
# shortcut: one cache lock; split per path if large vaults cause request contention.
_recording_cache_lock = threading.Lock()


def _pause_downloads() -> None:
    stages = {r["id"]: r.get("stage") for r in vault.scan()}
    for job in jobs.recent(-1):
        if job["kind"] in ("import", "import_plaud", "resume") and stages.get(job["rec_id"], "new") == "new":
            jobs.pause(job["kind"], job["rec_id"])


def _run_job(job: dict) -> None:
    with _recording_locks.setdefault(job["rec_id"], threading.Lock()):
        _dispatch_job(job)


def _auth_provider(error) -> str | None:
    if isinstance(error, llm.ProviderError):
        return error.provider
    m = re.search(r"sign in to (\S+) again", str(error), re.I)
    return m[1] if m else None


def _note_provider(job: dict) -> str | None:
    if job["kind"] == "generate":
        return job["args"].get("provider")
    if job["kind"] != "regenerate":
        return None
    try:
        return notes.entry(vault.find(job["rec_id"]), job["args"]["file"])["provider"]
    except Exception:
        return None


def _parse_duration(val) -> float:
    if isinstance(val, (int, float)) and val > 0:
        return float(val)
    if not isinstance(val, str):
        return 600.0
    s = val.strip()
    if ":" in s:
        try:
            parts = [float(p) for p in s.split(":")]
            if len(parts) == 2:
                return max(1.0, parts[0] * 60 + parts[1])
            if len(parts) == 3:
                return max(1.0, parts[0] * 3600 + parts[1] * 60 + parts[2])
        except ValueError:
            pass
    total = sum(float(n) * {"h": 3600, "m": 60, "s": 1}[u]
                for n, u in re.findall(r"(\d+(?:\.\d+)?)\s*([hms])", s.lower()))
    return total if total > 0 else 600.0


def _duration_s(rec_id: str) -> float:
    for r in _plaud_cache["list"]:
        if r.get("id") == rec_id:
            return _parse_duration(r.get("duration_s") or r.get("duration"))
    with _recording_cache_lock:
        for _, summary in _recording_cache.values():
            if summary.get("id") == rec_id:
                return _parse_duration(summary.get("duration_s") or summary.get("duration"))
    return 600.0


# Seconds of work per unit (per second of audio, or per note), measured on this machine. Seeded with
# the speeds measured during development; each finished stage moves its rate halfway to what it took.
_DEFAULT_RATES = {"download": 0.005, "transcribe:large-v3-turbo": 1 / 28, "transcribe:large-v3": 1 / 12,
                  "parakeet": 1 / 23, "arbiter": 1 / 15, "speakers:pyannote": 1 / 25, "speakers:sherpa": 0.45,
                  "note": 45.0, "plaud_download": 6.0, "plaud_transcript": 4.0, "plaud_notes": 4.0,
                  "check": 4.0, "run": 3.0}
try:
    _rates = {**_DEFAULT_RATES, **json.loads((jobs.DATA / "timings.json").read_text())}
except (OSError, ValueError):
    _rates = dict(_DEFAULT_RATES)


def _learn(rate_key: str, seconds: float, units: float) -> None:
    if units <= 0 or seconds <= 0:
        return
    old = _rates.get(rate_key)
    _rates[rate_key] = seconds / units if old is None else (old + seconds / units) / 2
    try:
        (jobs.DATA / "timings.json").write_text(json.dumps(_rates, indent=1))   # beside jobs.db
    except OSError:
        pass   # a lost measurement only makes the next estimate less exact


def _job_stages(job: dict) -> list[tuple[str, str, float, str, float]]:
    """(key, label, estimated seconds, rate key, units) for the stages this job will really run."""
    kind, args = job["kind"], job["args"]
    rec = next((r for r in vault.scan() if r["id"] == job["rec_id"]), None) or {}
    dur = _duration_s(job["rec_id"])
    model = args.get("model") or rec.get("model") or cfg["whisper_model"]
    whisper = cfg["whisper_model"] if model == "ensemble" else model
    n_notes = sum(1 for b in vault.blueprints() if b["auto"])

    def st(key, label, rate_key, units):
        return (key, label, max(1.0, _rates.get(rate_key, 1 / 20) * units), rate_key, units)

    transcribe = [st("transcribe", "Transcribe", f"transcribe:{whisper}", dur)]
    if model == "ensemble":
        transcribe += [st("parakeet", "Second model", "parakeet", dur), st("arbiter", "Compare", "arbiter", dur)]
    speakers = [st("speakers", "Speakers", f"speakers:{cfg['diar_engine']}", dur)]
    if kind in ("import", "resume") and rec.get("source") != "plaud":
        full = [st("download", "Download", "download", dur), *transcribe, *speakers, st("notes", "Notes", "note", n_notes)]
        # Resuming skips the stages already saved in recording.json.
        done = {"downloaded": ["download"], "transcribed": ["download", "transcribe", "parakeet", "arbiter"],
                "speakers": ["download", "transcribe", "parakeet", "arbiter", "speakers"]}.get(rec.get("stage"), [])
        return [s for s in full if s[0] not in done]
    if kind in ("import_plaud", "resume"):
        return [st("download", "Download", "plaud_download", 1), st("transcribe", "Transcript", "plaud_transcript", 1),
                st("notes", "Notes", "plaud_notes", 1)]
    if kind == "retranscribe":
        return transcribe
    if kind == "respeak":
        return speakers
    if kind in ("generate", "regenerate"):
        return [st("notes", "Write note", "note", 1)]
    if kind == "check_providers":
        return [st("check", "Check AI", "check", 1 if args.get("provider") else max(1, len(cfg["providers"])))]
    return [st("run", "Working", "run", 1)]


def _infer_key(msg: str) -> str | None:
    low = msg.lower()
    if "downloading audio" in low:
        return "download"
    if "second model" in low:
        return "parakeet"
    if "arbitrating" in low:
        return "arbiter"
    if "transcrib" in low or "downloading transcript" in low:
        return "transcribe"
    if "separating speakers" in low:
        return "speakers"
    if "writing " in low or "downloading notes" in low or "retrying " in low:
        return "notes"
    return None


def _infer_stage(stages: list, msg: str, current: int) -> int:
    """Stages only move forward: a later message never drags the bar back."""
    key = _infer_key(msg)
    return next((i for i, stage in enumerate(stages) if stage[0] == key and i >= current), current)


def _set_progress_frac(job_id: int, frac: float) -> None:
    p = _progress.get(job_id)
    if p is not None:
        frac = max(p["stage_frac"] or 0.0, min(1.0, float(frac)))
        if frac > 0 and p.get("first") is None:   # pace is timed from here: model loading is not work
            now = time.time()
            p["first"] = (now, frac, min(0.95, (now - p["stage_started"]) / p["stages"][p["stage_idx"]][2]))
        p["stage_frac"] = frac


def _close_stage(p: dict, now: float) -> None:
    """Learn how long the stage just finished really took (only if it ran from its own start)."""
    key, _, _, rate_key, units = p["stages"][p["stage_idx"]]
    if p["entered"]:
        _learn(rate_key, now - p["stage_started"], p["notes_written"] if key == "notes" and units > 1 else units)


def _progress_snapshot(job_id: int) -> dict | None:
    p = _progress.get(job_id)
    if not isinstance(p, dict):
        return None
    now = time.time()
    stages, idx = p["stages"], p["stage_idx"]
    est = stages[idx][2]
    el = max(0.0, now - p["stage_started"])
    frac = p["stage_frac"]
    overdue = False
    if frac and p.get("first"):   # measured progress: trust its own pace more the further it gets
        t0, f0, a = p["first"]    # when, how far, and how much of the bar the first report found
        work = (frac - f0) / (1 - f0) if f0 < 1 else 1.0
        usual = max(est * (1 - a), 1.0) * (1 - work)
        pace = (now - t0) * (1 - work) / work if work > 0 else usual
        rem = (1 - work) * usual + work * pace
        frac = a + (1 - a) * work
    else:      # no signal from this step (an AI call): elapsed against this machine's usual time
        frac = min(0.95, el / est)
        rem = max(0.0, est - el)
        overdue = el > est * 1.25
    total = sum(s[2] for s in stages)
    pct = 100.0 * (sum(s[2] for s in stages[:idx]) + est * frac) / total
    p["pct"] = pct = max(p.get("pct", 0.0), min(99.0, pct))
    return {
        "pct": round(pct, 1),
        "eta_s": max(1, round(rem + sum(s[2] for s in stages[idx + 1:]))),
        "overdue": overdue,
        "elapsed_s": int(max(0.0, now - p["started"])),
        "stage": stages[idx][0],
        "stage_label": stages[idx][1],
        "step": idx + 1,
        "steps": len(stages),
        "stages": [s[1] for s in stages],
    }


def _dispatch_job(job: dict) -> None:
    rec_id, args = job["rec_id"], job["args"]
    now = time.time()
    try:
        stages = _job_stages(job)
    except Exception:   # a progress estimate must never stop the job itself
        stages = [("run", "Working", 30.0, "run", 0)]
    _progress[job["id"]] = {
        "msg": "", "started": now, "stage_started": now, "entered": False, "notes_written": 0,
        "stage_idx": 0, "stage_frac": None, "stages": stages,
    }

    def log(message):
        p = _progress.get(job["id"])
        if p is not None:
            p["msg"] = message
            idx = _infer_stage(p["stages"], message, p["stage_idx"])
            if idx != p["stage_idx"] or (not p["entered"] and p["stages"][idx][0] == _infer_key(message)):
                t = time.time()
                if idx != p["stage_idx"]:
                    _close_stage(p, t)
                p.update(stage_idx=idx, stage_started=t, stage_frac=None, first=None, entered=True)
            if message.startswith("writing '"):
                p["notes_written"] += 1
        logging.getLogger(__name__).info("Job %s: %s", job["id"], message)

    log.progress = lambda frac: _set_progress_frac(job["id"], frac)
    try:
        if provider := _note_provider(job):
            sign_in = f"sign in to {provider} again"
            if sign_in in jobs.provider_auth_errors():
                jobs.pause_provider(provider, sign_in, [job["id"]])
                return
        if job["kind"] == "move":
            vault.move(rec_id, **args)
        elif job["kind"] == "speakers":
            pipeline.rename_speakers(rec_id, **args)
        elif job["kind"] == "check_providers":
            for name, res in doctor.check_providers(log=log, provider=args.get("provider")).items():
                if res.get("ok"):
                    jobs.unpause_provider(name)
        else:
            fn = {"import": pipeline.ingest, "import_plaud": pipeline.ingest_plaud, "resume": pipeline.resume,
                  "retranscribe": pipeline.retranscribe, "respeak": pipeline.respeak,
                  "generate": pipeline.generate, "regenerate": notes.regenerate}[job["kind"]]
            fn(rec_id, **args, log=log)
        if (p := _progress.get(job["id"])) is not None:
            _close_stage(p, time.time())
        jobs.finish(job["id"])
    except Exception as e:
        logging.getLogger(__name__).exception("Job %s (%s) failed", job["id"], job["kind"])
        if pipeline.error_kind(e) == "auth":
            if provider := _auth_provider(e):
                extra = [j["id"] for j in jobs.recent(-1)
                         if j["status"] in ("queued", "running") and j["kind"] == "regenerate"
                         and _note_provider(j) == provider]
                jobs.pause_provider(provider, f"sign in to {provider} again", [job["id"], *extra])
            else:
                _plaud_cache["error"] = str(e)
                jobs.pause(job["kind"], rec_id, str(e))
                _pause_downloads()
        else:
            jobs.fail(job["id"], str(e), pipeline.retry_delay(e, job["attempts"]))
    finally:
        _progress.pop(job["id"], None)


def _worker() -> None:  # one job at a time: the GPU fits one model
    while True:
        if pipeline.error_kind(_plaud_cache["error"]) == "auth":
            _pause_downloads()
        if job := jobs.next_job():
            _run_job(job)
        else:
            time.sleep(0.5)


def refresh_plaud(date_from=None) -> None:
    try:
        rows = plaud.list_recordings(date_from)
        if date_from:
            rows = list({r["id"]: r for r in [*_plaud_cache["list"], *rows]}.values())
        else:
            _plaud_details_cache.clear()
        _plaud_cache.update(list=rows, error="", at=time.time())
    except Exception as e:
        _plaud_cache["error"] = str(e)[:300]


def _poll_once(since: str) -> None:
    authenticated = True
    if (pipeline.error_kind(_plaud_cache["error"]) == "auth"
            or any(j["status"] == "paused" and not (j.get("error") or "").startswith("sign in to ")
                   for j in jobs.recent(-1))):
        try:
            plaud.me()
            jobs.unpause()
            _plaud_cache["error"] = ""
        except Exception as e:
            _plaud_cache["error"] = f"Plaud sign-in expired; account check: {e}"
            _pause_downloads()
            authenticated = False
    if authenticated:
        refresh_plaud(since)
    recordings = vault.scan()
    history = jobs.recent(-1)
    live = {j["rec_id"] for j in history if j["status"] in ("queued", "running", "paused")}
    stopped = {j["rec_id"] for j in history if j["kind"] in ("import", "import_plaud", "resume") and j["status"] == "failed"}
    for rec in recordings:
        if rec.get("stage") != "done" and rec["id"] not in live | stopped:
            error = rec.get("error") or {}
            if error and (pipeline.error_kind(error["message"]) == "gpu" or error["attempts"] >= 4):
                continue
            jobs.submit("resume", rec["id"], {})
    if cfg["auto_process"]:
        known = {r["id"] for r in recordings} | live | stopped
        for rec in _plaud_cache["list"]:
            if rec["id"] not in known and rec["date"] >= since:
                jobs.submit("import", rec["id"], {"model": cfg["whisper_model"], "num_speakers": 0})
    if pipeline.error_kind(_plaud_cache["error"]) == "auth":
        _pause_downloads()


def _poller() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    state = DATA / "state.json"
    if not state.exists():  # only recordings made from now on are processed automatically
        state.write_text(json.dumps({"auto_since": dt.date.today().isoformat()}))
    since = json.loads(state.read_text())["auto_since"]
    refresh_plaud()  # Keep older recordings available for manual import.
    while True:
        try:
            _poll_once(since)
        except Exception:
            logging.getLogger(__name__).exception("Poll failed; will try again")
        time.sleep(cfg["poll_minutes"] * 60)


def _doctor_loop() -> None:
    while True:
        try:
            _doctor_cache.update(doctor.check())
        except Exception:
            logging.getLogger(__name__).exception("Setup check failed")
        time.sleep(600)


def _rec_id(body: dict) -> str:
    rec_id = body.get("id", "")
    if not isinstance(rec_id, str) or not plaud.ID_RE.fullmatch(rec_id):
        raise HTTPException(400, "bad recording id")
    return rec_id


def _model(body: dict) -> str:
    if (m := body.get("model") or cfg["whisper_model"]) not in cfg["whisper_models"]:
        raise HTTPException(400, "unknown model")
    return m


def _nspk(body: dict) -> int:
    n = body.get("speakers", 0)
    if type(n) is not int or not 0 <= n <= 12:
        raise HTTPException(400, "speakers must be 0 (auto) to 12")
    return n


def _existing(rec_id: str) -> dict:
    try:
        rec = vault.find(rec_id)
        vault.writable(rec)
        return rec
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "dashboard.html")


@app.get("/favicon.svg")
def favicon():
    return FileResponse(Path(__file__).parent / "favicon.svg", media_type="image/svg+xml")


@app.get("/api/state")
def state():
    recs = []
    with _recording_cache_lock:
        paths = {p for p in vault.BASE.glob("*/*/recording.json") if not p.parent.parent.name.startswith("_")}
        for removed in _recording_cache.keys() - paths:
            del _recording_cache[removed]
        for path in sorted(paths):
            try:
                modified = path.stat().st_mtime_ns
                cached = _recording_cache.get(path)
                if cached is None or cached[0] != modified:
                    r = json.loads(path.read_text(encoding="utf-8"))
                    if r.get("schema", 1) < 2:
                        raise ValueError("recording migration did not complete")
                    r["_dir"] = path.parent
                    summary = {"id": r["id"], "title": r["title"], "date": r["date"], "duration": r["duration"],
                               "group": path.parent.parent.name, "stem": r["stem"], "model": r.get("model"),
                               "language": r.get("language"), "num_speakers": r.get("num_speakers", 0),
                               "speaker_engine": r.get("speaker_engine"),
                               "true_speakers": r.get("true_speakers"),
                               "stage": r.get("stage"), "error": r.get("error"),
                               "speakers": {s: vault.speaker_name(r, s) for s in r["speakers"]},
                               "marks": len(r.get("marks", [])),
                               "glossary_dropped": len(r.get("transcript", {}).get("glossary_dropped", [])),
                               "notes": [n | {"state": notes.state(r, n)} for n in r["notes"]],
                               "path": path.parent.relative_to(VAULT).as_posix()}
                    _recording_cache[path] = (modified, summary)
                summary = _recording_cache[path][1]
                recs.append(summary | {"notes": [n | {"missing": not (path.parent / n["file"]).is_file()}
                                                 for n in summary["notes"]]})
            except (OSError, ValueError, KeyError, TypeError):
                _recording_cache.pop(path, None)
                logging.getLogger(__name__).exception("Cannot read recording %s", path)
    groups = vault.groups()
    have = {r["id"] for r in recs}
    installed = llm.available()
    checks = llm.statuses()
    auth_errors = jobs.provider_auth_errors()
    provider_checks = {name: checks[name] for name in cfg["providers"] if name in checks}
    provider_config = {
        name: {
            "type": p["type"],
            "has_key": llm.is_installed(name) if p["type"] == "openai" else None,
            "can_set_key": bool(p.get("dashboard_key")) if p["type"] == "openai" else False,
            "api_key_env": p.get("api_key_env") if p["type"] == "openai" else None,
            "models": llm.available_models(name),
            "default_model": p.get("model"),
            "selected_model": llm.selected_model(name) if llm.available_models(name) else None,
        }
        for name, p in cfg["providers"].items()
    }
    bps = vault.blueprints()
    return {"recordings": sorted(recs, key=lambda r: r["date"], reverse=True),
            "not_imported": [r for r in _plaud_cache["list"] if r["id"] not in have],
            "plaud_error": _plaud_cache["error"], "groups": groups,
            "glossaries": {g: glossary.counts(g) for g in groups},
            "blueprints": [b["name"] for b in bps],
            "blueprint_meta": {b["name"]: {"auto": b["auto"]} for b in bps},
            "providers": [p for p in installed if checks.get(p, {}).get("ok")
                          and f"sign in to {p} again" not in auth_errors],
            "provider_checks": provider_checks,
            "provider_config": provider_config,
            "default_provider": cfg["default_provider"],
            "arbiter_provider": cfg["arbiter_provider"],
            "models": cfg["whisper_models"],
            "default_model": cfg["whisper_model"], "vault": VAULT.name, "inbox": cfg["inbox"],
            "jobs": [
                j | {"msg": p["msg"] if isinstance(p := _progress.get(j["id"]), dict) else (p or ""),
                     **({"progress": snap} if (snap := _progress_snapshot(j["id"])) else {})}
                for j in jobs.recent()
            ],
            "doctor": _doctor_cache, "started_at": _started_at}


@app.post("/api/check_providers")
def api_check_providers():
    return jobs.submit("check_providers", "providers", {})


@app.post("/api/provider_key")
def api_provider_key(body: dict = Body(...)):
    prov, key = body.get("provider"), body.get("api_key")
    if not isinstance(prov, str) or not isinstance(key, str):
        raise HTTPException(400, "provider and api_key must be strings")
    try:
        has_key = llm.set_api_key(prov, key)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if has_key:
        jobs.submit("check_providers", f"provider:{prov}", {"provider": prov})
    return {"ok": True, "has_key": has_key}


@app.post("/api/provider_model")
def api_provider_model(body: dict = Body(...)):
    prov, model = body.get("provider"), body.get("model")
    if not isinstance(prov, str) or not isinstance(model, str):
        raise HTTPException(400, "provider and model must be strings")
    try:
        chosen = llm.set_model(prov, model)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "model": chosen}


@app.get("/api/plaud/{rec_id}")
def api_plaud_details(rec_id: str):
    i = _rec_id({"id": rec_id})
    cached = _plaud_details_cache.get(i)
    if cached and time.time() - cached[0] < 120:
        return cached[1]
    try:
        info = plaud.details(i)
    except Exception as e:
        raise HTTPException(502, str(e))
    _plaud_details_cache[i] = (time.time(), info)
    return info


@app.post("/api/refresh")
def api_refresh():
    refresh_plaud()
    return {"ok": True}


@app.post("/api/import")
def api_import(body: dict = Body(...)):
    i = _rec_id(body)
    source = body.get("source") or "local"
    if source not in ("local", "plaud"):
        raise HTTPException(400, "unknown import source")
    m, n = (None, 0) if source == "plaud" else (_model(body), _nspk(body))
    named = (body.get("group") or "").strip()
    group = named or cfg["inbox"]
    if not vault.group_ok(group):
        raise HTTPException(400, "invalid folder name")
    rec = next((r for r in vault.scan() if r["id"] == i), None)
    if rec:
        if rec["stage"] == "done":
            raise HTTPException(400, "this recording is already in the vault")
        if named and rec["group"] != group:   # file it first, so the rest of the import uses that folder's glossary
            jobs.submit("move", i, {"group": group})
        return jobs.submit("import_plaud" if source == "plaud" else "resume", i, {})
    return (jobs.submit("import_plaud", i, {"group": group}) if source == "plaud"
            else jobs.submit("import", i, {"model": m, "num_speakers": n, "group": group}))


@app.post("/api/retranscribe")
def api_retranscribe(body: dict = Body(...)):
    i, m, n = _rec_id(body), _model(body), _nspk(body)
    _existing(i)
    return jobs.submit("retranscribe", i, {"model": m, "num_speakers": n})


@app.post("/api/respeak")
def api_respeak(body: dict = Body(...)):
    i, n = _rec_id(body), _nspk(body)
    _existing(i)
    return jobs.submit("respeak", i, {"num_speakers": n})


@app.post("/api/generate")
def api_generate(body: dict = Body(...)):
    i, bp, prov = _rec_id(body), body.get("blueprint"), body.get("provider")
    if bp not in [b["name"] for b in vault.blueprints()] or prov not in llm.available():
        raise HTTPException(400, "unknown blueprint or provider")
    args = {"blueprint": bp, "provider": prov}
    model = body.get("model")
    if model is not None and model != "":
        allowed = llm.available_models(prov)
        if not isinstance(model, str) or model not in allowed:
            raise HTTPException(400, "unknown model for provider")
        args["model"] = model
    _existing(i)
    return _submit_note("generate", i, args, prov)


@app.post("/api/move")
def api_move(body: dict = Body(...)):
    i, group = _rec_id(body), body.get("group", "")
    _existing(i)
    if not isinstance(group, str) or not vault.group_ok(group.strip()):
        raise HTTPException(400, "invalid folder name")
    return jobs.submit("move", i, {"group": group.strip()})


@app.post("/api/regenerate")
def api_regenerate(body: dict = Body(...)):
    i, file = _rec_id(body), body.get("file")
    rec = _existing(i)
    try:
        note = notes.entry(rec, file)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if note["blueprint"] not in [b["name"] for b in vault.blueprints()] or note["provider"] not in llm.available():
        raise HTTPException(400, "unknown blueprint or provider")
    return _submit_note("regenerate", i, {"file": file}, note["provider"])


def _submit_note(kind: str, rec_id: str, args: dict, provider: str) -> dict:
    sign_in = f"sign in to {provider} again"
    if sign_in in jobs.provider_auth_errors():
        raise HTTPException(409, f"{sign_in}, then check providers")
    return jobs.submit(kind, rec_id, args)


@app.post("/api/speakers")
def api_speakers(body: dict = Body(...)):
    names = body.get("names", {})
    if not isinstance(names, dict) or not all(re.fullmatch(r"S[1-9][0-9]*", k) and isinstance(v, str)
                                             and len(v) <= 60 for k, v in names.items()):
        raise HTTPException(400, "bad speaker names")
    i = _rec_id(body)
    rec = _existing(i)
    if any(k not in rec["speakers"] for k in names):
        raise HTTPException(400, "unknown speaker")
    args = {"names": names} if "names" in body or "true_speakers" not in body else {}
    if "true_speakers" in body:
        count = body["true_speakers"]
        if type(count) is not int or count < 0:
            raise HTTPException(400, "true_speakers must be a non-negative integer")
        args["true_speakers"] = count
    renamed = {k for k, name in names.items() if name.strip() != rec["speakers"][k]["name"]}
    result = _edit_speakers(i, lambda: pipeline.rename_speakers(i, **args))
    rec = vault.find(i)
    named = {}
    for spk in sorted(rec["speakers"], key=lambda k: k in renamed):
        speaker = rec["speakers"][spk]
        name = speaker["name"]
        if name and not speaker.get("merged_into"):
            if name in named:
                return result | {"merge_offer": [spk, named[name]]}
            named[name] = spk
    return result


def _edit_speakers(rec_id, edit):
    lock = _recording_locks.setdefault(rec_id, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "busy")
    try:
        if any(j["rec_id"] == rec_id and j["status"] == "running" for j in jobs.recent(-1)):
            raise HTTPException(409, "busy")
        try:
            edit()
        except (ValueError, KeyError) as e:
            raise HTTPException(400, str(e))
        return {"ok": True}
    finally:
        lock.release()


@app.post("/api/title")
def api_title(body: dict = Body(...)):
    i = _rec_id(body)
    _existing(i)
    return _edit_speakers(i, lambda: pipeline.rename(i, body.get("title")))


@app.post("/api/merge")
def api_merge(body: dict = Body(...)):
    i = _rec_id(body)
    return _edit_speakers(i, lambda: pipeline.merge(i, body.get("src"), body.get("dst")))


@app.post("/api/suggestion")
def api_suggestion(body: dict = Body(...)):
    i = _rec_id(body)
    spk, accept, expected = body.get("spk"), body.get("accept"), body.get("name")
    if not isinstance(spk, str) or type(accept) is not bool or (
        expected is not None and not isinstance(expected, str)
    ):
        raise HTTPException(400, "bad voice suggestion")
    return _edit_speakers(i, lambda: pipeline.answer_suggestion(i, spk, accept, expected))


@app.post("/api/unmerge")
def api_unmerge(body: dict = Body(...)):
    i = _rec_id(body)
    return _edit_speakers(i, lambda: pipeline.unmerge(i, body.get("src")))


@app.post("/api/fix")
def api_fix(body: dict = Body(...)):
    i = _rec_id(body)
    return _edit_speakers(i, lambda: pipeline.add_fix(i, body.get("s"), body.get("e"), body.get("spk")))


@app.post("/api/unfix")
def api_unfix(body: dict = Body(...)):
    i = _rec_id(body)
    return _edit_speakers(i, lambda: pipeline.remove_fix(i, body.get("index")))


@app.get("/api/recordings/{rec_id}")
def api_recording(rec_id: str):
    rec = _existing(_rec_id({"id": rec_id}))
    return {k: v for k, v in rec.items() if k not in ("words", "_dir")} | {
        "suggestions": voices.suggest(rec),
        "voice_people_needed": voices.needed(rec["diarization"].get("engine") or cfg["diar_engine"]),
        "closest_voices": {k: pipeline.closest_voice(rec, k) for k in rec["speakers"]}}


@app.get("/api/notes/{rec_id}/{file}")
def api_note(rec_id: str, file: str):
    """Read-only: the body of one indexed note, for the dashboard's note tabs."""
    try:
        rec = vault.find(_rec_id({"id": rec_id}))
        notes.entry(rec, file)
        return {"text": vault._frontmatter((rec["_dir"] / file).read_text(encoding="utf-8"))[1]}
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    except OSError:
        raise HTTPException(404, "note file is missing")


def _glossary_rec(rec_id):
    try:
        return vault.find(_rec_id({"id": rec_id}))
    except KeyError as e:
        raise HTTPException(400, str(e))


@app.get("/api/recordings/{rec_id}/glossary")
def api_glossary(rec_id: str):
    """The Glossary tab of one recording: its folder's words, grouped for this recording."""
    rec = _glossary_rec(rec_id)
    return glossary.view(rec["group"], rec)


@app.post("/api/recordings/{rec_id}/glossary")
def api_glossary_act(rec_id: str, body: dict = Body(...)):
    """One word change from the Glossary tab; answers with the tab's new state."""
    rec = _glossary_rec(rec_id)
    try:
        glossary.act(rec["group"], body.get("action"), body.get("term"), rec["id"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return glossary.view(rec["group"], rec)


@app.get("/api/audio/{rec_id}")
def api_audio(rec_id: str):
    rec = _existing(_rec_id({"id": rec_id}))
    path = pipeline._audio(rec)
    if not path.is_file():
        raise HTTPException(404, "audio not downloaded")
    # Plaud also returns MP3 tutorials under the vault's historical .ogg filename.
    with path.open("rb") as audio:
        header = audio.read(4)
    mp3 = header.startswith(b"ID3") or (len(header) >= 2 and header[0] == 255 and header[1] & 224 == 224)
    return FileResponse(path, media_type="audio/mpeg" if mp3 else "audio/ogg")


@app.post("/api/retry")
def api_retry(body: dict = Body(...)):
    if type(body.get("job")) is not int:
        raise HTTPException(400, "bad job id")
    try:
        return jobs.retry(body["job"])
    except ValueError as e:
        raise HTTPException(400, str(e))


def main() -> None:
    global _started_at
    sock = socket.socket()
    try:
        sock.bind((cfg["host"], cfg["port"]))
    except OSError as e:
        sock.close()
        if e.errno not in (98, 10048) and getattr(e, "winerror", None) != 10048:
            raise
        print(f"already running at http://{cfg['host']}:{cfg['port']}")
        return
    DATA.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(DATA / "server.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s", force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # Request URLs can grant access to private recordings.
    _started_at = dt.datetime.now().isoformat(timespec="seconds")
    logging.info("Server started at %s", _started_at)
    vault.seed()
    vault.migrate_all()
    try:
        glossary.relocate()   # repairs terms left in an old folder by moves made before this fix
    except Exception:
        logging.exception("Glossary relocation skipped")
    jobs.requeue_running()
    threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_poller, daemon=True).start()
    threading.Thread(target=_doctor_loop, daemon=True).start()
    try:
        uvicorn.Server(uvicorn.Config(app, log_config=None)).run(sockets=[sock])
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()


if __name__ == "__main__":
    main()
