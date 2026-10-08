import base64
import json
import urllib.error
from datetime import UTC, datetime
from typing import Any

import pytest

from cuecal import secrets
from cuecal.config import ConfigError, parse_config
from cuecal.extract import extract
from cuecal.sources import GmailSource, Source
from cuecal.sources.gmail import (
    DEFAULT_GMAIL_QUERY,
    html_to_text,
    matches_query,
    parse_gmail_message,
)


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Google Inc//Google Calendar 70.9054//EN
BEGIN:VEVENT
UID:sample-uid-123@google.com
DTSTART:20261015T170000Z
DTEND:20261015T180000Z
SUMMARY:Architecture Review
DESCRIPTION:Reviewing the v1 architecture.\\nhttps://zoom.us/j/1234567890
LOCATION:https://zoom.us/j/1234567890
ATTENDEE;CN=Alice:mailto:alice@example.com
ATTENDEE;CN=Bob:mailto:bob@example.com
END:VEVENT
END:VCALENDAR"""


HTML_ZOOM_BODY = """
<html>
  <head><title>Invite</title><style>.hidden { display:none; }</style></head>
  <body>
    <p>Hi Team,</p>
    <p>You are invited to the Sprint Planning meeting.</p>
    <p>Time: Oct 10, 2026 at 2:00 PM PDT</p>
    <p>Join Zoom Meeting: <a href="https://zoom.us/j/9876543210?pwd=secret123">https://zoom.us/j/9876543210</a></p>
    <div>Meeting ID: 987 654 3210</div>
    <div>Passcode: secret123</div>
  </body>
</html>
"""


class MockHttpClient:
    """Mock client simulating Gmail REST API responses."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses = responses or {}
        self.call_history: list[tuple[str, dict[str, Any] | None]] = []

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.call_history.append((path, params))
        key = path
        if key in self.responses:
            resp = self.responses[key]
            if isinstance(resp, Exception):
                raise resp
            if callable(resp):
                return resp(params)
            return resp
        # Match by prefix
        for k, v in self.responses.items():
            if path.startswith(k):
                if isinstance(v, Exception):
                    raise v
                if callable(v):
                    return v(params)
                return v
        raise KeyError(f"Unhandled mock path: {path}")


@pytest.fixture
def mock_gmail_api():
    profile_data = {
        "emailAddress": "user@example.com",
        "messagesTotal": 42,
        "threadsTotal": 20,
        "historyId": "100500",
    }

    messages_list_data = {
        "messages": [
            {"id": "msg_html_zoom", "threadId": "thread_01"},
            {"id": "msg_ics_attach", "threadId": "thread_02"},
        ],
        "resultSizeEstimate": 2,
    }

    msg_html_zoom = {
        "id": "msg_html_zoom",
        "threadId": "thread_01",
        "historyId": "100450",
        "internalDate": "1791036000000",
        "snippet": "Sprint Planning meeting...",
        "payload": {
            "mimeType": "text/html",
            "headers": [
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "Subject", "value": "Sprint Planning"},
                {"name": "Date", "value": "Sat, 03 Oct 2026 14:00:00 +0000"},
            ],
            "body": {
                "size": len(HTML_ZOOM_BODY),
                "data": _b64(HTML_ZOOM_BODY),
            },
        },
    }

    msg_ics_attach = {
        "id": "msg_ics_attach",
        "threadId": "thread_02",
        "historyId": "100500",
        "internalDate": "1791039600000",
        "snippet": "Architecture Review invitation",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "Google Calendar <calendar-notification@google.com>"},
                {"name": "Subject", "value": "Invitation: Architecture Review"},
                {"name": "Date", "value": "Sat, 03 Oct 2026 15:00:00 +0000"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {
                        "size": 30,
                        "data": _b64("Please join the review meeting."),
                    },
                },
                {
                    "mimeType": "text/calendar",
                    "filename": "invite.ics",
                    "body": {
                        "size": len(SAMPLE_ICS),
                        "data": _b64(SAMPLE_ICS),
                    },
                },
            ],
        },
    }

    msg_new_teams = {
        "id": "msg_new_teams",
        "threadId": "thread_03",
        "historyId": "100600",
        "internalDate": "1791046800000",
        "snippet": "Teams meeting invite",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "Charlie <charlie@example.com>"},
                {"name": "Subject", "value": "Weekly 1:1"},
                {"name": "Date", "value": "Sat, 03 Oct 2026 17:00:00 +0000"},
            ],
            "body": {
                "size": 80,
                "data": _b64(
                    "Join Teams: https://teams.microsoft.com/l/meetup-join/19%3ameeting_xyz\n"
                    "Time: Oct 11, 2026 at 10:00 AM PDT"
                ),
            },
        },
    }

    history_with_messages = {
        "historyId": "100600",
        "history": [
            {
                "id": "100501",
                "messagesAdded": [{"message": {"id": "msg_new_teams", "threadId": "thread_03"}}],
            }
        ],
    }

    history_empty = {
        "historyId": "100600",
    }

    responses = {
        "/users/me/profile": profile_data,
        "/users/me/messages/msg_html_zoom": msg_html_zoom,
        "/users/me/messages/msg_ics_attach": msg_ics_attach,
        "/users/me/messages/msg_new_teams": msg_new_teams,
        "/users/me/messages": messages_list_data,
        "/users/me/history": history_with_messages,
    }
    client = MockHttpClient(responses)
    return client, {
        "profile": profile_data,
        "msg_html_zoom": msg_html_zoom,
        "msg_ics_attach": msg_ics_attach,
        "msg_new_teams": msg_new_teams,
        "history_with_messages": history_with_messages,
        "history_empty": history_empty,
    }


