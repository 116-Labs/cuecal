import sqlite3

import pytest

from cuecal import db


def _tables(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r[0] for r in rows}


def test_migrate_from_empty(tmp_path):
    conn = db.connect(tmp_path / "sub" / "state.db")
    assert db.schema_version(conn) == len(db.MIGRATIONS)
    assert {"source_cursor", "seen_message", "event_link", "pending"} <= _tables(conn)


def test_migrate_is_idempotent(tmp_path):
    conn = db.connect(tmp_path / "state.db")
    conn.execute("INSERT INTO seen_message (source, message_id) VALUES ('s', '1')")
    conn.commit()
    assert db.migrate(conn) == len(db.MIGRATIONS)
    assert conn.execute("SELECT COUNT(*) FROM seen_message").fetchone()[0] == 1


def test_applies_only_outstanding_migrations(tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / "state.db")
    db.migrate(conn)
    monkeypatch.setattr(db, "MIGRATIONS", [*db.MIGRATIONS, "CREATE TABLE extra (x INTEGER);"])
    assert db.migrate(conn) == 2
    assert "extra" in _tables(conn)


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / "state.db")
    db.migrate(conn)
    monkeypatch.setattr(
        db, "MIGRATIONS", [*db.MIGRATIONS, "CREATE TABLE half (x INTEGER); BOGUS SQL;"]
    )
    with pytest.raises(sqlite3.Error):
        db.migrate(conn)
    assert not conn.in_transaction
    assert db.schema_version(conn) == 1
    assert "half" not in _tables(conn)


def test_newer_db_rejected(tmp_path):
    conn = sqlite3.connect(tmp_path / "state.db")
    conn.execute(f"PRAGMA user_version = {len(db.MIGRATIONS) + 1}")
    with pytest.raises(RuntimeError, match="newer"):
        db.migrate(conn)
