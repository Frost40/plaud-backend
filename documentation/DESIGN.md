# Design: Plaud without the subscription, version 2

Status: proposal, 2026-11-17. Baseline: branch `rebuild-official-cli`, uncommitted, 14 tests passing.
Markers: **[unverified]** means I could not confirm the claim from a primary source or a run on
this machine. "Re-run today" means I ran the existing scoring scripts on existing files during this
design session; everything else under "measured" comes from `documentation/CHECKPOINT.md` and the
project memory, and I say so where it matters.

---

## 1. Summary

Version 2 keeps every model in use (`large-v3-turbo`, the turbo + Parakeet ensemble, pyannote
`community-1`); the evidence supports them. The failures are around the models. Redoing speakers
throws away the names, because speaker numbers are talk-time ranks. A failed import blocks itself
forever. Jobs are lost on restart. Notes go stale silently. Nothing is measured against real ground
truth.

Version 2 changes six things:

1. `recording.json` gets a schema version, stable speaker ids, raw speaker turns and voice embeddings.
2. Speaker corrections become real operations: names survive a redo, speakers merge, passages move,
   voices can be played, and known voices are suggested across recordings.
3. Renames reach existing notes for free; larger changes mark notes out of date for a one-click
   regenerate.
4. The glossary grows by itself from names, notes and corrections, ranked to fit Whisper's limit.
5. The job queue lives in SQLite, imports resume where they stopped, and the server starts with
   Windows.
6. Model swaps are experiments with kill rules; hand-labelled ground truth is designed but deferred.

---

## 2. Requirements

Each requirement below is the owner's frozen decision, restated. Each acceptance test is either an
automated test (a `pytest` name; the file is created in the milestone that delivers it) or a scripted
manual check that has a named procedure. Where a test does not exist yet, the milestone in section 7
that creates it is given.

**R1. Speakers first, words second, Italian = English, mixed meetings work.**
Acceptance is measured on the hand-labelled set (section 6) with `eval/run.py`:
- the speaker count is exact on every eval recording with 4 or fewer speakers;
- word speaker-attribution error is 5 % or less on the Italian and on the English excerpts;
- the Italian and English attribution errors are within 2 points of each other, measured on the
  owner's own meetings (G1–G3 against G7; the stage recording G4 does not count for parity);
- word error rate on the mixed Italian/English excerpt is within 3 points of the Italian excerpts.

Unit tests for the metrics: `tests/test_eval.py::test_attribution_error_on_synthetic_words` and
`::test_wer_normalisation`. Delivered in M1 and M7.

**R2. AI providers are swappable; none is hardwired.**
- `tests/test_llm.py::test_cli_provider_reads_stdin_and_output_file` uses a fake CLI written in Python.
- `::test_openai_provider_with_mock_transport` uses `httpx.MockTransport`.
- `::test_ensemble_and_notes_use_the_chosen_provider` checks that no code path names a provider
  literally.
- Manual check: `python -m app.doctor --providers` writes one note per installed provider from a
  2-minute fixture transcript.

Delivered in M6.

**R3. One recording has many notes; each is a (blueprint, provider) pair; all are linked and
reachable from one place.**
- `tests/test_core.py::test_same_blueprint_two_providers_two_notes_both_in_hub` checks that the hub
  lists both notes and that `recording.json` → `notes` has both entries.

Delivered in M5.

**R4. Real topic folders; moving a recording moves all its notes.**
- The existing `test_render_and_move`.
- New `::test_move_keeps_every_note_and_wikilink`: after the move, every file is in the new folder
  and every `[[link]]` in the hub resolves to a file in it.

Delivered in M2.

**R5. Obsidian is the store; data stays app-friendly (`recording.json` per recording).**
- `tests/test_schema.py::test_v1_migrates_to_v2` runs on copies of the four vault recordings, which
  are reduced to fixtures without words.
- `::test_save_is_atomic` checks that a crash mid-write leaves the previous file intact.
- `::test_v2_round_trip`.

Delivered in M2.

**R6. Highlights and memos survive and appear at the right time in transcript and notes.**
- `test_render_and_move` (existing: a memo sits before its utterance).
- New `::test_marks_survive_retranscribe_and_redo` and `::test_marks_are_in_the_note_prompt`.
- Manual check: for 07-23 and 09-29, compare the hub's mark list with
  `plaud transcript <id> --highlights`. The count must be equal, and every time must match to the
  second.

Delivered in M4 and M5.

**R7. No Docker, no Riffado, no Supabase.**
- `tests/test_repo.py::test_no_forbidden_dependencies` checks that `requirements.txt` and `app/`
  contain none of `docker`, `riffado` or `supabase`.

Delivered in M0.

**R8. Plaud is reached only through `@plaud-ai/cli`; no bypass.**
- `tests/test_repo.py::test_plaud_only_through_cli` checks two things: only `app/plaud.py` spawns
  `plaud`, and no file in `app/` contains a Plaud API host name. The audio download goes to the
  signed URL that the CLI prints. That is the CLI's own output, not a bypass.

Delivered in M0.

**R9. The local dashboard controls the system:**
- choose the transcription model per recording;
- see and change the folder;
- name speakers;
- redo speakers with a fixed count;
- create a note from a blueprint with a chosen provider.

Tests:
- `tests/test_server.py` uses FastAPI's `TestClient` with the pipeline functions replaced by fakes.
  There is one test per control, checking that the right job is queued with the right arguments.
- Manual click-through: the checklist in M8, run in the browser pane against the running server.

Delivered in M3 and M8.

**R10. Glossaries are per folder plus one global list; blueprints are editable Markdown in the vault.**
- The existing glossary assertions.
- New `::test_glossary_folder_plus_global_dedup`.
- New `::test_blueprint_edit_is_used_without_restart`: edit the file, generate, and check that the
  prompt contains the new text.

Delivered in M5.

**R11. At most about 4 speakers; RTX 3070 8 GB, 20 CPUs, Windows 10, no ffmpeg.**
- `tests/test_jobs.py::test_one_gpu_job_at_a_time`.
- `app.doctor` reports `ffmpeg: not needed, not found` and fails if any stage shells out to it.
- Manual check: import the 72-minute recording end to end while sampling `nvidia-smi` every 2 s.
  Peak VRAM must stay at or below 7.5 GB, and the server must answer `/api/state` in under 0.5 s
  throughout.

Delivered in M3 and M7.

**R12. Every proposal can be built and tested, and its test is named.**
- Every milestone in section 7 names its test.
- `pytest` passes at each milestone.
- Section 7 is the checklist.

---

## 3. Current system and evidence

### What exists

About 1,300 lines in `app/`:

| Module | Role |
|---|---|
| `plaud.py` | Wraps the official CLI 0.3.15. It parses the human-readable output and strips ANSI codes. |
| `speech.py` | Runs faster-whisper with hotwords, Parakeet TDT v3 through onnx-asr, and speaker separation (the pyannote worker in `.venv-pyannote`, with sherpa-onnx + `merge_voices` as the fallback in a child process). It also does phrase-level speaker assignment in `utterances`. |
| `ensemble.py` | An LLM arbiter over 30-second windows. Its output is restricted to candidate or glossary words. |
| `vault.py` | Folder layout, hub and transcript rendering, and owned-file protection. |
| `llm.py` | Runs a CLI provider (prompt on stdin) or any OpenAI-compatible API. |
| `pipeline.py` | `ingest`, `retranscribe`, `respeak`, `rename_speakers`, `generate`. |
| `server.py` | FastAPI app, an in-memory job list, one worker thread, and a poller that runs every 5 minutes. |
| `dashboard.html` | The dashboard page. |

The vault holds four imported recordings: three in `Inbox` and one in `Plaud tutorials`. There are
three blueprints, plus `_rules.md` and `_Glossary.md` (which is empty).

### What was measured, with caveats

**Speakers.** The yardstick is Plaud's own speaker labels at a 1-second grid. Plaud is a proxy, not
truth. The grid also hides two kinds of error: seconds where either side is silent are skipped, so
missed speech and false alarms are invisible, and overlap is reduced to one label.

| Recording | Real speakers | pyannote: count, agreement on raw turns (log) | Agreement on the final transcript (re-run today) | sherpa + merge 0.85 (re-run today from cached turns) |
|---|---|---|---|---|
| 07-23, 22 min, IT | 3 (Plaud) | 3, 96 %, 127 s | 95.4 % | 3, 90 % |
| 09-29, 50 min, IT | 3 (owner) | 3, 96 %, 89 s | 93.2 % | 3, 96 % |
| 11-10, 72 min, IT | 2 (owner) | 2, 89 %, 176 s | not in the vault | 2, 88 % |
| Jobs & Gates, 81 min, EN | about 10 | 9 found (end-to-end import) | 93.9 % | not run |

Caveats on these numbers:

- **The pyannote figures** come from `data/speaker-eval/pyannote_eval.log`, which was not re-run
  today (each pass is a 1.5 to 3 minute GPU job). They are untuned defaults. There are three
  recordings, all Italian and all with 2 or 3 speakers.
- **The final-transcript column** uses `score_rec.py`, which is stricter. It paints each paragraph's
  whole span, including pauses of up to 2 s and interjections inside a 60-second paragraph. On 09-29
  the drop from 96 % to 93.2 % mixes two things: real assignment loss inside `utterances()` and the
  scorer's paragraph painting. No current measurement separates them. Section 6 does.
- **The sherpa merge threshold.** Re-running today confirms that it is fragile. 11-10 collapses to 1
  speaker at every tested threshold from 0.75 to 0.82, and 07-23 splits into 5 speakers at 0.88. The
  threshold was fitted on the same three recordings it is scored on.
- **Jobs & Gates** is clean stage audio, so it is easier than a meeting room. Three audience
  questioners (McNamee, the Sony Pictures one, Rob Kelly) were merged into one speaker. One phantom
  speaker of 8 s appeared. Plaud files Charlie Brenner and the unnamed questioner at 79:15 under one
  label; our system keeps them apart. Nobody has listened to settle which is right. That disputed
  65 s is one reason the proxy cannot be trusted on its own.

