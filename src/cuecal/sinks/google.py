"""Google Calendar sink adapter implementing the Sink protocol."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from dateutil import parser as dateparser

from cuecal import secrets
from cuecal.conference import (
    ConferencePlan,
    _provider_for_uri,
    event_conference_uris,
    meet_join_url,
    normalize_meet_code,
    plan_conference,
)
from cuecal.config import ConferenceConfig
from cuecal.models import MeetingCandidate
from cuecal.sinks.base import SinkEvent

logger = logging.getLogger("cuecal.sinks.google")

GOOGLE_CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"


def parse_calendar_event(data: dict[str, Any]) -> SinkEvent:
    """Parse a Google Calendar REST API event resource into a cuecal SinkEvent."""
    event_id = data.get("id", "")
    title = data.get("summary", "")

    start_raw = data.get("start", {})
    end_raw = data.get("end", {})

    start_str = start_raw.get("dateTime") or start_raw.get("date") or ""
    end_str = end_raw.get("dateTime") or end_raw.get("date") or ""

    if start_str:
        try:
            start_dt = dateparser.parse(start_str)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=UTC)
        except (ValueError, OverflowError):
            start_dt = datetime.now(UTC)
    else:
        start_dt = datetime.now(UTC)

    if end_str:
        try:
            end_dt = dateparser.parse(end_str)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=UTC)
        except (ValueError, OverflowError):
            end_dt = start_dt + timedelta(minutes=30)
    else:
        end_dt = start_dt + timedelta(minutes=30)

    location = data.get("location")
    description = data.get("description")
    meeting_id = (
        data.get("extendedProperties", {}).get("private", {}).get("cuecalMeetingId")
    )
    html_link = data.get("htmlLink")

    return SinkEvent(
        id=event_id,
        title=title,
        start=start_dt,
        end=end_dt,
        location=location,
        description=description,
        meeting_id=meeting_id,
        html_link=html_link,
        raw=data,
    )


def _mirror_of(event: dict[str, Any]) -> str | None:
    """Return the ``cuecalMirrorOf`` key of a calendar mirror, else None."""
    return ((event.get("extendedProperties") or {}).get("private") or {}).get("cuecalMirrorOf")


SAME_MEETING_WINDOW = timedelta(minutes=15)


def _starts_near(event: dict[str, Any], start: datetime | None) -> bool:
    """True when the event starts within 15 minutes of ``start`` (one recurring instance)."""
    raw = (event.get("start") or {}).get("dateTime")
    if start is None or not raw:
        return False
    try:
        ev_start = dateparser.parse(raw)
    except (ValueError, OverflowError):
        return False
    if ev_start.tzinfo is None:
        ev_start = ev_start.replace(tzinfo=UTC)
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    return abs(ev_start - start) <= SAME_MEETING_WINDOW


def _meet_code(event: dict[str, Any]) -> str | None:
    for uri in event_conference_uris(event):
        code = normalize_meet_code(uri)
        if code:
            return code
    return None


class GoogleCalendarSink:
    """Google Calendar native sink adapter implementing the Sink protocol."""

    name: str = "google-calendar"

    def __init__(
        self,
        token_provider: str | Callable[[], str] | None = None,
        *,
        calendar_id: str = "primary",
        secret_ref: str | None = None,
        dry_run: bool = False,
        http_client: Any = None,
        conference_poll_attempts: int = 3,
        conference_poll_delay: float = 1.0,
    ) -> None:
        self.conference_poll_attempts = conference_poll_attempts
        self.conference_poll_delay = conference_poll_delay
        self.token_provider = token_provider
        self.calendar_id = calendar_id
        self.secret_ref = secret_ref
        self.dry_run = dry_run
        self._http_client = http_client

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
            if token.startswith("{"):
                try:
                    data = json.loads(token)
                    return data.get("access_token") or data.get("token") or token
                except json.JSONDecodeError:
                    pass
            return token
        return ""

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._http_client is not None:
            if hasattr(self._http_client, "request"):
                return self._http_client.request(method, path, params=params, json=body)
            method_lower = method.lower()
            if hasattr(self._http_client, method_lower):
                handler = getattr(self._http_client, method_lower)
                try:
                    return handler(path, params=params, json=body)
                except TypeError:
                    return handler(path, params=params, body=body)
            if callable(self._http_client):
                return self._http_client(method, path, params=params, body=body)

        token = self._get_token()
        headers = {
            "Accept": "application/json",
            "User-Agent": "cuecal/0.1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        data_bytes = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data_bytes = json.dumps(body).encode("utf-8")

        url = f"{GOOGLE_CALENDAR_API_BASE}{path}"
        if params:
            encoded_params = urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}
            )
            url = f"{url}?{encoded_params}"

        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers=headers,
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(req) as resp:
                raw_resp = resp.read()
                if not raw_resp:
                    return {}
                return json.loads(raw_resp.decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code in (429, 503):
                retry_after = err.headers.get("Retry-After")
                logger.warning(
                    "Google Calendar API rate limited (%d), Retry-After: %s",
                    err.code,
                    retry_after,
                )
            raise

    def _candidate_to_event_body(self, c: MeetingCandidate) -> dict[str, Any]:
        if c.start is None:
            raise ValueError("MeetingCandidate.start is required to format calendar event")

        start_dt = c.start
        end_dt = c.end or (start_dt + timedelta(minutes=30))

        start_dict: dict[str, Any] = {"dateTime": start_dt.isoformat()}
        end_dict: dict[str, Any] = {"dateTime": end_dt.isoformat()}

        if c.tz:
            start_dict["timeZone"] = c.tz
            end_dict["timeZone"] = c.tz
        elif start_dt.tzinfo is not None:
            start_dict["timeZone"] = str(start_dt.tzinfo)
            if end_dt.tzinfo is not None:
                end_dict["timeZone"] = str(end_dt.tzinfo)

        body: dict[str, Any] = {
            "summary": c.title or "Meeting",
            "start": start_dict,
            "end": end_dict,
        }

        if c.join_url:
            body["location"] = c.join_url
            body["conferenceData"] = {
                "entryPoints": [
                    {
                        "entryPointType": "video",
                        "uri": c.join_url,
                        "label": c.join_url,
                    }
                ],
                "conferenceSolution": {
                    "name": "Video Conference",
                    "key": {
                        "type": (
                            "eventHangout"
                            if "meet.google.com" in c.join_url
                            else "addOn"
                        )
                    },
                },
            }

        desc_lines: list[str] = []
        if c.source_ref:
            desc_lines.append(f"Source: {c.source_ref}")
        if c.join_url:
            desc_lines.append(f"Join URL: {c.join_url}")
        if c.passcode:
            desc_lines.append(f"Passcode: {c.passcode}")
        if c.meeting_id:
            desc_lines.append(f"Meeting ID: {c.meeting_id}")
        if c.attendees:
            desc_lines.append(f"Attendees: {', '.join(c.attendees)}")

        if desc_lines:
            body["description"] = "\n".join(desc_lines)

        if c.meeting_id:
            body["extendedProperties"] = {
                "private": {
                    "cuecalMeetingId": c.meeting_id,
                }
            }

        if c.attendees:
            body["attendees"] = [
                {"email": a} if "@" in a else {"displayName": a} for a in c.attendees
            ]

        return body

    def events_by_meeting_id(self, meeting_id: str) -> list[dict[str, Any]]:
        """Return the raw, non-cancelled events carrying this ``cuecalMeetingId``."""
        encoded_cal = urllib.parse.quote(self.calendar_id, safe="")
        params = {"privateExtendedProperty": f"cuecalMeetingId={meeting_id}"}
        resp = self._request("GET", f"/calendars/{encoded_cal}/events", params=params)
        return [i for i in resp.get("items", []) if i.get("status") != "cancelled"]

    def find_by_meeting_id(self, meeting_id: str) -> SinkEvent | None:
        """Look up an existing sink event by its unique meeting ID."""
        items = self.events_by_meeting_id(meeting_id)
        return parse_calendar_event(items[0]) if items else None

    def create(self, c: MeetingCandidate) -> SinkEvent:
        """Create a new event from a MeetingCandidate (idempotent if meeting_id exists).

        A calendar mirror of the same meeting at the same time wins: it is returned untouched.
        """
        if c.meeting_id:
            items = self.events_by_meeting_id(c.meeting_id)
            mirror = next(
                (i for i in items if _mirror_of(i) and _starts_near(i, c.start)), None
            )
            if mirror is not None:
                logger.info(
                    "Event %s already mirrors meeting_id %s; leaving the mirror as is",
                    mirror.get("id"),
                    c.meeting_id,
                )
                return parse_calendar_event(mirror)
            own = next((i for i in items if not _mirror_of(i)), None)
            existing = parse_calendar_event(own) if own is not None else None
            if existing is not None:
                logger.info(
                    "Event already exists for meeting_id %s; updating existing event %s",
                    c.meeting_id,
                    existing.id,
                )
                return self.update(existing.id, c)

        body = self._candidate_to_event_body(c)

        if self.dry_run:
            logger.info(
                "[DRY RUN] Would create Google Calendar event: %s at %s",
                c.title,
                c.start,
            )
            start_dt = c.start or datetime.now(UTC)
            end_dt = c.end or (start_dt + timedelta(minutes=30))
            return SinkEvent(
                id=f"dry-run-{c.meeting_id or 'new'}",
                title=c.title or "Meeting",
                start=start_dt,
                end=end_dt,
                location=c.join_url,
                description=body.get("description"),
                meeting_id=c.meeting_id,
                html_link="https://calendar.google.com/calendar/event?eid=dryrun",
                raw=body,
            )

        encoded_cal = urllib.parse.quote(self.calendar_id, safe="")
        params: dict[str, Any] = {}
        if "conferenceData" in body:
            params["conferenceDataVersion"] = 1

        resp = self._request(
            "POST",
            f"/calendars/{encoded_cal}/events",
            params=params or None,
            body=body,
        )
        return parse_calendar_event(resp)

    def update(self, event_id: str, c: MeetingCandidate) -> SinkEvent:
        """Update an existing sink event with new candidate details."""
        body = self._candidate_to_event_body(c)

        if self.dry_run:
            logger.info(
                "[DRY RUN] Would update Google Calendar event %s: %s",
                event_id,
                c.title,
            )
            start_dt = c.start or datetime.now(UTC)
            end_dt = c.end or (start_dt + timedelta(minutes=30))
            return SinkEvent(
                id=event_id,
                title=c.title or "Meeting",
                start=start_dt,
                end=end_dt,
                location=c.join_url,
                description=body.get("description"),
                meeting_id=c.meeting_id,
                html_link=f"https://calendar.google.com/calendar/event?eid={event_id}",
                raw=body,
            )

        encoded_cal = urllib.parse.quote(self.calendar_id, safe="")
        encoded_event = urllib.parse.quote(event_id, safe="")
        params: dict[str, Any] = {}
        if "conferenceData" in body:
            params["conferenceDataVersion"] = 1

        resp = self._request(
            "PATCH",
            f"/calendars/{encoded_cal}/events/{encoded_event}",
            params=params or None,
            body=body,
        )
        return parse_calendar_event(resp)

    def provision_conference(
        self, event_id: str, conf: ConferenceConfig
    ) -> ConferencePlan:
        """Add a Google Meet link to an event, or replace a configured provider's link.

        Returns the decided plan. Under ``dry_run`` the plan is logged and nothing is mutated.
        """
        encoded_cal = urllib.parse.quote(self.calendar_id, safe="")
        encoded_event = urllib.parse.quote(event_id, safe="")
        path = f"/calendars/{encoded_cal}/events/{encoded_event}"

        event = self._request("GET", path)
        plan = plan_conference(event, conf)
        if plan.action == "skip":
            logger.info("Conference skipped for event %s: %s", event_id, plan.reason)
            return plan
        if self.dry_run:
            logger.info("[DRY RUN] Would %s Meet link on event %s", plan.action, event_id)
            return plan

        patch_body = {
            "conferenceData": {
                "createRequest": {
                    "requestId": uuid.uuid4().hex,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
        }
        resp = self._request(
            "PATCH", path, params={"conferenceDataVersion": 1}, body=patch_body
        )
        # A pending create request carries no Meet URI yet: re-read the event a few times.
        for attempt in range(self.conference_poll_attempts):
            if _meet_code(resp) or attempt == self.conference_poll_attempts - 1:
                break
            time.sleep(self.conference_poll_delay)
            resp = self._request("GET", path)

        code = _meet_code(resp)
        if code is None:
            logger.warning(
                "Meet link for event %s is still pending after %d reads; metadata not written",
                event_id,
                self.conference_poll_attempts,
            )
            return plan

        if plan.action == "replace":
            old = [
                u
                for u in event_conference_uris(resp)
                if normalize_meet_code(u) is None
                and _provider_for_uri(u) in set(conf.replace)
            ]
            if old:
                logger.warning(
                    "Event %s still lists replaced provider link(s) %s after the Meet "
                    "create request; metadata not written",
                    event_id,
                    old,
                )
                return plan

        private = dict((event.get("extendedProperties") or {}).get("private") or {})
        private["cuecalMeetingId"] = code
        meta: dict[str, Any] = {"extendedProperties": {"private": private}}
        # Keep a physical location; only an empty one or a replaced provider's URL is overwritten.
        location = (event.get("location") or "").strip()
        if not location or _provider_for_uri(location) in set(conf.replace):
            meta["location"] = meet_join_url(code)
        self._request("PATCH", path, body=meta)
        return plan

    def busy(self, start: datetime, end: datetime) -> list[SinkEvent]:
        """Return existing events overlapping the given time window."""
        start_iso = start.isoformat() if start.tzinfo else start.replace(tzinfo=UTC).isoformat()
        end_iso = end.isoformat() if end.tzinfo else end.replace(tzinfo=UTC).isoformat()

        encoded_cal = urllib.parse.quote(self.calendar_id, safe="")
        params = {
            "timeMin": start_iso,
            "timeMax": end_iso,
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        resp = self._request("GET", f"/calendars/{encoded_cal}/events", params=params)
        items = resp.get("items", [])
        # Imported here: sources.calendar imports this module.
        from cuecal.sources.calendar import meeting_id_for

        events = []
        for item in items:
            if item.get("status") == "cancelled":
                continue
            ev = parse_calendar_event(item)
            ev.conference_meeting_id = meeting_id_for(item)
            events.append(ev)
        return events
