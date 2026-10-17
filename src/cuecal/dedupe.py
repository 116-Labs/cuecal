"""Cross-source meeting deduplication engine."""

from __future__ import annotations

import difflib
import sqlite3
from datetime import timedelta

from .models import MeetingCandidate, Sink

DEFAULT_DURATION = timedelta(minutes=30)


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

    return matches_nearby_event(candidate, sink)


def matches_nearby_event(candidate: MeetingCandidate, sink: Sink) -> bool:
    """Tier 3: an event starting within ±15 min with a similar title or the same conference ID.

    A candidate without an end time is searched with the sinks' 30-minute default duration.
    An event carrying the candidate's own cuecalMeetingId is left to the sink's create.
    """
    if not candidate.start:
        return False
    margin = timedelta(minutes=15)
    end = candidate.end or candidate.start + DEFAULT_DURATION
    for ev in sink.busy(candidate.start - margin, end + margin):
        if not ev.start or abs((ev.start - candidate.start).total_seconds()) > 900:
            continue
        if candidate.meeting_id and ev.meeting_id ==candidate.meeting_id:
            continue
        if candidate.meeting_id and candidate.meeting_id in ev.conference_meeting_ids:
            return True
        if _similar_title(candidate.title, ev.title):
            return True
    return False
