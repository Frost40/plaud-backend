# 04: Fix speakers in the dashboard

**Needs:** 03 · **Size:** L

**Suggested model** (choose one; ★ = recommended):
- Low (a flash model: Haiku, Luna or Gemini Flash): not enough: merge and moved passages must survive a redo, which needs care.
- ★ Medium (Sol or Sonnet): recommended: the rules are fixed in the design and the stored turns from ticket 03 make each operation a CPU change.
- Hard (Opus or Astra): fine, not needed.

## You get

A speaker view for each recording in the dashboard, where you can:
- **hear** each voice (its three longest turns);
- **join** two speakers that are really one person;
- **give a passage to another speaker** or to a new one;
- **confirm the real number of speakers**.

Short "speakers" that are probably mistakes are flagged so you can check them with one click. Everything you do here survives "Redo speakers".

## Read first

`documentation/DESIGN.md`:
- 5.4 rules 3 to 7 (merge, move a passage, hear a voice, short speakers, wrong count);
- 5.2 the `speakers.merged_into` and `fixes` fields;
- 5.7 items 1 and 5 (what the speaker view holds; keep everything that exists);
- section 2, R9.

## Build (in this order)

1. **`app/pipeline.py`**:
   - `merge(rec_id, src, dst)` and `unmerge(rec_id, src)` (rule 3);
   - `add_fix(rec_id, s, e, spk_or_"new")` and `remove_fix(rec_id, index)` (rule 4);
   - `closest_voice(rec, spk)` by cosine of `diarization.embeddings` (rule 6). It returns `None` when a recording has no embeddings (migrated recordings).

   All of them re-run `speech.utterances` on the stored turns with `merged_into` and `fixes` applied, increment `speakers_rev`, append to `history` (`kind: "speakers"`, `changed` share), and call `vault.render`. Ticket 03's `match_speakers` already keeps fixes and named speakers; check that a redo re-applies `fixes` and `merged_into`.
2. **Same name means merge.** `/api/speakers`: when two ids get the same name, answer `{"ok": true, "merge_offer": ["S4", "S2"]}` and save the names. The dashboard then asks "Merge Speaker 4 into Speaker 2?".
3. **New routes in `app/server.py`**:
   - `POST /api/merge {id, src, dst}`, `POST /api/unmerge {id, src}`;
   - `POST /api/fix {id, s, e, spk}` (`spk` may be `"new"`), `POST /api/unfix {id, index}`;
   - `GET /api/recordings/{id}`: the recording without `words`, for the speaker view;
   - `GET /api/audio/{id}`: the recording's `.ogg`, served with HTTP Range. FastAPI's `FileResponse` handles Range in recent versions; check it, and write a small Range reply only if it does not.

   All of them validate the id, the speaker ids and that `0 <= s < e <= duration_s`. These are quick CPU operations: run them directly, not through the job queue, unless a GPU job is running on the same recording (then answer 409 "busy").
4. **`app/dashboard.html`**, a "Speakers" panel that opens per recording:
   - Each speaker: name field, talk time, ▶ sample (plays the three longest turns one after another with an `<audio>` element and `currentTime`), a "check" badge under 30 s or 2 % of speech with "merge into closest voice", and a "merge into…" menu.
   - A field "real number of speakers" that saves `true_speakers`.
   - The paragraph list: time, ▶, text, and a speaker menu (including "new speaker") that records a fix. A fixed paragraph shows a small undo.
   - Keep the current look (ticket 10 redesigns it).

## Tests

- `tests/test_speakers.py::test_merge_joins_paragraphs_and_hub_lists_name_once`.
- `::test_unmerge_restores`.
- `::test_fix_reassigns_only_its_span_and_survives_redo`: uses ticket 03's matching with a fake diarizer.
- `::test_fix_to_new_speaker_creates_id`.
- `::test_closest_voice_uses_embeddings` and `::test_closest_voice_none_without_embeddings`.
- `tests/test_server.py::test_audio_route_serves_range`: a Range request answers 206 with the right bytes.
- `::test_same_name_offers_merge`.
- `::test_fix_rejects_bad_span`.

## Done when

- [x] Common checks
- [x] Real run on the sandbox, "Steve Jobs & Bill Gates": find which speaker holds McNamee's question at 62:37–63:05 and Rob Kelly's at 71:14–71:32 (times from `data\speaker-eval\of_8a43.plaud.txt`). Move Rob Kelly's passage to a new speaker with a fix. Redo speakers (GPU, about 3 minutes). The fix is still applied and the new speaker still exists. The Progress log has the ids before and after.
- [x] In the browser pane on `http://127.0.0.1:8378`, open the speaker view, play one sample (the network log shows a 206 answer), merge the 8-second phantom speaker into its closest voice, and take one screenshot for the Progress log
- [x] Guard check: `POST /api/fix` with `e` beyond the recording's length answers 400
- [x] Undo the fix and the merge made here, clear `true_speakers`, and stop the sandbox server

## Not in this ticket

Updating notes after a merge (ticket 05). Suggestions of known voices (ticket 08). The new look (ticket 10).

## Decisions

- Keep raw diarization turns unchanged; resolve merge chains on assignment, including fix targets, so undo and redo remain reversible.
- Reuse installed Starlette FileResponse (local source confirms Range support); no dependencies.
- Apply speaker edits immediately with the same recording lock as worker dispatch; reject edits during a job on that recording.

