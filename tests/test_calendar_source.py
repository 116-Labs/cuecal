"""Tests for the calendar source that mirrors secondary calendars into the target calendar."""

from __future__ import annotations

import copy
import json
import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from cuecal import cli, db, registry
from cuecal.conference import plan_conference
from cuecal.config import ConferenceConfig, MirrorConfig
from cuecal.models import MeetingCandidate
from cuecal.sinks.google import GoogleCalendarSink
from cuecal.sources import CalendarSource, Source
from cuecal.sources.calendar import (
    GOOGLE_SCOPES,
    MIRROR_OF,
    SCOPE_CALENDAR_LIST,
    SCOPE_EVENTS,
    required_scope,
    token_cursor_key,
    window_cursor_key,
)

FIXTURES = Path(__file__).parent / "fixtures" / "calendar"
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
WORK = "work@group.calendar.google.com"
TEAM = "team@group.calendar.google.com"
BUSY = "busy@group.calendar.google.com"
ME = "me@example.com"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ApiError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(f"HTTP {code}")
        self.code = code


class FakeCalendarApi:
    """In-memory Calendar API: a stateful target calendar plus scripted source calendars."""

    def __init__(self) -> None:
        self.calendar_list = load("calendar_list.json")
        self.target: dict[str, dict[str, Any]] = {}
        self.sources: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self.calls: list[tuple[str, str, dict[str, Any], dict[str, Any] | None]] = []
        self._ids = 0

    def seed(self, event: dict[str, Any]) -> dict[str, Any]:
        self.target[event["id"]] = copy.deepcopy(event)
        return self.target[event["id"]]

    def writes(self) -> list[tuple[str, str, dict[str, Any], dict[str, Any] | None]]:
        return [c for c in self.calls if c[0] != "GET"]

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = dict(params or {})
        self.calls.append((method, path, params, copy.deepcopy(json)))
        if path == "/users/me/calendarList":
            return self.calendar_list
        parts = path.split("/")
        cal = urllib.parse.unquote(parts[2])
        event_id = urllib.parse.unquote(parts[4]) if len(parts) > 4 else None
        if cal not in ("primary", ME):
            assert method == "GET", f"wrote to source calendar {cal}"
            return self.sources[cal](params)
        return self._target(method, event_id, params, json)

    def _target(
        self, method: str, event_id: str | None, params: dict[str, Any], body: Any
    ) -> dict[str, Any]:
        if method == "GET" and event_id is None:
            items = list(self.target.values())
            if "privateExtendedProperty" in params:
                k, v = params["privateExtendedProperty"].split("=", 1)
                items = [
                    i
                    for i in items
                    if ((i.get("extendedProperties") or {}).get("private") or {}).get(k) == v
                ]
            if "iCalUID" in params:
                items = [i for i in items if i.get("iCalUID") == params["iCalUID"]]
            return {"items": copy.deepcopy(items)}
        if method == "POST":
            self._ids += 1
            new_id = f"target{self._ids}"
            self.target[new_id] = {
                **copy.deepcopy(body),
                "id": new_id,
                "iCalUID": f"{new_id}@google.com",
                "status": "confirmed",
            }
            return copy.deepcopy(self.target[new_id])
        if method == "PATCH":
            event = self.target[event_id]
            for key, value in copy.deepcopy(body).items():
                if key == "extendedProperties":
                    private = (event.get("extendedProperties") or {}).get("private") or {}
                    private.update(value.get("private") or {})
                    event["extendedProperties"] = {"private": private}
                else:
                    event[key] = value
            return copy.deepcopy(event)
        if method == "DELETE":
            del self.target[event_id]
            return {}
        raise AssertionError(f"unexpected {method} {event_id}")