**Words.** The yardstick is word disagreement with Plaud's transcript. The script that produced the
two-clip figures is not in the repository, so I could not re-run them.

- **Italian, turbo:** about 28x real time; 2.5 GB of VRAM (memory notes).
- **Italian, ensemble:** disagreement went from 11.9 % to 9.5 %, and from 24.9 % to 18.7 %, on two
  clips. The clip lengths are not recorded.
- **Approaches tested on Italian with no gain:** single-transcript LLM clean-up; `large-v3` as a
  third voter; per-segment language detection, which also disturbed the Italian output.
- **English, turbo:** 7.5 % disagreement on one 81-minute recording, with no glossary. The ensemble
  has never been run on English.
- **Listening sheet:** `documentation/transcription-comparison.md` holds side-by-side outputs for
  listening. Nobody has filled in its "Best" boxes, so it is not yet a measurement.

**Speed and the dashboard:**
- Jobs & Gates imported in 6 min 19 s.
- The ensemble re-transcription of 07-23 took 12 min, of which 8.5 min was speaker separation with
  the old sherpa default.
- The dashboard answered in under 0.3 s during jobs.

### Facts in the code that the brief does not list

These were found while reading the code and the vault. They drive the design.

1. **A failed import blocks itself.** `ingest` creates the folder and `recording.json` before
   anything can fail. After a failure, `vault.scan()` sees the recording as imported. The poller
   skips it, and `/api/import` refuses it ("already in the vault").
2. **Speaker numbers are talk-time ranks.** `tidy_turns` renumbers speakers so that speaker 0 talks
   most. Names are stored against those numbers, so any redo moves them to other voices. That is why
   `_speakers` clears them.
3. **Raw speaker turns are thrown away.** Only paragraphs are stored. Merge, split and reassign
   therefore all need the GPU again. pyannote's overlapping (non-exclusive) output and its per-speaker
   embeddings are also discarded. The 4.x pipeline returns both, and the worker reads neither.
4. **Merging by giving two speakers the same name only changes the display.** Paragraphs stay
   separate, and the hub's `speakers:` list repeats the name.
5. **Notes record nothing about their source.** There is no transcript revision and no speaker map,
   so they go stale silently on rename, redo and re-transcribe.
6. **`recording.json` has weak storage.** It has no schema version, and writes are not atomic.
   `/api/state` re-reads every word of every recording every 3 seconds. `start_at` has two formats
   in the vault (`2026-07-23T…` with 19 or 26 characters). Whether it is local time or UTC is not
   stated by the CLI [unverified].
7. **A Codex note exists.** The brief says Codex notes were never produced, but the vault contains
   `How to use Plaud - Mind map (codex).md`, created 2026-11-16 17:00. Codex has therefore produced
   at least one note through the current command. What remains untested is Codex on a full meeting
   (the checkpoint records that the usage limit was hit during testing).
8. **The Plaud CLI 0.3.15 has more options than the wrapper uses.** It offers paging (`-p`,
   `-s`) and server-side `--date-from`/`--date-to` on `files`. `plaud file <id>` prints these fields
   only: id, name, created_at, start_at, duration, serial_number, audio, transcript, summary. Only
   `summary --json` has a JSON mode, so the listing still has to be parsed from text.
9. **Photos are untested, not proven impossible.** The raw `--highlights` JSON has five keys per
   mark: `mark_id`, `mark_type`, `mark_content`, `timestamp` and `picture_link`. On 09-29 the four
   button highlights carry opaque values such as `oc_sc_source:…_i1`. These are not URLs, and the
   CLI offers no command that takes them. No recording in the vault has a photo mark (type 2), so
   what a photo's `picture_link` holds has never been seen. The type numbers themselves (1 and 4 =
   button, 3 = memo, 2 = photo) are the builder's inference [unverified].
10. **The non-ASCII text checks out.** The mark text in `recording.json` is valid UTF-8 (checked:
   no U+FFFD). Requirement 6 does not fail on encoding.

---

## 4. State of the art, per stage

Each candidate is filtered in this order: does it run natively on Windows without ffmpeg or Docker;
does it fit in 8 GB of VRAM; does it cover Italian and English; what are its licence and access
terms. The table records where each candidate fails. All benchmark numbers are copied from the
source named, on the test set named. None of them are on the owner's audio.

### 4.1 Speech-to-text

| Candidate | Windows, no ffmpeg | 8 GB | IT + EN | Licence / access | Published accuracy (source, set) | Verdict |
|---|---|---|---|---|---|---|
| Whisper `large-v3-turbo` via faster-whisper (in use) | yes, measured here (PyAV decode) | yes, about 2.5 GB measured | yes, 99 languages | MIT, open | Model card: "minor quality degradation" vs large-v3, decoder cut from 32 to 4 layers. No Italian number on the card. | Keep |
| Parakeet TDT 0.6B v3 via onnx-asr (in use, ensemble only) | yes, measured here | yes, about 5 GB measured | yes, 25 European languages, automatic language detection | CC-BY-4.0, open | Model card, greedy decoding, no punctuation: IT FLEURS 3.00 %, MLS 10.08 %, CoVoST 3.69 %; EN FLEURS 4.85 % | Keep, as the ensemble's second voice |
| Qwen3-ASR-1.7B | [unverified]: transformers or vLLM; the card does not mention Windows | likely (about 2B parameters, BF16) [unverified] | yes, 30 languages including Italian; code-switching not stated | Apache-2.0, open | Model card gives only multilingual averages that include Italian: FLEURS (12 languages) 4.90, MLS (8 languages) 8.55. No Italian-only figure. Its separate aligner covers Italian, with segments up to 5 minutes. | Experiment X2 (third or replacement voice) |
| Nemotron 3.5 ASR Streaming 0.6B (NVIDIA, June 2026) | the card lists Linux only; a transformers path exists (≥ 5.13) [unverified on Windows] | yes (0.6B) | yes; it-IT and en are in the "transcription-ready" tier; auto-detect labels each utterance's language | OpenMDW-1.1 | Model card, FLEURS, 1.12 s chunk: IT 4.25 %, EN 7.91 %; the card warns that cross-language normalisation is imperfect | Deferred; it fails the Windows filter until shown otherwise |
| Voxtral Mini 3B (Mistral) | [unverified] | **no**: the card says about 9.5 GB of GPU RAM in bf16/fp16 | yes, Italian named | Apache-2.0 | The card lists no Italian number in text; an open-asr mean of 7.05 is given without saying which language | Rejected (VRAM) |
| Voxtral Small 24B, Nemotron 3.5 Transcribe (30 to 34B), omniASR-LLM-7B | n/a | **no** | n/a | various | A third-party mirror of the Open ASR Leaderboard ranks Voxtral Small first on Italian (WER 3.42) [unverified: mirror, not the live Space] | Rejected (VRAM) |
| Whisper `large-v3` (tested here) | yes | yes | yes | MIT | Owner's clips: slower and not better | Keep only for comparison |

**Code-switching.** None of the cards above claims to handle a switch of language within an
utterance. Nemotron 3.5 labels the language per utterance, but it fails the Windows filter. The
current per-file language detection, with per-segment detection off, is the only option tested
here. It was tested on one splice. The real question is open until the owner records one real mixed
meeting (section 6).

### 4.2 Speaker separation (diarization)

| Candidate | Windows, no ffmpeg | 8 GB | Languages | Licence / access | Published accuracy (DER %, source) | Verdict |
|---|---|---|---|---|---|---|
| pyannote `speaker-diarization-community-1` (in use) | yes, measured here: in-memory waveform from a `.npy` file; pyannote 4.0 removed sox/soundfile and needs ffmpeg or in-memory audio, so in-memory is the right path | yes, measured | language-independent | CC-BY-4.0; gated (accept the terms, HF token); can run offline from a cloned repo | Model card, no collar, overlap scored: AMI-SDM 19.9, AliMeeting ch1 20.3, DIHARD3 20.2, VoxConverse 11.2, MSDWild 22.8 | **Keep** |
| pyannoteAI `precision-2` | hosted API | n/a | n/a | commercial, API key | Same card: AMI-SDM 15.6, DIHARD3 14.7, VoxConverse 8.5 | Rejected by the owner, D6 (paid, sends audio out) |
| DiariZen Large-s80-v2 (BUT) | [unverified]; the README pins conda, Python 3.10 and torch 2.1.1/cu121 | likely (WavLM-Large) [unverified] | language-independent | code MIT; **weights CC-BY-NC-4.0, research and academic use only** | README: AMI-SDM 13.9, AliMeeting far 10.8, DIHARD3 14.5, VoxConverse 9.1, compared with pyannote 3.1 (not community-1) | Deferred (licence plus Windows); worth one measurement only if the owner's use is non-commercial (D6) |
| NVIDIA Streaming Sortformer 4spk-v2.1 | NeMo; install docs are Linux-style; Windows not stated | 117M parameters; VRAM not stated | trained "primarily in English" | NVIDIA Open Model License | Model card, 30.4 s latency: DIHARD3 ≤4 speakers 14.84; AMI-SDM 17.80; CALLHOME 4 speakers 12.33. Hard limit of 4 speakers; degrades at 5 or more. | Rejected: hard limit of 4 (the owner says "about 4"; Jobs & Gates had about 10), English-trained, NeMo on Windows |
| NVIDIA Nemotron-3-Diarization (Sept 2026, up to 8 speakers) | NeMo [unverified] | about 100M parameters [unverified] | [unverified] | OpenMDW-1.1 per secondary coverage; one report calls the preview "evaluation-only" [unverified] | Secondary coverage only: DIHARD III 12.73 % offline [unverified] | Deferred: card not read, licence unclear, Windows unclear |
| sherpa-onnx + `merge_voices` (in use as fallback) | yes, measured | CPU | language-independent | Apache-2.0 [unverified] | Owner's recordings: see section 3; the threshold is fitted, and 11-10 collapses below 0.85 | Keep as fallback only |

