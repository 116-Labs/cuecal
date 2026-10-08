"""SQLite state DB with an ordered, forward-only migrations mechanism."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cuecal.models import MeetingCandidate

# Append-only. Index + 1 is the schema version each entry brings the DB to.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE source_cursor (
        source TEXT PRIMARY KEY,
        cursor TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE seen_message (
        source TEXT NOT NULL,
        message_id TEXT NOT NULL,
        seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (source, message_id)
    );
    CREATE TABLE event_link (
        meeting_id TEXT NOT NULL,
        sink TEXT NOT NULL,
        sink_event_id TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (meeting_id, sink)
    );
    CREATE TABLE pending (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        message_id TEXT NOT NULL,
        candidate_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE service_run (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL,
        error TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE service_stat (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER,
        kind TEXT NOT NULL,
        name TEXT NOT NULL,
        count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (run_id) REFERENCES service_run (id)
    );
    """,
    """
    ALTER TABLE pending ADD COLUMN confidence REAL;
    ALTER TABLE pending ADD COLUMN reason TEXT;
    ALTER TABLE pending ADD COLUMN source_snippet TEXT;
    ALTER TABLE pending ADD COLUMN status TEXT NOT NULL DEFAULT 'pending';
    """,
]


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> int:
    """Apply outstanding migrations, each in its own transaction. Returns the new version."""
    version = schema_version(conn)
    if version > len(MIGRATIONS):
        raise RuntimeError(
            f"state DB is schema v{version}, newer than this cuecal (v{len(MIGRATIONS)})"
        )
    for target in range(version + 1, len(MIGRATIONS) + 1):
        script = f"BEGIN;\n{MIGRATIONS[target - 1]}\nPRAGMA user_version = {target};\nCOMMIT;"
        try:
            conn.executescript(script)
        except sqlite3.Error:
            if conn.in_transaction:
                conn.rollback()
            raise
    return schema_version(conn)


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    migrate(conn)
    return conn


def record_run_start(conn: sqlite3.Connection, started_at: str | None = None) -> int:
    now = started_at or datetime.now(UTC).isoformat()
    cursor = conn.execute(
        "INSERT INTO service_run (started_at, status) VALUES (?, ?)",
        (now, "running"),
    )
    conn.commit()
    return int(cursor.lastrowid)


def record_run_finish(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    status: str = "success",
    error: str | None = None,
    finished_at: str | None = None,
    stats: list[tuple[str, str, int]] | None = None,
) -> None:
    now = finished_at or datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE service_run SET finished_at = ?, status = ?, error = ? WHERE id = ?",
        (now, status, error, run_id),
    )
    if stats:
        conn.executemany(
            "INSERT INTO service_stat (run_id, kind, name, count) VALUES (?, ?, ?, ?)",
            [(run_id, kind, name, count) for kind, name, count in stats],
        )
    conn.commit()


def get_last_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
    query = (
        "SELECT id, started_at, finished_at, status, error "
        "FROM service_run ORDER BY id DESC LIMIT 1"
    )
    row = conn.execute(query).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "started_at": row[1],
        "finished_at": row[2],
        "status": row[3],
        "error": row[4],
    }


def get_last_error(conn: sqlite3.Connection) -> dict[str, Any] | None:
    query = (
        "SELECT id, started_at, finished_at, status, error "
        "FROM service_run WHERE error IS NOT NULL AND error != '' "
        "ORDER BY id DESC LIMIT 1"
    )
    row = conn.execute(query).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "started_at": row[1],
        "finished_at": row[2],
        "status": row[3],
        "error": row[4],
    }


