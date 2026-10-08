"""Calendar sinks (Google Calendar, etc.)."""

from __future__ import annotations

from cuecal.sinks.base import Sink, SinkEvent
from cuecal.sinks.fanout import deliver, retry_failed
from cuecal.sinks.google import GoogleCalendarSink

__all__ = ["GoogleCalendarSink", "Sink", "SinkEvent", "deliver", "retry_failed"]