**Verified facts that change the design.** The pyannote 4.x pipeline code returns:

- `speaker_embeddings`: one embedding per speaker, ordered like `speaker_diarization.labels()`;
- both `speaker_diarization` (overlapping) and `exclusive_speaker_diarization` (at most one speaker
  per frame);
- support for `num_speakers` or `min_speakers`/`max_speakers` (the bounds are ignored when
  `num_speakers` is given).

So stable identity across redo, overlap marking and cross-recording recognition need **no new
model**. They need the worker to save outputs it already receives. Sources: `speaker_diarization.py`
on pyannote-audio `main`, and the 4.0.0 release notes (VBx clustering, exclusive output, offline
use). I confirmed the same fields (`speaker_embeddings`, `exclusive_speaker_diarization`,
`min_speakers`) in the copy actually installed here, pyannote.audio 4.0.7 in `.venv-pyannote`.

### 4.3 Overlap

There are three options:

1. **Mark it.** The overlapping output already says where two people talk at once.
2. **Separate it.** pyannote has had separation pipelines, PixIT/ToTaToNet [unverified current
   status and licence].
3. **Ask an end-to-end model for multiple active speakers per frame.** Sortformer and
   Nemotron-3-Diarization do this. Both are rejected or deferred above.

The design marks overlap and measures how much of the owner's meetings it covers before anything
heavier is considered (experiment X3).

### 4.4 Speaker identity across recordings

pyannote returns a voice embedding per speaker (above). The sherpa path already computes pooled voice
prints (`voice_prints`). Recognising a person across recordings therefore needs these pieces:

- a small store of enrolled voices (a name plus the mean of the embeddings the owner confirmed);
- a cosine match;
- a threshold.

The threshold must be measured, not assumed. The 0.85 fitted for sherpa's merge uses a different
embedding model and does not transfer. The owner chose to add it as suggestions (D3).

### 4.5 Word timing and speaker assignment

| Option | Fit | Status |
|---|---|---|
| Whisper word timestamps from cross-attention (in use) | already here | Keep |
| torchaudio `VOXPOPULI_ASR_BASE_10K_IT` (WhisperX's default Italian aligner; English uses `WAV2VEC2_ASR_BASE_960H`) | torch is only in `.venv-pyannote`; no ffmpeg needed when given an array [unverified] | Experiment X4, only if errors cluster at turn boundaries |
| Qwen3-ForcedAligner-0.6B | covers Italian; at most 5 minutes per call; Apache-2.0 | Alternative inside X4 |
| ctc-forced-aligner (MMS) | **needs ffmpeg**; default weights CC-BY-NC-4.0 | Rejected |

### 4.6 Transcript correction

Measured here:
- the guarded two-model arbiter helped on two Italian clips;
- single-transcript LLM clean-up did not help;
- a third Whisper-family voter did not help.

The literature agrees on the mechanism: correction works when the model sees competing hypotheses.
HyPoradise (Chen et al., NeurIPS 2023, arXiv 2309.15701) shows generative correction over N-best
lists can beat N-best reranking, but its strongest results are with fine-tuning. I did not read its
in-context numbers [unverified], and fine-tuning is out of scope. Decision: keep the guarded
arbiter. Test whether a *different-family* voice (Qwen3-ASR) adds diversity (X2). Reject unguarded
clean-up.

### 4.7 Note generation and providers

The current CLI pattern is sound: prompt on stdin, tools off or blocked, empty working folder,
output to stdout or a file. It ran with Claude and, at least once, with Codex.

Why Antigravity CLI (`agy`) replaces `@google/gemini-cli` (`gemini`): on 2026-06-18 Google
deprecated consumer / Google AI Pro OAuth login on `@google/gemini-cli` (returning `#3501`:
"You do not have a valid license of this product" unless given a Workspace Code Assist seat or a
separate paid API key), and `gemini` 0.68.0's model table does not include Gemini 4 (`hydrogen`,
`argon`, `carbon`). Antigravity CLI (`agy`) uses the owner's existing Google AI Pro plan directly.

Antigravity CLI (`agy`) facts, verified on this machine against `agy.exe`:
- `-p <prompt>` / `--print` ignores `stdin` and requires a command-line string (which hits Windows'
  command-line length limit on long transcripts);
- `--input-format stream-json --output-format stream-json` reads NDJSON on `stdin`
  (`{"event": "user", "message": {"content": "..."}}`) without `-p`, and emits NDJSON events on
  `stdout` whose final `{"event": "result", "result": {"status": "SUCCESS", "response": "..."}}`
  holds the answer (or `error` on failure);
- `--sandbox` restricts terminal execution, `--disable-slash-commands` disables slash-command and
  skill expansion (note: `--mode plan` has no effect when slash commands are disabled), and
  `--settings` accepts session-only `permissions.deny` rules (e.g. `command(*)`, `write_file(*)`,
  `replace_file_content(*)`, `multi_replace_file_content(*)`, `sed_file(*)`, `mcp(*)`);
