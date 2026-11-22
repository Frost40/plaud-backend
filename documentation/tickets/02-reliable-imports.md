# 02: Imports that never get stuck

**Needs:** 01, and part A step 1 of ticket 00 for the real run · **Size:** L, with one step for the owner after it is done (autostart)

**Suggested model** (choose one; ★ = recommended):
- Low (a flash model: Haiku, Luna or Gemini Flash): not enough: a worker thread, a poller and a database must agree on job states.
- Medium (Sol or Sonnet): possible; the queue is small and the design fixes every state.
- ★ Hard (Opus or Astra): recommended: things run at the same time, and a wrong resume can import a recording twice or lose one.

## You get

- A failed import no longer blocks itself: it is retried automatically, and you can press "Retry".
- The job list survives a restart, and an interrupted job continues where it stopped.
- When the Plaud sign-in expires, the dashboard says so at the top instead of failing job after job.
- The dashboard can start by itself when you sign in to Windows (after your one step in ticket 00, part B).
- A short check, `app.doctor`, that tells you whether everything the program needs is in place, and a setup guide for a new computer.

## Read first

`documentation/DESIGN.md`:
- 5.3 "Pipeline stages and failure handling";
- 5.8 "Job queue";
- 5.9 "Starting with Windows";
- 5.10 "Setup on a new machine";
- 5.1 (paging the Plaud listing);
- section 3, "Facts in the code" items 1 and 8.

## Build (in this order)

1. **`app/jobs.py`**: the table and statuses of 5.8 in `<data_dir>\jobs.db` with the standard `sqlite3` module. Functions: `submit(kind, rec_id, args)`, `next_job()`, `finish(job_id)`, `fail(job_id, error, retry_after_s|None)`, `pause(kind)`, `recent(n)`, `requeue_running()` (called at start). One connection per call; no global connection shared across threads.
2. **`app/pipeline.py`**: `ingest` becomes the four stages of 5.3. Each stage sets `rec["stage"]` when it finishes and is safe to run again. On an exception, set `rec["error"]` (`stage`, `message`, `at`, `attempts`) and re-raise. A function `resume(rec_id)` runs from the stage after the last finished one. The notes stage runs each `auto:` blueprint on its own, so one provider failure does not stop the others.
3. **Errors that decide retries**, a small function in `pipeline.py`:
   - "auth": the text `AUTH_FAILED` or "sign-in expired" from `plaud.py`. Pause download jobs, do not count an attempt.
   - "gpu": CUDA out-of-memory text. Do not retry automatically.
   - Everything else: retry with back-off of 5 min, 30 min and 2 h, at most 3 attempts.

   Ticket 09 refines the provider errors; keep this function the single place it changes.
4. **`app/server.py`**:
   - the worker takes jobs from `jobs.py`, one at a time;
   - at start, `requeue_running()`;
   - the poller also queues `resume` for every vault recording with `stage != "done"` and no live job, and the paused auth jobs come back once `plaud me` succeeds again;
   - `/api/import` of a recording already in the vault with `stage != "done"` resumes it instead of refusing;
   - new `POST /api/retry {job}`;
   - `state` returns the jobs from the database and a `doctor` summary.
5. **`app/plaud.py`**: `list_recordings()` pages with `-s 100 -p N` until a page has fewer than 100 rows, passing `--date-from` when given a start date. The poller uses `auto_since` as that date.
6. **`app/doctor.py`** (`python -m app.doctor`): one line per check, each `ok` or the fix to apply:
   - `plaud` on PATH and `plaud me` succeeds;
   - the GPU is visible (`ctranslate2.get_cuda_device_count() > 0`);
   - ffmpeg: "not needed" (and it is never called);
   - the model files of `config.py` exist;
   - `.venv-pyannote\Scripts\python.exe` exists;
   - the vault folder exists;
   - which providers are on PATH (names only).

   The dashboard shows one status line from it, refreshed every 10 minutes, not every 3 seconds.
