# Design

## Goal

CueCal is a local-first background agent. It watches message sources (Gmail, Slack, Zoho Mail/Cliq, any MCP server) for meeting invites. It extracts the time, timezone, join link and context, and adds the meeting to the user's calendar. It spends LLM tokens only when deterministic parsing cannot do the job.

Origin: sales-meeting invites arrive scattered across Slack and Zoho messages, so the Zoom link has to be hunted down in chat. Reclaim, Motion and Clockwise schedule around a calendar but never read chat to find meetings.

CueCal is meant to be a general-purpose tool under 116-Labs, not a personal script.

## Architecture

```
Sources (pluggable)         Extractor (tiered)          Sinks (pluggable)
├─ native: Gmail API        regex gate                  ├─ Google Calendar  (v1)
├─ native: Slack API   ──►  → deterministic (.ics/    ──►├─ CalDAV / iCloud  (later)
├─ mcp: Zoho Mail           │   Zoom template)          └─ Outlook / Graph  (later)
├─ mcp: Zoho Cliq           → local LLM (Ollama)
└─ mcp: <any server>        → paid LLM (escalation)
         ▲                          ▲
    state: SQLite (cursors, seen IDs, meeting IDs, pending queue)
    secrets: OS keychain (keyring), never plaintext config
```

### Plugin interfaces

- `Source.fetch_since(cursor) -> (list[Message], next_cursor)`. The runner persists cursors in `source_cursor`.
- `Sink.find_by_meeting_id / create / update / busy`.
- LLM provider interface: Ollama, OpenAI-compatible (llama.cpp server, LM Studio, OpenRouter), Anthropic.

### Sources

- Native adapters for Gmail and Slack.
- One generic MCP-client adapter (official `mcp` Python SDK; stdio and streamable HTTP) driven by a per-server mapping file (TOML/YAML). Mappings declare the list tool and argument template, an optional follow-up fetch tool, JSON-path field mappings into `Message`, and how to derive the next cursor.
- Shipped mappings: `zoho-mail`, `zoho-cliq` (Zoho MCP at mcp.zoho.com; tool names are user-overridable).
- Adding an MCP-backed source should normally mean adding a mapping file, not code.

### Extractor tiers

- **Tier 0, regex gate.** Detects Zoom, Google Meet, Teams and Webex links plus meeting ID and passcode. Messages with no link and no calendar attachment are dropped (about 99% at zero cost). The join URL and meeting ID come from regex, never from an LLM. The meeting ID is the downstream dedupe key.
- **Tier 1, deterministic.** `.ics` / `text/calendar` via `icalendar` (capturing `METHOD:CANCEL`/`REQUEST` for v2) and known templates (Zoom invite text, Google Calendar invite emails, Zoho Bookings/CRM) via explicit patterns plus `dateutil`. Confidence is high only when start time and timezone are both unambiguous; otherwise the partial candidate goes to Tier 2.
- **Tier 2, local LLM.** Default Ollama with a small Gemma model (size chosen from eval results). The prompt carries message text, received-at timestamp, recipient timezone and the partial candidate; the model fills only time, title and attendees. Strict JSON output, short `keep_alive`.
- **Validation gate.** Schema valid, start in the future (or within a small past window), timezone resolvable, end > start, model confidence >= threshold.
- **Tier 3, paid.** Only when Tier 2 fails validation or is low-confidence. Configurable provider/model with a per-day spend/token cap.
- Tier, provider, model, tokens and latency are recorded per candidate for `eval` and logs.

### Sinks

- v1: Google Calendar. CalDAV/iCloud and Outlook/Graph are later.
- Event shape: title, start/end with tz, join URL in `location` (and `conferenceData` where applicable), description with source + permalink + passcode, extended private property `cuecalMeetingId`.
- Create is idempotent: look up by extended property first.

### Dedupe and routing

- Dedupe keys in order: meeting ID, sink extended property, then start +/- 15 min plus similar title via `Sink.busy`.
- High confidence (Tier 1, or Tier 2/3 passing validation above threshold) is auto-created. Everything else goes to a `pending` table, managed with `cuecal pending`, `approve`, `reject`, `edit`.
- Notifier interface for pending items; v1 is desktop notification (macOS `osascript` / `terminal-notifier`) and optional ntfy.sh.

### Service

`cuecal service install|uninstall|status` manages a launchd agent that runs `cuecal run --once` on `StartInterval` (default 10 min). A single-instance lock prevents overlapping runs. Linux systemd user timer is a follow-up.

## Constraints

- Runs on the user's machine. Do not add an LLM call where a regex or parser works; every new extraction path starts at Tier 0/1.
- Nothing user-specific hardcoded: calendar target via OAuth + picker; sources, LLM providers and thresholds are config.
- Secrets in the OS keychain (keyring), never plaintext config.
- Low RAM: target machines may have 16 GB shared with other workloads.
- Fixtures must contain no real PII.

## v1 scope and sequencing

Epic #1. Sub-issues: #2 scaffold; #3 Gmail; #4 Slack; #5 generic MCP + Zoho mappings; #6 extractor tiers 0-1; #7 eval fixtures; #8 extractor tiers 2-3; #9 Google Calendar sink; #10 dedupe + pending queue; #11 launchd service. Dependencies: #3-#6 and #9 depend on #2; #7 on #6; #8 on #6 and #7; #10 on #8 and #9; #11 on #10. After #2, three tracks run in parallel: sources (#3-#5), extractor (#6 -> #7 -> #8), sink (#9). Issues are in the backlog with no milestone.

## v2 (#12, blocked by v1)

Reschedule and cancellation sync: update the existing event keyed on meeting ID, and delete or mark cancelled (configurable). Free-text reschedules without a meeting ID need thread context and are likely a Tier 3 task.

## Related work

No open-source project combines any-source ingestion, local-first tiered extraction, meeting-ID dedupe, an approval queue and pluggable sinks. Closest are aayushch/laya (borrow approval-card UX and LiteLLM routing) and elie222/inbox-zero (do not fork). jnstockley/email-to-calendar is GPL-3.0, so use it only as a CalDAV reference, not for code. Reuse libraries: `icalendar`, `dateparser`, `talon`, `mail-parser`, `instructor`/`outlines`/Ollama JSON-schema output, the official MCP SDK, `caldav`.
