# Minimal OAuth scopes and raw REST for source adapters

**Context:** Gmail and Slack adapters need read access only, and full vendor SDKs add weight.

**Decision:** Gmail uses `gmail.readonly` only, sharing the Google OAuth helper with the Calendar sink, with raw `requests` against the REST API beyond auth. Slack uses a user token with history/search/users scopes stored in keyring, preferring `search.messages` with meeting-link terms and falling back to `conversations.history`. Fetches are narrowed server-side where possible and respect rate limits (`Retry-After`).

**Consequences:** Adapters need fixture-based contract tests (cursor advancement, `.ics` parts, link unwrapping, rate-limit backoff).
