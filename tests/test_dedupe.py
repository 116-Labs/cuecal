import sqlite3
from datetime import UTC, datetime

import pytest

from cuecal.dedupe import is_duplicate, reconcile_pending
from cuecal.models import MeetingCandidate, SinkEvent
from cuecal.sinks.google import GoogleCalendarSink


class MockSink:
    def __init__(self, name: str):
        self.name = name
        self.events: dict[str, SinkEvent] = {}
        self.by_meeting_id: dict[str, SinkEvent] = {}

    def find_by_meeting_id(self, meeting_id: str) -> SinkEvent | None:
        return self.by_meeting_id.get(meeting_id)

    def busy(self, start: datetime, end: datetime) -> list[SinkEvent]:
        # Return events overlapping with [start, end]
        overlapping = []
        for ev in self.events.values():
            if ev.start <= end and ev.end >= start:
                overlapping.append(ev)
        return overlapping

    def create(self, candidate: MeetingCandidate) -> str:
        # Mock create
        return "mock_event_id"


def test_dedupe_tier1_local_db():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE event_link (
            meeting_id TEXT NOT NULL,
            sink TEXT NOT NULL,
            sink_event_id TEXT NOT NULL,
            PRIMARY KEY (meeting_id, sink)
        )
        """
    )
    conn.execute(
        "INSERT INTO event_link (meeting_id, sink, sink_event_id) VALUES (?, ?, ?)",
        ("zoom_123", "mock", "evt_1"),
    )
    conn.commit()

    sink = MockSink("mock")
    candidate = MeetingCandidate(
        title="Weekly Sync",
        start=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
        end=datetime(2026, 10, 5, 11, 0, tzinfo=UTC),
        meeting_id="zoom_123",
    )

    # Should be true because of local db match
    assert is_duplicate(candidate, sink, conn) is True


def test_dedupe_tier2_extended_property():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE event_link (meeting_id TEXT, sink TEXT, sink_event_id TEXT)"
    )

    sink = MockSink("mock")
    ev = SinkEvent(
        id="evt_2",
        title="Sync",
        start=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
        end=datetime(2026, 10, 5, 11, 0, tzinfo=UTC),
        cuecal_meeting_id="meet_456",
    )
    sink.events["evt_2"] = ev
    sink.by_meeting_id["meet_456"] = ev

    candidate = MeetingCandidate(
        title="Sync (Different Source)",
        start=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
        end=datetime(2026, 10, 5, 11, 0, tzinfo=UTC),
        meeting_id="meet_456",
    )

    # DB is empty, but sink has it
    assert is_duplicate(candidate, sink, conn) is True


def test_dedupe_tier3_fuzzy_match():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE event_link (meeting_id TEXT, sink TEXT, sink_event_id TEXT)"
    )

    sink = MockSink("mock")
    ev = SinkEvent(
        id="evt_3",
        title="Project Kickoff",
        start=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
        end=datetime(2026, 10, 5, 11, 0, tzinfo=UTC),
    )
    sink.events["evt_3"] = ev

    # Start time is 10 min earlier, similar title
    candidate = MeetingCandidate(
        title="Project Kickoff Sync",
        start=datetime(2026, 10, 5, 9, 50, tzinfo=UTC),
        end=datetime(2026, 10, 5, 10, 50, tzinfo=UTC),
    )

    assert is_duplicate(candidate, sink, conn) is True

    # Start time is 20 min earlier (outside +/- 15 min), same title -> Not duplicate
    candidate2 = MeetingCandidate(
        title="Project Kickoff",
        start=datetime(2026, 10, 5, 9, 40, tzinfo=UTC),
        end=datetime(2026, 10, 5, 10, 40, tzinfo=UTC),
    )
    assert is_duplicate(candidate2, sink, conn) is False


class FakeCalendarClient:
    """Serves fixed raw events for the events listing, as the Calendar API would."""

    def __init__(self, items: list[dict]):
        self.items = items

    def request(self, method, path, params=None, json=None):
        if params and "privateExtendedProperty" in params:
            return {"items": []}  # nothing carries a CueCal tag
        return {"items": self.items}


def _hand_made_event(**extra) -> dict:
    return {
        "id": "hand_1",
        "summary": "Call w/ Samuel re: Acme",
        "start": {"dateTime": "2026-10-05T10:05:00Z"},
        "end": {"dateTime": "2026-10-05T11:00:00Z"},
        **extra,
    }


def _invite(meeting_id: str) -> MeetingCandidate:
    return MeetingCandidate(
        title="Sam Rao - Acme",
        start=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
        end=datetime(2026, 10, 5, 11, 0, tzinfo=UTC),
        meeting_id=meeting_id,
    )


def _no_links_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE event_link (meeting_id TEXT, sink TEXT, sink_event_id TEXT)")
    return conn


@pytest.mark.parametrize(
    ("extra", "meeting_id"),
    [
        ({"location": "https://zoom.us/j/81234567890?pwd=abc"}, "81234567890"),
        ({"description": "Join: https://zoom.us/j/81234567890"}, "81234567890"),
        (
            {
                "conferenceData": {
                    "entryPoints": [
                        {
                            "entryPointType": "video",
                            "uri": "https://meet.google.com/abc-defg-hij",
                        }
                    ]
                }
            },
            "abc-defg-hij",
        ),
        (
            {
                "location": "https://zoom.us/j/81234567890",
                "hangoutLink": "https://meet.google.com/abc-defg-hij",
                "conferenceData": {
                    "entryPoints": [
                        {
                            "entryPointType": "video",
                            "uri": "https://meet.google.com/abc-defg-hij",
                        }
                    ]
                },
            },
            "81234567890",
        ),
        (
            {
                "description": (
                    "Dial-in: https://teams.live.com/meet/9876543210\n"
                    "Join: https://zoom.us/j/81234567890"
                )
            },
            "81234567890",
        ),
    ],
)
def test_dedupe_tier3_conference_id_beats_dissimilar_title(extra, meeting_id):
    sink = GoogleCalendarSink(
        token_provider="dummy", http_client=FakeCalendarClient([_hand_made_event(**extra)])
    )
    assert is_duplicate(_invite(meeting_id), sink, _no_links_conn()) is True


def test_dedupe_tier3_different_conference_id_is_not_duplicate():
    event = _hand_made_event(location="https://zoom.us/j/81234567890")
    sink = GoogleCalendarSink(token_provider="dummy", http_client=FakeCalendarClient([event]))
    assert is_duplicate(_invite("99999999999"), sink, _no_links_conn()) is False


def test_identical_meeting_distinct_sources():
    # Test identical meeting from two distinct sources creates exactly one sink event
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE event_link (meeting_id TEXT, sink TEXT, sink_event_id TEXT)"
    )
    sink = MockSink("mock")

    # Source 1: Slack
    slack_candidate = MeetingCandidate(
        title="All Hands",
        start=datetime(2026, 10, 6, 14, 0, tzinfo=UTC),
        end=datetime(2026, 10, 6, 15, 0, tzinfo=UTC),
        meeting_id="webex_789",
    )

    is_dup_1 = is_duplicate(slack_candidate, sink, conn)
    assert is_dup_1 is False

    # Mock "creation"
    ev_id = sink.create(slack_candidate)
    conn.execute(
        "INSERT INTO event_link (meeting_id, sink, sink_event_id) VALUES (?, ?, ?)",
        ("webex_789", "mock", ev_id),
    )

    # Source 2: Email
    email_candidate = MeetingCandidate(
        title="All Hands Meeting",
        start=datetime(2026, 10, 6, 14, 0, tzinfo=UTC),
        end=datetime(2026, 10, 6, 15, 0, tzinfo=UTC),
        meeting_id="webex_789",
    )

    is_dup_2 = is_duplicate(email_candidate, sink, conn)
    assert is_dup_2 is True


def test_reconcile_pending_matching_calendar_event(tmp_path):
    from cuecal import db

    conn = db.connect(tmp_path / "state.db")
    cand = MeetingCandidate(
        title="Weekly Sync",
        start=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
        end=datetime(2026, 10, 5, 11, 0, tzinfo=UTC),
        meeting_id="meet_101",
    )
    pid = db.add_pending(conn, candidate=cand, source="slack", message_id="msg_1")

    sink = MockSink("mock")
    ev = SinkEvent(
        id="evt_101",
        title="Weekly Sync",
        start=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
        end=datetime(2026, 10, 5, 11, 0, tzinfo=UTC),
        cuecal_meeting_id="meet_101",
    )
    sink.events["evt_101"] = ev
    sink.by_meeting_id["meet_101"] = ev

    reconciled = reconcile_pending(conn, sink)
    assert len(reconciled) == 1
    assert reconciled[0]["id"] == pid
    assert db.get_pending(conn, pid)["status"] == "reconciled"
    assert db.list_pending(conn, status="pending") == []


def test_reconcile_pending_preserves_unrelated_and_retries_safely(tmp_path):
    from cuecal import db

    conn = db.connect(tmp_path / "state.db")
    cand_match = MeetingCandidate(
        title="Sprint Planning",
        start=datetime(2026, 10, 5, 9, 0, tzinfo=UTC),
        end=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
        meeting_id="plan_1",
    )
    cand_other = MeetingCandidate(
        title="Doctor Appt",
        start=datetime(2026, 10, 5, 15, 0, tzinfo=UTC),
        end=datetime(2026, 10, 5, 16, 0, tzinfo=UTC),
        meeting_id="doc_2",
    )
    pid_match = db.add_pending(conn, candidate=cand_match, source="slack", message_id="m1")
    pid_other = db.add_pending(conn, candidate=cand_other, source="slack", message_id="m2")

    sink = MockSink("mock")
    ev = SinkEvent(
        id="evt_p1",
        title="Sprint Planning",
        start=datetime(2026, 10, 5, 9, 0, tzinfo=UTC),
        end=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
        cuecal_meeting_id="plan_1",
    )
    sink.events["evt_p1"] = ev
    sink.by_meeting_id["plan_1"] = ev

    # First reconciliation: reconciles matching candidate, preserves unrelated
    reconciled = reconcile_pending(conn, sink)
    assert len(reconciled) == 1
    assert reconciled[0]["id"] == pid_match
    assert db.get_pending(conn, pid_match)["status"] == "reconciled"
    assert db.get_pending(conn, pid_other)["status"] == "pending"
    assert [p["id"] for p in db.list_pending(conn)] == [pid_other]

    # Repeated reconciliation: safe to retry, leaves unrelated pending and reconciled intact
    retry_reconciled = reconcile_pending(conn, sink)
    assert retry_reconciled == []
    assert db.get_pending(conn, pid_match)["status"] == "reconciled"
    assert db.get_pending(conn, pid_other)["status"] == "pending"
    assert [p["id"] for p in db.list_pending(conn)] == [pid_other]


def test_reconcile_pending_fuzzy_time_and_title_match(tmp_path):
    from cuecal import db

    conn = db.connect(tmp_path / "state.db")
    cand = MeetingCandidate(
        title="Design review",
        start=datetime(2026, 10, 5, 10, 5, tzinfo=UTC),
        end=datetime(2026, 10, 5, 10, 35, tzinfo=UTC),
    )
    pid = db.add_pending(conn, candidate=cand, source="gmail", message_id="g1")

    sink = MockSink("mock")
    sink.events["evt_f"] = SinkEvent(
        id="evt_f",
        title="Design Review Sync",
        start=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
        end=datetime(2026, 10, 5, 10, 30, tzinfo=UTC),
    )

    reconciled = reconcile_pending(conn, sink)
    assert len(reconciled) == 1
    assert reconciled[0]["id"] == pid
    assert db.get_pending(conn, pid)["status"] == "reconciled"


def test_reconcile_pending_conference_id_match(tmp_path):
    from cuecal import db

    conn = db.connect(tmp_path / "state.db")
    cand = MeetingCandidate(
        title="Sync",
        start=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
        end=datetime(2026, 10, 5, 10, 30, tzinfo=UTC),
        meeting_id="zoom_999",
    )
    pid = db.add_pending(conn, candidate=cand, source="slack", message_id="s1")

    sink = MockSink("mock")
    sink.events["evt_c"] = SinkEvent(
        id="evt_c",
        title="Untitled Meeting",
        start=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
        end=datetime(2026, 10, 5, 10, 30, tzinfo=UTC),
        conference_meeting_ids=("zoom_999",),
    )

    reconciled = reconcile_pending(conn, sink)
    assert len(reconciled) == 1
    assert reconciled[0]["id"] == pid
    assert db.get_pending(conn, pid)["status"] == "reconciled"



def test_reconcile_pending_naive_pending_start_does_not_raise_against_aware_candidate(tmp_path):
    from cuecal import db

    conn = db.connect(tmp_path / "state.db")
    naive = MeetingCandidate(title="Design review", start=datetime(2026, 10, 5, 10, 0))
    pid = db.add_pending(conn, candidate=naive, source="gmail", message_id="g1")
    delivered = MeetingCandidate(
        title="Design review", start=datetime(2026, 10, 5, 10, 5, tzinfo=UTC)
    )

    reconciled = reconcile_pending(conn, candidate=delivered)
    assert [r["id"] for r in reconciled] == [pid]


def test_reconcile_pending_conflicting_meeting_ids_do_not_match_by_title_and_time(tmp_path):
    from cuecal import db

    conn = db.connect(tmp_path / "state.db")
    start = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)
    pending = MeetingCandidate(title="Weekly Sync", start=start, meeting_id="zoom_111")
    pid = db.add_pending(conn, candidate=pending, source="slack", message_id="s1")
    delivered = MeetingCandidate(title="Weekly Sync", start=start, meeting_id="zoom_222")

    assert reconcile_pending(conn, candidate=delivered) == []
    assert db.get_pending(conn, pid)["status"] == "pending"


def test_reconcile_pending_sink_event_with_other_meeting_id_does_not_match_by_title_and_time(
    tmp_path,
):
    from cuecal import db

    conn = db.connect(tmp_path / "state.db")
    start = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)
    pending = MeetingCandidate(title="Weekly Sync", start=start, meeting_id="zoom_111")
    pid = db.add_pending(conn, candidate=pending, source="slack", message_id="s1")
    sink = MockSink("mock")
    sink.events["evt_other"] = SinkEvent(
        id="evt_other",
        title="Weekly Sync",
        start=start,
        end=datetime(2026, 10, 5, 10, 30, tzinfo=UTC),
        cuecal_meeting_id="zoom_222",
    )
    delivered = MeetingCandidate(title="Weekly Sync", start=start, meeting_id="zoom_222")

    assert reconcile_pending(conn, sink, candidate=delivered) == []
    assert db.get_pending(conn, pid)["status"] == "pending"


def test_reconcile_pending_sink_class_is_instantiated_for_calendar_lookups(tmp_path):
    from cuecal import db

    class NoArgSink(MockSink):
        def __init__(self):
            super().__init__("mock")

        def find_by_meeting_id(self, meeting_id):
            return SinkEvent(
                id="evt",
                title="Sync",
                start=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
                end=datetime(2026, 10, 5, 10, 30, tzinfo=UTC),
            )

    conn = db.connect(tmp_path / "state.db")
    cand = MeetingCandidate(title="Sync", meeting_id="zoom_999")
    pid = db.add_pending(conn, candidate=cand, source="slack", message_id="s1")

    reconciled = reconcile_pending(conn, NoArgSink)
    assert [r["id"] for r in reconciled] == [pid]
