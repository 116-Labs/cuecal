"""TOML config: load, validate, and write the default file.

The config holds only secret *references* (keyring entry names), never tokens.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_TOML = """\
# CueCal configuration. Secrets live in the OS keyring; reference them by name below.
sources = []
sink = "google-calendar"
poll_interval_seconds = 300

[llm]
# Ordered extraction tiers; later tiers run only when earlier ones are not confident enough.
tiers = ["regex", "local", "paid"]

[thresholds]
auto_create = 0.85
pending = 0.5

[secrets]
# provider = "keyring-entry-name"
# Only keyring entry names belong here, never tokens. Store secrets with `cuecal auth <provider>`.
"""

_TOP_KEYS = {"sources", "sink", "poll_interval_seconds", "llm", "thresholds", "secrets", "gmail"}
_LLM_TIERS = {"regex", "local", "paid"}
_TOKEN_PREFIXES = ("xoxb-", "xoxp-", "ya29.", "1//", "sk-")


class ConfigError(ValueError):
    """Raised when the config file is missing, unparsable or invalid."""


@dataclass
class GmailConfig:
    query: str = "zoom.us OR meet.google.com OR teams.microsoft.com OR filename:ics"
    lookback_days: int = 7


@dataclass
class Config:
    sources: list[str] = field(default_factory=list)
    sink: str = "google-calendar"
    poll_interval_seconds: int = 300
    llm_tiers: list[str] = field(default_factory=lambda: ["regex", "local", "paid"])
    auto_create_threshold: float = 0.85
    pending_threshold: float = 0.5
    secrets: dict[str, str] = field(default_factory=dict)
    gmail: GmailConfig = field(default_factory=GmailConfig)


def _table(data: dict[str, Any], key: str, allowed: set[str]) -> dict[str, Any]:
    table = data.get(key, {})
    if not isinstance(table, dict):
        raise ConfigError(f"[{key}] must be a table")
    unknown = set(table) - allowed
    if unknown:
        raise ConfigError(f"unknown keys in [{key}]: {', '.join(sorted(unknown))}")
    return table


def parse_config(data: dict[str, Any]) -> Config:
    unknown = set(data) - _TOP_KEYS
    if unknown:
        raise ConfigError(f"unknown config keys: {', '.join(sorted(unknown))}")
    cfg = Config()

    sources = data.get("sources", cfg.sources)
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        raise ConfigError("sources must be a list of strings")
    cfg.sources = list(sources)

    sink = data.get("sink", cfg.sink)
    if not isinstance(sink, str) or not sink:
        raise ConfigError("sink must be a non-empty string")
    cfg.sink = sink

    poll = data.get("poll_interval_seconds", cfg.poll_interval_seconds)
    if isinstance(poll, bool) or not isinstance(poll, int) or poll < 1:
        raise ConfigError("poll_interval_seconds must be a positive integer")
    cfg.poll_interval_seconds = poll

    llm = _table(data, "llm", {"tiers"})
    tiers = llm.get("tiers", cfg.llm_tiers)
    if (
        not isinstance(tiers, list)
        or not tiers
        or not all(isinstance(t, str) for t in tiers)
        or set(tiers) - _LLM_TIERS
    ):
        raise ConfigError(f"llm.tiers must be a non-empty list drawn from {sorted(_LLM_TIERS)}")
    cfg.llm_tiers = list(tiers)

    thresholds = _table(data, "thresholds", {"auto_create", "pending"})
    for key, attr in (("auto_create", "auto_create_threshold"), ("pending", "pending_threshold")):
        value = thresholds.get(key, getattr(cfg, attr))
        if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 1:
            raise ConfigError(f"thresholds.{key} must be a number between 0 and 1")
        setattr(cfg, attr, float(value))
    if cfg.pending_threshold > cfg.auto_create_threshold:
        raise ConfigError("thresholds.pending must not exceed thresholds.auto_create")

    secrets = data.get("secrets", {})
    if not isinstance(secrets, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in secrets.items()
    ):
        raise ConfigError("[secrets] must map provider names to keyring entry names")
    for provider, ref in secrets.items():
        if ref.startswith(_TOKEN_PREFIXES):
            raise ConfigError(
                f"secrets.{provider} looks like a raw token; store it with "
                f"`cuecal auth {provider}` and reference the keyring entry name here"
            )
    cfg.secrets = dict(secrets)

    gmail_data = _table(data, "gmail", {"query", "lookback_days"})
    query = gmail_data.get("query", cfg.gmail.query)
    if not isinstance(query, str):
        raise ConfigError("gmail.query must be a string")
    lookback = gmail_data.get("lookback_days", cfg.gmail.lookback_days)
    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 1:
        raise ConfigError("gmail.lookback_days must be a positive integer")
    cfg.gmail = GmailConfig(query=query, lookback_days=lookback)

    return cfg


def load_config(path: Path) -> Config:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise ConfigError(f"config not found: {path} (run `cuecal init`)") from exc
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc
    return parse_config(data)


def write_default_config(path: Path, *, force: bool = False) -> bool:
    """Write the default config. Returns False if one already exists and force is not set."""
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
    return True
