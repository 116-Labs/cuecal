# Bring-your-own Google OAuth client for v1

**Context:** Calendar is a Google sensitive scope. An OAuth app in Testing mode expires refresh tokens after 7 days, and a shared client would need Google verification.

**Decision:** Each user creates a Desktop OAuth client in their own GCP project and sets the consent screen to In production (unverified). The `init` wizard walks them through it. Scopes are limited to `calendar.events` and `calendar.calendarlist.readonly`. The token is stored in keyring.

**Consequences:** No Google verification is needed for v1. Setup takes more user effort. Token refresh must be verified after restart.
