# 01: Safe ground: sandbox, guards, recording format 2

**Needs:** none · **Size:** L

**Suggested model** (choose one; ★ = recommended):
- Low (a flash model: Haiku, Luna or Gemini Flash): not enough: the format change touches every module, and a wrong migration damages the owner's recordings.
- Medium (Sol or Sonnet): possible, since the steps are written out, but risky for the same reason.
- ★ Hard (Opus or Astra): recommended: it changes how every recording is stored and must convert real data safely.

## You get

- A private copy of your vault (the "sandbox") that every later ticket uses for real runs, so your own recordings are never touched while things are built.
- Every recording stored in a new, versioned format that keeps speakers apart by a fixed id, lists its notes, and can be upgraded safely later. Your four recordings convert by themselves the next time you restart the dashboard, and the old file is kept beside each one.
- The dashboard loads faster, because it no longer re-reads every word of every recording every 3 seconds.
- Two guards that fail the tests if Docker, Riffado or Supabase come back, or if anything reaches Plaud without the official command-line tool.

## Read first

`documentation/DESIGN.md`:
- 5.13 "Sandbox for test runs";
- 5.2 "Data layout in the vault" (the whole schema, the rules and the migration);
- section 2, R4, R5, R7 and R8 (the tests named there);
- section 3, "Facts in the code" items 2 and 6.

## Limits

- The owner's vault `C:\Users\<user>\Documents\Obsidian Vault\Plaud\` is only **read** by `scripts\make_sandbox.py`. Nothing in this ticket writes there. The real migration happens when the owner restarts the dashboard (ticket 00, part B).
- The migration must never delete anything: it writes `recording.v1.json` first, checks that the copy reads back identical, then writes the new `recording.json` atomically. If any step fails, it leaves the recording as it was and logs why.

## Build (in this order)

### Part A: the sandbox

1. **`app/config.py`**: read the settings file named by the environment variable `PLAUD_CONFIG` when it is set, otherwise `config.json` in the project root. Add the setting `data_dir` (default `"data"`, relative paths resolved from the project root) and make `DATA` use it.
2. **`app/server.py`**: before any `from app import …` line, look for `--config FILE` in `sys.argv` and, when present, set `os.environ["PLAUD_CONFIG"]` to it. Use `DATA` for `state.json`.
3. **`scripts/make_sandbox.py`**: exactly as 5.13. Copy `<vault>\Plaud\` (from the normal config) to `data\sandbox\vault\Plaud\`, replacing any earlier sandbox, and write `data\sandbox\config.json` with `vault`, `port: 8378`, `auto_process: false`, `data_dir: "data/sandbox/state"`. Print what it copied (number of recordings and files).
4. **`.claude/launch.json`**: add the entry `plaud-dashboard-sandbox` (`.venv/Scripts/python.exe`, args `-m app.server --config data/sandbox/config.json`, port 8378).

### Part B: the guards

5. **`tests/test_repo.py`**: `test_no_forbidden_dependencies` (no `docker`, `riffado` or `supabase`, case-insensitive, in `requirements.txt` or any file under `app/`) and `test_plaud_only_through_cli` (only `app/plaud.py` runs the `plaud` executable; no file under `app/` contains `plaud.ai`).

### Part C: recording format 2

6. **`app/vault.py`**:
   - `save()` writes `recording.json.tmp` then `os.replace`, and refuses (raises) when the record's `schema` is higher than 2.
   - `migrate_v1(data, note_files)`: a pure function from a version-1 dict (and the front matter of the recording's note files) to a version-2 dict, exactly as the migration rules in 5.2. Integer speaker `k` becomes `"S{k+1}"` everywhere (utterances, `speakers`); `diarization.turns` is made from the utterances with `engine: "migrated"`; `notes` comes from the note files' front matter with both revisions 1; `stage: "done"`; `duration_s` from `duration`; `start_at` cut to seconds; `history: []`; `true_speakers: null`; `transcript.rev: 1`; `speakers_rev: 1`.
   - `migrate_all()`: for every recording without `schema`, write `recording.v1.json`, read it back and compare, then save the migrated version. Called once in `server.main()` after `seed()`.
   - `speaker_name(rec, spk_id)` works with string ids and `{"name": …}` entries.
7. **Every reader and writer of speakers** moves to string ids in the same change: `speech.utterances` and `tidy_turns` keep returning ranks, and `pipeline._speakers` turns rank `k` into `"S{k+1}"` and stores the turns in `diarization.turns` (engine, `rev` +1, `asked.num`). Stable ids across a redo are ticket 03's job; here a redo still renumbers and still clears names, as today. `pipeline.rename_speakers` and `/api/speakers` take ids like `"S1"`. `generate` adds its note to `rec["notes"]` (blueprint, provider, file, time, both revisions).
8. **`/api/state`**: keep an in-memory cache of each `recording.json` keyed by path and modification time, and return summaries without `words` or `utterances` text.
9. **`README.md`**: a short "Sandbox" paragraph (how to make it and start it) and one line on the new format.

## Tests

- `tests/test_schema.py::test_v1_migrates_to_v2`: fixtures made from the four vault recordings with their `words` removed and utterance texts shortened (save them under `tests/fixtures/`; they hold no full meeting text). Check ids, notes, `stage`, `duration_s`, `start_at`, synthetic turns.
- `::test_save_is_atomic`: make `os.replace` raise; the old file is still there and intact.
- `::test_v2_round_trip`: save then load gives the same dict.
- `::test_newer_schema_is_read_only`: `schema: 3` cannot be saved.
- `::test_migrate_all_keeps_v1_copy_and_skips_on_error`: a broken file is left unchanged.
- `tests/test_core.py::test_move_keeps_every_note_and_wikilink`.
- The existing tests, changed only where speaker ids became strings.

## Done when

- [x] Common checks
- [x] `.venv\Scripts\python scripts\make_sandbox.py` copies 4 recordings; the owner's vault's newest file time is unchanged
- [x] Before migrating, save a copy of each sandbox `… - Transcript.md` and hub note to `%TEMP%`. Start the sandbox server: all four sandbox recordings now have `"schema": 2` and a `recording.v1.json`. The regenerated transcripts are identical to the saved copies, and the hubs differ only in the list of notes or the talk-time speaker ordering required by design 5.2 (write the diff in the Progress log)
- [x] `GET http://127.0.0.1:8378/api/state` answers in under 0.3 s and contains no `words`
- [x] Guard check: add the word `supabase` to a temporary file in `app/`, see `test_no_forbidden_dependencies` fail, then delete the file
- [x] Rename one sandbox speaker through `/api/speakers` with `{"S1": "Test name"}`; the transcript shows it. Then clear it again.
- [x] Stop the sandbox server