- verified in a temp folder: with `--sandbox` alone, `write_file` still wrote to the working
  folder, whereas adding `--settings` with `permissions.deny` blocked `write_file` ("Matches
  user-configured deny rule").

Still unverified for `agy`: what it prints when a Google AI Pro usage limit or expired login is hit
[unverified] (a timeout printed `AGY_ERROR: {"status":"DEADLINE_EXCEEDED","reason":"print_timeout"}`
on stderr). Note also that `agy` takes ~40 s per cold subprocess call because it starts the
Antigravity runtime, so `arbiter_provider` should avoid `agy` when a faster CLI has headroom. I could
not open the Codex `exec` documentation (the repo page only links out). The current Codex flags
are trusted because they produced a note, not because I verified them.

### 4.8 Local job handling

- SQLite ships with Python, needs no server, and survives restarts. A dedicated queue library
  (Huey, Celery and others) would add a dependency for one worker and one table.
- Windows can start a program at logon with Task Scheduler or a Startup-folder shortcut. Both are
  built into the OS.

Choice: stdlib `sqlite3` plus a Task Scheduler entry. Nothing to verify beyond Python's and
Windows' own documentation.

### Sources consulted

- pyannote `speaker-diarization-community-1` model card (huggingface.co/pyannote/speaker-diarization-community-1)
- pyannote-audio releases (github.com/pyannote/pyannote-audio/releases)
- pyannote `speaker_diarization.py` on `main`
- Parakeet TDT 0.6B v3 card (huggingface.co/nvidia/parakeet-tdt-0.6b-v3)
- Whisper large-v3-turbo card (huggingface.co/openai/whisper-large-v3-turbo)
- Qwen3-ASR-1.7B card (huggingface.co/Qwen/Qwen3-ASR-1.7B)
- Nemotron 3.5 ASR Streaming card (huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)
- Voxtral Mini 3B card (huggingface.co/mistralai/Voxtral-Mini-3B-2507)
- Streaming Sortformer v2.1 card (huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1)
- DiariZen README (github.com/BUTSpeechFIT/DiariZen)
- WhisperX `alignment.py`
- ctc-forced-aligner README
- Antigravity CLI docs (`antigravity.google/docs/cli/reference`, `antigravity.google/docs/permissions`) and live verification of `agy.exe` on this machine
- HyPoradise (arXiv 2309.15701): abstract and summary only, not its tables
- Seen only as search results, not read, and marked [unverified] where used: the Open ASR
  Leaderboard paper (arXiv 2510.06961), coverage of Nemotron 3.5 Transcribe and
  Nemotron-3-Diarization, and the Italian leaderboard mirror
- Checked on this machine: the installed pyannote.audio 4.0.7 source, pyannote.metrics 4.2.0 in
  `.venv-pyannote`, `plaud` 0.3.15 help text, `plaud file` output and raw `--highlights` JSON for
  three recordings

---

## 5. Design

### 5.0 Decision per stage

Each row is one stage. "Expected gain" is what the decision should change and by how much.
"Confirm or kill" is the measurement that settles it, and "Fallback" is what happens if it fails.
Where no accuracy gain is expected (the change is about reliability or workflow), the row says so,
and the measurement is a test rather than a metric.

| Stage | Decision | Evidence | Expected gain | Confirm or kill | Fallback |
|---|---|---|---|---|---|
| Plaud access | **Keep** the CLI wrapper; add paging and `--date-from` | Works end to end; CLI 0.3.15 help shows both options | Removes the 100-recording ceiling; no accuracy change | `test_parse_plaud_listing` with a 2-page captured sample | Current single page |
| Speech-to-text | **Keep** turbo as default, ensemble as option | Section 3 (turbo 28x; ensemble −2.4 and −6.2 points vs Plaud on two Italian clips) | None now | M7 baseline on G1–G7; X2 tests a different-family voice | n/a |
| Ensemble on English | **Measure** before recommending | Never run on English | Unknown; at least 1 point of WER on G4/G7 to keep it for English | M7: ensemble vs turbo on G4/G7 | Default English to turbo |
| Transcript correction | **Keep** the guarded arbiter; make its provider a setting | Single-transcript clean-up measured no gain | No accuracy change from the setting; it only moves usage | `test_ensemble_and_notes_use_the_chosen_provider` | `default_provider`, as today |
| Speaker separation | **Keep** pyannote `community-1`, untuned; store overlap turns and embeddings | Right count on 3 of 3 Italian recordings, 89–96 % vs Plaud | None from the model; storing outputs enables every correction below | M7 baseline; no speaker cap (D7) | sherpa + merge, as today |
| Overlap | **Change**: mark phrases that touch overlap | pyannote already returns overlap; nothing uses it | No accuracy gain; it points the owner at the passages most likely wrong | On G5, flagged phrases must hold at least twice the attribution error rate of unflagged ones; otherwise the flag is noise and is removed | No marker |
| Word assignment | **Keep** phrase-level assignment; **measure** its loss | 96 % on raw turns vs 93.2 % on the final transcript (09-29), mixed with scorer effects | Unknown until split | M7: attribution error on raw turns vs final utterances; X4 if boundary errors dominate | Current `utterances()` |
| Speaker ids and corrections | **Change**: stable ids, names carried across redo, merge, fixes, voice samples | Today every redo clears names; same-name merge is display-only | Names lost per redo: from all to none on the test cases | `tests/test_speakers.py` (5.4); M4 manual check on Jobs & Gates | None needed: the old renumbering is what this replaces |
| Identity across recordings | **Add** as suggestions (D3: yes) | Embeddings are already returned | Fewer names typed by hand; false suggestions at or below 5 % | Leave-one-recording-out on the owner's named speakers (5.4, rule 8) | Name by hand, as today |
| Glossary | **Change**: grows automatically from names, notes, corrections and the ensemble; ranked to fit Whisper's 223-token hotword limit | Hotwords fixed domain terms; today's join silently loses terms past the limit | Fewer errors on domain terms with no typing | Proxy re-transcription check in 5.12 | Manual glossary only, as today |
| Notes | **Change**: provenance and out-of-date badge | Notes go stale silently today | Stale notes shown: from none to all | `test_rename_marks_note_out_of_date` | Notes as today |
| Providers | **Keep** `llm.py`; add a check, Antigravity (`agy`), error classes | Claude and Codex both produced notes; `agy` verified headless in stream-json | A usage limit no longer loses a transcript | `tests/test_llm.py`; M6 manual check | Remove a provider from the list |
| Jobs | **Change**: SQLite queue, stages, retries, autostart | Failed imports block themselves; jobs vanish on restart | Jobs lost on restart: from all to none | `tests/test_jobs.py`; M3 kill-and-restart check | The in-memory list, as today |
| Storage | **Change**: schema 2, atomic save, state cache | No version, non-atomic writes, full re-read every 3 s | Safe migrations and a faster `/api/state` | `tests/test_schema.py` | Keep the v1 backup files |

### 5.1 Architecture

The shape stays the same: one Python process (FastAPI, a worker thread, a poller) plus child
processes for GPU and CPU-heavy work. There are four changes.

- **The job queue moves into `data/jobs.db` (SQLite).** The worker stays single, because the GPU
  fits one model at a time.
- **The pyannote worker writes more.** It writes the overlapping turns, the exclusive turns and the
  per-speaker embeddings, instead of the exclusive turns alone.
- **A new module, `app/doctor.py`, checks the installation.** It checks the CLIs, logins, models,
  VRAM, the absence of ffmpeg, and the providers. It is used both by setup and by the dashboard's
  status line.
- **The poller pages through Plaud** with `plaud files --date-from <auto_since> -s 100 -p N`. That
  removes the 100-recording ceiling.

New files are kept to a minimum: `app/jobs.py` (queue), `app/doctor.py`, `eval/` (scoring, moved
from the git-ignored `data/speaker-eval/` so that the code is versioned and the data stays
ignored), and `scripts/autostart.ps1`.

### 5.2 Data layout in the vault

The folder layout does not change:

```
<vault>/Plaud/<Folder>/<date title>/recording.json
                                   /<date title>.md                     hub
                                   /<date title> - Transcript.md
                                   /<date title> - <Blueprint> (<provider>).md
                                   /<date title>.ogg
<vault>/Plaud/<Folder>/Glossary.md
<vault>/Plaud/_Glossary.md
<vault>/Plaud/_Blueprints/*.md, _rules.md
<vault>/Plaud/_Voices.json          enrolled voices for cross-recording suggestions (D3, see 5.4)
```

**`recording.json`, schema 2.** It stays one file per recording: one file is the simplest thing
for both Obsidian and the future app. Fields:

```jsonc
{
  "schema": 2,
  "id": "of_…", "title": "…", "date": "2026-09-29",
  "start_at": "2026-09-29T13:03:44",          // normalised: seconds precision, local time, no zone
  "duration_s": 2996.0, "duration": "49m56s",
  "stem": "…",
  "stage": "done",                            // new | downloaded | transcribed | speakers | done
  "error": null,                              // {stage, message, at, attempts} after a failure
  "language": "it",
  "transcript": {"model": "ensemble", "rev": 3, "at": "…", "glossary": ["…"]},
  "words": [{"s": 0.0, "e": 0.52, "w": " effettivamente"}],
  "diarization": {
    "engine": "pyannote", "rev": 2, "at": "…",
    "asked": {"num": 0, "min": 0, "max": 0},
    "turns":   [[0.0, 18.9, "S1"]],           // exclusive: one speaker at a time
    "overlap": [[61.2, 62.0]],                // stretches where two or more people talk
    "embeddings": {"S1": [0.01, …]}           // pyannote: one vector per speaker
  },
  "speakers": {"S1": {"name": "Paolo"}, "S4": {"name": "", "merged_into": "S2"}},
  "fixes": [{"s": 1200.0, "e": 1214.5, "spk": "S3"}],   // owner's manual reassignments
  "utterances": [{"s": 0.0, "e": 18.96, "spk": "S1", "text": "…", "overlap": false}],
  "marks": [{"t": 1167.0, "kind": "highlight", "text": "…"}],
  "notes": [{"file": "… - Meeting minutes (claude).md", "blueprint": "Meeting minutes",
             "provider": "claude", "at": "…", "transcript_rev": 3, "speakers_rev": 5,
             "check_failed": []}],
  "speakers_rev": 5,
  "history": [{"kind": "transcript", "rev": 3, "changed": 0.012},     // share of words changed
              {"kind": "speakers", "rev": 5, "changed": 0.0, "renamed": {"S3": "Paolo"}}],
  "true_speakers": 3,                         // count the owner confirmed; null if not confirmed
  "written": {"… - Transcript.md": "<sha1>"}
}
```

Rules:

- **Speaker ids are stable strings (`S1`, `S2`, …).** They are never renumbered by talk time.
  Display order is by talk time, computed when rendering.
- **`speakers_rev` goes up** on every rename, merge, fix or redo. `transcript.rev` goes up on every
  transcription.
- **Writes are atomic.** Write `recording.json.tmp`, then `os.replace`. Readers never see half a
  file.
- **`/api/state` keeps an in-memory cache keyed by path and mtime.** It returns a summary without
  `words`. Edits that Obsidian makes are seen because the mtime changes.
- **Migration from schema 1** (the four current recordings). Integer speaker `k` becomes `S{k+1}`.
  `speakers {"0": "Paolo"}` becomes `{"S1": {"name": "Paolo"}}`. `notes` is rebuilt from each note
  file's front matter, with both revisions set to 1. `stage` becomes `done`. `duration_s` is parsed
  from `duration`. `start_at` is normalised. The migration runs once at startup and keeps
  `recording.v1.json` beside the new file as a backup. Version 1 kept no raw turns, so
  `diarization.turns` is synthesised from the utterances (one turn per paragraph), with
  `engine: "migrated"`, no overlap and no embeddings. Merge, fixes and samples therefore work on
  migrated recordings at paragraph resolution. The first "Redo speakers" replaces the synthetic
  turns with real ones, and rule 2 in 5.4 carries the names across.
- **`true_speakers`** is a separate field holding the count the owner confirmed. It is not
  `diarization.asked.num`, which only records what a redo was asked to use. The evaluation's count
  metric reads `true_speakers`.
- **Future versions** bump `schema`, add a migration function, and add a fixture test. Readers that
  see a higher `schema` than they know refuse to write. This protects data written by a newer app.

### 5.3 Pipeline stages and failure handling

`ingest` becomes a sequence of stages. Each stage writes `stage` when it finishes:

1. **download** (CLI): audio, marks, full title.
2. **transcribe** (GPU): turbo or ensemble.
3. **speakers** (GPU, child process): diarization, then assignment.
4. **notes**: blueprints with `auto: true`.

On failure, `error` is filled in and the folder stays.

- **The poller** treats a recording whose `stage != done` and that has no live job as unfinished.
  It requeues from the next stage, with up to 3 automatic retries after the initial execution
  (4 executions total), delayed 5 min, 30 min and 2 h. Exhausted and GPU failures remain stopped
  until manual Retry; the poller does not create a fresh job to bypass that limit.
- **Manual import** of an unfinished recording resumes it instead of refusing it.
- **The notes stage** retries each failed blueprint separately. A usage-limit failure from a
  provider does not undo the transcript.
- **Expired Plaud sign-in** (`AUTH_FAILED`) pauses all download jobs and shows "run `plaud login`"
  at the top of the dashboard. It does not use up attempts.
- **A GPU out-of-memory error** is not retried automatically. It is shown with a "Retry" button,
  because retrying the same thing would fail again.

### 5.4 Speaker workflow, including corrections

This is the top-priority part. Each piece is small and testable without a GPU, because it works on
the stored turns.

0. **Re-transcribing no longer redoes speakers.** Today `_transcribe` always calls `_speakers`, so
   "Transcribe again" re-diarizes and clears every name. In version 2 it re-runs only the assignment
   of the new words to the *stored* turns (CPU, seconds). Speaker ids, names, merges and fixes are
   untouched. Diarization runs only on import and on an explicit "Redo speakers". Test:
   `tests/test_speakers.py::test_retranscribe_keeps_turns_and_names`.

1. **Automatic run.** pyannote decides the count on its own. There is no cap and no default bound
   (owner decision D7); the only override is the exact count the owner types for a redo. The
   overlapping turns, exclusive turns and embeddings are all stored. Assignment stays phrase-level
   (`utterances`), working from the exclusive turns. A phrase that touches 0.5 s or more of overlap
   is marked `overlap: true`. The transcript shows it with a small ⇄ marker, so the owner knows where
   to check.

2. **Names survive a redo.** After a redo, each new speaker is matched to the old speaker it shares
   the most talk-seconds with. This is the same greedy one-to-one matching the scorer uses. A new
   speaker inherits the old id and name when at least 50 % of its talk time falls on that old
   speaker's turns. Otherwise it gets a fresh id with no name. `fixes` are re-applied after a redo.
   An old speaker that has a name or is the target of a fix is never deleted, even when no new
   speaker matches it. It stays in `speakers` and keeps the spans its fixes give it, so a fix can
   never point at an id that no longer exists.
   Test: `tests/test_speakers.py::test_redo_keeps_names_by_overlap`, which uses synthetic turns with
   shuffled indices and one speaker split in two.

3. **Merge.** "Merge S4 into S2" sets `S4.merged_into = S2`. It rewrites `S4` to `S2` in the turns,
   rebuilds the utterances so consecutive paragraphs join, and bumps `speakers_rev`. It is undoable,
   because the original turns are kept and `merged_into` can be cleared. Giving two speakers the same
   name now *offers* a merge instead of silently showing two people under one name. Test:
   `::test_merge_joins_paragraphs_and_hub_lists_name_once`.

4. **Move a passage.** In the dashboard's speaker view, each paragraph has a speaker drop-down. A
   change records `{s, e, spk}` in `fixes` and re-runs assignment on the CPU. A new speaker can be
   created this way. This is how the three merged questioners in Jobs & Gates would be split. Test:
   `::test_fix_reassigns_only_its_span_and_survives_redo`.

5. **Hear a voice.** Each speaker row has a ▶ button. It plays the speaker's three longest turns
   through an `<audio>` element. The element points at a new `GET /api/audio/{id}?s=…&e=…`, which
   serves the `.ogg` file with HTTP Range so the browser seeks. This answers "who is S3?" without
   opening Obsidian. Test: `tests/test_server.py::test_audio_route_serves_range`.

6. **Short speakers are flagged, not deleted.** A speaker under 30 s of talk, or under 2 % of the
   speech, gets a "check" badge. A one-click "merge into closest voice" uses the embedding cosine.
   The Jobs & Gates evidence shows why nothing is dropped automatically: real questioners talked
   32 to 50 s, and the phantom 8 s.

7. **Wrong count.** The dashboard offers, in this order:
   - (a) fix the count and redo (exists);
   - (b) merge;
   - (c) move passages.

   The automatic count is shown with a note that the owner should confirm it. Once the owner
   confirms a count, it is stored as `true_speakers`. All three actions keep names, by rule 2.

8. **Recognise people across recordings (owner decision D3: yes).** Every speaker the owner names
   adds its embedding to `<vault>/Plaud/_Voices.json`, which looks like
   `{"Paolo": {"pyannote": [{"rec_id": "of_…", "spk": "S1", "vector": [0.01, …]}]}}`.
   It holds at most 20 vectors per person and engine, the newest kept. After every diarization,
   each unnamed speaker is compared with every
   enrolled person: the score is the cosine of its embedding against that person's mean vector.
   - The best match above the threshold becomes a **suggestion** shown in the dashboard ("sounds
     like Paolo, 0.81 — accept?"). It is never applied silently. Accepting fills in the name, which
     enrols one more vector.
   - Two speakers of one recording are never both suggested as the same person; the higher score
     wins.
   - **Threshold without extra labelling work.** The owner's own names are the ground truth: every
     named speaker in the vault is a labelled example. Leave-one-recording-out: for each named
     speaker, match it against voices enrolled from the *other* recordings. The threshold is the
     lowest value whose false-match rate stays at or below 5 % over all named speakers. Until at
     least 3 people are each named in at least 2 recordings with the same engine, the panel
     withholds suggestions because the threshold cannot be measured.
   - Embeddings from sherpa and from pyannote are different models and are never compared with each
     other. Each vector is stored with its engine name.
   - Tests: `tests/test_voices.py::test_enrol_on_naming`, `::test_suggestion_needs_threshold`,
     `::test_no_two_speakers_get_the_same_suggestion`, `::test_threshold_from_leave_one_out`
     (synthetic vectors), `::test_engines_never_mixed`.

The **sherpa fallback** uses the same stored format: ids, turns, and voice prints as embeddings.
Everything above therefore works on both engines.

### 5.5 Notes and blueprints

- **Prompt.** It is built as today: rules, the blueprint, the flagged moments, then the transcript
  with names. One addition: the folder glossary goes into the prompt as "spellings to use" (R10).
  `requires:` checking and the single retry stay.
- **Provenance.** Front matter gets `transcript_rev`, `speakers_rev` and `speakers` (the id → name
  map used). The note is also added to `recording.json` → `notes`.
- **Keeping notes correct without wasting tokens (owner decision D4).** Each change is handled at
  the lowest cost that keeps the note right:

  | What changed | What happens to existing notes | Tokens spent |
  |---|---|---|
  | A speaker is named or renamed | The old label (for example "Speaker 3") is replaced by the new name everywhere in the note body. Whole words only, using the id → name map in the note's front matter. The map is updated. | none |
  | Two speakers are merged | Same substitution: the merged speaker's label becomes the target's name. | none |
  | Re-transcription changed less than 2 % of words, and speakers are unchanged | The note is kept and its revision updated, with `minor_change: true`. | none |
  | Re-transcription changed more, or a redo or a fix moved more than 2 % of words to another speaker | The note is marked "out of date". The dashboard shows "Regenerate" on that note. | only when the owner clicks |

  The share of changed words is computed when the change happens, while both the old and the new
  versions are in memory. It is a word-level diff of the transcript text, and for speakers the
  share of words whose speaker changed. It is stored in the recording's revision history, so a note
  several revisions behind adds up the shares since its own revision.
  Nothing ever regenerates a note automatically. Regenerating writes through the existing
  `_write_owned` path, so if the owner edited the note, the edit is kept as "(your edit n).md".
  The 2% boundary itself is out of date (minor means strictly less than 2%). A free relabel does
  not advance past earlier substantive speaker changes, so an already stale note stays stale.
  Undoing a merge or renaming one of two identically named people cannot reliably split identical
  labels: ambiguous mentions retain their actual label map and set `relabel_failed: true` in
  front matter and the note index. This keeps the note out of date until regeneration clears it,
  even when the speaker-change share is below 2% or the rename itself changed no assignments.
  Relabelling an owner-edited note preserves its ownership hash mismatch for that later backup.
  Tests: `tests/test_notes.py::test_rename_rewrites_labels_without_llm` (the provider is a fake
  that fails the test if called), `::test_merge_rewrites_labels_without_llm`,
  `::test_small_retranscribe_keeps_note`, `::test_large_change_marks_out_of_date`,
  `::test_regenerate_keeps_owner_edit`.
- **The hub stays the one place every note is reachable from.** It is rebuilt from `notes`, so a
  note file that was renamed by hand drops off with a warning instead of a broken link.

### 5.6 Providers

`llm.py` keeps its two kinds, `cli` and `openai`. Changes:

- **Each provider entry gains an optional `check` prompt.** `app.doctor --providers` runs it
  ("Reply with OK") and reports what each one returns. The dashboard lists only providers whose last
  check passed, with the time of the check.
- **Antigravity (`agy`).** Replaces the deprecated `gemini` CLI. Uses `"format": "agy-stream-json"`
  with `["agy", "--input-format", "stream-json", "--output-format", "stream-json", "--model",
  "gemini-4-hydrogen-medium", "--sandbox", "--disable-slash-commands", "--settings", <deny JSON>]`.
  The prompt is sent on `stdin` as an NDJSON `user` event and the answer is read from the
  `result` event on `stdout`. Uses the owner's existing Antigravity / Google AI Pro sign-in.
- **The ensemble arbiter's provider** becomes a setting (`arbiter_provider`). It is no longer
  implicitly `default_provider`, so the owner can put the high-volume arbiter calls on the
  subscription with the most headroom.
- **Provider errors are classified** as usage limit, auth or other. The classification uses the
  exit code and the stderr text. It drives the retry policy in 5.3. Test: `tests/test_llm.py` with
  fake CLIs that print the known limit messages.

### 5.7 Dashboard

It stays one HTML file. Additions, in priority order:

1. A speaker view per recording: the rules in 5.4, with ▶ samples, merge, per-paragraph reassign,
   the exact-count redo, the "check" badges, and the "sounds like …" suggestions (5.4, rule 8).
2. Note rows with an "out of date" badge and a "Regenerate" button.
3. The job list, read from SQLite, so it survives restarts, with failed jobs showing a "Retry"
   button and the error text.
4. A status line from `app.doctor`: Plaud login, GPU, providers.
5. Everything that exists today stays.

The redraw rule ("don't redraw while the user is typing") stays.

**Redesign (decided 2026-11-17, built after the features exist).** The owner wants the dashboard
more modern, minimal, better looking and easier to use. The look and the layout are chosen with
the owner from options. These limits hold whatever is chosen:
- It stays one HTML file served by the server, with no build step. It loads nothing from the
  internet (system fonts, inline icons), because it must work offline.
- Every control and every API call that exists keeps working the same way; the redesign changes
  how things look and where they sit, not what they do.
- Light and dark follow the system setting, as today. It must stay usable at phone width.
- Exception agreed with the owner (2026-11-18, ticket 10): the read-only `GET /api/notes/{id}/{file}`
  planned for the app (below) is built now, so the dashboard can show each note's text in a tab.
- Chosen layout (ticket 10): recordings on the left (All recordings, Not imported yet, folders that open in place,
  New folder, drag a recording onto a folder to move it, search scoped to the selection); a recording shows a
  Transcript tab and one tab per note; ⚙️ Settings holds folder, model, names and count. It reads only files in the recording's note index.
- Chosen speaker view (ticket 10, Part C): no separate panel. In the Transcript tab, a speaker's name in the list opens a card
  (name, listen, "same person as" = merge, undo merge); a passage's name opens "Who says this?" (= the per-paragraph
  reassign of 5.4 rule 4, plus undo); one plain question at a time covers the "check" voices, the suggestions and the
  confirmed count. The exact-count redo stays in ⚙️ Settings.
- Chosen notes, glossary and providers (ticket 10, Part D): a dot on an out-of-date note tab and an "Out of date" bar
  with Regenerate; "+" asks what kind of note and which ready AI writes it; an "AI" chip in the top bar lists each
  provider's state with "Check again"; a Glossary tab next to Transcript reads and edits the folder glossary.
- Second exception agreed with the owner (2026-11-18, ticket 10, Part D; reshaped 2026-11-22):
  `GET /api/recordings/{id}/glossary` and `POST /api/recordings/{id}/glossary {action, term}`. The tab groups the
  folder glossary for one recording, each word once: New (found here, waiting), Heard (active and said here),
  Added by you (your words, speaker names and fixes first given on this recording), then Active, Waiting and
  Blocked for the rest of the folder. Actions are single words: add, use (active without a second recording),
  block, restore, delete (only from Blocked: removes the evidence too; a later recording may find it again).
  Each action names the state it expects, so a stale page gets 409 instead of a wrong change. Owner lines are
  rewritten only when they change. `Glossary.json` also keeps the recordings each owner word was added on and the
  owner words now blocked; words added on a recording move with it to its new folder (the Inbox keeps its copy).

### 5.8 Job queue

There is one table:
`jobs(id, rec_id, kind, args_json, status, attempts, not_before, error, created, updated)`.

- **Status values:** `queued | running | done | failed | paused`.
- **At startup,** `running` rows go back to `queued`. Each stage is idempotent at stage
  granularity, so resuming is safe.
- **One worker thread** takes the oldest `queued` row whose `not_before` has passed.
- **The dashboard keeps its 3-second refresh.** The data comes from a cheap read of the jobs table.

Tests in `tests/test_jobs.py`:
- `test_running_job_requeued_after_restart`;
- `test_failed_import_resumes_from_its_stage` (fake `plaud` and `speech`);
- `test_auth_failure_pauses_without_using_attempts`;
- `test_one_gpu_job_at_a_time`.

### 5.9 Starting with Windows

`scripts/autostart.ps1` registers a Task Scheduler task "Plaud dashboard" with these settings:

- trigger: at logon;
- action: `<project>\.venv\Scripts\pythonw.exe -m app.server`;
- start in: the project folder;
- restart on failure 3 times, 1 minute apart.

Output goes to `data/server.log` (rotated at 5 MB with the stdlib `RotatingFileHandler`). A second
instance exits at once when the port is taken. The dashboard shows "server started at …" so a silent
restart is visible.

Test: a manual reboot check. The script also has `-Check`, which runs `schtasks /query` and prints
the last run result.

### 5.10 Setup on a new machine

This becomes `documentation/SETUP.md`, verified by `python -m app.doctor`:

1. Install Python 3.11 and Node LTS. Install nothing else system-wide; ffmpeg is not needed.
2. Create the main environment:
   - `py -3.11 -m venv .venv`
   - `pip install -r requirements.txt`
   - uninstall the CPU `onnxruntime` that faster-whisper pulls in, as the requirements comment says.
3. Install and log in to Plaud: `npm install -g @plaud-ai/cli`, then `plaud login`.
4. Set up pyannote:
   - accept the terms on the model page and run `hf auth login`;
   - create `.venv-pyannote` with `pyannote.audio`;
   - reinstall torch from the **cu126 index** with `--no-deps`. PyPI's wheel is CPU-only on this
     machine.
5. Fetch the models: Parakeet with `onnx-asr` into `models/parakeet-v3`, the sherpa models into
   `models/`. `app.doctor --fetch-models` prints the exact commands; it does not run them silently.
6. Log in to each provider CLI you use: `claude`, `codex`, `agy` (Antigravity CLI).
7. Put the vault path in `config.json`.
8. Run `scripts/autostart.ps1`.
9. Run `app.doctor`. Every line should report `ok`.

### 5.11 The path to the Flutter app

**Postponed by the owner (D5).** This section fixes where the app plugs in, so nothing built now
has to be undone; none of it is built until the owner reopens D5. The app sits at the very end of
the pipeline. It is a second client of the same server, beside the dashboard, and it never takes
part in import, transcription, speakers or notes.

- **The app talks to this server's HTTP API.** It never writes to vault files directly. There is
  then one writer, and that keeps `written` hashes, revisions and atomic saves trustworthy.
- **The app reads** `GET /api/state` (summaries), `GET /api/recordings/{id}` (the full
  `recording.json`), the Markdown note files through a new `GET /api/notes/{id}/{file}`, and the
  audio route.
- **The app writes** through the same POST routes the dashboard uses.
- **Changes needed before the app:** schema 2 with stable speaker ids and the notes index (M2, M4,
  M5), and a short API description generated from FastAPI's own OpenAPI output (`/openapi.json`,
  already served by FastAPI at no cost).
