# MCP mappings need contract tests and must fail loudly

**Context:** MCP tool output schemas are not standardized and can change silently. Zoho lets users rename tools.

**Decision:** Every shipped mapping gets a contract test against a recorded tool response. The adapter must fail loudly, not return zero messages, when mapped fields are missing.

**Consequences:** Mapping validation errors surface in both `doctor` and the runner. The generic adapter is tested against a local stub MCP server over stdio.