## Not in this ticket

Names surviving a redo, overlap, embeddings (ticket 03). The job queue and stages (ticket 02). Note revisions and out-of-date logic (ticket 05).

## Decisions

- 2026-11-17: Work in the existing clean `rebuild-official-cli` checkout; one final commit for this ticket. Follow the AGENTS instructions supplied in chat (no AGENTS.md exists on disk).
- Keep legacy display metadata (`model`, `duration`, `speaker_engine`, `num_speakers`) alongside schema 2 so existing dashboard and Markdown output stay compatible. Redo still clears names until ticket 03.
- Save resume checkpoints here after each stage; no real provider calls or GPU jobs are needed (budget: 0 calls).
- Reject explicit missing config files instead of silently falling back to the owner vault; sandbox copying ignores PLAUD_CONFIG and rejects overlapping paths, symlinks and Windows junctions before replacement.
- Migration preserves an existing backup only if its bytes and decoded JSON match the source. Conflicting or incomplete backups cause that recording to be skipped and logged. Migration itself changes JSON only; rendering is verified separately.
- Design 5.2 takes precedence over the original hub-diff acceptance wording: rendering orders speakers by computed talk time. The English recording's brief Speaker 6 moves after Speakers 7–9; allow and record this ordering-only change in acceptance. The design itself is unchanged.
- Cache only summaries by recording path/mtime; refresh note filenames each request so Obsidian additions/deletions remain visible. Broken/unmigrated JSON is logged and omitted from state, leaving the original file intact.
- Keep source revisions from the note prompt, then reload the recording after provider work so intervening renames/moves are not overwritten. Full note-staleness handling remains ticket 05.

## Progress log

### Checkpoint 0 — 2026-11-17 — scope read, implementation starting

- Baseline: branch `rebuild-official-cli`, HEAD `42c0ef7`, clean working tree. Read README, workflow, ticket, schema/sandbox design, all storage/pipeline/server callers and dashboard speaker handling.
- In progress: Part A delegated to sandbox agent (config, early server config parsing, sandbox helper, launch entry, isolated tests). Root owns Parts B/C, fixtures, verification and docs.
- Scope: `app/config.py`, `app/server.py`, `app/vault.py`, `app/pipeline.py`, sandbox script, launch config, schema/guard/cache tests, reduced fixtures, README and ticket/checkpoint board documents. Speech ranks remain integers; convert at pipeline boundary. Dashboard already preserves string keys.
- Safety: do not start default server or write owner vault. Only `scripts/make_sandbox.py` reads owner vault. Capture source newest file time through that script before copying; it has not been read or modified yet. Never stop port 8377.
- Next: finish sandbox and baseline tests; copy sandbox and capture original hub/transcript files to TEMP; add guards; implement atomic migration and schema consumers; test and run sandbox acceptance; stop sandbox, update board, commit once.
- Resume: inspect `git diff` and this log first. No server started, no migration run, no provider calls (0), no GPU work.

### Checkpoint 1 — 2026-11-17 — sandbox copied, schema implementation underway

