"""Primary + secondary sink fan-out with per-sink delivery tracking and retries.

The primary sink is written first. Only once it succeeds are the secondary sinks written, each
independently. A secondary failure is recorded in ``sink_delivery`` and retried on later runs; it
never touches the primary event (or the Meet link it carries).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Mapping
from typing import Any

from cuecal import db
from cuecal.models import MeetingCandidate

logger = logging.getLogger("cuecal.sinks.fanout")

RETRY_STATUSES = ("pending", "failed")


def instantiate(plugin: Any) -> Any:
    """Registry entries may be sink classes or ready instances."""
    return plugin() if isinstance(plugin, type) else plugin


def create_on_sink(sink: Any, c: MeetingCandidate) -> str:
    """Create an event on ``sink`` and return its id."""
    if hasattr(sink, "create"):
        res = sink.create(c)
    elif hasattr(sink, "create_event"):
        res = sink.create_event(c)
    else:
        raise TypeError(f"sink {type(sink).__name__} has no create method")
    return res.id if hasattr(res, "id") else str(res)


def _link(conn: sqlite3.Connection, c: MeetingCandidate, sink_name: str, event_id: str) -> None:
    if c.meeting_id and not db.is_duplicate(conn, c.meeting_id, sink_name):
        db.record_event_link(conn, c.meeting_id, sink_name, event_id)


def _write_secondary(
    conn: sqlite3.Connection,
    delivery_id: int,
    name: str,
    plugin: Any | None,
    c: MeetingCandidate,
) -> bool:
    if plugin is None:
        db.record_sink_attempt(
            conn,
            delivery_id,
            status="failed",
            error_message=f"no sinks plugin named {name!r} is registered",
        )
        return False
    try:
        event_id = create_on_sink(instantiate(plugin), c)
    except Exception as exc:  # noqa: BLE001 - a secondary failure must not undo the primary
        logger.warning("secondary sink %r failed for %r: %s", name, c.title, exc)
        db.record_sink_attempt(
            conn, delivery_id, status="failed", error_message=f"{type(exc).__name__}: {exc}"
        )
        return False
    _link(conn, c, name, event_id)
    db.record_sink_attempt(conn, delivery_id, status="synced", sink_event_id=event_id)
    return True


def deliver(
    conn: sqlite3.Connection,
    c: MeetingCandidate,
    *,
    primary_name: str,
    primary: Any,
    secondaries: Mapping[str, Any | None] | None = None,
) -> str:
    """Write ``c`` to the primary sink, then fan out to each secondary. Returns the primary id.

    A primary failure propagates before any secondary is written. ``secondaries`` maps sink names
    to registry plugins; ``None`` marks a configured sink with no registered plugin. A secondary
    that already holds an event for this meeting is not written again.
    """
    event_id = create_on_sink(instantiate(primary), c)
    _link(conn, c, primary_name, event_id)
    candidate_json = c.to_json()
    primary_id = db.add_sink_delivery(
        conn,
        sink=primary_name,
        candidate_json=candidate_json,
        meeting_id=c.meeting_id,
        role="primary",
    )
    db.record_sink_attempt(conn, primary_id, status="synced", sink_event_id=event_id)

    for name, plugin in (secondaries or {}).items():
        if c.meeting_id and db.is_duplicate(conn, c.meeting_id, name):
            continue
        delivery_id = db.add_sink_delivery(
            conn, sink=name, candidate_json=candidate_json, meeting_id=c.meeting_id
        )
        _write_secondary(conn, delivery_id, name, plugin, c)
    return event_id


def retry_failed(
    conn: sqlite3.Connection, secondaries: Mapping[str, Any | None]
) -> dict[str, int]:
    """Retry pending/failed secondary deliveries for the configured secondary sinks.

    Deliveries for sinks no longer configured are left untouched. Returns synced/failed counts.
    """
    result = {"synced": 0, "failed": 0}
    for row in db.list_sink_deliveries(conn, statuses=RETRY_STATUSES):
        if row["role"] != "secondary" or row["sink"] not in secondaries:
            continue
        try:
            c = MeetingCandidate.from_json(row["candidate_json"])
        except (ValueError, TypeError, KeyError) as exc:
            db.record_sink_attempt(
                conn, row["id"], status="failed", error_message=f"unreadable candidate: {exc}"
            )
            result["failed"] += 1
            continue
        ok = _write_secondary(conn, row["id"], row["sink"], secondaries[row["sink"]], c)
        result["synced" if ok else "failed"] += 1
    if result["synced"] or result["failed"]:
        logger.info(
            "retried secondary sink deliveries: %d synced, %d failed",
            result["synced"],
            result["failed"],
        )
    return result
