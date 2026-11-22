# 05: Notes that stay correct without wasting tokens

**Needs:** 04 · **Size:** M

**Suggested model** (choose one; ★ = recommended):
- Low (a flash model: Haiku, Luna or Gemini Flash): possible for the text replacement, but the change-share sums and the owned-file rules need judgement.
- ★ Medium (Sol or Sonnet): recommended: the design gives every rule as a table, and the code follows existing patterns (`_write_owned`, front matter).
- Hard (Opus or Astra): not needed.

## You get

- When you name, rename or merge speakers, the names change inside the notes you already have too, with no AI call.
- When a recording changes a lot (re-transcribed, speakers redone), its notes show "out of date" with a **Regenerate** button; small changes leave them alone.
- If you edited a note yourself, regenerating keeps your version as a copy.
- Notes use the folder's glossary for the spelling of names and terms.

## Read first

`documentation/DESIGN.md`:
- 5.5 "Notes and blueprints" (the whole section, especially the table "Keeping notes correct without wasting tokens");
- 5.2 the `notes` and `history` fields;
- owner decision D4 in section 9;
- section 2, R3, R6 and R10.

## Build (in this order)

1. **Front matter of new notes** (`pipeline.generate`): add `transcript_rev`, `speakers_rev` and `speakers` (id → name, the label used in the prompt, so `"S3": "Speaker 3"` when unnamed). The entry in `rec["notes"]` holds the same revisions (it exists from ticket 01).
2. **`app/notes.py`** (new, because rename, merge, re-transcribe and the dashboard all use it):
   - `relabel(rec, old_map, new_map)`: for every note in `rec["notes"]`, replace each old label with its new name as a whole word. This is a regex with word boundaries, the longest labels first, so "Speaker 1" does not match inside "Speaker 12". Update the front-matter map and `speakers_rev` in the note and in the index. It never calls a provider. Notes changed by the owner since writing (hash in `written`) are relabelled too: names are not the owner's content.
   - `state(rec, note)`: "current", "minor" or "out_of_date", by summing `history[].changed` for revisions after the note's own, against 0.02 (5.5 table).
   - `regenerate(rec_id, file)`: rebuild the prompt and rewrite the same file through `vault._write_owned` (keep the owner's edit as "(your edit n).md").
3. **Hooks:** `pipeline.rename_speakers`, `merge` and `unmerge` call `relabel`. When a re-transcription or redo leaves a note "minor", mark it `minor_change: true` in front matter and move its revisions forward.
4. **Glossary in the prompt:** `build_prompt` adds "Spellings to use: …" with `vault.glossary(group)` when it is not empty.
5. **Hub:** the list of notes comes from `rec["notes"]`. A file that no longer exists is listed as "(missing: name)" and logged, instead of a broken link.
6. **Dashboard and API:** each note shows its state; out-of-date notes get **Regenerate** (`POST /api/regenerate {id, file}`, a queued job).

## Tests

- `tests/test_notes.py::test_rename_rewrites_labels_without_llm`: the provider is a fake that fails the test if called.
- `::test_merge_rewrites_labels_without_llm`.
- `::test_small_retranscribe_keeps_note`.
- `::test_large_change_marks_out_of_date`.
- `::test_regenerate_keeps_owner_edit`.
- `::test_speaker_12_not_touched_by_speaker_1`.
- `tests/test_core.py::test_same_blueprint_two_providers_two_notes_both_in_hub` (two fake providers).
- `::test_marks_are_in_the_note_prompt`.
- `::test_blueprint_edit_is_used_without_restart`.
- `::test_glossary_folder_plus_global_dedup`.

## Done when

- [x] Common checks
- [x] Real run on the sandbox, recording 07-23 (at most 2 AI calls):
  1. Rename S1 to "Docente". The existing "Meeting minutes (claude)" note now says "Docente" where it said "Speaker 1", and the server log shows no provider call.
  2. Transcribe again with `large-v3-turbo`. The Progress log has the change share and the note's resulting state.
  3. If it is "out of date", press **Regenerate** once (1 call); otherwise regenerate it once anyway from the API to prove the path.
- [x] Guard check: edit the sandbox note by hand, regenerate, and see "(your edit 1).md" beside it
- [x] Put 07-23 back as it was: stop the sandbox server, delete the sandbox's 07-23 folder, and copy the same folder from the owner's vault (read-only on the source). Do not re-make the whole sandbox, because it may hold 11-10 from ticket 06, which ticket 07 needs.

## Not in this ticket

The automatic glossary (ticket 07; this ticket only passes the existing glossary to notes). Provider error handling (ticket 09).

## Decisions

- Reuse YAML front matter, the owned-file writer and SQLite worker; no dependencies or extra services. The approved ticket/design is the implementation plan.
- Work on the required `rebuild-official-cli` branch; checkpoint here after each testable part, with exact next actions and live-job/call counts.
- Whole-label substitutions are simultaneous and affect only the note body; YAML records the actual prompt labels. Relabelling preserves the ownership hash mismatch of edited notes so regeneration still backs them up.
- Exactly 2% is out of date (minor means strictly less than 2%). A relabel advances speaker revisions only when it cannot hide an earlier substantive change. Undoing a merge cannot split identical mentions back into two people: leave ambiguous mentions and retain the change history for regeneration.
- The hub and dashboard use the schema-2 note index; unindexed owner files and edit backups stay in the folder. Missing indexed notes show a warning without a broken link.
- Independent review found shared-name and prefix-name edge cases. Match unchanged longer labels too; ambiguous labels keep their actual provenance and set `relabel_failed: true` in note/index until regeneration, rather than claiming a successful rename or minor unmerge.
- Restore by archiving the test recording outside the sandbox vault, then copying the owner source read-only, instead of deleting evidence. Verify both restored contents and all other sandbox files by SHA-256.
- Owner approved the final external acceptance attempt and requested Claude Haiku. Use `--model haiku` only in the local acceptance runner; leave normal provider settings unchanged. An exclusive call-marker file enforces one remaining invocation across retries/restarts.

## Implementation checkpoints

- [x] Note provenance and shared relabel/state/regenerate logic, with failing regression checks first.
- [x] Speaker/transcript hooks, glossary prompt, indexed hub and missing-file warning.
- [x] Queued regenerate API and dashboard note states; focused and full offline checks.
- [x] Sandbox 07-23 rename/retranscribe/regeneration (at most 2 AI calls), owner-edit backup, restore only 07-23.
- [x] README/checkpoint/board, final vault timestamp comparison and one ticket commit.

## Progress log

- 2026-11-17 checkpoint A: clean tree on `rebuild-official-cli`; read user-supplied AGENTS.md (no physical file), README, workflow, design 5.2/5.5/D4 and affected callers. Workflow path is `documentation/tickets/WORKFLOW.md`. Protected vault newest UTC before: `2026-11-17T06:06:15.8559430Z`. Existing sandbox config: `data/sandbox/config.json`; preserve all other sandbox recordings, especially 11-10. AI calls 0, GPU runs 0, no server started. Next: regression tests for provenance, simultaneous whole-word relabel, cumulative revision shares and protected regeneration; then implement in ticket order. Resume by reading this ticket, `git diff`, and the latest checkpoint; never recreate the entire sandbox or mutate port 8377.
- Checkpoint B: note regressions failed first (missing provenance/module/relabel/hub behavior), then 12 passed. Shared logic and all callers implemented; API regression failed before the route/state/dispatch integration, then passed. Full offline suite: **98 passed, 0 skipped**, one pre-existing Starlette/httpx deprecation warning. Updated older fixture records with required `notes` arrays and state expectations with indexed-note behavior. Provider calls 0, GPU runs 0. Next: review edge cases, JS syntax/browser, sandbox 07-23 acceptance; record live PID/jobs and call count BEFORE launching expensive work. No sandbox recreation needed.
- Checkpoint C / live run: sandbox server PID **55092**, `data/sandbox/ticket05-server.pid`, port 8378; do not stop port 8377 (not listening at preflight). Queued turbo re-transcription **job 7**, recording `of_772c3a645b1b1e7d5180839292b7e793`. Do not submit it twice. Renamed S1 to Docente; existing Meeting minutes note has 7 Docente mentions and no Speaker 1; server log since startup contains no provider-writing line. Evidence `data/sandbox/ticket05-evidence.jsonl`; original sandbox recording JSON `ticket05-before.json`; other sandbox file hashes `ticket05-other-files.json`. JS passes `node --check` via stdin (file-path invocation hits sandbox EPERM). AI calls **0 of 2**, GPU runs **1 queued**. Next: poll job 7, record history change share/state; browser stale/current rendering; edit the note before regeneration to combine owner-edit guard with the first regeneration (stay within 2 actual provider calls, including any requires retry). Then stop sandbox, archive only sandbox 07-23 and restore that folder from owner read-only source; preserve other recordings.
- Checkpoint D / live provider: job 7 completed in **49.5s**, latest transcript change share **0.0**, note remains **out_of_date** because it predates transcript rev 2's **0.1005586592178771** change and speaker rev 3's **0.0007069635913750442** change. Chrome headless/CDP (PID **12096**, port 9225, isolated `ticket05-chrome` profile; initial sandboxed Chrome exited, second uses `--no-sandbox`) rendered the stale badge and Regenerate button without JS errors. Added `Ticket 05 owner guard.` to the sandbox note and clicked the real button: **regenerate job 8 queued**, budget **1 Claude call reserved of 2** (count retries in server.log). Exact edited note saved in `data/sandbox/ticket05-owner-note.md`; browser runner `ticket05-browser.py` MUST NOT be rerun (it submits another job). Next: poll job 8, verify backup matches saved owner note byte-for-byte and provenance/current state; save screenshot; do not resubmit or exceed 2 calls. Three extra edge checks pass for stale-fix retention, minor redo ownership and provider failure preserving the file.
- Checkpoint E / approval pending: Claude attempt **1 of 2** failed with `API Error: Connection refused ... ECONNREFUSED` after 177s. No regeneration or backup happened; edited note remains intact. Automatic approval review **rejected** restarting PID 55092 outside network restrictions because it would transmit sensitive recording/note content to Claude without more specific user authorization, and objected to forced termination. Asked the owner asynchronously for explicit permission for one remaining Claude attempt using transcript/marks/glossary. **Job 8 was changed from queued to failed, attempts stays 1, automatic retry disabled**; do not retry until owner answers. Sandbox PID **55092** and Chrome PID **12096** still running at this checkpoint. No protected data written. Independent reviewer found two relabel bugs; all three added regressions failed first, fixes pass (18 note tests). Next: finish offline re-review/docs; safely stop test processes and restore only 07-23 if approval not available. If approved, restart sandbox with current code and run exactly one final provider attempt (no requires retry beyond remaining allowance); verify owner backup and current note. Never rerun ticket05-browser.py or submit job 8 blindly.
- **Checkpoint F / resume here:** implementation and independent re-review complete; reviewer reports no remaining important issues. Full offline suite **104 passed, 0 skipped**, only the pre-existing Starlette/httpx warning; JS syntax and `git diff --check` pass. Live Claude regeneration/owner-backup acceptance is the only unfinished check, awaiting explicit owner approval. Board remains **05 Ready**, ticket 07 remains Waiting on 05 and 06; do not mark Done or make the ticket commit yet.
  - Test processes stopped: sandbox listener child PID **55460**, launcher **55092**, isolated Chrome **12096**. Cleanup alone was approved by auto-review; PowerShell Stop-Process failed internally, .NET process termination succeeded. Port 8378 is no longer listening. Port 8377 was never mutated.
  - Archived test 07-23 folder to `data/sandbox/ticket05-run-07-23`, then restored its original active folder from the owner vault (source read-only). Restored files match the source byte-for-byte; **24 other sandbox files unchanged** by SHA-256. The source recording is schema 1 again; normal next sandbox startup will migrate it, as designed. Original edited test note is also saved as `data/sandbox/ticket05-owner-note.md`.
  - Protected vault newest UTC **before AND after: `2026-11-17T06:06:15.8559430Z`**. Provider attempts **1 of 2 used**, no successful response; GPU re-transcriptions **1**, completed. Job **8 failed**, no retry queued; do not rerun `ticket05-browser.py` (it edits/submits again). Local evidence: `ticket05-evidence.jsonl`, `ticket05-stale.png`, `ticket05-owner-note.md`; server history `data/sandbox/state/server.log`.
  - Resume after owner approval: use existing sandbox config, start server with current code outside network restrictions, and make exactly **one** remaining Claude call on 07-23. Enforce the remaining allowance including blueprint `requires` retries (a local acceptance-only wrapper around `llm.run` may refuse any second invocation; no production config needed). Reapply Docente and an owner edit on the restored sandbox note, submit regeneration once, verify `(your edit 1).md` matches the edited note, note current/provenance and same filename, and screenshot. Stop sandbox, restore only 07-23 again, compare other-file hashes and vault timestamp, remove the pending owner-check entry, tick Done checks, update board/checkpoint and commit all ticket changes once on `rebuild-official-cli`. If approval is declined or provider still fails, keep this ticket open and log the exact failure rather than claiming the real check passed.
- **Checkpoint G / approved resume, 20:50:** owner explicitly approved the final Claude attempt and requested **Haiku**. Protected vault newest UTC still `2026-11-17T06:06:15.8559430Z`. Local runner `data/sandbox/ticket05-haiku-server.py` appends `--model haiku` in memory and enforces one invocation with exclusive `ticket05-haiku-call.json`; never delete that marker or rerun a provider after it exists. Production config unchanged. Next: start only sandbox on 8378 outside network restriction, reapply Docente/owner edit, queue one regeneration and record job id. Budget still **1 attempt used, 1 remaining**; no new GPU work needed.
- Checkpoint H / final live attempt: approved unrestricted sandbox launcher PID **56368**, port 8378; re-migrated restored recording, renamed S1 to Docente without provider call, added `Ticket 05 Haiku owner guard.` to the note and saved exact bytes as `data/sandbox/ticket05-haiku-owner-note.md`. **Regenerate job 9 queued**, model **Haiku**, final attempt reserved (**2/2 total**). Do not submit another regeneration. Next: poll job 9 and `ticket05-haiku-call.json`; verify note/index/current state and exact `(your edit 1).md` backup, then browser screenshot/cleanup/restoration. If it fails, stop the job's automatic retry; the call marker prevents additional provider invocations.
- Checkpoint I / acceptance passed: **job 9 Done in 20.1s**, **Claude Haiku**, exactly one invocation (marker `ticket05-haiku-call.json` status returned, 3019 output characters); total **2 attempts used**, first failed/second successful. Same Meeting minutes filename and single index entry; state **current**, transcript revision **1**, speaker revision **2**, S1 label **Docente**, all blueprint checks pass. `(your edit 1).md` is byte-for-byte identical to `ticket05-haiku-owner-note.md`; new note excludes the guard edit and hub links only the indexed generated note. Chrome/CDP confirms current badge, no Regenerate button and no JS exceptions; screenshot `data/sandbox/ticket05-current.png`. Browser closed through CDP. Next: stop only sandbox launcher 56368/listener child, archive this test recording to `ticket05-haiku-run-07-23`, restore only original 07-23 from read-only owner source, verify 24 other sandbox files and owner timestamp; full offline checks, docs/board and one ticket commit. No more provider or GPU calls needed.
- **Checkpoint J / final handoff (supersedes pending checkpoints above):** live acceptance complete with the owner's approved **Haiku** attempt. Stopped sandbox listener **34292** and launcher **56368**; Chrome closed; no provider retry remains. Archived acceptance output/backup to `data/sandbox/ticket05-haiku-run-07-23`, restored only sandbox 07-23 from the owner source read-only, verified byte-for-byte copy and **24 other sandbox files unchanged**. Protected vault newest UTC before AND after remains **`2026-11-17T06:06:15.8559430Z`**. No production provider configuration changed. Total provider attempts **2/2** (one refused connection, one successful Haiku); one earlier turbo GPU run. Offline code independently reviewed with no remaining important findings. Final full suite/JS/diff verification precedes the one ticket commit on `rebuild-official-cli`. Board **05 Done**; **07 remains Waiting** for 06; next Ready ticket is **06**. Do not rerun acceptance or recreate the sandbox. Resume from this checkpoint and Git status if interrupted during the final commit.
