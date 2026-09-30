# SQLite for state, OS keychain for secrets

**Context:** The agent needs durable local state and credentials for several services.

**Decision:** State (cursors, seen IDs, meeting IDs, pending queue) lives in SQLite. Secrets live in the OS keychain via keyring, never in plaintext config.

**Consequences:** Runner persists cursors in `source_cursor`. Tokens for Google, Slack and MCP servers are read from keyring.
