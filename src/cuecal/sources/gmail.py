"""Gmail message source adapter using raw REST requests against the Gmail API."""

from __future__ import annotations

import base64
import html
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from typing import Any

from dateutil import parser as dateparser

from cuecal import secrets
from cuecal.models import Message

logger = logging.getLogger("cuecal.sources.gmail")

DEFAULT_GMAIL_QUERY = ""
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"


class _HTMLToText(HTMLParser):
    """HTML parser converting email HTML to readable plain text, preserving link URLs."""

    def __init__(self) -> None:
        super().__init__()
        self._pieces: list[str] = []
        self._current_href: str | None = None
        self._current_anchor_text: list[str] = []
        self._in_anchor = False
        self._skip_tag = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in ("script", "style", "head"):
            self._skip_tag += 1
            return
        if self._skip_tag > 0:
            return

        if tag_lower in ("p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br"):
            self._pieces.append("\n")
        elif tag_lower == "a":
            self._in_anchor = True
            self._current_anchor_text = []
            attr_dict = dict(attrs)
            self._current_href = attr_dict.get("href")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in ("script", "style", "head"):
            if self._skip_tag > 0:
                self._skip_tag -= 1
            return
        if self._skip_tag > 0:
            return

        if tag_lower in ("p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._pieces.append("\n")
        elif tag_lower == "a":
            self._in_anchor = False
            text = "".join(self._current_anchor_text).strip()
            href = (self._current_href or "").strip()
            if text and href and href not in text and not href.startswith("mailto:"):
                self._pieces.append(f"{text} ({href})")
            elif text:
                self._pieces.append(text)
            elif href and not href.startswith("mailto:"):
                self._pieces.append(href)
            self._current_href = None
            self._current_anchor_text = []

    def handle_data(self, data: str) -> None:
        if self._skip_tag > 0:
            return
        unescaped = html.unescape(data)
        if self._in_anchor:
            self._current_anchor_text.append(unescaped)
        else:
            self._pieces.append(unescaped)

    def get_text(self) -> str:
        raw = "".join(self._pieces)
        lines = [line.strip() for line in raw.splitlines()]
        cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
        return cleaned.strip()


def html_to_text(html_content: str) -> str:
    """Convert HTML string to readable plain text with links preserved."""
    if not html_content:
        return ""
    parser = _HTMLToText()
    parser.feed(html_content)
    parser.close()
    return parser.get_text()


def _decode_b64(data: str | None) -> str:
    """Decode standard or URL-safe base64 string from Gmail API."""
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")


def parse_gmail_message(data: dict[str, Any]) -> Message:
    """Parse a Gmail REST API message resource into a cuecal Message."""
    msg_id = data.get("id", "")
    payload = data.get("payload", {})
    headers = {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers", [])}

    sender = headers.get("from", "")
    internal_date = data.get("internalDate")
    if internal_date:
        try:
            ts = datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC)
        except (ValueError, OverflowError):
            ts = datetime.now(UTC)
    elif "date" in headers:
        try:
            ts = dateparser.parse(headers["date"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
        except (ValueError, OverflowError):
            ts = datetime.now(UTC)
    else:
        ts = datetime.now(UTC)

    plain_parts: list[str] = []
    html_parts: list[str] = []
    ics_parts: list[str] = []

    def _walk_part(part: dict[str, Any]) -> None:
        mime_type = part.get("mimeType", "").lower()
        filename = part.get("filename", "").lower()
        body = part.get("body", {})
        body_data = body.get("data")

        is_ics = (
            mime_type in ("text/calendar", "application/ics", "application/calendar")
            or filename.endswith(".ics")
            or filename.endswith(".ical")
        )

        if is_ics and body_data:
            decoded_ics = _decode_b64(body_data)
            if decoded_ics:
                ics_parts.append(decoded_ics)
        elif mime_type == "text/plain" and body_data:
            decoded_plain = _decode_b64(body_data)
            if "BEGIN:VCALENDAR" in decoded_plain:
                ics_parts.append(decoded_plain)
            else:
                plain_parts.append(decoded_plain)
        elif mime_type == "text/html" and body_data:
            decoded_html = _decode_b64(body_data)
            html_parts.append(decoded_html)

        for subpart in part.get("parts", []):
            _walk_part(subpart)

    _walk_part(payload)

    if plain_parts:
        text = "\n".join(plain_parts).strip()
    elif html_parts:
        text = html_to_text("\n".join(html_parts))
    else:
        text = data.get("snippet", "")

    permalink = f"https://mail.google.com/mail/u/0/#all/{msg_id}"

    return Message(
        id=msg_id,
        source="gmail",
        sender=sender,
        ts=ts,
        text=text,
        permalink=permalink,
        attachments=tuple(ics_parts),
    )


def matches_query(message_data: dict[str, Any], query: str | None) -> bool:
    """Check if a Gmail message resource matches a query string.

    Supports 'term1 OR term2 OR filename:ics' syntax used for narrowing filters.
    """
    if not query or not query.strip():
        return True

    # Check for .ics attachment
    has_ics = False
    payload = message_data.get("payload", {})

    def _check_ics(part: dict[str, Any]) -> None:
        nonlocal has_ics
        if has_ics:
            return
        m_type = part.get("mimeType", "").lower()
        f_name = part.get("filename", "").lower()
        if (
            m_type in ("text/calendar", "application/ics", "application/calendar")
            or f_name.endswith(".ics")
            or f_name.endswith(".ical")
        ):
            has_ics = True
            return
        for sub in part.get("parts", []):
            _check_ics(sub)

    _check_ics(payload)

    # Searchable text across snippet, headers, and decoded payload parts
    text_chunks: list[str] = [message_data.get("snippet", "")]
    for h in payload.get("headers", []):
        text_chunks.append(h.get("value", ""))

    def _collect_text(part: dict[str, Any]) -> None:
        m_type = part.get("mimeType", "").lower()
        b_data = part.get("body", {}).get("data")
        if b_data and m_type in ("text/plain", "text/html"):
            text_chunks.append(_decode_b64(b_data))
        for sub in part.get("parts", []):
            _collect_text(sub)

    _collect_text(payload)
    full_text = " ".join(text_chunks).lower()

    # Split terms by ' OR '
    raw_terms = re.split(r"\s+OR\s+", query, flags=re.I)
    for term in raw_terms:
        term = term.strip().lower()
        if not term:
            continue
        if term == "filename:ics":
            if has_ics or "begin:vcalendar" in full_text:
                return True
        elif term in full_text:
            return True

    return False


class GmailSource:
    """Gmail native source adapter implementing the Source protocol."""

    name: str = "gmail"

    def __init__(
        self,
        token_provider: str | Callable[[], str] | None = None,
        *,
        secret_ref: str | None = None,
        query: str = DEFAULT_GMAIL_QUERY,
        lookback_days: int = 7,
        user_id: str = "me",
        http_client: Any = None,
        fetch_limit: int = 100,
        latency_budget_seconds: float = 30.0,
    ) -> None:
        self.token_provider = token_provider
        self.secret_ref = secret_ref
        self.query = query
        self.lookback_days = lookback_days
        self.user_id = user_id
        self._http_client = http_client
        self.fetch_limit = fetch_limit
        self.latency_budget_seconds = latency_budget_seconds

    def _get_token(self) -> str:
        if callable(self.token_provider):
            return self.token_provider()
        if isinstance(self.token_provider, str):
            return self.token_provider
        if self.secret_ref:
            token = secrets.get_secret(self.secret_ref)
            if token:
                return token
        token = secrets.get_secret("google")
        if token:
            # If stored as JSON credentials
            if token.startswith("{"):
                try:
                    data = json.loads(token)
                    return data.get("access_token") or data.get("token") or token
                except json.JSONDecodeError:
                    pass
            return token
        return ""

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._http_client is not None:
            if hasattr(self._http_client, "get"):
                return self._http_client.get(path, params=params)
            if callable(self._http_client):
                return self._http_client("GET", path, params=params)

        token = self._get_token()
        headers = {
            "Accept": "application/json",
            "User-Agent": "cuecal/0.1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        url = f"{GMAIL_API_BASE}{path}"
        if params:
            encoded_params = urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}
            )
            url = f"{url}?{encoded_params}"

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                data = resp.read()
                return json.loads(data.decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code in (429, 503):
                retry_after = err.headers.get("Retry-After")
                logger.warning(
                    "Gmail API rate limited (%d), Retry-After: %s", err.code, retry_after
                )
            raise

    def _fetch_initial(self, limit: int | None = None) -> tuple[list[Message], str]:
        """First run bounded by lookback window, fetch cap, and latency budget."""
        effective_limit = limit if limit is not None else self.fetch_limit
        start_time = time.monotonic()
        cutoff = datetime.now(UTC) - timedelta(days=self.lookback_days)
        after_epoch = int(cutoff.timestamp())

        q = f"({self.query}) after:{after_epoch}" if self.query else f"after:{after_epoch}"
        max_results = min(max(effective_limit, 1), 100)
        list_resp = self._request(
            f"/users/{self.user_id}/messages", params={"q": q, "maxResults": max_results}
        )
        message_summaries = list_resp.get("messages", [])

        # Fetch current mailbox historyId from profile
        try:
            profile = self._request(f"/users/{self.user_id}/profile")
            next_cursor = str(profile.get("historyId", ""))
        except Exception:
            next_cursor = ""

        messages: list[Message] = []
        max_history_id = 0

        for summary in message_summaries:
            if len(messages) >= effective_limit:
                break
            if time.monotonic() - start_time >= self.latency_budget_seconds:
                logger.warning(
                    "Gmail initial fetch exceeded latency budget (%ss)",
                    self.latency_budget_seconds,
                )
                break
            msg_id = summary.get("id")
            if not msg_id:
                continue
            try:
                msg_data = self._request(
                    f"/users/{self.user_id}/messages/{msg_id}", params={"format": "full"}
                )
                h_id = int(msg_data.get("historyId", 0))
                if h_id > max_history_id:
                    max_history_id = h_id
                messages.append(parse_gmail_message(msg_data))
            except Exception as exc:
                logger.warning("Failed to fetch Gmail message %s: %s", msg_id, exc)

        if not next_cursor and max_history_id > 0:
            next_cursor = str(max_history_id)

        return messages, next_cursor

    def _fetch_incremental(
        self, cursor: str, limit: int | None = None
    ) -> tuple[list[Message], str]:
        """Incremental fetch using history.list from stored historyId under caps and budget."""
        effective_limit = limit if limit is not None else self.fetch_limit
        start_time = time.monotonic()
        try:
            history_resp = self._request(
                f"/users/{self.user_id}/history",
                params={
                    "startHistoryId": cursor,
                    "historyTypes": "messageAdded",
                    "maxResults": 100,
                },
            )
        except urllib.error.HTTPError as err:
            if err.code in (404, 400):
                logger.warning(
                    "Gmail historyId %s expired or invalid (HTTP %d); "
                    "falling back to lookback window",
                    cursor,
                    err.code,
                )
                return self._fetch_initial(limit=limit)
            raise
        except Exception as err:
            # Handle HTTP 404 in custom mock clients
            err_code = getattr(err, "code", None) or getattr(err, "status_code", None)
            if err_code in (404, 400):
                return self._fetch_initial(limit=limit)
            raise

        history_records = history_resp.get("history", [])

        # Process record by record so cursor only advances past completed records
        messages: list[Message] = []
        current_cursor = cursor
        seen_ids: set[str] = set()
        limit_reached = False

        for record in history_records:
            record_id = str(record.get("id", ""))
            record_msg_ids: list[str] = []
            for added in record.get("messagesAdded", []):
                msg_info = added.get("message", {})
                m_id = msg_info.get("id")
                if m_id and m_id not in seen_ids:
                    seen_ids.add(m_id)
                    record_msg_ids.append(m_id)
            for msg_info in record.get("messages", []):
                m_id = msg_info.get("id")
                if m_id and m_id not in seen_ids:
                    seen_ids.add(m_id)
                    record_msg_ids.append(m_id)

            for msg_id in record_msg_ids:
                if len(messages) >= effective_limit:
                    limit_reached = True
                    break
                if time.monotonic() - start_time >= self.latency_budget_seconds:
                    logger.warning(
                        "Gmail incremental fetch exceeded latency budget (%ss)",
                        self.latency_budget_seconds,
                    )
                    limit_reached = True
                    break
                try:
                    msg_data = self._request(
                        f"/users/{self.user_id}/messages/{msg_id}", params={"format": "full"}
                    )
                    if matches_query(msg_data, self.query):
                        messages.append(parse_gmail_message(msg_data))
                except Exception as exc:
                    logger.warning("Failed to fetch Gmail message %s: %s", msg_id, exc)

            if limit_reached:
                break
            if record_id:
                current_cursor = record_id

        if not limit_reached:
            next_cursor = str(history_resp.get("historyId", current_cursor))
        else:
            next_cursor = current_cursor

        return messages, next_cursor

    def fetch_since(
        self, cursor: str | None, limit: int | None = None
    ) -> tuple[list[Message], str]:
        """Fetch messages since cursor. Returns new messages and next historyId cursor."""
        if not cursor:
            return self._fetch_initial(limit=limit)
        return self._fetch_incremental(cursor, limit=limit)

