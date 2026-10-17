"""Calendar sinks written through an MCP server's tools (Zoho Calendar first).

The mapping file's ``[write]`` table names the create/update/delete tools and their argument
templates. Events carry the title, time, join URL and a short description only: attendees are
never copied, so a synced copy never invites anyone.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from dateutil import parser as dateparser

from cuecal import secrets
from cuecal.dedupe import _similar_title
from cuecal.models import MeetingCandidate
from cuecal.sinks.base import SinkCredentialsError, SinkEvent, SinkPermissionError
from cuecal.sources.mcp import MCPToolError, MCPWriter, load_mapping

logger = logging.getLogger("cuecal.sinks.mcp")

# A first-time match must start this close to the candidate (#10's third dedupe key).
MATCH_WINDOW = timedelta(minutes=15)
DEFAULT_DURATION = timedelta(minutes=30)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _utc_compact(dt: datetime) -> str:
    return _aware(dt).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _aware(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        return _aware(dateparser.parse(value))
    except (ValueError, OverflowError):
        return None


def describe(c: MeetingCandidate) -> str:
    lines = []
    if c.join_url:
        lines.append(f"Join URL: {c.join_url}")
    if c.meeting_id:
        lines.append(f"Meeting ID: {c.meeting_id}")
    if c.passcode:
        lines.append(f"Passcode: {c.passcode}")
    lines.append("Synced from Google Calendar by CueCal; edits here are overwritten.")
    return "\n".join(lines)


class MCPCalendarSink:
    """Secondary calendar sink over a generic MCP mapping with a ``[write]`` table."""

    name: str = "mcp-calendar"
    mapping_name: str = ""

    def __init__(
        self,
        mapping_name: str | None = None,
        *,
        dry_run: bool = False,
        writer: MCPWriter | None = None,
    ) -> None:
        if mapping_name:
            self.mapping_name = mapping_name
        self.dry_run = dry_run
        self._writer = writer

    @property
    def writer(self) -> MCPWriter:
        if self._writer is None:
            self._writer = MCPWriter(load_mapping(self.mapping_name))
        return self._writer

    def check_credentials(self) -> None:
        mapping = self.writer.mapping
        if mapping.transport != "sse" or not mapping.auth_provider:
            return
        if not secrets.get_secret(mapping.auth_provider):
            raise SinkCredentialsError(
                f"{self.name} sink has no credentials; store an access token as keyring entry "
                f'"{mapping.auth_provider}" under service "cuecal"'
            )

    def validate(self) -> None:
        """Check the server exposes the mapped tools with schemas our arguments fit."""
        self.writer.validate()

    def _values(self, c: MeetingCandidate, event_id: str = "") -> dict[str, Any]:
        if c.start is None:
            raise ValueError("MeetingCandidate.start is required to write a calendar event")
        start = c.start
        end = c.end or (start + DEFAULT_DURATION)
        tz = c.tz or (str(start.tzinfo) if start.tzinfo is not None else "UTC")
        return {
            "title": c.title or "Meeting",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "start_utc": _utc_compact(start),
            "end_utc": _utc_compact(end),
            "tz": tz,
            "location": c.join_url or "",
            "join_url": c.join_url or "",
            "description": describe(c),
            "event_id": event_id,
        }

    def _event(self, event_id: str, c: MeetingCandidate) -> SinkEvent:
        start = c.start or datetime.now(UTC)
        return SinkEvent(
            id=event_id,
            title=c.title or "Meeting",
            start=start,
            end=c.end or (start + DEFAULT_DURATION),
            location=c.join_url,
            description=describe(c),
            meeting_id=c.meeting_id,
        )

    def _run(self, op: str, values: dict[str, Any]) -> Any:
        try:
            return getattr(self.writer, op)(values)
        except MCPToolError as exc:
            if exc.permission:
                raise SinkPermissionError(str(exc), payload=exc.raw) from exc
            raise

    def busy(self, start: datetime, end: datetime) -> list[SinkEvent]:
        """Return events in [start, end] from the mapped list tool ([] when none is mapped)."""
        values = {
            "range_start": _aware(start).isoformat(),
            "range_end": _aware(end).isoformat(),
            "range_start_utc": _utc_compact(start),
            "range_end_utc": _utc_compact(end),
        }
        events = []
        for item in self.writer.list_events(values):
            ev_start = _parse_time(item.get("start"))
            if ev_start is None:
                continue
            events.append(
                SinkEvent(
                    id=str(item["id"]),
                    title=str(item.get("title") or ""),
                    start=ev_start,
                    end=_parse_time(item.get("end")) or ev_start + DEFAULT_DURATION,
                    raw=item,
                )
            )
        return events

    def find_match(self, c: MeetingCandidate) -> SinkEvent | None:
        """First-time match: an event starting within 15 minutes with a similar title."""
        if c.start is None:
            return None
        start = _aware(c.start)
        end = _aware(c.end) if c.end else start + DEFAULT_DURATION
        for ev in self.busy(start - MATCH_WINDOW, end + MATCH_WINDOW):
            if abs(ev.start - start) <= MATCH_WINDOW and _similar_title(c.title, ev.title):
                return ev
        return None

    def find_by_meeting_id(self, meeting_id: str) -> SinkEvent | None:
        # These events carry no CueCal property; the meeting ID to event ID map is event_link.
        return None

    def create(self, c: MeetingCandidate) -> SinkEvent:
        """Patch a matching event, else create one."""
        match = self.find_match(c)
        if match is not None:
            logger.info("%s: matched existing event %s for %r", self.name, match.id, c.title)
            return self.update(match.id, c)
        if self.dry_run:
            logger.info("[DRY RUN] Would create %s event: %s at %s", self.name, c.title, c.start)
            return self._event(f"dry-run-{c.meeting_id or 'new'}", c)
        return self._event(self._run("create", self._values(c)), c)

    def update(self, event_id: str, c: MeetingCandidate) -> SinkEvent:
        if self.dry_run:
            logger.info("[DRY RUN] Would update %s event %s: %s", self.name, event_id, c.title)
        else:
            self._run("update", self._values(c, event_id))
        return self._event(event_id, c)

    def delete(self, event_id: str) -> None:
        if self.dry_run:
            logger.info("[DRY RUN] Would delete %s event %s", self.name, event_id)
            return
        self._run("delete", {"event_id": event_id})


class ZohoCalendarSink(MCPCalendarSink):
    name = "zoho-calendar"
    mapping_name = "zoho-calendar"
