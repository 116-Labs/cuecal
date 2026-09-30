# Eval fixture set before choosing model and threshold

**Context:** The local model size and escalation threshold should not be assumed.

**Decision:** Build 30-50 PII-scrubbed fixtures under `tests/fixtures/eval/`, each with expected `MeetingCandidate` JSON, a fixed received-at timestamp and a recipient timezone so relative dates are deterministic. `cuecal eval` reports per-field accuracy, escalation rate, latency and tokens. Record results for at least two local model sizes before choosing Tier 2 defaults.

**Consequences:** #8 depends on #7. Fixtures also serve as extractor regression tests and are labeled for reschedule/cancel for v2.
