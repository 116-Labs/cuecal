"""Tier 0 decision-model client against a mock llama-server (#21). No GPU, no model."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from cuecal import db
from cuecal.config import ConfigError, Tier0Config, parse_config
from cuecal.extract import decision
from cuecal.extract.decision import (
    CLASSES,
    Route,
    Tier0Client,
    Tier0Unavailable,
    build_request,
    parse_answer,
    record_near_miss,
    route_for,
)
from cuecal.extract.providers import ProviderError
from cuecal.models import Message


def answer(**probs: float) -> dict[str, Any]:
    full = {name: 0.0 for name in CLASSES} | probs
    top = max(full, key=lambda k: full[k])
    return {
        decision.QUESTION_ID: {
            "type": "choice",
            "choice": top,
            "probabilities": full,
            "confidence": full[top],
        }
    }


class MockLlamaServer:
    """A llama-server stand-in for POST /v1/systemone; ``reply`` decides each response."""

    def __init__(self, reply: Callable[[dict[str, Any]], tuple[int, Any, float]]) -> None:
        self.reply = reply
        self.requests: list[dict[str, Any]] = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server API
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with mock._lock:
                    mock.requests.append({"path": self.path, "body": body})
                    mock.active += 1
                    mock.max_active = max(mock.max_active, mock.active)
                try:
                    status, payload, delay = mock.reply(body)
                    time.sleep(delay)
                    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    with mock._lock:
                        mock.active -= 1

            def log_message(self, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.host = f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self) -> MockLlamaServer:
        serve = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        serve.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.server.shutdown()
        self.server.server_close()


@contextmanager
def serving(*replies: tuple[int, Any, float]) -> Iterator[MockLlamaServer]:
    """Serve ``replies`` in order; the last one repeats."""
    queue = list(replies)

    def reply(_body: dict[str, Any]) -> tuple[int, Any, float]:
        return queue.pop(0) if len(queue) > 1 else queue[0]

    with MockLlamaServer(reply) as server:
        yield server


def client(host: str, **kw: Any) -> Tier0Client:
    args = {"host": host, "high": 0.8, "low": 0.3, "timeout": 2.0, "retries": 1}
    return Tier0Client(**{**args, **kw})


def test_sends_one_five_class_choice_question_and_parses_probabilities():
    with serving((200, answer(new_invite=0.9, mentions_meeting=0.1), 0)) as server:
        result = client(server.host).classify("standup moved to 10, zoom link below")
    [req] = server.requests
    assert req["path"] == "/v1/systemone"
    assert req["body"]["state"] == "standup moved to 10, zoom link below"
    [(qid, question)] = req["body"]["questions"].items()
    assert qid == decision.QUESTION_ID
    assert question["type"] == "choice"
    assert list(question["criteria"]) == list(CLASSES)
    assert result.label == "new_invite"
    assert result.probability == pytest.approx(0.9)
    assert result.probabilities["mentions_meeting"] == pytest.approx(0.1)
    assert result.route is Route.TIER1_2


@pytest.mark.parametrize(
    ("probs", "label", "route"),
    [
        ({"new_invite": 0.92}, "new_invite", Route.TIER1_2),
        ({"new_invite": 0.8}, "new_invite", Route.TIER1_2),
        ({"new_invite": 0.55, "not_invite": 0.45}, "new_invite", Route.PENDING),
        ({"reschedule": 0.7}, "reschedule", Route.LOG_ONLY),
        ({"cancel": 0.9}, "cancel", Route.LOG_ONLY),
        ({"mentions_meeting": 0.85}, "mentions_meeting", Route.DROP),
        ({"not_invite": 0.97}, "not_invite", Route.DROP),
        ({"new_invite": 0.25, "not_invite": 0.2, "cancel": 0.2}, "new_invite", Route.NEAR_MISS),
        ({"not_invite": 0.28, "mentions_meeting": 0.27}, "not_invite", Route.NEAR_MISS),
    ],
)
def test_each_route_from_the_mock_server(probs, label, route):
    with serving((200, answer(**probs), 0)) as server:
        result = client(server.host).classify("text")
    assert (result.label, result.route) == (label, route)


def test_high_and_low_thresholds_are_inclusive():
    assert route_for("new_invite", 0.3, high=0.8, low=0.3) is Route.PENDING
    assert route_for("new_invite", 0.29, high=0.8, low=0.3) is Route.NEAR_MISS


def test_thresholds_come_from_config_and_drive_the_route():
    cfg = parse_config({"tier0": {"host": "http://gpu-box:8080", "high": 0.95, "low": 0.5}})
    assert cfg.tier0 == Tier0Config(host="http://gpu-box:8080", high=0.95, low=0.5)
    c = Tier0Client.from_config(cfg.tier0)
    assert (c.host, c.high, c.low, c.timeout, c.retries, c.serialize) == (
        "http://gpu-box:8080", 0.95, 0.5, 10.0, 1, True
    )
    with serving((200, answer(new_invite=0.9), 0)) as server:
        c.host = server.host
        assert c.classify("text").route is Route.PENDING


@pytest.mark.parametrize("key", [None, "answers", "result"])
def test_parse_answer_accepts_the_known_envelopes(key):
    body = answer(new_invite=0.6, not_invite=0.4)
    probs, confidence = parse_answer({key: body} if key else body)
    assert probs["new_invite"] == pytest.approx(0.6)
    assert confidence == pytest.approx(0.6)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {decision.QUESTION_ID: {"probabilities": {"new_invite": 1.0}}},
        {decision.QUESTION_ID: {"probabilities": dict.fromkeys(CLASSES, 1.5)}},
        {decision.QUESTION_ID: {"probabilities": dict.fromkeys(CLASSES, "0.2")}},
        {decision.QUESTION_ID: {"probabilities": dict.fromkeys(CLASSES, True)}},
    ],
)
def test_parse_answer_rejects_unusable_bodies(body):
    with pytest.raises(ProviderError):
        parse_answer(body)


def test_retries_a_server_error_then_succeeds():
    with serving((500, {"error": "loading"}, 0), (200, answer(cancel=0.9), 0)) as server:
        result = client(server.host, retries=1).classify("text")
    assert len(server.requests) == 2
    assert result.route is Route.LOG_ONLY


def test_each_try_is_cut_off_at_the_timeout_and_exhaustion_raises_tier0_unavailable():
    with serving((200, answer(new_invite=0.9), 1.0)) as server:
        started = time.monotonic()
        with pytest.raises(Tier0Unavailable, match="after 3 tries"):
            client(server.host, timeout=0.2, retries=2).classify("text")
        elapsed = time.monotonic() - started
    assert len(server.requests) == 3
    assert elapsed < 2.0


def test_unusable_answer_raises_tier0_unavailable_after_retries():
    with serving((200, b"not json", 0)) as server:
        with pytest.raises(Tier0Unavailable):
            client(server.host, retries=1).classify("text")
    assert len(server.requests) == 2


def test_zero_retries_means_one_attempt():
    with serving((503, {}, 0)) as server:
        with pytest.raises(Tier0Unavailable, match="after 1 tries"):
            client(server.host, retries=0).classify("text")
    assert len(server.requests) == 1


def test_unreachable_host_after_shutdown_raises_tier0_unavailable():
    with MockLlamaServer(lambda _b: (200, {}, 0)) as server:
        host = server.host
    with pytest.raises(Tier0Unavailable):
        client(host, timeout=0.5, retries=1).classify("text")


def test_non_http_status_line_raises_tier0_unavailable_after_retries():
    listener = socket.create_server(("127.0.0.1", 0))
    listener.settimeout(5)
    tries = 0

    def answer_with_ssh_banner() -> None:
        nonlocal tries
        for _ in range(2):
            conn, _addr = listener.accept()
            with conn:
                tries += 1
                conn.recv(65536)
                conn.sendall(b"SSH-2.0-OpenSSH_9.6\r\n")

    serve = threading.Thread(target=answer_with_ssh_banner, daemon=True)
    serve.start()
    host = f"http://127.0.0.1:{listener.getsockname()[1]}"
    try:
        with pytest.raises(Tier0Unavailable, match="after 2 tries"):
            client(host, retries=1).classify("text")
    finally:
        serve.join(timeout=5)
        listener.close()
    assert tries == 2


def test_never_invokes_the_regex_gate(monkeypatch):
    from cuecal.extract import tier0

    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the decision client must not call the regex gate")

    monkeypatch.setattr(tier0, "gate", boom)
    monkeypatch.setattr(tier0, "find_links", boom)
    with serving((200, answer(new_invite=0.9), 0)) as server:
        assert client(server.host).classify("https://zoom.us/j/81234567890").label == "new_invite"
    with serving((503, {}, 0)) as server:
        with pytest.raises(Tier0Unavailable):
            client(server.host, retries=0).classify("https://zoom.us/j/81234567890")


def _concurrency(serialize: bool) -> int:
    with serving((200, answer(new_invite=0.9), 0.3)) as server:
        c = client(server.host, serialize=serialize)
        threads = [threading.Thread(target=c.classify, args=("text",)) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return server.max_active


def test_requests_to_one_host_are_serialized_by_default():
    assert _concurrency(serialize=True) == 1


def test_serialization_can_be_turned_off():
    assert _concurrency(serialize=False) > 1


def test_below_threshold_decision_is_recorded_as_a_near_miss(tmp_path):
    conn = db.connect(tmp_path / "state.db")
    msg = Message(
        id="C1:1760000000.0001",
        source="slack",
        sender="Priya",
        ts=datetime(2026, 10, 26, tzinfo=UTC),
        text="maybe we should sync sometime?",
    )
    with serving((200, answer(new_invite=0.25, mentions_meeting=0.2, not_invite=0.2), 0)) as srv:
        result = client(srv.host).classify(msg.text)
    assert result.route is Route.NEAR_MISS
    record_near_miss(conn, msg, result)
    [row] = db.list_near_misses(conn)
    assert row["message_id"] == msg.id
    assert row["score"] == pytest.approx(0.25)
    assert "below the low threshold" in row["reason"]
    assert json.loads(row["details_json"])["tier0"]["new_invite"] == pytest.approx(0.25)


def test_request_shape_is_stable():
    req = build_request("hi")
    assert req == {
        "state": "hi",
        "questions": {
            "invite": {
                "type": "choice",
                "instructions": decision.INSTRUCTIONS,
                "criteria": decision.CRITERIA,
            }
        },
    }


def test_tier0_config_is_off_unless_present():
    assert parse_config({}).tier0 is None


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ({"host": "gpu-box:8080"}, "tier0.host must be an http"),
        ({"host": "http://"}, "tier0.host must be an http"),
        ({"timeout_seconds": float("inf")}, "tier0.timeout_seconds must be a finite number"),
        ({"timeout_seconds": float("nan")}, "tier0.timeout_seconds must be a finite number"),
        ({"high": 1.2}, "tier0.high must be a number"),
        ({"low": -0.1}, "tier0.low must be a number"),
        ({"high": 0.4, "low": 0.6}, "tier0.low must not exceed tier0.high"),
        ({"retries": 9}, "tier0.retries must be an integer"),
        ({"retries": True}, "tier0.retries must be an integer"),
        ({"serialize": "yes"}, "tier0.serialize must be true or false"),
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"model": "clef"}, r"unknown keys in \[tier0\]"),
    ],
)
def test_tier0_config_validation(table, message):
    with pytest.raises(ConfigError, match=message):
        parse_config({"tier0": table})
