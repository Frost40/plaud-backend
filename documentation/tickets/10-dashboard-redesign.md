# 10: Dashboard redesign, with you

**Needs:** 02, 05, 07, 08, 09 · **Size:** L, with the owner present for each choice

**Suggested model** (choose one; ★ = recommended):
- Low (a flash model: Haiku, Luna or Gemini Flash): not enough: this is taste and layout work with the owner.
- Medium (Sol or Sonnet): possible for building, but weaker at proposing clearly different, good-looking options.
- ★ Hard (Opus or Astra): recommended: taste, and every existing control must keep working while the whole page changes.

## You get

A dashboard that is more modern, minimal, better looking and easier to use, in a look you chose from options. Everything it can do today still works the same way.

## Read first

`documentation/DESIGN.md`:
- 5.7 "Dashboard" (what it holds, and the paragraph "Redesign" with its three limits: one file and offline, behaviour unchanged, light/dark and phone width);
- section 2, R9 (the controls that must exist).

## Owner's taste (optional)

Fill in before starting, or leave empty: "<a site or app whose look you like, colours you like or dislike>". Default when empty: a calm, neutral look with one accent colour, plenty of space, and clear type in the system font.

## How this ticket works (it is different from the others)

The rule of this project is "decide, don't ask". **This ticket is the exception, by the owner's choice.** For each part below:

