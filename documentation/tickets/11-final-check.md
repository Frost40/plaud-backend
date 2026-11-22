# 11: Final check and hand-over

**Needs:** 10 · **Size:** M

**Suggested model** (choose one; ★ = recommended):
- Low (a flash model: Haiku, Luna or Gemini Flash): not enough: it judges the whole product and must notice what is subtly wrong.
- Medium (Sol or Sonnet): possible, but it may miss problems that cross tickets.
- ★ Hard (Opus or Astra): recommended: the whole product is checked, and the owner's real vault must be proven untouched.

## You get

Proof that everything built in tickets 01 to 10 works together, twice in a row, on a copy of your vault. You also get a plain-words note of what changed, what to do after updating, and what is still left for later.

## Read first

`documentation/DESIGN.md`:
- section 2 (every requirement and its acceptance test);
- section 7, M8 (the click-through list);
- section 10 "Deferred and rejected";
- `documentation/tickets/WORKFLOW.md` "Left out on purpose".

## Build (in this order)

1. **Requirement tests:** for each of R1 to R12 in section 2, find the named test or manual check and run it. A test named there that does not exist is either written now, if it is small, or listed in the hand-over with the reason. R1's absolute floors wait for ground truth (D2): report the proxy numbers from `documentation/EVAL-BASELINE.md` instead.
2. **Fresh sandbox:** `.venv\Scripts\python scripts\make_sandbox.py`, then start the sandbox server.
3. **The walk-through:** the M8 list of section 7, all 13 steps, in the browser pane on `http://127.0.0.1:8378`, with at most 6 AI calls per pass. A fresh sandbox has too few named people for voice suggestions, so step 11 is checked by running `.venv\Scripts\python eval\voices_check.py` instead, and step 12 by generating notes for two recordings of the same folder. Fix what fails, with a test for each fix, and walk again from step 1. The walk is done when **two passes in a row** find nothing.
4. **Docs against the real system:** check `README.md`, `documentation/SETUP.md` and `documentation/CHECKPOINT.md` against what the program really does. Every command must run, and every setting named must exist in `app/config.py`. Fix the docs, not the code, unless the code is wrong.
5. **Clean-up:**
   - delete `data\sandbox\`, `data\eval\vram-1110.csv` and any `*.tmp` file left in the project;
   - keep `data\eval\results.jsonl` and `data\speaker-eval\`;
   - check that no test fixture holds full meeting text.
6. **Real data untouched:** in the owner's vault, list the recordings and their `schema`. Check that no file holds a sandbox id, a test name ("Uno", "Due", "Tre", "Docente", "Test name") or a `_Voices.json` from the tests. Compare its newest file time with the one written at the start of ticket 01. Any change after that must be the owner's own dashboard (ticket 00, part B). Write what you found.
7. **`documentation/HANDOVER.md`**, for the owner, in plain words:
   - what is new, as things you can now do;
   - what to do after updating (restart, autostart);
   - the measured numbers with their "proxy" caveat;
   - what is left for later (the Flutter app, ground truth, photos), and the open lines of `OWNER_CHECKS.md`.

## Tests

- The full suite.
- One test per fix made during the walk-through.

## Done when

- [x] Common checks
- [x] Every requirement R1–R12 has a result line in the Progress log (passed, proxy number, or listed in the hand-over with its reason)
- [x] Two walk-through passes in a row with nothing found; the Progress log lists both
- [x] `data\sandbox\` no longer exists
- [x] The real-vault check of step 6 is written in the Progress log
- [x] `documentation/HANDOVER.md` exists and `README.md` links to it
- [x] Every ticket on the board is Done

## Not in this ticket

New features or redesigns: problems found that are not faults go into `HANDOVER.md` as suggestions.

## Decisions

- Use the two short Plaud tutorials for provider notes. Turn off the copied Meeting minutes blueprint's automatic run so the budget goes to explicit note actions. Count setup probes separately and carry their actual readiness results into repeat passes.
- Use an isolated headless Chrome window driven through its loopback debugging port. The session has no integrated browser pane.
- Measure the long import with Whisper turbo in `int8_float16`, automatic speaker count and notes disabled. Limit speaker batches to eight and reserve 8 GiB of available RAM for desktop use during the measurement.

## Progress log

- 2026-11-18, start on `rebuild-official-cli`. Clean worktree. Using the AGENTS.md instructions supplied by the owner in chat (no repository copy found). Real vault newest file before any run: `recording.json`, 2026-11-17T06:06:15.8559430Z. No AI calls or M8 passes yet. Resume with R1–R12 and confirm port 8378 is idle before replacing the sandbox.

### Checkpoint A — initial verification

- R1: both metric tests passed. Italian ensemble word disagreement 14.88%, 10.10%, 20.23%; English 7.67%. Absolute floors and parity await D2.
- R2: CLI/stdin, HTTP transport and provider routing tests passed. Live sandbox doctor returned OK for Claude, Codex and Antigravity (3 short calls); optional API key absent. Doctor probes readiness; ticket 09 separately exercised note generation.
- R3: same blueprint/two providers test passed, including both hub links.
- R4: both move tests passed, including note links.
- R5: fixture migrations, atomic save and round-trip passed. Fresh sandbox copied 4 recordings/26 files and served 4 recordings on 8378.
- R6: marks in render, retranscription, redo and note prompt passed. Compared both sandbox hubs with fresh official CLI highlight exports: 07-23 matched 3/3, 09-29 matched 6/6, including every displayed second.
- R7: forbidden dependency guard passed.
- R8: CLI-only guard passed; real read-only sign-in and highlight downloads succeeded.
- R9: offline controller suite passed. M8 still open.
- R10: folder/global dedup and blueprint hot-reload tests passed.
- R11: single GPU job test passed, sandbox doctor reported GPU OK and ffmpeg not needed. Ticket 06 measured 504.6 s, max state latency 91.2 ms, peak 7721 MiB (41 MiB above the ceiling); a fresh long import has not been measured.
- R12: 169 offline tests passed before the logging fix. Three live CLI cases excluded from that run. Full suite and M8 remain open.
- Preliminary walk imported Welcome with turbo and count 2. Found HTTPX logging a signed URL on successful download; failed status messages also contained the URL. Changed HTTPX server logging and download status errors; 20 core tests passed. Clean passes so far: 0. Stopped sandbox PID 57948 and isolated Chrome PID 27656. No note calls during the preliminary import.
- Real vault audit: Jobs & Gates, 07-23, 09-29 and How to use Plaud each lack a schema key (legacy v1). No _Voices.json or occurrence of the previous sandbox-only Welcome ID in Markdown or JSON. Literal Tre occurs in Jobs & Gates and Uno/Due in September source material predating ticket 01. No Docente or Test name. End-of-ticket comparison still due.

### Checkpoint B — first click-through findings

The first post-fix import downloaded, transcribed and separated Welcome; the fresh server log had zero signed queries. Moved the recording and saved both names. Listen failed: Chrome had requested audio while the recording was still at stage `new`, cached a 404, then reused the broken player. Reloading the media manually demonstrated that the bytes played. The MP3 tutorial was also being served as Ogg. Fixed the initial media request and content type. All 13 server tests passed. No note calls; still 3 setup probes overall and 0 clean passes. Four schema fixtures contain zero words and only placeholder utterance text. Owner speaker maps have no test names.

For both clean passes start from a fresh sandbox, saved real provider readiness results, auto notes disabled, and a sandbox-only Tutorial overview blueprint asking for presenter names and for Plaud in the glossary if mentioned. Use Welcome with count 2 and the existing How to use Plaud for the second note source. Never reset the sandbox while a pass is in progress.

### Checkpoint C — post-fix walk, pass 1

Fresh copy at 20:00 local. Imported Welcome (turbo, count 2, job 1), moved it to Tutorial checks (job 2), named S1 Presenter and S2 Guest, clicked Listen and observed advancing audio, joined S2 into S1, moved the first passage to a new speaker and saw Undo. Submitted fixed-count redo (job 3). Chrome port 9381; server 8378. On resume inspect the job list and note index before sending anything: the browser is scripted to proceed after job 3 with two Tutorial overview notes (Claude, Codex), rename Presenter to Host, verify both bodies, and queue large-v3 retranscription. No automatic notes, retries or ensemble calls scheduled by the pass. Latest offline suite 171 passed, 3 live cases deselected. Readiness probes 3 outside the pass.

- Steps 7–10 completed. Redo preserved Presenter. Jobs 4/5 generated separate Claude and Codex notes. Renamed Presenter to Host and read both rendered bodies: each contained Host, neither contained Presenter, and no provider job ran for the rename. Job 6 (large-v3) made both stale. Job 7 regenerated the Claude note; Codex remained stale. Three pass calls so far.
- Released the idle server's cached GPU model before the external voices check. The owner server was offline and the restarted sandbox idle. Step 11 benchmark session 7714. Step 12 uses How to use Plaud as the second recording in Tutorial checks; look for job 9 before retrying. Pending: results of 11/12 and controlled mid-job restart for step 13, then repeat from a fresh copy. Ticket 11 audit reran both README scoring commands on migrated July audio metadata: 15.09% word disagreement, 4.63% attribution error, 3/3 speakers and 95.4% per-second agreement. This source copy predates the ticket 06 sandbox experiments.
- Step 11: pyannote matched 4/4 on-stage voices with 0 wrong. Step 12: after moving How to use Plaud and generating its Claude note, 5 previously absent terms appeared with two recording IDs, including Plaud and Ask Plaud. Count: 4 calls in pass 1. Step 13: stopped only the sandbox during job 10. Its SQLite row was still running with 0 attempts while the server was down. Restarted the sandbox; verify job 10 finishes before resetting. Source scan across all files, including audio, found zero occurrences of any of the three sandbox-only recording IDs identified from the old copy and tickets.

### Checkpoint D — pass 1 complete; pass 2 in progress

Pass 1 clean, 13/13. After restart, browser reported job 10 done with 0 attempts and one row. At 20:09 the server and Chrome were stopped and a new 4-recording sandbox was made. The source timestamp still matches ticket 01. Pass 2 recreates the same browser actions and the real readiness cache. Check the current sandbox jobs before any retry: job IDs restart from 1. Only 4 AI calls in pass 1 plus 3 earlier readiness probes.

### Checkpoint E — paused at the owner's request, 2026-11-18

The owner needs the PC. Wait for their go-ahead before starting the server or any benchmark. The sandbox server, GPU worker and isolated browser were stopped. Ports 8378 and 9381 have no listeners; no Python process from this run remains. Keep the existing sandbox for resumption.

Pass 2 stopped during step 1 (Welcome, job 1). Download and transcription completed; the last log line was speaker separation. SQLite still says running, attempts 0, as expected after stopping the worker. When the owner is ready, start the sandbox server with its existing config; startup requeues the job. Verify it finishes, then proceed to step 2. Do not copy the vault again or submit another import. Pass 2 provider calls: 0. Total so far: 7 (3 readiness, 4 pass 1).

After pass 2: fresh R11 measurements remain open. Keep 11-10 local unless the owner authorizes sending the transcript to Claude. Three live provider containment checks remain outstanding; ticket 10 records the Claude runtime-file discrepancy. Finish the handover, cleanup and final vault timestamp check, then update the board and commit when its gates are satisfied. The owner-only restart and Windows sign-in check in ticket 00 remain open.

### Checkpoint F — resumed with desktop memory reserved

The owner authorized resumption while using the PC. The initial reading was 10.4 GiB available RAM and 1663 MiB of 8192 MiB VRAM used. The sandbox runs below normal priority inside a Windows job limited to 4608 MiB committed memory across its process tree. Its monitor exits and kills that tree at less than 5 GiB free RAM or 6656 MiB total VRAM used. Only one GPU workload runs at once. The speaker pipeline now batches eight windows instead of the downloaded model's 32. No owner server was running.

Pass 2 jobs 1–5 finished. Listened to advancing playback, moved the recording, named, merged and reassigned speakers, verified the fixed-count redo retained Presenter, wrote both notes, and checked that both rendered bodies changed to Host with no provider job. Two pass calls. The guard shut down the first large-v3 retranscription when its external GPU monitor failed. Job 6 recovered from SQLite with the same ID using sandbox-only `int8_float16` precision and a direct NVIDIA driver memory counter. The pending browser command verifies both stale notes and regenerates Claude once. Inspect the job list before submitting any action. The existing sandbox still holds both recordings and the temporary guarded launch/browser scripts.

### Checkpoint G — second pass, restart submitted

Pass 2 steps 1–12 passed. Job 6 made both notes stale. Job 7 regenerated Claude only; Codex stayed stale. With both servers stopped, the 81-minute reference voice check using batches of eight again scored 4/4 correct with zero wrong; cutoff 0.669136. The first guarded invocation did not capture stdout, so the score table was captured on a second invocation. In the browser, job 8 moved the second tutorial and job 9 wrote its note. Six previously absent terms appeared in the glossary with two recording sources each. Four note calls in pass 2 (eight across the two passes, plus three readiness checks).

Step 13 stopped the sandbox during job 10; SQLite showed exactly one row, `respeak/running/0 attempts`, after shutdown. Closed the isolated browser to release RAM. On resume, run the guarded server with the existing sandbox when desktop headroom permits, and check job 10 finishes once without a retry. Then run the local-only R11 import with auto notes off, the full suite, and the final audit and cleanup. The temporary guard, state sampler, browser steps and resource logs are inside `data/sandbox/`. No outstanding provider dispatch for the tutorials. Production CLI temp files now follow each provider's working directory; the existing containment assertions remain intact.

- R12: full suite **174 passed, 0 skipped**, including all three installed-provider cases, in 50.46 seconds. One Starlette/httpx deprecation warning. Test tree capped at 1252 MiB. No changes to containment-test exclusions. Three fixture invocations bring the ticket's total provider invocations to 14 (3 readiness, 8 tutorial notes, 3 containment).
- R9: all 13 steps passed in the first walk, steps 1–12 plus interruption passed in the second. Only completion of the recovered job 10 remains for the second walk. R11 fresh measurement still pending. The standalone voice check and full suite are complete; do not repeat them on resume unless relevant code changes.
- Read-only vault audit after the suite: 4 recordings, 26 files, newest 2026-11-17T06:06:15.855943Z, identical to ticket 01. Jobs & Gates, July 23, September 29 and How to use Plaud all lack a schema key (legacy v1). No sandbox-only recording ID in any file, no `_Voices.json`, no test name in any speaker map. A whole-word check found capitalized Uno and Due in the original September prose, and lowercase Italian number words in July and September. The earlier Jobs & Gates substring match was not a whole-word test name. No Docente or Test name. All four schema fixtures have empty word lists. Repeat the timestamp comparison after cleanup.

Resume commands from the repository root:

1. Run `.venv\Scripts\python data/sandbox/guard.py server`. Its normal preflight requires at least 8200 MiB of physical RAM available, at most 3600 MiB of VRAM in use, and no competing dashboard work. Keep this guard alive. It requeues job 10 without submitting another job.
2. On port 8378, verify that job 10 ends once, with zero attempts, and the tutorial's speaker engine is pyannote. Both browser passes are then complete.
3. With the guarded server idle, run `.venv\Scripts\python data/sandbox/r11.py` once. It requires the November 10 recording to be unimported, checks that all copied blueprints have automatic notes off, and samples state latency and `nvidia-smi` every two seconds. The server guard logs RAM and VRAM separately. Inspect both the job and the CSV before reporting a pass. If interrupted after submission, inspect SQLite first; do not submit a duplicate.
4. Stop the guarded sandbox by creating `data/sandbox/server.stop`, record the numbers in the handover, then perform ticket cleanup, the final source timestamp comparison, board update and commit if the Done gates are satisfied. Keep the real dashboard on 8377 untouched.

### Checkpoint H — both dashboard walks complete; R11 submitted

Pass 2, step 13: the recovered job 10 finished exactly once, attempts 0; the saved recording is done, with Host retained. A 2458 MiB process-tree cap prevented a pyannote allocation during this deliberately interrupted tutorial check. The documented CPU fallback (sherpa) completed the job. Step 13 tests recovery; step 7 and the separate voice check exercised pyannote. Two completed 13/13 walks, four tutorial calls each.

With 8940 MiB available after releasing the tutorial server, the normal preflight passed. Local 72-minute import **job 11** was submitted once with turbo, automatic count and auto notes disabled. Guarded server limit 3550 MiB; `data/sandbox/r11-state.csv` contains elapsed seconds, state request seconds, job status, recording stage and two-second NVIDIA samples (first column is epoch time). The guard samples free RAM and VRAM separately. Inspect the existing job and both files before acting; do not rerun the import command or reset the sandbox.

### Checkpoint I — RAM regression fixed; clean measurement prepared

The first long import hit its Windows commit cap: faster-whisper requested another 634 MiB for 413449 overlapping FFT windows at once. The guard kept the desktop usable. The trial server was stopped before retry. The regular `config.json` sandbox contains the interrupted long job; leave it stopped.

The shared Whisper loader now builds identical log-Mel features in 3000-frame blocks. Full-recording gain normalization, window overlap, padding, language detection and decoding remain intact. A numerical comparison against the installed faster-whisper extractor passed for non-aligned audio spanning a quiet/loud block boundary, with both zero and normal padding. Full suite output: **175 passed, 0 skipped, 1 Starlette warning** in 78.06 s. The outer Windows guard returned nonzero after the summary. The earlier 174-case run and the new regression alone both exited successfully. Three further synthetic fixture invocations; ticket total 17 provider invocations.

**Resume from here, superseding the launch instructions above.** `data/sandbox/measured.json` points to a separate five-recording sandbox vault and fresh state database. All automatic blueprints are off. Run `.venv\Scripts\python data/sandbox/guard.py measured` once its normal RAM/GPU preflight passes. Then run `.venv\Scripts\python data/sandbox/r11.py` only if the measurement database is still empty and `r11-final.csv` does not exist. It checks the vault and job state before submitting. Once submitted, monitor that job instead of submitting again. Stop this server via `data/sandbox/measured.stop`. Record the measured limits, verify cleanup and the original vault timestamp, and close only the gates supported by evidence. Both M8 passes and the voice checks are complete.

At the last stop the preflight waited three minutes and exited without starting a server. The last reading was 7558 MiB of free RAM against the 8200 MiB startup threshold. No clean measurement job was submitted; ports 8378 and 9381 have no listener. The owner vault still matches its original snapshot. The installed Plaud/provider CLIs, hf executable, configured ONNX model paths, faster-whisper 1.2.1, CTranslate2 4.8.0, ONNX Runtime GPU 1.32.0 and separate pyannote 4.0.7 / Torch 2.14.1+cu126 environment were verified. No installations or owner sign-in changes were performed.

### Checkpoint J — clean long import running, 2026-11-19

The guarded sandbox started with over 10 GiB available RAM and a 4608 MiB process-tree limit. The first launch could not read the installed Plaud CLI. It stopped with zero jobs. The approved launch listed the target and accepted exactly one import, **job 1** in `measured-state/jobs.db`. Download completed and turbo started transcribing 01:12:29.880. Continue by inspecting this job, `r11-final.csv` and `measured-resources.csv`; do not submit again. Both walk-throughs are already complete.

The guard stopped that run when free RAM fell to 4999 MiB, with 2817 MiB of VRAM used. The last of 38 dashboard samples was at 74.2 seconds and the longest request took 88.3 ms. The database holds the one interrupted import, attempts 0, recording stage `downloaded`. Its sandbox config uses `int8_float16`. The sample covers only download and early transcription. After stopping all sandbox work, available RAM continued down to 4063 MiB. The original vault still matched all three baseline fields and had none of the three sandbox-only IDs. All 522 fixture utterances contained just the shortened-excerpt placeholder.

### Checkpoint K — ready for an uninterrupted measurement

Whisper now pads only the blocks at the edges of a recording. This also avoids two full-length audio buffers. The numerical regression now limits padding input size as well as FFT input size. An independent check of 25 padding and length combinations matched the reference indices.

The stopped recording, its database and its 38 samples are preserved together under `data/sandbox/interrupted-1/`. The measurement vault is back to its five-recording seed, with no active job database or final CSV. This allows a fresh time from submission to completion. The guarded pytest runner waits for desktop headroom. Let it finish before launching `guard.py measured wait`, then use `r11.py` once the read-only Plaud listing appears. Use the final CSV for the new run only. The previous trial sent no note and left the owner vault unchanged.

The final padding implementation also matched the installed Whisper calculation at five padding sizes spanning three to four blocks. A fresh full pytest run reached 84 completed items, then the 5 GiB RAM guard stopped it before pytest produced a summary. Do not count that run as a pass. The short offline suite can run with `guard.py offline wait`, followed by `guard.py tests wait` for a complete exit code. The sandbox has no active GPU worker. At 10:44 local there were 1669 MiB of system RAM available. The previous full-run summary and the interrupted checks are distinct. The old evaluation VRAM CSV was removed as requested. Both retained evaluation directories/files were verified, and a workspace scan found no `*.tmp` outside the disposable sandbox.

The current session has queued the offline suite, then the full suite, then the sandbox import and shutdown. Each stage requires the previous stage to exit successfully and has its own RAM preflight. Before launching anything after a session interruption, check `offline-output.txt`, `tests-output.txt`, `measured-resources.csv`, `r11-final.csv`, the measurement database and the guard processes. Check the final job status and counts, not just the sampler exit code.

Final-code offline run: **172 passed, three installed-provider cases deselected**, one Starlette warning, 10.66 s. Pytest and the outer guard exited 0. The 2057 MiB commit cap stayed active. The remaining queued stages are the complete suite and the clean R11 import.

### Resume after context reset (historical, completed)

**Paused at the owner's request on 2026-11-19.** This section supersedes all earlier launch instructions. The test/benchmark queue was cancelled. A process and listener check found zero ticket runners and zero listeners on 8378 and 9381. Nothing is scheduled to restart. Keep this working tree on `rebuild-official-cli`, including the untracked handover and the ignored sandbox helpers. Do not recreate the sandbox. No ticket 11 commit has been made.

Both 13-step dashboard passes, the four-speaker voice check and the final-code offline suite are complete. There is **one GPU job** left. Finish in this order from the repository root:

1. Run `.venv\Scripts\python data/sandbox/guard.py tests wait`. It waits for stable headroom, then runs the full pytest suite with the three installed-provider fixtures. Verify a **new** 175-pass summary in `data/sandbox/tests-output.txt` and exit 0 from the guard. The file contains an older 175-pass summary and a later interrupted run. The separate 172-pass offline run is already verified. Earlier completed runs accounted for 17 provider invocations; the interrupted rerun did not record a per-provider count. Use synthetic fixtures for these checks.
2. Run `.venv\Scripts\python data/sandbox/guard.py measured wait` using the installed read-only Plaud CLI and local model cache. Leave the guard running. It requires 8200 MiB free RAM and at most 3600 MiB system VRAM in use for 15 seconds, and stops at less than 5120 MiB free RAM or 6656 MiB VRAM used. The copied configuration uses turbo with `int8_float16`, speaker batches of eight and automatic notes disabled. Leave port 8377 and the owner vault alone.
3. The five-recording seed currently has neither `measured-state/jobs.db` nor `r11-final.csv`. Once port 8378 lists the November 10 recording as available and shows zero jobs, run `.venv\Scripts\python data/sandbox/r11.py` once. The sampler reserves its CSV before submitting and signals the guard to stop on completion or retry. If interrupted, inspect the saved row and samples before acting. Confirm one completed import, the saved speaker engine, attempts, elapsed time, maximum state latency and peak VRAM. Use the guard log for minimum available RAM. The 38 samples under `interrupted-1/` are from an incomplete trial.
4. Record the results in the handover and here. After the processes have stopped, finish the scoped sandbox cleanup, confirm the retained evaluation data and repeat the source snapshot (4 recordings, 26 files, newest 2026-11-17T06:06:15.855943Z). Update the board and checkpoint against the actual Done gates and commit the ticket changes. Ticket 00's owner-only dashboard restart, hub inspection and Windows sign-in check remain unconfirmed.

### Final verification on November 19

The full suite on the final code passed all 175 tests in 31.61 seconds with one Starlette deprecation warning. All three installed-provider fixtures ran. Pytest and the Windows guard both exited 0. The new sandbox listed five recordings, no jobs and one matching November 10 recording. The sampler submitted job 1. If interrupted, inspect `data/sandbox/measured-state/jobs.db` and `data/sandbox/r11-final.csv` before doing anything else.

The 4608 MiB process-tree cap stopped a CPU allocation inside the Pyannote worker after transcription succeeded. The server started the CPU fallback. The trial was stopped at 378 s and archived under `interrupted-2`. For the fresh trial the guard reserves 8192 MiB of physical RAM for the desktop and limits the process tree to the smaller of 7168 MiB and the available RAM above that reserve. The system-wide VRAM stop remains 6656 MiB. The new process tree received 6985 MiB and job 1 started from the five-recording seed. The 175 tests are already final.

**R11 passed.** The November 10 recording (1 h 12 min 29.88 s) took 290.21 s from submission to observed completion. The clean database contained exactly one import, done with zero retries. The recording reached `done` with 10,387 words, two pyannote speakers and zero notes. The slowest of 146 dashboard state requests was 115.67 ms against the 500 ms limit. The two-second GPU samples and 363 guard samples recorded a system-wide peak of 2729 MiB against the 7680 MiB ceiling. Minimum available system RAM was 12,198 MiB. The sampler signalled shutdown and neither sandbox port had a listener afterwards.

**R12 passed.** The final 175-test run included three synthetic provider invocations. Together with the completed earlier runs there were 20 confirmed invocations. An interrupted suite did not record a per-provider count. The measured import used none.

**Original vault audit.** Before and after the ticket, the newest write was 2026-11-17T06:06:15.855943Z. All 26 files and four recording metadata files were accounted for. Jobs & Gates, 07-23, 09-29 and How to use Plaud each still have legacy schema 1 (absent key). A scan of all files found none of the three sandbox recording IDs. There was no `_Voices.json` and no test name in a speaker map. The pre-existing words Uno, Due and Tre occur in source material as recorded in Checkpoint A. All 522 utterances across the four test fixtures contained only the shortened-excerpt placeholder.

**Final checkpoint.** The disposable sandbox and old VRAM CSV are gone. The workspace scan found zero `*.tmp` files. Both `data/eval/results.jsonl` and `data/speaker-eval/` were retained. The original vault passed the same audit after cleanup. All ticket 11 sandbox and test work is finished.

On 2026-11-19 the owner confirmed both the upgraded Obsidian hub and dashboard startup after Windows sign-in. This closes ticket 00 part B and the final ticket 11 acceptance check. All twelve tickets are Done.
