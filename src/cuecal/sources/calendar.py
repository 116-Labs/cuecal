"""Calendar source: mirror events from secondary Google calendars into the target calendar.

Tools that read only an account's primary calendar never see events on calendars shared to it.
This source copies those events into CueCal's target calendar. A calendar event is already
structured, so it bypasses the extractor and the pending queue: ``fetch_since`` yields no
messages and the work happens in :meth:`CalendarSource.sync`, which ``cuecal run`` calls.

Each source calendar keeps its own ``syncToken`` cursor (``calendar:<id>``) and the horizon of
its last window scan (``calendar-window:<id>``), so events that enter the lookahead window as
time passes are listed once. Mirrors carry ``cuecalMirrorOf=<calendarId>:<eventId>`` and are
written with ``sendUpdates=none``; original guests are never copied.
"""

from __future__ import annotations

import logging
import sqlite3
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from dateutil import parser as dateparser

from cuecal import db
from cuecal.conference import MIRROR_PROPERTY, event_conference_uris
from cuecal.config import MirrorConfig
from cuecal.extract.tier0 import find_links
from cuecal.models import Message
from cuecal.sinks.google import SAME_MEETING_WINDOW, GoogleCalendarSink

logger = logging.getLogger("cuecal.sources.calendar")

MIRROR_OF = "cuecalMirrorOf"
MEETING_ID = "cuecalMeetingId"
SOURCE_UPDATED = "cuecalSourceUpdated"

SCOPE_EVENTS = "https://www.googleapis.com/auth/calendar.events"
SCOPE_CALENDAR_LIST = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
# The scopes ADR 0005 grants. `calendar.events` reads events on every calendar the user can
# access, so mirroring needs nothing beyond them.
GOOGLE_SCOPES = (SCOPE_EVENTS, SCOPE_CALENDAR_LIST)

FREE_BUSY_ROLE = "freeBusyReader"
_NO_EMAIL = {"sendUpdates": "none"}


def required_scope(path: str) -> str:
    """Return the OAuth scope that covers a Calendar API request path."""
    if path.startswith("/users/me/calendarList"):
        return SCOPE_CALENDAR_LIST
    if path.startswith("/calendars/") and "/events" in path:
        return SCOPE_EVENTS
    raise ValueError(f"no granted scope covers {path}")


def token_cursor_key(calendar_id: str) -> str:
    return f"calendar:{calendar_id}"


def window_cursor_key(calendar_id: str) -> str:
    return f"calendar-window:{calendar_id}"


@dataclass(frozen=True)
class CalendarInfo:
    id: str
    summary: str
    access_role: str
    primary: bool = False

    @property
    def free_busy_only(self) -> bool:
        return self.access_role == FREE_BUSY_ROLE


@dataclass(frozen=True)
class MirrorOp:
    action: str  # "create" | "update" | "convert" | "delete"
    key: str
    title: str
    start: str | None = None
    event_id: str | None = None

    def describe(self) -> str:
        when = f" at {self.start}" if self.start else ""
        target = f" (target event {self.event_id})" if self.event_id else ""
        return f"{self.action} mirror {self.key}: {self.title!r}{when}{target}"


def _private(event: dict[str, Any]) -> dict[str, Any]:
    return (event.get("extendedProperties") or {}).get("private") or {}


def _shared(event: dict[str, Any]) -> dict[str, Any]:
    return (event.get("extendedProperties") or {}).get("shared") or {}


