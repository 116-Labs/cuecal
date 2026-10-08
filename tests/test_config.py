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
    assert cfg.llm_tiers == ["regex", "local", "paid"]
    assert cfg.auto_create_threshold == 0.85


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


@pytest.mark.parametrize(
    "data, message",
    [
        ({"bogus": 1}, "unknown config keys"),
        ({"sources": "slack"}, "sources"),
        ({"sink": ""}, "sink"),
        ({"poll_interval_seconds": 0}, "poll_interval_seconds"),
        ({"poll_interval_seconds": True}, "poll_interval_seconds"),
        ({"llm": {"tiers": ["gpt"]}}, "llm.tiers"),
        ({"llm": {"tiers": [["regex"]]}}, "llm.tiers"),
        ({"secrets": {"slack": "xoxb-123"}}, "cuecal auth slack"),
        ({"secrets": {"google": "ya29.abc"}}, "raw token"),
        ({"llm": {"extra": 1}}, "unknown keys in \\[llm\\]"),
        ({"thresholds": {"auto_create": 2}}, "thresholds.auto_create"),
        ({"thresholds": {"auto_create": 0.4, "pending": 0.6}}, "must not exceed"),
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