def recorded_work_calendar(expire: bool = False) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Replay the recorded events.list pages for the work calendar."""

    def respond(params: dict[str, Any]) -> dict[str, Any]:
        if "syncToken" in params:
            if expire or params["syncToken"] == "expired-token":
                raise ApiError(410)
            assert params["syncToken"] == "sync-token-1"
            return load("work_events_incremental.json")
        if params.get("pageToken") == "page-2":
            return load("work_events_page2.json")
        return load("work_events_page1.json")

    return respond


class ScriptedCalendar:
    """A source calendar that answers window listings and replays queued incremental changes."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events
        self.changes: list[dict[str, Any]] = []
        self.tokens = 0

    def __call__(self, params: dict[str, Any]) -> dict[str, Any]:
        self.tokens += 1
        if "syncToken" in params:
            items, self.changes = self.changes, []
        else:
            lo = datetime.fromisoformat(params["timeMin"].replace("Z", "+00:00"))
            hi = datetime.fromisoformat(params["timeMax"].replace("Z", "+00:00"))
            items = [
                e
                for e in self.events
                if "dateTime" not in e.get("start", {})
                or (_dt(e["end"]["dateTime"]) > lo and _dt(e["start"]["dateTime"]) < hi)
            ]
        return {"items": copy.deepcopy(items), "nextSyncToken": f"tok-{self.tokens}"}


def _dt(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def event(
    event_id: str,
    start: datetime,
    *,
    minutes: int = 30,
    summary: str = "Meeting",
    updated: str = "2026-10-01T00:00:00.000Z",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": event_id,
        "status": "confirmed",
        "summary": summary,
        "updated": updated,
        "htmlLink": f"https://www.google.com/calendar/event?eid={event_id}",
        "iCalUID": f"{event_id}@google.com",
        "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": (start + timedelta(minutes=minutes)).isoformat(), "timeZone": "UTC"},
        **extra,
    }


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "state.db")
    yield c
    c.close()


@pytest.fixture
def api() -> FakeCalendarApi:
    return FakeCalendarApi()


def make_source(
    api: FakeCalendarApi, sources: list[str], clock: Clock | None = None, **cfg: Any
) -> CalendarSource:
    return CalendarSource(
        MirrorConfig(source_calendars=sources, **cfg),
        token_provider="t",
        http_client=api,
        now=clock or Clock(),
    )


def mirrors(api: FakeCalendarApi) -> dict[str, dict[str, Any]]:
    return {
        e["extendedProperties"]["private"][MIRROR_OF]: e
        for e in api.target.values()
        if MIRROR_OF in ((e.get("extendedProperties") or {}).get("private") or {})
    }


# -- Contract tests on recorded fixtures --------------------------------------------------


def test_calendar_source_implements_source_protocol():
    source = CalendarSource(token_provider="t", http_client=FakeCalendarApi())
    assert isinstance(source, Source)
    assert source.fetch_since("anything") == ([], "anything")


def test_contract_full_sync_expands_recurring_instances_in_window(api, conn):
    api.sources[WORK] = recorded_work_calendar()
    ops = make_source(api, [WORK]).sync(conn)

    reads = [c for c in api.calls if c[1].startswith(f"/calendars/{urllib.parse.quote(WORK)}")]
    assert [r[2].get("pageToken") for r in reads] == [None, "page-2"]
    first = reads[0][2]
    assert first["singleEvents"] == "true"
    assert first["timeMin"] == "2026-10-08T12:00:00Z"
    assert first["timeMax"] == "2026-10-22T12:00:00Z"
    assert "syncToken" not in first

    created = mirrors(api)
    assert set(created) == {
        f"{WORK}:standup_20261009T160000Z",
        f"{WORK}:standup_20261010T160000Z",
        f"{WORK}:oneonone01",
    }
    assert [op.action for op in ops] == ["create", "create", "create"]
    assert db.get_cursor(conn, token_cursor_key(WORK)) == "sync-token-1"
    assert db.get_cursor(conn, window_cursor_key(WORK)) == "2026-10-22T12:00:00Z"


