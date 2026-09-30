# Robust unattended launchd service

**Context:** CueCal must run unattended, and a versioned interpreter path breaks on upgrade.

**Decision:** `cuecal service install` writes a launchd agent that runs `cuecal run --once` via `StartInterval` (default 10 min), pointing at the uv tool executable path rather than a versioned interpreter path. A single-instance lock stops overlapping runs. Linux systemd user timer is a follow-up.

**Consequences:** Overlapping invocations exit cleanly on lock contention. Uninstall must leave no residue. `service status` shows last run, last error and counts per source/tier.
