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
# Extra sinks written after the primary `sink`; failed writes retry on later runs.
secondary_sinks = []
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

# Mirror secondary calendars into the target calendar: add "calendar" to `sources` and pick
# calendar IDs from `cuecal mirror calendars`.
# [mirror]
# With the google-calendar sink the target must be "primary" (or mirror.self_email).
# target_calendar = "primary"
# source_calendars = []
# lookahead_days = 14
# self_attendee = true
"""

_TOP_KEYS = {
    "sources",
    "sink",
    "secondary_sinks",
    "poll_interval_seconds",
    "llm",
    "thresholds",
    "secrets",
    "gmail",
    "limits",
    "notify",
    "conference",
    "mirror",
}
_PROVISION_MODES = ("organizer_only", "any_linkless", "off")
_TRANSPARENCIES = ("opaque", "transparent")
_LLM_TIERS = {"regex", "local", "paid"}
_TOKEN_PREFIXES = ("xoxb-", "xoxp-", "ya29.", "1//", "sk-")
GOOGLE_SINK = "google-calendar"


class ConfigError(ValueError):
    """Raised when the config file is missing, unparsable or invalid."""


@dataclass
class GmailConfig:
    query: str = ""
    lookback_days: int = 7
    fetch_limit: int = 100
    latency_budget_seconds: float = 30.0


@dataclass
class ConferenceConfig:
    # provision_for = "off" disables both provisioning and replacement.
    preferred: str = "google_meet"
    replace: list[str] = field(default_factory=list)
    provision_for: str = "off"


@dataclass
class MirrorConfig:
    # Calendar IDs come from `cuecal mirror calendars`; the target is never also a source.
    target_calendar: str = "primary"
    source_calendars: list[str] = field(default_factory=list)
    lookahead_days: int = 14
    include_transparent: bool = False
    transparency: str = "opaque"
    self_attendee: bool = True
    # Target account email; looked up from the calendar list when empty.
    self_email: str = ""


@dataclass
class Config:
    sources: list[str] = field(default_factory=list)
    sink: str = "google-calendar"
    secondary_sinks: list[str] = field(default_factory=list)
    poll_interval_seconds: int = 300
    llm_tiers: list[str] = field(default_factory=lambda: ["regex", "local", "paid"])
    auto_create_threshold: float = 0.85
    pending_threshold: float = 0.5
    secrets: dict[str, str] = field(default_factory=dict)
    gmail: GmailConfig = field(default_factory=GmailConfig)
    fetch_limit: int = 100
    latency_budget_seconds: float = 30.0
    notify_desktop: bool = True
    notify_ntfy_topic: str = ""
    notify_ntfy_server: str = "https://ntfy.sh"
    conference: ConferenceConfig = field(default_factory=ConferenceConfig)
    mirror: MirrorConfig = field(default_factory=MirrorConfig)


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

    secondary = data.get("secondary_sinks", cfg.secondary_sinks)
    if not isinstance(secondary, list) or not all(isinstance(s, str) and s for s in secondary):
        raise ConfigError("secondary_sinks must be a list of non-empty strings")
    if len(set(secondary)) != len(secondary):
        raise ConfigError("secondary_sinks must not repeat a sink")
    if sink in secondary:
        raise ConfigError(f"secondary_sinks must not include the primary sink {sink!r}")
    cfg.secondary_sinks = list(secondary)

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

    gmail_data = _table(
        data, "gmail", {"query", "lookback_days", "fetch_limit", "latency_budget_seconds"}
    )
    query = gmail_data.get("query", cfg.gmail.query)
    if not isinstance(query, str):
        raise ConfigError("gmail.query must be a string")
    lookback = gmail_data.get("lookback_days", cfg.gmail.lookback_days)
    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 1:
        raise ConfigError("gmail.lookback_days must be a positive integer")
    g_fetch_limit = gmail_data.get("fetch_limit", cfg.gmail.fetch_limit)
    if isinstance(g_fetch_limit, bool) or not isinstance(g_fetch_limit, int) or g_fetch_limit < 1:
        raise ConfigError("gmail.fetch_limit must be a positive integer")
    g_latency = gmail_data.get("latency_budget_seconds", cfg.gmail.latency_budget_seconds)
    if isinstance(g_latency, bool) or not isinstance(g_latency, int | float) or g_latency <= 0:
        raise ConfigError("gmail.latency_budget_seconds must be a positive number")
    cfg.gmail = GmailConfig(
        query=query,
        lookback_days=lookback,
        fetch_limit=g_fetch_limit,
        latency_budget_seconds=float(g_latency),
    )

    limits_data = _table(data, "limits", {"fetch_limit", "latency_budget_seconds"})
    fetch_limit = limits_data.get("fetch_limit", cfg.fetch_limit)
    if isinstance(fetch_limit, bool) or not isinstance(fetch_limit, int) or fetch_limit < 1:
        raise ConfigError("limits.fetch_limit must be a positive integer")
    cfg.fetch_limit = fetch_limit
    latency_budget = limits_data.get("latency_budget_seconds", cfg.latency_budget_seconds)
    if (
        isinstance(latency_budget, bool)
        or not isinstance(latency_budget, int | float)
        or latency_budget <= 0
    ):
        raise ConfigError("limits.latency_budget_seconds must be a positive number")
    cfg.latency_budget_seconds = float(latency_budget)

    notify = _table(data, "notify", {"desktop", "ntfy_topic", "ntfy_server"})
    desktop = notify.get("desktop", cfg.notify_desktop)
    if not isinstance(desktop, bool):
        raise ConfigError("notify.desktop must be a boolean")
    cfg.notify_desktop = desktop
    topic = notify.get("ntfy_topic", cfg.notify_ntfy_topic)
    if not isinstance(topic, str):
        raise ConfigError("notify.ntfy_topic must be a string")
    cfg.notify_ntfy_topic = topic.strip()
    server = notify.get("ntfy_server", cfg.notify_ntfy_server)
    if not isinstance(server, str) or not server.startswith(("https://", "http://")):
        raise ConfigError("notify.ntfy_server must be an http(s) URL")
    cfg.notify_ntfy_server = server

    conf = _table(data, "conference", {"preferred", "replace", "provision_for"})
    preferred = conf.get("preferred", cfg.conference.preferred)
    if not isinstance(preferred, str) or not preferred:
        raise ConfigError("conference.preferred must be a non-empty string")
    replace = conf.get("replace", cfg.conference.replace)
    if not isinstance(replace, list) or not all(isinstance(r, str) for r in replace):
        raise ConfigError("conference.replace must be a list of strings")
    provision_for = conf.get("provision_for", cfg.conference.provision_for)
    if provision_for not in _PROVISION_MODES:
        raise ConfigError(f"conference.provision_for must be one of {list(_PROVISION_MODES)}")
    cfg.conference = ConferenceConfig(
        preferred=preferred, replace=list(replace), provision_for=provision_for
    )

    cfg.mirror = _parse_mirror(data)
    _check_mirror_target(cfg)
    return cfg


def _check_mirror_target(cfg: Config) -> None:
    """The Google sink writes to the primary calendar; mirrors must land there too (#10 dedupe)."""
    if GOOGLE_SINK not in (cfg.sink, *cfg.secondary_sinks):
        return
    target = cfg.mirror.target_calendar.lower()
    if target == "primary" or (cfg.mirror.self_email and target == cfg.mirror.self_email.lower()):
        return
    raise ConfigError(
        f"mirror.target_calendar {cfg.mirror.target_calendar!r} must be the primary calendar "
        f"while the {GOOGLE_SINK!r} sink is used: that sink writes to 'primary', and dedupe "
        "between mirrors and invites only looks in one calendar"
    )


def _parse_mirror(data: dict[str, Any]) -> MirrorConfig:
    default = MirrorConfig()
    mirror = _table(
        data,
        "mirror",
        {
            "target_calendar",
            "source_calendars",
            "lookahead_days",
            "include_transparent",
            "transparency",
            "self_attendee",
            "self_email",
        },
    )
    target = mirror.get("target_calendar", default.target_calendar)
    if not isinstance(target, str) or not target:
        raise ConfigError("mirror.target_calendar must be a non-empty string")
    sources = mirror.get("source_calendars", default.source_calendars)
    if not isinstance(sources, list) or not all(isinstance(s, str) and s for s in sources):
        raise ConfigError("mirror.source_calendars must be a list of non-empty calendar IDs")
    if len(set(sources)) != len(sources):
        raise ConfigError("mirror.source_calendars must not repeat a calendar")
    self_email = mirror.get("self_email", default.self_email)
    if not isinstance(self_email, str):
        raise ConfigError("mirror.self_email must be a string")
    self_email = self_email.strip()
    # "primary" is an alias for the account's own calendar, whose ID is the account email.
    target_names = {target.lower()}
    if target == "primary" and self_email:
        target_names.add(self_email.lower())
    if self_email and target.lower() == self_email.lower():
        target_names.add("primary")
    clash = [s for s in sources if s.lower() in target_names]
    if clash:
        raise ConfigError(
            f"mirror.source_calendars must not include the target calendar {clash[0]!r}"
        )
    lookahead = mirror.get("lookahead_days", default.lookahead_days)
    if isinstance(lookahead, bool) or not isinstance(lookahead, int) or lookahead < 1:
        raise ConfigError("mirror.lookahead_days must be a positive integer")
    for key in ("include_transparent", "self_attendee"):
        if not isinstance(mirror.get(key, getattr(default, key)), bool):
            raise ConfigError(f"mirror.{key} must be a boolean")
    transparency = mirror.get("transparency", default.transparency)
    if transparency not in _TRANSPARENCIES:
        raise ConfigError(f"mirror.transparency must be one of {list(_TRANSPARENCIES)}")
    return MirrorConfig(
        target_calendar=target,
        source_calendars=list(sources),
        lookahead_days=lookahead,
        include_transparent=mirror.get("include_transparent", default.include_transparent),
        transparency=transparency,
        self_attendee=mirror.get("self_attendee", default.self_attendee),
        self_email=self_email,
    )


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
