"""Message sources (Gmail, Slack, MCP)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cuecal.models import Message
from cuecal.sources.gmail import GmailSource

__all__ = ["GmailSource", "Source"]


@runtime_checkable
class Source(Protocol):
    name: str

    def fetch_since(self, cursor: str | None) -> tuple[list[Message], str]:
        """Fetch messages since cursor. Returns new messages and the next cursor."""
        ...