- **Whether the app runs on the phone** over the local network, which needs binding beyond
  127.0.0.1 and a token, is owner decision D5. Nothing else in the layout depends on it.

### 5.12 Automatic glossary

The owner asked for the glossary to grow by itself, so that the models learn each topic's names
and terms without anyone typing them in. Glossaries stay where they are: one `Glossary.md` per
folder plus `_Glossary.md` for everything (R10).

**One fact limits the design.** faster-whisper 1.2.1 (installed here) cuts the hotwords to 223
tokens (`max_length // 2 - 1` in `get_prompt`). It does this silently. Today `_transcribe` joins
every term with ", ", so once a glossary grows past roughly 100 to 150 terms [unverified: depends
on the words], the tail is dropped without warning. An automatic glossary therefore needs ranking
and a budget, not just appending.

**Where terms come from.** All four sources are free or nearly free in tokens.
1. **Speaker names** given in the dashboard go into the folder glossary at once. Cost: none.
2. **The notes the owner already generates.** The note prompt ends with this instruction: "After the note,
   add a fenced block marked `glossary` that lists up to 15 names, technical terms and acronyms
   spoken in this meeting, spelled correctly, one per line." The block is parsed and removed before
   the note is saved. Cost: about 50 output tokens per note, in a call that happens anyway. No
   extra call is ever made just for the glossary.
