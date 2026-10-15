"""Stub calendar MCP server for the zoho-calendar mapping contract tests.

argv[1] is a JSON state file (each tool call runs in a fresh process); argv[2] is an optional mode:
"no-location" exposes a create_event without a location field.
"""

import json
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

STATE = Path(sys.argv[1])
MODE = sys.argv[2] if len(sys.argv) > 2 else ""

mcp = MCPServer("stub-calendar")


def _load() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"events": {}, "calls": [], "next": 1}


def _save(state: dict) -> None:
    STATE.write_text(json.dumps(state))


def _create(**fields) -> str:
    state = _load()
    event_id = f"z{state['next']}"
    state["next"] += 1
    state["events"][event_id] = {"event_id": event_id, **fields}
    state["calls"].append(["create", fields])
    _save(state)
    return json.dumps({"data": {"event_id": event_id}})


if MODE == "no-location":

    @mcp.tool()
    def create_event(
        title: str, start: str, end: str, timezone: str = "", description: str = ""
    ) -> str:
        return _create(title=title, start=start, end=end, description=description)

else:

    @mcp.tool()
    def create_event(
        title: str,
        start: str,
        end: str,
        timezone: str = "",
        location: str = "",
        description: str = "",
    ) -> str:
        return _create(
            title=title,
            start=start,
            end=end,
            timezone=timezone,
            location=location,
            description=description,
        )


@mcp.tool()
def update_event(
    event_id: str,
    title: str,
    start: str,
    end: str,
    timezone: str = "",
    location: str = "",
    description: str = "",
) -> str:
    if event_id.startswith("locked"):
        # ToolError reaches the client as is_error with this text; other exceptions are masked.
        raise ToolError(
            json.dumps(
                {"error": {"code": "PERMISSION_DENIED", "message": f"no edit rights on {event_id}"}}
            )
        )
    state = _load()
    fields = {
        "title": title,
        "start": start,
        "end": end,
        "timezone": timezone,
        "location": location,
        "description": description,
    }
    state["events"][event_id] = {"event_id": event_id, **fields}
    state["calls"].append(["update", {"event_id": event_id, **fields}])
    _save(state)
    return json.dumps({"data": {"event_id": event_id}})


@mcp.tool()
def delete_event(event_id: str) -> str:
    state = _load()
    state["events"].pop(event_id, None)
    state["calls"].append(["delete", {"event_id": event_id}])
    _save(state)
    return json.dumps({"data": {"deleted": event_id}})


@mcp.tool()
def list_events(start: str, end: str) -> str:
    events = [e for e in _load()["events"].values() if start <= e["start"] <= end]
    return json.dumps({"data": {"events": events}})


if __name__ == "__main__":
    mcp.run()
