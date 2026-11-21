"""Tier 0 decision-model clients: local llama-server (#21) and opt-in Workers AI (#81).

Exhaustion raises ``Tier0Unavailable`` for the degraded-mode wrapper; neither client runs the
regex gate itself."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from cuecal import db
from cuecal.config import DEFAULT_WORKERS_AI_MODEL, Tier0Config, WorkersAIConfig
from cuecal.extract.providers import (
    ProviderError,
    ProviderResult,
    UnusableAnswer,
    _is_count,
    _post_json,
)
from cuecal.models import Message

logger = logging.getLogger("cuecal.extract")

ENDPOINT = "/v1/systemone"
WORKERS_AI_BASE_URL = "https://api.cloudflare.com/client/v4"
WORKERS_AI_UNKNOWN_USAGE = "tier 0 Workers AI returned no usable token counts today; capped"
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
    result = body.get("result")
    nested = result.get("answers") if isinstance(result, dict) else None
    for container in (body, body.get("answers"), result, nested):
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


@dataclass(frozen=True)
class WorkersAIResult:
    decision: Tier0Decision
    input_tokens: int
    output_tokens: int
    usage_known: bool = True


def _workers_ai_usage(body: dict[str, Any]) -> ProviderResult:
    """Extract Workers AI token counts; missing or malformed counts report unknown, never zero."""
    result = body.get("result")
    usage = body.get("usage")
    if not isinstance(usage, dict) and isinstance(result, dict):
        usage = result.get("usage")
    if not isinstance(usage, dict):
        return ProviderResult("", usage_known=False)
    for in_key, out_key in (
        ("prompt_tokens", "completion_tokens"),
        ("input_tokens", "output_tokens"),
    ):
        if in_key in usage or out_key in usage:
            in_tok, out_tok = usage.get(in_key), usage.get(out_key)
            total = usage.get("total_tokens")
            if (
                _is_count(in_tok)
                and _is_count(out_tok)
                and (total is None or _is_count(total))
            ):
                if total is not None and total > in_tok + out_tok:
                    out_tok = total - in_tok
                return ProviderResult("", in_tok, out_tok)
            return ProviderResult("", usage_known=False)
    total = usage.get("total_tokens")
    if _is_count(total):
        return ProviderResult("", total, 0)
    return ProviderResult("", usage_known=False)


def workers_ai_cap_reason(conn: sqlite3.Connection, daily_token_cap: int, day: str) -> str | None:
    """Why Workers AI must be skipped today, or None. Unknown or unreadable usage is capped.

    The cap is soft: it is checked before a request, so the last request may overshoot it."""
    try:
        tokens = db.get_tier0_usage(conn, day)
        unknown = db.tier0_usage_unknown(conn, day)
    except (sqlite3.Error, TypeError, ValueError) as exc:
        return f"Workers AI usage unreadable ({exc}); treated as capped"
    if unknown:
        return WORKERS_AI_UNKNOWN_USAGE
    if tokens >= daily_token_cap:
        return f"Workers AI daily token cap reached ({tokens}/{daily_token_cap})"
    return None


def record_workers_ai_usage(
    conn: sqlite3.Connection,
    day: str,
    input_tokens: int,
    output_tokens: int,
    *,
    known: bool = True,
) -> None:
    if not known:
        db.mark_tier0_usage_unknown(conn, day)
        return
    db.add_tier0_usage(conn, day, input_tokens=input_tokens, output_tokens=output_tokens)


class WorkersAIClient:
    def __init__(
        self,
        *,
        account_id: str,
        api_key: Callable[[], str | None],
        high: float,
        low: float,
        model: str = DEFAULT_WORKERS_AI_MODEL,
        timeout: float = 10.0,
        base_url: str = "",
    ) -> None:
        self.account_id = account_id
        self.api_key = api_key
        self.high = high
        self.low = low
        self.model = model
        self.timeout = timeout
        self.base_url = (base_url or WORKERS_AI_BASE_URL).rstrip("/")

    @classmethod
    def from_config(
        cls, cfg: Tier0Config, workers_ai: WorkersAIConfig, api_key: Callable[[], str | None]
    ) -> WorkersAIClient:
        return cls(
            account_id=workers_ai.account_id,
            api_key=api_key,
            high=cfg.high,
            low=cfg.low,
            model=workers_ai.model,
            timeout=workers_ai.timeout_seconds,
        )

    def classify(self, text: str) -> WorkersAIResult:
        """Ask Workers AI the five-class choice question; raise ProviderError on failure."""
        try:
            key = self.api_key()
        except Exception as exc:  # noqa: BLE001 - keyring backend failures fail closed
            raise ProviderError(f"Workers AI keyring read failed: {exc}") from exc
        if not key:
            raise ProviderError("Workers AI API key missing from the keyring")
        url = f"{self.base_url}/accounts/{self.account_id}/ai/run/{self.model.lstrip('/')}"
        try:
            body = _post_json(
                url,
                {**build_request(text), "model": self.model},
                headers={"Authorization": f"Bearer {key}"},
                timeout=self.timeout,
            )
        except ProviderError as exc:
            # A request that may have been billed before it failed is unknown usage, never zero.
            raise UnusableAnswer(str(exc), ProviderResult("", usage_known=False)) from exc
        usage = _workers_ai_usage(body)
        if body.get("success") is False:
            raise UnusableAnswer("Workers AI response reported success = false", usage)
        try:
            probs, confidence = parse_answer(body)
        except ProviderError as exc:
            raise UnusableAnswer(str(exc), usage) from exc
        label = max(CLASSES, key=lambda name: probs[name])
        dec = Tier0Decision(
            label=label,
            probability=probs[label],
            probabilities=probs,
            route=route_for(label, probs[label], high=self.high, low=self.low),
            confidence=confidence,
        )
        return WorkersAIResult(
            decision=dec,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            usage_known=usage.usage_known,
        )