def test_contract_sync_token_advances_and_applies_changes(api, conn):
    api.sources[WORK] = recorded_work_calendar()
    source = make_source(api, [WORK])
    source.sync(conn)
    before = mirrors(api)
    one_on_one_id = before[f"{WORK}:oneonone01"]["id"]
    api.calls.clear()

    ops = source.sync(conn)

    incremental = [c for c in api.calls if "syncToken" in c[2]]
    assert len(incremental) == 1
    assert incremental[0][2] == {"syncToken": "sync-token-1", "singleEvents": "true"}
    assert db.get_cursor(conn, token_cursor_key(WORK)) == "sync-token-2"

    after = mirrors(api)
    # Time change patches the same mirror; the cancelled instance's mirror is deleted.
    assert after[f"{WORK}:oneonone01"]["id"] == one_on_one_id
    assert after[f"{WORK}:oneonone01"]["start"]["dateTime"] == "2026-10-12T16:00:00Z"
    assert f"{WORK}:standup_20261010T160000Z" not in after
    assert f"{WORK}:standup_20261009T160000Z" in after
    assert sorted(op.action for op in ops) == ["delete", "update"]


def test_contract_410_gone_triggers_bounded_full_resync(api, conn):
    api.sources[WORK] = recorded_work_calendar(expire=True)
    db.set_cursor(conn, token_cursor_key(WORK), "expired-token")

    make_source(api, [WORK]).sync(conn)

    reads = [c[2] for c in api.calls if c[1].startswith("/calendars/work")]
    assert reads[0]["syncToken"] == "expired-token"
    resync = reads[1]
    assert "syncToken" not in resync
    assert resync["timeMin"] == "2026-10-08T12:00:00Z"
    assert resync["timeMax"] == "2026-10-22T12:00:00Z"
    assert db.get_cursor(conn, token_cursor_key(WORK)) == "sync-token-1"
    assert len(mirrors(api)) == 3


def test_contract_needs_no_scope_beyond_adr_0005(api, conn):
    assert set(GOOGLE_SCOPES) == {SCOPE_EVENTS, SCOPE_CALENDAR_LIST}
    api.sources[WORK] = recorded_work_calendar()
    source = make_source(api, [WORK])
    source.sync(conn)
    source.sync(conn)
    source.prune(dry_run=True)

    assert api.calls
    for method, path, _, _ in api.calls:
        assert required_scope(path) in GOOGLE_SCOPES, (method, path)
    # Reading a source calendar's events is covered by calendar.events.
    source_reads = [p for _, p, _, _ in api.calls if p.startswith("/calendars/work")]
    assert source_reads and {required_scope(p) for p in source_reads} == {SCOPE_EVENTS}
    with pytest.raises(ValueError):
        required_scope("/calendars/work/acl")


# -- Lifecycle ---------------------------------------------------------------------------


def test_each_source_calendar_keeps_its_own_sync_token(api, conn):
    api.sources[WORK] = ScriptedCalendar([event("w1", NOW + timedelta(days=1))])
    api.sources[TEAM] = ScriptedCalendar([event("t1", NOW + timedelta(days=2))])
    make_source(api, [WORK, TEAM]).sync(conn)

    rows = dict(conn.execute("SELECT source, cursor FROM source_cursor").fetchall())
    assert rows[token_cursor_key(WORK)] == "tok-1"
    assert rows[token_cursor_key(TEAM)] == "tok-1"
    assert set(mirrors(api)) == {f"{WORK}:w1", f"{TEAM}:t1"}


def test_failing_calendar_does_not_stop_the_others(api, conn, caplog):
    def broken(params: dict[str, Any]) -> dict[str, Any]:
        raise ApiError(404)

    api.sources[WORK] = broken
    api.sources[TEAM] = ScriptedCalendar([event("t1", NOW + timedelta(days=1))])
    with caplog.at_level("WARNING", logger="cuecal.sources.calendar"):
        make_source(api, [WORK, TEAM]).sync(conn)

    assert "mirroring calendar" in caplog.text
    assert set(mirrors(api)) == {f"{TEAM}:t1"}
    assert db.get_cursor(conn, token_cursor_key(WORK)) is None


