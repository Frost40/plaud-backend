# 03: Speaker names that survive

**Needs:** 01 · **Size:** L

**Suggested model** (choose one; ★ = recommended):
- Low (a flash model: Haiku, Luna or Gemini Flash): not enough: the matching of old and new speakers is the heart of the owner's top priority.
- Medium (Sol or Sonnet): possible with the design's rules, but the edge cases (split, merged, vanished speakers) are easy to get wrong.
- ★ Hard (Opus or Astra): recommended: speaker attribution is the owner's first priority, and three parts (worker, pipeline, render) must change together.

## You get

- Names you give speakers stay on the right voices when you press "Transcribe again" or "Redo speakers".
- The transcript marks with ⇄ the places where two people talk at once, so you know where to double-check.
- The program keeps everything the speaker model found (who talked when, overlaps, and a voice print per person), so later corrections and voice recognition need no new GPU run.
- You can confirm the real number of speakers of a recording, and it is remembered.

## Read first

`documentation/DESIGN.md`:
- 5.4 rules 0, 1 and 2 (re-transcribing, automatic run, names surviving a redo) and the last paragraph (sherpa fallback);
- 5.2 the `diarization`, `speakers`, `true_speakers` and `history` fields;
- section 4.2 "Verified facts that change the design" (what pyannote returns);
- section 3, "Facts in the code" items 2 and 3.

## Build (in this order)

1. **`app/pyannote_worker.py`**: write one JSON object, `{"labels": [...], "turns": [[s, e, i]], "overlap_turns": [[s, e, i]], "embeddings": [[...]]}`. Here `turns` is `exclusive_speaker_diarization`, `overlap_turns` is `speaker_diarization` (which can overlap), and `embeddings` is `speaker_embeddings` in `labels` order. Keep passing audio as `.npy` (no ffmpeg).
2. **`app/speech.py`**:
   - `diarize()` returns a dict `{engine, turns, overlap, embeddings}`. `overlap` is the list of stretches where two or more `overlap_turns` are active, merged and rounded to 0.01 s. `embeddings` maps the worker's index to a list of floats.
   - On the sherpa path, `overlap` is empty and `embeddings` are the pooled voice prints that `voice_prints()` already computes.
   - `tidy_turns` keeps doing what it does (`keep_all` as today). No cap on the count (owner decision D7).
3. **`app/pipeline.py`**:
   - `match_speakers(old_turns, new_turns, old_speakers, fixes)` returns the new id for each new index, exactly as rule 2 of 5.4: greedy one-to-one by shared seconds; inherit when at least 50 % of the new speaker's talk time falls on that old speaker; otherwise a fresh id (`S<n>` with the next free number). Old speakers with a name or a fix are never dropped.
   - `_speakers` stores the dict in `rec["diarization"]` with ids, increments `speakers_rev`, appends to `history` (`kind: "speakers"`, `changed`: the share of words whose speaker id changed), and keeps `speakers` names through `match_speakers`.
   - `_transcribe` no longer calls diarization (rule 0). It re-assigns the new words to the stored turns with `speech.utterances`, increments `transcript.rev`, and appends to `history` (`kind: "transcript"`, `changed`: the share of words that differ, by `difflib.SequenceMatcher` on the two word lists). Diarization runs on import and on "Redo speakers" only. A migrated recording (engine `migrated`) uses its synthetic turns.
   - Phrases that overlap a stretch of `overlap` by 0.5 s or more get `overlap: true` (rule 1).
4. **`app/vault.py`**: the transcript shows `⇄` after the time of an utterance with `overlap: true`.
5. **`/api/speakers`** also accepts `{"true_speakers": n}` (0 clears it). The control in the dashboard comes in ticket 04.

## Tests

- `tests/test_speakers.py::test_retranscribe_keeps_turns_and_names`: a fake `speech` whose `diarize` fails the test if called.
- `::test_redo_keeps_names_by_overlap`: synthetic turns with shuffled indices, one speaker split in two, one new short speaker. Names land on the right ids, the split half gets a fresh id, the short speaker gets a fresh id.
- `::test_named_speaker_never_dropped`.
- `::test_overlap_flag_on_phrases`.
- `::test_worker_output_is_parsed`: a saved worker JSON with 3 speakers and one overlap.
- `tests/test_core.py::test_marks_survive_retranscribe_and_redo`.
- `::test_history_shares`: a 10-word transcript where 1 word changes gives `changed == 0.1`.

