"""SQLite state DB with an ordered, forward-only migrations mechanism."""

from __future__ import annotations

import sqlite3
from pathlib import Path

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
