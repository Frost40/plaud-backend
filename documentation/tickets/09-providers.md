# 09: All three AI providers, checked

**Needs:** 02, and part A step 2 of ticket 00 for the real Antigravity (`agy`) run (optional) · **Size:** M

**Suggested model** (choose one; ★ = recommended):
- Low (a flash model: Haiku, Luna or Gemini Flash): not enough: `agy` error messages must be verified, and the injection test is about safety.
- ★ Medium (Sol or Sonnet): recommended: the provider code exists; this adds a check, `agy` error classification, and a safety test.
- Hard (Opus or Astra): fine, not needed unless `agy` behaves very differently from its docs.

## You get

- Claude, Codex (ChatGPT) and Antigravity (`agy`) can each write any note, and the dashboard lists only the ones that answered their last check.
- You choose which subscription does the many small "ensemble" calls, separately from the one used for notes.
- A usage limit or an expired login is recognised by name: the note is retried later, and the transcript is never lost.
- A test proves that what people say in a recording cannot make an AI tool change files on your computer.

## Read first

`documentation/DESIGN.md`:
- 5.6 "Providers";
- section 4.7 (what is verified about Antigravity's `agy` command line and what is not);
- 5.3 (the retry policy that uses the error classes, built in ticket 02);
- section 2, R2.

## The one hard fact

`agy`'s headless I/O and tool-blocking are already verified (see `DESIGN.md` 4.7: `--input-format stream-json --output-format stream-json --sandbox --disable-slash-commands --settings` with `permissions.deny`). What is **not** verified is:
- what `agy` prints on `stderr` / `AGY_ERROR` / `result.error` when the usage limit is hit or the login is expired.

Check `agy --help` / `agy`'s error output when testing `check("antigravity")`. Note that `agy` takes ~40 s per cold call, so `arbiter_provider` should avoid `agy` when Claude or Codex has headroom. If `agy` is not installed or signed in (ticket 00, part A step 2 skipped), keep the documented command, write "Antigravity not available: tested with a fake only" in Decisions, and continue.

## Build (in this order)

1. **`app/config.py`**:
   - keep the `antigravity` command of 5.6;
   - a `check` prompt per provider (default "Reply with exactly: OK");
   - the setting `arbiter_provider` (default: `default_provider`).
2. **`app/llm.py`**:
   - `check(provider)` runs the check prompt and stores the result (`ok`, time, message) in `<data_dir>\providers.json`;
   - `classify(provider, exit_code, text)` returns `"limit"`, `"auth"` or `"other"`. Base it on the exit codes and messages found for each CLI: for Claude and Codex, read their messages in their `--help` and docs, and test with saved strings.
3. **Retry policy**: the error function of ticket 02 uses `llm.classify`. "limit" waits 2 h before retrying, "auth" pauses note jobs for that provider and shows "sign in to <provider> again", "other" follows the normal back-off.
4. **`app/doctor.py --providers`**: runs `check` for every installed provider and prints the results. The dashboard's provider menus list only providers whose last check is `ok`, and a "check providers" button runs it (a queued job).
5. **`ensemble.fuse`** gets its provider from `arbiter_provider`.

## Tests

`tests/test_llm.py`:
- `::test_cli_provider_reads_stdin_and_output_file`: a fake CLI written in Python under `tests/fixtures/`.
- `::test_openai_provider_with_mock_transport`: `httpx.MockTransport`.
- `::test_ensemble_and_notes_use_the_chosen_provider`: no code path names a provider literally.
- `::test_classify_limit_and_auth`: saved messages of each CLI.
- `::test_injection_fixture_cannot_write_outside_temp`: an integration test, skipped for a provider whose CLI is missing. A transcript fixture asks the model to create a file in the parent folder and to run a shell command. Assert that nothing outside the provider's temporary folder changed (compare a listing of the project folder and the user's temp folder before and after).

## Done when

- [x] Common checks
- [x] `.venv\Scripts\python -m app.doctor --providers` prints a result for claude, codex and antigravity (or "not installed"); the Progress log has it
- [x] Real run on the sandbox, at most 6 AI calls in total: the three checks, then one "Meeting minutes" note on 07-23 from Codex and one from Antigravity (`agy`) when installed. Both notes are listed in the hub.
- [x] The injection test ran for real against each installed provider and passed
- [x] Guard check: point the `codex` command to a fake that prints a usage-limit message; a note job is marked "limit" and scheduled 2 h later; restore the setting
- [x] Remove the notes created here from the sandbox, and stop the sandbox server

## Not in this ticket

New provider types beyond command-line tools and OpenAI-compatible APIs. The new look of the provider menus (ticket 10).

## Decisions

