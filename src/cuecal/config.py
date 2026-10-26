"""TOML config: load, validate, and write the default file.

The config holds only secret *references* (keyring entry names), never tokens.
"""

from __future__ import annotations

import json
import math
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_CONFIG_TOML = """\
# CueCal configuration. Secrets live in the OS keyring; reference them by name below.
sources = []
sink = "google-calendar"
# Extra sinks written after the primary `sink`; failed writes retry on later runs. Each copy then
# follows the primary event one-way (e.g. "zoho-calendar"; check its tools with `cuecal doctor`).
secondary_sinks = []
poll_interval_seconds = 300

[thresholds]
# Candidates at or above this confidence are created; the rest go to `cuecal pending`.
auto_create = 0.85

[secrets]
# provider = "keyring-entry-name"
# Only keyring entry names belong here, never tokens. Store secrets with `cuecal auth <provider>`.

# LLM tiers are off until configured: Tier 2 runs only with [llm.local], Tier 3 only with
# [llm.paid]. They fill time, title and attendees for partial candidates; never the join link.
# [llm]
# min_confidence = 0.7            # Tier 2 results below this escalate to Tier 3
# start_past_window_hours = 24    # reject starts this long before the message was received
# timezone = "Europe/London"      # recipient IANA zone; default is the system zone
#                                 # (TZ or /etc/localtime); with none, LLM results go to pending
#
# [llm.local]
# provider = "ollama"
# host = "http://localhost:11434"
# model = "gemma3:1b"             # provisional; the model choice is open in #121
# keep_alive = "30s"              # unloads the model between batches
# timeout_seconds = 60
#
# [llm.paid]
# provider = "anthropic"          # or "openai" for any OpenAI-compatible server
# model = ""
# base_url = ""                   # optional; required for a non-OpenAI "openai" server
#                                 # (https whenever api_key_secret is set)
# api_key_secret = "anthropic"    # a key under [secrets], never the API key itself
# daily_token_cap = 200000
# daily_usd_cap = 1.0
# input_usd_per_mtok = 0.0        # prices are yours to set; there is no built-in table
# output_usd_per_mtok = 0.0

# Tier 0 decision model (#21), planned: this table is parsed but not yet used by `cuecal run`.
# Extraction still uses the regex gate. Thresholds are provisional until the #47 eval.
# [tier0]
# host = "http://localhost:8080"
# high = 0.8                      # new_invite at or above this continues to Tier 1/2
# low = 0.3                       # any top answer below this is dropped as a near miss
# timeout_seconds = 10
# retries = 1                     # extra tries before Tier0Unavailable
# serialize = true                # one request at a time per host

# Mirror secondary calendars into the target calendar: add "calendar" to `sources` and pick
# calendar IDs from `cuecal mirror calendars`.
# [mirror]
# The calendar the google-calendar sink and mirrors write to; `cuecal auth google` sets it.
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
    "thresholds",
    "secrets",
    "gmail",
    "limits",
    "notify",
    "conference",
    "mirror",
    "llm",
    "tier0",
}
_PAID_PROVIDERS = ("anthropic", "openai")
_PROVISION_MODES = ("organizer_only", "any_linkless", "off")
_TRANSPARENCIES = ("opaque", "transparent")
_TOKEN_PREFIXES = ("xoxb-", "xoxp-", "ya29.", "1//", "sk-")
_TABLE_HEADER = re.compile(r"^\s*\[\s*([^\]]+?)\s*\]\s*(#.*)?$")
_TARGET_KEY = re.compile(r"^\s*target_calendar\s*=")


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
class LocalLLMConfig:
    provider: str = "ollama"
    host: str = "http://localhost:11434"
    model: str = "gemma3:1b"
    keep_alive: str = "30s"
    timeout_seconds: float = 60.0


@dataclass
class PaidLLMConfig:
    provider: str
    model: str
    daily_token_cap: int
    daily_usd_cap: float
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    base_url: str = ""
    api_key_secret: str = ""


@dataclass
class LLMConfig:
    min_confidence: float = 0.7
    start_past_window_hours: float = 24.0
    # Empty means the system zone, resolved when a prompt is built.
    timezone: str = ""
    local: LocalLLMConfig | None = None
    paid: PaidLLMConfig | None = None


@dataclass
class Tier0Config:
    host: str = "http://localhost:8080"
    high: float = 0.8
    low: float = 0.3
    timeout_seconds: float = 10.0
    retries: int = 1
    serialize: bool = True


@dataclass
class Config:
    sources: list[str] = field(default_factory=list)
    sink: str = "google-calendar"
    secondary_sinks: list[str] = field(default_factory=list)
    poll_interval_seconds: int = 300
    auto_create_threshold: float = 0.85
    secrets: dict[str, str] = field(default_factory=dict)
    gmail: GmailConfig = field(default_factory=GmailConfig)
    fetch_limit: int = 100
    latency_budget_seconds: float = 30.0
    notify_desktop: bool = True
    notify_ntfy_topic: str = ""
    notify_ntfy_server: str = "https://ntfy.sh"
    conference: ConferenceConfig = field(default_factory=ConferenceConfig)
    mirror: MirrorConfig = field(default_factory=MirrorConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    tier0: Tier0Config | None = None


def _table(
    data: dict[str, Any], key: str, allowed: set[str], label: str | None = None
) -> dict[str, Any]:
    label = label or key
    table = data.get(key, {})
    if not isinstance(table, dict):
        raise ConfigError(f"[{label}] must be a table")
    unknown = set(table) - allowed
    if unknown:
        raise ConfigError(f"unknown keys in [{label}]: {', '.join(sorted(unknown))}")
    return table


def _reject_removed_settings(data: dict[str, Any]) -> None:
    removed = []
    llm = data.get("llm")
    if isinstance(llm, dict) and "tiers" in llm:
        removed.append("[llm].tiers")
    thresholds = data.get("thresholds")
    if isinstance(thresholds, dict) and "pending" in thresholds:
        removed.append("thresholds.pending")
    if removed:
        raise ConfigError(
            f"{' and '.join(removed)} {'was' if len(removed) == 1 else 'were'} removed; "
            "delete them from your config"
        )


def parse_config(data: dict[str, Any]) -> Config:
    _reject_removed_settings(data)
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

    thresholds = _table(data, "thresholds", {"auto_create"})
    auto_create = thresholds.get("auto_create", cfg.auto_create_threshold)
    if (
        isinstance(auto_create, bool)
        or not isinstance(auto_create, int | float)
        or not 0 <= auto_create <= 1
    ):
        raise ConfigError("thresholds.auto_create must be a number between 0 and 1")
    cfg.auto_create_threshold = float(auto_create)

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
    cfg.llm = _parse_llm(data, cfg.secrets)
    cfg.tier0 = _parse_tier0(data) if "tier0" in data else None
    return cfg


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float)


def _positive(table: dict[str, Any], key: str, name: str, default: Any = None) -> float:
    value = table.get(key, default)
    if not _is_number(value) or value <= 0:
        raise ConfigError(f"{name}.{key} must be a positive number")
    return value


def _non_negative(table: dict[str, Any], key: str, name: str) -> float:
    value = table.get(key)
    if not _is_number(value) or value < 0:
        raise ConfigError(f"{name}.{key} must be a number of at least 0")
    return float(value)


def _string(table: dict[str, Any], key: str, name: str, default: str) -> str:
    value = table.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"{name}.{key} must be a string")
    return value.strip()


def _valid_zone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return True


def _parse_llm(data: dict[str, Any], secrets: dict[str, str]) -> LLMConfig:
    default = LLMConfig()
    llm = _table(
        data, "llm", {"min_confidence", "start_past_window_hours", "timezone", "local", "paid"}
    )
    min_conf = llm.get("min_confidence", default.min_confidence)
    if not _is_number(min_conf) or not 0 <= min_conf <= 1:
        raise ConfigError("llm.min_confidence must be a number between 0 and 1")
    window = _positive(llm, "start_past_window_hours", "llm", default.start_past_window_hours)
    timezone = _string(llm, "timezone", "llm", default.timezone)
    if timezone and not _valid_zone(timezone):
        raise ConfigError(f"llm.timezone {timezone!r} is not an IANA timezone name")
    return LLMConfig(
        min_confidence=float(min_conf),
        start_past_window_hours=float(window),
        timezone=timezone,
        local=_parse_llm_local(llm) if "local" in llm else None,
        paid=_parse_llm_paid(llm, secrets) if "paid" in llm else None,
    )


def _parse_llm_local(llm: dict[str, Any]) -> LocalLLMConfig:
    default = LocalLLMConfig()
    local = _table(
        llm, "local", {"provider", "host", "model", "keep_alive", "timeout_seconds"}, "llm.local"
    )
    provider = local.get("provider", default.provider)
    if provider != "ollama":
        raise ConfigError('llm.local.provider must be "ollama"')
    host = _string(local, "host", "llm.local", default.host)
    if not host.startswith(("https://", "http://")):
        raise ConfigError("llm.local.host must be an http(s) URL")
    model = _string(local, "model", "llm.local", default.model)
    if not model:
        raise ConfigError("llm.local.model must be a non-empty string")
    keep_alive = _string(local, "keep_alive", "llm.local", default.keep_alive)
    if not keep_alive:
        raise ConfigError("llm.local.keep_alive must be a non-empty duration such as \"30s\"")
    timeout = _positive(local, "timeout_seconds", "llm.local", default.timeout_seconds)
    return LocalLLMConfig(
        provider=provider,
        host=host.rstrip("/"),
        model=model,
        keep_alive=keep_alive,
        timeout_seconds=float(timeout),
    )


def _parse_llm_paid(llm: dict[str, Any], secrets: dict[str, str]) -> PaidLLMConfig:
    paid = _table(
        llm,
        "paid",
        {
            "provider",
            "model",
            "base_url",
            "api_key_secret",
            "daily_token_cap",
            "daily_usd_cap",
            "input_usd_per_mtok",
            "output_usd_per_mtok",
        },
        "llm.paid",
    )
    provider = paid.get("provider")
    if provider not in _PAID_PROVIDERS:
        raise ConfigError(f"llm.paid.provider must be one of {list(_PAID_PROVIDERS)}")
    model = _string(paid, "model", "llm.paid", "")
    if not model:
        raise ConfigError("llm.paid.model must be a non-empty string")
    base_url = _string(paid, "base_url", "llm.paid", "")
    if base_url and not base_url.startswith(("https://", "http://")):
        raise ConfigError("llm.paid.base_url must be an http(s) URL")
    key_ref = _string(paid, "api_key_secret", "llm.paid", "")
    if key_ref and key_ref not in secrets:
        raise ConfigError(
            f"llm.paid.api_key_secret {key_ref!r} is not a key under [secrets]; add "
            f'{key_ref} = "<keyring entry name>" there'
        )
    if key_ref and base_url.startswith("http://"):
        raise ConfigError("llm.paid.base_url must use https when api_key_secret is set")
    # OpenAI-compatible local servers (llama.cpp, LM Studio) take no key.
    if provider == "anthropic" and not key_ref:
        raise ConfigError("llm.paid.api_key_secret is required for the anthropic provider")
    token_cap = paid.get("daily_token_cap")
    if isinstance(token_cap, bool) or not isinstance(token_cap, int) or token_cap <= 0:
        raise ConfigError("llm.paid.daily_token_cap must be a positive integer")
    return PaidLLMConfig(
        provider=provider,
        model=model,
        base_url=base_url.rstrip("/"),
        api_key_secret=key_ref,
        daily_token_cap=token_cap,
        daily_usd_cap=float(_positive(paid, "daily_usd_cap", "llm.paid")),
        input_usd_per_mtok=_non_negative(paid, "input_usd_per_mtok", "llm.paid"),
        output_usd_per_mtok=_non_negative(paid, "output_usd_per_mtok", "llm.paid"),
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


def set_target_calendar(text: str, calendar_id: str) -> str:
    """Return ``text`` with ``[mirror] target_calendar`` set, every other line kept as is.

    Raises ConfigError when the edited config would not load, e.g. the target is also a source.
    """
    line = f"target_calendar = {json.dumps(calendar_id)}\n"
    lines = text.splitlines(keepends=True)
    header = next(
        (i for i, raw in enumerate(lines) if (m := _TABLE_HEADER.match(raw)) and m[1] == "mirror"),
        None,
    )
    if header is None:
        prefix = text if not text or text.endswith("\n") else text + "\n"
        edited = f"{prefix}\n[mirror]\n{line}"
    else:
        end = next(
            (i for i in range(header + 1, len(lines)) if _TABLE_HEADER.match(lines[i])),
            len(lines),
        )
        key = next((i for i in range(header + 1, end) if _TARGET_KEY.match(lines[i])), None)
        if key is None:
            lines.insert(header + 1, line)
        else:
            lines[key] = line
        edited = "".join(lines)
    try:
        cfg = parse_config(tomllib.loads(edited))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"cannot set mirror.target_calendar automatically: {exc}") from exc
    if cfg.mirror.target_calendar != calendar_id:
        raise ConfigError("cannot set mirror.target_calendar automatically; edit the config")
    return edited


def write_default_config(path: Path, *, force: bool = False) -> bool:
    """Write the default config. Returns False if one already exists and force is not set."""
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
    return True


def _parse_tier0(data: dict[str, Any]) -> Tier0Config:
    default = Tier0Config()
    t0 = _table(data, "tier0", {"host", "high", "low", "timeout_seconds", "retries", "serialize"})
    host = _string(t0, "host", "tier0", default.host)
    if not host.startswith(("https://", "http://")) or not host.split("://", 1)[1].strip("/"):
        raise ConfigError("tier0.host must be an http(s) URL")
    high, low = t0.get("high", default.high), t0.get("low", default.low)
    for key, value in (("high", high), ("low", low)):
        if not _is_number(value) or not 0 <= value <= 1:
            raise ConfigError(f"tier0.{key} must be a number between 0 and 1")
    if low > high:
        raise ConfigError("tier0.low must not exceed tier0.high")
    timeout = _positive(t0, "timeout_seconds", "tier0", default.timeout_seconds)
    if not math.isfinite(timeout):
        raise ConfigError("tier0.timeout_seconds must be a finite number")
    retries = t0.get("retries", default.retries)
    if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 5:
        raise ConfigError("tier0.retries must be an integer from 0 to 5")
    serialize = t0.get("serialize", default.serialize)
    if not isinstance(serialize, bool):
        raise ConfigError("tier0.serialize must be true or false")
    return Tier0Config(
        host=host.rstrip("/"),
        high=float(high),
        low=float(low),
        timeout_seconds=float(timeout),
        retries=retries,
        serialize=serialize,
    )
