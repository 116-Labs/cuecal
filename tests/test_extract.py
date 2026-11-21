from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from cuecal import db, extract
from cuecal.config import parse_config
from cuecal.extract import decision, tier0, tier1
from cuecal.extract.decision import CLASSES, QUESTION_ID, Route, WorkersAIClient
from cuecal.models import Message


def msg(text: str, attachments: tuple[str, ...] = (), mid: str = "m1") -> Message:
    return Message(mid, "gmail", "a", datetime(2026, 10, 1, tzinfo=UTC), text, None, attachments)


def _answer(**probs: float) -> dict[str, Any]:
    full = {name: 0.0 for name in CLASSES} | probs
    top = max(full, key=lambda k: full[k])
    return {
        QUESTION_ID: {
            "type": "choice",
            "choice": top,
            "probabilities": full,
            "confidence": full[top],
        }
    }


class _LoopbackServer:
    def __init__(self, reply: Callable[[dict[str, Any]], tuple[int, Any]]) -> None:
        self.requests: list[dict[str, Any]] = []
        lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                headers = {k.lower(): v for k, v in self.headers.items()}
                with lock:
                    outer.requests.append({"path": self.path, "headers": headers, "body": body})
                status, payload = reply(body)
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.host = f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self) -> _LoopbackServer:
        threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        ).start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.server.shutdown()
        self.server.server_close()


@contextmanager
def _serving(status: int, payload: Any) -> Iterator[_LoopbackServer]:
    with _LoopbackServer(lambda _body: (status, payload)) as server:
        yield server


def test_dropped_without_link_or_calendar():
    assert extract.extract(msg("see you at 2")) is None


def test_link_only_gives_partial_candidate():
    c = extract.extract(msg("call: https://meet.google.com/abc-defg-hij"))
    assert c is not None
    assert c.start is None
    assert c.meeting_id == "abc-defg-hij"
    assert c.confidence < tier1.HIGH


def test_zoom_invite_is_high():
    text = (
        "Topic: Sync\n"
        "Time: Oct 3, 2026 02:00 PM Pacific Time (US and Canada)\n"
        "https://zoom.us/j/81234567890"
    )
    c = extract.extract(msg(text))
    assert c is not None
    assert c.confidence == tier1.HIGH
    assert c.meeting_id == "81234567890"


def test_ics_attachment_without_link():
    body = (
        "BEGIN:VCALENDAR\r\nMETHOD:REQUEST\r\nBEGIN:VEVENT\r\nUID:1\r\n"
        "DTSTART:20261003T210000Z\r\nSUMMARY:X\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    c = extract.extract(msg("see attached", (body,)))
    assert c is not None
    assert c.tier == "ics"
    assert c.meeting_id is None
    assert c.confidence == tier1.HIGH


def _cloud_reply(**probs: float) -> dict[str, Any]:
    return {
        "result": _answer(**probs),
        "usage": {"prompt_tokens": 30, "completion_tokens": 10},
    }


def test_tier0_runner_healthy_local_never_calls_workers_ai_or_regex_gate(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "state.db")
    monkeypatch.setattr(
        tier0,
        "gate",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("regex gate must not run")),
    )
    with (
        _serving(200, _answer(new_invite=0.92)) as local_srv,
        _serving(200, _cloud_reply(new_invite=0.92)) as cloud_srv,
    ):
        cfg = parse_config(
            {
                "secrets": {"cf": "cuecal-cf"},
                "tier0": {
                    "host": local_srv.host,
                    "retries": 0,
                    "workers_ai": {
                        "enabled": True,
                        "account_id": "acct",
                        "api_key_secret": "cf",
                    },
                },
            }
        )
        assert cfg.tier0 is not None
        cloud = WorkersAIClient(
            account_id="acct",
            api_key=lambda: "token",
            high=0.8,
            low=0.3,
            base_url=cloud_srv.host,
        )
        runner = extract.Tier0Runner(cfg.tier0, conn=conn, workers_ai=cloud)
        out = runner.extract(msg("lunch meeting tomorrow at noon in Room 4B"))
    assert out.decision is not None and out.decision.route is Route.TIER1_2
    assert out.candidate is not None
    assert not out.used_regex_fallback
    assert len(local_srv.requests) == 1
    assert cloud_srv.requests == []


def test_tier0_runner_warns_once_per_run_and_falls_back_to_regex(tmp_path, caplog):
    conn = db.connect(tmp_path / "state.db")
    with _serving(503, {}) as local_srv:
        cfg = parse_config({"tier0": {"host": local_srv.host, "retries": 0}})
        runner = extract.Tier0Runner.from_config(cfg, conn=conn)
        assert runner is not None
        with caplog.at_level("WARNING", logger="cuecal.extract"):
            first = runner.extract(msg("call: https://meet.google.com/abc-defg-hij", mid="m1"))
            second = runner.extract(msg("no link here", mid="m2"))
    assert first.used_regex_fallback and first.candidate is not None
    assert first.candidate.meeting_id == "abc-defg-hij"
    assert second.used_regex_fallback and second.candidate is None
    warnings = [
        r for r in caplog.records if r.name == "cuecal.extract" and r.levelname == "WARNING"
    ]
    assert len(warnings) == 1
    assert local_srv.host in warnings[0].getMessage()
    assert "degraded" in warnings[0].getMessage()


