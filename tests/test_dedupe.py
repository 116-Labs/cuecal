import sqlite3
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from cuecal.dedupe import (
    is_duplicate,
    linkless_dedupe_key,
    normalize_organizer,
    normalize_start,
    normalize_title,
)
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


def test_normalize_organizer_display_name_and_bare_email():
    assert normalize_organizer("John Doe <john@example.com>") == "john@example.com"
    assert normalize_organizer("<john@example.com>") == "john@example.com"
    assert normalize_organizer("john@example.com") == "john@example.com"
    assert normalize_organizer('"Doe, John" <john@example.com>') == "john@example.com"
    assert normalize_organizer("mailto:john@example.com") == "john@example.com"
    assert normalize_organizer(None) == ""
    assert normalize_organizer("") == ""


def test_normalize_organizer_case_and_whitespace():
    assert normalize_organizer("   JOHN.DOE@EXAMPLE.COM   ") == "john.doe@example.com"
    assert normalize_organizer("John <  JOHN.DOE@EXAMPLE.COM  >") == "john.doe@example.com"


def test_normalize_title_re_fwd_prefixes_repeated_mixed_case():
    assert normalize_title("Re: Project Kickoff") == "project kickoff"
    assert normalize_title("RE: Fwd: re: FWD: Project Kickoff") == "project kickoff"
    assert normalize_title("Fw: Project Kickoff") == "project kickoff"
    assert normalize_title("Re[2]: Project Kickoff") == "project kickoff"
    assert normalize_title("re(3): Project Kickoff") == "project kickoff"
    assert normalize_title("Re:") == ""
    assert normalize_title(None) == ""


def test_normalize_title_whitespace_and_case():
    assert normalize_title("   Project    Kickoff   Sync   ") == "project kickoff sync"
    assert normalize_title("PROJECT KICKOFF") == "project kickoff"
    assert normalize_title("Re:   Project   Kickoff  ") == "project kickoff"


def test_normalize_start_rounds_to_minute_in_utc():
    t = datetime(2026, 10, 5, 14, 30, 45, tzinfo=UTC)
    assert normalize_start(t) == "2026-10-05T14:30:00Z"
    t_naive = datetime(2026, 10, 5, 14, 30, 12)
    assert normalize_start(t_naive) == "2026-10-05T14:30:00Z"
    assert normalize_start(None) is None


def test_linkless_dedupe_key_normalization_case_differences():
    t = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)
    k1 = linkless_dedupe_key(t, "Alice@Example.com", "Project Sync")
    k2 = linkless_dedupe_key(t, "alice@example.com", "project sync")
    assert k1 == k2


def test_linkless_dedupe_key_normalization_whitespace():
    t = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)
    k1 = linkless_dedupe_key(t, "  alice@example.com  ", "  Project   Sync  ")
    k2 = linkless_dedupe_key(t, "alice@example.com", "Project Sync")
    assert k1 == k2


def test_linkless_dedupe_key_normalization_re_fwd_prefixes():
    t = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)
    k1 = linkless_dedupe_key(t, "alice@example.com", "Re: Fwd: RE: fwd: Project Sync")
    k2 = linkless_dedupe_key(t, "alice@example.com", "Project Sync")
    assert k1 == k2


def test_linkless_dedupe_key_normalization_display_name_vs_bare_email():
    t = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)
    k1 = linkless_dedupe_key(t, "Alice Smith <alice@example.com>", "Project Sync")
    k2 = linkless_dedupe_key(t, "alice@example.com", "Project Sync")
    assert k1 == k2


def test_linkless_dedupe_key_start_differing_only_by_seconds():
    t1 = datetime(2026, 10, 5, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 5, 10, 0, 45, tzinfo=UTC)
    k1 = linkless_dedupe_key(t1, "alice@example.com", "Project Sync")
    k2 = linkless_dedupe_key(t2, "alice@example.com", "Project Sync")
    assert k1 == k2


def test_linkless_dedupe_key_start_different_timezones_same_instant():
    t_utc = datetime(2026, 10, 5, 14, 0, 0, tzinfo=UTC)
    t_ny = datetime(2026, 10, 5, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    t_la = datetime(2026, 10, 5, 7, 0, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    k_utc = linkless_dedupe_key(t_utc, "alice@example.com", "Sync")
    k_ny = linkless_dedupe_key(t_ny, "alice@example.com", "Sync")
    k_la = linkless_dedupe_key(t_la, "alice@example.com", "Sync")
    assert k_utc == k_ny == k_la


def test_linkless_dedupe_key_missing_start_falls_back_to_message_id():
    key = linkless_dedupe_key(
        None, "alice@example.com", "Project Sync", source="slack", message_id="msg_999"
    )
    assert key == "slack:msg_999"