def test_source_protocol_compliance():
    adapter = GmailSource()
    assert isinstance(adapter, Source)
    assert adapter.name == "gmail"


def test_html_to_text_preserves_links_and_formatting():
    html_input = """
    <html>
      <head><style>body { font-family: sans-serif; }</style></head>
      <body>
        <h1>Team Meeting</h1>
        <p>Hello everyone,<br>Please find the meeting details below:</p>
        <p>Join: <a href="https://meet.google.com/xyz-uvw-rst">Google Meet Link</a></p>
        <p>Direct URL: <a href="https://zoom.us/j/123456789">https://zoom.us/j/123456789</a></p>
      </body>
    </html>
    """
    text = html_to_text(html_input)
    assert "Team Meeting" in text
    assert "Google Meet Link (https://meet.google.com/xyz-uvw-rst)" in text
    assert "https://zoom.us/j/123456789" in text
    assert "font-family" not in text


def test_parse_gmail_message_html_only():
    data = {
        "id": "18a123456789abcd",
        "internalDate": "1727960000000",
        "payload": {
            "headers": [
                {"name": "From", "value": "Organizer <org@example.com>"},
                {"name": "Subject", "value": "Project Kickoff"},
                {"name": "Date", "value": "Fri, 03 Oct 2026 12:00:00 -0000"},
            ],
            "mimeType": "text/html",
            "body": {
                "data": _b64("<p>Join Zoom: <a href='https://zoom.us/j/111222333'>Link</a></p>"),
            },
        },
    }
    msg = parse_gmail_message(data)
    assert msg.id == "18a123456789abcd"
    assert msg.source == "gmail"
    assert msg.sender == "Organizer <org@example.com>"
    assert msg.permalink == "https://mail.google.com/mail/u/0/#all/18a123456789abcd"
    assert "https://zoom.us/j/111222333" in msg.text
    assert msg.attachments == ()
    assert msg.ts == datetime.fromtimestamp(1727960000, tz=UTC)


