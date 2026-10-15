"""Tests for the MCP write adapter and the zoho-calendar sink (ADR 0004 contract)."""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from cuecal.models import MeetingCandidate
from cuecal.sinks.base import SinkCredentialsError, SinkPermissionError
from cuecal.sinks.mcp import ZohoCalendarSink
from cuecal.sources.mcp import (
    MCPError,
    MCPWriter,
    _parse_write,
    check_write_tools,
    load_mapping,
    render_args,
)

STUB = Path(__file__).parent / "stub_calendar_mcp_server.py"
START = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)


def _cand(**kw) -> MeetingCandidate:
    base = {
        "title": "Weekly Sync",
        "start": START,
        "end": START + timedelta(hours=1),
        "join_url": "https://meet.google.com/abc-defg-hij",
        "meeting_id": "abc-defg-hij",
        "attendees": ["colleague@example.com", "boss@example.com"],
        "confidence": 0.9,
    }
    base.update(kw)
    return MeetingCandidate(**base)


def _stub_sink(state: Path, mode: str = "") -> ZohoCalendarSink:
    """The shipped zoho-calendar mapping, pointed at the stdio stub instead of mcp.zoho.com."""
    mapping = dataclasses.replace(
        load_mapping("zoho-calendar"),
        transport="stdio",
        command=sys.executable,
        args=[str(STUB), str(state), *([mode] if mode else [])],
    )
    return ZohoCalendarSink(writer=MCPWriter(mapping))


