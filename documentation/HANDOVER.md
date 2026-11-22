# Updating the Plaud dashboard

After updating, close the old dashboard server and start `.venv\Scripts\python -m app.server` from the project folder. Open <http://127.0.0.1:8377>. On its first start with older recordings, the server upgrades their metadata and saves each original beside it as `recording.v1.json`. Open a hub in Obsidian and follow its transcript and note links.

The owner confirmed that the upgraded hub works in Obsidian and the dashboard starts after Windows sign-in. To set up autostart again, run `powershell -ExecutionPolicy Bypass -File scripts\autostart.ps1`. [Setup](SETUP.md)

## What you can do

- Import a recording with your chosen model, follow its progress, and resume an interrupted import. Failed jobs show their error and a Retry button.
- Listen to a speaker's samples, give the voice a name, join two voices, or move a passage to the right person. A redo carries the names and saved corrections forward. Once three people each have examples in two recordings, the dashboard can suggest known names for you to confirm.
- Create several notes for one recording using different blueprints and providers. Renaming a speaker updates existing labels without an AI call. When a note goes out of date, you choose whether to regenerate it. Your hand edits are backed up alongside the regenerated note.
- Search recordings and notes, move a recording and its notes into a topic folder, and keep or reject learned terms in the Glossary tab. Open AI to check which providers are ready. The optional API needs its configured key.

## What the measurements show

Plaud's own transcript and speaker labels served as the comparison. These are **proxy** measurements. Human-labelled accuracy, mixed-language accuracy and Italian/English parity on your own meetings remain open.

| Measurement | Result |
|---|---|
| Word disagreement on three Italian recordings | The ensemble improved on turbo by 4.07–7.33 percentage points. |
| Word disagreement on the English stage recording | Turbo 7.55%, ensemble 7.67%. English uses turbo by default. |
| Speaker counts | Matched Plaud on all three Italian recordings. On the English stage recording the system found nine and Plaud labelled eight. |
| Automatic glossary on the Italian recordings | Term errors fell from 12 to 9. Pooled word disagreement fell from 21.810% to 19.806%. |
| 72-minute import on the RTX 3070 (ticket 11) | 4 min 50 s from clicking Import to completion. The slowest of 146 dashboard requests took 116 ms. Across the whole PC, sampled GPU memory peaked at 2.67 GiB and available system RAM stayed at or above 11.9 GiB. |

See the [measurement tables](EVAL-BASELINE.md) for results by recording and speaker-attribution errors.

## Outstanding checks

Both dashboard walks passed all 13 steps. On the second restart check the CPU fallback finished the interrupted tutorial under a small memory limit and kept the speaker name. The voice check matched all four stage speakers with zero wrong suggestions using the smaller GPU batches. Whisper now prepares long recordings in blocks. The regression test compares the audio features with Whisper’s original calculation.

The final suite passed all 175 tests, including the three installed-provider checks. For the measured import, Whisper turbo used `int8_float16` and pyannote identified two speakers automatically. The job finished without a retry or an AI note. These memory readings include other programs open during that run. [Ticket results](tickets/11-final-check.md#final-verification-on-november-19)

- Dragging a recording onto a folder with the mouse remains a manual follow-up.
- The AI check sends each configured provider a short readiness prompt. Ticket 09 separately checked note generation. In ticket 11 Claude and Codex wrote separate notes from the same tutorial. The optional API has no key configured.
- An earlier Claude arbitration attempt returned no usable answer and the recording kept its Whisper transcript. Later provider checks succeeded. A readiness probe alone cannot establish the quality of a future arbitration. [Owner checks](OWNER_CHECKS.md)
- The phone app, hand-labelled evaluation and experiments that rely on it are deferred. The dashboard preserves photo markers, but the CLI does not supply the images.
