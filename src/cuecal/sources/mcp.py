"""Generic MCP adapter.

Loads mapping files and connects to MCP servers to fetch messages (`MCPSource`). A mapping with a
``[write]`` table also gets create/update/delete tools for calendar sinks (`MCPWriter`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import tomllib
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client

from cuecal import paths, secrets
from cuecal.models import Message

logger = logging.getLogger(__name__)


class MCPError(Exception):
    pass


class MCPToolError(MCPError):
    """A tool call the server answered with an error. ``raw`` is the upstream payload as sent."""

    def __init__(
        self,
        tool: str,
        raw: str,
        *,
        code: str | None = None,
        message: str | None = None,
        permission: bool = False,
    ) -> None:
        detail = f"{code}: {message}" if code and message else (code or message or raw)
        super().__init__(f"tool {tool!r} failed: {detail}")
        self.tool = tool
        self.raw = raw
        self.code = code
        self.message = message
        self.permission = permission


# Values a [write] argument template may reference as {name}.
WRITE_PLACEHOLDERS = frozenset(
    {
        "title",
        "start",
        "end",
        "start_utc",
        "end_utc",
        "tz",
        "location",
        "join_url",
        "description",
        "event_id",
        "range_start",
        "range_end",
        "range_start_utc",
        "range_end_utc",
    }
)
# Event fields create and update must send, with the placeholders that satisfy each (ADR 0004).
REQUIRED_EVENT_FIELDS: dict[str, tuple[str, ...]] = {
    "title": ("title",),
    "start": ("start", "start_utc"),
    "end": ("end", "end_utc"),
    "location": ("location", "join_url"),
    "description": ("description",),
}
DEFAULT_PERMISSION_ERROR_CODES = ("403", "FORBIDDEN", "PERMISSION_DENIED", "NO_PERMISSION")
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


@dataclass
class MCPWriteMapping:
    create_tool: str
    update_tool: str
    delete_tool: str
    create_args: dict[str, Any]
    update_args: dict[str, Any]
    delete_args: dict[str, Any]
    # JSON path to the new event's ID in the create tool's result.
    event_id_path: str = ""
    # Optional tool listing events in a time range; used for first-time matching.
    list_tool: str = ""
    list_args: dict[str, Any] = field(default_factory=dict)
    items_path: str = ""
    field_mapping: dict[str, str] = field(default_factory=dict)
    error_code_path: str = "error.code"
    error_message_path: str = "error.message"
    permission_error_codes: list[str] = field(
        default_factory=lambda: list(DEFAULT_PERMISSION_ERROR_CODES)
    )

    def tools(self) -> dict[str, tuple[str, dict[str, Any]]]:
        """Return {op: (tool name, argument template)} for every mapped write-side tool."""
        ops = {
            "create": (self.create_tool, self.create_args),
            "update": (self.update_tool, self.update_args),
            "delete": (self.delete_tool, self.delete_args),
        }
        if self.list_tool:
            ops["list"] = (self.list_tool, self.list_args)
        return ops


@dataclass
class MCPMapping:
    name: str
    transport: str  # "stdio" or "sse"
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    auth_provider: str | None = None
    auth_header: str | None = None
    auth_prefix: str = ""
    list_tool: str = ""
    list_args: dict[str, Any] | None = None
    items_path: str = ""
    cursor_path: str = ""
    field_mapping: dict[str, str] | None = None
    write: MCPWriteMapping | None = None


def _placeholders(template: Any) -> set[str]:
    if isinstance(template, str):
        return set(_PLACEHOLDER_RE.findall(template))
    if isinstance(template, dict):
        return set().union(*(_placeholders(v) for v in template.values()))
    if isinstance(template, list):
        return set().union(*(_placeholders(v) for v in template))
    return set()


def _parse_write(data: Any, path: Path) -> MCPWriteMapping:
    """Parse a [write] table. A template that cannot carry a required event field fails here."""
    if not isinstance(data, dict):
        raise MCPError(f"[write] in {path} must be a table")
    where = f"[write] in {path}"
    tools = {}
    for op in ("create", "update", "delete"):
        tool = data.get(f"{op}_tool")
        if not isinstance(tool, str) or not tool:
            raise MCPError(f"{where} needs a {op}_tool name")
        args = data.get(f"{op}_args", {})
        if not isinstance(args, dict):
            raise MCPError(f"{where}: {op}_args must be a table")
        tools[op] = (tool, args)

    list_args = data.get("list_args", {})
    field_mapping = data.get("field_mapping", {})
    if not isinstance(list_args, dict) or not isinstance(field_mapping, dict):
        raise MCPError(f"{where}: list_args and field_mapping must be tables")
    codes = data.get("permission_error_codes", list(DEFAULT_PERMISSION_ERROR_CODES))
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
        raise MCPError(f"{where}: permission_error_codes must be a list of strings")

    for op, args in [*((op, args) for op, (_, args) in tools.items()), ("list", list_args)]:
        unknown = _placeholders(args) - WRITE_PLACEHOLDERS
        if unknown:
            raise MCPError(f"{where}: {op}_args uses unknown placeholder(s) {sorted(unknown)}")
    for op in ("create", "update"):
        used = _placeholders(tools[op][1])
        missing = [f for f, names in REQUIRED_EVENT_FIELDS.items() if not used & set(names)]
        if missing:
            raise MCPError(f"{where}: {op}_args does not send required field(s) {missing}")
    for op in ("update", "delete"):
        if "event_id" not in _placeholders(tools[op][1]):
            raise MCPError(f"{where}: {op}_args must pass {{event_id}}")

    return MCPWriteMapping(
        create_tool=tools["create"][0],
        update_tool=tools["update"][0],
        delete_tool=tools["delete"][0],
        create_args=tools["create"][1],
        update_args=tools["update"][1],
        delete_args=tools["delete"][1],
        event_id_path=data.get("event_id_path", ""),
        list_tool=data.get("list_tool", ""),
        list_args=list_args,
        items_path=data.get("items_path", ""),
        field_mapping=field_mapping,
        error_code_path=data.get("error_code_path", "error.code"),
        error_message_path=data.get("error_message_path", "error.message"),
        permission_error_codes=list(codes),
    )


def load_mapping(name: str) -> MCPMapping:
    # First check user config dir, then shipped mappings
    user_path = paths.config_path().parent / "mappings" / f"{name}.toml"
    shipped_path = Path(__file__).parent / "mappings" / f"{name}.toml"

    path = user_path if user_path.exists() else shipped_path
    if not path.exists():
        raise MCPError(f"Mapping {name} not found")

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MCPError(f"Invalid TOML in {path}: {exc}") from exc

    return MCPMapping(
        name=name,
        transport=data.get("transport", "stdio"),
        command=data.get("command"),
        args=data.get("args", []),
        url=data.get("url"),
        auth_provider=data.get("auth_provider"),
        auth_header=data.get("auth_header"),
        auth_prefix=data.get("auth_prefix", ""),
        list_tool=data.get("list_tool", ""),
        list_args=data.get("list_args", {}),
        items_path=data.get("items_path", ""),
        cursor_path=data.get("cursor_path", ""),
        field_mapping=data.get("field_mapping", {}),
        write=_parse_write(data["write"], path) if "write" in data else None,
    )


def _is_error(result: Any) -> bool:
    # mcp 2.x renamed isError to is_error; accept either SDK.
    return bool(getattr(result, "is_error", None) or getattr(result, "isError", False))


def _input_schema(tool: Any) -> dict[str, Any]:
    return getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {}


def _resolve_json_path(data: Any, path: str) -> Any:
    if not path:
        return data
    for part in path.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


@asynccontextmanager
async def open_session(
    mapping: MCPMapping, *, require_auth: bool = True
) -> AsyncIterator[ClientSession]:
    """Connect to the mapping's server and yield an initialized session."""
    if mapping.transport == "stdio":
        if not mapping.command:
            raise MCPError("stdio transport requires 'command'")
        server_params = StdioServerParameters(
            command=mapping.command, args=mapping.args or [], env=None
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    elif mapping.transport == "sse":
        if not mapping.url:
            raise MCPError("sse transport requires 'url'")
        headers = {}
        if mapping.auth_provider and mapping.auth_header:
            token = secrets.get_secret(mapping.auth_provider)
            if token:
                headers[mapping.auth_header] = f"{mapping.auth_prefix}{token}"
            elif require_auth:
                raise MCPError(f"Secret not found for provider {mapping.auth_provider}")
        async with sse_client(mapping.url, headers=headers) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    else:
        raise MCPError(f"Unknown transport: {mapping.transport}")


class MCPSource:
    def __init__(
        self,
        name: str,
        mapping: MCPMapping,
        fetch_limit: int = 50,
        latency_budget_seconds: float = 30.0,
    ):
        self.name = name
        self.mapping = mapping
        self.fetch_limit = fetch_limit
        self.latency_budget_seconds = latency_budget_seconds

    def fetch_since(
        self, cursor: str | None, limit: int | None = None
    ) -> tuple[list[Message], str]:
        return asyncio.run(self._fetch_async(cursor, limit=limit))

    async def _fetch_async(
        self, cursor: str | None, limit: int | None = None
    ) -> tuple[list[Message], str]:
        async with open_session(self.mapping) as session:
            return await self._execute_fetch(session, cursor, limit=limit)

    async def _execute_fetch(
        self, session: ClientSession, cursor: str | None, limit: int | None = None
    ) -> tuple[list[Message], str]:
        effective_limit = limit if limit is not None else self.fetch_limit
        # Prepare args
        args = dict(self.mapping.list_args or {})
        if "limit" in args:
            try:
                args["limit"] = min(int(args["limit"]), effective_limit)
            except (ValueError, TypeError):
                args["limit"] = effective_limit
        for k, v in list(args.items()):
            if isinstance(v, str) and "{cursor}" in v:
                if cursor:
                    args[k] = v.format(cursor=cursor)
                else:
                    if v == "{cursor}":
                        del args[k]  # omit it completely if not provided
                    else:
                        args[k] = v.replace("{cursor}", "")

        result = await session.call_tool(self.mapping.list_tool, arguments=args)
        if _is_error(result):
            raise MCPError(f"Tool error: {result.content}")
        if not result.content:
            raise MCPError("Tool returned empty content")

        # Tool result content is a list of TextContent/ImageContent etc.
        # Assuming JSON string in the first text content
        text_content = result.content[0].text
        try:
            data = json.loads(text_content)
        except json.JSONDecodeError as exc:
            raise MCPError(f"Tool returned invalid JSON: {exc}") from exc

        items = _resolve_json_path(data, self.mapping.items_path)
        if not isinstance(items, list):
            raise MCPError(f"Items path {self.mapping.items_path!r} did not resolve to a list")

        if len(items) > effective_limit:
            messages = [self._parse_message(item) for item in items[:effective_limit]]
            next_cursor = cursor or ""
        else:
            messages = [self._parse_message(item) for item in items]
            resolved_cursor = _resolve_json_path(data, self.mapping.cursor_path)
            next_cursor = resolved_cursor if resolved_cursor is not None else (cursor or "")

        return messages, str(next_cursor)

    def _parse_message(self, item: dict[str, Any]) -> Message:
        fm = self.mapping.field_mapping or {}
        try:
            id_val = _resolve_json_path(item, fm.get("id", "id"))
            sender_val = _resolve_json_path(item, fm.get("sender", "sender"))
            ts_val = _resolve_json_path(item, fm.get("ts", "ts"))
            text_val = _resolve_json_path(item, fm.get("text", "text"))
            permalink_val = _resolve_json_path(item, fm.get("permalink", "permalink"))

            if id_val is None or sender_val is None or ts_val is None or text_val is None:
                raise ValueError("missing required field in tool output")

            # parse ts
            ts = datetime.fromisoformat(ts_val) if isinstance(ts_val, str) else ts_val
            if not isinstance(ts, datetime):
                raise ValueError("invalid timestamp")

            return Message(
                id=str(id_val),
                source=self.name,
                sender=str(sender_val),
                ts=ts,
                text=str(text_val),
                permalink=str(permalink_val) if permalink_val is not None else None,
            )
        except Exception as exc:
            raise MCPError(f"Failed to map message fields: {exc}") from exc

    async def _validate_async(self) -> None:
        async with open_session(self.mapping, require_auth=False) as session:
            result = await session.list_tools()

        tool_names = [t.name for t in result.tools]
        if self.mapping.list_tool not in tool_names:
            raise MCPError(
                f"Mapped list_tool {self.mapping.list_tool!r} not exposed by server. "
                f"Exposed tools: {', '.join(tool_names)}"
            )

    def validate(self) -> None:
        asyncio.run(self._validate_async())


def load_source(
    name: str, *, fetch_limit: int = 50, latency_budget_seconds: float = 30.0
) -> MCPSource:
    mapping = load_mapping(name)
    return MCPSource(
        name, mapping, fetch_limit=fetch_limit, latency_budget_seconds=latency_budget_seconds
    )


def render_args(template: Any, values: dict[str, Any]) -> Any:
    """Fill {placeholders}. A value that is exactly one placeholder keeps the value's type."""
    if isinstance(template, dict):
        return {k: render_args(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [render_args(v, values) for v in template]
    if not isinstance(template, str):
        return template
    whole = _PLACEHOLDER_RE.fullmatch(template)
    if whole:
        value = values.get(whole.group(1))
        return "" if value is None else value
    return _PLACEHOLDER_RE.sub(lambda m: str(values.get(m.group(1)) or ""), template)


def check_write_tools(write: MCPWriteMapping, tools: Iterable[Any]) -> None:
    """Fail loudly unless the server exposes every mapped tool with a schema our args fit.

    Each argument we send must be a property of the tool's input schema, and each property the
    schema requires must be one we send. So a tool that has no location, description or time
    field for the template to fill is rejected here rather than silently dropping that field.
    """
    by_name = {t.name: t for t in tools}
    problems: list[str] = []
    for op, (tool_name, template) in write.tools().items():
        tool = by_name.get(tool_name)
        if tool is None:
            problems.append(f"{op} tool {tool_name!r} is not exposed by the server")
            continue
        schema = _input_schema(tool)
        properties = schema.get("properties")
        sent = set(template)
        if isinstance(properties, dict):
            unknown = sorted(sent - set(properties))
            if unknown:
                problems.append(f"{op} tool {tool_name!r} schema has no field(s) {unknown}")
        required = sorted(set(schema.get("required") or ()) - sent)
        if required:
            problems.append(f"{op} tool {tool_name!r} requires field(s) {required} we never send")
    if problems:
        exposed = ", ".join(sorted(by_name)) or "(none)"
        raise MCPError("; ".join(problems) + f". Exposed tools: {exposed}")


def _json_in(text: str) -> Any:
    """Parse ``text`` as JSON, or the outermost {...} inside it (servers often prefix errors)."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    return None


class MCPWriter:
    """Calls a mapping's [write] tools. Each call opens its own short-lived session."""

    def __init__(self, mapping: MCPMapping) -> None:
        if mapping.write is None:
            raise MCPError(f"Mapping {mapping.name} has no [write] table")
        self.mapping = mapping
        self.write = mapping.write

    def _tool_error(self, tool: str, raw: str, data: Any) -> MCPToolError:
        code = message = None
        if isinstance(data, dict):
            code_val = _resolve_json_path(data, self.write.error_code_path)
            msg_val = _resolve_json_path(data, self.write.error_message_path)
            code = None if code_val is None else str(code_val)
            message = None if msg_val is None else str(msg_val)
        codes = [c.lower() for c in self.write.permission_error_codes]
        permission = (code is not None and code.lower() in codes) or any(
            re.search(rf"\b{re.escape(c)}\b", raw, re.IGNORECASE) for c in codes
        )
        return MCPToolError(tool, raw, code=code, message=message, permission=permission)

    async def _call(self, op: str, values: dict[str, Any]) -> Any:
        tool, template = self.write.tools()[op]
        args = render_args(template, values)
        async with open_session(self.mapping) as session:
            result = await session.call_tool(tool, arguments=args)
        raw = "\n".join(t for c in result.content or [] if (t := getattr(c, "text", None)))
        data = _json_in(raw) if raw else None
        if _is_error(result):
            raise self._tool_error(tool, raw, data)
        if raw and data is None:
            raise MCPError(f"tool {tool!r} returned invalid JSON: {raw[:200]}")
        if isinstance(data, dict) and _resolve_json_path(data, self.write.error_code_path):
            raise self._tool_error(tool, raw, data)
        return data

    def call(self, op: str, values: dict[str, Any]) -> Any:
        """Run the mapped tool for ``op`` with its template filled from ``values``."""
        return asyncio.run(self._call(op, values))

    def create(self, values: dict[str, Any]) -> str:
        data = self.call("create", values)
        event_id = _resolve_json_path(data, self.write.event_id_path)
        if event_id is None or isinstance(event_id, dict | list) or event_id == "":
            raise MCPError(
                f"create tool {self.write.create_tool!r} result has no event ID at "
                f"{self.write.event_id_path!r}"
            )
        return str(event_id)

    def update(self, values: dict[str, Any]) -> None:
        self.call("update", values)

    def delete(self, values: dict[str, Any]) -> None:
        self.call("delete", values)

    def list_events(self, values: dict[str, Any]) -> list[dict[str, Any]]:
        """Return events in a range as {id, title, start, end} dicts; [] without a list_tool."""
        if not self.write.list_tool:
            return []
        data = self.call("list", values)
        items = _resolve_json_path(data, self.write.items_path)
        if not isinstance(items, list):
            raise MCPError(f"Items path {self.write.items_path!r} did not resolve to a list")
        fm = self.write.field_mapping
        events = []
        for item in items:
            event = {
                k: _resolve_json_path(item, fm.get(k, k)) for k in ("id", "title", "start", "end")
            }
            if event["id"] is not None:
                events.append(event)
        return events

    async def _validate_async(self) -> None:
        async with open_session(self.mapping, require_auth=False) as session:
            result = await session.list_tools()
        check_write_tools(self.write, result.tools)

    def validate(self) -> None:
        asyncio.run(self._validate_async())