7. **Server process**:
   - if the port is taken, print "already running at …" and exit 0;
   - log to `<data_dir>\server.log` with `logging.handlers.RotatingFileHandler` (5 MB, 3 files);
   - the dashboard shows "server started at …".
8. **`scripts/autostart.ps1`**: as 5.9. With `-Check` it only prints whether the task exists and its last result. Without it, it registers the task for the current user. Never run it without `-Check` yourself: registering it is the owner's step (ticket 00, part B).
9. **`dashboard.html`**: the job list shows failed jobs with their error and a **Retry** button; a banner when the Plaud sign-in expired; the doctor status line. Keep the current look (ticket 10 redesigns it).
10. **`documentation/SETUP.md`**: the steps of 5.10, ending with `python -m app.doctor`. Link it from `README.md`.

## Tests

- `tests/test_jobs.py`:
  - `test_running_job_requeued_after_restart`;
  - `test_failed_import_resumes_from_its_stage`: a fake `plaud` that fails the first time in the transcribe stage; the second run does not download again;
  - `test_auth_failure_pauses_without_using_attempts`;
  - `test_one_gpu_job_at_a_time`;
  - `test_gpu_error_is_not_retried`.
- `tests/test_server.py`, using FastAPI's `TestClient` with the pipeline functions replaced by fakes: import, transcribe again with a model, redo speakers with a count, move, names, create note. Each queues the right job with the right arguments, and bad input (unknown model, count 13, bad id) answers 400.
- `tests/test_core.py::test_parse_plaud_listing_pages`: two saved pages, 100 rows then 3.

## Done when

- [x] Common checks
- [x] `.venv\Scripts\python -m app.doctor` prints every line; the Progress log has its output
- [x] Real run on the sandbox server (port 8378): import the shortest recording not yet in the sandbox (at most one auto note, so at most 1 AI call). While it transcribes, stop the server with Ctrl+C and start it again: the job continues from its stage and finishes. The Progress log names the recording, the stages seen and the times.
- [x] Guard check: point the sandbox config's `parakeet_dir` to a missing folder, import with `ensemble`, see the job fail with its error and **Retry** shown; restore the setting, press Retry, and see it finish
- [x] Starting a second server on 8378 prints "already running" and exits
- [x] `powershell -ExecutionPolicy Bypass -File scripts\autostart.ps1 -Check` reports "not registered" (the owner registers it in ticket 00, part B)
- [x] Remove the recording imported here from the sandbox folder, and stop the sandbox server

## Not in this ticket

Provider-specific error messages and the provider check (ticket 09). Speaker work (tickets 03, 04). The new look (ticket 10).

## Decisions

- 2026-11-17: Use the supplied AGENTS.md instructions (no on-disk AGENTS.md exists), ponytail full, and the existing `documentation/` paths rather than `docs/`.
- Retry policy: initial execution plus at most three automatic retries, delayed 5 minutes, 30 minutes, then 2 hours; auth failures consume no attempt. Terminal failures stay stopped until manual Retry.
- Clarified design 5.3's ambiguous "3 attempts" to three retries after the initial execution: all three specified back-off delays now have a defined use, with tests enforcing the bound and terminal stop.
- Keep checkpoints here and in `documentation/CHECKPOINT.md`; retain one final ticket commit on `rebuild-official-cli` once the acceptance checks are satisfied.
- Downloads publish a `.part` file only after success. Resume keeps the original model/count and successful auto-note provenance; local stages can proceed even with expired Plaud sign-in. Move and name edits also go through the single worker to avoid racing a stage save.

## Progress log

