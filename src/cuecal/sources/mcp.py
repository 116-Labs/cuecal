"""Generic MCP source adapter.

Loads mapping files and connects to MCP servers to fetch messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tomllib
from dataclasses import dataclass
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
    )


def _resolve_json_path(data: Any, path: str) -> Any:
    if not path:
        return data
    for part in path.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


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
        if self.mapping.transport == "stdio":
            if not self.mapping.command:
                raise MCPError("stdio transport requires 'command'")
            server_params = StdioServerParameters(
                command=self.mapping.command, args=self.mapping.args or [], env=None
            )
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await self._execute_fetch(session, cursor, limit=limit)
        elif self.mapping.transport == "sse":
            if not self.mapping.url:
                raise MCPError("sse transport requires 'url'")
            headers = {}
            if self.mapping.auth_provider and self.mapping.auth_header:
                token = secrets.get_secret(self.mapping.auth_provider)
                if not token:
                    raise MCPError(f"Secret not found for provider {self.mapping.auth_provider}")
                headers[self.mapping.auth_header] = f"{self.mapping.auth_prefix}{token}"

            async with sse_client(self.mapping.url, headers=headers) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await self._execute_fetch(session, cursor, limit=limit)
        else:
            raise MCPError(f"Unknown transport: {self.mapping.transport}")

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
        if getattr(result, "isError", False):
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
        if self.mapping.transport == "stdio":
            if not self.mapping.command:
                raise MCPError("stdio transport requires 'command'")
            server_params = StdioServerParameters(
                command=self.mapping.command, args=self.mapping.args or [], env=None
            )
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
        elif self.mapping.transport == "sse":
            if not self.mapping.url:
                raise MCPError("sse transport requires 'url'")
            headers = {}
            if self.mapping.auth_provider and self.mapping.auth_header:
                token = secrets.get_secret(self.mapping.auth_provider)
                if token:
                    headers[self.mapping.auth_header] = f"{self.mapping.auth_prefix}{token}"
            async with sse_client(self.mapping.url, headers=headers) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
        else:
            raise MCPError(f"Unknown transport: {self.mapping.transport}")

        tool_names = [t.name for t in result.tools]
        if self.mapping.list_tool not in tool_names:
            raise MCPError(
                f"Mapped list_tool {self.mapping.list_tool!r} not exposed by server. "
                f"Exposed tools: {', '.join(tool_names)}"
            )

    def validate(self) -> None:
        asyncio.run(self._validate_async())


def load_source(name: str) -> MCPSource:
    mapping = load_mapping(name)
    return MCPSource(name, mapping)
