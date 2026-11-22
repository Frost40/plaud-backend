# Workflow: the ticket board

**The source of truth is `documentation/DESIGN.md`.** A ticket says what to build and how to prove it; the design says exactly how it must behave. Where a ticket and the design disagree, the design wins. If the design is wrong, fix the design in the same commit and write why in the ticket's Decisions.

## How to work

1. Read `README.md` (always), this file, and the design once.
2. Take the first ticket on the board with status **Ready**. Read its file, then what its "Read first" names.
3. Build in the order the ticket gives. Write each decision you make as one line in the ticket's **Decisions** box.
4. When every Done box is ticked:
   - set the ticket to **Done** on the board and the tickets it unblocks to **Ready**;
   - commit on the branch `rebuild-official-cli` (one commit per ticket);
   - write a short report for the owner in plain words.
5. If your session ends first, write in the ticket's **Progress log** exactly where you stopped and what comes next. The next agent continues from there.

**Owner:** for each ticket, open a new chat with the agent and paste:
> Read README.md and do the next Ready ticket in documentation/tickets/WORKFLOW.md.

Choose the model first. Each ticket has a **Suggested model** box with three levels: Low (a flash model: Haiku, Luna or Gemini Flash), Medium (Sol or Sonnet) and Hard (Opus or Astra). The "Model ★" column below shows the recommended one.

## Rules for every ticket

- **Where things go.** Program code in `app/`, tests in `tests/`, measurement scripts in `eval/`, helper scripts in `scripts/`, documents in `documentation/`. Keep the project's style: few files, short functions, no new dependency when the standard library or an installed package does the job.
- **One way to run things.** Every Python command uses `.venv\Scripts\python` from the project root. pyannote runs only through `app/pyannote_worker.py`, which `app/speech.py` starts with `.venv-pyannote\Scripts\python`. Never install packages into either environment unless the ticket says so.
- **The owner's vault is protected.** `C:\Users\<user>\Documents\Obsidian Vault\Plaud\` holds the owner's real recordings and notes. No ticket writes there. Real runs go to the sandbox (`data\sandbox\`, design section 5.13), made by `.venv\Scripts\python scripts\make_sandbox.py` (from ticket 01) and served by `.venv\Scripts\python -m app.server --config data\sandbox\config.json` on port 8378. Before ticket 01 exists, nothing runs for real.
- **The owner's dashboard may be running** on port 8377. Never stop it and never send it requests that change anything.
- **Tests never touch** Plaud, a GPU, an AI provider or the internet: they use `tmp_path` folders and fakes. The real thing is run once by hand, as a Done box.
- **Plaud account: read-only.** Only `plaud files`, `plaud file`, `plaud audio`, `plaud transcript`, `plaud me`. Never `plaud login` or `plaud logout`; if the sign-in has expired, tell the owner in one line (ticket 00) and continue with work that needs no download.
- **AI usage costs the owner allowance.** Real runs use the `claude` provider unless the ticket says otherwise, and each ticket states the most calls it may make; count them in the Progress log. The `ensemble` model makes one call per 10 minutes of audio.
- **The GPU fits one job.** Before a GPU run outside the server, check with `GET http://127.0.0.1:8377/api/state` and `:8378/api/state` that no job is `running`. Wait if one is.
- **Decide, don't ask.** Stop only for a missing key or permission, for anything that costs money, and before deleting or overwriting protected data. Checks only a human can do go to `OWNER_CHECKS.md`.

## Common Done checks (every ticket)

- [ ] `.venv\Scripts\python -m pytest tests -q` passes, with no test skipped except those marked as needing a provider CLI that is not installed
- [ ] What the ticket built was run for real once in the sandbox, and the Progress log says what was run and what came out
- [ ] Docs updated: `README.md` for anything the owner sees or runs; `documentation/DESIGN.md` when behaviour had to differ from it (with the reason in Decisions); one dated line in `documentation/CHECKPOINT.md`
- [ ] The owner's vault was not written to (its newest file time is unchanged since the ticket started; write both times in the Progress log)
- [ ] Decisions and Progress log written; board updated

## Board

| # | Ticket | Status | Needs | Model ★ |
|---|---|---|---|---|
| 00 | [Your setup (owner only)](00-owner-setup.md) | Done | none | Low |
| 01 | [Safe ground: sandbox, guards, recording format 2](01-safe-ground.md) | Done | none | Hard |
| 02 | [Imports that never get stuck](02-reliable-imports.md) | Done | 01 | Hard |
| 03 | [Speaker names that survive](03-speaker-names-survive.md) | Done | 01 | Hard |
| 04 | [Fix speakers in the dashboard](04-fix-speakers.md) | Done | 03 | Medium |
| 05 | [Notes that stay correct without wasting tokens](05-notes-stay-correct.md) | Done | 04 | Medium |
| 06 | [Measurements on the Plaud proxy](06-proxy-measurements.md) | Done | 03 | Medium |
| 07 | [A glossary that grows by itself](07-automatic-glossary.md) | Done | 05, 06 | Hard |
| 08 | [Known voices suggested across recordings](08-known-voices.md) | Done | 04 | Medium |
| 09 | [All three AI providers, checked](09-providers.md) | Done | 02 | Medium |
| 10 | [Dashboard redesign, with you](10-dashboard-redesign.md) | Done | 02, 05, 07, 08, 09 | Hard |
| 11 | [Final check and hand-over](11-final-check.md) | Done | 10, 00 (owner sign-off) | Hard |

Statuses:
- **Ready**: start it.
- **Waiting**: its "Needs" are not Done yet.
- **Done**: finished and checked.
- **Owner**: only the owner can do it.

The program already works end to end today. After ticket 02, imports also survive failures and restarts and the server starts with Windows; after ticket 05, everything you do to speakers and notes keeps names and notes correct without spending tokens.

Tickets 02 and 03 need only 01 and do not need each other; 06, 08 and 09 do not need each other either. When ticket 00 part A is not done (Plaud signed out, Antigravity `agy` missing), do not stop: tell the owner in one line and carry on with the parts that need no download or no Antigravity.

Every ticket uses the sandbox copy of the vault; ticket 00 part B tells the owner when to restart the real dashboard so the new code runs on the real vault.

Left out on purpose: the Flutter app (design 5.11, milestone M9, postponed by the owner, D5; ticket 04 already builds the read route it will use); hand-labelled ground truth and the experiments X2 to X4 that need it (D2); photos (Plaud's CLI returns no images, design section 10); any speaker cap (D7); paid or non-commercial speaker engines (D6).

After ticket 11, every milestone of the design except the Flutter app is built, tested and checked in the sandbox, and the dashboard has the new look.
