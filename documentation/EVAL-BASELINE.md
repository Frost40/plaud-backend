# Proxy Evaluation Baseline — 2026-11-17

Measured against Plaud's own transcript and speaker labels (sandbox vault, `pyannote` `speaker-diarization-community-1`, `claude` arbiter). Hand-labelled ground truth is deferred (owner decision D2), so every accuracy figure below is **proxy: agreement with Plaud, not truth**.

## Word disagreement (WER)

> proxy: agreement with Plaud, not truth

| Recording | Language | Duration | Model | WER vs Plaud | Change vs turbo |
|---|---|---|---|---|---|
| 07-23 (`of_772c`) | `it` | 21m 47s | `large-v3-turbo` | 19.57% | — |
| 07-23 (`of_772c`) | `it` | 21m 47s | `ensemble` | 14.88% | -4.69 pp |
| 09-29 (`of_9a02`) | `it` | 49m 56s | `large-v3-turbo` | 14.17% | — |
| 09-29 (`of_9a02`) | `it` | 49m 56s | `ensemble` | 10.10% | -4.07 pp |
| 11-10 (`of_350a`) | `it` | 1h 12m | `large-v3-turbo` | 27.56% | — |
| 11-10 (`of_350a`) | `it` | 1h 12m | `ensemble` | 20.23% | -7.33 pp |
| Jobs & Gates (`of_8a43`) | `en` | 1h 21m | `large-v3-turbo` | 7.55% | — |
| Jobs & Gates (`of_8a43`) | `en` | 1h 21m | `ensemble` | 7.67% | +0.12 pp |

Note on the 5th vault recording: *How to use Plaud* (`of_dfe7`, `en`, 3m 46s, `large-v3-turbo`, 1 speaker `Narrator`) has no Plaud transcript file in `data/speaker-eval/`, so `eval/run.py` exits with `no matching Plaud file for of_dfe77a408c63c20e7a058df806345268`.

## Word speaker-attribution error

> proxy: agreement with Plaud, not truth

| Recording | Engine | Model | Attribution error | Notes |
|---|---|---|---|---|
| 07-23 (`of_772c`) | `pyannote` | `large-v3-turbo` | 5.93% | 361 raw turns (ticket 03) |
| 07-23 (`of_772c`) | `pyannote` | `ensemble` | 3.33% | same turns; words changed |
| 09-29 (`of_9a02`) | `pyannote` (migrated turns) | `large-v3-turbo` | 6.55% | `eval/score_rec.py`: 93.2% of 2753 s |
| 09-29 (`of_9a02`) | `pyannote` (migrated turns) | `ensemble` | 6.67% | `eval/score_rec.py`: 93.2% of 2729 s |
| 11-10 (`of_350a`) | `pyannote` | `large-v3-turbo` | 22.54% | `eval/score_rec.py`: 76.4% of 3776 s |
| 11-10 (`of_350a`) | `pyannote` | `ensemble` | 12.98% | same turns; words changed |
| Jobs & Gates (`of_8a43`) | `pyannote` | `large-v3-turbo` | 5.18% | 9 found speakers |
| Jobs & Gates (`of_8a43`) | `pyannote` | `ensemble` | 4.47% | same turns; words changed |

## Assignment loss (`utterances()` minus raw exclusive turns)

> proxy: agreement with Plaud, not truth

| Recording | Engine | Model | Assignment loss | Raw turn vs final utterance |
|---|---|---|---|---|
| 07-23 (`of_772c`) | `pyannote` | `large-v3-turbo` | +2.19% | 3.74% -> 5.93% |
| 07-23 (`of_772c`) | `pyannote` | `ensemble` | -0.47% | 3.80% -> 3.33% |
| 09-29 (`of_9a02`) | `pyannote` (migrated) | `large-v3-turbo` | +0.00% | synthetic turns match utterances |
| 09-29 (`of_9a02`) | `pyannote` (migrated) | `ensemble` | +0.00% | synthetic turns match utterances |
| 11-10 (`of_350a`) | `pyannote` | `large-v3-turbo` | +13.23% | 9.31% -> 22.54% |
| 11-10 (`of_350a`) | `pyannote` | `ensemble` | +2.94% | 10.04% -> 12.98% |
| Jobs & Gates (`of_8a43`) | `pyannote` | `large-v3-turbo` | +0.28% | 4.90% -> 5.18% |
| Jobs & Gates (`of_8a43`) | `pyannote` | `ensemble` | -0.27% | 4.74% -> 4.47% |

## Speaker count error

> proxy: agreement with Plaud, not truth

