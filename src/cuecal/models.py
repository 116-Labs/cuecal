"""Core data types passed between sources, extractors and sinks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


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
    start: datetime | None = None
    end: datetime | None = None
    tz: str | None = None
    join_url: str | None = None
    meeting_id: str | None = None
    passcode: str | None = None
    attendees: list[str] = field(default_factory=list)
    source_ref: str | None = None
    confidence: float = 0.0
    tier: str = "regex"
    method: str | None = None

@dataclass
class SinkEvent:
    id: str
    title: str
    start: datetime
    end: datetime
    cuecal_meeting_id: str | None = None

class Sink(Protocol):
    name: str

    def find_by_meeting_id(self, meeting_id: str) -> SinkEvent | None:
        """Find an event by its cuecalMeetingId extended property."""
        ...

    def busy(self, start: datetime, end: datetime) -> list[SinkEvent]:
        """Return events overlapping with the given time range."""
        ...

    def create(self, candidate: MeetingCandidate) -> str:
        """Create an event and return its sink_event_id."""
        ...
