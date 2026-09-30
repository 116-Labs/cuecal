# Tiered extraction: LLM tokens only when needed

**Context:** The agent runs on the user's machine and most messages are not invites. Paid LLM calls on every message would be costly.

**Decision:** Use four tiers. Tier 0 regex gate, Tier 1 `.ics`/template parsing, Tier 2 local LLM (Ollama, small Gemma), Tier 3 paid model only on Tier 2 validation failure or low confidence, with a per-day spend/token cap. The join URL and meeting ID always come from regex.

**Consequences:** Tier 0 drops about 99% of messages at zero cost. No LLM call is added where a regex or parser works. New extraction paths start at Tier 0/1. Tier 3 must never be called when Tier 2 passes validation, and the spend cap must be enforced (both tested).