def test_tier0_runner_workers_ai_cap_is_independent_of_tier3_llm_usage(
    tmp_path, monkeypatch, caplog
):
    conn = db.connect(tmp_path / "state.db")
    now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    db.add_llm_usage(conn, "2026-10-18", input_tokens=999_999, output_tokens=1, usd=5.0)
    monkeypatch.setattr("cuecal.secrets.get_secret", lambda ref: "cf-token")
    with (
        _serving(503, {}) as local_srv,
        _serving(200, _cloud_reply(new_invite=0.9)) as cloud_srv,
    ):
        monkeypatch.setattr(decision, "WORKERS_AI_BASE_URL", cloud_srv.host)
        cfg = parse_config(
            {
                "secrets": {"cf": "cuecal-cf"},
                "llm": {"timezone": "UTC"},
                "tier0": {
                    "host": local_srv.host,
                    "retries": 0,
                    "workers_ai": {
                        "enabled": True,
                        "account_id": "acct",
                        "api_key_secret": "cf",
                        "daily_token_cap": 40,
                    },
                },
            }
        )
        runner = extract.Tier0Runner.from_config(cfg, conn=conn)
        assert runner is not None
        runner.now = lambda: now
        with caplog.at_level("WARNING", logger="cuecal.extract"):
            first = runner.extract(msg("room sync tomorrow at 2", mid="m1"))
            assert len(caplog.records) == 1
            second = runner.extract(msg("room sync tomorrow at 3", mid="m2"))
    assert not first.used_regex_fallback and first.decision is not None
    assert first.decision.route is Route.TIER1_2
    assert second.used_regex_fallback and second.candidate is None
    assert len(cloud_srv.requests) == 1
    assert len(caplog.records) == 1
    assert "degraded" in caplog.records[0].getMessage()


_ICS = (
    "BEGIN:VCALENDAR\r\nMETHOD:REQUEST\r\nBEGIN:VEVENT\r\nUID:1\r\n"
    "DTSTART:20261003T210000Z\r\nSUMMARY:X\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
)


@pytest.mark.parametrize("label", ["not_invite", "mentions_meeting"])
def test_tier0_runner_negative_decision_keeps_parsed_ics_invitation(tmp_path, label):
    conn = db.connect(tmp_path / "state.db")
    with _serving(200, _answer(**{label: 0.95})) as local_srv:
        cfg = parse_config({"tier0": {"host": local_srv.host, "retries": 0}})
        runner = extract.Tier0Runner.from_config(cfg, conn=conn)
        assert runner is not None
        with_ics = runner.extract(msg("see attached", (_ICS,)))
        without = runner.extract(msg("see attached"))
    assert with_ics.decision is not None and with_ics.decision.route in (
        Route.DROP,
        Route.NEAR_MISS,
    )
    assert with_ics.candidate is not None and with_ics.candidate.tier == "ics"
    assert without.candidate is None


def test_tier0_runner_dry_run_never_calls_workers_ai_or_records_usage(
    tmp_path, monkeypatch, caplog
):
    conn = db.connect(tmp_path / "state.db")
    monkeypatch.setattr("cuecal.secrets.get_secret", lambda ref: "cf-token")
    with (
        _serving(503, {}) as local_srv,
        _serving(200, _cloud_reply(new_invite=0.9)) as cloud_srv,
    ):
        monkeypatch.setattr(decision, "WORKERS_AI_BASE_URL", cloud_srv.host)
        cfg = parse_config(
            {
                "secrets": {"cf": "cuecal-cf"},
                "tier0": {
                    "host": local_srv.host,
                    "retries": 0,
                    "workers_ai": {"enabled": True, "account_id": "acct", "api_key_secret": "cf"},
                },
            }
        )
        runner = extract.Tier0Runner.from_config(cfg, conn=conn, dry_run=True)
        assert runner is not None
        out = runner.extract(msg("call: https://meet.google.com/abc-defg-hij"))
    assert out.used_regex_fallback
    assert cloud_srv.requests == []
    assert db.get_tier0_usage(conn, "2026-10-18") == 0


def test_tier0_runner_workers_ai_transport_failure_caps_the_day(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "state.db")
    now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    monkeypatch.setattr("cuecal.secrets.get_secret", lambda ref: "cf-token")
    with _serving(500, {}) as local_srv, _serving(500, {}) as cloud_srv:
        monkeypatch.setattr(decision, "WORKERS_AI_BASE_URL", cloud_srv.host)
        cfg = parse_config(
            {
                "secrets": {"cf": "cuecal-cf"},
                "llm": {"timezone": "UTC"},
                "tier0": {
                    "host": local_srv.host,
                    "retries": 0,
                    "workers_ai": {"enabled": True, "account_id": "acct", "api_key_secret": "cf"},
                },
            }
        )
        runner = extract.Tier0Runner.from_config(cfg, conn=conn)
        assert runner is not None
        runner.now = lambda: now
        first = runner.extract(msg("room sync", mid="m1"))
        second = runner.extract(msg("room sync", mid="m2"))
    assert first.used_regex_fallback and second.used_regex_fallback
    assert len(cloud_srv.requests) == 1
    assert db.tier0_usage_unknown(conn, "2026-10-18")