def test_parse_gmail_message_with_ics_attachment():
    data = {
        "id": "18b987654321fedc",
        "internalDate": "1727970000000",
        "payload": {
            "headers": [
                {"name": "From", "value": "Calendar <calendar@example.com>"},
                {"name": "Subject", "value": "Meeting Invitation"},
            ],
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64("Please find the invite attached.")},
                },
                {
                    "mimeType": "text/calendar",
                    "filename": "event.ics",
                    "body": {"data": _b64(SAMPLE_ICS)},
                },
            ],
        },
    }
    msg = parse_gmail_message(data)
    assert msg.id == "18b987654321fedc"
    assert len(msg.attachments) == 1
    assert "BEGIN:VCALENDAR" in msg.attachments[0]
    assert "UID:sample-uid-123@google.com" in msg.attachments[0]

    # End-to-end extraction through extractor
    candidate = extract(msg)
    assert candidate is not None
    assert candidate.title == "Architecture Review"
    assert candidate.join_url == "https://zoom.us/j/1234567890"
    assert candidate.tier == "ics"


def test_matches_query_filtering():
    msg_zoom = {
        "snippet": "Zoom link",
        "payload": {
            "headers": [{"name": "Subject", "value": "Call"}],
            "body": {"data": _b64("Join https://zoom.us/j/123456")},
            "mimeType": "text/plain",
        },
    }
    msg_unrelated = {
        "snippet": "Your receipt",
        "payload": {
            "headers": [{"name": "Subject", "value": "Receipt for order"}],
            "body": {"data": _b64("Thank you for your purchase.")},
            "mimeType": "text/plain",
        },
    }
    msg_ics = {
        "snippet": "Invite",
        "payload": {
            "headers": [{"name": "Subject", "value": "Sync"}],
            "parts": [
                {
                    "mimeType": "text/calendar",
                    "filename": "invite.ics",
                    "body": {"data": _b64("BEGIN:VCALENDAR")},
                }
            ],
        },
    }

    narrowing_query = "zoom.us OR meet.google.com OR teams.microsoft.com OR filename:ics"
    assert matches_query(msg_zoom, narrowing_query) is True
    assert matches_query(msg_ics, narrowing_query) is True
    assert matches_query(msg_unrelated, narrowing_query) is False
    assert matches_query(msg_unrelated, DEFAULT_GMAIL_QUERY) is True
    assert matches_query(msg_unrelated, None) is True
    assert matches_query(msg_unrelated, "") is True
    assert matches_query(msg_unrelated, "receipt OR invoice") is True


def test_contract_initial_fetch(mock_gmail_api):
    client, _ = mock_gmail_api
    source = GmailSource(token_provider="dummy-token", http_client=client)

    messages, cursor = source.fetch_since(None)

    assert len(messages) == 2
    assert cursor == "100500"  # Profile historyId

    msg1, msg2 = messages
    assert msg1.id == "msg_html_zoom"
    assert "https://zoom.us/j/9876543210" in msg1.text
    assert msg1.sender == "Alice <alice@example.com>"

    assert msg2.id == "msg_ics_attach"
    assert len(msg2.attachments) == 1
    assert "BEGIN:VCALENDAR" in msg2.attachments[0]

    # Verify API queries
    paths_called = [p for p, _ in client.call_history]
    assert "/users/me/messages" in paths_called
    assert "/users/me/profile" in paths_called


def test_contract_incremental_fetch_advances_cursor(mock_gmail_api):
    client, _ = mock_gmail_api
    source = GmailSource(token_provider="dummy-token", http_client=client)

    # Initial fetch at cursor 100500
    messages, next_cursor = source.fetch_since("100500")

    assert len(messages) == 1
    assert next_cursor == "100600"
    assert messages[0].id == "msg_new_teams"
    assert "teams.microsoft.com" in messages[0].text


def test_contract_incremental_fetch_no_duplicates_on_rerun(mock_gmail_api):
    client, fixtures = mock_gmail_api
    client.responses["/users/me/history"] = fixtures["history_empty"]
    source = GmailSource(token_provider="dummy-token", http_client=client)

    messages, cursor = source.fetch_since("100600")

    assert messages == []
    assert cursor == "100600"


def test_contract_history_expired_fallback(mock_gmail_api):
    client, _ = mock_gmail_api

    class Http404Error(urllib.error.HTTPError):
        def __init__(self):
            super().__init__(
                url="https://gmail.googleapis.com/gmail/v1/users/me/history",
                code=404,
                msg="historyId not found",
                hdrs={},
                fp=None,
            )

    client.responses["/users/me/history"] = Http404Error()
    source = GmailSource(token_provider="dummy-token", http_client=client)

    # Should fall back to initial fetch
    messages, cursor = source.fetch_since("expired_history_id")
    assert len(messages) == 2
    assert cursor == "100500"