- Baseline suite: 15 passed. Part A: 11 sandbox/config safety tests passed. Schema tests first failed for missing migration/atomic writes; storage tests now pass. Guards pass after narrowing executable detection to process calls rather than ordinary Plaud labels.
- Ran `.venv\Scripts\python scripts\make_sandbox.py`: copied **4 recordings, 26 files**. Source newest UTC before/after: **2026-11-17T06:06:15.855943+00:00**. Baseline metadata in `data/sandbox/source_snapshot.json`.
- Original sandbox hubs/transcripts saved to `C:\Users\<user>\AppData\Local\Temp\plaud-ticket01-before-fbv0ve93`; manifest `data/sandbox/verification.json` maps each file. Do not recreate sandbox before completing comparison.
- Four fixtures in `tests/fixtures/recording-v1-*.json`: words removed, every utterance and memo text replaced with placeholders, note front matter retained. Source was the sandbox copy only.
- Implemented vault migration/atomic save/future schema guards and pipeline string IDs/revisions/note registry; pipeline integration check was observed failing before its implementation and needs rerun. No server started yet, sandbox remains v1.
- Next: add server summary cache and API tests; complete fixture/move/failure tests; run full suite; start sandbox for migration, render comparisons and rename/clear; run negative guards; stop server; verify source timestamp; docs/board/final commit.
- Provider calls: 0. GPU jobs: 0. Owner vault writes: none.

### Checkpoint 2 — 2026-11-17 — implementation checked, live acceptance starting

- Full suite: **46 passed**, no skips; one installed Starlette/httpx deprecation warning. Includes four real reduced fixtures, interrupted backup/verification/replace with retry, unknown-schema write protection, move/link integrity, pipeline provenance, config isolation and cache/API tests.
- Independent code review found three regressions; all reproduced by failing tests then fixed: cache refreshes Markdown filenames independently of JSON; note generation reloads current record after provider while preserving prompt revisions; empty diarization still registers the transcript's fallback S1.
- Sandbox server launched hidden via `.venv\Scripts\python -m app.server --config data/sandbox/config.json`; its PID is persisted at `data/sandbox/server.pid`, logs at `data/sandbox/server.stdout.log` and `.stderr.log`. Port 8378 was free before launch. Do not stop any other process, especially port 8377.
- Next: verify all four backups/schema 2; regenerate sandbox hubs/transcripts and compare against checkpoint 1 TEMP copies; time state requests, rename/clear S1, run negative dependency/CLI guard checks, stop only saved sandbox PID; final source timestamp check through `scripts.make_sandbox.source_snapshot`; README/checkpoint/board and one final commit.
- Provider calls remain 0, GPU jobs 0. Resume using `data/sandbox/verification.json` and the saved server PID; do not recreate sandbox or lose pre-migration copies.

### Checkpoint 3 — 2026-11-17 — acceptance passed, ready for final commit

- Live startup migrated **4/4** sandbox recordings with `recording.v1.json` backups; words and marks are unchanged. Regenerated **4/4 transcripts byte-identical**, **3/4 hubs byte-identical**. Only English hub diff: speaker order `[1,2,3,4,5,6,7,8,9]` becomes `[1,2,3,4,5,7,8,9,6]`; all other front matter and body text match. This follows design 5.2; acceptance wording/decision above records the conflict.
- Six real `/api/state` requests: **0.088641, 0.053253, 0.046447, 0.032473, 0.032568, 0.042723 s**; four recordings, no `words` or `utterances` text. Real `/api/speakers` rename S1 to Test name, clear and restore original names passed with transcript checks.
- Negative guard checks: temporary `app/_ticket01_guard_probe.py` containing `supabase` caused the dependency test to fail; a direct subprocess Plaud invocation caused the CLI test to fail. Probe never executed and was removed in `finally`.
- Stopped only sandbox PID **14404** (the PID launched here, verified as Python with matching start time). WMI command-line lookup was unavailable under sandbox permissions; process-name/start-time verification worked. **Port 8378 confirmed closed**. Port 8377 was never stopped or sent a mutating request.
- Owner vault newest UTC at start: **2026-11-17T06:06:15.855943+00:00**; after all acceptance: **2026-11-17T06:06:15.855943+00:00**. File/recording counts also unchanged, checked through the sandbox helper.
- Real provider calls: **0**; GPU jobs: **0**. Sandbox poller's read-only Plaud listing reported no error. No packages installed.
- README and board updated; 02 and 03 are Ready. Detailed ignored verification manifest remains `data/sandbox/verification.json`; sandbox is migrated and stopped. TEMP comparison copies remain available.
- Resume if interrupted here: inspect diff; rerun `.venv\Scripts\python -m pytest tests -q` and `git diff --check`; commit ticket files once on `rebuild-official-cli`. Do not redo the live run unless implementation changes require it.
- Final validation: **46 passed, 0 skipped**; `git diff --check` passed. Independent scoped re-review found no blocking issues. Optional Obsidian visual check added to OWNER_CHECKS.md. Work is complete; only the single local ticket commit remains at this checkpoint.
