You are the lead architect for a self-hosted replacement of the Plaud subscription. Write one design document, `documentation/DESIGN.md`, for the next version of this project. The current build (branch `rebuild-official-cli`, nothing committed) works end to end and is your baseline evidence. The next version is an evolution of it, not a rewrite from zero, unless your evidence shows a part must be replaced.

<goal>
The owner bought a Plaud Note Pro recorder and does not want Plaud's paid plan. Recordings sync to Plaud's cloud with the free phone app. This project downloads them, transcribes them on the owner's own GPU, separates speakers, places highlights and memos in the transcript, writes notes with whichever AI subscription is active, and stores everything in an Obsidian vault, driven from a local dashboard. The owner's bar: the experience must feel as seamless as Plaud's full ecosystem.
</goal>

<frozen_by_owner>
These are the owner's decisions. Design within them. If you believe one should change, list it under "Decisions for the owner" with your evidence; do not design around it.
1. Speaker count and correct attribution of who said what is the top priority. Transcription accuracy is second. Italian and English must work at the same level, including meetings that mix both.
2. AI providers are swappable: Claude, ChatGPT/Codex, Gemini subscriptions through their command-line tools, plus any external API. Never hardwire one.
3. One recording has many notes. Each note is a (blueprint, provider) pair. All notes of a recording are linked together and reachable from one place.
4. Recordings are grouped in real folders by topic, and the owner moves a recording with all its notes between folders.
5. Obsidian is the store now. A custom Flutter app comes later, so the data must stay app-friendly (today: one `recording.json` per recording next to the Markdown).
6. Everything the owner flags during a recording (button highlights, typed memos) must survive and appear at the right time in the transcript and reach the notes.
7. No Docker. No dependency on Riffado or Supabase (the abandoned first version used both).
8. Plaud is reached only through its official CLI (`@plaud-ai/cli`). Plaud's API blocks direct calls (Cloudflare); do not design a bypass.
9. A local dashboard is the control surface until the app exists: choose the transcription model per recording, see and change the folder, name speakers, redo speakers with a fixed count, create a new note from a blueprint with a chosen provider.
10. Vocabulary depends on the meeting's topic, so glossaries are per folder plus one global list. Blueprints live in the vault as editable Markdown.
11. The owner's meetings have at most about 4 speakers. Hardware: RTX 3070 8 GB, 20 logical CPUs, Windows 10, no ffmpeg installed.
12. The owner rejects findings-only answers. Every proposal must be something that can be built and tested, with the test named.
</frozen_by_owner>

<built_and_measured>
These were the builder's choices. They are revisable, but only on evidence at least as strong as what supports them. Read the code and `documentation/CHECKPOINT.md` for details; the summary below is what the repo's history does not show.

Pipeline today: Plaud CLI -> Ogg/Opus audio + marks -> faster-whisper `large-v3-turbo` (CUDA, glossary passed as hotwords) -> optional `ensemble` (turbo + NVIDIA Parakeet TDT v3 via ONNX, then an LLM picks between them 30 s at a time and may only use words one model produced or glossary terms) -> speaker separation -> phrase-level speaker assignment -> vault files -> blueprint notes. FastAPI server + one HTML file at http://127.0.0.1:8377, one job at a time because the GPU fits one model, polling Plaud every 5 minutes.

Measurements. The yardstick is agreement with Plaud's own transcript and speaker labels. That is a proxy, not ground truth; nobody has hand-labelled anything.
- Transcription, Italian: turbo runs about 28x real time. `large-v3` was slower and not better. Hotwords fix domain terms. Per-segment language detection gave no gain and disturbed Italian, so it is off. The ensemble cut word disagreement with Plaud from 11.9 % to 9.5 % and from 24.9 % to 18.7 % on two clips. LLM clean-up of a single transcript gave no gain; `large-v3` as a third voter gave no gain.
- Transcription, English: 7.5 % word disagreement on one 81-minute recording with turbo. The ensemble has not been run on English.
- Speakers, default engine: pyannote `speaker-diarization-community-1` on the GPU in its own environment (`.venv-pyannote`), default settings, never tuned on these recordings. Three Italian recordings (22, 50, 72 min; 3, 3 and 2 speakers; the owner confirmed the last two counts): right count on all three; 96 %, 96 %, 89 % agreement scored on raw turns; 1.5 to 3 minutes each.
- Speakers, fallback engine: sherpa-onnx on CPU over-split every full recording (8 to 10 "speakers"). A second pass that pools each cluster's audio and merges clusters with cosine similarity >= 0.85 gives 90 %, 96 %, 88 % and the right counts, but the threshold was fitted on those same three recordings and only 0.84 to 0.86 works. It takes 9 to 30 minutes.
- Unseen English test, "Steve Jobs & Bill Gates", 81 min, about 10 real voices (4 on stage, about 6 audience questioners), clean stage audio: imported in 6 min 19 s. Scored on the final transcript (a stricter scorer; the 50-minute Italian recording gets 93.2 % on it): 93.9 % overall, the four main voices 93 to 98 %. The count was wrong: 9 found, three questioners merged into one speaker, and one phantom speaker of 8 seconds.
- Lessons paid for: sherpa-onnx holds Python's GIL for minutes, so speaker work must run in a child process; PyPI's torch wheel is CPU-only on this machine (the CUDA build comes from the cu126 index); a file-name helper that truncates to 80 characters caused an endless loop that looked like a hung AI call; Plaud's listing truncates long titles; CLI output can carry colour codes.
</built_and_measured>

