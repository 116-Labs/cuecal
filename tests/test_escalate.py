from __future__ import annotations

import json
import logging
import sqlite3
import urllib.error
from datetime import UTC, datetime

import pytest

from cuecal import db
from cuecal.config import LLMConfig, PaidLLMConfig, parse_config
from cuecal.extract import escalate, tier1, tier3
from cuecal.extract.escalate import Escalator, needs_escalation
from cuecal.extract.providers import (
    OllamaProvider,
    ProviderError,
    ProviderResult,
    UnusableAnswer,
)
from cuecal.models import MeetingCandidate, Message

RECEIVED = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
GOOD = json.dumps(
    {
        "title": "Design review",
        "start": "2026-10-20T15:00:00",
        "end": "2026-10-20T15:30:00",
        "timezone": "America/New_York",
        "attendees": [],
        "confidence": 0.9,
    }
)
LOW = GOOD.replace("0.9", "0.5")


class FakeProvider:
    def __init__(self, name, answer, tokens=(100, 20), usage_known=True):
        self.name = name
        self.model = f"{name}-model"
        self.answer = answer
        self.tokens = tokens
        self.usage_known = usage_known
        self.calls = 0

    def complete(self, system, prompt, schema):
        self.calls += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return ProviderResult(self.answer, *self.tokens, usage_known=self.usage_known)


class Recorder:
    name = "recorder"

    def __init__(self):
        self.sent = []

    def send(self, notification):
        self.sent.append(notification)


def _paid_cfg(**changes):
    values = {
        "provider": "anthropic",
        "model": "m",
        "daily_token_cap": 10_000,
        "daily_usd_cap": 1.0,
        "input_usd_per_mtok": 3.0,
        "output_usd_per_mtok": 15.0,
        "api_key_secret": "anthropic",
    }
    values.update(changes)
    return PaidLLMConfig(**values)


def _llm(paid=True, **changes):
    return LLMConfig(timezone="UTC", paid=_paid_cfg(**changes) if paid else None)


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "state.db")


def _msg(mid="m1"):
    return Message(id=mid, source="slack", sender="ana", ts=RECEIVED, text="review tue 3pm ET")


def _partial(**kw):
    values = {
        "title": "Meeting",
        "join_url": "https://zoom.us/j/123456789",
        "meeting_id": "123456789",
        "confidence": 0.0,
        "tier": "regex",
    }
    values.update(kw)
    return MeetingCandidate(**values)


def _now():
    return RECEIVED


def test_needs_escalation_matches_the_eval_condition():
    assert needs_escalation(_partial())
    assert needs_escalation(_partial(tier="template", confidence=tier1.LOW))
    assert not needs_escalation(_partial(tier="template", confidence=tier1.HIGH))
    assert not needs_escalation(_partial(tier="ics", confidence=tier1.HIGH))