## Implementation checkpoints

- [x] Pipeline: regression tests first, reversible merges/fixes, cosine suggestion, redo preservation.
- [x] API: immediate validated edits, busy guard, detail without words, ranged audio; update old queue expectations.
- [x] Dashboard: existing style, speaker panel, samples, merge/undo, fixes/undo, confirmed count.
- [x] Verify: full offline suite, sandbox Jobs & Gates fix/redo/undo and browser playback/screenshot, vault timestamp check.
- [x] Docs/board and one ticket commit on rebuild-official-cli after all Done checks.

## Progress log

- 2026-11-17 checkpoint A: clean tree on rebuild-official-cli. Read README, workflow, design and ticket; callers traced in pipeline/server/tests. No repository AGENTS.md; use user-supplied instructions. Protected vault newest file UTC: 2026-11-17T06:06:15.8559430Z. AI calls: 0. Existing sandbox config at data/sandbox/config.json. Next: write failing pipeline tests. Resume from this checklist and git diff; never recreate the sandbox blindly or touch port 8377 mutations.

- Checkpoint B: pipeline and API regression cycles verified (missing functions/routes failed first); 23 focused tests pass. Dashboard speaker dialog implemented, preserving existing controls/style. Immediate edits share per-recording worker locks and reject running jobs. No provider calls/GPU runs. Next: full suite, JS/browser availability, real sandbox acceptance.

- Checkpoint C: full suite 81 passed, 0 skipped (existing Starlette/httpx deprecation warning). JS syntax checked via node stdin. Ports 8377/8378 idle before run. Sandbox server running in exec session 75059 on 8378. Jobs & Gates id of_8a437ab8b8c5a3b75c07c8889272bc32: McNamee 3757?3785 and Rob Kelly 4274?4292 both S5. Applied fix 4274?4292 -> new S10; redo job 6 queued/running. Baseline data/sandbox/ticket04-before.json, evidence ticket04-evidence.jsonl. AI calls 0. Next: wait for job 6 without duplicating it, inspect persisted S10/fix, browser samples + phantom merge/screenshot, undo test changes, stop only sandbox. No connected browser pane; use installed Chrome headless/CDP if available.

- Checkpoint D: Chrome headless/CDP opened the live sandbox speaker dialog (10 rows), clicked a voice sample, observed playing audio at 2859s and two HTTP 206 responses; no JS exceptions. Evidence: data/sandbox/ticket04-browser-network.json and ticket04-speakers.png; runner ticket04-browser.py. Initial screenshot before redo has disabled closest-voice buttons because migrated Jobs & Gates has no embeddings. Fixed shell-encoding question marks in new UI text. Redo job 6 still running; do not restart server or duplicate the GPU job. Next: verify result + S10, merge phantom using new embeddings through browser, refresh screenshot, undo test changes.

- Checkpoint E / acceptance: redo job 6 finished successfully with pyannote in under 173s (polled at 173s). Stored 9 embeddings; fix 4274?4292 -> S10 survived, with S10 paragraphs at 4274.12?4275.96, 4276.14?4281.06 and 4281.58?4291.98. The last word crossing 4292 correctly remains S5 by midpoint. McNamee was S5 before; Rob Kelly was S5 before and S10 within the corrected span after. Snapshot: data/sandbox/ticket04-after-redo.json.
- Real-run variation: migrated S6's six phantom turns total 8.04s; the new model puts most of those intervals in new S11 (73.35s total, below 2% of speech), with a few fragments in S4/S3/S1. S6 has no inherited turns/embedding because the 50% overlap rule rejects the match. Therefore the browser check merged its flagged successor S11 into the cosine-closest S4, rather than fabricating an embedding for retired S6. All original speaker rows remain available; no automatic deletion. This is the same phantom region with the actual new model output, not a forced 8-second result.
- Browser acceptance used installed Chrome headless via CDP because no browser pane session was connected. Clicked sample: playback active and network HTTP 206 (after redo one response, before redo two), no JavaScript exceptions. Clicked S11's closest-voice button and verified S11.merged_into=S4. Screenshot: [speaker panel](../screenshots/ticket04-speakers.png). Then clicked Undo merge and Undo fix; confirmed true_speakers=9 and cleared it to null. Verified no fixes or merge remain; S10 remains as a reserved unused id. Evidence/runner: data/sandbox/ticket04-evidence.jsonl, ticket04-browser-network.json, ticket04-browser.py. POST /api/fix beyond duration returned 400.
- Final review added a failing regression for merge direction when the first stored speaker is renamed to an existing name; fixed the offer to merge the edited voice into the existing voice. README documents controls and API. No dependencies installed; AI calls 0. Sandbox server (session 75059) and test Chrome closed. Protected vault newest UTC before AND after: 2026-11-17T06:06:15.8559430Z (unchanged).
- Resume/completion checkpoint: implementation and sandbox acceptance complete; final full suite and diff check precede the one ticket commit on rebuild-official-cli. Board: 04 Done; 05 and 08 Ready. Next work is ticket 05. No further GPU runs, provider calls, or sandbox recreation needed. Earlier checkpoints are historical and superseded by this entry.
