# Reschedule and cancellation sync deferred to v2

**Context:** Updating by meeting ID is easy, but linking a free-text message like "push to 4?" to its original event needs thread context and is likely a Tier 3 job.

**Decision:** v1 only creates events. v1 Tier 1 captures `METHOD:CANCEL`/`REQUEST` for later use. Reschedule and cancel sync is epic #12, blocked by v1.

**Consequences:** Per-source thread-context fetch must be designed in v2. Cancellation behavior (delete or mark cancelled) will be configurable.
