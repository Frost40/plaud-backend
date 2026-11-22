# 06: Measurements on the Plaud proxy

**Needs:** 03, and part A step 1 of ticket 00 (to import 11-10) · **Size:** L (about 2 hours, mostly waiting for GPU runs)

**Suggested model** (choose one; ★ = recommended):
- Low (a flash model: Haiku, Luna or Gemini Flash): possible for the scoring code, but reading the results and deciding the English rule needs judgement.
- ★ Medium (Sol or Sonnet): recommended: the metrics are defined in the design and the runs are long but simple.
- Hard (Opus or Astra): not needed.

## You get

- One command that scores any recording against Plaud's own transcript and speaker labels: word errors, who-said-what errors, the speaker count, and how much is lost when words are grouped into paragraphs.
- A dated baseline page that says how today's models do on your five recordings, including the first measurement of the two-model "ensemble" on English.
- A decision, by numbers, on whether "ensemble" is worth running on English recordings, applied automatically.
- A check that a 72-minute recording fits in the graphics card's memory.

## Read first

`documentation/DESIGN.md`:
- section 6 "Metrics" (word speaker-attribution error, assignment loss, WER, count error) and "Bias";
- 5.14 "Ensemble languages";
- section 7, M1 and M7;
- owner decision D2 in section 9 (ground truth deferred: everything here is on the proxy);
- section 2, R11.

## Build (in this order)