def test_without_llm_config_candidate_is_unchanged_and_no_provider_exists(conn, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("no HTTP call expected")

    monkeypatch.setattr("urllib.request.urlopen", no_network)
    esc = Escalator.from_config(parse_config({}), conn=conn)
    assert esc.local is None and esc.paid is None
    cand = _partial()
    outcome = esc.process(_msg(), cand)
    assert outcome.candidate is cand
    assert outcome.pending_reason is None
    assert outcome.attempts == []


def test_high_confidence_candidate_never_calls_a_provider(conn):
    local = FakeProvider("ollama", GOOD)
    paid = FakeProvider("anthropic", GOOD)
    esc = Escalator(_llm(), conn=conn, local=local, paid=paid, now=_now)
    cand = _partial(tier="template", confidence=tier1.HIGH)
    assert esc.process(_msg(), cand).candidate is cand
    assert local.calls == paid.calls == 0


def test_unknown_recipient_timezone_routes_passing_llm_result_to_pending(
    conn, monkeypatch, caplog
):
    monkeypatch.setattr(escalate.tier2, "system_timezone", lambda: None)
    local = FakeProvider("ollama", GOOD)
    esc = Escalator(LLMConfig(timezone=""), conn=conn, local=local, now=_now)
    with caplog.at_level(logging.WARNING, logger="cuecal.extract"):
        first = esc.process(_msg("m1"), _partial())
        second = esc.process(_msg("m2"), _partial())
    for outcome in (first, second):
        assert outcome.candidate.tier == "local"
        assert outcome.pending_reason == escalate.UNKNOWN_TIMEZONE
    assert sum("no IANA zone" in r.getMessage() for r in caplog.records) == 1


def test_unknown_timezone_also_sends_a_passing_tier3_result_to_pending(conn, monkeypatch):
    monkeypatch.setattr(escalate.tier2, "system_timezone", lambda: None)
    paid = FakeProvider("anthropic", GOOD)
    llm = LLMConfig(timezone="", paid=_paid_cfg())
    outcome = Escalator(llm, conn=conn, paid=paid, now=_now).process(_msg(), _partial())
    assert outcome.candidate.tier == "paid"
    assert outcome.pending_reason == escalate.UNKNOWN_TIMEZONE


def test_tier3_is_never_called_when_tier2_passes(conn):
    local = FakeProvider("ollama", GOOD)
    paid = FakeProvider("anthropic", GOOD)
    esc = Escalator(_llm(), conn=conn, local=local, paid=paid, now=_now)
    outcome = esc.process(_msg(), _partial())
    assert outcome.pending_reason is None
    assert outcome.candidate.tier == "local"
    assert outcome.candidate.meeting_id == "123456789"
    assert (local.calls, paid.calls) == (1, 0)


@pytest.mark.parametrize("answer", ["{}", LOW], ids=["fails-validation", "below-min-confidence"])
def test_tier3_is_called_when_tier2_fails(conn, answer):
    local = FakeProvider("ollama", answer)
    paid = FakeProvider("anthropic", GOOD)
    esc = Escalator(_llm(), conn=conn, local=local, paid=paid, now=_now)
    outcome = esc.process(_msg(), _partial())
    assert (local.calls, paid.calls) == (1, 1)
    assert outcome.pending_reason is None
    assert outcome.candidate.tier == "paid"


def test_tier3_result_is_not_held_to_min_confidence(conn):
    paid = FakeProvider("anthropic", LOW)
    esc = Escalator(_llm(), conn=conn, local=FakeProvider("ollama", "{}"), paid=paid, now=_now)
    outcome = esc.process(_msg(), _partial())
    assert outcome.pending_reason is None
    assert outcome.candidate.confidence == 0.5


def _ollama_failing(monkeypatch, failure):
    def fake_urlopen(req, timeout=None):
        if isinstance(failure, Exception):
            raise failure

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return failure

        return Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return OllamaProvider(host="http://localhost:11434", model="m", keep_alive="30s", timeout=1)


FAILURES = [
    urllib.error.URLError(ConnectionRefusedError("refused")),
    TimeoutError("timed out"),
    b'{"message": {"content": "sure! the meeting is tuesday"}}',
]
FAILURE_IDS = ["host-down", "timeout", "non-json"]


@pytest.mark.parametrize("failure", FAILURES, ids=FAILURE_IDS)
def test_tier2_transport_failures_escalate_once_to_tier3(conn, monkeypatch, failure):
    paid = FakeProvider("anthropic", GOOD)
    esc = Escalator(
        _llm(), conn=conn, local=_ollama_failing(monkeypatch, failure), paid=paid, now=_now
    )
    outcome = esc.process(_msg(), _partial())
    assert paid.calls == 1
    assert outcome.candidate.tier == "paid"


@pytest.mark.parametrize("failure", FAILURES, ids=FAILURE_IDS)
def test_tier2_failure_with_tier3_off_keeps_the_partial_for_pending(conn, monkeypatch, failure):
    esc = Escalator(
        _llm(paid=False), conn=conn, local=_ollama_failing(monkeypatch, failure), now=_now
    )
    cand = _partial()
    outcome = esc.process(_msg(), cand)
    assert outcome.candidate is cand
    assert outcome.pending_reason.startswith("tier 2 failed")


@pytest.mark.parametrize("failure", FAILURES[:2], ids=FAILURE_IDS[:2])
def test_unreachable_tier2_is_skipped_for_the_rest_of_the_run_but_tier3_still_runs(
    conn, monkeypatch, caplog, failure
):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        raise failure

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    local = OllamaProvider(host="http://localhost:11434", model="m", keep_alive="30s", timeout=1)
    paid = FakeProvider("anthropic", GOOD)
    esc = Escalator(_llm(), conn=conn, local=local, paid=paid, now=_now)
    with caplog.at_level(logging.WARNING, logger="cuecal.extract"):
        outcomes = [esc.process(_msg(f"m{i}"), _partial()) for i in range(3)]
    assert len(calls) == 1
    assert paid.calls == 3
    assert all(o.candidate.tier == "paid" for o in outcomes)
    assert sum("tier 2 unreachable" in r.getMessage() for r in caplog.records) == 1


def test_unreachable_tier2_with_tier3_off_names_the_skip_in_pending(conn, monkeypatch):
    local = _ollama_failing(monkeypatch, TimeoutError("timed out"))
    esc = Escalator(_llm(paid=False), conn=conn, local=local, now=_now)
    esc.process(_msg("m1"), _partial())
    assert esc.process(_msg("m2"), _partial()).pending_reason == escalate.LOCAL_UNREACHABLE


@pytest.mark.parametrize("answer", ["{}", LOW], ids=["fails-validation", "below-min-confidence"])
def test_tier2_gate_failure_does_not_skip_tier2_for_later_candidates(conn, answer):
    local = FakeProvider("ollama", answer)
    esc = Escalator(_llm(paid=False), conn=conn, local=local, now=_now)
    esc.process(_msg("m1"), _partial())
    esc.process(_msg("m2"), _partial())
    assert local.calls == 2


def test_tier2_http_error_does_not_skip_tier2_for_later_candidates(conn, monkeypatch):
    error = urllib.error.HTTPError("http://localhost:11434", 500, "boom", {}, None)
    local = _ollama_failing(monkeypatch, error)
    esc = Escalator(_llm(paid=False), conn=conn, local=local, now=_now)
    esc.process(_msg("m1"), _partial())
    assert esc.process(_msg("m2"), _partial()).pending_reason.startswith("tier 2 failed")


def test_unknown_tier3_usage_caps_the_day_and_survives_restart(tmp_path, caplog):
    first = db.connect(tmp_path / "state.db")
    paid = FakeProvider("anthropic", GOOD, tokens=(0, 0), usage_known=False)
    esc = Escalator(_llm(), conn=first, paid=paid, now=_now)
    with caplog.at_level(logging.ERROR, logger="cuecal.extract"):
        outcome = esc.process(_msg("m1"), _partial())
    assert outcome.candidate.tier == "paid"
    assert outcome.pending_reason is None
    assert "no usable token counts" in caplog.text
    assert esc.process(_msg("m2"), _partial()).pending_reason == tier3.UNKNOWN_USAGE
    assert paid.calls == 1
    first.close()

    second = db.connect(tmp_path / "state.db")
    assert db.get_llm_usage(second, "2026-10-18") == (0, 0.0)
    later = FakeProvider("anthropic", GOOD)
    restarted = Escalator(_llm(), conn=second, paid=later, now=_now)
    assert restarted.process(_msg("m3"), _partial()).pending_reason == tier3.UNKNOWN_USAGE
    assert later.calls == 0


def test_unusable_tier3_answer_still_counts_its_billed_tokens(conn):
    billed = ProviderResult("", 100_000, 20_000)
    paid = FakeProvider("anthropic", UnusableAnswer("no tool_use block", billed))
    esc = Escalator(_llm(daily_token_cap=100_000), conn=conn, paid=paid, now=_now)
    assert "tier 3 failed" in esc.process(_msg("m1"), _partial()).pending_reason
    assert db.get_llm_usage(conn, "2026-10-18")[0] == 120_000
    assert "daily token cap reached" in esc.process(_msg("m2"), _partial()).pending_reason
    assert paid.calls == 1


def test_unusable_tier3_answer_without_usage_caps_the_day(conn):
    unknown = ProviderResult("", usage_known=False)
    paid = FakeProvider("anthropic", UnusableAnswer("no tool_use block", unknown))
    esc = Escalator(_llm(), conn=conn, paid=paid, now=_now)
    esc.process(_msg("m1"), _partial())
    assert esc.process(_msg("m2"), _partial()).pending_reason == tier3.UNKNOWN_USAGE
    assert paid.calls == 1


def test_unknown_tier3_usage_cap_lifts_on_a_new_local_date(conn):
    db.mark_llm_usage_unknown(conn, "2026-10-18")
    paid = FakeProvider("anthropic", GOOD)
    tomorrow = datetime(2026, 10, 19, 0, 30, tzinfo=UTC)
    esc = Escalator(_llm(), conn=conn, paid=paid, now=lambda: tomorrow)
    assert esc.process(_msg(), _partial()).pending_reason is None
    assert paid.calls == 1


def test_failed_unknown_usage_write_caps_tier3_for_the_rest_of_the_run(conn, monkeypatch):
    def broken(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(db, "mark_llm_usage_unknown", broken)
    paid = FakeProvider("anthropic", GOOD, usage_known=False)
    esc = Escalator(_llm(), conn=conn, paid=paid, now=_now)
    esc.process(_msg(), _partial())
    assert "could not be recorded" in esc.process(_msg("m2"), _partial()).pending_reason
    assert paid.calls == 1


def _capped_run(conn, caplog, **cap):
    recorder = Recorder()
    paid = FakeProvider("anthropic", GOOD)
    esc = Escalator(
        _llm(**cap),
        conn=conn,
        notifiers=[recorder],
        local=FakeProvider("ollama", "{}"),
        paid=paid,
        now=_now,
    )
    with caplog.at_level(logging.WARNING, logger="cuecal.extract"):
        outcome = esc.process(_msg(), _partial())
        second = esc.process(_msg("m2"), _partial())
    return outcome, second, paid, recorder


def test_daily_token_cap_skips_tier3_logs_and_notifies_once(conn, caplog):
    db.add_llm_usage(conn, "2026-10-18", input_tokens=900, output_tokens=100, usd=0.0)
    outcome, second, paid, recorder = _capped_run(conn, caplog, daily_token_cap=1000)
    assert paid.calls == 0
    assert "daily token cap reached" in outcome.pending_reason
    assert "daily token cap reached" in second.pending_reason
    assert "daily token cap reached" in caplog.text
    assert len(recorder.sent) == 1
    assert "paid LLM tier skipped" in recorder.sent[0].title


def test_cap_notice_is_sent_once_per_day_across_runs(tmp_path, caplog):
    first = db.connect(tmp_path / "state.db")
    db.add_llm_usage(first, "2026-10-18", input_tokens=1000, output_tokens=0, usd=0.0)
    _, _, _, recorder = _capped_run(first, caplog, daily_token_cap=1000)
    first.close()
    _, _, _, next_run = _capped_run(db.connect(tmp_path / "state.db"), caplog, daily_token_cap=1000)
    assert len(recorder.sent) == 1
    assert next_run.sent == []


def test_daily_usd_cap_skips_tier3_logs_and_notifies(conn, caplog):
    db.add_llm_usage(conn, "2026-10-18", input_tokens=1, output_tokens=1, usd=0.5)
    outcome, _, paid, recorder = _capped_run(conn, caplog, daily_usd_cap=0.5)
    assert paid.calls == 0
    assert "daily USD cap reached" in outcome.pending_reason
    assert "daily USD cap reached" in caplog.text
    assert len(recorder.sent) == 1


def test_tier3_usage_is_recorded_in_usd_and_survives_restart(tmp_path):
    first = db.connect(tmp_path / "state.db")
    paid = FakeProvider("anthropic", GOOD, tokens=(1_000_000, 100_000))
    uncapped_tokens = 10**9
    esc = Escalator(
        _llm(daily_usd_cap=5.0, daily_token_cap=uncapped_tokens), conn=first, paid=paid, now=_now
    )
    esc.process(_msg(), _partial())
    first.close()

    second = db.connect(tmp_path / "state.db")
    tokens, usd = db.get_llm_usage(second, "2026-10-18")
    assert tokens == 1_100_000
    assert usd == pytest.approx(3.0 + 1.5)
    later = FakeProvider("anthropic", GOOD)
    restarted = Escalator(
        _llm(daily_usd_cap=4.5, daily_token_cap=uncapped_tokens), conn=second, paid=later, now=_now
    )
    assert "daily USD cap reached" in restarted.process(_msg("m2"), _partial()).pending_reason
    assert later.calls == 0


def test_usage_resets_on_a_new_local_date(conn):
    db.add_llm_usage(conn, "2026-10-18", input_tokens=10_000, output_tokens=0, usd=0.0)
    paid = FakeProvider("anthropic", GOOD)
    tomorrow = datetime(2026, 10, 19, 0, 30, tzinfo=UTC)
    esc = Escalator(_llm(), conn=conn, paid=paid, now=lambda: tomorrow)
    assert esc.process(_msg(), _partial()).pending_reason is None
    assert paid.calls == 1


def test_local_date_follows_the_recipient_timezone(conn):
    db.add_llm_usage(conn, "2026-10-19", input_tokens=10_000, output_tokens=0, usd=0.0)
    paid = FakeProvider("anthropic", GOOD)
    llm = LLMConfig(timezone="Asia/Tokyo", paid=_paid_cfg())
    late_utc = datetime(2026, 10, 18, 20, 0, tzinfo=UTC)
    esc = Escalator(llm, conn=conn, paid=paid, now=lambda: late_utc)
    assert "daily token cap reached" in esc.process(_msg(), _partial()).pending_reason


def test_failed_usage_read_fails_closed(conn, monkeypatch):
    def broken(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db, "get_llm_usage", broken)
    paid = FakeProvider("anthropic", GOOD)
    esc = Escalator(_llm(), conn=conn, paid=paid, now=_now)
    outcome = esc.process(_msg(), _partial())
    assert paid.calls == 0
    assert "unreadable" in outcome.pending_reason


def test_failed_usage_write_caps_tier3_for_the_rest_of_the_run(conn, monkeypatch):
    def broken(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(db, "add_llm_usage", broken)
    paid = FakeProvider("anthropic", GOOD)
    esc = Escalator(_llm(), conn=conn, paid=paid, now=_now)
    assert esc.process(_msg(), _partial()).pending_reason is None
    assert "could not be recorded" in esc.process(_msg("m2"), _partial()).pending_reason
    assert paid.calls == 1


def _cfg_with_paid():
    return parse_config(
        {
            "secrets": {"anthropic": "cuecal-anthropic"},
            "llm": {
                "paid": {
                    "provider": "anthropic",
                    "model": "m",
                    "api_key_secret": "anthropic",
                    "daily_token_cap": 1000,
                    "daily_usd_cap": 1.0,
                    "input_usd_per_mtok": 1.0,
                    "output_usd_per_mtok": 1.0,
                }
            },
        }
    )


def test_keyring_failure_at_call_time_routes_candidate_to_pending(conn, monkeypatch):
    keys = iter(["sk-present"])

    def get_secret(ref):
        assert ref == "cuecal-anthropic"
        try:
            return next(keys)
        except StopIteration:
            raise RuntimeError("keyring locked") from None

    def no_network(*a, **k):
        raise AssertionError("no HTTP call expected")

    monkeypatch.setattr("cuecal.secrets.get_secret", get_secret)
    monkeypatch.setattr("urllib.request.urlopen", no_network)
    esc = Escalator.from_config(_cfg_with_paid(), conn=conn)
    assert esc.paid is not None
    cand = _partial()
    outcome = esc.process(_msg(), cand)
    assert outcome.candidate is cand
    assert "keyring" in outcome.pending_reason


@pytest.mark.parametrize(
    ("get_secret", "problem"),
    [
        (lambda ref: None, "is missing"),
        (lambda ref: (_ for _ in ()).throw(RuntimeError("no backend")), "failed"),
    ],
    ids=["missing", "backend-error"],
)
def test_missing_key_at_run_start_turns_tier3_off(conn, monkeypatch, caplog, get_secret, problem):
    monkeypatch.setattr("cuecal.secrets.get_secret", get_secret)
    cfg = _cfg_with_paid()
    assert problem in escalate.paid_key_problem(cfg)
    with caplog.at_level(logging.ERROR, logger="cuecal.extract"):
        esc = Escalator.from_config(cfg, conn=conn)
    assert esc.paid is None
    assert "tier 3 is off" in caplog.text
    assert "API key missing" in esc.process(_msg(), _partial()).pending_reason


def test_paid_key_problem_is_none_when_the_entry_exists(monkeypatch):
    monkeypatch.setattr("cuecal.secrets.get_secret", lambda ref: "sk-x")
    assert escalate.paid_key_problem(_cfg_with_paid()) is None
    assert escalate.paid_key_problem(parse_config({})) is None


def test_telemetry_is_stored_and_logged_for_every_candidate(conn, caplog):
    local = FakeProvider("ollama", "{}", tokens=(40, 5))
    paid = FakeProvider("anthropic", GOOD, tokens=(300, 60))
    esc = Escalator(_llm(), conn=conn, local=local, paid=paid, now=_now)
    with caplog.at_level(logging.INFO, logger="cuecal.extract"):
        deterministic = _partial(tier="ics", confidence=tier1.HIGH)
        esc.process(_msg("deterministic"), deterministic, base_latency_ms=2)
        esc.process(_msg("escalated"), _partial())
    rows = {r["message_id"]: r for r in db.list_extraction_telemetry(conn)}
    assert rows["deterministic"]["tier"] == "ics"
    assert rows["deterministic"]["provider"] is None
    assert rows["deterministic"]["latency_ms"] == 2
    esc_row = rows["escalated"]
    assert (esc_row["tier"], esc_row["provider"], esc_row["model"]) == (
        "paid",
        "anthropic",
        "anthropic-model",
    )
    assert (esc_row["input_tokens"], esc_row["output_tokens"]) == (340, 65)
    assert esc_row["latency_ms"] >= 0
    logged = [r for r in caplog.records if r.getMessage() == "extraction telemetry"]
    assert [r.message_id for r in logged] == ["deterministic", "escalated"]
    assert logged[1].tier == "paid"


def test_telemetry_is_logged_but_not_stored_when_recording_is_off(conn):
    esc = Escalator(_llm(paid=False), conn=conn, record=False)
    esc.process(_msg(), _partial())
    assert db.list_extraction_telemetry(conn) == []


def test_unexpected_provider_exception_keeps_partial_for_pending(conn):
    local = FakeProvider("ollama", ValueError("adapter bug"))
    esc = Escalator(_llm(paid=False), conn=conn, local=local, now=_now)
    cand = _partial()
    outcome = esc.process(_msg(), cand)
    assert outcome.candidate is cand
    assert outcome.pending_reason == "escalation error: adapter bug"


def test_paid_provider_error_keeps_partial(conn):
    paid = FakeProvider("anthropic", ProviderError("HTTP 529"))
    esc = Escalator(_llm(), conn=conn, paid=paid, now=_now)
    outcome = esc.process(_msg(), _partial())
    assert outcome.candidate.tier == "regex"
    assert "tier 3 failed: provider error: HTTP 529" in outcome.pending_reason
