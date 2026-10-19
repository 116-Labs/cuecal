from __future__ import annotations

import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from cuecal.extract import tier2
from cuecal.extract.providers import ProviderError, ProviderResult
from cuecal.models import MeetingCandidate, Message

RECEIVED = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def _answer(**overrides):
    data = {
        "title": "Design review",
        "start": "2026-10-20T15:00:00",
        "end": "2026-10-20T15:30:00",
        "timezone": "America/New_York",
        "attendees": ["ana@example.com"],
        "confidence": 0.9,
    }
    data.update(overrides)
    return json.dumps({k: v for k, v in data.items() if v is not None})


def _gate(raw, **kw):
    args = {
        "received_at": RECEIVED,
        "window_hours": 24,
        "fallback_tz": "Europe/London",
        "min_confidence": 0.7,
    }
    return tier2.validate(raw, **{**args, **kw})


def test_gate_passes_a_well_formed_answer_and_localises_naive_times():
    result = _gate(_answer())
    assert result.passed
    assert result.fields.start == datetime(2026, 10, 20, 15, tzinfo=ZoneInfo("America/New_York"))
    assert result.fields.tz == "America/New_York"
    assert result.fields.attendees == ["ana@example.com"]


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[1, 2]",
        _answer(start=None),
        _answer(title=5),
        _answer(attendees="ana"),
        _answer(confidence="high"),
        _answer(confidence=True),
        _answer(confidence=1.5),
        _answer(start="next tuesday"),
    ],
    ids=[
        "non-json",
        "not-object",
        "missing-start",
        "title-not-string",
        "attendees-not-list",
        "confidence-string",
        "confidence-bool",
        "confidence-out-of-range",
        "start-not-iso",
    ],
)
def test_gate_rejects_invalid_schema(raw):
    result = _gate(raw)
    assert not result.passed
    assert result.reason


def test_gate_rejects_start_earlier_than_received_at_minus_window():
    result = _gate(_answer(start="2026-10-17T11:59:00Z", end="2026-10-17T12:30:00Z"))
    assert not result.passed
    assert "before receipt" in result.reason


def test_gate_accepts_start_inside_the_past_window():
    result = _gate(_answer(start="2026-10-17T12:30:00Z", end="2026-10-17T13:00:00Z"))
    assert result.passed


def test_gate_window_is_measured_from_received_at_not_wall_clock():
    old = datetime(2020, 1, 1, 9, tzinfo=UTC)
    result = _gate(
        _answer(start="2020-01-01T10:00:00Z", end="2020-01-01T10:30:00Z"), received_at=old
    )
    assert result.passed


def test_gate_invalid_iana_timezone_falls_back_to_configured_zone():
    result = _gate(_answer(timezone="IST"))
    assert result.passed
    assert result.fields.tz == "Europe/London"
    assert result.fields.start.tzinfo == ZoneInfo("Europe/London")


@pytest.mark.parametrize("end", ["2026-10-20T15:00:00", "2026-10-20T14:00:00"])
def test_gate_rejects_end_not_after_start(end):
    result = _gate(_answer(end=end))
    assert not result.passed
    assert "end must be after start" in result.reason


def test_gate_rejects_confidence_below_min_confidence():
    result = _gate(_answer(confidence=0.69))
    assert not result.passed
    assert "below" in result.reason


def test_gate_accepts_confidence_at_min_confidence():
    assert _gate(_answer(confidence=0.7)).passed


def _partial():
    return MeetingCandidate(
        title="Meeting",
        join_url="https://zoom.us/j/123456789?pwd=abc",
        meeting_id="123456789",
        passcode="abc",
        confidence=0.0,
        tier="regex",
    )


def test_regex_link_meeting_id_and_passcode_override_llm_output():
    raw = _answer(
        join_url="https://evil.example/j/1", meeting_id="999", passcode="nope", title="Sync"
    )
    fields = _gate(raw).fields
    merged = tier2.merge(_partial(), fields, "local")
    assert merged.join_url == "https://zoom.us/j/123456789?pwd=abc"
    assert merged.meeting_id == "123456789"
    assert merged.passcode == "abc"
    assert merged.title == "Sync"
    assert merged.tier == "local"
    assert merged.confidence == 0.9


def test_prompt_carries_message_received_at_timezone_and_partial():
    msg = Message(id="m1", source="slack", sender="ana", ts=RECEIVED, text="sync tue 3pm?")
    prompt = tier2.build_prompt(msg, _partial(), "Europe/London")
    assert RECEIVED.isoformat() in prompt
    assert "Europe/London" in prompt
    assert "sync tue 3pm?" in prompt
    assert "123456789" in prompt


class _Provider:
    name = "fake"
    model = "fake-1"

    def __init__(self, answer):
        self.answer = answer

    def complete(self, system, prompt, schema):
        if isinstance(self.answer, Exception):
            raise self.answer
        return ProviderResult(self.answer, 11, 7)


def _attempt(provider):
    msg = Message(id="m1", source="slack", sender="ana", ts=RECEIVED, text="x")
    return tier2.attempt(
        provider,
        msg,
        _partial(),
        tier="local",
        timezone="UTC",
        window_hours=24,
        min_confidence=0.7,
    )


def test_attempt_reports_tokens_and_gate_result():
    result = _attempt(_Provider(_answer()))
    assert result.passed
    assert (result.input_tokens, result.output_tokens) == (11, 7)
    assert (result.provider, result.model, result.tier) == ("fake", "fake-1", "local")


def test_attempt_turns_provider_error_into_a_failed_gate():
    result = _attempt(_Provider(ProviderError("cannot reach host")))
    assert not result.passed
    assert "cannot reach host" in result.gate.reason


def test_system_timezone_reads_tz_env(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    assert tier2.system_timezone() == "Asia/Tokyo"
    assert tier2.recipient_timezone("") == "Asia/Tokyo"
    assert tier2.recipient_timezone("Europe/Paris") == "Europe/Paris"


def test_system_timezone_is_none_not_utc_when_no_iana_zone_resolves(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.setattr(tier2.os.path, "realpath", lambda path: "C:\\etc\\localtime")
    assert tier2.system_timezone() is None
    assert tier2.recipient_timezone("") is None
    assert tier2.recipient_timezone("Europe/Paris") == "Europe/Paris"
