"""Primary + secondary sink fan-out with per-sink delivery tracking and retries.

The primary sink is written first. Only once it succeeds are the secondary sinks written, each
independently. A secondary failure is recorded in ``sink_delivery`` and retried on later runs; it
never touches the primary event (or the Meet link it carries).

After the first write, `sync_secondaries` keeps each secondary copy following the primary event
one-way: edits to title, time or join URL are patched in, and a deleted or cancelled primary event
deletes the copy.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from cuecal import db
from cuecal.models import MeetingCandidate
from cuecal.sinks.base import SinkPermissionError

logger = logging.getLogger("cuecal.sinks.fanout")

RETRY_STATUSES = ("pending", "failed")
SYNC_STATUSES = ("synced", "failed")


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

    Deliveries for sinks no longer configured are left untouched, and so are copies that already
    exist (they have a sink event ID): `sync_secondaries` retries their failed updates and
    deletes. Returns synced/failed counts.
    """
    result = {"synced": 0, "failed": 0}
    for row in db.list_sink_deliveries(conn, statuses=RETRY_STATUSES):
        if row["role"] != "secondary" or row["sink"] not in secondaries:
            continue
        if row["sink_event_id"]:
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


@dataclass
class SyncOp:
    sink: str
    action: str  # "update" | "delete"
    sink_event_id: str
    title: str

    def describe(self) -> str:
        return f"{self.action} {self.sink} event {self.sink_event_id} ({self.title})"


@dataclass
class PermissionFailure:
    """A secondary refused an update; the run queues it for a human with the raw error."""

    sink: str
    sink_event_id: str
    candidate: MeetingCandidate
    payload: str


@dataclass
class SyncResult:
    ops: list[SyncOp] = field(default_factory=list)
    permission_failures: list[PermissionFailure] = field(default_factory=list)
    failed: int = 0


def _instant(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _changed(old: MeetingCandidate, new: MeetingCandidate) -> bool:
    """True when a field a secondary copy carries differs."""
    return (
        (old.title or "") != (new.title or "")
        or (old.join_url or "") != (new.join_url or "")
        or _instant(old.start) != _instant(new.start)
        or _instant(old.end) != _instant(new.end)
    )


def _is_past(c: MeetingCandidate, now: datetime) -> bool:
    start = _instant(c.start)
    if start is None:
        return False
    end = _instant(c.end) or start + timedelta(minutes=30)
    return end < now


def sync_secondaries(
    conn: sqlite3.Connection,
    *,
    primary_name: str,
    primary: Any,
    secondaries: Mapping[str, Any | None],
    dry_run: bool = False,
    now: datetime | None = None,
) -> SyncResult:
    """Make each existing secondary copy follow its primary event (one-way).

    The primary is read by the event ID recorded at creation. A deleted or cancelled primary event
    deletes the copy; a changed title, start/end or join URL patches it. A copy whose last update
    or delete failed is tried again. Meetings that already ended are left alone. A failed read of
    the primary skips that meeting, so an outage never deletes anything. Under ``dry_run`` the
    planned operations are returned and nothing is written.
    """
    result = SyncResult()
    read = getattr(instantiate(primary), "current_candidate", None)
    if read is None:
        return result
    now = now or datetime.now(UTC)

    for row in db.list_sink_deliveries(conn, statuses=SYNC_STATUSES):
        name, copy_id, meeting_id = row["sink"], row["sink_event_id"], row["meeting_id"]
        if row["role"] != "secondary" or not copy_id or not meeting_id:
            continue
        plugin = secondaries.get(name)
        if plugin is None:
            continue
        try:
            stored = MeetingCandidate.from_json(row["candidate_json"])
        except (ValueError, TypeError, KeyError):
            continue
        if _is_past(stored, now):
            continue
        primary_id = db.get_event_link(conn, meeting_id, primary_name)
        if primary_id is None:
            continue
        try:
            current = read(primary_id)
        except Exception as exc:  # noqa: BLE001 - an unreadable primary must not delete copies
            logger.warning("could not read %s event %s: %s", primary_name, primary_id, exc)
            continue

        sink = instantiate(plugin)
        if current is None:
            op = SyncOp(name, "delete", copy_id, stored.title)
            result.ops.append(op)
            if dry_run:
                continue
            try:
                sink.delete(copy_id)
            except Exception as exc:  # noqa: BLE001 - recorded and retried on the next run
                logger.warning("%s failed: %s", op.describe(), exc)
                db.record_sink_attempt(
                    conn, row["id"], status="failed", error_message=f"delete: {exc}"
                )
                result.failed += 1
                continue
            db.forget_sink_copy(conn, row["id"], meeting_id=meeting_id, sink_name=name)
            continue

        current.meeting_id = stored.meeting_id
        current.source_ref = stored.source_ref
        if row["status"] == "synced" and not _changed(stored, current):
            continue
        op = SyncOp(name, "update", copy_id, current.title)
        result.ops.append(op)
        if dry_run:
            continue
        # Store the wanted state first, so a failed update is retried with it.
        db.set_sink_delivery_candidate(conn, row["id"], current.to_json())
        try:
            sink.update(copy_id, current)
        except SinkPermissionError as exc:
            logger.warning("%s refused: %s", op.describe(), exc.payload)
            db.record_sink_attempt(
                conn, row["id"], status="failed", error_message=f"permission denied: {exc.payload}"
            )
            result.permission_failures.append(
                PermissionFailure(name, copy_id, current, exc.payload)
            )
            result.failed += 1
        except Exception as exc:  # noqa: BLE001 - recorded and retried on the next run
            logger.warning("%s failed: %s", op.describe(), exc)
            db.record_sink_attempt(
                conn,
                row["id"],
                status="failed",
                error_message=f"update: {type(exc).__name__}: {exc}",
            )
            result.failed += 1
        else:
            db.record_sink_attempt(conn, row["id"], status="synced")
    return result
