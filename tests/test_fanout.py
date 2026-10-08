import pytest

from cuecal import db
from cuecal.models import MeetingCandidate
from cuecal.sinks import fanout
from cuecal.sinks.base import SinkEvent


class RecordingSink:
    def __init__(self, name, calls, *, fail=None):
        self.name = name
        self.calls = calls
        self.fail = fail

    def create(self, c):
        self.calls.append((self.name, "create", c.meeting_id))
        if self.fail:
            raise self.fail
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        return SinkEvent(id=f"{self.name}-evt", title=c.title, start=now, end=now)

    def update(self, event_id, c):
        self.calls.append((self.name, "update", event_id))

    def delete(self, event_id):  # never expected: fan-out must not roll back
        self.calls.append((self.name, "delete", event_id))


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "state.db")
    yield c
    c.close()


def _cand(mid="mtg1"):
    return MeetingCandidate(title="Sync", confidence=0.9, meeting_id=mid)


def test_primary_then_secondaries_all_synced(conn):
    calls = []
    event_id = fanout.deliver(
        conn,
        _cand(),
        primary_name="google-calendar",
        primary=RecordingSink("google-calendar", calls),
        secondaries={"zoho": RecordingSink("zoho", calls)},
    )
    assert event_id == "google-calendar-evt"
    assert calls == [("google-calendar", "create", "mtg1"), ("zoho", "create", "mtg1")]

    rows = {r["sink"]: r for r in db.list_sink_deliveries(conn)}
    assert rows["google-calendar"]["role"] == "primary"
    assert rows["google-calendar"]["status"] == "synced"
    assert rows["zoho"]["role"] == "secondary"
    assert rows["zoho"]["status"] == "synced"
    assert rows["zoho"]["sink_event_id"] == "zoho-evt"
    assert rows["zoho"]["attempts"] == 1
    assert rows["zoho"]["last_attempt_at"]
    assert db.is_duplicate(conn, "mtg1", "google-calendar")
    assert db.is_duplicate(conn, "mtg1", "zoho")


def test_secondary_failure_recorded_and_primary_kept(conn):
    calls = []
    event_id = fanout.deliver(
        conn,
        _cand(),
        primary_name="google-calendar",
        primary=RecordingSink("google-calendar", calls),
        secondaries={
            "zoho": RecordingSink("zoho", calls, fail=RuntimeError("401 unauthorized")),
            "ics": RecordingSink("ics", calls),
        },
    )
    assert event_id == "google-calendar-evt"
    # The primary event is never touched again, and a later secondary still runs.
    assert [c for c in calls if c[0] == "google-calendar"] == [
        ("google-calendar", "create", "mtg1")
    ]
    assert ("ics", "create", "mtg1") in calls

    rows = {r["sink"]: r for r in db.list_sink_deliveries(conn)}
    assert rows["google-calendar"]["status"] == "synced"
    assert rows["zoho"]["status"] == "failed"
    assert rows["zoho"]["error_message"] == "RuntimeError: 401 unauthorized"
    assert rows["ics"]["status"] == "synced"
    assert db.is_duplicate(conn, "mtg1", "google-calendar")
    assert not db.is_duplicate(conn, "mtg1", "zoho")


def test_primary_failure_skips_secondaries(conn):
    calls = []
    with pytest.raises(RuntimeError, match="primary down"):
        fanout.deliver(
            conn,
            _cand(),
            primary_name="google-calendar",
            primary=RecordingSink("google-calendar", calls, fail=RuntimeError("primary down")),
            secondaries={"zoho": RecordingSink("zoho", calls)},
        )
    assert calls == [("google-calendar", "create", "mtg1")]
    assert db.list_sink_deliveries(conn) == []


def test_synced_secondary_not_written_again(conn):
    calls = []
    fanout.deliver(
        conn,
        _cand(),
        primary_name="google-calendar",
        primary=RecordingSink("google-calendar", calls),
        secondaries={"zoho": RecordingSink("zoho", calls)},
    )
    (before,) = db.list_sink_deliveries(conn, sink="zoho")

    # A second delivery for the same meeting (e.g. approving a queued duplicate) skips zoho.
    fanout.deliver(
        conn,
        _cand(),
        primary_name="google-calendar",
        primary=RecordingSink("google-calendar", calls),
        secondaries={"zoho": RecordingSink("zoho", calls)},
    )
    assert calls.count(("zoho", "create", "mtg1")) == 1
    (after,) = db.list_sink_deliveries(conn, sink="zoho")
    assert after == before


