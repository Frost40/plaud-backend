# 07: A glossary that grows by itself

**Needs:** 05, 06 · **Size:** L

**Suggested model** (choose one; ★ = recommended):
- Low (a flash model: Haiku, Luna or Gemini Flash): not enough: four sources, promotion rules and a token budget must fit together, and a wrong term can hurt every later transcript.
- Medium (Sol or Sonnet): possible; the design fixes every rule.
- ★ Hard (Opus or Astra): recommended: many parts must fit at once, and the measurement decides whether the automatic list may reach the speech model.

## You get

- Each topic folder's glossary fills itself with the names and terms of your meetings. The terms come from speaker names you give, from a short list at the end of each note you already generate (no extra AI call), from your own corrections to a transcript in Obsidian, and from the words the two-model "ensemble" chose.
- A term is used once it has appeared in two recordings of the folder; a term you delete never comes back.
- The list given to the speech model is ranked and trimmed to what it can really read, with your own terms first, and the dashboard tells you when terms did not fit.
- A measured answer to whether the automatic terms help the speech model, applied by itself.

## Read first

`documentation/DESIGN.md`:
- 5.12 "Automatic glossary" (the whole section: the 223-token limit, the four sources, the file layout with its two markers, promotion, budget, measurement, the setting `auto_glossary_whisper`);
- 5.5 (where the note prompt is built);
- 5.2 (`transcript.glossary`, `transcript.glossary_dropped`);
- section 2, R10.

## Build (in this order)

1. **`app/glossary.py`** (new, because the transcriber, the notes and the dashboard use it):
   - read and write a `Glossary.md` with the owner part, the automatic part and the rejected part, exactly as the example in 5.12. The owner part is never rewritten byte for byte; only the text below the first marker changes.
   - `add_candidates(folder, terms, rec_id, source)`.
   - `active(folder)`: owner terms, then the global owner terms, names, then automatic terms seen in 2 or more recordings, ordered as 5.12.
   - `notice_rejections(folder)`: an automatic line that disappeared since the last write goes to "Rejected".
   - `promote_global()`: a term active in 2 or more folders goes to `_Glossary.md`'s automatic part.
   - `hotwords(folder, rec_id, tokenizer)`: the budgeted string and the dropped terms. It excludes terms whose only evidence is `rec_id` itself.
2. **Sources:**
   - names: `pipeline.rename_speakers` adds each new name;
   - notes: append the `glossary` instruction of 5.12 to the prompt in `build_prompt`; `generate` parses the fenced `glossary` block, removes it from the note text, and adds the terms;
   - corrections: when `vault._write_owned` finds the owner edited a transcript, diff the edited words against the generated ones and add the replacement words that 5.12 accepts, before keeping the edit;
   - ensemble: in `ensemble.fuse`, compare each window's fused words with Whisper's words and return the candidates of 5.12; `pipeline._transcribe` adds them.
3. **`pipeline._transcribe`**: use `glossary.hotwords()` with the loaded Whisper model's tokenizer. Count with `model.hf_tokenizer.encode(…).ids` in faster-whisper 1.2.1; check the attribute name once and write it in Decisions. Pass the whole active list to the ensemble guard. Store `transcript.glossary` and `transcript.glossary_dropped`. When `auto_glossary_whisper` is `false`, only owner terms and names reach Whisper.
4. **Dashboard:** next to each folder, "Glossary: N terms (M automatic)", and on a recording "N glossary terms did not fit" when `glossary_dropped` is not empty. Keep the current look.

## Tests

- `tests/test_glossary.py::test_parse_and_strip_glossary_block`.
- `::test_promotion_needs_two_recordings`.
- `::test_names_and_corrections_active_at_once`.
- `::test_rejected_term_never_returns`.
- `::test_budget_keeps_owner_terms_first_and_reports_dropped`: the real tokenizer from the installed `tokenizers` package with Whisper's vocabulary, no GPU. If loading it needs the model files, use the ones faster-whisper already cached.
- `::test_edit_diff_finds_corrected_term`.
- `::test_terms_do_not_feed_their_own_recording`.
- `::test_owner_part_never_rewritten`.

## Done when

- [x] Common checks
- [x] Real run on the sandbox (at most 3 AI calls):
  1. Generate "Meeting minutes" with `claude` for 07-23 and for 09-29; their glossary blocks are parsed and removed. The Progress log lists the terms and which became active.
  2. Rename one speaker; the name appears in the folder's glossary at once.
- [x] Measurement as 5.12, with `eval/run.py` from ticket 06:
  1. Re-transcribe 07-23, 09-29 and 11-10 with `large-v3-turbo`, once with `auto_glossary_whisper: false` and once with `true`.
  2. Write the six scores and the term errors in `documentation/EVAL-BASELINE.md`.
  3. Apply the rule (keep `true`, or set the default to `false`) and write it in Decisions.
- [x] Guard check: delete one automatic line from the sandbox `Glossary.md`, run a note again (1 call), and see the term under "Rejected" and not re-added
- [x] Stop the sandbox server

## Not in this ticket

Recognising voices across recordings (ticket 08). The new look of the glossary display (ticket 10).

## Decisions

- Verified faster-whisper 1.2.1 uses `model.hf_tokenizer` and encodes a leading space before hotwords. Count the entire joined prefix with special tokens disabled, up to 213 tokens.