1. Read the files listed for it and look at how it is today (open the sandbox dashboard in the browser pane and take a screenshot).
2. Show the owner **2 to 4 clearly different options**, each with one or two lines and a picture. Make the picture by building the option as a throwaway HTML file under `data\sandbox\mockups\` and taking a screenshot in the browser pane. Say which one you recommend and why, in one line.
3. **Wait for the owner's answer.** Change nothing for that part before the owner picks.
4. Adjust the chosen option until the owner says it is final.
5. Build the final version into `app/dashboard.html`, run the tests, and show the result.
6. Write the final choice in **Decisions**, then go to the next part.

### Part A: overall look

Owner's words: "more modern, minimal, better looking and easier to use"

- Where: the `<style>` block of `app/dashboard.html`.
- Keep: light and dark following the system; system fonts only; no file loaded from the internet.
- Questions to settle with options: colours and accent, type sizes, density (compact or airy), shape of buttons and cards, icons (inline SVG or none).
- Ideas to show (not limits): a neutral grey look with one blue accent; a warm paper-like look; a dark-first look.

### Part B: layout and navigation

Owner's words: "easier to use"

- Where: the page structure in `app/dashboard.html`.
- Keep: every control of R9 and every API call the page makes today. List them first with a search for `post("` and `fetch(` and keep the list in the Progress log.
- Questions to settle with options: list and detail (a recording list on the left, the chosen recording on the right) or cards in folders as today; where jobs and the status line live; how "not imported yet" recordings appear; what a phone shows.
- Ideas to show (not limits): a sidebar of folders; a search box; a quiet job indicator that opens a panel.

### Part C: the speaker view

Owner's words: speaker attribution is the top priority, so this view must be the clearest

- Where: the speaker panel built in ticket 04, the suggestions from ticket 08.
- Keep: samples, merge, moving passages, the real-count field, "check" badges, suggestions with Accept and No.
- Questions to settle with options: speakers as rows or as coloured chips; how a passage is moved (menu, drag, keyboard); how overlaps (⇄) and short speakers stand out.

### Part D: notes, glossary and providers

- Where: the note list, the out-of-date badge and Regenerate (ticket 05), the glossary count (ticket 07), the provider menus and check (ticket 09).
- Keep: every action.
- Questions to settle with options: how a note's state is shown; where "create note" sits; how the glossary is shown and opened.

## Tests

- All existing tests pass unchanged (the redesign changes how things look, not what they do).
- `tests/test_server.py::test_dashboard_calls_every_route`: the served HTML still contains every API path used before the redesign. Write the list in the test, taken from the Progress log of Part B.
- `::test_dashboard_loads_nothing_external`: no `http://` or `https://` URLs in `dashboard.html` other than `obsidian://` links.

## Done when

- [x] Common checks (one exception, owner to decide: `test_llm.py::test_injection_fixture_cannot_write_outside_temp[claude]` fails, see the Progress log)
- [x] Part A chosen by the owner, built, tested, shown
- [x] Part B chosen by the owner, built, tested, shown
- [x] Part C chosen by the owner, built, tested, shown
- [x] Part D chosen by the owner, built, tested, shown
- [x] Each final choice is one line in Decisions
- [x] Screenshots of the final dashboard in light, dark and phone width (the browser pane's mobile preset) are described in the Progress log; the viewport is reset to desktop afterwards
- [x] Every control on the R9 list was clicked once on the sandbox and did what it did before (one line each in the Progress log)
- [x] `data\sandbox\mockups\` deleted, and the sandbox server stopped

## Not in this ticket

New features. Any change to the API or to stored data. The Flutter app (left out on purpose).

## Decisions

- Part A (owner, 2026-11-18): "A+B Warm Studio". Warm paper neutrals with one terracotta accent, which also marks errors (solid badge = error, soft = needs a look, grey = info). Serif titles (Iowan/Charter/Cambria/Georgia), Segoe UI for everything else, rounded 14px cards, one filled ink button per row for the main action. Built into the `<style>` block; the only markup change is an `attn` class on the "out of date" and "check" pills.
- Part B (owner, 2026-11-18): the combined layout in `combined.html`.
  - Top bar: brand, status and a jobs button that opens a panel.
  - Left column: search (scoped to the selection); Library (All recordings, Not imported yet) apart from Folders; folders open to show their recordings; "+ New folder"; drag-and-drop moves.
  - Recording view: title, meta and speaker strip, with a "⚙️ Settings" button opening a side panel (folder, model, Transcribe again, names, count, Redo speakers, speaker details).
  - Tabs: Transcript alone on the left, styled like the note tabs; note tabs stack from the right with "+" and scroll sideways.
  - The Transcript tab shows speakers, timestamps that play the audio, highlights, memos and ⇄ overlaps.
- API exception (owner said yes, 2026-11-18): `GET /api/notes/{id}/{file}` (the shape DESIGN already planned for the Flutter app) returns one indexed note's body (front matter removed), read-only, validated by `notes.entry`. Written into DESIGN 5.7.
- Part C (owner, 2026-11-18): "A, always clickable". No separate speaker panel: speakers are fixed in the Transcript tab. A legend name opens a card (name + Save, Listen, "Same person as… Join" = merge, Undo for joined voices); a passage's name opens "Who says this?" (speakers + "Someone new" = fix; "Moved by you · Undo" = unfix); one question at a time with "skip" covers short voices (name it, or "No, it's <closest>" = merge into closest), voice suggestions (Yes/No) and the people count (Yes, or type the number; "✓ N people" reopens it). Exact-count redo stays in ⚙️ Settings. Naming a short voice counts as keeping it (there is no "keep" action).
- Part D (owner, 2026-11-18): option A, with the glossary as a tab beside Transcript, readable and editable, instead of a line under the folder. Out-of-date note tab gets a dot, and the note shows an "Out of date" bar with Regenerate; "minor" shows as "small transcript changes since, still up to date"; "+" asks "What kind of note?" (choice buttons), "Written by" (ready AI only) and Create note, or "Check AI" when none is ready; the top-bar "AI" chip lists each provider (ready / needs you / not installed) with "Check again". The "+ New folder" button from Part B stays as built.
- API exception 2 (owner asked for an editable glossary, 2026-11-18): `GET /api/glossary/{folder}` and `POST /api/glossary {folder, mine, removed}` (`glossary.view` / `glossary.save`). A save rewrites only the owner term lines (front matter, headings, comments kept) and the rejected list; learned evidence stays. Written into DESIGN 5.7 and README.
- Search loads each recording's detail and notes into the page on the first search (no new route). There's a `ponytail:` note on when a server index is worth it. A new folder lives in the page until a recording is moved into it.

## Progress log

- 2026-11-18: started. Vault newest file at start: 2026-11-17 07:06:15 (`Inbox\2026-06-23 Steve Jobs & Bill Gates…\recording.json`).
- Part A: three looks built in `data\sandbox\mockups\look.html` (A Quiet Graphite, B Paper & Vermilion, C Ink & Mint; `?look=a|b|c&theme=light|dark`), screenshotted in light, dark and phone width. Text contrast was measured from the OKLCH tokens, and every pair is at least 4.5:1. Waiting for the owner to choose. Nothing in `app/` has changed yet.
- Part A, round 2: owner dropped C, liked A and B but found too many colours. Rebuilt A and B with neutrals and one accent: red only for errors (solid badge), speakers as shades of the accent, links and states without colour. Added A+B "Warm Studio" (A's cards and spacing; B's paper, serif titles and ink buttons). Contrast measured again, every pair at least 5.0:1.
- Part A built into `app/dashboard.html`. Sandbox checked in light, dark and phone width (375px, no sideways scroll). pytest: 165 passed, 1 failed: `test_llm.py::test_injection_fixture_cannot_write_outside_temp[claude]`, because the real Claude CLI now leaves its own `scratchpad` and `cache-break-state` folders in temp. That failure is unrelated to the dashboard; the test runs the real CLI twice (2 provider calls).
- Part B: API calls the page makes today, kept by every layout option: GET `/api/state`, `/api/recordings/{id}`, `/api/audio/{id}`; POST `/api/check_providers`, `/api/generate`, `/api/import`, `/api/merge`, `/api/move`, `/api/refresh`, `/api/regenerate`, `/api/respeak`, `/api/retranscribe`, `/api/retry`, `/api/speakers`, `/api/suggestion`, `/api/unmerge`, `/api/fix`, `/api/unfix`. Three layouts in `data\sandbox\mockups\layout.html` (`?v=1|2|3`, `&jobs=1` opens the jobs panel). Waiting for the owner.
- Part B, round 2: owner rejected all three as they were and asked for a mix: search across everything or within one folder; option 3's folder rail, where clicking a folder opens its recordings beneath it; tabs inside a recording, one per note, to read every LLM note; a dedicated Transcript tab showing speakers, highlights and memos. Built as `data\sandbox\mockups\combined.html` (`?tab=transcript|note|stale|manage&q=fase&jobs=1&rail=1`). Checked on desktop, in dark and at phone width. Open question for the owner: reading notes in the page needs a new read-only GET route for note text (the ticket says no API change). The Transcript tab needs no API change: it uses `/api/recordings/{id}` utterances and marks.
- Part B, round 3: owner's changes, built into `combined.html` (`?scope=all|ni|Inbox&many=1&settings=1`):
  - Library (All recordings as one list, Not imported yet) is separate from Folders, which no longer include "not imported".
  - Search moved into the side column and searches whatever is selected.
  - The Transcript tab stands alone on the left. Note tabs stack from the right with "+" at the end and scroll sideways, with a fade when they overflow.
  - "⚙️ Settings" is a button in the recording header that opens a side panel.
  - Checked on desktop, in dark and at phone width.
- Part B, round 3b: owner added creating folders at will and drag-and-drop moves.
  - Mockup: "+ New folder" beside Folders; recordings drag onto any folder, which shows a dashed outline while hovered and a "Moved to …" confirmation after the drop.
  - No API change needed: folders are vault directories, and `/api/move` already creates the target folder. A new empty folder lives in the page until the first recording is dropped in.
  - On a phone, native drag doesn't work with touch, so moving stays in ⚙️ Settings › Folder.
- Part B built into `app/dashboard.html`; the speaker panel code is unchanged (Part C), now opened from ⚙️ Settings.
  - Added `test_dashboard_calls_every_route` and `test_dashboard_loads_nothing_external`, plus note-route checks in `test_note_states_and_queued_regeneration`.
  - pytest: 167 passed, 1 deselected (the real-Claude-CLI injection test, which fails because of the CLI's own temp files; it was not rerun, to save allowance).
  - Sandbox checks: recording opens with real transcript and speaker strip; the note tab renders Meeting minutes; search "pistone" finds 15 matches inside one recording; ⚙️ Settings opens with every control; drag of "How to use Plaud" onto Inbox moved it (move job done), then moved back. Light, dark and 375px phone checked, no sideways scroll.
- Part B fixes after review:
  - Caches drop on every edit and when a recording's job finishes; the open recording redraws only when something it shows changed, so scroll and playback survive refreshes; the search box no longer blocks refreshes.
  - Search highlighting escapes after matching; the speaker filter resets when another recording opens; recording rows are `div role=button` with Enter/Space.
  - Rechecked on the sandbox: scroll held at 3000 px through a refresh; 4 highlights and 2 memos render and "Highlights only" filters to them; clicking a time plays from it; renaming Speaker 1 showed at once in legend and transcript, then reverted; Speakers panel opens from ⚙️ Settings (102 passages); the Import view shows for a not-imported item; "+ New folder" appears in the list.
  - A real mouse drag could not be tested: the browser pane's automated drag fires no `dragstart` at all. A drop driven by drag events moved a recording (move job done) and moved it back. Owner to try one real drag.
  - The jobs popover's Retry is unchanged code, with no failed job in the sandbox to click.
  - pytest after these fixes: 167 passed, 1 deselected.
- Part C: today's speaker panel is a modal with one form row per speaker and 102 passages, each with its own dropdown. Three options in `data\sandbox\mockups\speakers.html` (`?v=1|2|3&theme=dark`), with demo data added so every case shows (short speaker, suggestion, overlaps, a merge, a moved passage): 1 speaker sheet (rows, chip menu per passage, filters); 2 edit inside the Transcript tab (timeline lanes, speaker chips, drag a passage onto a chip); 3 review mode (checklist of what to settle, "to check" passages, number keys). Checked in light, dark and 375px phone, no sideways scroll. Waiting for the owner.
- Part C, round 2: owner found all three too complex and asked where the view lives. Rebuilt as one simple idea inside the Transcript tab (no separate screen), in `speakers.html` (`?v=a|b&open=chip|menu&q=0-3`):
  - Click a speaker in the legend: name + Save, ▶ Listen, "Same person as…" (merge), and Undo for a joined speaker.
  - Click the name on a passage: "Who says this?" with the speakers and "Someone new" (move); a moved passage shows "Undo".
  - One plain question at a time above the transcript: short speaker ("No, it's Speaker 3" = merge into closest), voice suggestion (Yes/No), and the people count (Yes = confirm, or type the real number).
  - A: always clickable; B: clean reading until "✏️ Fix speakers".
  - Checked in light, dark and 375px phone. Waiting for the owner.
- Part C built into `app/dashboard.html` (owner chose A): the speaker dialog, `openSpeakers` and the ⚙️ Settings "Speaker details" row are gone; README and DESIGN 5.7 updated.
  - Sandbox click-through on "09-29 Revisione…" with real clicks: passage menu → "Someone new" created Speaker 4, showed "Moved by you · Undo" and the "talks only 1 second" question; legend card → Listen played 18.98–19.48 s and stopped; "Same person as Speaker 3 · Join" merged it (question gone, card showed "Speaker 4 was joined here · Undo"); Undo unmerged; "Yes, give a name" opened the card with the cursor in the name box, Enter saved "Ospite" and settled the question; count "Yes" saved 4, "✓ 4 people" reopened it, Save 3 stored 3; "skip" hid the question. The voice suggestion question was drawn with made-up data only (no suggestion exists in the sandbox): "Speaker 2 sounds like Alice. Listen / Yes, it's Alice / No".
  - Restored afterwards: names back, fix removed, count cleared (0). The server keeps the empty Speaker 4 created by "Someone new" (it never deletes speakers; the old panel did the same), so join targets list only voices with talk time.
  - Bugs found and fixed while testing: a closed card stayed visible (`display:grid` beat `hidden`); "Yes, give a name" closed its own card (the click reached the outside-click handler); "1 seconds".
  - Light, dark and 375px phone checked, no sideways scroll. pytest: 167 passed, 1 deselected (the real-Claude-CLI test).
  - After review: an edit deep in the transcript flashed the page to the top for a moment (lowest scroll 3 px, then back to 9806). The view now keeps its height until the transcript is redrawn; rechecked moving and undoing passage 61: scroll stayed at 9806 throughout. The short-voice question's "No, it's…" list merged Speaker 4 into Speaker 3 (then undone). 0 clears a confirmed count again, as in the old panel (confirmed 3, then 0 → cleared, question back).
  - Not clickable on the sandbox: "No, it's <closest>" (no voice embeddings in this recording) and the voice suggestion's Yes/No (no suggestion). They call the same `merge` and `suggestion` routes as before.
  - pytest after these fixes: 167 passed, 1 deselected.
- Part D: today a note's state shows as an "out of date" pill on its tab (plus a Regenerate bar inside); "minor" and "current" show only as text; "+" opens a row with two drop-downs (blueprint, provider); the glossary is a count line under an open folder with no way to open it; providers are a text line and "Check providers" in the top bar. Note states in the code: current, minor (kept automatically), out_of_date, plus missing. Two options in `data\sandbox\mockups\notes.html` (`?v=a|b&t=stale|new|ai|gloss`), kept simple after the Part C feedback:
  - A "where you need it": a dot on an out-of-date tab, "Out of date" bar with Regenerate; "+" tab opens "What kind of note?" choices + "Written by" + Create; "📖 Glossary · 5 words ↗" under the open folder opens it in Obsidian; top-bar chip "AI: 1 of 3 ready" opens a list of providers with their state and "Check again".
  - B "fewer places": the "out of date" pill stays on the tab; "✨ New note" button beside ⚙️ Settings opens a short menu (one click creates); the glossary line moves into ⚙️ Settings › Folder with "Open in Obsidian"; the top bar keeps a text line "AI ready: claude" and "↻ Check AI".
  - No API change in either: the glossary opens through an `obsidian://` link to `Plaud/<folder>/Glossary.md`. Checked in light, dark and 375px phone. Waiting for the owner.
- Part D built into `app/dashboard.html` (owner chose A, glossary as a tab):
  - Server: `glossary.view`/`glossary.save` (with `glossary.valid`, now shared with `add_candidates`), `GET /api/glossary/{folder}`, `POST /api/glossary`. Tests: `test_glossary.py::test_dashboard_edit_keeps_headings_and_evidence`, `::test_dashboard_edit_of_folder_without_glossary`, `test_server.py::test_glossary_routes` (bad folders `..` and `_Blueprints`, bad lists, a `·` in a word all refused); `/api/glossary` added to `test_dashboard_calls_every_route`.
  - Sandbox, real clicks on the Inbox glossary: Remove "Ospite" (the name my Part C test had leaked in; it stays removed as cleanup) moved it to Removed; typing "Speckle" showed "Not saved yet" and survived a background refresh; Save stored it. By page clicks: Keep "Speaker 3" moved it to your words; Bring back / Remove "Ospite" round-tripped; clearing the box and Save restored the rest. `Glossary.md` stays in the Obsidian format (automatic marker, "Rejected" list with "- Ospite").
  - Out-of-date dot and bar, and the AI list's three states, checked by changing the page's copy of the state only (nothing saved): no sandbox note is out of date and no provider check has run. "+" card: choice buttons switch; Create stays off and "Check AI" shows while no AI is ready. "Check now" / "Create note" not clicked (AI calls; kept for the final click-through).
  - Light, dark and 375px phone checked, no sideways scroll; on a phone the chip shows "● AI".
  - pytest: 170 passed, 1 deselected (the real-Claude-CLI test).
  - After review, two data-loss gaps fixed:
    - A tab opened before an Obsidian edit overwrote it: confirmed ("Fresnel" added by hand above the marker, then Keep in the open tab removed it). Now `view` returns a version (`rev`, a hash of the file) and `save` refuses with 409 when the file changed; the page says so and reloads the tab. Rechecked: the save was refused and "Fresnel" stayed. Test added in both test files.
    - Unsaved words were wiped by redraws that are not the 3-second poll. The draft now lives in the page and is put back on every redraw of that folder's tab, and closing the page with a draft asks first. Rechecked: the draft survived a forced redraw, a search, and switching to Transcript and back; Save then wrote it.
  - The tab's number is `glossary.counts`, which also counts words for every folder (`_Glossary.md`); hovering it says so. The lists show the folder file only.
  - Sandbox glossary restored from a backup afterwards (only "Ospite" stays removed). pytest: 170 passed, 1 deselected.
- Found in passing (glossary): default speaker names ("Speaker 1", "Speaker 2"…) were learned as glossary words. Fixed at the owner's request (2026-11-18): ⚙️ Settings › Save names sends back the shown default for an unnamed speaker, which was stored as a real name. `pipeline.rename_speakers` now treats a speaker's own default label as no name, and `glossary.add_candidates` never learns a `Speaker N` label (from names or notes). Test: `test_notes.py::test_default_label_is_not_a_name`. The owner's vault had none; the sandbox's three (and the test name "Prof. Test") were removed, and the sandbox recording's names reset to empty.
- Found in passing: the `marks` text in this sandbox recording is double-encoded UTF-8 ("anzichÃ©"). That's a stored-data bug, outside this ticket. Temporary `mockups` entry in `.claude/launch.json` (port 8390), to be removed when the mockups are deleted.
- Owner confirmed Parts C and D as final (2026-11-18: "solve the glossary bug… then do the final checks and commit").
- Final click-through on the sandbox (port 8378; the owner's 8377 was not running: connection refused). Every R9 control and every API call, one line each:
  - Name speakers: ⚙️ Settings › Save names on "07-23 Ottimizzazione…" (three unnamed speakers): 200, names stayed empty, nothing learned (the bug path above). Legend-card names: Part C.
  - Check providers: AI chip › Check now: claude, codex, antigravity OK; api "missing OPENAI_API_KEY"; chip shows "AI: 3 of 4 ready". 3 AI calls.
  - Choose the model: ⚙️ Settings › Transcribe again (large-v3-turbo) on "How to use Plaud" (3m46s): done; both notes went out of date for real, the tab dot, the rail's "note out of date" and the "Out of date" bar showed. GPU.
  - Regenerate (Meeting minutes): done, back to current. 1 Claude call.
  - Create note: "+" › Study notes › claude › Create note: a new "Study notes (claude)" tab. 1 Claude call.
  - Redo speakers with a fixed count: ⚙️ Settings › count 1 › Redo speakers: done, "Narrator" kept. GPU.
  - Change the folder: ⚙️ Settings › Folder › Move to Inbox, then back to Plaud tutorials: both moves done. Drag-and-drop: Part B (event-driven; owner to try one real drag).
  - Import: Not imported yet › "Welcome to Plaud.ai" (4m13s) › Import: downloaded, transcribed, speakers, Meeting minutes written; now in Inbox. GPU + 1 Claude call. It stays in the sandbox.
  - Refresh (Not imported yet): POST `/api/refresh` 200.
  - Merge, unmerge, fix, unfix, speaker count, suggestion: Part C. Glossary read/save: Part D.
  - Not clickable, no case in the sandbox: Retry (no failed job), voice-suggestion Yes/No and "No, it's <closest>" (no suggestion or embeddings). Same routes and code as before.
- Found and fixed during the click-through: the side column scrolled with the page, so opening an item low in a long list left the recording view off-screen above. The rail is now sticky under the top bar with its own scroll on desktop (unchanged on a phone). Rechecked: rail scrolled to the bottom, clicked an item, the view showed at the top.
- Final screenshots ("How to use Plaud", Transcript tab): light: warm paper, terracotta speaker bar, the count question, highlight card; dark: same layout on near-black with peach accents; phone (375 px): one column, "☰ Plaud · ● AI · No jobs running", Settings under the title, tabs scroll sideways, no sideways page scroll; ☰ opens the full-width rail. Viewport reset to desktop afterwards.
- AI calls in the final click-through: 6 (3 provider checks, regenerate, create note, import's automatic note), plus 2 runs of the real-Claude test below. GPU jobs: 3 (transcribe again, redo speakers, import).
- Cleanup: `data\sandbox\mockups\` deleted, `mockups` entry removed from `.claude/launch.json`, sandbox server stopped.
- pytest: 171 passed, 1 deselected. The deselected one, `test_llm.py::test_injection_fixture_cannot_write_outside_temp[claude]`, fails because the Claude CLI now keeps its session state inside `TEMP\claude\` (a per-folder session directory and `cache-break-state-<id>.json`). The test already allows `TEMP\claude` itself but not what is inside. Widening the allowance to the whole folder is a change to a security test, so it waits for the owner (carried to ticket 11). Nothing was written to the project folder in either run.
- Owner's vault: newest file at the end 2026-11-17 07:06:15 (`Inbox\2026-06-23 Steve Jobs & Bill Gates…\recording.json`), unchanged since the start.
- Still for the owner: try one real mouse drag onto a folder; restart the dashboard on 8377 to get the new page.
