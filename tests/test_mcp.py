import sys
from pathlib import Path

from cuecal.sources.mcp import MCPMapping, MCPSource


def test_mcp_source_stdio():
    # Use the stub server
    stub_path = Path(__file__).parent / "stub_mcp_server.py"

    mapping = MCPMapping(
        name="test-zoho-mail",
        transport="stdio",
        command=sys.executable,
        args=[str(stub_path)],
        list_tool="list_emails",
        list_args={"query": "meeting", "cursor": "{cursor}"},
        items_path="data.emails",
        cursor_path="data.next_cursor",
        field_mapping={
            "id": "message_id",
            "sender": "from_address",
            "ts": "received_time",
            "text": "body_text",
            "permalink": "web_url",
        },
    )

    source = MCPSource("test-zoho-mail", mapping)
    source.validate()  # ensure it validates without error against the stub server

    messages, next_cursor = source.fetch_since(None)

    assert len(messages) == 1
    assert messages[0].id == "123"
    assert messages[0].sender == "alice@example.com"
    assert messages[0].text == "Let's meet"
    assert next_cursor == "cur123"


def test_mcp_source_stdio_cliq():
    stub_path = Path(__file__).parent / "stub_mcp_server.py"

    mapping = MCPMapping(
        name="test-zoho-cliq",
        transport="stdio",
        command=sys.executable,
        args=[str(stub_path)],
        list_tool="list_messages",
        list_args={"query": "meeting", "cursor": "{cursor}"},
        items_path="data.messages",
        cursor_path="data.next_cursor",
        field_mapping={
            "id": "message_id",
            "sender": "sender.email",
            "ts": "created_time",
            "text": "content",
            "permalink": "message_url",
        },
    )

    source = MCPSource("test-zoho-cliq", mapping)
    source.validate()

    messages, next_cursor = source.fetch_since(None)

    assert len(messages) == 1
    assert messages[0].id == "m1"
    assert messages[0].sender == "bob@example.com"
    assert messages[0].text == "zoom call?"


def test_zoho_mail_mapping_contract():
    import pytest

    from cuecal.sources.mcp import MCPError, load_mapping, load_source

    mapping = load_mapping("zoho-mail")
    source = load_source("zoho-mail")
    assert mapping.name == "zoho-mail"
    assert mapping.list_tool == "list_emails"

    # Recorded sample response matching Zoho Mail schema
    sample_email = {
        "message_id": "zm_98765",
        "from_address": "colleague@zoho.com",
        "received_time": "2026-10-03T15:30:00Z",
        "body_text": "Team sync at 4pm today",
        "web_url": "https://mail.zoho.com/zm#mail/98765",
    }
    msg = source._parse_message(sample_email)
    assert msg.id == "zm_98765"
    assert msg.sender == "colleague@zoho.com"
    assert msg.text == "Team sync at 4pm today"
    assert msg.permalink == "https://mail.zoho.com/zm#mail/98765"

    # Must fail loudly if mapped fields are missing
    with pytest.raises(MCPError, match="Failed to map message fields"):
        source._parse_message({"message_id": "zm_98765"})


def test_zoho_cliq_mapping_contract():
    import pytest

    from cuecal.sources.mcp import MCPError, load_mapping, load_source

    mapping = load_mapping("zoho-cliq")
    source = load_source("zoho-cliq")
    assert mapping.name == "zoho-cliq"
    assert mapping.list_tool == "list_messages"

    # Recorded sample response matching Zoho Cliq schema
    sample_message = {
        "message_id": "cliq_112233",
        "sender": {"email": "pm@zoho.com", "name": "PM"},
        "created_time": "2026-10-03T16:00:00Z",
        "content": "Standup link: https://meet.google.com/abc-defg-hij",
        "message_url": "https://cliq.zoho.com/chat/112233",
    }
    msg = source._parse_message(sample_message)
    assert msg.id == "cliq_112233"
    assert msg.sender == "pm@zoho.com"
    assert msg.text == "Standup link: https://meet.google.com/abc-defg-hij"
    assert msg.permalink == "https://cliq.zoho.com/chat/112233"

    # Must fail loudly if mapped fields are missing
    with pytest.raises(MCPError, match="Failed to map message fields"):
        source._parse_message({"message_id": "cliq_112233"})
