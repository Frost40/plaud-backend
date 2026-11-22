# Checkpoint — 2026-11-17 07:15

2026-11-19. All twelve tickets are Done. The owner confirmed the upgraded Obsidian hub and Windows autostart. Ticket 11 passed all 175 tests and both 13-step dashboard walks. The 72-minute import finished in 4 min 50 s with two speakers and zero retries. Peak sampled GPU memory was 2729 MiB and minimum available RAM was 12,198 MiB. Sandbox cleanup and the owner vault audit are complete. [Final verification](tickets/11-final-check.md#final-verification-on-november-19)

The earlier entries below describe the system on their respective dates.

## State

- Branch `rebuild-official-cli`, **nothing committed** (old Riffado/Supabase deletions are staged).
- 14 tests pass (`.venv\Scripts\python -m pytest tests -q`).
- Dashboard: `.claude/launch.json` name `plaud-dashboard`, http://127.0.0.1:8377.
- Vault: `C:\Users\<user>\Documents\Obsidian Vault\Plaud\`. Imported: "How to use Plaud"
  (folder `Plaud tutorials`), 07-23 (Inbox; ensemble transcript, 3 speakers, names not set),
  09-29 and "Steve Jobs & Bill Gates" (Inbox, speaker names not set).

## Verified by clicking in the dashboard

Import and move to a new folder (clicked with earlier code; import's parts re-checked since through
Transcribe again and Create), Create note (Claude), Redo speakers (automatic count), Save names
(checked in `recording.json` and the transcript), Transcribe again with `ensemble` on a full
22-minute recording (12 min in total, 8.5 of them speaker separation; dashboard answered in
under 0.3 s throughout).

## Fixed on 2026-11-16 (evening)

- Speaker over-splitting: `speech.merge_voices` (pooled voice print per cluster, merge at
  cosine >= `diar_same_voice` = 0.85). Full recordings vs Plaud's labels:
  07-23 3 speakers 90 %, 09-29 3 speakers 96 %, 11-10 2 speakers 88 % (user confirmed 3 and 2).
  Right count only for 0.84–0.86; fitted on these three, no held-out recording.
- Dashboard froze during speaker separation: now a child process.
- Notes hung forever for recordings with long titles (`vault.add_note` name collision). CLI
  output also goes to files instead of pipes now, as a precaution only.

## pyannote (added 2026-11-16, late evening)

- User accepted the terms and logged in (`hf auth login`). `.venv-pyannote` (git-ignored) holds
  pyannote.audio 4.0.7 + torch 2.14.1+cu126; `app/pyannote_worker.py` runs in it, started by
  `speech.diarize`. `diar_engine` = `pyannote` is the default; sherpa is the fallback.
- Full recordings, default settings, vs Plaud's labels: 07-23 3 speakers 96 %, 09-29 3 speakers
  96 %, 11-10 2 speakers 89 %; 1.5–3 min each including model load (sherpa: 9–29 min).
- Clicked in the dashboard: Redo speakers on 07-23 took 1 min 37 s, 3 speakers.
- Baseline data and both eval scripts: `data/speaker-eval/` (git-ignored).

## English, many speakers (2026-11-17)

Imported "Steve Jobs & Bill Gates" (1h21m, English, unseen by any tuning) through the dashboard's
import endpoint, default settings, automatic count: 6 min 19 s in total (transcript 2.7 min,
speakers 3 min, Claude note 15 s). Language detected `en`. Scored with
`eval/score_rec.py` (current path) against Plaud's named labels (`of_8a43.plaud.txt`):

- 93.9 % of seconds agree. This scorer works on the final transcript, not raw turns, so compare
  with 09-29 on the same scorer: 93.2 % (its raw-turn score was 96 %). The four on-stage voices:
  Gates 98 %, Jobs 96 %, Mossberg 94 %, Swisher 93 % of their Plaud seconds.
- Count is wrong: 9 found, about 10 real (4 on stage + about 6 audience questioners; five give a
  name, the last one at 79:15 does not). Three questioners (McNamee, the Sony Pictures one, Rob
  Kelly) are merged into Speaker 5. Jesse Corns is kept apart (Plaud files him under McNamee);
  79:15 is kept apart from Charlie Brenner (Plaud merges them; nobody listened to check). One
  phantom "Speaker 6": 8 s of scraps ("okay", "Well,").
- `keep_all` on the pyannote path: the old sliver floor here would be 89 s (2 % of the talk) and
  would have removed Speakers 7, 8, 9 (real questioners, 50/33/32 s) with the phantom. One
  recording; code left as is.
- Words: 7.5 % disagreement with Plaud's transcript (turbo, no glossary). Seen errors: "I want to
  say" -> "I want to clip", "Woz" -> "Walsh"/"laws".
- Clean stage audio from a published recording: easier than a meeting room.
- Started through the import endpoint (the same call the Import button makes), not clicked. The
  dashboard server was not running at the start and was restarted.

## Ticket 01 — 2026-11-17

Sandbox/config isolation, repository guards, atomic schema-2 migration, string speaker IDs,
note provenance and cached state summaries are complete. 46 tests pass. All four sandbox
recordings migrated with v1 backups; all transcripts match byte for byte. One hub reorders
Speaker 6 by talk time as design 5.2 requires. State took 32–89 ms; rename/clear passed.
Owner vault newest UTC stayed `2026-11-17T06:06:15.855943+00:00`; sandbox server stopped.
No GPU or provider calls. Resume evidence and checkpoints: `tickets/01-safe-ground.md`.
Tickets 02 and 03 are Ready; owner restarts the real dashboard when ready (ticket 00 part B).

## Open

Ticket 03 Done, 2026-11-17: speaker ids/names survive redo and retranscription; overlap markers, embeddings, history and confirmed-count API implemented. **72 tests passed, 0 skipped**; sandbox acceptance completed. Redo scored **95.4%** with ensemble words; turbo scored **94.2%** and preserved names/turns/fixes/marks. Owner explicitly accepted the score gate with that known model difference. Test names cleared, sandbox stopped; protected vault newest UTC unchanged (`2026-11-17T06:06:15.8559430Z`); AI calls 0. Evidence and decisions: `tickets/03-speaker-names-survive.md`, checkpoint 6. Board: 03 Done; 04 and 06 Ready. Next ticket: **04**. Work belongs to the ticket 03 commit on `rebuild-official-cli`; do not follow the historical uncommitted-tree or pending-acceptance notes above.

Ticket 02 Done, 2026-11-17: SQLite jobs, stage resume, retries/auth pause, doctor, logs, paging, dashboard Retry, autostart script and setup docs implemented. **61 tests passed, 0 skipped**; diff check clean. Live sandbox missing-model/Retry/restart check passed; audio was not downloaded again. Original sandbox config/blueprints restored, new recording removed, sandbox/browser stopped. Protected vault newest UTC unchanged (`2026-11-17T06:06:15.8559430Z`). One Claude attempt used (no usable answer; existing Whisper fallback). Board: 02 Done, 09 Ready; next ticket is 03. Full evidence: `tickets/02-reliable-imports.md`. Owner tasks: `OWNER_CHECKS.md`. Resume here, not from the historical uncommitted-tree note above.

1. Not tested: people talking over each other in a real room; a real English meeting of the
   user's own; the `ensemble` model on English.
2. Not tested at all: merging two speakers by giving them the same name; Codex notes (ChatGPT
   usage limit was hit during testing).
3. Known gaps: photo files are not available from Plaud's CLI; notes written before a "Redo speakers" keep the old labels;
   the 07-23 "Meeting minutes" note predates its ensemble transcript.


- 2026-11-17, ticket 04 complete on rebuild-official-cli: reversible speaker merges/fixes, immediate guarded API, ranged audio and speaker dialog. 81 offline tests pass; real Jobs & Gates S5 -> S10 fix survives pyannote redo, Chrome playback returns 206, phantom successor S11 -> S4 merge/undo verified. Screenshot and exact model variation in tickets/04-fix-speakers.md. Sandbox/Chrome stopped, owner vault newest UTC unchanged at 2026-11-17T06:06:15.8559430Z, AI calls 0. Next: ticket 05; 05/08 Ready. Resume from ticket 04's final checkpoint, not the historical initial state above.

- 2026-11-17, ticket 05 implementation reviewed, **104 offline tests pass**, JS/diff checks pass; **live acceptance pending**. Free note relabels, provenance, freshness, glossary, protected regeneration, indexed hub and dashboard/API implemented. Real 07-23 rename and turbo retranscription verified; browser Regenerate submitted job 8, but Claude attempt 1/2 failed ECONNREFUSED. Auto-review rejected a network-unrestricted restart; explicit owner approval requested for the remaining call. Job 8 stopped as failed, all test processes stopped, only sandbox 07-23 restored from read-only owner source; 24 other files unchanged. Protected vault newest UTC before/after 2026-11-17T06:06:15.8559430Z. **Resume from ticket 05 checkpoint F**, not earlier checkpoints: one allowed call remains, real regeneration/backup still unchecked, board 05 Ready, changes intentionally uncommitted until all Done checks pass.

- 2026-11-17, **ticket 05 Done**, superseding the pending entry above: owner approved the remaining call with **Claude Haiku**; job 9 regenerated the same note in 20.1s, all blueprint checks passed, revisions/labels match the prompt, and the `(your edit 1).md` backup exactly matches the hand edit. Browser shows current/no Regenerate; no JS errors. **104 offline tests pass**; review complete. Both test server/browser stopped, only sandbox 07-23 restored, 24 other sandbox files unchanged; owner vault newest UTC before/after **2026-11-17T06:06:15.8559430Z**. Total AI attempts 2 (one failed connection, one successful Haiku), no production provider config changed. Final evidence/resume: **ticket 05 checkpoint J**; one ticket commit on `rebuild-official-cli`. Next Ready: **06**; 07 still needs 06. No acceptance rerun needed.

- 2026-11-17, **ticket 06 Done**: added `eval/` (`metrics.py`, `plaud_labels.py`, `run.py`, moved `score_rec.py`/`merge_eval.py`/`pyannote_eval.py`), `ensemble_languages`, and `_model` unload before `pyannote` in `app/speech.py`; **110 offline tests pass, 0 skipped**. Sandbox imported `11-10` in 504.6 s (`/api/state` <= 91.2 ms; pipeline VRAM 4.23 GiB turbo / ~5.91 GiB pyannote delta, system-wide peak 7.54 GiB w/ desktop apps, 0 OOM) and measured all 8 proxy runs (`documentation/EVAL-BASELINE.md`; `09-29` `score_rec.py` 93.2%; 26/26 AI calls). Removed `"en"` from `ensemble_languages` default (`["it"]`) after Jobs & Gates showed 7.67% vs 7.55% WER; sandbox stopped (`11-10` kept), owner vault UTC unchanged (`2026-11-17T06:06:15.855943+00:00`), ticket 07 now **Ready**.

- 2026-11-18, **ticket 07 Done**. Three Haiku calls verified note extraction and permanent rejection in the sandbox. All six Italian proxy runs finished. Keep automatic Whisper terms enabled (pooled WER 21.810% → 19.806%, term errors 12 → 9). 118 tests passed. Sandbox stopped and protected vault timestamp unchanged. Evidence in [ticket 07](tickets/07-automatic-glossary.md#progress-log) and [EVAL-BASELINE](EVAL-BASELINE.md#ticket-07-glossary-comparison). Next Ready is 08.

- 2026-11-18, ticket 08 Done. The speaker panel offers opt-in names from confirmed same-engine samples and remembers refusals. Sandbox Chrome showed the three-person enrollment gate. The Jobs & Gates pyannote benchmark matched all four on-stage voices with zero wrong suggestions. 126 tests passed, none skipped. Sandbox stopped, owner vault timestamp unchanged, no AI calls. See `tickets/08-known-voices.md`, checkpoint C. Next Ready: 09.

- 2026-11-18, **ticket 09 Done** and merged into `rebuild-official-cli`: added `arbiter_provider`, per-provider `check` prompt and `<data_dir>/providers.json`, `llm.classify`, 2 h usage-limit backoff, per-provider auth pausing/unpausing, `app.doctor --providers`, dashboard provider check filter + **Check providers** job, and `tests/test_llm.py`. **166 passed, 0 skipped** post-merge (`08 + 09`, including live CLI injection checks for `claude`, `codex`, `antigravity`); sandbox/CLI checks verified, protected vault UTC unchanged (`2026-11-17T06:06:15.855943+00:00`). Evidence in [ticket 09](tickets/09-providers.md#progress-log). Next Ready: 10.

- 2026-11-18, **ticket 10 Done**. Dashboard redesigned with the owner in four parts: Warm Studio look; folder rail with Library, search, ⚙️ Settings and tabs (Transcript, Glossary, notes, "+"); speakers fixed by clicking names in the transcript, one question at a time; note state dots, "+" card, an AI chip, and an editable Glossary tab (two new routes, with a version check). Default "Speaker N" labels are no longer learned as glossary words. 171 passed, 1 deselected: the real-Claude injection test fails on the CLI's own files in `TEMP\claude` (owner to decide). 6 AI calls and 3 GPU jobs in the click-through; protected vault unchanged. See [ticket 10](tickets/10-dashboard-redesign.md#progress-log). Next Ready: 11.