def mirror_key(event: dict[str, Any]) -> str | None:
    return _private(event).get(MIRROR_OF)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = dateparser.parse(raw)
    except (ValueError, OverflowError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _status_code(exc: Exception) -> int | None:
    return getattr(exc, "code", None) or getattr(exc, "status_code", None)


def is_all_day(event: dict[str, Any]) -> bool:
    start = event.get("start") or {}
    return "dateTime" not in start


def declined_by_owner(event: dict[str, Any]) -> bool:
    """The source calendar's owner (the user) declined the event."""
    return any(
        a.get("self") and a.get("responseStatus") == "declined"
        for a in event.get("attendees") or []
    )


def skip_reason(
    event: dict[str, Any], *, self_email: str | None, include_transparent: bool = False
) -> str | None:
    """Why ``event`` must not be mirrored, or None. Declines and cancellations are separate."""
    if MIRROR_OF in _private(event) or MIRROR_OF in _shared(event) or _private(event).get(
        MIRROR_PROPERTY
    ):
        return "created by CueCal"
    if is_all_day(event):
        return "all-day event"
    if event.get("transparency") == "transparent" and not include_transparent:
        return "marked free (transparent)"
    if self_email:
        for a in event.get("attendees") or []:
            if (a.get("email") or "").lower() == self_email and a.get(
                "responseStatus"
            ) != "declined":
                return "target account is already invited"
    return None


def conference_link(event: dict[str, Any]) -> str | None:
    if event.get("hangoutLink"):
        return event["hangoutLink"]
    entries = (event.get("conferenceData") or {}).get("entryPoints") or []
    for entry in entries:
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            return entry["uri"]
    uris = event_conference_uris(event)
    return uris[0] if uris else None


def meeting_id_for(event: dict[str, Any]) -> str | None:
    """Parse a Zoom/Meet/Teams meeting ID the same way the extractor does, for #10 dedupe."""
    parts = [*event_conference_uris(event), event.get("location") or ""]
    parts.append(event.get("description") or "")
    links = find_links("\n".join(parts))
    return links[0].meeting_id if links else None


def _attendee_line(a: dict[str, Any]) -> str:
    name = a.get("displayName")
    email = a.get("email") or ""
    who = f"{name} <{email}>" if name and email else (name or email or "unknown")
    status = a.get("responseStatus")
    return f"- {who}" + (f" ({status})" if status else "")


def build_mirror_body(
    event: dict[str, Any],
    *,
    key: str,
    calendar_name: str,
    cfg: MirrorConfig,
    self_email: str | None,
    meeting_id: str | None,
) -> dict[str, Any]:
    """Shape a mirror of ``event``. Original guests only ever appear as description text."""
    link = conference_link(event)
    location = (event.get("location") or "").strip()
    if link and link not in location:
        location = f"{location} | {link}" if location else link

    lines = [f"Mirrored by CueCal from calendar: {calendar_name}"]
    if event.get("htmlLink"):
        lines.append(f"Original event: {event['htmlLink']}")
    if link:
        lines.append(f"Join: {link}")
    guests = event.get("attendees") or []
    if guests:
        lines.append("Original attendees (not invited to this copy):")
        lines.extend(_attendee_line(a) for a in guests)

    private = {
        MIRROR_PROPERTY: "true",
        MIRROR_OF: key,
        SOURCE_UPDATED: event.get("updated") or "",
    }
    if meeting_id:
        private[MEETING_ID] = meeting_id

    start = event.get("start") or {}
    end = event.get("end") or {}
    body: dict[str, Any] = {
        "summary": event.get("summary") or "(no title)",
        "start": {k: start[k] for k in ("dateTime", "timeZone") if k in start},
        "end": {k: end[k] for k in ("dateTime", "timeZone") if k in end},
        "location": location,
        "description": "\n".join(lines),
        "visibility": "private",
        "transparency": cfg.transparency,
        # Explicit list: an update also strips guests a Gmail-invite event carried.
        "attendees": (
            [{"email": self_email, "responseStatus": "accepted"}]
            if cfg.self_attendee and self_email
            else []
        ),
        "extendedProperties": {"private": private},
    }
    return body


class CalendarSource:
    """Mirror secondary calendars into the target calendar (implements the Source protocol)."""

    name: str = "calendar"

    def __init__(
        self,
        cfg: MirrorConfig | None = None,
        *,
        target: GoogleCalendarSink | None = None,
        token_provider: str | Callable[[], str] | None = None,
        http_client: Any = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.cfg = cfg or MirrorConfig()
        self.target = target or GoogleCalendarSink(
            token_provider, calendar_id=self.cfg.target_calendar, http_client=http_client
        )
        self._now = now or (lambda: datetime.now(UTC))
        self._calendars: list[CalendarInfo] | None = None

    def fetch_since(self, cursor: str | None) -> tuple[list[Message], str | None]:
        """Mirrored events bypass the extractor, so this yields no messages; see ``sync``."""
        return [], cursor

    # -- Calendar API helpers ---------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.target._request(method, path, params=params, body=body)

    def _target_path(self, event_id: str | None = None) -> str:
        path = f"/calendars/{urllib.parse.quote(self.cfg.target_calendar, safe='')}/events"
        return f"{path}/{urllib.parse.quote(event_id, safe='')}" if event_id else path

    def _list_events(
        self, calendar_id: str, params: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], str | None]:
        """List every page; returns the items and the final page's ``nextSyncToken``."""
        path = f"/calendars/{urllib.parse.quote(calendar_id, safe='')}/events"
        items: list[dict[str, Any]] = []
        page: str | None = None
        while True:
            query = dict(params)
            if page:
                query["pageToken"] = page
            resp = self._request("GET", path, params=query)
            items.extend(resp.get("items") or [])
            page = resp.get("nextPageToken")
            if not page:
                return items, resp.get("nextSyncToken")

    def _list_target(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        items, _ = self._list_events(self.cfg.target_calendar, params)
        return [i for i in items if i.get("status") != "cancelled"]

    def list_calendars(self) -> list[CalendarInfo]:
        """The account's calendar list, for the picker and source validation."""
        if self._calendars is None:
            calendars: list[CalendarInfo] = []
            page: str | None = None
            while True:
                resp = self._request(
                    "GET", "/users/me/calendarList", params={"pageToken": page} if page else None
                )
                for item in resp.get("items") or []:
                    calendars.append(
                        CalendarInfo(
                            id=item.get("id", ""),
                            summary=item.get("summaryOverride") or item.get("summary") or "",
                            access_role=item.get("accessRole", ""),
                            primary=bool(item.get("primary")),
                        )
                    )
                page = resp.get("nextPageToken")
                if not page:
                    break
            self._calendars = calendars
        return self._calendars

    def self_email(self) -> str | None:
        if self.cfg.self_email:
            return self.cfg.self_email.lower()
        primary = next((c for c in self.list_calendars() if c.primary), None)
        return primary.id.lower() if primary and "@" in primary.id else None

    def target_ids(self) -> set[str]:
        """Lower-cased IDs naming the target calendar ("primary" and its account email)."""
        target = self.cfg.target_calendar.lower()
        ids = {target}
        email = self.self_email()
        if email and target in ("primary", email):
            ids |= {"primary", email}
        return ids

    def source_warnings(self) -> dict[str, str]:
        """Map each configured source calendar that cannot be mirrored to the reason."""
        known = {c.id: c for c in self.list_calendars()}
        targets = self.target_ids()
        warnings: dict[str, str] = {}
        for cal_id in self.cfg.source_calendars:
            info = known.get(cal_id)
            if cal_id.lower() in targets:
                warnings[cal_id] = "is the target calendar"
            elif info is None:
                warnings[cal_id] = "is not in this account's calendar list"
            elif info.free_busy_only:
                warnings[cal_id] = "shares free/busy only (titles hidden), so it is skipped"
        return warnings

    # -- Sync -----------------------------------------------------------------------------

    def sync(self, conn: sqlite3.Connection, *, dry_run: bool = False) -> list[MirrorOp]:
        """Mirror every configured source calendar. Under ``dry_run`` nothing is written."""
        warnings = self.source_warnings()
        known = {c.id: c for c in self.list_calendars()}
        ops: list[MirrorOp] = []
        for cal_id in self.cfg.source_calendars:
            if cal_id in warnings:
                logger.warning("source calendar %r %s", cal_id, warnings[cal_id])
                continue
            try:
                ops.extend(self.sync_calendar(conn, known[cal_id], dry_run=dry_run))
            except Exception as exc:  # noqa: BLE001 - one calendar must not stop the others
                logger.warning("mirroring calendar %r failed: %s", cal_id, exc)
        return ops

    def sync_calendar(
        self, conn: sqlite3.Connection, info: CalendarInfo, *, dry_run: bool = False
    ) -> list[MirrorOp]:
        now = self._now()
        horizon = now + timedelta(days=self.cfg.lookahead_days)
        token = db.get_cursor(conn, token_cursor_key(info.id))
        changed: list[dict[str, Any]] = []
        next_token: str | None = None
        full = token is None
        if token:
            try:
                changed, next_token = self._list_events(
                    info.id, {"syncToken": token, "singleEvents": "true"}
                )
            except Exception as exc:
                if _status_code(exc) != 410:
                    raise
                logger.warning("sync token for %r expired (410); resyncing the window", info.id)
                full = True
        if full:
            changed, next_token = self._list_events(
                info.id,
                {"singleEvents": "true", "timeMin": _iso(now), "timeMax": _iso(horizon)},
            )
        else:
            # A sync token only reports edits, never events that the window slid onto.
            mark = _parse_dt(db.get_cursor(conn, window_cursor_key(info.id)))
            since = max(mark, now) if mark else now
            if horizon > since:
                entered, _ = self._list_events(
                    info.id,
                    {"singleEvents": "true", "timeMin": _iso(since), "timeMax": _iso(horizon)},
                )
                seen = {e.get("id") for e in changed}
                changed.extend(e for e in entered if e.get("id") not in seen)

        ops: list[MirrorOp] = []
        for event in changed:
            op = self._apply(info, event, now=now, horizon=horizon, dry_run=dry_run)
            if op is not None:
                ops.append(op)

        if not dry_run:
            if next_token:
                db.set_cursor(conn, token_cursor_key(info.id), next_token)
            db.set_cursor(conn, window_cursor_key(info.id), _iso(horizon))
        return ops

    def _find_mirror(self, key: str) -> dict[str, Any] | None:
        items = self._list_target({"privateExtendedProperty": f"{MIRROR_OF}={key}"})
        return items[0] if items else None

    def _native_copy_on_target(self, event: dict[str, Any]) -> bool:
        uid = event.get("iCalUID")
        if not uid:
            return False
        return any(not mirror_key(i) for i in self._list_target({"iCalUID": uid}))

    def _convertible(self, meeting_id: str, start: datetime | None) -> dict[str, Any] | None:
        """A CueCal-created, not yet mirrored event for the same meeting at the same time."""
        if start is None:
            return None
        for item in self.target.events_by_meeting_id(meeting_id):
            ev_start = _parse_dt((item.get("start") or {}).get("dateTime"))
            if mirror_key(item) or ev_start is None:
                continue
            if abs(ev_start - start) <= SAME_MEETING_WINDOW:
                return item
        return None

    def _apply(
        self,
        info: CalendarInfo,
        event: dict[str, Any],
        *,
        now: datetime,
        horizon: datetime,
        dry_run: bool,
    ) -> MirrorOp | None:
        event_id = event.get("id")
        if not event_id:
            return None
        key = f"{info.id}:{event_id}"
        title = event.get("summary") or "(no title)"
        start_raw = (event.get("start") or {}).get("dateTime")
        mirror = self._find_mirror(key)

        if event.get("status") == "cancelled" or declined_by_owner(event):
            if mirror is None:
                return None
            op = MirrorOp("delete", key, mirror.get("summary") or title, None, mirror["id"])
            if not dry_run:
                self._request("DELETE", self._target_path(mirror["id"]), params=dict(_NO_EMAIL))
            return op

        email = self.self_email()
        reason = skip_reason(
            event, self_email=email, include_transparent=self.cfg.include_transparent
        )
        if reason:
            logger.debug("not mirroring %s: %s", key, reason)
            return None

        meeting_id = meeting_id_for(event)
        body = build_mirror_body(
            event,
            key=key,
            calendar_name=info.summary or info.id,
            cfg=self.cfg,
            self_email=email,
            meeting_id=meeting_id,
        )

        if mirror is not None:
            if _private(mirror).get(SOURCE_UPDATED) == (event.get("updated") or ""):
                return None
            op = MirrorOp("update", key, title, start_raw, mirror["id"])
            if not dry_run:
                self._request(
                    "PATCH", self._target_path(mirror["id"]), params=dict(_NO_EMAIL), body=body
                )
            return op

        start = _parse_dt(start_raw)
        end = _parse_dt((event.get("end") or {}).get("dateTime")) or start
        if start is None or end is None or end <= now or start >= horizon:
            return None
        if self._native_copy_on_target(event):
            logger.debug("not mirroring %s: same iCalUID already on the target", key)
            return None

        if meeting_id:
            own = self._convertible(meeting_id, start)
            if own is not None:
                op = MirrorOp("convert", key, title, start_raw, own["id"])
                if not dry_run:
                    self._request(
                        "PATCH", self._target_path(own["id"]), params=dict(_NO_EMAIL), body=body
                    )
                return op

        op = MirrorOp("create", key, title, start_raw)
        if not dry_run:
            created = self._request("POST", self._target_path(), params=dict(_NO_EMAIL), body=body)
            op = MirrorOp("create", key, title, start_raw, created.get("id"))
        return op

    # -- Prune ----------------------------------------------------------------------------

    def prune(self, *, dry_run: bool = False) -> list[MirrorOp]:
        """Delete mirrors whose source calendar is no longer configured."""
        keep = set(self.cfg.source_calendars)
        ops: list[MirrorOp] = []
        for item in self._list_target({"privateExtendedProperty": f"{MIRROR_PROPERTY}=true"}):
            key = mirror_key(item)
            if not key or key.rsplit(":", 1)[0] in keep:
                continue
            start = (item.get("start") or {}).get("dateTime")
            ops.append(MirrorOp("delete", key, item.get("summary") or "", start, item["id"]))
            if not dry_run:
                self._request("DELETE", self._target_path(item["id"]), params=dict(_NO_EMAIL))
        return ops