def test_running_sync_twice_creates_no_duplicates(api, conn):
    work = ScriptedCalendar([event("w1", NOW + timedelta(days=1))])
    api.sources[WORK] = work
    source = make_source(api, [WORK])
    source.sync(conn)
    # The incremental pass reports the same unchanged event again.
    work.changes = copy.deepcopy(work.events)
    source.sync(conn)
    # A lost cursor forces a full resync; the mirror lookup still finds the existing copy.
    conn.execute("DELETE FROM source_cursor")
    source.sync(conn)

    assert len(api.target) == 1
    assert len([c for c in api.writes() if c[0] == "POST"]) == 1


def test_mirror_out_of_window_is_kept_and_entering_event_created_once(api, conn):
    soon = event("soon", NOW + timedelta(days=1))
    later = event("later", NOW + timedelta(days=20))
    api.sources[WORK] = ScriptedCalendar([soon, later])
    clock = Clock()
    source = make_source(api, [WORK], clock)
    source.sync(conn)
    assert set(mirrors(api)) == {f"{WORK}:soon"}

    clock.now = NOW + timedelta(days=10)
    source.sync(conn)
    assert set(mirrors(api)) == {f"{WORK}:soon", f"{WORK}:later"}
    assert not [c for c in api.writes() if c[0] == "DELETE"]

    clock.now = NOW + timedelta(days=11)
    source.sync(conn)
    assert len([c for c in api.writes() if c[0] == "POST"]) == 2


def test_declining_the_source_event_deletes_its_mirror(api, conn):
    work = ScriptedCalendar([event("w1", NOW + timedelta(days=1))])
    api.sources[WORK] = work
    source = make_source(api, [WORK])
    source.sync(conn)
    declined = event(
        "w1",
        NOW + timedelta(days=1),
        updated="2026-10-08T13:00:00.000Z",
        attendees=[{"email": "me@work.example", "self": True, "responseStatus": "declined"}],
    )
    work.changes = [declined]
    source.sync(conn)
    assert mirrors(api) == {}


# -- Filters ---------------------------------------------------------------------------


def test_declined_all_day_and_cuecal_events_are_not_mirrored(api, conn):
    start = NOW + timedelta(days=1)
    owner_declined = {"email": "me@work.example", "self": True, "responseStatus": "declined"}
    all_day = {"start": {"date": "2026-10-09"}, "end": {"date": "2026-10-10"}}
    api.sources[WORK] = ScriptedCalendar(
        [
            event("declined", start, attendees=[owner_declined]),
            {**event("allday", start), **all_day},
            event(
                "tagged",
                start,
                extendedProperties={"private": {MIRROR_OF: "other@group:abc"}},
            ),
            event("kept", start),
        ]
    )
    make_source(api, [WORK]).sync(conn)
    assert set(mirrors(api)) == {f"{WORK}:kept"}


def test_transparent_events_skipped_unless_opted_in(api, conn, tmp_path):
    api.sources[WORK] = ScriptedCalendar(
        [event("free", NOW + timedelta(days=1), transparency="transparent")]
    )
    make_source(api, [WORK]).sync(conn)
    assert mirrors(api) == {}

    other = db.connect(tmp_path / "other.db")
    make_source(api, [WORK], include_transparent=True).sync(other)
    other.close()
    assert set(mirrors(api)) == {f"{WORK}:free"}


def test_native_duplicates_are_skipped(api, conn):
    start = NOW + timedelta(days=1)
    api.seed(
        {
            **event("native-copy", start, summary="Shared"),
            "iCalUID": "shared-uid@google.com",
        }
    )
    api.sources[WORK] = ScriptedCalendar(
        [
            event(
                "invited",
                start,
                attendees=[{"email": "Me@Example.com", "responseStatus": "accepted"}],
            ),
            {**event("same-uid", start), "iCalUID": "shared-uid@google.com"},
            event(
                "declined-self",
                start,
                attendees=[{"email": ME, "responseStatus": "declined"}],
            ),
        ]
    )
    make_source(api, [WORK]).sync(conn)
    assert set(mirrors(api)) == {f"{WORK}:declined-self"}


# -- Mirror shape ----------------------------------------------------------------------