| Recording | Model | Found speakers | Plaud labels | Count error | Note |
|---|---|---|---|---|---|
| 07-23 (`of_772c`) | `large-v3-turbo` | 3 | 3 | 0 | — |
| 07-23 (`of_772c`) | `ensemble` | 3 | 3 | 0 | — |
| 09-29 (`of_9a02`) | `large-v3-turbo` | 3 | 3 | 0 | owner count: 3 |
| 09-29 (`of_9a02`) | `ensemble` | 3 | 3 | 0 | owner count: 3 |
| 11-10 (`of_350a`) | `large-v3-turbo` | 2 | 2 | 0 | owner count: 2 |
| 11-10 (`of_350a`) | `ensemble` | 2 | 2 | 0 | owner count: 2 |
| Jobs & Gates (`of_8a43`) | `large-v3-turbo` | 9 | 8 | 1 | real speakers ~10 (4 stage + ~6 audience) |
| Jobs & Gates (`of_8a43`) | `ensemble` | 9 | 8 | 1 | real speakers ~10 |

## 72-minute import check (`11-10`, R11)

Ticket 11 repeated the import with turbo in `int8_float16`, pyannote batches of eight and automatic notes disabled. It finished in 290.21 s with two speakers. The longest dashboard request took 115.67 ms, sampled system VRAM peaked at 2729 MiB, and at least 12,198 MiB of system RAM stayed available. The earlier ticket 06 figures below include a Claude note in the wall time and a separate GPU sampling run. [Ticket 11 results](tickets/11-final-check.md#final-verification-on-november-19)

- **Wall time (full end-to-end import, Job 10, `large-v3-turbo`):** **504.6 s (8m 25s)**, well under the 15-minute ceiling (`download` 16 s, `transcribe` 160 s, `speakers` 281 s, `notes` `claude` 43 s).
- **`/api/state` max latency during import:** **91.2 ms** (ceiling: 0.5 s).
- **Peak VRAM (164 samples at 2 s, raw CSV removed during ticket 11 cleanup):**
  - Initial `respeak` while `app/speech.py:diarize()` kept Whisper `_model` cached peaked at `7692 MiB` (`7.51 GiB`).
  - Added `_model = None; gc.collect()` before spawning `pyannote_worker.py` in `app/speech.py:diarize()`, freeing `~2.1 GiB` (`3779 -> 1667 MiB`).
  - Re-sampled across `11-10` `large-v3-turbo` (`retranscribe`) + `pyannote` (`respeak`): desktop GUI baseline `979 MiB` (`0.96 GiB`), `large-v3-turbo` peak `4330 MiB` (`4.23 GiB`), idle server/desktop transition `1667 MiB`, `pyannote` embedding phase median `7615 MiB` (`7.44 GiB`, pipeline delta `~5.91 GiB`), system-wide peak `7721 MiB` (`7.54 GiB`, 2 transient PyTorch caching-allocator samples > `7680 MiB`; 162/164 samples <= `7662 MiB`, zero OOM errors).

## English ensemble decision (M7)

- **Kill rule:** keep `"en"` in `ensemble_languages` only if `ensemble` lowers word disagreement on *Jobs & Gates* by at least 1.0 percentage point.
- **Measured result:** on *Jobs & Gates* (`en`), `ensemble` had **7.67%** WER vs **7.55%** for `large-v3-turbo` (**+0.12 pp**, no gain; `13` of `163` arbiter segments rejected by the guard). By contrast, on all three Italian recordings (`07-23`, `09-29`, `11-10`), `ensemble` cut WER by **4.07 to 7.33 percentage points**.
- **Action applied:** removed `"en"` from `DEFAULTS["ensemble_languages"]` in `app/config.py` (now `["it"]`). When `ensemble` is selected on an English (or other unlisted-language) recording, Whisper runs once and logs `ensemble skipped for <language>`.

## Ticket 07 glossary comparison

Sandbox `large-v3-turbo` WER against Plaud's Italian transcript (proxy). The July recording
supplied the speaker name `Voce A`. It was excluded for July and available in both arms for
September and November. There were no manual terms. Each transcript was generated from the same sandbox audio and scored with `eval/run.py`.

The two Haiku notes promoted Overfitting, SLM, Transformer and Trasformata di Fourier.
The on arm also included Gerchberg, a September transcript correction, for July and November.
The name and correction were each excluded from their own recording. Speckle had been rejected
before scoring. All eligible terms fit the token budget.

| Recording | WER off | WER on | Term errors off | Term errors on |
|---|---:|---:|---:|---:|
| 07-23 | 19.57% | 20.37% | 1 | 1 |
| 09-29 | 16.29% | 14.87% | 5 | 5 |
| 11-10 | 26.05% | 22.92% | 6 | 3 |
| **Pooled** | **21.810%** | **19.806%** | **12** | **9** |

Each pair uses the same on-arm term list for scoring. After normalization and word alignment
with `eval.metrics`, count each missing or spurious whole-term occurrence as one error.
Pooled WER weights each recording by the number of reference words. The observed change was
−2.004 percentage points, within the +0.5-point limit. Term errors fell from 12 to 9.
Keep `auto_glossary_whisper` enabled by default on this three-recording proxy.