## Done when

- [x] Common checks
- [x] Real run on the sandbox, recording 07-23:
  1. Name S1, S2 and S3 "Uno", "Due" and "Tre" through `/api/speakers`.
  2. Redo speakers with automatic count (GPU, about 2 minutes). The three names are on speakers again, and the Progress log shows which old id each new speaker matched and the shared seconds.
  3. Transcribe again with `large-v3-turbo`. The names are untouched, and no diarization ran (the job log shows no "separating speakers").
- [x] Recording 07-23 in the sandbox has 3 `embeddings`, and the number of `overlap` stretches and their total seconds are written in the Progress log
- [x] `.venv\Scripts\python data\speaker-eval\score_rec.py data\sandbox\vault\Plaud\Inbox\<07-23 folder>\recording.json data\speaker-eval\of_772c.plaud.txt` gives at least 94.4 % (today 95.4 %); the number is in the Progress log. If the scorer needs a small change for string ids, make it there. **Owner accepted the 95.4% redo result on 2026-11-17; turbo's 94.2% is recorded separately because the baseline used ensemble.**
- [x] Clear the three test names again in the sandbox

## Not in this ticket

Merge, moving passages, voice samples, the short-speaker badge and the dashboard controls (ticket 04). Recognising voices across recordings (ticket 08). Updating notes after a rename (ticket 05).

## Decisions

- 2026-11-17, owner acceptance: apply the score gate to the comparable redo result (95.4% with ensemble words). Accept turbo's 94.2% as the known model difference; no further accuracy tuning required for ticket 03.

- 2026-11-17: Follow the supplied AGENTS.md (no file exists), ponytail full, and the approved design. Use the existing worker, phrase assignment, schema and queue; no dependency or model changes. Keep the legacy retranscribe count argument compatible with queued jobs, but it will not trigger diarization.
- Checkpoints live here and in `documentation/CHECKPOINT.md`; finish with one ticket commit on `rebuild-official-cli`. Real checks use only sandbox 07-23, turbo and automatic speaker count, with zero AI calls.
- Keep old speaker records so ids are never reused and names/fix targets survive a disappearance. Match ties deterministically by new index and old id. Mark overlap per phrase and keep flagged/unflagged phrases in separate paragraphs; apply saved fixes at word midpoints before grouping.
- Transcript history counts SequenceMatcher replacement/insertion/deletion spans against the longer word list (bounded to 1); speaker history compares final assignments on the same word timestamps. Confirmed counts accept any non-negative integer (0 clears), independently of the existing redo-count control.

## Progress log

- 2026-11-17, checkpoint 1: Clean tree at `0dd2be8`; baseline 61 tests passed. Read ticket/design and traced worker -> speech -> pipeline -> vault/server plus all callers and affected tests. Protected vault newest UTC before work: `2026-11-17T06:06:15.8559430Z`. Scope: worker JSON, embedding/index alignment after tidy, overlap intervals, stable matching, stored-turn reassignment/history, count API, render, tests and README. Next: failing regression checks, implementation, full suite, sandbox acceptance and cleanup. No live jobs started; AI calls 0.
- Checkpoint 2: Nine new regression checks failed as expected before implementation; full suite now **70 passed, 0 skipped**. Worker saves label-ordered embeddings and both annotations; speech remaps embeddings after tidy, derives overlap, and preserves sherpa pooled vectors. Pipeline matches stable ids, reuses stored turns on retranscription, retains corrections and writes revision history. API accepts count-only updates without clearing names. Existing schema/import tests updated to the new dict result. `git diff --check` passes. No dependency installs, live runs or AI calls. Next: inspect final edge cases, update README, check both server states, start only sandbox 8378, name/redo/transcribe/score 07-23, clear test names, stop sandbox, verify protected timestamp and commit.
- Checkpoint 3 (18:58 local): **72 tests pass** after identical-timestamp sherpa and empty/overlap-boundary checks. README updated. Both ports were idle; sandbox server now running in tool session `5462` on 8378. Baseline saved to `data/sandbox/ticket03-before.json`. API name job 2 completed (S1 Uno, S2 Due, S3 Tre); automatic redo job 3 queued at `18:57:54`. Evidence: `data/sandbox/ticket03-evidence.jsonl`. Local ignored scorer now supports string ids. AI calls 0. Next: await job 3 (do not queue another), record shared-seconds matches/embeddings/overlap and proxy score, retranscribe with turbo and verify diarization unchanged, clear names, stop sandbox and finish checks/commit.