3. **The owner's own corrections.** When the owner edits a transcript in Obsidian, the existing
   `written` hash detects it. The edited text is compared word by word with the generated one, and
   every replacement word that is capitalised, contains a digit, or is absent from the transcript's
   other words becomes a candidate. Cost: none.
4. **The ensemble arbiter's choices** (only for recordings transcribed with `ensemble`). These are
   words where the arbiter chose Parakeet's spelling over Whisper's and that are capitalised or are
   not common words of the transcript's language. The common words come from the transcripts already
   in the vault, so no dictionary file is needed. They are found by comparing the fused words with
   Whisper's own words for the same window. Cost: none; it reads output that already exists.

**How a term becomes active.** `Glossary.md` gets two marked parts. Above the marker are the
owner's own lines, always active and never touched by the system. Below it, the system keeps its
own list, one term per line with its evidence:

```
%% Automatic terms below. Delete a line to drop a term; move it above to keep it for good. %%
- MRAF · 3 recordings · last 2026-11-17
- pistone medio · 2 recordings · last 2026-09-29
%% Rejected: never added again %%
- Walsh
```

- A candidate becomes active when it has been seen in **2 or more recordings** of the folder. The
  exceptions are speaker names and owner corrections, which are active at once because a human
  supplied them.
- An active automatic term seen in **2 or more folders** is copied into `_Glossary.md`'s automatic
  list.
- A line the owner deletes from the automatic list moves to "Rejected" and is never re-added.
- The terms from one recording never feed the transcription of that same recording; they apply
  from the next recording on (or when the owner presses "Transcribe again"). That avoids a loop
  where a mistake confirms itself.

**Budget.** At transcription time the active terms are ordered: the owner's folder terms, the
owner's global terms, speaker names, then automatic terms by number of recordings and recency. Each
term's length is counted with Whisper's own tokenizer. Terms are added until the 223-token limit
would be passed, leaving a margin of 10 tokens. The terms left out are recorded in
`recording.json` → `transcript.glossary_dropped`, and the dashboard shows "N glossary terms did not
fit". The ensemble's word guard and the notes prompt use the **whole** active list, because they
have no such limit.

**Measuring it (owner decision D2 deferred, so on the proxy).** Re-transcribe the three Italian
recordings once with the owner's manual terms only and once with the automatic list added. Then
compare against Plaud's transcript, both overall and on the glossary terms' own spellings. Keep the
automatic list if word disagreement does not rise by more than 0.5 points and term errors fall.
Otherwise, keep the automatic list for notes and the ensemble guard only, and stop passing it to
Whisper: the setting `auto_glossary_whisper` (default `true`) is set to `false` in the defaults.
The owner's manual terms always reach Whisper. Hotwords can push Whisper to insert a term that was not said, which is the risk this check
covers.

**Tests:** `tests/test_glossary.py::test_parse_and_strip_glossary_block`,
`::test_promotion_needs_two_recordings`, `::test_names_and_corrections_active_at_once`,
`::test_rejected_term_never_returns`, `::test_budget_keeps_owner_terms_first_and_reports_dropped`
(uses the real tokenizer, no GPU), `::test_edit_diff_finds_corrected_term`,
`::test_terms_do_not_feed_their_own_recording`.

### 5.13 Sandbox for test runs

Real runs during development must not touch the owner's vault. Two small things make that easy:
- `app/config.py` reads its settings file from the environment variable `PLAUD_CONFIG` when it is
  set, and from `config.json` in the project root otherwise. `python -m app.server --config FILE`
  sets that variable before anything else is imported.
- `scripts/make_sandbox.py` copies `<vault>/Plaud/` (read-only on the source) to
  `data/sandbox/vault/Plaud/` and writes `data/sandbox/config.json` with that vault, port 8378,
  `auto_process: false` and `data_dir: data/sandbox/state`. Running it again replaces the sandbox.
  `data/` is git-ignored.
- A new setting `data_dir` (default `data`) holds the local state: `state.json`, `jobs.db`, the
  server log. The sandbox server therefore never shares a job queue or a log with the real one.

`.claude/launch.json` gets a second entry, `plaud-dashboard-sandbox`, that starts the server with
`--config data/sandbox/config.json` on port 8378.

