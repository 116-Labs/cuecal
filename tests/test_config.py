import pytest

from cuecal.config import (
    DEFAULT_CONFIG_TOML,
    ConfigError,
    load_config,
    parse_config,
    write_default_config,
)


def test_default_config_loads(tmp_path):
    path = tmp_path / "config.toml"
    assert write_default_config(path)
    cfg = load_config(path)
    assert cfg.sink == "google-calendar"
    assert cfg.poll_interval_seconds == 300
    assert cfg.auto_create_threshold == 0.85


def test_default_config_leaves_llm_tiers_off_and_omits_removed_settings(tmp_path):
    assert "pending =" not in DEFAULT_CONFIG_TOML
    assert "tiers =" not in DEFAULT_CONFIG_TOML
    path = tmp_path / "config.toml"
    write_default_config(path)
    llm = load_config(path).llm
    assert llm.local is None
    assert llm.paid is None


def test_default_config_documents_every_llm_key():
    keys = (
        "min_confidence",
        "start_past_window_hours",
        "timezone",
        "[llm.local]",
        "keep_alive",
        "timeout_seconds",
        "[llm.paid]",
        "base_url",
        "api_key_secret",
        "daily_token_cap",
        "daily_usd_cap",
        "input_usd_per_mtok",
        "output_usd_per_mtok",
    )
    for key in keys:
        assert key in DEFAULT_CONFIG_TOML


def test_v0_1_1_starter_config_names_the_removed_settings(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[llm]\ntiers = ["regex", "local"]\n\n[thresholds]\nauto_create = 0.85\npending = 0.5\n'
    )
    with pytest.raises(
        ConfigError, match=r"\[llm\]\.tiers and thresholds.pending were removed; delete them"
    ):
        load_config(path)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"llm": {"tiers": ["regex"]}}, r"\[llm\]\.tiers was removed; delete them"),
        (
            {"llm": {"tiers": ["regex"], "local": {}}},
            r"\[llm\]\.tiers was removed; delete them",
        ),
        ({"thresholds": {"pending": 0.5}}, "thresholds.pending was removed"),
    ],
)
def test_single_removed_setting_is_named(data, message):
    with pytest.raises(ConfigError, match=message):
        parse_config(data)


PAID = {
    "provider": "anthropic",
    "model": "some-model",
    "api_key_secret": "anthropic",
    "daily_token_cap": 1000,
    "daily_usd_cap": 0.5,
    "input_usd_per_mtok": 1.0,
    "output_usd_per_mtok": 5.0,
}
SECRETS = {"anthropic": "cuecal-anthropic"}


def test_llm_table_without_tiers_is_accepted_with_defaults():
    llm = parse_config({"llm": {}}).llm
    assert llm.min_confidence == 0.7
    assert llm.start_past_window_hours == 24
    assert llm.timezone == ""
    assert llm.local is None and llm.paid is None


def test_llm_local_defaults_keep_alive_to_thirty_seconds():
    local = parse_config({"llm": {"local": {}}}).llm.local
    assert local.provider == "ollama"
    assert local.keep_alive == "30s"
    assert local.host == "http://localhost:11434"
    assert local.model


def test_llm_full_schema_parses():
    cfg = parse_config(
        {
            "secrets": SECRETS,
            "llm": {
                "min_confidence": 0.6,
                "start_past_window_hours": 12,
                "timezone": "Asia/Kolkata",
                "local": {
                    "provider": "ollama",
                    "host": "http://box:11434/",
                    "model": "gemma3:4b",
                    "keep_alive": "5m",
                    "timeout_seconds": 20,
                },
                "paid": PAID,
            },
        }
    )
    assert cfg.llm.min_confidence == 0.6
    assert cfg.llm.timezone == "Asia/Kolkata"
    assert cfg.llm.local.host == "http://box:11434"
    assert cfg.llm.local.keep_alive == "5m"
    assert cfg.llm.paid.daily_token_cap == 1000
    assert cfg.llm.paid.output_usd_per_mtok == 5.0


def test_llm_paid_openai_compatible_server_needs_no_key():
    paid = dict(PAID, provider="openai", base_url="http://127.0.0.1:8080/v1")
    del paid["api_key_secret"]
    cfg = parse_config({"llm": {"paid": paid}})
    assert cfg.llm.paid.api_key_secret == ""
    assert cfg.llm.paid.base_url == "http://127.0.0.1:8080/v1"


def test_llm_paid_https_base_url_with_a_key_is_accepted():
    cfg = parse_config(_paid(base_url="https://proxy.example/"))
    assert cfg.llm.paid.base_url == "https://proxy.example"


