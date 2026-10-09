"""Core data types passed between sources, extractors and sinks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "tz": self.tz,
            "join_url": self.join_url,
            "meeting_id": self.meeting_id,
            "passcode": self.passcode,
            "attendees": list(self.attendees),
            "source_ref": self.source_ref,
            "confidence": self.confidence,
            "tier": self.tier,
            "method": self.method,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MeetingCandidate:
        start = data.get("start")
        if start and isinstance(start, str):
            try:
                start = datetime.fromisoformat(start)
            except ValueError:
                from dateutil import parser as dateparser

                start = dateparser.parse(start)
        end = data.get("end")
        if end and isinstance(end, str):
            try:
                end = datetime.fromisoformat(end)
            except ValueError:
                from dateutil import parser as dateparser

                end = dateparser.parse(end)
        return cls(
            title=data.get("title", ""),
            start=start,
            end=end,
            tz=data.get("tz"),
            join_url=data.get("join_url"),
            meeting_id=data.get("meeting_id"),
            passcode=data.get("passcode"),
            attendees=list(data.get("attendees", [])),
            source_ref=data.get("source_ref"),
            confidence=float(data.get("confidence", 0.0)),
            tier=data.get("tier", "regex"),
            method=data.get("method"),
        )

    @classmethod
    def from_json(cls, raw: str) -> MeetingCandidate:
        return cls.from_dict(json.loads(raw))

@dataclass
class SinkEvent:
    id: str
    title: str
    start: datetime
    end: datetime
    cuecal_meeting_id: str | None = None
    conference_meeting_id: str | None = None

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
