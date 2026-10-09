# CueCal

Local-first agent that finds meeting invites buried in chat and email (Gmail, Slack, Zoho, any MCP source) and puts them on your calendar. Deterministic parsing and a small local model do the work; a paid LLM runs only on escalation.

> **Status: pre-alpha.** The scaffold and the deterministic extractor have landed. Sources, sinks and the background service are still in progress, so `cuecal run` does not do anything yet. See [Status](#status).

## Why

Meeting invites rarely arrive as tidy calendar invitations. A Zoom link shows up in a Slack thread, a time gets agreed in a Zoho Cliq chat, a booking confirmation sits in email. Scheduling tools like Reclaim, Motion and Clockwise work from the calendar you already have; none of them read your messages to find the meetings that never made it there.

CueCal polls your message sources, pulls out the time, timezone, join link and context, and creates the event for you. Anything it isn't sure about waits in an approval queue instead of landing on your calendar silently.

## How it works

```
Sources (pluggable)           Extractor (tiered)                 Sinks (pluggable)
├─ Gmail     (native)         T0  decision model + link regex    ├─ Google Calendar
├─ Slack     (native)    ──►  T1  .ics / known templates    ──►  └─ more via plugins
├─ Zoho Mail (MCP)            T2  local LLM (Ollama)
├─ Zoho Cliq (MCP)            T3  paid LLM, escalation only
└─ any MCP server             └─ validation gate → auto-create or pending queue

State: SQLite (cursors, seen messages, event links, pending queue)
Secrets: OS keychain via keyring, never in the config file
```

- **Sources.** Gmail and Slack have native, read-only adapters. Every other source goes through one generic MCP client driven by a per-server mapping file, so adding a source means writing a mapping, not code.
- **Tier 0: decide.** Today the link regex is the Tier 0 gate, and a small local decision model ([Laya](https://github.com/116-Labs/cuecal/issues/21)) is planned in [#21](https://github.com/116-Labs/cuecal/issues/21). Regex extracts the join URL, meeting ID and passcode; those never come from an LLM, and the meeting ID is the dedupe key.
- **Tier 1: parse.** `.ics` / `text/calendar` attachments and known invite templates (Zoom, Google Calendar, Zoho) are parsed deterministically. A candidate is high-confidence only when its start time and timezone are both unambiguous.
- **Tier 2: local LLM.** A small model on Ollama fills in only what parsing couldn't (time, title, attendees) as strict JSON.
- **Tier 3: paid LLM.** Runs only when Tier 2 fails validation or reports low confidence, under a per-day cap.
- **Routing.** Every candidate passes a validation gate (schema, future start, resolvable timezone, end after start, confidence threshold). High-confidence events are created; the rest go to a pending queue you approve or reject.
- **Dedupe.** The same meeting often arrives from both chat and email. CueCal matches on meeting ID first, then on its own marker stored on the calendar event, then on start time and title.

Nothing is tied to one person's setup: accounts, calendars, sources, models and thresholds are all configuration.

## Status

| Area | State |
|---|---|
| Package, CLI, config, keyring secrets, SQLite state, plugin registry | Done |
| Extractor Tier 0 (link regex) and Tier 1 (`.ics` + templates) | Done |
| Tier 0 decision model (Laya) replacing the regex gate | Planned ([#21](https://github.com/116-Labs/cuecal/issues/21)) |
| Gmail, Slack and generic MCP (Zoho Mail/Cliq) sources | In progress ([#3](https://github.com/116-Labs/cuecal/issues/3), [#4](https://github.com/116-Labs/cuecal/issues/4), [#5](https://github.com/116-Labs/cuecal/issues/5)) |
| Eval fixture set, Tiers 2–3 | In progress ([#7](https://github.com/116-Labs/cuecal/issues/7), [#8](https://github.com/116-Labs/cuecal/issues/8)) |
| Google Calendar sink with OAuth | In progress ([#9](https://github.com/116-Labs/cuecal/issues/9)) |
| Dedupe + pending queue, launchd service | In progress ([#10](https://github.com/116-Labs/cuecal/issues/10), [#11](https://github.com/116-Labs/cuecal/issues/11)) |

The v1 epic is [#1](https://github.com/116-Labs/cuecal/issues/1). Beyond v1: reschedule and cancellation sync ([#12](https://github.com/116-Labs/cuecal/issues/12)), mirroring secondary calendars into the target calendar ([#17](https://github.com/116-Labs/cuecal/issues/17)), and provisioning a preferred conference link and propagating it to Zoho Calendar ([#20](https://github.com/116-Labs/cuecal/issues/20)).

## Quickstart

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

### 1. Install as a standalone CLI command (Recommended)

```sh
git clone https://github.com/116-Labs/cuecal.git
cd cuecal
uv tool install --editable .
```

This installs `cuecal` directly onto your `PATH`. You can then run commands directly:

```sh
cuecal init     # writes the default config and creates the state DB
cuecal doctor   # reports config, DB, keyring backend and registered plugins
```

### 2. Or run via `uv run` (Development)

```sh
uv sync
uv run cuecal init
uv run cuecal doctor
```

Working today: `init`, `doctor`, `auth slack`, `run --once`. Stubs until their issues land: `auth google` (#51), `pending` (#40), `service install|uninstall` (#11). Every command accepts `--dry-run` and `-v/--verbose`.

### Config and data

| What | Default location | Override |
|---|---|---|
| Config (TOML) | platform config dir, e.g. `~/Library/Application Support/cuecal/config.toml` on macOS | `CUECAL_CONFIG` |
| State DB (SQLite) | platform data dir, e.g. `~/Library/Application Support/cuecal/state.db` on macOS | `CUECAL_DB` |

The config holds only keyring entry *names* under `[secrets]`. CueCal refuses to load a config that contains something that looks like a raw token.

`sink` names the primary sink. `secondary_sinks` lists extra sinks that receive each event only after the primary write succeeds. A failed secondary write never undoes the primary event; it is recorded per sink in the state DB, shown with its error under `cuecal service status`, and retried automatically on the next run while the sink stays listed in `secondary_sinks`. Failures for a sink removed from that list are no longer retried and are marked as such in the status output.

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