- Store recording IDs and the last published list beside each Markdown file. Deduplicate evidence case-insensitively, rank by distinct recordings and latest recording date, and retain owner spelling. A line moved intact above the marker keeps the term.
- Use the 100 most frequent words in existing transcripts of the detected language as the ensemble common-word filter.
- Append the glossary format to each note prompt so existing vaults receive it without modifying the owner's `_rules.md`. Haiku returned the block on the September retry with the instruction last.
- For the proxy decision, pool WER by reference-word count. Within each recording use the same on-arm term inventory in both arms. Count missed and spurious occurrences of complete normalized terms using the shared word alignment. Keep automatic Whisper hints only if pooled WER rises by at most 0.5 percentage points and total term errors fall.

- Kept `auto_glossary_whisper: true`. Across the three Italian recordings pooled WER fell from 21.810% to 19.806% and term errors from 12 to 9. See the paired scores in [EVAL-BASELINE](../EVAL-BASELINE.md#ticket-07-glossary-comparison).

## Progress log

- 2026-11-17, checkpoint 1. Clean branch `rebuild-official-cli` (already one commit ahead). Read the supplied AGENTS.md instructions, workflow and design. Protected vault newest file UTC `2026-11-17T06:06:15.8559430Z`. Existing sandbox contains the three Italian recordings and cached Whisper vocabulary. Calls used 0/3. Next implement evidence, four sources, dashboard and offline checks before sandbox measurement.

- 2026-11-18, checkpoint 2. Implemented the shared glossary, four sources, Whisper budget and dashboard. All 110 previous tests and eight new glossary tests passed separately. Sandbox July S1 renamed to Voce A, immediately active. Claude call 1 was denied before execution because explicit approval is required to send the private sandbox transcripts. Asked the owner; no calls spent. Do not run the provider scripts until approved. Local baseline runs started with both dashboard ports closed. Resume using `data/sandbox/ticket07_measure.py off` (skips completed scores in `ticket07-results`); it uses isolated JSON outputs so the original ensemble inputs for the notes stay available. After approval use `data/sandbox/ticket07_note.py first` and `second`; its JSONL ledger reserves a call before invoking Claude. Run measurement `on` before deleting any term, then do the rejection check with `guard`. All scripts use the project venv.

- 2026-11-18, checkpoint 3. All **118 tests passed**, no skips. Dashboard JS parsed; sandbox server on 8378 returned Inbox **1 term (1 automatic)** and the dropped-term count on every recording. Stopped that server and verified no listener. All three off-arm runs finished and were scored by `eval/run.py`: July **19.57%**, September **16.29%**, November **26.05%**. Isolated transcripts and scores in `data/sandbox/ticket07-results`. Owner vault newest UTC after checks **2026-11-17T06:06:15.8559430Z**, identical to start. No Claude calls made.
- Remaining work requires explicit permission to send the 07-23 and 09-29 transcripts to Claude. After approval run the two note phases in checkpoint 2 and record the terms from `data/sandbox/ticket07-calls.jsonl`. Run `.venv\Scripts\python data/sandbox/ticket07_measure.py on`, then `.venv\Scripts\python data/sandbox/ticket07_terms.py`. Write the six WERs and term errors in EVAL-BASELINE, apply the decision to the default, delete a learned line in the sandbox, run the guard note, verify rejection, and record the results. Recheck tests and vault time, update board and commit. Keep the existing sandbox for resume. No ticket commit until all Done checks pass.

- 2026-11-18, checkpoint 4. Owner authorized Claude Haiku for July and September, maximum three calls. All three ran with `--model haiku`. July returned 15 candidates: MRAF, Speckle, Loss, SLM, GS, Transformer, Trasformata di Fourier, Fase, Ampiezza, Batch, Overfitting, Scatterer, Signal region, ASCII, NIST. Only the speaker name was active after that note.
- September's first response omitted the block. Moved the format instruction to the end of the prompt and showed the closing fence. In the September sandbox transcript, corrected one “Gerber Saxton” to “Gerchberg Saxton” and “Speckler” to “Speckle”. Both replacement words became active. Deleted only the Speckle automatic line. Used the third call for the scheduled guard check by regenerating the same September note.
- September then returned 15 candidates: SLM, Gerchberg-Saxton, Gerchberg, Random superposition, Pistone medio, Wrapping, Speckle, Unsupervised, Supervised, Teacher, Trasformata di Fourier, Gradiente della fase, Padding, Overfitting, Transformer. Both saved notes had their blocks stripped. Overfitting, SLM, Transformer and Trasformata di Fourier were active from two recordings. Voce A and Gerchberg were human-supplied. Speckle appeared in Haiku's answer and remained exclusively under Rejected. See the three reservations and responses in `data/sandbox/ticket07-calls.jsonl`. **3/3 calls spent; no further provider calls.**
- Measuring the three on-arm runs from the preserved sandbox audio with `data/sandbox/ticket07_measure.py on`; each writes its own transcript and score in `ticket07-results`. If interrupted, check for an existing GPU job before resuming the same command, then run `ticket07_terms.py`. Only scoring, the measured default, final checks, board update and commit remain.

- 2026-11-18, final checkpoint. All six runs scored. November WER went from 26.05% to 22.92% and term errors from 6 to 3. All eligible terms fit, and the measured default stays enabled. Final sandbox check confirmed both saved notes have no glossary fence, all three calls used Haiku, and Speckle is rejected. All 118 tests passed with zero skips; dashboard JavaScript and Git whitespace checks passed. Port 8378 closed. Protected vault newest UTC before and after: `2026-11-17T06:06:15.8559430Z`. Ticket 07 is Done; next Ready is 08.
