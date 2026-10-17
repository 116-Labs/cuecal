# AGENTS.md

Instructions for coding agents working on cuecal. `CLAUDE.md` imports it.

## What cuecal is

A local-first agent that finds meeting invites buried in chat and email (Gmail, Slack, any MCP
source such as Zoho) and puts them on the user's calendar. It is a general-purpose tool for anyone
who runs it, not one person's script. It must never: write an uncertain event to a calendar
silently (low confidence goes to the pending queue); hardcode an account, domain or calendar; keep
a secret anywhere but the OS keychain; or spend LLM tokens where a regex or parser would do. The
join URL and meeting ID always come from regex, never from a model.

## Commands

Set up the environment first:

```bash
uv sync --locked
```

The gates every change passes, in order, as `.gaal/project.yml` lists them:

```bash
uv run ruff check .
uv run pytest
```

## Architecture map

| Path | What lives there |
|---|---|
| `src/cuecal/cli.py` | CLI entry point and the `cuecal run` pipeline: source → extract → dedupe → route → sink |
| `src/cuecal/sources/` | Native Gmail and Slack adapters; `mcp.py` is the one generic MCP adapter, driven by per-server files in `mappings/` |
| `src/cuecal/extract/` | Tier 0 (link regex gate) and Tier 1 (`.ics` and known templates); Tiers 2–3 (LLM) are not built |
| `src/cuecal/sinks/` | Sink protocol (`base.py`), Google Calendar sink, secondary-sink fan-out with retry |
| `src/cuecal/` (rest) | Config, keyring secrets, SQLite state (`db.py`), plugin registry, pending notifier, launchd/Task Scheduler service, run lock |
| `src/cuecal/eval/` | Eval fixture schema and the `cuecal eval` runner (`runner.py`) |
| `scripts/` | `release.sh` (publish a release) and the `block_commit.sh` hook |
| `tests/` | pytest suite, one `test_<module>.py` per module; fixtures and a stub MCP server |

## Code conventions

Comments:

- Comment only what the code cannot say: why a choice was made, an invariant, a non-obvious
  constraint, an issue reference (`#329`). Never what the code does.
- At most 2 lines per comment; 3 for the doc of an exported API.
- No history in comments ("was X, now Y", "added for …"); that belongs in the commit and PR.
- Prefer a clear name or a smaller function over a comment explaining a block.
- A change that makes a comment stale fixes or deletes it in the same commit.
- This overrides any instruction to match the surrounding code's comment density.

Other conventions:

- Ruff with line length 100 and rules `E`, `F`, `I`, `UP`, `B`; `from __future__ import annotations`.
- Each module raises its own named exception (`ConfigError`, `MCPError`, `SlackAPIError`, …).
  A broken MCP mapping raises; it never returns zero messages.
- Sources and sinks are plugins behind `registry.py`. A new MCP source is a mapping file, not code.
- Sources call REST with raw `requests` and read-only, minimal scopes; no vendor SDKs.
- Everything user-specific is configuration. Design decisions (ADRs 0001–0014) live in the
  maintainers' notes; when a change contradicts one, say so in the PR.

## Testing

- `uv run pytest` runs the tests; every gate above passes before a commit.
- A new behaviour gets a test; a test states what it guards in its name, not in a comment.

Tests live in `tests/`, recorded fixtures in `tests/fixtures/` (`calendar`, `eval`, `slack`).
MCP sources run against the local stub server `tests/stub_mcp_server.py` over stdio, not a mock.
HTTP and keyring are monkeypatched; no test reaches the network or a real keychain.
Fixtures are synthetic and PII-free: this repo is public.

## Don'ts

- Never bypass git hooks (`--no-verify`, `core.hooksPath`).
- Never commit secrets, credentials or personal data.
- Commit nothing under `.claude/skills/gaal-*` or `.agents/skills/gaal-*`: gaal renders them
  when it dispatches a run, and they are git-ignored.
- An AGENTS.md or architecture doc a change makes stale is updated in the same commit.
