"""Tier 2: an LLM fills time, title and attendees for a partial candidate, behind a pure gate.

Tier 3 reuses the prompt, the gate and the merge. The join URL, meeting ID and passcode always
come from the Tier 0/1 regex result, never from a model.
"""

from __future__ import annotations

import dataclasses
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil import parser as dt_parser

from cuecal.extract.providers import (
    Provider,
    ProviderError,
    ProviderResult,
    ProviderUnreachable,
    UnusableAnswer,
)
from cuecal.models import MeetingCandidate, Message

RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "start": {"type": "string", "description": "ISO 8601 date-time"},
        "end": {"type": "string", "description": "ISO 8601 date-time"},
        "timezone": {"type": "string", "description": "IANA timezone name"},
        "attendees": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["title", "start", "end", "timezone", "attendees", "confidence"],
}

SYSTEM_PROMPT = (
    "You extract one meeting from a chat or email message. Answer with JSON only, matching the "
    "schema. Resolve relative dates against the received-at time. Give start and end as ISO 8601 "
    "date-times and the meeting's IANA timezone; if the message names none, use the recipient "
    "timezone. If no end is stated, assume 30 minutes. confidence is your probability (0-1) that "
    "start, end and timezone are right. Never invent a join link or meeting ID."
)


@dataclass(frozen=True)
class LLMFields:
    title: str
    start: datetime
    end: datetime
    tz: str
    attendees: list[str]
    confidence: float


@dataclass(frozen=True)
class GateResult:
    fields: LLMFields | None = None
    reason: str | None = None

    @property
    def passed(self) -> bool:
        return self.fields is not None


@dataclass
class Attempt:
    tier: str
    provider: str
    model: str
    gate: GateResult = field(default_factory=GateResult)
    input_tokens: int = 0
    output_tokens: int = 0
    usage_known: bool = True
    unreachable: bool = False
    latency_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return self.gate.passed


def _zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def system_timezone() -> str | None:
    """The host's IANA zone, from TZ or /etc/localtime; None when neither names one.

    Windows and a copied /etc/localtime name no IANA zone, so callers must not assume UTC.
    """
    env = os.environ.get("TZ", "").lstrip(":")
    if env and _zone(env):
        return env
    try:
        target = os.path.realpath("/etc/localtime")
    except OSError:
        target = ""
    if "zoneinfo/" in target:
        name = target.split("zoneinfo/", 1)[1]
        if _zone(name):
            return name
    return None


def recipient_timezone(configured: str, override: str | None = None) -> str | None:
    """A valid override, else config, else the system zone; None when no zone is known."""
    if override and _zone(override):
        return override
    return configured or system_timezone()


def _aware(dt: datetime, zone: ZoneInfo) -> datetime:
    return dt.replace(tzinfo=zone) if dt.tzinfo is None else dt.astimezone(zone)


def _fail(reason: str) -> GateResult:
    return GateResult(reason=reason)


def validate(
    raw: str,
    *,
    received_at: datetime,
    window_hours: float,
    fallback_tz: str,
    min_confidence: float,
) -> GateResult:
    """Check one model answer; every rule must hold for the result to pass."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return _fail("non-JSON output")
    if not isinstance(data, dict):
        return _fail("output is not a JSON object")
    missing = [k for k in RESPONSE_SCHEMA["required"] if k not in data]
    if missing:
        return _fail(f"schema: missing {', '.join(missing)}")
    title, attendees, confidence = data["title"], data["attendees"], data["confidence"]
    if not all(isinstance(data[k], str) for k in ("title", "start", "end", "timezone")):
        return _fail("schema: title, start, end and timezone must be strings")
    if not isinstance(attendees, list) or not all(isinstance(a, str) for a in attendees):
        return _fail("schema: attendees must be a list of strings")
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        return _fail("schema: confidence must be a number")
    if not 0 <= confidence <= 1:
        return _fail("schema: confidence must be between 0 and 1")
    try:
        start = dt_parser.isoparse(data["start"])
        end = dt_parser.isoparse(data["end"])
    except (ValueError, OverflowError):
        return _fail("schema: start and end must be ISO 8601 date-times")

    tz = data["timezone"] if _zone(data["timezone"]) else fallback_tz
    zone = _zone(tz)
    if zone is None:
        return _fail(f"no valid timezone ({data['timezone']!r}, fallback {fallback_tz!r})")
    start, end = _aware(start, zone), _aware(end, zone)
    received = _aware(received_at, zone)
    if start < received - timedelta(hours=window_hours):
        return _fail(f"start {start.isoformat()} is more than {window_hours:g}h before receipt")
    if end <= start:
        return _fail("end must be after start")
    if confidence < min_confidence:
        return _fail(f"confidence {confidence:.2f} below {min_confidence:.2f}")
    return GateResult(
        LLMFields(
            title=title.strip(),
            start=start,
            end=end,
            tz=tz,
            attendees=[a.strip() for a in attendees if a.strip()],
            confidence=float(confidence),
        )
    )


def merge(partial: MeetingCandidate, fields: LLMFields, tier: str) -> MeetingCandidate:
    """Fill the partial from the model; the regex link, meeting ID and passcode are kept."""
    return dataclasses.replace(
        partial,
        title=fields.title or partial.title,
        start=fields.start,
        end=fields.end,
        tz=fields.tz,
        attendees=fields.attendees or list(partial.attendees),
        confidence=fields.confidence,
        tier=tier,
    )


def build_prompt(message: Message, partial: MeetingCandidate, timezone: str) -> str:
    known = {
        "title": partial.title,
        "start": partial.start.isoformat() if partial.start else None,
        "end": partial.end.isoformat() if partial.end else None,
        "timezone": partial.tz,
        "attendees": partial.attendees,
        "join_url": partial.join_url,
        "meeting_id": partial.meeting_id,
    }
    return (
        f"Received at: {message.ts.isoformat()}\n"
        f"Recipient timezone: {timezone}\n"
        f"Already parsed (may be partial): {json.dumps(known)}\n"
        f"Sender: {message.sender}\n"
        f"Message:\n{message.text}"
    )


def _copy_usage(result: Attempt, usage: ProviderResult) -> None:
    result.input_tokens, result.output_tokens = usage.input_tokens, usage.output_tokens
    result.usage_known = usage.usage_known


def attempt(
    provider: Provider,
    message: Message,
    partial: MeetingCandidate,
    *,
    tier: str,
    timezone: str,
    window_hours: float,
    min_confidence: float,
) -> Attempt:
    """One provider call plus the gate; a provider failure is a failed attempt, never raised."""
    result = Attempt(tier=tier, provider=provider.name, model=provider.model)
    started = time.perf_counter()
    try:
        answer = provider.complete(
            SYSTEM_PROMPT, build_prompt(message, partial, timezone), RESPONSE_SCHEMA
        )
    except ProviderError as exc:
        result.gate = _fail(f"provider error: {exc}")
        result.unreachable = isinstance(exc, ProviderUnreachable)
        if isinstance(exc, UnusableAnswer):
            _copy_usage(result, exc.usage)
    else:
        _copy_usage(result, answer)
        result.gate = validate(
            answer.text,
            received_at=message.ts,
            window_hours=window_hours,
            fallback_tz=timezone,
            min_confidence=min_confidence,
        )
    result.latency_ms = (time.perf_counter() - started) * 1000
    return result