- Checkpoint 4 (resumed): Redo job 3 completed, names preserved; proxy 95.4%. Saved `ticket03-after-redo.json`. Job 4 (turbo retranscribe) failed twice while saving: NumPy timestamps produced a NumPy overlap boolean. Reproduced in the overlap render regression, fixed at `speech.utterances` with native bool; **72 tests pass** again. Stopped old sandbox session 5462; restarting sandbox with the fix and retrying the same job 4. No provider calls. Next: await retry, compare diarization/names/marks to after-redo snapshot, score, clear test names and stop sandbox before final documentation/commit.

- Redo evidence: new S1 matched old S1 with 786.68 shared seconds out of 843.06 new talk seconds; new S2 matched old S2 with 159.41/199.05 s; new S3 matched old S3 with 135.91/159.90 s. All Uno/Due/Tre names survived. Three embeddings of 256 floats each; **160 overlap stretches, 124.8 seconds total**, 50 flagged paragraphs. Final-transcript proxy immediately after redo: **95.4% of 1166 s** (baseline 95.4% of 1167 s).

- Checkpoint 5 (resumed session): Turbo retry of job 4 completed at 19:10:22 with no error. Saved diarization (including revision), names, speakers revision, marks and fixes are value-identical to the after-redo snapshot; transcript revision advanced once. Polled progress went from `transcribing with large-v3-turbo` to done, with no `separating speakers`. Full test suite after the NumPy bool fix: **72 passed, 0 skipped**, one existing Starlette/httpx deprecation warning. Diff check clean.
- **Acceptance gate at checkpoint 5 (resolved by owner in checkpoint 6):** proxy on the successful turbo output is **94.2% of 1175 s**, below the ticket's 94.4% gate. The 95.4% baseline and after-redo result use **ensemble** words. Offline reassignment without overlap flags still gives turbo 94.2% (1176 s) and ensemble 95.4% (1167 s), so overlap paragraph splitting does not explain the drop. No assignment tuning or baseline substitution made. Asked owner whether to accept the comparable redo result with the turbo limitation recorded, or keep the ticket open for turbo attribution investigation. Score Done box, common checks and board completion remain pending that answer.
- Cleanup job 5 cleared Uno/Due/Tre via `/api/speakers`; verified all names empty and diarization preserved. Sandbox server stopped; ports 8377 and 8378 idle. Owner vault newest UTC before **and after**: `2026-11-17T06:06:15.8559430Z`. AI provider calls: **0**. No dependency changes. Latest state and evidence: `data/sandbox/ticket03-evidence.jsonl`; baseline and after-redo snapshots remain there. Scorer's string-id compatibility fix is local in ignored `data/speaker-eval/score_rec.py`.
- **Resume instructions at checkpoint 5 (superseded by checkpoint 6):** implementation is in the working tree on `rebuild-official-cli`, base `0dd2be8`, no commit yet. No server or GPU job is running; all sandbox jobs finished. If owner accepts the redo score, check remaining boxes, set 03 Done and **04 and 06 Ready**, update CHECKPOINT and commit the explicit changed app/tests/docs/README files once. Otherwise investigate turbo attribution from cached sandbox words/turns without rerunning GPU jobs. Do not touch the protected vault or recreate test names unnecessarily.

- Additional offline comparison: turbo words assigned to the **original pre-ticket stored turns**, without overlap formatting, score **93.8% of 1176 s**. Current turns score 94.2% with those same turbo words. This supports a baseline-model mismatch rather than a measured attribution regression from this change; it does not waive the written 94.4% acceptance gate. Cached artifact: `data/sandbox/ticket03-turbo-old-turns.json`.

- Checkpoint 6 / completion, 2026-11-17: Owner explicitly accepted the score gate and requested completion. All Done checks satisfied with that acceptance; **03 Done**, **04 and 06 Ready**. README, board and CHECKPOINT updated. Production code is unchanged since the verified **72 passed, 0 skipped** run and successful sandbox retry; no extra GPU/provider runs needed. One ticket commit on `rebuild-official-cli` completes this work. Next ticket: **04**. Historical resume instructions above are superseded.
