# CueCal

Local-first agent that finds meeting invites buried in chat and email (Gmail, Slack, Zoho, any MCP source) and puts them on your calendar. Deterministic parsing does most of the work; an optional small local model and, only on escalation, a paid LLM fill in what parsing can't.

> **Status: pre-alpha (v0.1.1).** `cuecal run` works end to end with the deterministic extractor (Tiers 0–1): the Gmail, Slack and Zoho (MCP) sources, the Google Calendar sink, the pending queue and the background service have landed. The LLM tiers (2–3) are built and off until configured; the Tier 2 model choice is still open ([#121](https://github.com/116-Labs/cuecal/issues/121)). The interactive Google sign-in is not built yet. See [Status](#status).

## Why

Meeting invites rarely arrive as tidy calendar invitations. A Zoom link shows up in a Slack thread, a time gets agreed in a Zoho Cliq chat, a booking confirmation sits in email. Scheduling tools like Reclaim, Motion and Clockwise work from the calendar you already have; none of them read your messages to find the meetings that never made it there.

CueCal polls your message sources, pulls out the time, timezone, join link and context, and creates the event for you. Anything it isn't sure about waits in an approval queue instead of landing on your calendar silently.

## How it works

```
Sources (pluggable)           Extractor (tiered)                 Sinks (pluggable)
├─ Gmail     (native)         T0  link regex; model planned      ├─ Google Calendar
├─ Slack     (native)    ──►  T1  .ics / known templates    ──►  └─ more via plugins
├─ Zoho Mail (MCP)            T2  local LLM (opt-in)
├─ Zoho Cliq (MCP)            T3  paid LLM, escalation only (opt-in)
└─ any MCP server             └─ confidence and end-time checks → auto-create or pending queue

State: SQLite (cursors, event links, pending queue, near-misses, per-sink delivery status,
       paid-LLM daily usage, per-candidate extraction telemetry)
Secrets: OS keychain via keyring, never in the config file
```

- **Sources.** Gmail and Slack have native, read-only adapters. Every other source goes through one generic MCP client driven by a per-server mapping file, so adding a source means writing a mapping, not code.
- **Tier 0: decide.** Today the link regex is the Tier 0 gate. A local decision model is planned in [#21](https://github.com/116-Labs/cuecal/issues/21): Clef-flash is the primary candidate and Laya the baseline, with the eval in [#47](https://github.com/116-Labs/cuecal/issues/47) deciding between them. Regex extracts the join URL, meeting ID and passcode; those never come from an LLM, and the meeting ID is the dedupe key.
- **Tier 1: parse.** `.ics` / `text/calendar` attachments and known invite templates (Zoom, Google Calendar, Zoho) are parsed deterministically. A candidate is high-confidence only when its start time and timezone are both unambiguous.
- **Tier 2: local LLM (opt-in, `[llm.local]`).** For a regex-only partial or a Tier 1 candidate below high confidence, a local Ollama model fills in only the time, title and attendees, as schema-constrained JSON. Its answer passes a validation gate: the JSON matches the schema, the start is no earlier than the message's receipt minus `start_past_window_hours`, the end is after the start, and the model's confidence is at least `min_confidence`. An unknown timezone falls back to `[llm].timezone`. `keep_alive` (default `30s`) unloads the model between batches. If Ollama cannot be reached or times out, Tier 2 is skipped for the rest of that run.
- **Tier 3: paid LLM (opt-in, `[llm.paid]`).** Anthropic or any OpenAI-compatible server (llama.cpp, LM Studio, OpenRouter). It runs once, only when Tier 2 fails (host down, timeout, bad JSON, gate failure) or is not configured, under a daily token and USD cap kept in the state DB. At a cap, Tier 3 is skipped and you get a log line and a notification. A Tier 3 response counts toward the cap even when its answer is unusable, and one without usable token counts caps the rest of that day. With `api_key_secret` set, `base_url` must be `https://`. A failed Tier 2/3 keeps the Tier 0/1 result and sends it to the pending queue; the run never stops for it.
- **Routing.** `cuecal run` auto-creates a candidate when its confidence clears `thresholds.auto_create` and any end time it carries is after its start; that is also the only test applied after an LLM tier. A candidate without an end time can still be auto-created; the Google Calendar sink gives it a 30-minute duration. Candidates below the confidence threshold, with an end before their start, or whose LLM escalation failed go to the pending queue.
- **Dedupe.** The same meeting often arrives from both chat and email. `cuecal run` skips a meeting ID already linked in the state DB. Before auto-creating an event it also skips a meeting that starts within 15 minutes of a calendar event with a similar title, or that matches a hand-made event's conference meeting ID; a meeting without an end time is searched as 30 minutes long. Candidates headed for the pending queue are never skipped this way. The sinks themselves look up their own match when they create (the Google Calendar sink by its `cuecalMeetingId` marker, the Zoho sink by start time and title) and update it rather than duplicate. If the calendar cannot be queried, the run falls back to the state DB check.

Nothing is tied to one person's setup: accounts, calendars, sources, models and thresholds are all configuration.

## Status

| Area | State |
|---|---|
| Package, CLI, config, keyring secrets, SQLite state, plugin registry | Done ([#2](https://github.com/116-Labs/cuecal/issues/2)) |
| Extractor Tier 0 (link regex) and Tier 1 (`.ics` + templates) | Done ([#6](https://github.com/116-Labs/cuecal/issues/6)) |
| Tier 0 decision model (Clef-flash, with Laya as the baseline) replacing the regex gate | Planned ([#21](https://github.com/116-Labs/cuecal/issues/21), [#47](https://github.com/116-Labs/cuecal/issues/47)) |
| Gmail, Slack and generic MCP (Zoho Mail/Cliq) sources; broadened fetch and the near-miss CLI (`misses`, `missed`) | Done ([#3](https://github.com/116-Labs/cuecal/issues/3), [#4](https://github.com/116-Labs/cuecal/issues/4), [#5](https://github.com/116-Labs/cuecal/issues/5), [#46](https://github.com/116-Labs/cuecal/issues/46)) |
| `cuecal run` pipeline: source → extract → dedupe → route → sink | Done ([#48](https://github.com/116-Labs/cuecal/issues/48)) |
| Google Calendar sink | Done ([#50](https://github.com/116-Labs/cuecal/issues/50)); open bug: a meeting-ID update can move an earlier recurring instance's event ([#65](https://github.com/116-Labs/cuecal/issues/65)) |
| Google sign-in and calendar picker (`cuecal auth google`) | Not built; the command is a stub ([#51](https://github.com/116-Labs/cuecal/issues/51)) |
| Pending queue (`pending`, `approve`, `reject`, `edit`) | Done ([#40](https://github.com/116-Labs/cuecal/issues/40)) |
| Pending notifications (desktop, ntfy) | Done ([#41](https://github.com/116-Labs/cuecal/issues/41)); desktop notifications are macOS only, so on Windows and Linux only ntfy delivers |
| Dedupe | Done: meeting-ID matching and start-time/title and hand-made-event matching run in `cuecal run`; the sinks match by `cuecalMeetingId` marker or start time and title when they create ([#39](https://github.com/116-Labs/cuecal/issues/39), [#124](https://github.com/116-Labs/cuecal/issues/124)) |
| Secondary sinks: fan-out with per-sink retry | Done ([#42](https://github.com/116-Labs/cuecal/issues/42)) |
| Google Meet provisioning and provider replacement | Partial: `cuecal run` and `cuecal approve` add a Meet link to events they create without one when `[conference] provision_for = "any_linkless"`. It never replaces another provider's link there, and skips `organizer_only`, because cuecal is always the organizer of what it creates ([#43](https://github.com/116-Labs/cuecal/issues/43)) |
| Calendar mirroring (secondary calendars into the target) | Done; final manual check open ([#17](https://github.com/116-Labs/cuecal/issues/17)) |
| Zoho Calendar sink (MCP write adapter, one-way sync) | Built; tool names unverified against a live Zoho MCP server ([#44](https://github.com/116-Labs/cuecal/issues/44)) |
| Background service (macOS launchd, Windows Task Scheduler) | Done ([#11](https://github.com/116-Labs/cuecal/issues/11), [#89](https://github.com/116-Labs/cuecal/pull/89)) |
| Eval fixture layout | Done ([#52](https://github.com/116-Labs/cuecal/pull/52)); fixture corpus and `cuecal eval` runner open ([#36](https://github.com/116-Labs/cuecal/issues/36), [#37](https://github.com/116-Labs/cuecal/issues/37)) |
| Extractor Tiers 2–3 (local and paid LLM) | Built, tested against mocked providers only ([#8](https://github.com/116-Labs/cuecal/issues/8)); Tier 2 model choice and eval results open ([#121](https://github.com/116-Labs/cuecal/issues/121)) |

The v1 epic is [#1](https://github.com/116-Labs/cuecal/issues/1). Beyond v1: reschedule and cancellation sync ([#12](https://github.com/116-Labs/cuecal/issues/12)), propagating events to Zoho Calendar ([#20](https://github.com/116-Labs/cuecal/issues/20), [#44](https://github.com/116-Labs/cuecal/issues/44)), and local model hosting on the Windows box ([#78](https://github.com/116-Labs/cuecal/issues/78)). Calendar mirroring and Meet provisioning, also planned as post-v1, have already landed; see the table.

## Quickstart

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

### Install a published release

The `release` branch always points at the newest published [release](https://github.com/116-Labs/cuecal/releases), so one command installs it on macOS, Windows and Linux (it needs `git` on your machine):

```sh
uv tool install git+https://github.com/116-Labs/cuecal@release
```

To upgrade to the newest release:

```sh
uv tool upgrade cuecal
```

Without git, install the wheel attached to a release instead (the URL changes with each version):

```sh
uv tool install https://github.com/116-Labs/cuecal/releases/download/v<version>/cuecal-<version>-py3-none-any.whl
```

Maintainers publish releases from a Mac with `scripts/release.sh` (`--dry-run` builds and smoke-tests without publishing).

### 1. Install as a standalone CLI command (Recommended)

```sh
git clone https://github.com/116-Labs/cuecal.git
cd cuecal
uv tool install --editable .
```

This installs `cuecal` directly onto your `PATH`. You can then run commands directly:

```sh
cuecal init     # writes the default config and creates the state DB
cuecal doctor   # reports config, sink credentials, DB, keyring backend and registered plugins
```

### 2. Or run via `uv run` (Development)

```sh
uv sync
uv run cuecal init
uv run cuecal doctor
```

Working today: `init`, `doctor`, `auth slack`, `run [--once]`, `pending`, `approve`, `reject`, `edit`, `misses`, `missed`, `mirror calendars|prune`, `service install|uninstall|status`, `eval --tier 1|2|3`. Stub until its issue lands: `auth google` (#51). Every command accepts `--dry-run` and `-v/--verbose`; `--dry-run` suppresses side effects only in commands that implement it.

### Background service

`cuecal service install` runs `cuecal run --once` every `poll_interval_seconds`, appending its output to `cuecal.stdout.log` and `cuecal.stderr.log` in the platform log dir:

- **macOS:** a launchd agent (`~/Library/LaunchAgents/com.cuecal.agent.plist`).
- **Windows:** a Task Scheduler task named `CueCal`, run as the installing user only while they are logged on (so it can read their Credential Manager vault), from logon and from install time, rounded up to whole minutes. It launches through `conhost.exe --headless`, so no console window flashes. Install it from a desktop session, not over SSH.

Other platforms exit non-zero with "not supported". `cuecal service status` shows the service state (on Windows also the task's last result and next run) and run statistics, and `cuecal service uninstall` removes it.

### Config and data

| What | Default location | Override |
|---|---|---|
| Config (TOML) | platform config dir, e.g. `~/Library/Application Support/cuecal/config.toml` on macOS | `CUECAL_CONFIG` |
| State DB (SQLite) | platform data dir, e.g. `~/Library/Application Support/cuecal/state.db` on macOS | `CUECAL_DB` |

The config holds only keyring entry *names* under `[secrets]`. CueCal refuses to load a config that contains something that looks like a raw token.

Besides `[secrets]`, the loader also accepts the `[thresholds]` (only `auto_create`; everything below it goes to the pending queue), `[gmail]`, `[limits]`, `[notify]`, `[conference]`, `[mirror]` and `[llm]` tables and rejects unknown keys; `cuecal init` writes a commented starting config. Configs written by v0.1.1 or earlier contain `[llm].tiers` and `thresholds.pending`, which no longer exist: delete both before upgrading. The new `[llm]` keys are documented in the starting config.

`[llm.paid]` names its API key through `api_key_secret`, a key under `[secrets]`; store the key itself in the OS keyring under service `cuecal` with the entry name `[secrets]` gives. `cuecal doctor` and each `cuecal run` check that entry before any extraction; a run without it turns Tier 3 off. Prices (`input_usd_per_mtok`, `output_usd_per_mtok`) are yours to set: there is no built-in price table. Without `[llm].timezone`, CueCal reads the system zone from `TZ` or `/etc/localtime`. When neither names an IANA zone (the case on Windows unless `TZ` is set), every LLM-filled candidate goes to the pending queue with a warning, so set `[llm].timezone` there.

`cuecal eval --tier 2` runs the fixtures through Ollama, with your `[llm.local]` or its defaults (`--model` overrides); `--tier 3` needs `[llm.paid]`. Eval usage never counts against the run's daily cap.

`sink` names the primary sink. `secondary_sinks` lists extra sinks that receive each event only after the primary write succeeds. A failed secondary write never undoes the primary event; it is recorded per sink in the state DB, shown with its error under `cuecal service status`, and retried automatically on the next run while the sink stays listed in `secondary_sinks`. Failures for a sink removed from that list are no longer retried and are marked as such in the status output.

After the first write, each secondary copy follows the primary event one-way. Every run re-reads the primary event of each upcoming meeting. A changed title, start/end or join URL is patched into the copy, and a deleted or cancelled primary event deletes it. A failed read of the primary changes nothing. If the secondary refuses an update as a permission error, the meeting goes to the pending queue with the raw upstream error as the reason. `--dry-run` prints the planned updates and deletes.

#### Zoho Calendar

Add `"zoho-calendar"` to `secondary_sinks` and store a Zoho MCP access token as keyring entry `zoho` (service `cuecal`). The sink writes through the tools named in the shipped mapping `zoho-calendar.toml`, in its `[write]` table. To change tool or field names, copy that file to `mappings/` next to your config. `cuecal doctor` checks that the server exposes the create/update/delete tools and that their input schemas accept the title, time, location and description fields. Copies carry the title, time, join URL and a short description only; attendees are never sent. On the first write, an existing Zoho event that starts within 15 minutes of the meeting and has a similar title is patched instead of creating a second one.

## Plugins

Sources, extractor providers and sinks register through Python entry points:

```toml
[project.entry-points."cuecal.sources"]
my-source = "my_package.source:MySource"
```

The groups are `cuecal.sources`, `cuecal.extractors` and `cuecal.sinks`. `cuecal doctor` lists what is registered and flags plugins that fail to load.

## Development

```sh
uv sync
uv run ruff check .
uv run pytest
```

CI runs both gates on every push and pull request. Commits follow [Conventional Commits](https://www.conventionalcommits.org/), and each pull request lands as a single commit.

## License

CueCal is pre-release and not yet licensed for reuse. The source is visible so the project can be developed in the open, but no license is granted yet: all rights are reserved until the first shareable version ships with an open-source license.

Gaal renders its skills (`.claude/skills/gaal-*`, `.agents/skills/gaal-*`) from its templates when it dispatches a run, so they are not committed here; `gaal skills render` writes them locally, to read or to run one by hand.