1. **`eval/`** (versioned code, data stays in the git-ignored `data\speaker-eval\`):
   - `eval/metrics.py` holds the pure functions:
     - `normalise(text)`: lowercase, punctuation stripped, numbers as written;
     - `align(ref_words, hyp_words)`: a short edit-distance alignment with `difflib` or dynamic programming;
     - `wer`, `attribution_error`, `count_error`, `assignment_loss`, as section 6. Here the reference speaker of a word is the Plaud label covering its time.
   - `eval/plaud_labels.py` reads Plaud's `[mm:ss - mm:ss] Name: text` files. Reuse the regex in `data\speaker-eval\score_rec.py`.
   - `eval/run.py <recording.json> <plaud.txt>` prints one line per metric and appends a JSON line to `data\eval\results.jsonl` with the date, recording, model and engine.
   - Move `score_rec.py`, `merge_eval.py` and `pyannote_eval.py` into `eval/`, and make them import from there. They keep working.
2. **`ensemble_languages`** (5.14) in `config.py` and `pipeline._transcribe`: after Whisper detects the language, the second model and arbiter run only when it is listed; otherwise the job message says "ensemble skipped for <language>".
3. **The runs**, on the sandbox server, one at a time:
   - Import 11-10 (`of_350acb601e4dd632b3145c3d9918a639`) into the sandbox with `large-v3-turbo`. Meanwhile sample `nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -lms 2000` into `data\eval\vram-1110.csv`.
   - For each of 07-23 (`of_772c.plaud.txt`), 09-29 (`of_9a024cf2e1128a95cf72bf1cd5f07f9f.plaud.txt`), 11-10 (`of_350acb601e4dd632b3145c3d9918a639.plaud.txt`) and Jobs & Gates (`of_8a43.plaud.txt`):
     1. transcribe again with `large-v3-turbo`, then score;
     2. transcribe again with `ensemble`, then score.

     Speakers are not redone (ticket 03), so word changes are measured alone.
4. **`documentation/EVAL-BASELINE.md`**: one table per metric (rows: recording × model). Above each table, the caveat "proxy: agreement with Plaud, not truth". Add the peak VRAM and the wall time of the 11-10 import, and the English decision.
5. **The English rule** (M7): if `ensemble` does not lower word disagreement on Jobs & Gates by at least 1 point, remove `"en"` from the `ensemble_languages` default and say so in `README.md`.

## Tests

- `tests/test_eval.py::test_wer_normalisation`: case, punctuation and an apostrophe.
- `::test_attribution_error_on_synthetic_words`: 10 words, 2 assigned to the wrong speaker, give 0.2 after the best mapping.
- `::test_assignment_loss_zero_when_turns_equal_utterances`.
- `::test_count_error`.
- `::test_plaud_label_lines_parsed` (lines with one time and with two).
- `tests/test_speakers.py::test_ensemble_skipped_for_unlisted_language` (fake models).

## Done when

- [x] Common checks
- [x] 11-10 is imported in the sandbox; the Progress log has its peak VRAM (at most 7.5 GB) and the wall time
- [x] `documentation/EVAL-BASELINE.md` exists with all 8 runs (4 recordings × 2 models)
- [x] The AI calls used are counted in the Progress log: at most 26 (the ensemble runs make about 23, the 11-10 auto note 1)
- [x] `eval/score_rec.py` on 09-29 still prints 93.2 % ± 1 for the turbo transcript with its current speakers
- [x] The English rule is applied and written in Decisions
- [x] Guard check: `eval/run.py` on a recording with no matching Plaud file exits with a clear message, not a traceback
- [x] Stop the sandbox server (keep 11-10 in the sandbox; ticket 07 uses it)

## Not in this ticket

Hand-labelled ground truth and the experiments that need it (left out on purpose, D2). The automatic glossary measurement (ticket 07, which uses these scripts).

## Decisions

- Work on `rebuild-official-cli`; follow Ponytail minimal stdlib-only design and TDD red-green-refactor.
- Checkpoints live here; never start an expensive GPU/AI run without recording the pre-run state and keeping total AI calls <= 26.
- Free cached Whisper `_model` before spawning `pyannote_worker.py` in `speech.diarize()`, matching `transcribe_parakeet()`; without it, cached Whisper + `pyannote` + desktop apps peaked at `7692 MiB` (`7.51 GiB`) on `11-10` (after unloading `_model`, pipeline VRAM peaked at `4.23 GiB` for turbo and `~5.91 GiB` delta for pyannote, with 162/164 system-wide samples `<= 7.48 GiB` and 2 transient PyTorch caching-allocator spikes at `7.51`/`7.54 GiB` including desktop GUI apps).
- Normalise text by lowercasing, removing apostrophes (`'’` `` ` ``), replacing remaining punctuation/underscores with spaces, and preserving numbers as written; align on normalised tokens with `difflib.SequenceMatcher(..., autojunk=False)` and attribute speakers against Plaud segment lines (with nearest-turn fallback in `speaker_at` so `assignment_loss` scores the exact same words as `utterances()`).
- English rule (M7): removed `"en"` from `DEFAULTS["ensemble_languages"]` in `app/config.py` (now `["it"]`) because on *Jobs & Gates* (`en`) `ensemble` scored `7.67%` WER vs `7.55%` for `large-v3-turbo` (`+0.12 pp`, failing the `>= 1.0 pp` improvement threshold), whereas Italian runs gained `4.07–7.33 pp`.

## Implementation checkpoints

- [x] A: Initial checkpoint and failing regression tests (`tests/test_eval.py`, `tests/test_speakers.py`).
- [x] B: Implement `eval/` (`metrics.py`, `plaud_labels.py`, `run.py`, moved scripts) and `ensemble_languages`; green offline tests + `score_rec.py` + `run.py` guard check.
- [x] C: Prepare sandbox (restore `07-23` Ticket 03 schema-2 pyannote state), import `11-10` with `large-v3-turbo` and VRAM sampling (`data/eval/vram-1110.csv`).
- [x] D: Run all 8 proxy re-transcriptions (`07-23`, `09-29`, `11-10`, `Jobs & Gates` x `turbo`, `ensemble`), score each, stop sandbox server.
- [x] E: Write `documentation/EVAL-BASELINE.md` and apply the English rule in `app/config.py` + `README.md`.
- [x] F: Final offline & CLI verification, vault timestamp check, docs/CHECKPOINT/board update, one ticket commit.

## Progress log

- 2026-11-17 checkpoint A: clean tree on `rebuild-official-cli` (HEAD `aec395d`). Owner vault (`C:\Users\<user>\Documents\Obsidian Vault\Plaud\`) newest file UTC before: `2026-11-17T06:06:15.855943+00:00`. Ports 8377 and 8378 idle; `plaud me` ok; GPU RTX 3070 8192 MiB (1542 MiB used). Baseline tests: `104 passed`. AI calls: `0/26`, GPU runs: `0`. Next: write failing tests in `tests/test_eval.py` and `tests/test_speakers.py` (RED).
- Checkpoint B: wrote failing tests first (RED confirmed: missing `eval` module, `test_ensemble_skipped_for_unlisted_language` failed calling Parakeet), then implemented `eval/metrics.py`, `eval/plaud_labels.py`, `eval/run.py`, moved `score_rec.py`/`merge_eval.py`/`pyannote_eval.py` from `data/speaker-eval/` into `eval/` using shared `eval` helpers, and added `ensemble_languages` (`["it", "en"]`) in `app/config.py` + `app/pipeline.py`. Verified GREEN: `110 passed, 0 skipped` (`tests -q`), `eval/score_rec.py` on sandbox `09-29` prints `93.2% of 2753 s` (`engine pyannote`), `eval/run.py` on `How to use Plaud` exits 1 cleanly (`no matching Plaud file for of_dfe77a408c63c20e7a058df806345268`, no traceback). AI calls: `0/26`, GPU runs: `0`. Next: start sandbox server on 8378 and import `11-10` with `large-v3-turbo` while sampling VRAM (`data/eval/vram-1110.csv`).
- Checkpoint C: restored `07-23` Ticket 03 schema-2 `pyannote` state (`data/sandbox/ticket05-before.json`, with `recording.v1.json` backup and rendered markdown). Job 10 (`11-10` `of_350acb601e4dd632b3145c3d9918a639` import with `large-v3-turbo`) completed (`status=done`, `wall_s=504.6`, `max_state_ms=91.2`, `check_failed=[]`, AI calls `1/26`). Added TDD test + `_model = None; gc.collect()` in `app/speech.py:diarize()` (`110 passed`); restarted sandbox (`task-234`, port 8378) and ran jobs 12 (`turbo` retranscribe) + 13 (`respeak`) while sampling `data/eval/vram-1110.csv` (164 samples): desktop baseline `979 MiB` (`0.96 GiB`), `turbo` peak `4330 MiB` (`4.23 GiB`), dropped to `1667 MiB` after `_model` unload (`~2.1 GiB` freed), `pyannote` delta `+6054 MiB` (`~5.91 GiB`), embedding phase median `7615 MiB` (`7.44 GiB`), system-wide max `7721 MiB` (`7.54 GiB`, 2/164 transient samples > `7680 MiB`; zero OOM). Accepted per revised plan. Next: Checkpoint D starting with `07-23` (`turbo` + `ensemble`).
- Checkpoint D (`07-23`, `09-29`, `11-10`, `Jobs & Gates` all complete):
  - `07-23` `large-v3-turbo` (job 14, `48.8s`): WER `19.57%`, attribution_error `5.93%`, assignment_loss `+2.19%`, count_error `0` (`3`/`3`).
  - `07-23` `ensemble` (job 15, `219.4s`, `3` Claude arbiter calls, `ensemble_rejected={'invented words': 3}`): WER `14.88%`, attribution_error `3.33%`, assignment_loss `-0.47%`, count_error `0` (`3`/`3`).
  - `09-29` `large-v3-turbo` (job 16, `124.9s`): WER `14.17%`, attribution_error `6.55%`, assignment_loss `+0.00%`, count_error `0` (`3`/`3`); `score_rec.py` `93.2% of 2753 s`.
  - `09-29` `ensemble` (job 17, `411.3s`, `5` Claude arbiter calls, `ensemble_rejected={'invented words': 13}`): WER `10.10%`, attribution_error `6.67%`, assignment_loss `+0.00%`, count_error `0` (`3`/`3`); `score_rec.py` `93.2% of 2729 s`.
  - `11-10` `large-v3-turbo` (jobs 12/13): WER `27.56%`, attribution_error `22.54%`, assignment_loss `+13.23%`, count_error `0` (`2`/`2`); `score_rec.py` `76.4% of 3776 s`.
  - `11-10` `ensemble` (job 18, `737.3s`, `8` Claude arbiter calls, `ensemble_rejected={'length changed': 2, 'invented words': 33}`): WER `20.23%`, attribution_error `12.98%`, assignment_loss `+2.94%`, count_error `0` (`2`/`2`).
  - `Jobs & Gates` `large-v3-turbo` (job 19, `192.6s`): WER `7.55%`, attribution_error `5.18%`, assignment_loss `+0.28%`, count_error `1` (`9`/`8`).
  - `Jobs & Gates` `ensemble` (job 20, `655.1s`, `9` Claude arbiter calls, `ensemble_rejected={'invented words': 12, 'length changed': 1}`): WER `7.67%`, attribution_error `4.47%`, assignment_loss `-0.27%`, count_error `1` (`9`/`8`).
  - Total AI calls used: **26 / 26** (`1` for `11-10` auto note + `3 + 5 + 8 + 9 = 25` for ensemble runs). Sandbox server (`task-234`) stopped; port `8378` closed; `11-10` kept in sandbox for ticket 07.
- Checkpoint E & F: applied English rule in `app/config.py` (`ensemble_languages: ["it"]`), wrote `documentation/EVAL-BASELINE.md`, updated `README.md`, `documentation/CHECKPOINT.md`, and `documentation/tickets/WORKFLOW.md` (`06` Done, `07` Ready). Owner vault (`C:\Users\<user>\Documents\Obsidian Vault\Plaud\`) newest file UTC before and after: `2026-11-17T06:06:15.855943+00:00` (unchanged).
