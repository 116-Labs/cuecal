import sqlite3
from datetime import UTC, datetime

from cuecal.dedupe import is_duplicate
from cuecal.models import MeetingCandidate, SinkEvent


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