def _paid(**changes):
    paid = dict(PAID, **changes)
    return {"secrets": SECRETS, "llm": {"paid": {k: v for k, v in paid.items() if v is not None}}}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"llm": {"min_confidence": 1.5}}, "llm.min_confidence"),
        ({"llm": {"min_confidence": True}}, "llm.min_confidence"),
        ({"llm": {"start_past_window_hours": 0}}, "llm.start_past_window_hours"),
        ({"llm": {"timezone": "Mars/Base"}}, "IANA"),
        ({"llm": {"timezone": 5}}, "llm.timezone"),
        ({"llm": {"extra": 1}}, r"unknown keys in \[llm\]"),
        ({"llm": "on"}, r"\[llm\] must be a table"),
        ({"llm": {"local": {"provider": "llamacpp"}}}, "llm.local.provider"),
        ({"llm": {"local": {"host": "localhost"}}}, "llm.local.host"),
        ({"llm": {"local": {"model": ""}}}, "llm.local.model"),
        ({"llm": {"local": {"keep_alive": 30}}}, "llm.local.keep_alive"),
        ({"llm": {"local": {"timeout_seconds": 0}}}, "llm.local.timeout_seconds"),
        ({"llm": {"local": {"bogus": 1}}}, r"unknown keys in \[llm.local\]"),
        (_paid(provider="gemini"), "llm.paid.provider"),
        (_paid(provider=None), "llm.paid.provider"),
        (_paid(model=None), "llm.paid.model"),
        (_paid(api_key_secret="openrouter"), r"not a key under \[secrets\]"),
        (_paid(api_key_secret=None), "required for the anthropic provider"),
        (_paid(base_url="ftp://x"), "llm.paid.base_url"),
        (_paid(base_url="http://proxy:8080"), "must use https when api_key_secret is set"),
        (
            _paid(provider="openai", base_url="http://proxy:8080/v1"),
            "must use https when api_key_secret is set",
        ),
        (_paid(daily_token_cap=0), "llm.paid.daily_token_cap"),
        (_paid(daily_token_cap=-5), "llm.paid.daily_token_cap"),
        (_paid(daily_token_cap=1.5), "llm.paid.daily_token_cap"),
        (_paid(daily_token_cap=None), "llm.paid.daily_token_cap"),
        (_paid(daily_usd_cap=0), "llm.paid.daily_usd_cap"),
        (_paid(daily_usd_cap="1"), "llm.paid.daily_usd_cap"),
        (_paid(input_usd_per_mtok=-1), "llm.paid.input_usd_per_mtok"),
        (_paid(output_usd_per_mtok=None), "llm.paid.output_usd_per_mtok"),
        (_paid(bogus=1), r"unknown keys in \[llm.paid\]"),
    ],
)
def test_llm_validation_errors(data, message):
    with pytest.raises(ConfigError, match=message):
        parse_config(data)


def test_write_default_keeps_existing(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('sink = "mine"\n')
    assert not write_default_config(path)
    assert path.read_text() == 'sink = "mine"\n'
    assert write_default_config(path, force=True)
    assert path.read_text() == DEFAULT_CONFIG_TOML


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="cuecal init"):
        load_config(tmp_path / "nope.toml")


def test_invalid_toml(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("sink = [")
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(path)


def test_keyring_reference_accepted():
    assert parse_config({"secrets": {"slack": "cuecal-slack"}}).secrets == {"slack": "cuecal-slack"}


def test_empty_config_uses_defaults():
    cfg = parse_config({})
    assert cfg.poll_interval_seconds == 300
    assert cfg.fetch_limit == 100
    assert cfg.latency_budget_seconds == 30.0
    assert cfg.gmail.fetch_limit == 100
    assert cfg.gmail.latency_budget_seconds == 30.0


def test_secondary_sinks_default_and_parse(tmp_path):
    path = tmp_path / "config.toml"
    write_default_config(path)
    assert load_config(path).secondary_sinks == []
    cfg = parse_config({"sink": "google-calendar", "secondary_sinks": ["zoho", "ics"]})
    assert cfg.secondary_sinks == ["zoho", "ics"]


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ("zoho", "list of non-empty strings"),
        ([""], "list of non-empty strings"),
        (["zoho", "zoho"], "must not repeat"),
        (["google-calendar"], "must not include the primary"),
    ],
)
def test_secondary_sinks_invalid(value, match):
    with pytest.raises(ConfigError, match=match):
        parse_config({"secondary_sinks": value})


def test_limits_config_parsing():
    cfg = parse_config(
        {
            "limits": {
                "fetch_limit": 25,
                "latency_budget_seconds": 12.5,
            }
        }
    )
    assert cfg.fetch_limit == 25
    assert cfg.latency_budget_seconds == 12.5


def test_gmail_config_limits_parsing():
    cfg = parse_config(
        {
            "gmail": {
                "fetch_limit": 15,
                "latency_budget_seconds": 10.0,
            }
        }
    )
    assert cfg.gmail.fetch_limit == 15
    assert cfg.gmail.latency_budget_seconds == 10.0


