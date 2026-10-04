"""Tests for the Sink interface protocol and GoogleCalendarSink."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cuecal import secrets
from cuecal.models import MeetingCandidate
from cuecal.sinks import GoogleCalendarSink, Sink, SinkEvent
from cuecal.sinks.google import parse_calendar_event


class MockHttpClient:
    """Mock client simulating Google Calendar REST API responses."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]] = []

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((method, path, params, json))
        key = f"{method.upper()} {path}"
        if key in self.responses:
            resp = self.responses[key]
            if isinstance(resp, Exception):
                raise resp
            if callable(resp):
                return resp(params, json)
            return resp

        # Prefix matching
        for k, v in self.responses.items():
            if key.startswith(k):
                if isinstance(v, Exception):
                    raise v
                if callable(v):
                    return v(params, json)
                return v

        raise KeyError(f"Unhandled mock request: {key}")


@pytest.fixture
def sample_candidate() -> MeetingCandidate:
    start_dt = datetime(2026, 10, 15, 17, 0, 0, tzinfo=UTC)
    end_dt = datetime(2026, 10, 15, 18, 0, 0, tzinfo=UTC)
    return MeetingCandidate(
        title="Sync on Architecture",
        start=start_dt,
        end=end_dt,
        tz="UTC",
        join_url="https://meet.google.com/abc-defg-hij",
        meeting_id="abc-defg-hij",
        passcode="123456",
        attendees=["alice@example.com", "Bob"],
        source_ref="https://mail.google.com/mail/u/0/#all/msg123",
        confidence=0.95,
        tier="regex",
    )


def test_sink_protocol_compliance():
    """Test that GoogleCalendarSink satisfies the Sink runtime-checkable protocol."""
    sink = GoogleCalendarSink(token_provider="dummy-token")
    assert isinstance(sink, Sink)
    assert sink.name == "google-calendar"
    mock_ev = SinkEvent(
        id="test",
        title="Test",
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
    )
    assert mock_ev.id == "test"


def test_token_resolution(monkeypatch):
    """Test token resolution via explicit provider, secret_ref, and default google keyring."""
    # Explicit string token
    sink1 = GoogleCalendarSink(token_provider="token-123")
    assert sink1._get_token() == "token-123"

    # Callable provider
    sink2 = GoogleCalendarSink(token_provider=lambda: "callable-token")
    assert sink2._get_token() == "callable-token"

    # Keyring secret_ref
    monkeypatch.setattr(
        secrets, "get_secret", lambda ref: "custom-token" if ref == "my-gcal" else None
    )
    sink3 = GoogleCalendarSink(secret_ref="my-gcal")
    assert sink3._get_token() == "custom-token"

    # Keyring JSON credentials
    json_creds = json.dumps({"access_token": "ya29.oauth-token", "token_type": "Bearer"})
    monkeypatch.setattr(
        secrets, "get_secret", lambda ref: json_creds if ref == "google" else None
    )
    sink4 = GoogleCalendarSink()
    assert sink4._get_token() == "ya29.oauth-token"

    # Fallback to empty string when not found
    monkeypatch.setattr(secrets, "get_secret", lambda ref: None)
    sink5 = GoogleCalendarSink()
    assert sink5._get_token() == ""


def test_candidate_to_event_body(sample_candidate):
    """Test serialization of MeetingCandidate into Google Calendar event payload."""
    sink = GoogleCalendarSink(token_provider="dummy")
    body = sink._candidate_to_event_body(sample_candidate)

    assert body["summary"] == "Sync on Architecture"
    assert body["start"] == {"dateTime": "2026-10-15T17:00:00+00:00", "timeZone": "UTC"}
    assert body["end"] == {"dateTime": "2026-10-15T18:00:00+00:00", "timeZone": "UTC"}
    assert body["location"] == "https://meet.google.com/abc-defg-hij"
    assert "conferenceData" in body
    assert body["conferenceData"]["entryPoints"][0]["uri"] == "https://meet.google.com/abc-defg-hij"

    # Description verification
    desc = body["description"]
    assert "Source: https://mail.google.com/mail/u/0/#all/msg123" in desc
    assert "Join URL: https://meet.google.com/abc-defg-hij" in desc
    assert "Passcode: 123456" in desc
    assert "Meeting ID: abc-defg-hij" in desc
    assert "Attendees: alice@example.com, Bob" in desc

    # Extended property for dedupe
    assert body["extendedProperties"]["private"]["cuecalMeetingId"] == "abc-defg-hij"

    # Attendees formatting
    assert body["attendees"] == [{"email": "alice@example.com"}, {"displayName": "Bob"}]


def test_candidate_missing_start():
    """Test that formatting fails with ValueError if start is None."""
    sink = GoogleCalendarSink(token_provider="dummy")
    c = MeetingCandidate(title="No Start Time")
    with pytest.raises(ValueError, match="start is required"):
        sink._candidate_to_event_body(c)