<open_and_untested>
The design must answer each of these, or say why it is deferred.
- Speaker count on harder material: people talking over each other in a real room, 4 or more speakers in the owner's own meetings. What the dashboard does when the automatic count is wrong.
- Redoing speakers renumbers them: names are cleared, and notes written earlier keep the old labels. Merging two speakers by giving them the same name is untested.
- Speakers are anonymous per recording. Recognising the same person across recordings was never discussed with the owner: treat it as a candidate, not a requirement.
- Failed automatic imports are not retried. The job list lives in memory and is lost on restart. The server does not start by itself.
- Photos taken during a recording are not retrievable through Plaud's CLI.
- Codex notes were never produced (usage limit during testing). Gemini's CLI is not installed.
- Re-transcribing does not regenerate existing notes.
- The path to the Flutter app: what the app reads and writes, and what must change in the data layout before then, if anything.
- Nothing is committed; the old Riffado/Supabase files are staged for deletion.
</open_and_untested>

<sources>
Read these before outlining. Treat them as the record; this prompt is the index.
- `README.md`, `documentation/CHECKPOINT.md` (current state, every measurement, known gaps)
- `app/` (about 1,300 lines: `plaud.py`, `speech.py`, `pyannote_worker.py`, `ensemble.py`, `vault.py`, `llm.py`, `pipeline.py`, `server.py`, `dashboard.html`, `config.py`), `tests/`
- `data/speaker-eval/` (git-ignored: Plaud label files, raw-turn baselines, `merge_eval.py`, `pyannote_eval.py`, `score_rec.py`)
- `documentation/transcription-comparison.md` (side-by-side model outputs on the owner's clips)
- The vault: `C:\Users\<user>\Documents\Obsidian Vault\Plaud\` (`_Blueprints\` with `_rules.md`, `_Glossary.md`, four imported recordings under `Inbox\` and `Plaud tutorials\`)
</sources>

<task>
1. Read the sources. Then consult the advisor before you outline.
2. Research the current state of the art for each stage (speech-to-text for Italian and English, speaker separation, overlap handling, speaker identity, transcript correction, note generation, local job handling). Use primary sources: model cards, papers, official docs, release notes. For each candidate state whether it fits 8 GB of VRAM, runs on Windows without ffmpeg, covers Italian and English, and what its licence and access terms are. Mark every claim you could not verify as [unverified]. Do not cite a benchmark number without its source and test set.
3. For each stage choose: keep, change, or replace. A change or replacement needs (a) the evidence, (b) what it is expected to improve and by how much, (c) a measurement plan on the existing evaluation set that would confirm or kill it, (d) the fallback if it fails. "Newer" alone is not a reason.
4. Design the evaluation itself: the current yardstick is a proxy. Say what minimal hand-labelled ground truth the owner should produce (how many minutes, which recordings) and how each metric is computed.
5. Write the document.
</task>

<output_format>
One file, `documentation/DESIGN.md`, in plain English a technical owner can read in one sitting; full sentences, tables only for comparisons. Sections, in this order:
1. Summary: what changes from today and why, in under 200 words.
2. Requirements: the frozen list, restated and numbered, each with its acceptance test.
3. Current system and evidence: what exists, what was measured, with caveats attached to every number.
4. State of the art, per stage: candidates table, verified facts, fit to this hardware.
5. Design: architecture, data layout in the vault (files, `recording.json` schema with versioning), pipeline stages, speaker workflow including corrections, notes and blueprints, providers, dashboard, job queue and failure handling, setup on a new machine.
6. Evaluation plan: datasets, ground truth, metrics, pass thresholds.
7. Build plan: ordered milestones, each small enough to build and verify on its own, each with its test and its dependency on earlier ones.
8. Risks and what would change the design.
9. Decisions for the owner: only choices that are theirs to make, each with options and your recommendation.
10. Deferred and rejected: what you left out and why.
</output_format>

<boundaries>
- Write only `documentation/DESIGN.md`. Change no code, no configuration, nothing in the vault. Make no commits.
- You may run read-only commands, the test suite (`.venv\Scripts\python -m pytest tests -q`) and the scoring scripts on existing files. Do not import recordings, download models, install packages or start GPU jobs longer than two minutes; a design that needs such an experiment lists it in the build plan instead.
- Work in this folder as it is, not in a git worktree: the new code is uncommitted and `data/`, `models/` and both virtual environments are git-ignored.
- If a question is the owner's to decide and blocks the design, ask all such questions in one batch, once, after reading the sources. Otherwise choose a default, state it, and continue.
- Keep the scope to what the owner asked for. Additions go under "Deferred and rejected" unless they serve a frozen requirement.
- Consult the advisor again when the draft is saved and before you declare it done.
</boundaries>

<done_when>
- `documentation/DESIGN.md` exists with all ten sections.
- Every frozen requirement has an acceptance test; every item in the open list is answered or explicitly deferred.
- Every number carries its source and caveat; every keep/change/replace decision carries its evidence and measurement plan.
- Your final message states what you verified, what is marked [unverified], and the decisions waiting for the owner.
</done_when>