- Resolved `arbiter_provider` after `config.json` loads so overriding `default_provider` without setting `arbiter_provider` still tracks `default_provider`, while setting `arbiter_provider` directs `ensemble.fuse` independently.
- Added `--disable-slash-commands` to `claude` alongside `--tools ""` and kept the `agy` command of design 5.6; `agy` (`antigravity`) was available and signed in on this machine.
- Classified provider failures uniformly via `ProviderError` and `llm.classify(provider, exit_code, text)` using patterns observed directly from the installed `claude`, `codex`, and `agy` binaries plus HTTP 401/429 for `openai` providers, without hardwiring provider names in `pipeline.py`, `ensemble.py`, `doctor.py`, or `server.py`.
- Kept `llm.available()` reporting installed providers (preserving `/api/generate` and `/api/regenerate` behaviour and existing tests) while `/api/state` filters `providers` to those whose last check in `<data_dir>/providers.json` is `ok`.
- Separated provider `"auth"` pauses (`sign in to <provider> again` on matching `generate`/`regenerate` and failed `resume` jobs) from Plaud `"auth"` pauses so Plaud polling never unpauses provider-auth jobs and provider checks (`POST /api/check_providers`) unpause only the recovered provider. Usage limits wait 7200 s (2 h) up to 3 automatic retries (`attempts < 3`).
- In `test_injection_fixture_cannot_write_outside_temp`, redirected `TEMP`/`TMP` to an isolated per-test directory so unrelated OS temp noise cannot flake, pruned `.venv`/`.venv-pyannote`/`models`/`data`/`.git` and hashed file contents in `snapshot`, and allowed only empty `claude` / `node-compile-cache` or the test's own empty `TemporaryDirectory` (which `agy`'s child process can briefly lock on Windows) while failing if any file or other directory appears anywhere in the project or temp directory.
- Fixed `pipeline.resume()` to retain `ProviderError` priority (`auth` > `limit` > `other`) when 2+ auto-blueprints fail, `pipeline.error_kind()` to recognize `<provider> limit`/`failed` after blueprint prefixes, `jobs.unpause_provider()` to match exact/prefix without SQL `LIKE` wildcards, `llm.run()` to reject empty OpenAI responses and check tail stderr/stdout, and `_AUTH_RE`/`_LIMIT_RE` to include observed `agy`/`codex`/`claude` strings and multiline 401/429.

## Progress log

- 2026-11-18: Worked in an isolated git worktree (`ticket-09-providers` branched off `5bc94f5` so `rebuild-official-cli` stays untouched for ticket 08). Owner vault newest UTC before: `2026-11-17T06:06:15.855943+00:00` (4 recordings, 26 files).
- `.venv\Scripts\python -m app.doctor --config data/sandbox/config.json --providers` (re-verified 2026-11-18 11:09 local):
  - `claude: ok (OK) [2026-11-18T11:09:46]`
  - `codex: ok (OK) [2026-11-18T11:09:49]`
  - `antigravity: ok (OK) [2026-11-18T11:09:57]`
  - `api: failed (missing OPENAI_API_KEY)`
- Sandbox server run on isolated port `8379` (prior run verified `07-23` `Meeting minutes` with `codex` and `antigravity`, both in hub; review re-verified `/api/state`, fake `codex` usage-limit guard `not_before = updated + 7200.0`, fake auth pause + `/api/check_providers` unpause, and headless Edge DOM render). Sandbox reset cleanly via `scripts/make_sandbox.py` and server stopped.
- `.venv\Scripts\python -m pytest tests -q` (including real `test_injection_fixture_cannot_write_outside_temp` for `claude`, `codex`, `antigravity`): **158 passed, 0 skipped, 1 warning in 79.64s**; `node -c` on `dashboard.html` JS exited 0; `git diff --check` clean.
- Owner vault newest UTC after all checks: `2026-11-17T06:06:15.855943+00:00` (unchanged). Board updated: 09 Done (`10` remains Waiting until `08` is also Done).

- 2026-11-18 post-merge follow-up: provider auth pauses now remove the provider from the dashboard menu and block new generate/regenerate requests until a successful dashboard recheck. The worker holds any note job queued during the transition. Existing paused jobs resume after recheck.
- Live OpenAI-compatible API check: OVHcloud AI Endpoints (`https://oai.endpoints.kepler.ai.cloud.ovh.net/v1`, `gpt-oss-20b`) returned `OK` and wrote a validated Meeting minutes note linked from a temporary hub. The only transcript sent was synthetic. The public endpoint requires omitting the Authorization header. A placeholder bearer value produced a real authentication failure before the successful anonymous run. [OVHcloud AI Endpoints](https://www.ovhcloud.com/en/public-cloud/ai-endpoints/catalog/gpt-oss-20b/).
- 163 offline tests passed. The three subscription CLI integration tests were excluded from this API follow-up.
