"""Cross-source meeting deduplication engine."""

from __future__ import annotations

import difflib
import hashlib
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from email.utils import parseaddr

from .models import MeetingCandidate, Sink

_RE_FWD_PREFIX = re.compile(r"^(?:\s*(?:re|fwd?)(?:\[\d+\]|\(\d+\))?:\s*)+", re.IGNORECASE)


def normalize_organizer(organizer: str | None) -> str:
    """Normalize organizer to a bare, casefolded email address."""
    if not organizer:
        return ""
    text = organizer.strip()
    if text.lower().startswith("mailto:"):
        text = text[7:].strip()
    _, addr = parseaddr(text)
    email = addr if addr else text
    email = email.strip("<>\"' \t\r\n")
    return email.casefold()


def normalize_title(title: str | None) -> str:
    """Normalize title by removing leading Re:/Fwd: prefixes and collapsing whitespace."""
    if not title:
        return ""
    text = title.strip()
    while True:
        m = _RE_FWD_PREFIX.match(text)
        if not m:
            break
        text = text[m.end():].strip()
    return " ".join(text.split()).casefold()


def normalize_start(start: datetime | None) -> str | None:
    """Normalize start time rounded to the minute in UTC."""
    if start is None:
        return None
    if start.tzinfo is None:
        start_utc = start.replace(tzinfo=UTC)
    else:
        start_utc = start.astimezone(UTC)
    start_utc = start_utc.replace(second=0, microsecond=0)
    return start_utc.strftime("%Y-%m-%dT%H:%M:00Z")


def linkless_dedupe_key(
    start: datetime | MeetingCandidate | None = None,
    organizer: str | None = None,
    title: str | None = None,
    *,
    source: str = "",
    message_id: str = "",
) -> str:
    """Compute stable dedupe key for linkless invites or fall back to message-ID key."""
    if isinstance(start, MeetingCandidate):
        cand = start
        start = cand.start
        title = title if title is not None else cand.title
        if organizer is None and cand.attendees:
            organizer = cand.attendees[0]

    if start is None:
        if source and message_id:
            return f"{source}:{message_id}"
        return message_id or source or ""

    norm_start = normalize_start(start)
    norm_organizer = normalize_organizer(organizer)
    norm_title = normalize_title(title)
    payload = f"{norm_start}|{norm_organizer}|{norm_title}".encode()
    return hashlib.sha256(payload).hexdigest()


compute_dedupe_key = linkless_dedupe_key
linkless_key = linkless_dedupe_key



def _similar_title(t1: str, t2: str) -> bool:
    if not t1 or not t2:
        return False
    t1_lower, t2_lower = t1.lower(), t2.lower()
    if t1_lower in t2_lower or t2_lower in t1_lower:
        return True
    return difflib.SequenceMatcher(None, t1_lower, t2_lower).ratio() > 0.6


def is_duplicate(candidate: MeetingCandidate, sink: Sink, conn: sqlite3.Connection) -> bool:
    """Check if the candidate meeting is a duplicate of an existing event.
    
    Implements multi-tier deduplication (ADR 0008):
    1. Meeting ID match in local DB
    2. Extended property match on sink events
    3. Fuzzy match: start time within ±15 min + similar title
    """
    if candidate.meeting_id:
        # Tier 1: Meeting ID match in local DB
        row = conn.execute(
            "SELECT sink_event_id FROM event_link WHERE meeting_id = ? AND sink = ?",
            (candidate.meeting_id, sink.name)
        ).fetchone()
        if row:
            return True

        # Tier 2: Extended property match (cuecalMeetingId on sink events)
        existing = sink.find_by_meeting_id(candidate.meeting_id)
        if existing:
            # We found it in the sink, which means we missed it in the local DB.
            # We can treat it as a duplicate. Backfilling the DB is handled elsewhere if needed.
            return True

    # Tier 3: Fuzzy match: start time within ±15 min + similar title via Sink.busy
    if candidate.start and candidate.end:
        margin = timedelta(minutes=15)
        # Search a wider window
        start_window = candidate.start - margin
        end_window = candidate.end + margin
        
        busy_events = sink.busy(start_window, end_window)
        for ev in busy_events:
            if ev.start:
                diff = (ev.start - candidate.start).total_seconds()
                if abs(diff) <= 900:  # 15 minutes
                    if candidate.meeting_id and candidate.meeting_id in ev.conference_meeting_ids:
                        return True
                    if _similar_title(candidate.title, ev.title):
                        return True

    return False
