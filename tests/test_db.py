import sqlite3

import pytest

from cuecal import db


def _tables(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r[0] for r in rows}


def test_migrate_from_empty(tmp_path):
    conn = db.connect(tmp_path / "sub" / "state.db")
    assert db.schema_version(conn) == len(db.MIGRATIONS)
    assert {
        "source_cursor",
        "seen_message",
        "event_link",
        "pending",
        "service_run",
        "service_stat",
    } <= _tables(conn)


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
    assert db.migrate(conn) == len(db.MIGRATIONS)
    assert "extra" in _tables(conn)


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / "state.db")
    db.migrate(conn)
    current_version = len(db.MIGRATIONS)
    monkeypatch.setattr(
        db, "MIGRATIONS", [*db.MIGRATIONS, "CREATE TABLE half (x INTEGER); BOGUS SQL;"]
    )
    with pytest.raises(sqlite3.Error):
        db.migrate(conn)
    assert not conn.in_transaction
    assert db.schema_version(conn) == current_version
    assert "half" not in _tables(conn)


def test_newer_db_rejected(tmp_path):
    conn = sqlite3.connect(tmp_path / "state.db")
    conn.execute(f"PRAGMA user_version = {len(db.MIGRATIONS) + 1}")
    with pytest.raises(RuntimeError, match="newer"):
        db.migrate(conn)


def test_service_run_and_stat_helpers(tmp_path):
    conn = db.connect(tmp_path / "state.db")
    assert db.get_last_run(conn) is None
    assert db.get_last_error(conn) is None

    run_id = db.record_run_start(conn, started_at="2026-10-03T10:00:00Z")
    assert run_id > 0
    last_run = db.get_last_run(conn)
    assert last_run["status"] == "running"
    assert last_run["started_at"] == "2026-10-03T10:00:00Z"

    db.record_run_finish(
        conn,
        run_id,
        status="success",
        finished_at="2026-10-03T10:00:05Z",
        stats=[("source", "gmail", 2), ("tier", "regex", 2)],
    )
    last_run = db.get_last_run(conn)
    assert last_run["status"] == "success"
    assert last_run["finished_at"] == "2026-10-03T10:00:05Z"
    assert db.get_last_error(conn) is None

    # Record error run
    err_run_id = db.record_run_start(conn, started_at="2026-10-03T10:10:00Z")
    db.record_run_finish(
        conn,
        err_run_id,
        status="error",
        error="Auth token expired",
        finished_at="2026-10-03T10:10:02Z",
    )
    last_err = db.get_last_error(conn)
    assert last_err["id"] == err_run_id
    assert last_err["error"] == "Auth token expired"

    # Source & tier counts
    source_counts = db.get_counts_by_source(conn)
    assert source_counts.get("gmail") == 2
    tier_counts = db.get_counts_by_tier(conn)
    assert tier_counts.get("regex") == 2
    assert tier_counts.get("deterministic") == 0


def test_pending_crud_helpers(tmp_path):
    from cuecal.models import MeetingCandidate

    conn = db.connect(tmp_path / "state.db")
    assert db.list_pending(conn) == []

    cand = MeetingCandidate(
        title="Sync Chat",
        confidence=0.6,
        meeting_id="m123",
        join_url="https://zoom.us/j/123",
        source_ref="slack:123",
    )

    pid = db.add_pending(
        conn,
        candidate=cand,
        reason="Low confidence (0.60 < 0.85)",
        source_snippet="hey let's sync",
        source="slack",
        message_id="msg1",
    )
    assert pid > 0

    item = db.get_pending(conn, pid)
    assert item is not None
    assert item["id"] == pid
    assert item["source"] == "slack"
    assert item["message_id"] == "msg1"
    assert item["confidence"] == 0.6
    assert item["reason"] == "Low confidence (0.60 < 0.85)"
    assert item["source_snippet"] == "hey let's sync"
    assert item["status"] == "pending"

    loaded_cand = MeetingCandidate.from_json(item["candidate_json"])
    assert loaded_cand.title == "Sync Chat"
    assert loaded_cand.confidence == 0.6
    assert loaded_cand.meeting_id == "m123"

    pending_list = db.list_pending(conn)
    assert len(pending_list) == 1
    assert pending_list[0]["id"] == pid

    # Update candidate
    cand.title = "Updated Sync"
    assert db.update_pending(conn, pid, candidate_json=cand.to_json()) is True
    item = db.get_pending(conn, pid)
    assert MeetingCandidate.from_json(item["candidate_json"]).title == "Updated Sync"

    # Reject
    assert db.reject_pending(conn, pid) is True
    assert db.get_pending(conn, pid)["status"] == "rejected"
    assert db.list_pending(conn, status="pending") == []
    assert len(db.list_pending(conn, status=None)) == 1

    # Add another and approve
    pid2 = db.add_pending(
        conn,
        candidate=cand,
        reason="Validation failed",
    )
    assert db.approve_pending(conn, pid2) is True
    assert db.get_pending(conn, pid2)["status"] == "approved"
    assert db.list_pending(conn, status="pending") == []