def test_candidate_default_end_duration():
    """Test that end defaults to start + 30m when end is None."""
    sink = GoogleCalendarSink(token_provider="dummy")
    start_dt = datetime(2026, 10, 15, 10, 0, 0, tzinfo=UTC)
    c = MeetingCandidate(title="Brief Chat", start=start_dt)
    body = sink._candidate_to_event_body(c)

    assert body["end"]["dateTime"] == "2026-10-15T10:30:00+00:00"


def test_find_by_meeting_id_found():
    """Test searching for an existing event by extended property cuecalMeetingId."""
    mock_event = {
        "id": "gcal_event_01",
        "summary": "Existing Meeting",
        "start": {"dateTime": "2026-10-15T17:00:00Z"},
        "end": {"dateTime": "2026-10-15T18:00:00Z"},
        "location": "https://zoom.us/j/999",
        "extendedProperties": {"private": {"cuecalMeetingId": "meet-999"}},
        "htmlLink": "https://calendar.google.com/event?eid=gcal_event_01",
    }
    client = MockHttpClient(
        {
            "GET /calendars/primary/events": {
                "items": [mock_event],
            }
        }
    )
    sink = GoogleCalendarSink(token_provider="dummy", http_client=client)
    event = sink.find_by_meeting_id("meet-999")

    assert event is not None
    assert event.id == "gcal_event_01"
    assert event.title == "Existing Meeting"
    assert event.meeting_id == "meet-999"
    assert event.location == "https://zoom.us/j/999"
    assert len(client.calls) == 1
    assert client.calls[0][2] == {"privateExtendedProperty": "cuecalMeetingId=meet-999"}


def test_find_by_meeting_id_cancelled_ignored():
    """Test that cancelled events in search results are ignored."""
    mock_cancelled = {
        "id": "gcal_event_cancelled",
        "summary": "Old Cancelled Meeting",
        "status": "cancelled",
        "extendedProperties": {"private": {"cuecalMeetingId": "meet-999"}},
    }
    client = MockHttpClient(
        {
            "GET /calendars/primary/events": {
                "items": [mock_cancelled],
            }
        }
    )
    sink = GoogleCalendarSink(token_provider="dummy", http_client=client)
    event = sink.find_by_meeting_id("meet-999")
    assert event is None


def test_create_new_event(sample_candidate):
    """Test creating a new event via Google Calendar API POST."""
    mock_created = {
        "id": "new_gcal_100",
        "summary": sample_candidate.title,
        "start": {"dateTime": "2026-10-15T17:00:00Z"},
        "end": {"dateTime": "2026-10-15T18:00:00Z"},
        "location": sample_candidate.join_url,
        "extendedProperties": {"private": {"cuecalMeetingId": sample_candidate.meeting_id}},
        "htmlLink": "https://calendar.google.com/event?eid=new_gcal_100",
    }
    client = MockHttpClient(
        {
            "GET /calendars/primary/events": {"items": []},
            "POST /calendars/primary/events": mock_created,
        }
    )
    sink = GoogleCalendarSink(token_provider="dummy", http_client=client)
    event = sink.create(sample_candidate)

    assert event.id == "new_gcal_100"
    assert event.title == sample_candidate.title
    assert event.meeting_id == "abc-defg-hij"

    # Check request call history
    assert len(client.calls) == 2
    assert client.calls[0][0] == "GET"  # find_by_meeting_id lookup
    assert client.calls[1][0] == "POST"  # create call
    assert client.calls[1][2] == {"conferenceDataVersion": 1}
    assert client.calls[1][3]["summary"] == sample_candidate.title


def test_create_idempotent_updates_existing(sample_candidate):
    """Test create idempotency: if event already exists for meeting_id, updates it."""
    existing_event = {
        "id": "existing_event_55",
        "summary": "Old Title",
        "start": {"dateTime": "2026-10-15T16:00:00Z"},
        "end": {"dateTime": "2026-10-15T17:00:00Z"},
        "extendedProperties": {"private": {"cuecalMeetingId": sample_candidate.meeting_id}},
    }
    updated_event = {
        "id": "existing_event_55",
        "summary": sample_candidate.title,
        "start": {"dateTime": "2026-10-15T17:00:00Z"},
        "end": {"dateTime": "2026-10-15T18:00:00Z"},
        "extendedProperties": {"private": {"cuecalMeetingId": sample_candidate.meeting_id}},
    }
    client = MockHttpClient(
        {
            "GET /calendars/primary/events": {"items": [existing_event]},
            "PATCH /calendars/primary/events/existing_event_55": updated_event,
        }
    )
    sink = GoogleCalendarSink(token_provider="dummy", http_client=client)
    event = sink.create(sample_candidate)

    assert event.id == "existing_event_55"
    assert event.title == sample_candidate.title

    # Must NOT have called POST
    for method, _, _, _ in client.calls:
        assert method != "POST"

    # Called GET lookup then PATCH
    assert client.calls[0][0] == "GET"
    assert client.calls[1][0] == "PATCH"
    assert client.calls[1][1] == "/calendars/primary/events/existing_event_55"


