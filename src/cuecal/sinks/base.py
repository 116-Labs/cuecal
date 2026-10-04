"""Base Sink interface protocol and data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from cuecal.models import MeetingCandidate


@dataclass
class SinkEvent:
    id: str
    title: str
    start: datetime
    end: datetime
    location: str | None = None
    description: str | None = None
    meeting_id: str | None = None
    html_link: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Sink(Protocol):
    """Protocol implemented by calendar sinks."""

    name: str

    def find_by_meeting_id(self, meeting_id: str) -> SinkEvent | None:
        """Look up an existing sink event by its unique meeting ID."""
        ...

    def create(self, c: MeetingCandidate) -> SinkEvent:
        """Create a new event from a MeetingCandidate (idempotent if meeting_id exists)."""
        ...

    def update(self, event_id: str, c: MeetingCandidate) -> SinkEvent:
        """Update an existing sink event with new candidate details."""
        ...

    def busy(self, start: datetime, end: datetime) -> list[SinkEvent]:
        """Return existing events overlapping the given time window."""
        ...
