# 08: Known voices suggested across recordings

**Needs:** 04 · **Size:** M

**Suggested model** (choose one; ★ = recommended):
- Low (a flash model: Haiku, Luna or Gemini Flash): possible for the storage, not for picking the threshold and judging the real run.
- ★ Medium (Sol or Sonnet): recommended: the matching is cosine arithmetic on stored vectors, and the rules are fixed in the design.
- Hard (Opus or Astra): not needed.

## You get

When a recording has someone you have already named in other recordings, the dashboard suggests the name ("sounds like Paolo, 0.81 — accept?"). One click accepts it, and every accepted name makes the next suggestion better. Nothing is named without your click. Suggestions start once at least three people are each named in at least two recordings; until then the dashboard says how many more are needed.

## Read first

`documentation/DESIGN.md`:
- 5.4 rule 8 "Recognise people across recordings" (enrolment, suggestions, the leave-one-recording-out threshold, engines never mixed, the five tests);
- 5.2 (`_Voices.json` in the vault layout);
- section 4.4;
- owner decision D3 in section 9.

## Build (in this order)

1. **`app/voices.py`** (new):
   - `enrol(name, vector, engine, rec_id)`: writes `<vault>\Plaud\_Voices.json` atomically, at most 20 vectors per person and engine, newest kept.
   - `forget(name, rec_id)`: when a name is removed or changed.
   - `threshold(engine)`: leave-one-recording-out over all enrolled vectors, the lowest value whose false-match rate is at or below 5 %, or `None` when fewer than 3 people have vectors from 2 or more recordings.
   - `suggest(rec)`: for each unnamed speaker with an embedding, the best person above the threshold, never the same person for two speakers of one recording (the higher score wins).
2. **Hooks:**
   - `pipeline.rename_speakers` enrols (or forgets) the speaker's vector from `rec["diarization"]["embeddings"]`, with the engine name.
   - After every diarization, `rec["suggestions"] = voices.suggest(rec)`.
   - Merging speakers (ticket 04) refreshes the suggestions.
3. **API and dashboard:**
   - `POST /api/suggestion {id, spk, accept: true|false}`. Accepting sets the name through `rename_speakers` (so notes are relabelled, ticket 05, and the glossary gets the name, ticket 07, when those exist). Refusing stores the refusal so it is not suggested again for that speaker.
   - In the speaker view (ticket 04), each suggestion shows beside the name field, with **Accept** and **No**. The status line says "voice suggestions: on", or "need N more named people".
4. **`eval/voices_check.py`**: a measurement on real audio that does not touch the vault. It loads the sandbox "Steve Jobs & Bill Gates" audio, runs `speech.diarize` on minutes 0–40 and on minutes 40–81 separately, and maps each half's speakers to Plaud's labels in `data\speaker-eval\of_8a43.plaud.txt` by shared seconds. Then it enrols the first half's four on-stage voices under their Plaud names, matches the second half, and prints for each speaker the true name, the suggestion and the score.

## Tests

`tests/test_voices.py`, all with synthetic vectors:
- `::test_enrol_on_naming`;
- `::test_suggestion_needs_threshold`;
- `::test_no_two_speakers_get_the_same_suggestion`;
- `::test_threshold_from_leave_one_out`;
- `::test_engines_never_mixed`;
- `::test_refused_suggestion_not_repeated`;
- `::test_at_most_20_vectors`.

## Done when

- [x] Common checks
- [x] `.venv\Scripts\python eval\voices_check.py` runs (2 GPU runs of about 2 minutes). The Progress log has its table, and at least 3 of the 4 on-stage voices are suggested correctly with no wrong suggestion above the threshold. If not, write the scores in Decisions and keep suggestions off by raising the threshold until no wrong suggestion remains.
- [x] In the sandbox dashboard, the status line says how many more named people are needed (the sandbox has no names yet)
- [x] Guard check: a `_Voices.json` with a pyannote vector and a sherpa vector of the same person never compares them (the test proves it; also try once by hand in a Python shell on a temporary vault)
- [x] Remove any `_Voices.json` created in the sandbox, and stop the sandbox server
- [x] One line added to `OWNER_CHECKS.md`: "After naming people in a few recordings, check that the 'sounds like …' suggestions are right."

## Not in this ticket

Naming speakers automatically without a click (rejected by the owner: suggestions only). The new look of the suggestions (ticket 10).

## Decisions

- Key voice samples by person and engine and keep each vector with its recording and speaker IDs so a rename can remove the affected sample without dropping another speaker's confirmation.
- Use a strict cosine cutoff and leave the entire query recording out of every calibration comparison. At the false-match boundary, reject ties.
- Use first-half cross-person similarities for the benchmark cutoff. The two halves come from one recording, so the benchmark cannot calibrate the dashboard's two-recording gate. The first-half templates stay in memory.
- Store refusals against stable speaker IDs and check the displayed name again before accepting a suggestion.

## Progress log

- Checkpoint A (2026-11-18). Branch `rebuild-official-cli` started clean at `5bc94f5`. Workflow and ticket are under `documentation/`. Follow the supplied AGENTS.md instructions in the conversation. Owner vault newest UTC before work: `2026-11-17T06:06:15.8559430Z`. No AI calls. Plan: synthetic tests and guarded voice store, pipeline/API/dashboard, two-half GPU evaluation and sandbox checks, then update board and commit. Resume from the latest entry here.

- Checkpoint B (2026-11-18). Voice store, pipeline, API and dashboard implemented. 125 offline tests passed. GPU benchmark launched from the project root with sandbox config and HF offline after neither dashboard port had a listener. PID in `data/sandbox/ticket08-eval.pid`, output in `data/sandbox/ticket08-eval.log` and `.err`. First attempt failed before diarization due to the full recording title, fixed by using its stable ID. Resume by checking the logs and then verifying the sandbox UI, reviewing and committing. No AI calls.

- Checkpoint C (2026-11-18). The benchmark completed both pyannote runs. First-half cutoff 0.669136. Four correct suggestions and zero wrong.

| Speaker | Plaud name | Best match | Cosine | Suggested |
|---|---|---|---:|---|
| 8 | Charlie Brenner | Bill Gates | 0.442804 | |
| 7 | Charlie Brenner | Bill Gates | 0.503856 | |
| 5 | Roger McNamee | Walt Mossberg | 0.636104 | |
| 4 | Roger McNamee | Walt Mossberg | 0.609774 | |
| 2 | Walt Mossberg | Walt Mossberg | 0.976202 | Walt Mossberg |
| 1 | Steve Jobs | Steve Jobs | 0.990192 | Steve Jobs |
| 0 | Bill Gates | Bill Gates | 0.990142 | Bill Gates |
| 3 | Kara Swisher | Kara Swisher | 0.968894 | Kara Swisher |
| 6 | Kara Swisher | Kara Swisher | 0.430401 | |

- Headless Chrome opened the sandbox speaker panel and showed “need 3 more named people” with no offer buttons or browser exceptions. Manual mixed-engine check passed in a temporary vault. No sandbox `_Voices.json` was created. The sandbox server and test browser were stopped. Owner vault newest UTC before and after: `2026-11-17T06:06:15.8559430Z`. No AI calls.

- Final verification: 126 offline tests passed with no skips. Dashboard JavaScript syntax and Git diff checks passed. Next Ready: 09. Ticket 10 still needs 09.