### 5.14 Ensemble languages

A setting `ensemble_languages` (default `["it", "en"]`) lists the languages for which choosing
`ensemble` really runs the second model and the arbiter. For a recording whose detected language
is not listed, `ensemble` behaves as turbo, and the job message says so. The proxy baseline (M7)
decides whether `en` stays in the list.

---

## 6. Evaluation plan

### Why

The current yardstick, agreement with Plaud, cannot tell whether Plaud or this system is wrong.
It cannot separate a diarization error from an assignment error, and it hides overlap. A small set
of hand-corrected ground truth fixes the first two and measures overlap where the owner marks it.
It only partly fixes missed speech (see "Bias" below).

### Ground truth the owner produces

Seven excerpts, about 75 minutes of audio in total.

| # | Source | Why |
|---|---|---|
| G1 | 07-23, minutes 0–10 | Italian, 3 speakers, already scored against Plaud |
| G2 | 09-29, minutes 15–25 (contains the "pistone medio" stretch and memos) | Italian, the densest technical vocabulary, marks |
| G3 | 11-10, a 10-minute stretch with the most turn changes | Italian, 2 speakers, the weakest proxy score (89 %) |
| G4 | Jobs & Gates, 62:20–72:20 plus 76:00–80:30 (14.5 min) | English, many short speakers. The first window holds McNamee, Rob Kelly and the other questioners that were merged into one speaker; the second holds Charlie Brenner and the unnamed 79:15 questioner, which Plaud merges (window checked against `of_8a43.plaud.txt`) |
| G5 | New: one of the owner's own meetings, 4 people in a room, with cross-talk | The untested hard case for R1 |
| G6 | New: one real mixed Italian/English meeting | The untested code-switching case |
| G7 | New: one of the owner's own English meetings, 10 min | Italian/English parity. G4 is clean stage audio and cannot be compared fairly with room meetings |

**How to label.** `eval/export.py` writes the baseline system output for the excerpt
(`large-v3-turbo` + pyannote `community-1`, default settings) as one line per phrase:
`[mm:ss.s-mm:ss.s] S2: text`. The owner corrects it in any editor, Obsidian included:
- the words;
- the speaker label of each line, using real names;
- splitting a line where the speaker changes inside it, and adjusting the times;
- adding lines for speech the system missed (an approximate time is enough);
- a `+` after the speaker label wherever two people talk at once.

Correcting is faster than transcribing from scratch. Effort estimate: 5–7 hours for about 75
minutes [unverified: my estimate, typical correction speed is a few times real time]. G5, G6 and
G7 need three recordings the owner does not have yet. **Speaker counts for every recording in the
vault** cost almost nothing and are collected too: the owner types the confirmed count into the
dashboard, which stores it as `true_speakers`. That one number is enough for the count metric on
all recordings, not just the excerpts.

**Bias.** The reference starts from the baseline's words and boundaries. Two consequences follow.
First, the reference leans toward turbo + pyannote: a corrector tends to keep text that is
plausible. Comparisons against the baseline (X2, X4) are therefore conservative. A new model must
beat a reference that slightly favours the old one, so a gain that shows is real, but a small real
gain can be missed. Second, timing is only as good as the owner's corrections. Missed speech that
the owner adds has rough times, and false alarms are counted only where the owner deletes a line.
So missed speech and false alarm are reported as lower bounds. **WER and word attribution error are
the primary metrics**, because they depend on words, not on boundaries.

### Metrics

All metrics are computed by `eval/run.py`. It has no new dependencies: word alignment is a short
edit-distance routine using `difflib`/dynamic programming, and DER comes from `pyannote.metrics`,
which is already installed in `.venv-pyannote` (version 4.2.0, checked).

- **Speaker count error.** |found − true| per recording, on every recording with a known count.
- **Word speaker-attribution error (the main speaker metric).**
  1. Align system words to reference words with edit distance on normalised tokens.
  2. Map system speakers to reference speakers with the same greedy one-to-one matching the current
     scorer uses.
  3. Report the share of matched reference words whose speaker is wrong.

  This is in the spirit of WDER (Shafey et al., Interspeech 2019, arXiv 1907.05337 [unverified]).
  It is reported separately for words inside and outside overlap.
- **Assignment loss.** The same word attribution error, computed twice: once with each reference
  word given the speaker of the raw exclusive turn it falls in, and once with the speaker of the
  final utterance. The difference is the loss caused by `utterances()`, which the current numbers
  cannot isolate.
- **Diarization error, split (secondary).** Missed speech (a lower bound), false alarm (a lower
  bound) and confusion, scored with no collar and then with a 0.25 s collar.
- **WER.** Lowercase, punctuation stripped, numbers left as written (the same rule on both sides).
  Reported per excerpt and per language. The glossary terms' error rate is reported separately,
  because they are what the owner cares about most.
- **Proxy, kept for continuity.** Agreement with Plaud's labels and transcript, so that old and new
  numbers can be compared.

### Pass thresholds

They have two parts.

**Absolute floors (R1):**
- the count is exact on every excerpt source with 4 or fewer speakers;
- word attribution error is 5 % or less on G1–G3, G7 and G4's on-stage voices, and 8 % or less on
  G5 (overlap);
- Italian (G1–G3) and English (G7) attribution are within 2 points of each other. Until G7 exists,
  parity cannot be judged; G4 alone is stage audio and is reported but not used for parity;
- WER on G6 is within 3 points of the mean of G1–G3.

These floors are provisional until M7 measures the baseline. If the baseline already beats one,
the floor tightens to the baseline. If it misses one, the floor stays as a target and the gap
becomes the first experiment.

**Relative rule for any change.** A change is accepted only if:
- it improves its target metric by at least 1 point absolute, averaged over the excerpts it
  targets;
- it worsens no excerpt by more than 1 point;
- it keeps the 72-minute import under 15 minutes on this machine.

With seven excerpts, gains under 1 point are noise.

---

## 7. Build plan

The milestones below are turned into build tickets in `documentation/tickets/WORKFLOW.md`.

Each milestone can be built and checked on its own. "Needs" lists the milestones it depends on.

**M0: Commit the baseline.** Needs: nothing, and the owner's go-ahead (D1).
- Commit the current tree on `rebuild-official-cli`, including the staged deletion of the
  Riffado/Supabase files.
- Add `tests/test_repo.py` (R7, R8).
- Test: `pytest` shows 16 passed.

**M1: Evaluation harness.** Needs M0.
- Create `eval/` with `export.py`, `run.py`, and the metric functions.
- Move the three scoring scripts in from `data/speaker-eval/`, keeping the data where it is.
- Tests: `tests/test_eval.py::test_attribution_error_on_synthetic_words`, `::test_wer_normalisation`,
  `::test_der_split_exclusive_vs_final`.
- Manual check: export G1, which is the owner's starting file for labelling.

**M2: Schema 2, atomic save, state cache, migration.** Needs M0.
- Tests: `tests/test_schema.py::test_v1_migrates_to_v2` (fixtures made from the four vault
  recordings, without words), `::test_save_is_atomic`, `::test_v2_round_trip`,
  `::test_newer_schema_is_read_only`, `tests/test_core.py::test_move_keeps_every_note_and_wikilink`.
- Manual check: run the migration on a copy of the vault and open the four hubs in Obsidian.

**M3: Persistent queue, stages, retries, autostart.** Needs M2.
- Fix the self-blocking failed import.
- Tests: `tests/test_jobs.py` (four tests listed in 5.8) and `tests/test_server.py` for the existing
  controls.
- Manual check: kill the server during a transcription, restart it, and watch the job resume. Then
  reboot and check that the dashboard comes up.

**M4: Speaker data and corrections.** Needs M2.
- The worker saves overlap turns and embeddings.
- Stable ids, names carried across a redo, merge, fixes, ▶ samples, short-speaker badges, overlap
  markers.
- Tests: `tests/test_speakers.py` (four tests in 5.4, including
  `test_retranscribe_keeps_turns_and_names`),
  `::test_overlap_flag_on_phrases`, `tests/test_core.py::test_marks_survive_retranscribe_and_redo`,
  `tests/test_server.py::test_audio_route_serves_range`.
- Manual check: on Jobs & Gates, split Speaker 5 into the three questioners with fixes. Redo
  speakers and confirm that the names and fixes are still there.

**M5: Note provenance and staleness.** Needs M2 and M4.
- Notes index, revisions and change shares, token-free label rewriting on rename and merge,
  out-of-date badge, regenerate through `_write_owned`, glossary in the prompt.
- Tests: `::test_same_blueprint_two_providers_two_notes_both_in_hub`, the five
  `tests/test_notes.py` tests in 5.5, `::test_marks_are_in_the_note_prompt`,
  `::test_blueprint_edit_is_used_without_restart`, `::test_glossary_folder_plus_global_dedup`.

**M6: Providers.** Needs M0.
- `doctor --providers`, Antigravity (`agy`) command and `agy-stream-json` wiring, `arbiter_provider`,
  error classification.
- Tests: `tests/test_llm.py` (four tests), plus
  `::test_injection_fixture_cannot_write_outside_temp`. This is an integration test, skipped when
  the provider's CLI is missing. It runs each installed provider on a transcript fixture that asks
  the model to create a file in the parent folder and to run a command, then asserts that nothing
  outside the provider's temporary folder changed. Transcripts are other people's words, so `agy`
  runs with `--sandbox`, `--disable-slash-commands`, and `--settings` `permissions.deny`.
- Manual check: a Meeting-minutes note from each of Claude, Codex and Antigravity on 07-23.

**M7: Baseline on the proxy (ground truth deferred by the owner, D2).** Needs M1, M4, and a fresh
import of 11-10, which is not in the vault today (the R11 VRAM check needs it).
- Run turbo and ensemble × pyannote on the four vault recordings plus 11-10, scored against Plaud's
  transcript and labels. This includes **the ensemble on English** (Jobs & Gates), which has never
  been measured.