def test_mirror_defaults_and_parse():
    cfg = parse_config({})
    assert cfg.mirror.target_calendar == "primary"
    assert cfg.mirror.source_calendars == []
    assert cfg.mirror.lookahead_days == 14
    assert cfg.mirror.include_transparent is False
    assert cfg.mirror.transparency == "opaque"
    assert cfg.mirror.self_attendee is True

    cfg = parse_config(
        {
            "mirror": {
                "source_calendars": ["work@group.calendar.google.com"],
                "lookahead_days": 7,
                "self_attendee": False,
                "self_email": " Me@Example.com ",
            }
        }
    )
    assert cfg.mirror.source_calendars == ["work@group.calendar.google.com"]
    assert cfg.mirror.lookahead_days == 7
    assert cfg.mirror.self_attendee is False
    assert cfg.mirror.self_email == "Me@Example.com"


@pytest.mark.parametrize(
    "mirror",
    [
        {"source_calendars": ["primary"]},
        {"target_calendar": "team@group", "source_calendars": ["team@group"]},
        {"self_email": "me@example.com", "source_calendars": ["ME@example.com"]},
        {
            "target_calendar": "me@example.com",
            "self_email": "me@example.com",
            "source_calendars": ["primary"],
        },
    ],
)
def test_mirror_rejects_target_as_source(mirror):
    with pytest.raises(ConfigError, match="must not include the target calendar"):
        parse_config({"mirror": mirror})


@pytest.mark.parametrize(
    "data",
    [
        {"mirror": {"target_calendar": "team@group"}},
        {"mirror": {"target_calendar": "me@example.com"}},
        {
            "sink": "other",
            "secondary_sinks": ["google-calendar"],
            "mirror": {"target_calendar": "x"},
        },
    ],
)
def test_mirror_target_must_match_google_sink_calendar(data):
    with pytest.raises(ConfigError, match="must be the primary calendar"):
        parse_config(data)


@pytest.mark.parametrize(
    "data",
    [
        {"mirror": {"target_calendar": "primary"}},
        {"mirror": {"target_calendar": "Me@Example.com", "self_email": "me@example.com"}},
        {"sink": "other", "mirror": {"target_calendar": "team@group"}},
    ],
)
def test_mirror_target_accepts_the_google_sink_calendar(data):
    assert parse_config(data).mirror.target_calendar == data["mirror"]["target_calendar"]


@pytest.mark.parametrize(
    "data, message",
    [
        ({"mirror": {"source_calendars": "work"}}, "mirror.source_calendars"),
        ({"mirror": {"source_calendars": ["a", "a"]}}, "must not repeat"),
        ({"mirror": {"target_calendar": ""}}, "mirror.target_calendar"),
        ({"mirror": {"lookahead_days": 0}}, "mirror.lookahead_days"),
        ({"mirror": {"self_attendee": "yes"}}, "mirror.self_attendee"),
        ({"mirror": {"transparency": "busy"}}, "mirror.transparency"),
        ({"mirror": {"extra": 1}}, "unknown keys in \\[mirror\\]"),
        ({"bogus": 1}, "unknown config keys"),
        ({"sources": "slack"}, "sources"),
        ({"sink": ""}, "sink"),
        ({"poll_interval_seconds": 0}, "poll_interval_seconds"),
        ({"poll_interval_seconds": True}, "poll_interval_seconds"),
        ({"secrets": {"slack": "xoxb-123"}}, "cuecal auth slack"),
        ({"secrets": {"google": "ya29.abc"}}, "raw token"),
        ({"thresholds": {"auto_create": 2}}, "thresholds.auto_create"),
        ({"secrets": {"slack": 5}}, "secrets"),
        ({"limits": {"fetch_limit": 0}}, "limits.fetch_limit"),
        ({"limits": {"fetch_limit": -1}}, "limits.fetch_limit"),
        ({"limits": {"fetch_limit": True}}, "limits.fetch_limit"),
        ({"limits": {"fetch_limit": "50"}}, "limits.fetch_limit"),
        ({"limits": {"latency_budget_seconds": 0}}, "limits.latency_budget_seconds"),
        ({"limits": {"latency_budget_seconds": -5.0}}, "limits.latency_budget_seconds"),
        ({"limits": {"latency_budget_seconds": True}}, "limits.latency_budget_seconds"),
        ({"limits": {"latency_budget_seconds": "30"}}, "limits.latency_budget_seconds"),
        ({"limits": {"extra": 1}}, "unknown keys in \\[limits\\]"),
        ({"gmail": {"fetch_limit": 0}}, "gmail.fetch_limit"),
        ({"gmail": {"fetch_limit": True}}, "gmail.fetch_limit"),
        ({"gmail": {"latency_budget_seconds": 0}}, "gmail.latency_budget_seconds"),
        ({"gmail": {"latency_budget_seconds": True}}, "gmail.latency_budget_seconds"),
    ],
)
def test_validation_errors(data, message):
    with pytest.raises(ConfigError, match=message):
        parse_config(data)