def get_counts_by_source(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    rows = conn.execute("SELECT source, COUNT(*) FROM seen_message GROUP BY source").fetchall()
    for source, cnt in rows:
        counts[source] = cnt
    stat_rows = conn.execute(
        "SELECT name, SUM(count) FROM service_stat WHERE kind = 'source' GROUP BY name"
    ).fetchall()
    for name, cnt in stat_rows:
        counts[name] = counts.get(name, 0) + (cnt or 0)
    return counts


def get_counts_by_tier(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {
        "regex": 0,
        "deterministic": 0,
        "local": 0,
        "paid": 0,
    }
    rows = conn.execute(
        "SELECT name, SUM(count) FROM service_stat WHERE kind = 'tier' GROUP BY name"
    ).fetchall()
    for name, cnt in rows:
        counts[name] = cnt or 0
    return counts


def get_cursor(conn: sqlite3.Connection, source_name: str) -> str | None:
    row = conn.execute(
        "SELECT cursor FROM source_cursor WHERE source = ?", (source_name,)
    ).fetchone()
    return row[0] if row else None


def set_cursor(conn: sqlite3.Connection, source_name: str, cursor: str) -> None:
    conn.execute(
        "INSERT INTO source_cursor (source, cursor) VALUES (?, ?) "
        "ON CONFLICT(source) DO UPDATE SET cursor = excluded.cursor, "
        "updated_at = CURRENT_TIMESTAMP",
        (source_name, cursor),
    )
    conn.commit()


def is_duplicate(conn: sqlite3.Connection, meeting_id: str, sink_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM event_link WHERE meeting_id = ? AND sink = ?", (meeting_id, sink_name)
    ).fetchone()
    return row is not None


def record_event_link(
    conn: sqlite3.Connection, meeting_id: str, sink_name: str, sink_event_id: str
) -> None:
    conn.execute(
        "INSERT INTO event_link (meeting_id, sink, sink_event_id) VALUES (?, ?, ?)",
        (meeting_id, sink_name, sink_event_id),
    )
    conn.commit()


def add_pending(
    conn: sqlite3.Connection,
    *,
    candidate: MeetingCandidate | None = None,
    candidate_json: str | None = None,
    confidence: float | None = None,
    reason: str | None = None,
    source_snippet: str | None = None,
    source: str = "",
    message_id: str = "",
) -> int:
    if candidate is not None:
        if candidate_json is None:
            candidate_json = candidate.to_json()
        if confidence is None:
            confidence = candidate.confidence
        if not source and candidate.source_ref:
            source = candidate.source_ref
    if candidate_json is None:
        raise ValueError("candidate or candidate_json is required")

    cursor = conn.execute(
        """
        INSERT INTO pending (
            source, message_id, candidate_json, confidence, reason, source_snippet, status
        )
        VALUES (?, ?, ?, ?, ?, ?, 'pending')
        """,
        (source, message_id, candidate_json, confidence, reason, source_snippet),
    )
    conn.commit()
    return int(cursor.lastrowid)


def get_pending(conn: sqlite3.Connection, pending_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, source, message_id, candidate_json, confidence, reason, source_snippet, status,
               created_at
        FROM pending
        WHERE id = ?
        """,
        (pending_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "source": row[1],
        "message_id": row[2],
        "candidate_json": row[3],
        "confidence": row[4],
        "reason": row[5],
        "source_snippet": row[6],
        "status": row[7],
        "created_at": row[8],
    }


def list_pending(
    conn: sqlite3.Connection, *, status: str | None = "pending"
) -> list[dict[str, Any]]:
    if status is not None:
        rows = conn.execute(
            """
            SELECT id, source, message_id, candidate_json, confidence, reason,
                   source_snippet, status, created_at
            FROM pending
            WHERE status = ?
            ORDER BY id ASC
            """,
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, source, message_id, candidate_json, confidence, reason,
                   source_snippet, status, created_at
            FROM pending
            ORDER BY id ASC
            """
        ).fetchall()
    return [
        {
            "id": r[0],
            "source": r[1],
            "message_id": r[2],
            "candidate_json": r[3],
            "confidence": r[4],
            "reason": r[5],
            "source_snippet": r[6],
            "status": r[7],
            "created_at": r[8],
        }
        for r in rows
    ]


def update_pending(
    conn: sqlite3.Connection,
    pending_id: int,
    *,
    candidate_json: str | None = None,
    status: str | None = None,
) -> bool:
    clauses: list[str] = []
    params: list[Any] = []
    if candidate_json is not None:
        clauses.append("candidate_json = ?")
        params.append(candidate_json)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if not clauses:
        return False
    params.append(pending_id)
    cursor = conn.execute(
        f"UPDATE pending SET {', '.join(clauses)} WHERE id = ?",
        params,
    )
    conn.commit()
    return cursor.rowcount > 0


def approve_pending(conn: sqlite3.Connection, pending_id: int) -> bool:
    return update_pending(conn, pending_id, status="approved")


def reject_pending(conn: sqlite3.Connection, pending_id: int) -> bool:
    return update_pending(conn, pending_id, status="rejected")