- 2026-11-17, checkpoint 1: Read README, workflow, design requirements and all pipeline/server callers. Clean starting tree on `rebuild-official-cli`. Protected vault newest file UTC: `2026-11-17T06:06:15.8559430Z`. No live actions or AI calls (0/1). Root cause: the in-memory queue is lost and transcription is only saved after speakers; partially created recordings are rejected on import. Next: SQLite queue, stage checkpoints, fake tests, then server/doctor/UI and sandbox acceptance checks. Autostart registration remains owner-only.
- Checkpoint 2: Queue, staged imports, worker/poller, retry API/UI, paging, doctor, logs, autostart script and setup guide implemented. 56 tests passed before the latest auth-local-stage fix (rerun next). Read-only doctor succeeds outside the execution sandbox; inside it Node gets EPERM resolving the user directory, not a Plaud login failure. Doctor output: `plaud: ok; GPU: ok; ffmpeg: not needed; parakeet_dir: ok; diar_segmentation: ok; diar_embedding: ok; pyannote: ok; vault: ok; providers: ok: claude, codex, antigravity`. Autostart `-Check`: `Plaud dashboard: not registered`. AI calls 0/1. Next: test auth-local-stage handling and doctor, inspect live ports read-only, run sandbox import/restart and missing-Parakeet retry check, restore/clean sandbox, verify vault timestamp, update board and commit. No sandbox server started yet.
- Checkpoint 3 (18:37 local): 60 tests pass. Live check uses the shortest unimported recording, `of_f848f172858d6be03202701715a0b54a`, "How to use Plaud", 3m46s. Sandbox config/blueprints backed up in `data/sandbox/ticket02-backup.json`; auto notes temporarily disabled to reserve the single AI call for ensemble. Import job 1: 18:34:18 queued, 18:34:22 downloading, 18:34:27 saved `downloaded` and missing-Parakeet error. Second server exited 0 with `already running at http://127.0.0.1:8378`. Restored model config, restarted, and clicked the real Retry button using isolated headless Edge (CDP port 9223; PID file `data/sandbox/ticket02-browser.pid`). Ctrl+C during turbo transcription at 18:36:16 left job 1 `running`, stage `downloaded`; restarted server (tool session 46879). 18:36:44 Parakeet; 18:36:49 one Claude arbitration attempt (1/1 allowance); 18:36:52 `transcribed`, separating speakers. Monitor session 21618; evidence `data/sandbox/ticket02-evidence.jsonl`. Next: await completion (do not trigger another AI call), verify audio unchanged, stop sandbox and headless browser, restore backed-up blueprints/config, delete only this new recording from sandbox, final tests/timestamp/board/commit. Added graceful Ctrl+C handling after seeing Uvicorn's KeyboardInterrupt traceback; not yet tested in a new process.
- Checkpoint 4 (18:42 local): Job 1 reached `done` at 18:38:21 (523 words, pyannote); its downloaded audio retained the exact size (1,861,928 bytes) and mtime (`1794936864789780200` ns). One Claude call was attempted, but all eight windows had `no answer`; existing ensemble fallback kept Whisper. Provider diagnosis belongs to ticket 09; no second call made. State samples during work were 0.28–0.50 s including client creation. Browser confirmed error, Retry, setup status and start time. Sandbox server/browser stopped, only the newly imported sandbox recording removed, original config/blueprints restored byte-for-byte (initial restoration assertion exposed CRLF normalization, corrected before restoring). Sandbox has its original four recordings. Final build started at 18:40:30 with `Setup ok`, no running jobs; second instance exited 0; Ctrl+C stopped it without traceback. Protected vault newest UTC after cleanup: `2026-11-17T06:06:15.8559430Z`, identical to before. 61 tests passed before the final start-time normalization assertion; next: final suite/diff checks, board and one ticket commit. Owner still registers autostart and checks sign-out/sign-in; see `documentation/OWNER_CHECKS.md`.
- Final checkpoint: `.venv\Scripts\python -m pytest tests -q` passes: **61 passed, 0 skipped**, with only the existing Starlette/httpx deprecation warning. `git diff --check` passes. Ports 8377, 8378 and the isolated browser's 9223 are stopped. All ticket acceptance checks complete; board marks 02 Done and 09 Ready. No dependency installation, autostart registration, owner-vault write or second AI call. Ready for the single ticket commit on `rebuild-official-cli`; next ticket remains 03.
