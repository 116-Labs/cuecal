"""Tier 0 decision-model client (#21): one five-class choice question to a llama-server host.

Exhaustion raises ``Tier0Unavailable`` for the #81 degraded-mode wrapper; it never runs the regex
gate itself."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from cuecal import db
from cuecal.config import Tier0Config
from cuecal.extract.providers import ProviderError, _post_json
from cuecal.models import Message

logger = logging.getLogger("cuecal.extract")

ENDPOINT = "/v1/systemone"
QUESTION_ID = "invite"
CLASSES = ("new_invite", "reschedule", "cancel", "mentions_meeting", "not_invite")
INSTRUCTIONS = "What is this message, as far as the reader's calendar is concerned?"
# Option descriptions are the zero-shot wording; #47 tunes them on the eval fixtures.
CRITERIA: dict[str, str] = {
    "new_invite": "It invites the reader to a new meeting or call, or proposes a time for one.",
    "reschedule": "It moves a meeting that was already scheduled to a different time.",
    "cancel": "It cancels a meeting that was already scheduled.",
    "mentions_meeting": (
        "It talks about a meeting without scheduling one: notes, recordings, summaries or chat "
        "about a past or ongoing meeting."
    ),
    "not_invite": "It has nothing to do with meetings.",
}


class Tier0Unavailable(RuntimeError):
    """Raised when the decision-model host cannot answer after the bounded retries."""


class Route(StrEnum):
    TIER1_2 = "tier1_2"  # continue to Tier 1 / Tier 2
    PENDING = "pending"  # low-to-mid confidence invite: approval queue (ADR 0009)
    LOG_ONLY = "log_only"  # reschedule / cancel: logged until v2 (#12)
    DROP = "drop"  # mentions_meeting / not_invite: dropped, logged
    NEAR_MISS = "near_miss"  # top answer below the low threshold: dropped, recorded


@dataclass(frozen=True)
class Tier0Decision:
    label: str
    probability: float
    probabilities: dict[str, float]
    route: Route
    confidence: float | None = None


def route_for(label: str, probability: float, *, high: float, low: float) -> Route:
    """Map the top answer to a route. Any answer the model is unsure of is a near miss."""
    if probability < low:
        return Route.NEAR_MISS
    if label == "new_invite":
        return Route.TIER1_2 if probability >= high else Route.PENDING
    if label in ("reschedule", "cancel"):
        return Route.LOG_ONLY
    return Route.DROP


def build_request(text: str) -> dict[str, Any]:
    return {
        "state": text,
        "questions": {
            QUESTION_ID: {"type": "choice", "instructions": INSTRUCTIONS, "criteria": CRITERIA}
        },
    }


def _find_answer(body: dict[str, Any]) -> dict[str, Any]:
    # Clef answers are keyed by question id. The envelope around them is not documented for the
    # llama-server port, so accept the answer at the top level or under "answers"/"result".
    for container in (body, body.get("answers"), body.get("result")):
        if isinstance(container, dict) and isinstance(container.get(QUESTION_ID), dict):
            return container[QUESTION_ID]
    raise ProviderError(f"decision response has no answer for {QUESTION_ID!r}")


def parse_answer(body: dict[str, Any]) -> tuple[dict[str, float], float | None]:
    """Return (per-class probabilities, confidence) from a systemone response body."""
    answer = _find_answer(body)
    probs = answer.get("probabilities")
    if not isinstance(probs, dict) or set(probs) != set(CLASSES):
        raise ProviderError("decision answer must give a probability for each of the five classes")
    out: dict[str, float] = {}
    for name in CLASSES:
        p = probs[name]
        if isinstance(p, bool) or not isinstance(p, int | float) or not 0 <= p <= 1:
            raise ProviderError(f"probability for {name!r} must be a number between 0 and 1")
        out[name] = float(p)
    conf = answer.get("confidence")
    usable = isinstance(conf, int | float) and not isinstance(conf, bool)
    confidence = float(conf) if usable else None
    return out, confidence


_host_locks: dict[str, threading.Lock] = {}
_host_locks_guard = threading.Lock()


def _host_lock(host: str) -> threading.Lock:
    with _host_locks_guard:
        return _host_locks.setdefault(host, threading.Lock())


class Tier0Client:
    def __init__(
        self,
        *,
        host: str,
        high: float,
        low: float,
        timeout: float = 10.0,
        retries: int = 1,
        serialize: bool = True,
    ) -> None:
        self.host = host.rstrip("/")
        self.high = high
        self.low = low
        self.timeout = timeout
        self.retries = retries
        self.serialize = serialize

    @classmethod
    def from_config(cls, cfg: Tier0Config) -> Tier0Client:
        return cls(
            host=cfg.host,
            high=cfg.high,
            low=cfg.low,
            timeout=cfg.timeout_seconds,
            retries=cfg.retries,
            serialize=cfg.serialize,
        )

    def _ask(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.host}{ENDPOINT}"
        if not self.serialize:
            return _post_json(url, payload, headers={}, timeout=self.timeout)
        with _host_lock(self.host):
            return _post_json(url, payload, headers={}, timeout=self.timeout)

    def classify(self, text: str) -> Tier0Decision:
        """Ask the five-class question; raise Tier0Unavailable once ``retries`` extra tries fail."""
        payload = build_request(text)
        last: Exception | None = None
        for attempt in range(1 + self.retries):
            try:
                probs, confidence = parse_answer(self._ask(payload))
            except ProviderError as exc:
                last = exc
                logger.info("tier 0 attempt %d failed: %s", attempt + 1, exc)
                continue
            label = max(CLASSES, key=lambda name: probs[name])
            return Tier0Decision(
                label=label,
                probability=probs[label],
                probabilities=probs,
                route=route_for(label, probs[label], high=self.high, low=self.low),
                confidence=confidence,
            )
        raise Tier0Unavailable(
            f"tier 0 host {self.host} gave no usable answer after {1 + self.retries} tries: {last}"
        )


def record_near_miss(conn: sqlite3.Connection, message: Message, decision: Tier0Decision) -> int:
    """Record a below-threshold decision so it shows in `cuecal misses`."""
    return db.record_near_miss(
        conn,
        source=message.source,
        message_id=message.id,
        sender=message.sender,
        text=message.text,
        confidence=decision.probability,
        score=decision.probabilities["new_invite"],
        reason=f"tier 0: {decision.label} at {decision.probability:.2f}, below the low threshold",
        details_json=json.dumps({"tier0": decision.probabilities}),
    )
