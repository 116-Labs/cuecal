"""Cross-source meeting deduplication engine."""

from __future__ import annotations

import difflib
import sqlite3
from datetime import timedelta

from .models import MeetingCandidate, Sink


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
                    if _similar_title(candidate.title, ev.title):
                        return True

    return False
