# 00: Your setup (owner only)

**Needs:** none · **Size:** 5 minutes now, about 10 minutes later

**Suggested model** (choose one; ★ = recommended):
- ★ Low (a flash model: Haiku, Luna or Gemini Flash): enough. An agent is only needed for the check at the end.
- Medium (Sol or Sonnet): not needed.
- Hard (Opus or Astra): not needed.

## Why

Only you can sign in to Plaud and to an AI subscription, and only you should restart your own dashboard and make it start with Windows. Tickets 02, 06 and 09 need a working Plaud sign-in; ticket 09 tests Antigravity (`agy`) if you are signed in. Tickets 01, 03, 04, 05, 07, 08 and 10 can start without anything from you. Nothing here costs money.

## Part A: do it now (5 minutes)

### 1. Plaud still signed in (for tickets 02, 06 and 09)

1. Open **PowerShell**.
2. Type `plaud me` and press Enter.
3. If it shows your account, you are done. If it says `AUTH_FAILED` or asks you to sign in, type `plaud login` and finish the sign-in in the browser page that opens.

### 2. Antigravity command-line tool (optional, for ticket 09)

`agy` replaces the deprecated `@google/gemini-cli` (which no longer accepts personal Google AI Pro logins) and uses your existing Antigravity / Google AI Pro plan directly. Skip this if you do not use Antigravity; ticket 09 then tests it with a fake only.

1. In **PowerShell**, type `agy models` and press Enter.
2. If it lists your models (for example `gemini-4-hydrogen-medium`), you are already signed in. If it asks you to log in, complete the browser sign-in with your Google AI Pro account.

### 3. Tell the agent

Say: "Ticket 00 part A done." The agent runs `plaud me` and `agy models` (or `agy --help`), and reads only whether they succeed, never your account details.

## Part B: later, when a ticket asks you

| When | What you do | Time |
|---|---|---|
| After ticket 01 is Done | Close your dashboard's window or press Ctrl+C where it runs, then start it again with `.venv\Scripts\python -m app.server` from the project folder. On start it converts your four recordings to the new format once and keeps each old file beside it as `recording.v1.json`. Open one hub note in Obsidian to see it still looks right. | 3 minutes |
| After ticket 02 is Done | In **PowerShell**, in the project folder, run `powershell -ExecutionPolicy Bypass -File scripts\autostart.ps1`. Sign out of Windows and back in, then open `http://127.0.0.1:8377`: the dashboard should be there without you starting it. | 5 minutes |
| After each later ticket | Restart the dashboard as above (or sign out and in once autostart exists), so you use the newest version. | 1 minute |
| During ticket 10 | Be at the computer: the agent shows you options for the new look and waits for your choice. | 30–60 minutes |

## Optional, any time

Take one photo with the Plaud app during a short test recording and let it sync. A later project can then see what Plaud stores for photos (the current tickets do not need it).

## Done when

Part A
- [x] `plaud me` succeeds
- [x] `agy models` succeeds, or you said you skip Antigravity

Part B
- [x] Dashboard restarted after ticket 01, and one hub note checked in Obsidian
- [x] Autostart registered after ticket 02, and the dashboard came up after signing in again
- [x] Present for ticket 10 (the [dashboard review log](10-dashboard-redesign.md#progress-log) records the owner's choices for the speaker controls and glossary)

## Decisions

## Progress log
- 2026-11-17: Part A verified (`plaud me` exit 0, `agy models` exit 0).
- 2026-11-19. The owner confirmed that the upgraded Obsidian hub works and the dashboard starts after Windows sign-in.
