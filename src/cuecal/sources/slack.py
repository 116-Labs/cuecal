"""Slack native source adapter.

Connects to Slack using a user token, fetches messages matching meeting terms via search.messages
or conversations.history, unwraps Slack link formatting and unfurls, caches user metadata, and
respects Retry-After rate limits.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from cuecal import registry, secrets
from cuecal.models import Message

logger = logging.getLogger("cuecal.sources.slack")

DEFAULT_SEARCH_TERMS: tuple[str, ...] = ()

# Regexes for unwrapping Slack mrkdwn formatting
_MAILTO_RE = re.compile(r"<mailto:([^|>]+)(?:\|([^>]+))?>")
_LINK_RE = re.compile(r"<(https?://[^|>]+)\|([^>]+)>")
_URL_RE = re.compile(r"<(https?://[^>]+)>")
_USER_RE = re.compile(r"<@([A-Z0-9]+)(?:\|([^>]+))?>")
_CHANNEL_RE = re.compile(r"<#([A-Z0-9]+)(?:\|([^>]+))?>")
_SUBTEAM_RE = re.compile(r"<!subteam\^[A-Z0-9]+(?:\|([^>]+))?>")
_SPECIAL_RE = re.compile(r"<!(here|channel|everyone)>")


def unwrap_slack_mrkdwn(text: str) -> str:
    """Unwrap Slack-specific link, mention, and channel formatting."""
    if not text:
        return ""
    # <mailto:user@domain.com|label> -> label or email
    text = _MAILTO_RE.sub(lambda m: m.group(2) or m.group(1), text)
    # <https://link|label> -> https://link label
    text = _LINK_RE.sub(r"\1 \2", text)
    # <https://link> -> https://link
    text = _URL_RE.sub(r"\1", text)
    # <@U123|name> -> @name / @U123
    text = _USER_RE.sub(lambda m: f"@{m.group(2)}" if m.group(2) else f"@{m.group(1)}", text)
    # <#C123|name> -> #name / #C123
    text = _CHANNEL_RE.sub(lambda m: f"#{m.group(2)}" if m.group(2) else f"#{m.group(1)}", text)
    # <!subteam^S123|name> -> @name
    text = _SUBTEAM_RE.sub(lambda m: f"@{m.group(1)}" if m.group(1) else "@subteam", text)
    # <!here> -> @here
    text = _SPECIAL_RE.sub(r"@\1", text)
    return text


def _extract_attachment_text(att: dict[str, Any]) -> str:
    """Extract titles, links, fields, and descriptions from a Slack attachment."""
    parts: list[str] = []
    title = att.get("title")
    title_link = att.get("title_link")
    if title and title_link:
        parts.append(f"{title}: {title_link}")
    elif title:
        parts.append(title)
    elif title_link:
        parts.append(title_link)

    for key in ("text", "fallback", "from_url", "original_url"):
        val = att.get(key)
        if val and isinstance(val, str) and val not in parts:
            parts.append(val)

    for f in att.get("fields", []):
        f_title = f.get("title", "")
        f_val = f.get("value", "")
        if f_title or f_val:
            parts.append(f"{f_title}: {f_val}".strip(": "))

    return "\n".join(parts)


def unwrap_slack_message(msg: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    """Unwrap message text, unfurls, blocks, and attachments.

    Returns (unwrapped_text, calendar_attachments).
    """
    text_parts: list[str] = []
    main_text = msg.get("text", "")
    if main_text:
        text_parts.append(unwrap_slack_mrkdwn(main_text))

    raw_attachments: list[str] = []
    for att in msg.get("attachments", []):
        att_text = _extract_attachment_text(att)
        if att_text:
            text_parts.append(unwrap_slack_mrkdwn(att_text))
        for key in ("text", "fallback"):
            v = att.get(key, "")
            if "BEGIN:VCALENDAR" in v:
                raw_attachments.append(v)

    for block in msg.get("blocks", []):
        # Extract plain text or mrkdwn from block elements if not already in main_text
        block_text = block.get("text", {})
        if isinstance(block_text, dict) and block_text.get("text"):
            unwrapped = unwrap_slack_mrkdwn(block_text["text"])
            if unwrapped not in text_parts:
                text_parts.append(unwrapped)

    combined_text = "\n\n".join(filter(None, text_parts)).strip()
    return combined_text, tuple(raw_attachments)


@dataclass
class SlackQueryBuilder:
    """Modular query builder for Slack search.messages."""

    terms: tuple[str, ...] = DEFAULT_SEARCH_TERMS
    extra_query: str | None = None

    def build_query(self) -> str:
        parts: list[str] = []
        if self.terms:
            if len(self.terms) == 1:
                parts.append(self.terms[0])
            else:
                parts.append(" OR ".join(self.terms))
        if self.extra_query:
            parts.append(self.extra_query)
        return " ".join(parts).strip()


class SlackAPIError(RuntimeError):
    """Raised when the Slack API returns an error response."""


class SlackRateLimitError(SlackAPIError):
    """Raised when rate limits are exhausted after retrying."""


class SlackClient:
    """Minimal REST client for the Slack Web API using urllib."""

    def __init__(
        self,
        token: str,
        base_url: str = "https://slack.com/api/",
        max_retries: int = 3,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/") + "/"
        self.max_retries = max_retries
        self.sleep_fn = sleep_fn
        self._user_cache: dict[str, str] = {}

    def _request(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = urllib.parse.urljoin(self.base_url, endpoint)
        query_params = {k: str(v) for k, v in (params or {}).items() if v is not None}
        if query_params:
            url += "?" + urllib.parse.urlencode(query_params)

        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "cuecal/0.1.0",
                "Content-Type": "application/json; charset=utf-8",
            },
        )

        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(req) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if not data.get("ok"):
                        err = data.get("error", "unknown_error")
                        if err == "ratelimited" and attempt < self.max_retries:
                            retry_after = 1.0
                            logger.warning(
                                "Slack rate limited (api level), retrying in %ss", retry_after
                            )
                            self.sleep_fn(retry_after)
                            continue
                        raise SlackAPIError(f"Slack API error on {endpoint}: {err}")
                    return data
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    if attempt < self.max_retries:
                        retry_after_hdr = exc.headers.get("Retry-After")
                        try:
                            retry_after = float(retry_after_hdr) if retry_after_hdr else 1.0
                        except ValueError:
                            retry_after = 1.0
                        logger.warning(
                            "Slack HTTP 429 rate limit on %s; sleeping %ss (attempt %d/%d)",
                            endpoint,
                            retry_after,
                            attempt + 1,
                            self.max_retries,
                        )
                        self.sleep_fn(retry_after)
                        continue
                    raise SlackRateLimitError(
                        f"Slack rate limit exhausted on {endpoint} after {self.max_retries} retries"
                    ) from exc
                body = ""
                try:
                    body = exc.read().decode("utf-8")
                except Exception:
                    pass
                raise SlackAPIError(
                    f"Slack HTTP {exc.code} error on {endpoint}: {body or exc.reason}"
                ) from exc
            except urllib.error.URLError as exc:
                raise SlackAPIError(f"Slack connection error on {endpoint}: {exc.reason}") from exc

        raise SlackRateLimitError(f"Slack rate limit exhausted on {endpoint}")

    def search_messages(
        self,
        query: str,
        page: int = 1,
        count: int = 100,
        sort: str = "timestamp",
        sort_dir: str = "desc",
    ) -> dict[str, Any]:
        return self._request(
            "search.messages",
            {"query": query, "page": page, "count": count, "sort": sort, "sort_dir": sort_dir},
        )

    def conversations_history(
        self,
        channel: str,
        oldest: str | None = None,
        latest: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"channel": channel, "limit": limit}
        if oldest:
            params["oldest"] = oldest
        if latest:
            params["latest"] = latest
        if cursor:
            params["cursor"] = cursor
        return self._request("conversations.history", params)

    def get_user_info(self, user_id: str) -> str:
        if not user_id:
            return "unknown"
        if user_id in self._user_cache:
            return self._user_cache[user_id]

        try:
            data = self._request("users.info", {"user": user_id})
            user_obj = data.get("user", {})
            profile = user_obj.get("profile", {})
            name = (
                profile.get("display_name")
                or profile.get("real_name")
                or user_obj.get("real_name")
                or user_obj.get("name")
                or user_id
            )
            self._user_cache[user_id] = name
            return name
        except SlackAPIError as exc:
            logger.debug("Failed to resolve user name for %s: %s", user_id, exc)
            self._user_cache[user_id] = user_id
            return user_id

    def get_permalink(self, channel: str, message_ts: str) -> str | None:
        try:
            data = self._request(
                "chat.getPermalink", {"channel": channel, "message_ts": message_ts}
            )
            return data.get("permalink")
        except SlackAPIError:
            return None


@dataclass
class SlackSource:
    """Slack native source adapter."""

    name: str = "slack"
    token: str | None = None
    secret_ref: str = "slack"
    channels: list[str] | None = None
    query_builder: SlackQueryBuilder = field(default_factory=SlackQueryBuilder)
    client: SlackClient | None = None
    fetch_limit: int = 100
    latency_budget_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.token:
            self.token = secrets.get_secret(self.secret_ref)
        if not self.client and self.token:
            self.client = SlackClient(token=self.token)

    def _ensure_client(self) -> SlackClient:
        if self.client:
            return self.client
        if not self.token:
            self.token = secrets.get_secret(self.secret_ref)
        if not self.token:
            raise ValueError(
                f"Slack token not found in keyring (ref: {self.secret_ref!r}); "
                "store it with `cuecal auth slack`"
            )
        self.client = SlackClient(token=self.token)
        return self.client

    def fetch_since(
        self, cursor: str | None, limit: int | None = None
    ) -> tuple[list[Message], str | None]:
        """Fetch messages arriving after cursor (Slack timestamp)."""
        client = self._ensure_client()
        messages: list[Message] = []
        cursor_ts = float(cursor) if cursor else 0.0
        effective_limit = limit if limit is not None else self.fetch_limit
        start_time = time.monotonic()

        if not self.channels:
            # Default fetch strategy: search.messages with modular meeting terms
            base_query = self.query_builder.build_query()
            if cursor_ts > 0:
                cursor_dt = datetime.fromtimestamp(cursor_ts, tz=UTC)
                # Slack after:YYYY-MM-DD searches strictly after that date,
                # so subtract 1 day to ensure messages from the cursor's day are included.
                after_date = (cursor_dt.date() - timedelta(days=1)).strftime("%Y-%m-%d")
                query = f"{base_query} after:{after_date}" if base_query else f"after:{after_date}"
            else:
                query = base_query

            page = 1
            max_pages = 10
            while page <= max_pages:
                if time.monotonic() - start_time >= self.latency_budget_seconds:
                    logger.warning(
                        "Slack search fetch exceeded latency budget (%ss)",
                        self.latency_budget_seconds,
                    )
                    break
                resp = client.search_messages(query=query, page=page, count=100, sort_dir="desc")
                msg_container = resp.get("messages", {})
                matches = msg_container.get("matches", [])
                if not matches:
                    break

                hit_older = False
                for match in matches:
                    ts_str = match.get("ts", "0")
                    try:
                        ts_val = float(ts_str)
                    except ValueError:
                        continue

                    if ts_val <= cursor_ts:
                        hit_older = True
                        continue

                    channel_obj = match.get("channel", {})
                    channel_id = (
                        channel_obj.get("id") if isinstance(channel_obj, dict) else str(channel_obj)
                    ) or "unknown"
                    user_id = match.get("user") or match.get("username") or "unknown"
                    sender_name = client.get_user_info(user_id)
                    text, attachments = unwrap_slack_message(match)
                    permalink = match.get("permalink") or client.get_permalink(channel_id, ts_str)
                    dt = datetime.fromtimestamp(ts_val, tz=UTC)

                    msg_id = f"{channel_id}:{ts_str}"
                    messages.append(
                        Message(
                            id=msg_id,
                            source="slack",
                            sender=sender_name,
                            ts=dt,
                            text=text,
                            permalink=permalink,
                            attachments=attachments,
                        )
                    )

                paging = msg_container.get("paging", {})
                pages = paging.get("pages", 1)
                if page >= pages or hit_older:
                    break
                page += 1
        else:
            # Fallback strategy: conversations.history for configured channels/DMs
            for ch in self.channels:
                if time.monotonic() - start_time >= self.latency_budget_seconds:
                    logger.warning(
                        "Slack conversations fetch exceeded latency budget (%ss)",
                        self.latency_budget_seconds,
                    )
                    break
                cursor_param: str | None = None
                while True:
                    if time.monotonic() - start_time >= self.latency_budget_seconds:
                        logger.warning(
                            "Slack conversations fetch exceeded latency budget (%ss)",
                            self.latency_budget_seconds,
                        )
                        break
                    resp = client.conversations_history(
                        channel=ch, oldest=cursor, cursor=cursor_param, limit=100
                    )
                    for raw_msg in resp.get("messages", []):
                        ts_str = raw_msg.get("ts", "0")
                        try:
                            ts_val = float(ts_str)
                        except ValueError:
                            continue

                        if ts_val <= cursor_ts:
                            continue

                        user_id = raw_msg.get("user") or "unknown"
                        sender_name = client.get_user_info(user_id)
                        text, attachments = unwrap_slack_message(raw_msg)
                        permalink = client.get_permalink(ch, ts_str)
                        dt = datetime.fromtimestamp(ts_val, tz=UTC)

                        msg_id = f"{ch}:{ts_str}"
                        messages.append(
                            Message(
                                id=msg_id,
                                source="slack",
                                sender=sender_name,
                                ts=dt,
                                text=text,
                                permalink=permalink,
                                attachments=attachments,
                            )
                        )

                    has_more = resp.get("has_more", False)
                    resp_meta = resp.get("response_metadata", {})
                    next_page_cursor = resp_meta.get("next_cursor")
                    if not has_more or not next_page_cursor:
                        break
                    cursor_param = next_page_cursor

        # Sort chronologically by timestamp (oldest first)
        messages.sort(key=lambda m: m.ts)

        # Apply fetch limit to the oldest messages so cursor advances sequentially
        if len(messages) > effective_limit:
            messages = messages[:effective_limit]

        next_cursor = cursor
        if messages:
            # The next cursor is the timestamp of the newest message kept
            next_cursor = messages[-1].id.split(":")[-1]

        return messages, next_cursor


# Register plugin in cuecal registry
try:
    registry.register("sources", "slack", SlackSource)
except ValueError:
    pass
