from datetime import UTC, datetime, timedelta

import pytest

from cuecal import db
from cuecal.models import MeetingCandidate
from cuecal.sinks import fanout
from cuecal.sinks.base import SinkEvent, SinkPermissionError


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


def test_second_primary_event_for_one_meeting_id_stays_unlinked_and_unmirrored_until_12(conn):
    class SecondInstancePrimary(RecordingSink):
        def create(self, c):
            event = super().create(c)
            return SinkEvent(
                id="google-calendar-evt-2", title=c.title, start=event.start, end=event.end
            )

    calls = []
    kwargs = {
        "primary_name": "google-calendar",
        "secondaries": {"zoho": RecordingSink("zoho", calls)},
    }
    fanout.deliver(conn, _cand(), primary=RecordingSink("google-calendar", calls), **kwargs)
    fanout.deliver(conn, _cand(), primary=SecondInstancePrimary("google-calendar", calls), **kwargs)

    assert db.get_event_link(conn, "mtg1", "google-calendar") == "google-calendar-evt"
    assert calls.count(("zoho", "create", "mtg1")) == 1


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


FUTURE = datetime(2030, 1, 7, 15, 0, tzinfo=UTC)
NOW = datetime(2030, 1, 1, tzinfo=UTC)


class Primary:
    """Primary sink whose events the test edits; current_candidate mirrors the Google sink."""

    name = "google-calendar"

    def __init__(self):
        self.events = {}
        self.read_error = None

    def create(self, c):
        self.events["g1"] = MeetingCandidate.from_dict(c.to_dict())
        return SinkEvent(id="g1", title=c.title, start=c.start, end=c.end)

    def current_candidate(self, event_id):
        if self.read_error:
            raise self.read_error
        ev = self.events.get(event_id)
        return None if ev is None else MeetingCandidate.from_dict(ev.to_dict())


class Copy(RecordingSink):
    def __init__(self, calls, *, fail_update=None, fail_delete=None):
        super().__init__("zoho-calendar", calls)
        self.fail_update = fail_update
        self.fail_delete = fail_delete

    def update(self, event_id, c):
        self.calls.append((self.name, "update", event_id, c.title, c.start))
        if self.fail_update:
            raise self.fail_update

    def delete(self, event_id):
        self.calls.append((self.name, "delete", event_id))
        if self.fail_delete:
            raise self.fail_delete


def _timed(**kw):
    base = {
        "title": "Sync",
        "start": FUTURE,
        "end": FUTURE + timedelta(hours=1),
        "join_url": "https://meet.google.com/abc-defg-hij",
        "meeting_id": "mtg1",
        "confidence": 0.9,
    }
    base.update(kw)
    return MeetingCandidate(**base)


def _delivered(conn, primary, copy, cand=None):
    fanout.deliver(
        conn,
        cand or _timed(),
        primary_name="google-calendar",
        primary=primary,
        secondaries={"zoho-calendar": copy},
    )


def _sync(conn, primary, copy, **kw):
    return fanout.sync_secondaries(
        conn,
        primary_name="google-calendar",
        primary=primary,
        secondaries={"zoho-calendar": copy},
        now=NOW,
        **kw,
    )


def test_sync_noop_when_primary_unchanged(conn):
    calls, primary = [], Primary()
    _delivered(conn, primary, Copy(calls))
    result = _sync(conn, primary, Copy(calls))
    assert result.ops == []
    assert calls == [("zoho-calendar", "create", "mtg1")]


def test_sync_propagates_title_time_and_join_url(conn):
    calls, primary = [], Primary()
    _delivered(conn, primary, Copy(calls))
    moved = FUTURE + timedelta(hours=3)
    primary.events["g1"].title = "Sync (moved)"
    primary.events["g1"].start = moved
    primary.events["g1"].end = moved + timedelta(hours=1)

    result = _sync(conn, primary, Copy(calls))
    assert [op.describe() for op in result.ops] == [
        "update zoho-calendar event zoho-calendar-evt (Sync (moved))"
    ]
    assert calls[-1] == ("zoho-calendar", "update", "zoho-calendar-evt", "Sync (moved)", moved)
    (row,) = db.list_sink_deliveries(conn, sink="zoho-calendar")
    assert row["status"] == "synced"
    assert MeetingCandidate.from_json(row["candidate_json"]).start == moved
    # The stored state now matches: a second sync writes nothing (idempotent).
    assert _sync(conn, primary, Copy(calls)).ops == []

    primary.events["g1"].join_url = "https://meet.google.com/xyz-abcd-efg"
    assert [op.action for op in _sync(conn, primary, Copy(calls)).ops] == ["update"]


def test_sync_deletes_copy_when_primary_deleted(conn):
    calls, primary = [], Primary()
    _delivered(conn, primary, Copy(calls))
    del primary.events["g1"]

    result = _sync(conn, primary, Copy(calls))
    assert [op.action for op in result.ops] == ["delete"]
    assert calls[-1] == ("zoho-calendar", "delete", "zoho-calendar-evt")
    assert db.list_sink_deliveries(conn, sink="zoho-calendar") == []
    assert not db.is_duplicate(conn, "mtg1", "zoho-calendar")
    assert _sync(conn, primary, Copy(calls)).ops == []


def test_sync_never_deletes_when_primary_read_fails(conn):
    calls, primary = [], Primary()
    _delivered(conn, primary, Copy(calls))
    primary.read_error = ConnectionError("google down")
    assert _sync(conn, primary, Copy(calls)).ops == []
    assert ("zoho-calendar", "delete", "zoho-calendar-evt") not in calls
    assert db.is_duplicate(conn, "mtg1", "zoho-calendar")