def _guest_event(start: datetime) -> dict[str, Any]:
    return event(
        "g1",
        start,
        summary="Planning",
        location="HQ",
        hangoutLink="https://meet.google.com/abc-defg-hij",
        attendees=[
            {"email": "alice@work.example", "displayName": "Alice", "responseStatus": "accepted"},
            {"email": "bob@work.example", "responseStatus": "tentative"},
        ],
    )


@pytest.mark.parametrize("self_attendee", [True, False])
def test_mirrors_never_carry_original_guests(api, conn, self_attendee):
    work = ScriptedCalendar([_guest_event(NOW + timedelta(days=1))])
    api.sources[WORK] = work
    source = make_source(api, [WORK], self_attendee=self_attendee)
    source.sync(conn)
    work.changes = [{**_guest_event(NOW + timedelta(days=2)), "updated": "2026-10-08T14:00:00Z"}]
    source.sync(conn)

    expected = [{"email": ME, "responseStatus": "accepted"}] if self_attendee else []
    bodies = [c[3] for c in api.writes() if c[3] is not None]
    assert [c[0] for c in api.writes()] == ["POST", "PATCH"]
    for body in bodies:
        assert body["attendees"] == expected
        assert "alice@work.example" not in json.dumps(body["attendees"])
    mirror = mirrors(api)[f"{WORK}:g1"]
    assert mirror["visibility"] == "private"
    assert mirror["transparency"] == "opaque"
    assert mirror["location"] == "HQ | https://meet.google.com/abc-defg-hij"
    assert "Alice <alice@work.example> (accepted)" in mirror["description"]
    assert "Work (other account)" in mirror["description"]
    assert "Original event: https://www.google.com/calendar/event?eid=g1" in mirror["description"]
    assert mirror["extendedProperties"]["private"]["cuecalMeetingId"] == "abc-defg-hij"


def test_every_mirror_write_sends_no_emails(api, conn):
    work = ScriptedCalendar([event("w1", NOW + timedelta(days=1))])
    api.sources[WORK] = work
    source = make_source(api, [WORK])
    source.sync(conn)
    work.changes = [event("w1", NOW + timedelta(days=1, hours=1), updated="2026-10-08T15:00Z")]
    source.sync(conn)
    work.changes = [{"id": "w1", "status": "cancelled"}]
    source.sync(conn)

    writes = api.writes()
    assert [w[0] for w in writes] == ["POST", "PATCH", "DELETE"]
    for _, _, params, _ in writes:
        assert params.get("sendUpdates") == "none"


def test_mirrors_only_copy_existing_link_and_skip_conference_provisioning(api, conn):
    start = NOW + timedelta(days=1)
    api.sources[WORK] = ScriptedCalendar(
        [
            event("linked", start, hangoutLink="https://meet.google.com/abc-defg-hij"),
            event("linkless", start),
        ]
    )
    make_source(api, [WORK]).sync(conn)

    for _, _, params, body in api.writes():
        assert "conferenceData" not in body
        assert "conferenceDataVersion" not in params
    conf = ConferenceConfig(provision_for="any_linkless", replace=["zoom"])
    for mirror in mirrors(api).values():
        assert plan_conference(mirror, conf).action == "skip"
    assert mirrors(api)[f"{WORK}:linkless"]["location"] == ""


# -- Dedupe with Gmail (#10) ----------------------------------------------------------


ZOOM_START = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)


def _zoom_candidate() -> MeetingCandidate:
    return MeetingCandidate(
        title="1:1 Bob / Me",
        start=ZOOM_START,
        end=ZOOM_START + timedelta(minutes=30),
        join_url="https://zoom.us/j/1234567890",
        meeting_id="1234567890",
        attendees=["bob@work.example"],
        confidence=0.95,
    )


def _zoom_event() -> dict[str, Any]:
    return event(
        "z1",
        ZOOM_START,
        summary="1:1 Bob / Me",
        conferenceData={
            "entryPoints": [{"entryPointType": "video", "uri": "https://zoom.us/j/1234567890"}]
        },
    )