- Speaker counts are scored against `true_speakers` wherever the owner has confirmed one.
- Record peak VRAM and wall time on 11-10 (R11).
- Output: `documentation/EVAL-BASELINE.md`. Every number is labelled "proxy". The absolute floors
  in section 6 wait for D2; until then only the relative rule applies, measured on the proxy.
- Kill rule for the English ensemble: if it does not beat turbo by at least 1 point of word
  disagreement on Jobs & Gates, the dashboard defaults English recordings to turbo.
- When the owner reopens D2, the same scripts run on G1–G7 with no code change.

**M8: Dashboard click-through.** Needs M3, M4, M5.
A scripted checklist, run in the browser pane:
1. import with a chosen model and count;
2. move to a new folder;
3. name speakers;
4. play a sample;
5. merge two speakers;
6. reassign a paragraph;
7. redo with a fixed count (names stay);
8. create notes with two providers;
9. rename a speaker (both notes show the new name, and no provider was called);
10. re-transcribe with the other model, then regenerate one note that shows out of date;
11. accept a "sounds like …" suggestion on a recording with a known voice;
12. check that a new term appears in the folder's automatic glossary after two recordings;
13. kill the server mid-job and restart.

Each step's result is noted in `CHECKPOINT.md`.

**Experiments (after M7; each one ends in "adopt" or "drop" under the relative rule in section 6):**

X2 to X4 need ground truth to be judged properly, so they wait for D2. (X1, a default speaker cap,
was dropped by owner decision D7.)

- **X2: A different-family second or third voice.** Use Qwen3-ASR-1.7B, first checking that it runs
  on Windows within 8 GB.
  - Target: WER on G1–G3 and G6.
  - Kill: it does not install natively on Windows, or the gain is under 1 point, or the 72-minute
    import goes over 15 minutes.
  - Fallback: the current ensemble.
- **X3: Overlap handling.** First measure the share of overlapped speech and the attribution error
  inside overlap on G5.
  - If overlap is under 5 % of speech, or its attribution error is within 3 points of the rest,
    stop: marking is enough.
  - Otherwise, evaluate assigning overlapped phrases from the non-exclusive turns (no new model)
    before considering any separation model.
- **X4: Forced alignment at turn boundaries.** Run it only if M7 shows that more than half of the
  attribution errors fall within 1 s of a speaker change.
  - Candidates: torchaudio `VOXPOPULI_ASR_BASE_10K_IT` (in `.venv-pyannote`), then
    Qwen3-ForcedAligner.
  - Kill: under 1 point of gain.
**M9: Flutter readiness.** Postponed by the owner (D5). Needs M2–M5.
- The `GET /api/recordings/{id}` and note routes.
- `/openapi.json` checked into `documentation/api.json`.
- Test: `tests/test_server.py::test_recording_route_returns_schema_2`.

**M10: Voices across recordings (D3: yes).** Needs M4.
- `_Voices.json`, enrolment on naming, suggestions, leave-one-recording-out threshold (5.4, rule 8).
- Tests: the five `tests/test_voices.py` tests in 5.4.
- Manual check: name the speakers of two recordings that share a person, redo speakers on a third,
  and see the suggestion. It needs at least 3 people named in at least 2 recordings each before any
  suggestion appears; until then the dashboard says how many more are needed.
- Kill: the false-match rate is above 5 % at a threshold that still finds 70 % of people. Fallback:
  enrolment keeps running silently and suggestions stay off.

**M11: Automatic glossary.** Needs M2 and M5 (the notes carry the glossary block).
- The four sources, promotion rules, rejected list and 223-token budget in 5.12.
- Tests: the seven `tests/test_glossary.py` tests in 5.12.
- Measurement: the proxy re-transcription check in 5.12, on the three Italian recordings.

The order that delivers the most in daily use first: M0, M2, M3, M4, M5, M11, M10, M6, then M1
and M7. M8 runs after M5 and again after M11.

---

## 8. Risks and what would change the design

- **Real meetings are harder than the evidence.** All the speaker evidence is 2 or 3 speakers, plus
  one clean stage recording. If the owner's first 4-person room meetings come out wrong even after
  X3, the dashboard's correction tools become the primary path, not the backup. DiariZen and the
  hosted `precision-2` stay out (D6) unless the owner reopens that decision.
- **An automatic glossary can teach a mistake.** A wrong term passed as a hotword can make Whisper
  write it where it was not said. The safeguards: promotion needs 2 recordings; a recording's own
  terms never feed its own transcription; the rejected list; and the proxy check in 5.12, which
  turns the hotword use off if it hurts.
- **Plaud CLI changes.** The wrapper parses text. A layout change breaks the listing silently.
  - Mitigation: `test_parse_plaud_listing` with a captured sample, refreshed on each CLI update, and
    `doctor` checking that the listing parses at least one row whenever the account has recordings.
  - If Plaud adds JSON output to `files`, switch to it.
  - If Plaud blocks the CLI itself, the project has no legal path to the audio and that is the end
    of the automatic import. Manual export from the phone app would be the only route [unverified
    that the free app exports audio].
- **Gated model access.** pyannote `community-1` needs an accepted licence and a token. A cloned
  local copy (supported by 4.0) removes the runtime dependency on Hugging Face.
- **Two CUDA stacks in one environment.** cu12 is used by CTranslate2 and cu13 by onnxruntime-gpu.
  Both work today. A driver or wheel update could break one. `doctor` runs a 2-second GPU smoke test
  of each.
- **Provider limits.** The ensemble makes one arbiter call per 10 minutes of audio (20 windows of
  30 s). Long days could hit subscription limits. The `arbiter_provider` setting and per-stage
  retries contain the damage, because a transcript is never lost to a note failure.
- **Overfitting.** Seven excerpts invite tuning to them. That is why the thresholds in section 6
  require a 1-point gain, and why any threshold (the voice threshold in M10, any future clustering setting) is checked on
  half the data and checked on the other half.
- **Mixed language.** If G6 shows that English passages inside Italian meetings come out
  mistranslated or dropped, the next step is per-paragraph language detection on the VAD segments
  only, measured on G6. Per-segment detection inside Whisper was already measured as harmful.

---

## 9. Decisions for the owner

The owner decided all seven on 2026-11-17. They are recorded here with what each one changes.

**D1. Commit the current build and the deletions: done.** The baseline and this design are
committed on `rebuild-official-cli` (M0).

**D2. Hand-labelled ground truth: deferred.** The owner judged it surplus for now. Consequences:
- M7 measures against the Plaud proxy and the owner's confirmed speaker counts (`true_speakers`);
  every number is labelled "proxy".
- Experiments X2–X4 wait, because a proxy cannot judge gains of about one point.
- The evaluation code (M1) is still built, so the labelled set can be added later with no code
  change. Section 6 stays as the plan for that day.

**D3. Recognise the same person across recordings: yes, if possible.** It is built as suggestions
the owner accepts with one click (5.4, rule 8; milestone M10). The threshold is measured on the
owner's own named speakers, so it needs no extra labelling work.

**D4. Keep notes correct without wasting tokens.** Renames and merges rewrite the speaker labels in
existing notes for free. Small re-transcriptions keep the note. Larger changes mark it out of date,
and it is regenerated only when the owner clicks (5.5).

**D5. The Flutter app: designed, postponed.** Section 5.11 fixes where it plugs in (a second client
of the server, after every pipeline stage). M9 is not built until the owner reopens this. Still
open for that day: which of the four ways it runs.

**D6. No paid hosted engine and no non-commercial weights.** pyannoteAI `precision-2` and DiariZen
stay out (section 10).

**D7. No speaker cap.** pyannote decides the count with no bound. The only override is the exact
count the owner types for a redo. X1 is dropped, and the dashboard has no min/max fields.

**New requirement from the same review: the glossary grows by itself.** Section 5.12 and milestone
M11. The glossary is fed by speaker names, by a short block added to notes the owner already
generates, by the owner's corrections in Obsidian, and by the ensemble's choices. It is ranked to
fit Whisper's 223-token hotword limit.

---

## 10. Deferred and rejected

- **Photos.** Deferred. CLI 0.3.15 has no command that returns an image. Marks carry a
  `picture_link` field, but the values seen are opaque ids, not URLs, and no recording in the vault
  has a photo mark (section 3, fact 9). Photo markers stay in the transcript as 📷 callouts and
  `picture_link` is stored with the mark, so nothing is lost if a later CLI can resolve it. Next
  step, cheap: take one photo during a test recording, then look at that mark's `picture_link`.
  Check again on every `plaud update`.
- **Replacing Whisper turbo.** Rejected for now. No candidate that fits 8 GB on Windows has evidence
  on the owner's audio. Qwen3-ASR is an experiment (X2).
- **Voxtral Mini/Small, Nemotron 3.5 Transcribe, omniASR-LLM-7B.** Rejected: VRAM.
- **Nemotron 3.5 ASR Streaming.** Deferred: the card lists Linux only, and it is a streaming model
  where batch accuracy matters more.
- **Streaming Sortformer.** Rejected: a hard limit of 4 speakers and English-centred training.
- **Nemotron-3-Diarization.** Deferred until its card and licence can be read.
- **DiariZen.** Deferred: non-commercial weights (D6) and a pinned old torch.
- **Speech separation for overlap.** Deferred behind X3's measurement.
- **ctc-forced-aligner.** Rejected: needs ffmpeg; non-commercial default weights.
- **Single-transcript LLM clean-up.** Rejected: measured, with no gain.
- **Tuning pyannote's clustering hyperparameters.** Deferred until there are at least six labelled
  recordings to split into tuning and checking halves.
- **A dedicated job-queue library or service, Docker, a database server.** Rejected: SQLite covers
  one worker (R7, R11).
- **Re-enabling per-segment language detection.** Rejected: measured as harmful. Section 8 has the
  alternative if G6 needs one.
- **Live or streaming transcription during a recording.** Not asked for. Recordings arrive after
  sync.
- **Multi-user access, remote access, accounts.** Out of scope until D5.