def test_configurable_narrowing_query(mock_gmail_api):
    client, _ = mock_gmail_api
    custom_query = "zoho.meeting OR filename:ics"
    source = GmailSource(
        token_provider="dummy-token",
        query=custom_query,
        http_client=client,
    )

    source.fetch_since(None)
    messages_call = next(
        params for path, params in client.call_history if path == "/users/me/messages"
    )
    assert f"({custom_query})" in messages_call["q"]


def test_auth_token_resolution(monkeypatch):
    monkeypatch.setattr(
        secrets,
        "get_secret",
        lambda ref: "stored-secret-token" if ref == "google" else None,
    )

    source_default = GmailSource()
    assert source_default._get_token() == "stored-secret-token"

    source_provider = GmailSource(token_provider=lambda: "dynamic-token")
    assert source_provider._get_token() == "dynamic-token"

    source_string = GmailSource(token_provider="raw-token-123")
    assert source_string._get_token() == "raw-token-123"

    monkeypatch.setattr(
        secrets,
        "get_secret",
        lambda ref: json.dumps({"access_token": "json-access-token"}) if ref == "google" else None,
    )
    source_json = GmailSource()
    assert source_json._get_token() == "json-access-token"


def test_config_gmail_section_parsing():
    cfg = parse_config(
        {
            "gmail": {
                "query": "zoom.us OR meet.google.com",
                "lookback_days": 14,
            }
        }
    )
    assert cfg.gmail.query == "zoom.us OR meet.google.com"
    assert cfg.gmail.lookback_days == 14

    # Default values
    cfg_default = parse_config({})
    assert cfg_default.gmail.query == DEFAULT_GMAIL_QUERY
    assert cfg_default.gmail.lookback_days == 7

    # Errors
    with pytest.raises(ConfigError, match="gmail.query"):
        parse_config({"gmail": {"query": 123}})
    with pytest.raises(ConfigError, match="gmail.lookback_days"):
        parse_config({"gmail": {"lookback_days": 0}})
    with pytest.raises(ConfigError, match=r"unknown keys in \[gmail\]"):
        parse_config({"gmail": {"extra": "field"}})


def test_gmail_fetch_limit(mock_gmail_api):
    client, _ = mock_gmail_api
    source = GmailSource(token_provider="dummy-token", http_client=client, fetch_limit=1)
    messages, cursor = source.fetch_since(None)
    assert len(messages) == 1


def test_gmail_latency_budget(mock_gmail_api, monkeypatch):
    client, _ = mock_gmail_api
    source = GmailSource(
        token_provider="dummy-token", http_client=client, latency_budget_seconds=0.0001
    )

    import time

    time_calls = [0.0, 100.0, 200.0]
    monkeypatch.setattr(time, "monotonic", lambda: time_calls.pop(0) if time_calls else 300.0)

    messages, cursor = source.fetch_since(None)
    # Exceeded budget before fetching all message details
    assert len(messages) == 0


def test_contract_incremental_fetch_limit_exhaustion_does_not_skip(mock_gmail_api):
    client, _ = mock_gmail_api
    history_multi = {
        "historyId": "100600",
        "history": [
            {
                "id": "100501",
                "messagesAdded": [{"message": {"id": "msg_new_teams"}}],
            },
            {
                "id": "100502",
                "messagesAdded": [{"message": {"id": "msg_html_zoom"}}],
            },
        ],
    }
    client.responses["/users/me/history"] = history_multi
    source = GmailSource(token_provider="dummy-token", http_client=client, fetch_limit=1)

    # First fetch with limit=1 only processes record 1 and advances cursor to 100501
    messages, next_cursor = source.fetch_since("100500")
    assert len(messages) == 1
    assert messages[0].id == "msg_new_teams"
    assert next_cursor == "100501"