def test_update_event(sample_candidate):
    """Test direct update of an existing event via PATCH."""
    updated_event = {
        "id": "target_event_99",
        "summary": sample_candidate.title,
        "start": {"dateTime": "2026-10-15T17:00:00Z"},
        "end": {"dateTime": "2026-10-15T18:00:00Z"},
        "extendedProperties": {"private": {"cuecalMeetingId": sample_candidate.meeting_id}},
    }
    client = MockHttpClient(
        {
            "PATCH /calendars/primary/events/target_event_99": updated_event,
        }
    )
    sink = GoogleCalendarSink(token_provider="dummy", http_client=client)
    event = sink.update("target_event_99", sample_candidate)

    assert event.id == "target_event_99"
    assert event.title == sample_candidate.title
    assert len(client.calls) == 1
    assert client.calls[0][0] == "PATCH"
    assert client.calls[0][1] == "/calendars/primary/events/target_event_99"


def test_busy_query():
    """Test busy / conflict checking against Google Calendar events."""
    start = datetime(2026, 10, 15, 14, 0, 0, tzinfo=UTC)
    end = datetime(2026, 10, 15, 18, 0, 0, tzinfo=UTC)

    mock_events = [
        {
            "id": "event_1",
            "summary": "Team Standup",
            "start": {"dateTime": "2026-10-15T14:30:00Z"},
            "end": {"dateTime": "2026-10-15T15:00:00Z"},
        },
        {
            "id": "event_2",
            "summary": "Cancelled Workshop",
            "status": "cancelled",
            "start": {"dateTime": "2026-10-15T16:00:00Z"},
            "end": {"dateTime": "2026-10-15T17:00:00Z"},
        },
        {
            "id": "event_3",
            "summary": "1:1 with Manager",
            "start": {"dateTime": "2026-10-15T17:00:00Z"},
            "end": {"dateTime": "2026-10-15T17:30:00Z"},
        },
    ]
    client = MockHttpClient(
        {
            "GET /calendars/primary/events": {"items": mock_events},
        }
    )
    sink = GoogleCalendarSink(token_provider="dummy", http_client=client)
    busy_list = sink.busy(start, end)

    # Cancelled event filtered out
    assert len(busy_list) == 2
    assert [e.id for e in busy_list] == ["event_1", "event_3"]
    assert busy_list[0].title == "Team Standup"
    assert busy_list[1].title == "1:1 with Manager"

    # Query params check
    params = client.calls[0][2]
    assert params["timeMin"] == "2026-10-15T14:00:00+00:00"
    assert params["timeMax"] == "2026-10-15T18:00:00+00:00"
    assert params["singleEvents"] == "true"
    assert params["orderBy"] == "startTime"


def test_dry_run_mode(sample_candidate):
    """Test that dry_run mode performs no mutating API calls."""
    client = MockHttpClient(
        {
            "GET /calendars/primary/events": {"items": []},
        }
    )
    sink = GoogleCalendarSink(token_provider="dummy", dry_run=True, http_client=client)

    # Create in dry_run
    created = sink.create(sample_candidate)
    assert created.id.startswith("dry-run-")
    assert created.title == sample_candidate.title
    assert created.meeting_id == sample_candidate.meeting_id

    # Update in dry_run
    updated = sink.update("real_id_123", sample_candidate)
    assert updated.id == "real_id_123"
    assert updated.title == sample_candidate.title

    # Only the find_by_meeting_id GET should have run, no POST or PATCH
    for method, _, _, _ in client.calls:
        assert method not in ("POST", "PATCH", "PUT", "DELETE")


def test_parse_calendar_event_edge_cases():
    """Test parse_calendar_event with all-day date and missing values."""
    data = {
        "id": "allday_1",
        "summary": "All Day Hackathon",
        "start": {"date": "2026-10-20"},
        "end": {"date": "2026-10-21"},
    }
    event = parse_calendar_event(data)
    assert event.id == "allday_1"
    assert event.title == "All Day Hackathon"
    assert event.start.year == 2026
    assert event.start.month == 10
    assert event.start.day == 20
    assert event.location is None
    assert event.meeting_id is None


def test_raw_urllib_request_dispatch():
    """Test raw urllib.request network path with mocked urllib.request.urlopen."""
    fake_resp = MagicMock()
    fake_resp.read.return_value = json.dumps(
        {"items": [{"id": "event_raw", "summary": "Raw Event"}]}
    ).encode("utf-8")
    fake_resp.__enter__.return_value = fake_resp

    with patch("urllib.request.urlopen", return_value=fake_resp) as mock_urlopen:
        sink = GoogleCalendarSink(token_provider="test-secret-token")
        event = sink.find_by_meeting_id("some-id")
        assert mock_urlopen.called
        req = mock_urlopen.call_args[0][0]
        assert req.headers.get("Authorization") == "Bearer test-secret-token"
        assert req.headers.get("User-agent") == "cuecal/0.1.0"
        assert event is not None
        assert event.id == "event_raw"