def _state(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {"events": {}, "calls": []}


def _write_table(**overrides) -> dict:
    table = {
        "create_tool": "create_event",
        "update_tool": "update_event",
        "delete_tool": "delete_event",
        "create_args": {
            "title": "{title}",
            "start": "{start}",
            "end": "{end}",
            "location": "{location}",
            "description": "{description}",
        },
        "update_args": {
            "event_id": "{event_id}",
            "title": "{title}",
            "start": "{start_utc}",
            "end": "{end_utc}",
            "location": "{join_url}",
            "description": "{description}",
        },
        "delete_args": {"event_id": "{event_id}"},
    }
    table.update(overrides)
    return table


# --- mapping parsing -------------------------------------------------------------------------


def test_shipped_mapping_parses_and_never_sends_attendees():
    write = load_mapping("zoho-calendar").write
    assert write is not None
    assert (write.create_tool, write.update_tool, write.delete_tool) == (
        "create_event",
        "update_event",
        "delete_event",
    )
    assert write.list_tool == "list_events"
    for template in (write.create_args, write.update_args):
        assert not {"attendees", "guests", "participants"} & set(template)


def test_parse_write_accepts_valid_table():
    write = _parse_write(_write_table(), Path("m.toml"))
    assert write.event_id_path == ""
    assert "list" not in write.tools()


@pytest.mark.parametrize("field", ["location", "description", "start", "end", "title"])
def test_parse_write_fails_loudly_without_required_field(field):
    args = dict(_write_table()["create_args"])
    del args[field]
    match = rf"create_args does not send required field\(s\) \['{field}'\]"
    with pytest.raises(MCPError, match=match):
        _parse_write(_write_table(create_args=args), Path("m.toml"))


def test_parse_write_requires_event_id_for_update_and_delete():
    with pytest.raises(MCPError, match=r"delete_args must pass \{event_id\}"):
        _parse_write(_write_table(delete_args={"id": "x"}), Path("m.toml"))


def test_parse_write_rejects_unknown_placeholder_and_missing_tool():
    args = {**_write_table()["create_args"], "guests": "{attendees}"}
    with pytest.raises(MCPError, match="unknown placeholder"):
        _parse_write(_write_table(create_args=args), Path("m.toml"))
    with pytest.raises(MCPError, match="needs a delete_tool"):
        _parse_write(_write_table(delete_tool=""), Path("m.toml"))


def test_render_args_keeps_whole_values_and_fills_embedded_ones():
    rendered = render_args(
        {"a": "{title}", "b": "At {start}", "c": {"d": ["{tz}"]}, "e": 5, "f": "{location}"},
        {"title": "T", "start": "9am", "tz": "UTC", "location": None},
    )
    assert rendered == {"a": "T", "b": "At 9am", "c": {"d": ["UTC"]}, "e": 5, "f": ""}


# --- schema contract -------------------------------------------------------------------------


def _tool(name, props, required=()):
    return SimpleNamespace(
        name=name,
        inputSchema={"properties": {p: {"type": "string"} for p in props}, "required": required},
    )


def _tools(create_props):
    upd = ["event_id", "title", "start", "end", "location", "description"]
    return [
        _tool("create_event", create_props),
        _tool("update_event", upd),
        _tool("delete_event", ["event_id"]),
    ]


def test_check_write_tools_passes_matching_schema():
    write = _parse_write(_write_table(), Path("m.toml"))
    check_write_tools(write, _tools(["title", "start", "end", "location", "description"]))


def test_check_write_tools_fails_loudly_when_schema_lacks_location():
    write = _parse_write(_write_table(), Path("m.toml"))
    match = r"create tool 'create_event' schema has no field\(s\) \['location'\]"
    with pytest.raises(MCPError, match=match):
        check_write_tools(write, _tools(["title", "start", "end", "description"]))


def test_check_write_tools_reports_missing_tool_and_unsent_required_field():
    write = _parse_write(_write_table(), Path("m.toml"))
    tools = _tools(["title", "start", "end", "location", "description", "calendar_id"])
    tools[0].inputSchema["required"] = ["calendar_id"]
    with pytest.raises(MCPError) as info:
        check_write_tools(write, tools[:1] + tools[2:])
    msg = str(info.value)
    assert "update tool 'update_event' is not exposed by the server" in msg
    assert "requires field(s) ['calendar_id'] we never send" in msg


# --- against the stdio stub ------------------------------------------------------------------


def test_validate_against_stub_server(tmp_path):
    _stub_sink(tmp_path / "s.json").validate()
    with pytest.raises(MCPError, match=r"schema has no field\(s\) \['location'\]"):
        _stub_sink(tmp_path / "s.json", "no-location").validate()


def test_create_carries_title_time_join_url_and_no_attendees(tmp_path):
    state = tmp_path / "s.json"
    event = _stub_sink(state).create(_cand())
    assert event.id == "z1"

    (call,) = _state(state)["calls"]
    op, args = call
    assert op == "create"
    assert args["title"] == "Weekly Sync"
    assert args["start"] == START.isoformat()
    assert args["end"] == (START + timedelta(hours=1)).isoformat()
    assert args["location"] == "https://meet.google.com/abc-defg-hij"
    assert "https://meet.google.com/abc-defg-hij" in args["description"]
    sent = json.dumps(args)
    assert "colleague@example.com" not in sent and "boss@example.com" not in sent


def test_create_patches_first_time_match_instead_of_duplicating(tmp_path):
    state = tmp_path / "s.json"
    near = (START + timedelta(minutes=10)).isoformat()
    state.write_text(
        json.dumps(
            {
                "events": {
                    "zx": {"event_id": "zx", "title": "Weekly sync", "start": near, "end": near}
                },
                "calls": [],
                "next": 1,
            }
        )
    )
    event = _stub_sink(state).create(_cand())
    assert event.id == "zx"
    calls = _state(state)["calls"]
    assert [c[0] for c in calls] == ["update"]
    assert calls[0][1]["event_id"] == "zx"
    assert calls[0][1]["location"] == "https://meet.google.com/abc-defg-hij"


def test_create_ignores_far_or_differently_titled_events(tmp_path):
    state = tmp_path / "s.json"
    far = (START + timedelta(minutes=20)).isoformat()
    near = (START + timedelta(minutes=5)).isoformat()
    state.write_text(
        json.dumps(
            {
                "events": {
                    "a": {"event_id": "a", "title": "Weekly Sync", "start": far, "end": far},
                    "b": {"event_id": "b", "title": "Dentist", "start": near, "end": near},
                },
                "calls": [],
                "next": 1,
            }
        )
    )
    assert _stub_sink(state).create(_cand()).id == "z1"


def test_update_and_delete_through_stub(tmp_path):
    state = tmp_path / "s.json"
    sink = _stub_sink(state)
    eid = sink.create(_cand()).id
    sink.update(eid, _cand(title="Weekly Sync (moved)", start=START + timedelta(hours=2)))
    assert _state(state)["events"][eid]["title"] == "Weekly Sync (moved)"
    sink.delete(eid)
    assert eid not in _state(state)["events"]


def test_permission_error_carries_raw_payload(tmp_path):
    with pytest.raises(SinkPermissionError) as info:
        _stub_sink(tmp_path / "s.json").update("locked-1", _cand())
    assert "PERMISSION_DENIED" in info.value.payload
    assert "no edit rights on locked-1" in info.value.payload


def test_dry_run_writes_nothing(tmp_path):
    state = tmp_path / "s.json"
    sink = _stub_sink(state)
    sink.dry_run = True
    sink.create(_cand())
    sink.update("z9", _cand())
    sink.delete("z9")
    assert _state(state)["calls"] == []


def test_check_credentials_needs_zoho_token(monkeypatch):
    monkeypatch.setattr("cuecal.sinks.mcp.secrets.get_secret", lambda ref: None)
    with pytest.raises(SinkCredentialsError, match='keyring entry "zoho"'):
        ZohoCalendarSink().check_credentials()
    monkeypatch.setattr("cuecal.sinks.mcp.secrets.get_secret", lambda ref: "tok")
    ZohoCalendarSink().check_credentials()