def test_sync_dry_run_plans_without_writing(conn):
    calls, primary = [], Primary()
    _delivered(conn, primary, Copy(calls))
    primary.events["g1"].title = "Renamed"
    result = _sync(conn, primary, Copy(calls), dry_run=True)
    assert [op.action for op in result.ops] == ["update"]
    assert calls == [("zoho-calendar", "create", "mtg1")]
    (row,) = db.list_sink_deliveries(conn, sink="zoho-calendar")
    assert MeetingCandidate.from_json(row["candidate_json"]).title == "Sync"

    del primary.events["g1"]
    assert [op.action for op in _sync(conn, primary, Copy(calls), dry_run=True).ops] == ["delete"]
    assert db.is_duplicate(conn, "mtg1", "zoho-calendar")


def test_sync_permission_error_is_recorded_and_reported(conn):
    calls, primary = [], Primary()
    _delivered(conn, primary, Copy(calls))
    primary.events["g1"].title = "Renamed"
    payload = '{"error": {"code": "PERMISSION_DENIED", "message": "read only"}}'
    copy = Copy(calls, fail_update=SinkPermissionError("refused", payload=payload))

    result = _sync(conn, primary, copy)
    (failure,) = result.permission_failures
    assert failure.sink == "zoho-calendar"
    assert failure.sink_event_id == "zoho-calendar-evt"
    assert failure.payload == payload
    assert failure.candidate.title == "Renamed"
    (row,) = db.list_sink_deliveries(conn, sink="zoho-calendar")
    assert row["status"] == "failed"
    assert row["error_message"] == f"permission denied: {payload}"


def test_sync_retries_failed_update_and_retry_failed_leaves_it(conn):
    calls, primary = [], Primary()
    _delivered(conn, primary, Copy(calls))
    primary.events["g1"].title = "Renamed"
    _sync(conn, primary, Copy(calls, fail_update=TimeoutError("slow")))
    (row,) = db.list_sink_deliveries(conn, sink="zoho-calendar")
    assert row["status"] == "failed"
    assert row["error_message"] == "update: TimeoutError: slow"

    # retry_failed must not create a second copy of an event that already exists.
    assert fanout.retry_failed(conn, {"zoho-calendar": Copy(calls)}) == {"synced": 0, "failed": 0}
    assert calls.count(("zoho-calendar", "create", "mtg1")) == 1

    # Nothing changed since, but the failed update is tried again and clears the error.
    assert [op.action for op in _sync(conn, primary, Copy(calls)).ops] == ["update"]
    (row,) = db.list_sink_deliveries(conn, sink="zoho-calendar")
    assert row["status"] == "synced"
    assert row["error_message"] is None


def test_sync_failed_delete_is_retried(conn):
    calls, primary = [], Primary()
    _delivered(conn, primary, Copy(calls))
    del primary.events["g1"]
    _sync(conn, primary, Copy(calls, fail_delete=RuntimeError("500")))
    (row,) = db.list_sink_deliveries(conn, sink="zoho-calendar")
    assert row["status"] == "failed"
    assert row["error_message"] == "delete: 500"

    _sync(conn, primary, Copy(calls))
    assert db.list_sink_deliveries(conn, sink="zoho-calendar") == []


def test_sync_skips_past_meetings_and_unconfigured_sinks(conn):
    calls, primary = [], Primary()
    past = NOW - timedelta(days=2)
    _delivered(conn, primary, Copy(calls), _timed(start=past, end=past + timedelta(hours=1)))
    del primary.events["g1"]
    assert _sync(conn, primary, Copy(calls)).ops == []
    assert fanout.sync_secondaries(
        conn, primary_name="google-calendar", primary=primary, secondaries={}, now=NOW
    ).ops == []


def test_sync_needs_a_readable_primary(conn):
    calls = []
    _delivered(conn, RecordingSink("google-calendar", calls), Copy(calls))
    assert _sync(conn, RecordingSink("google-calendar", calls), Copy(calls)).ops == []


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


def test_deliver_reconciles_matching_pending_candidate(conn):
    pid_match = db.add_pending(conn, candidate=_cand(mid="mtg1"), source="slack", message_id="m1")
    pid_other = db.add_pending(conn, candidate=_cand(mid="mtg2"), source="slack", message_id="m2")
    fanout.deliver(
        conn,
        _cand(mid="mtg1"),
        primary_name="google-calendar",
        primary=RecordingSink("google-calendar", []),
    )
    assert db.get_pending(conn, pid_match)["status"] == "reconciled"
    assert db.get_pending(conn, pid_other)["status"] == "pending"
    assert [p["id"] for p in db.list_pending(conn)] == [pid_other]



def test_deliver_with_sink_class_reconciles_through_calendar_lookup(conn):
    class ClassSink(RecordingSink):
        def __init__(self):
            super().__init__("google-calendar", [])

        def find_by_meeting_id(self, meeting_id):
            return object() if meeting_id == "mtg2" else None

    pid_present = db.add_pending(conn, candidate=_cand(mid="mtg2"), source="slack", message_id="m2")
    pid_absent = db.add_pending(conn, candidate=_cand(mid="mtg3"), source="slack", message_id="m3")
    fanout.deliver(conn, _cand(mid="mtg1"), primary_name="google-calendar", primary=ClassSink)
    assert db.get_pending(conn, pid_present)["status"] == "reconciled"
    assert db.get_pending(conn, pid_absent)["status"] == "pending"


def test_deliver_succeeds_when_reconcile_raises(conn, monkeypatch):
    def boom(*args, **kwargs):
        raise TypeError("can't compare")

    monkeypatch.setattr(fanout, "reconcile_pending", boom)
    event_id = fanout.deliver(
        conn, _cand(), primary_name="google-calendar", primary=RecordingSink("google-calendar", [])
    )
    assert event_id == "google-calendar-evt"