def test_failed_secondary_written_again_on_next_delivery(conn):
    calls = []
    fanout.deliver(
        conn,
        _cand(),
        primary_name="google-calendar",
        primary=RecordingSink("google-calendar", calls),
        secondaries={"zoho": RecordingSink("zoho", calls, fail=RuntimeError("x"))},
    )
    fanout.deliver(
        conn,
        _cand(),
        primary_name="google-calendar",
        primary=RecordingSink("google-calendar", calls),
        secondaries={"zoho": RecordingSink("zoho", calls)},
    )
    assert calls.count(("zoho", "create", "mtg1")) == 2
    (row,) = db.list_sink_deliveries(conn, sink="zoho")
    assert row["status"] == "synced"
    assert row["attempts"] == 2


def test_unregistered_secondary_recorded_as_failed(conn):
    fanout.deliver(
        conn,
        _cand(),
        primary_name="google-calendar",
        primary=RecordingSink("google-calendar", []),
        secondaries={"missing": None},
    )
    (row,) = db.list_sink_deliveries(conn, sink="missing")
    assert row["status"] == "failed"
    assert "no sinks plugin named 'missing'" in row["error_message"]


def test_retry_syncs_failed_delivery(conn):
    calls = []
    fanout.deliver(
        conn,
        _cand(),
        primary_name="google-calendar",
        primary=RecordingSink("google-calendar", calls),
        secondaries={"zoho": RecordingSink("zoho", calls, fail=RuntimeError("timeout"))},
    )

    # Still failing: attempts grow, error kept.
    result = fanout.retry_failed(
        conn, {"zoho": RecordingSink("zoho", calls, fail=RuntimeError("timeout again"))}
    )
    assert result == {"synced": 0, "failed": 1}
    (row,) = db.list_sink_deliveries(conn, sink="zoho")
    assert row["attempts"] == 2
    assert row["error_message"] == "RuntimeError: timeout again"

    result = fanout.retry_failed(conn, {"zoho": RecordingSink("zoho", calls)})
    assert result == {"synced": 1, "failed": 0}
    (row,) = db.list_sink_deliveries(conn, sink="zoho")
    assert row["status"] == "synced"
    assert row["attempts"] == 3
    assert row["error_message"] is None
    assert row["sink_event_id"] == "zoho-evt"
    assert db.is_duplicate(conn, "mtg1", "zoho")
    # The primary is never re-created by a retry.
    assert calls.count(("google-calendar", "create", "mtg1")) == 1

    # Nothing left to retry.
    assert fanout.retry_failed(conn, {"zoho": RecordingSink("zoho", calls)}) == {
        "synced": 0,
        "failed": 0,
    }


def test_retry_skips_sinks_no_longer_configured(conn):
    fanout.deliver(
        conn,
        _cand(),
        primary_name="google-calendar",
        primary=RecordingSink("google-calendar", []),
        secondaries={"zoho": RecordingSink("zoho", [], fail=RuntimeError("x"))},
    )
    assert fanout.retry_failed(conn, {"ics": RecordingSink("ics", [])}) == {
        "synced": 0,
        "failed": 0,
    }
    (row,) = db.list_sink_deliveries(conn, sink="zoho")
    assert row["status"] == "failed"
    assert row["attempts"] == 1


def test_retry_records_unreadable_candidate_as_failed(conn):
    did = db.add_sink_delivery(conn, sink="zoho", candidate_json="not json", meeting_id="m2")
    assert fanout.retry_failed(conn, {"zoho": RecordingSink("zoho", [])}) == {
        "synced": 0,
        "failed": 1,
    }
    (row,) = db.list_sink_deliveries(conn, sink="zoho")
    assert row["id"] == did
    assert row["status"] == "failed"
    assert row["error_message"].startswith("unreadable candidate:")


def test_create_on_sink_supports_legacy_create_event():
    class Legacy:
        def create_event(self, c):
            return "legacy-1"

    assert fanout.create_on_sink(Legacy(), _cand()) == "legacy-1"
    with pytest.raises(TypeError, match="no create method"):
        fanout.create_on_sink(object(), _cand())


def test_delivery_without_meeting_id_is_tracked(conn):
    fanout.deliver(
        conn,
        _cand(mid=None),
        primary_name="google-calendar",
        primary=RecordingSink("google-calendar", []),
        secondaries={"zoho": RecordingSink("zoho", [], fail=RuntimeError("x"))},
    )
    (row,) = db.list_sink_deliveries(conn, sink="zoho")
    assert row["meeting_id"] is None
    assert row["status"] == "failed"
    assert fanout.retry_failed(conn, {"zoho": RecordingSink("zoho", [])}) == {
        "synced": 1,
        "failed": 0,
    }
