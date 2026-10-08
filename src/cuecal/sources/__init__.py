"""Message sources (Gmail, Slack, MCP) and the calendar mirror source."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cuecal.models import Message
from cuecal.sources.calendar import CalendarSource
from cuecal.sources.gmail import GmailSource
from cuecal.sources.mcp import MCPSource
from cuecal.sources.slack import SlackSource

__all__ = ["CalendarSource", "GmailSource", "MCPSource", "SlackSource", "Source"]


@runtime_checkable
class Source(Protocol):
    """Protocol implemented by message sources."""

    name: str

    def fetch_since(self, cursor: str | None) -> tuple[list[Message], str | None]:
        """Fetch messages since cursor. Returns new messages and the next cursor."""
        ...