def test_same_zoom_meeting_from_gmail_then_mirror_is_one_event(api, conn):
    sink = GoogleCalendarSink(token_provider="t", http_client=api)
    gmail_event = sink.create(_zoom_candidate())
    api.sources[WORK] = ScriptedCalendar([_zoom_event()])

    ops = make_source(api, [WORK]).sync(conn)

    assert len(api.target) == 1
    converted = api.target[gmail_event.id]
    private = converted["extendedProperties"]["private"]
    assert private[MIRROR_OF] == f"{WORK}:z1"
    assert private["cuecalMeetingId"] == "1234567890"
    assert converted["attendees"] == [{"email": ME, "responseStatus": "accepted"}]
    assert [(op.action, op.event_id) for op in ops] == [("convert", gmail_event.id)]


def test_same_zoom_meeting_from_mirror_then_gmail_is_one_event(api, conn):
    api.sources[WORK] = ScriptedCalendar([_zoom_event()])
    make_source(api, [WORK]).sync(conn)
    mirror = mirrors(api)[f"{WORK}:z1"]
    api.calls.clear()

    sink = GoogleCalendarSink(token_provider="t", http_client=api)
    result = sink.create(_zoom_candidate())

    assert result.id == mirror["id"]
    assert len(api.target) == 1
    assert api.writes() == []


def test_mirror_of_another_instance_does_not_swallow_gmail_invite(api, conn):
    # A recurring Zoom series shares one meeting ID; only a mirror at the same time wins.
    api.sources[WORK] = ScriptedCalendar([_zoom_event()])
    make_source(api, [WORK]).sync(conn)
    mirror = mirrors(api)[f"{WORK}:z1"]
    next_week = _zoom_candidate()
    next_week.start = ZOOM_START + timedelta(days=7)
    next_week.end = next_week.start + timedelta(minutes=30)

    created = GoogleCalendarSink(token_provider="t", http_client=api).create(next_week)

    assert created.id != mirror["id"]
    assert api.target[mirror["id"]] == mirror
    assert len(api.target) == 2


def test_foreign_events_are_never_modified_or_deleted(api, conn):
    foreign = api.seed(
        {
            **event("foreign", ZOOM_START, summary="1:1 Bob / Me"),
            "location": "https://zoom.us/j/1234567890",
            "attendees": [{"email": "bob@work.example"}],
        }
    )
    snapshot = copy.deepcopy(foreign)
    work = ScriptedCalendar([_zoom_event()])
    api.sources[WORK] = work
    source = make_source(api, [WORK])
    source.sync(conn)
    work.changes = [{"id": "z1", "status": "cancelled"}]
    source.sync(conn)
    CalendarSource(MirrorConfig(), token_provider="t", http_client=api, now=Clock()).prune()

    assert api.target["foreign"] == snapshot
    assert not [w for w in api.writes() if w[1].endswith("/foreign")]


# -- Calendar selection ----------------------------------------------------------------


def test_free_busy_only_calendar_is_skipped_with_warning(api, conn, caplog):
    api.sources[WORK] = ScriptedCalendar([event("w1", NOW + timedelta(days=1))])
    source = make_source(api, [WORK, BUSY])

    assert "free/busy" in source.source_warnings()[BUSY]
    with caplog.at_level("WARNING", logger="cuecal.sources.calendar"):
        source.sync(conn)
    assert "free/busy" in caplog.text
    assert not [c for c in api.calls if "busy%40" in c[1] or BUSY in c[1]]
    assert db.get_cursor(conn, token_cursor_key(BUSY)) is None
    assert set(mirrors(api)) == {f"{WORK}:w1"}


def test_target_account_calendar_is_never_used_as_a_source(api, conn):
    source = make_source(api, [ME])
    assert source.source_warnings() == {ME: "is the target calendar"}
    assert source.sync(conn) == []


# -- Dry run and prune -----------------------------------------------------------------


