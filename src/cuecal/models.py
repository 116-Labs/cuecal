"""Core data types passed between sources, extractors and sinks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Message:
    id: str
    source: str
    sender: str
    ts: datetime
    text: str
    permalink: str | None = None
    attachments: tuple[str, ...] = ()


@dataclass
class MeetingCandidate:
    title: str
    start: datetime
    end: datetime | None = None
    tz: str | None = None
    join_url: str | None = None
    meeting_id: str | None = None
    passcode: str | None = None
    attendees: list[str] = field(default_factory=list)
    source_ref: str | None = None
    confidence: float = 0.0
    tier: str = "regex"
