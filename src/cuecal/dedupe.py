"""Cross-source meeting deduplication engine."""

from __future__ import annotations

import difflib
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from .models import MeetingCandidate, Sink

logger = logging.getLogger("cuecal.dedupe")

DEFAULT_DURATION = timedelta(minutes=30)


class ReconciledItem(int):
    """An int ID of a reconciled item with dict-like and property access."""

    def __new__(cls, val: int, data: dict[str, Any] | None = None) -> ReconciledItem:
        obj = super().__new__(cls, val)
        obj._data = dict(data or {})
        obj._data["id"] = int(val)
        return obj

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    @property
    def id(self) -> int:
        return int(self)


def _similar_title(t1: str, t2: str) -> bool:
    if not t1 or not t2:
        return False
    t1_lower, t2_lower = t1.lower(), t2.lower()
    if t1_lower in t2_lower or t2_lower in t1_lower:
        return True
    return difflib.SequenceMatcher(None, t1_lower, t2_lower).ratio() > 0.6


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _within_fuzzy_window(a: datetime, b: datetime) -> bool:
    return abs((_aware(a) - _aware(b)).total_seconds()) <= 900


def candidate_matches_event(cand: MeetingCandidate, ev: Any) -> bool:
    """Return whether a candidate corresponds to a calendar event."""
    ev_mid = getattr(ev, "meeting_id", None) or getattr(ev, "cuecal_meeting_id", None)
    if cand.meeting_id and ev_mid and ev_mid == cand.meeting_id:
        return True
    if cand.meeting_id and cand.meeting_id in getattr(ev, "conference_meeting_ids", ()):
        return True
    if cand.meeting_id and ev_mid:
        return False
    if cand.start and getattr(ev, "start", None):
        if _within_fuzzy_window(ev.start, cand.start):
            if _similar_title(cand.title, getattr(ev, "title", "")):
                return True
    return False


def candidates_match(c1: MeetingCandidate, c2: MeetingCandidate) -> bool:
    """Return whether two candidates describe the same meeting."""
    if c1.meeting_id and c2.meeting_id:
        return c1.meeting_id == c2.meeting_id
    if c1.start and c2.start and _within_fuzzy_window(c1.start, c2.start):
        if _similar_title(c1.title, c2.title):
            return True
    return False


def is_event_present(cand: MeetingCandidate, sink: Any | None, conn: sqlite3.Connection) -> bool:
    """Check if a calendar event corresponding to the candidate is present."""
    if cand.meeting_id:
        if sink is not None and hasattr(sink, "name"):
            row = conn.execute(
                "SELECT 1 FROM event_link WHERE meeting_id = ? AND sink = ?",
                (cand.meeting_id, sink.name),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM event_link WHERE meeting_id = ?",
                (cand.meeting_id,),
            ).fetchone()
        if row:
            return True

    if sink is None:
        return False

    if cand.meeting_id and hasattr(sink, "find_by_meeting_id"):
        try:
            if sink.find_by_meeting_id(cand.meeting_id) is not None:
                return True
        except Exception as exc:  # noqa: BLE001 - a failed lookup must not stop reconcile
            logger.warning("find_by_meeting_id failed for %r: %s", cand.title, exc)

    if hasattr(sink, "find_match"):
        try:
            if sink.find_match(cand) is not None:
                return True
        except Exception as exc:  # noqa: BLE001 - a failed lookup must not stop reconcile
            logger.warning("find_match failed for %r: %s", cand.title, exc)

    if hasattr(sink, "busy") and cand.start:
        try:
            margin = timedelta(minutes=15)
            end = cand.end or (cand.start + DEFAULT_DURATION)
            for ev in sink.busy(cand.start - margin, end + margin):
                if candidate_matches_event(cand, ev):
                    return True
        except Exception as exc:  # noqa: BLE001 - a failed lookup must not stop reconcile
            logger.warning("busy lookup failed for %r: %s", cand.title, exc)

    return False


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
        if hasattr(sink, "find_by_meeting_id"):
            existing = sink.find_by_meeting_id(candidate.meeting_id)
            if existing:
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
        ev_meeting_id = getattr(ev, "meeting_id", None) or getattr(ev, "cuecal_meeting_id", None)
        if candidate.meeting_id and ev_meeting_id == candidate.meeting_id:
            continue
        if candidate.meeting_id and candidate.meeting_id in ev.conference_meeting_ids:
            return True
        if _similar_title(candidate.title, ev.title):
            return True
    return False


def reconcile_pending(
    conn: sqlite3.Connection,
    target: Any | None = None,
    *,
    sink: Any | None = None,
    candidate: MeetingCandidate | None = None,
) -> Any:
    """Reconcile pending candidates whose corresponding event is present on the calendar."""
    if isinstance(target, int):
        from cuecal import db

        return db.update_pending(conn, target, status="reconciled")

    actual_sink = (
        target if target is not None and not isinstance(target, MeetingCandidate) else sink
    )
    actual_cand = target if isinstance(target, MeetingCandidate) else candidate

    if isinstance(actual_sink, type):
        try:
            actual_sink = actual_sink()
        except Exception as exc:  # noqa: BLE001 - reconcile still runs on local state
            logger.warning("could not instantiate sink %s: %s", actual_sink.__name__, exc)
            actual_sink = None

    from cuecal import db

    pending_items = db.list_pending(conn, status="pending")
    if not pending_items:
        return []

    reconciled: list[ReconciledItem] = []
    for item in pending_items:
        try:
            cand = MeetingCandidate.from_json(item["candidate_json"])
        except (ValueError, TypeError, KeyError):
            continue

        matched = False
        if actual_cand is not None and candidates_match(cand, actual_cand):
            matched = True
        elif is_event_present(cand, actual_sink, conn):
            matched = True

        if matched:
            db.update_pending(conn, item["id"], status="reconciled")
            reconciled_item = ReconciledItem(
                item["id"], {**item, "status": "reconciled"}
            )
            reconciled.append(reconciled_item)

    return reconciled