def test_dry_run_plans_operations_and_writes_nothing(api, conn):
    work = ScriptedCalendar([event("w1", NOW + timedelta(days=1))])
    api.sources[WORK] = work
    source = make_source(api, [WORK])
    source.sync(conn)
    work.events.append(event("w2", NOW + timedelta(days=2)))
    work.changes = [
        event("w1", NOW + timedelta(days=3), updated="2026-10-08T15:00Z"),
        event("w2", NOW + timedelta(days=2)),
    ]
    snapshot = copy.deepcopy(api.target)
    cursor = db.get_cursor(conn, token_cursor_key(WORK))
    api.calls.clear()

    ops = source.sync(conn, dry_run=True)

    assert sorted(op.action for op in ops) == ["create", "update"]
    assert api.writes() == []
    assert api.target == snapshot
    assert db.get_cursor(conn, token_cursor_key(WORK)) == cursor


def test_prune_dry_run_lists_mirrors_of_removed_calendars(api, conn):
    api.sources[WORK] = ScriptedCalendar([event("w1", NOW + timedelta(days=1))])
    api.sources[TEAM] = ScriptedCalendar([event("t1", NOW + timedelta(days=1))])
    make_source(api, [WORK, TEAM]).sync(conn)
    api.calls.clear()

    remaining = make_source(api, [WORK])
    planned = remaining.prune(dry_run=True)
    assert [op.key for op in planned] == [f"{TEAM}:t1"]
    assert api.writes() == []
    assert len(mirrors(api)) == 2

    done = remaining.prune()
    assert [op.key for op in done] == [f"{TEAM}:t1"]
    assert set(mirrors(api)) == {f"{WORK}:w1"}
    assert all(w[2]["sendUpdates"] == "none" for w in api.writes())


# -- CLI -------------------------------------------------------------------------------


@pytest.fixture
def cli_env(tmp_path, monkeypatch, api):
    monkeypatch.setenv("CUECAL_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("CUECAL_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("CUECAL_LOCK_PATH", str(tmp_path / "cuecal.lock"))
    monkeypatch.setenv("CUECAL_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(registry, "_registry", {kind: {} for kind in registry.KINDS})
    monkeypatch.setattr(
        cli,
        "_calendar_source",
        lambda cfg: CalendarSource(cfg.mirror, token_provider="t", http_client=api, now=Clock()),
    )
    (tmp_path / "config.toml").write_text(
        f'sources = ["calendar"]\n[mirror]\nsource_calendars = ["{WORK}", "{BUSY}"]\n',
        encoding="utf-8",
    )
    return tmp_path


def test_cli_run_dry_run_prints_planned_mirror_ops(cli_env, api, capsys):
    api.sources[WORK] = ScriptedCalendar([event("w1", NOW + timedelta(days=1), summary="Sync")])
    assert cli.main(["run", "--once", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert f"dry-run: would create mirror {WORK}:w1: 'Sync'" in out
    assert api.writes() == []


def test_cli_run_once_creates_mirrors(cli_env, api):
    api.sources[WORK] = ScriptedCalendar([event("w1", NOW + timedelta(days=1))])
    assert cli.main(["run", "--once"]) == 0
    assert set(mirrors(api)) == {f"{WORK}:w1"}


def test_cli_mirror_calendars_picker_warns_on_free_busy(cli_env, capsys):
    assert cli.main(["mirror", "calendars"]) == 0
    out = capsys.readouterr().out
    assert f"{ME}  {ME}  [primary, target]" in out
    assert f"{WORK}  Work (other account)  [source]" in out
    assert f"{TEAM}  Team calendar" in out
    assert f"{BUSY}  Partner availability  [source, free/busy only: cannot be mirrored]" in out
    assert f"warning: source calendar '{BUSY}' shares free/busy only" in out


def test_cli_mirror_prune_dry_run_writes_nothing(cli_env, api, capsys):
    api.seed(
        {
            **event("m1", NOW + timedelta(days=1), summary="Old team sync"),
            "extendedProperties": {
                "private": {"cuecalMirror": "true", MIRROR_OF: f"{TEAM}:t1"}
            },
        }
    )
    assert cli.main(["mirror", "prune", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert f"dry-run: would delete mirror {TEAM}:t1: 'Old team sync'" in out
    assert api.writes() == []
    assert "m1" in api.target
