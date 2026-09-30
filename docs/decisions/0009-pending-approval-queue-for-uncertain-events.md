# Route uncertain candidates to a pending-approval queue

**Context:** Low-confidence extractions should not silently write to the calendar.

**Decision:** High-confidence candidates (Tier 1, or Tier 2/3 passing validation above threshold) auto-create. Others go to a `pending` table with `cuecal pending`, `approve`, `reject`, `edit`, and a notifier (desktop notification, optional ntfy.sh) showing parsed time, link and source snippet.

**Consequences:** Low-confidence candidates are not written until approved (tested).
