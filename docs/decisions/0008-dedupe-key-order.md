# Dedupe keys applied in a fixed order

**Context:** The same meeting can arrive via Slack and email and must yield one event.

**Decision:** Dedupe by meeting ID first, then the sink extended property `cuecalMeetingId`, then start +/- 15 min with a similar title via `Sink.busy`. Sink create is idempotent via extended-property lookup.

**Consequences:** Regex-derived meeting ID is the primary key. Identical meetings from two sources produce one sink create (tested).
