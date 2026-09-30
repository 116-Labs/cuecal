# Nothing user-specific hardcoded; calendar chosen via OAuth picker

**Context:** CueCal is meant as a general-purpose tool under 116-Labs, not a personal script.

**Decision:** The target calendar is chosen through OAuth plus a calendar picker and stored in config. Sources, LLM providers and thresholds are config.

**Consequences:** No account or domain is hardcoded. `cuecal auth google` lists calendars and lets the user pick the target.
