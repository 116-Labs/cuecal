"""Tests for Google Meet provisioning and provider replacement."""

from __future__ import annotations

from typing import Any

import pytest

from cuecal.conference import normalize_meet_code, plan_conference
from cuecal.config import ConferenceConfig, ConfigError, parse_config
from cuecal.sinks import GoogleCalendarSink

EVENT_PATH = "/calendars/primary/events/ev1"


def _zoho_event(*, organizer: bool, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "id": "ev1",
        "organizer": {"self": organizer},
        "conferenceData": {
            "entryPoints": [{"entryPointType": "video", "uri": "https://meeting.zoho.com/j/1"}]
        },
    }
    event.update(extra or {})
    return event


def _linkless_event(*, organizer: bool) -> dict[str, Any]:
    return {"id": "ev1", "organizer": {"self": organizer}}


class RecordingClient:
    def __init__(self, event: dict[str, Any]) -> None:
        self.event = event
        self.calls: list[tuple[str, str, Any, Any]] = []

    def request(self, method, path, params=None, json=None):
        self.calls.append((method, path, params, json))
        if method == "GET":
            return self.event
        if json and "conferenceData" in json:
            return {
                "id": "ev1",
                "hangoutLink": "https://meet.google.com/abc-defg-hij",
            }
        return {"id": "ev1"}

    @property
    def mutations(self) -> list[tuple[str, str, Any, Any]]:
        return [c for c in self.calls if c[0] != "GET"]


def _conf(mode: str, replace: list[str] | None = None) -> ConferenceConfig:
    return ConferenceConfig(
        preferred="google_meet", replace=replace or ["zoho_meeting"], provision_for=mode
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://meet.google.com/abc-defg-hij", "abc-defg-hij"),
        ("https://meet.google.com/ABC-DEFG-HIJ?authuser=0", "abc-defg-hij"),
        ("meet.google.com/abc-defg-hij", "abc-defg-hij"),
        ("abcdefghij", "abc-defg-hij"),
        ("abc-defg-hij", "abc-defg-hij"),
        ("https://zoom.us/j/123", None),
        ("nonsense", None),
        (None, None),
    ],
)
def test_normalize_meet_code(value, expected):
    assert normalize_meet_code(value) == expected


@pytest.mark.parametrize(
    ("mode", "event", "action"),
    [
        ("organizer_only", _linkless_event(organizer=True), "provision"),
        ("organizer_only", _linkless_event(organizer=False), "skip"),
        ("any_linkless", _linkless_event(organizer=True), "provision"),
        ("any_linkless", _linkless_event(organizer=False), "provision"),
        ("off", _linkless_event(organizer=True), "skip"),
        ("off", _linkless_event(organizer=False), "skip"),
    ],
)
def test_provision_for_modes(mode, event, action):
    assert plan_conference(event, _conf(mode)).action == action


@pytest.mark.parametrize("mode", ["organizer_only", "any_linkless"])
def test_replacement_strictly_organizer_only(mode):
    assert plan_conference(_zoho_event(organizer=True), _conf(mode)).action == "replace"
    plan = plan_conference(_zoho_event(organizer=False), _conf(mode))
    assert plan.action == "skip"


def test_replacement_off_and_unlisted_provider():
    assert plan_conference(_zoho_event(organizer=True), _conf("off")).action == "skip"
    zoom = _zoho_event(organizer=True)
    zoom["conferenceData"]["entryPoints"][0]["uri"] = "https://zoom.us/j/1"
    assert plan_conference(zoom, _conf("organizer_only")).action == "skip"
    assert (
        plan_conference(zoom, _conf("organizer_only", ["zoom"])).action == "replace"
    )


def test_existing_meet_and_mirrored_untouched():
    meet = {"id": "ev1", "hangoutLink": "https://meet.google.com/abc-defg-hij"}
    assert plan_conference(meet, _conf("any_linkless")).action == "skip"
    mirrored = _zoho_event(
        organizer=True, extra={"extendedProperties": {"private": {"cuecalMirror": "src"}}}
    )
    assert plan_conference(mirrored, _conf("organizer_only")).action == "skip"
    mirrored_linkless = _linkless_event(organizer=True)
    mirrored_linkless["extendedProperties"] = {"private": {"cuecalMirror": "src"}}
    assert plan_conference(mirrored_linkless, _conf("any_linkless")).action == "skip"


def test_sink_provisions_and_stores_meeting_id():
    client = RecordingClient(_linkless_event(organizer=True))
    sink = GoogleCalendarSink(token_provider="t", http_client=client)
    plan = sink.provision_conference("ev1", _conf("organizer_only"))

    assert plan.action == "provision"
    create, meta = client.mutations
    assert create[0] == "PATCH" and create[1] == EVENT_PATH
    assert create[2] == {"conferenceDataVersion": 1}
    request = create[3]["conferenceData"]["createRequest"]
    assert request["conferenceSolutionKey"] == {"type": "hangoutsMeet"}
    assert request["requestId"]
    assert meta[3]["location"] == "https://meet.google.com/abc-defg-hij"
    assert meta[3]["extendedProperties"]["private"]["cuecalMeetingId"] == "abc-defg-hij"


def test_sink_replaces_zoho_when_organizer():
    client = RecordingClient(_zoho_event(organizer=True))
    sink = GoogleCalendarSink(token_provider="t", http_client=client)
    assert sink.provision_conference("ev1", _conf("organizer_only")).action == "replace"
    assert len(client.mutations) == 2


def _sink(client, **kwargs):
    return GoogleCalendarSink(
        token_provider="t", http_client=client, conference_poll_delay=0, **kwargs
    )


def test_replace_keeps_metadata_off_when_old_provider_remains():
    client = RecordingClient(_zoho_event(organizer=True))
    zoho_entry = {"entryPointType": "video", "uri": "https://meeting.zoho.com/j/1"}

    def merged(method, path, params=None, json=None):
        client.calls.append((method, path, params, json))
        if method == "GET":
            return client.event
        return {
            "id": "ev1",
            "hangoutLink": "https://meet.google.com/abc-defg-hij",
            "conferenceData": {"entryPoints": [zoho_entry]},
        }

    client.request = merged
    assert _sink(client).provision_conference("ev1", _conf("organizer_only")).action == "replace"
    assert len(client.mutations) == 1


def test_sink_polls_until_meet_link_ready():
    client = RecordingClient(_linkless_event(organizer=True))
    gets = {"n": 0}

    def pending(method, path, params=None, json=None):
        client.calls.append((method, path, params, json))
        if method == "GET":
            gets["n"] += 1
            if gets["n"] == 1:
                return client.event
            return {"id": "ev1", "hangoutLink": "https://meet.google.com/abc-defg-hij"}
        if json and "conferenceData" in json:
            return {"id": "ev1", "conferenceData": {"createRequest": {"status": {}}}}
        return {"id": "ev1"}

    client.request = pending
    _sink(client).provision_conference("ev1", _conf("organizer_only"))
    meta = client.mutations[-1]
    assert meta[3]["extendedProperties"]["private"]["cuecalMeetingId"] == "abc-defg-hij"
    assert meta[3]["location"] == "https://meet.google.com/abc-defg-hij"


def test_sink_gives_up_when_link_stays_pending():
    client = RecordingClient(_linkless_event(organizer=True))

    def never_ready(method, path, params=None, json=None):
        client.calls.append((method, path, params, json))
        return client.event if method == "GET" else {"id": "ev1"}

    client.request = never_ready
    _sink(client).provision_conference("ev1", _conf("organizer_only"))
    assert len(client.mutations) == 1
    assert len([c for c in client.calls if c[0] == "GET"]) == 3


def test_physical_location_is_kept():
    event = _linkless_event(organizer=True)
    event["location"] = "Room 4B"
    client = RecordingClient(event)
    _sink(client).provision_conference("ev1", _conf("organizer_only"))
    meta = client.mutations[-1][3]
    assert "location" not in meta
    assert meta["extendedProperties"]["private"]["cuecalMeetingId"] == "abc-defg-hij"


def test_replaced_provider_location_is_overwritten():
    event = _zoho_event(organizer=True, extra={"location": "https://meeting.zoho.com/j/1"})
    client = RecordingClient(event)
    _sink(client).provision_conference("ev1", _conf("organizer_only"))
    assert client.mutations[-1][3]["location"] == "https://meet.google.com/abc-defg-hij"


def test_sink_never_replaces_when_not_organizer():
    client = RecordingClient(_zoho_event(organizer=False))
    sink = GoogleCalendarSink(token_provider="t", http_client=client)
    assert sink.provision_conference("ev1", _conf("any_linkless")).action == "skip"
    assert client.mutations == []


def test_sink_off_makes_no_mutations():
    client = RecordingClient(_linkless_event(organizer=True))
    sink = GoogleCalendarSink(token_provider="t", http_client=client)
    assert sink.provision_conference("ev1", _conf("off")).action == "skip"
    assert client.mutations == []


@pytest.mark.parametrize("event_factory", [_linkless_event, _zoho_event])
def test_dry_run_performs_zero_mutations(event_factory):
    client = RecordingClient(event_factory(organizer=True))
    sink = GoogleCalendarSink(token_provider="t", dry_run=True, http_client=client)
    plan = sink.provision_conference("ev1", _conf("any_linkless"))
    assert plan.action in ("provision", "replace")
    assert client.mutations == []


def test_conference_config_parsing():
    cfg = parse_config(
        {
            "conference": {
                "preferred": "google_meet",
                "replace": ["zoho_meeting"],
                "provision_for": "any_linkless",
            }
        }
    )
    assert cfg.conference.replace == ["zoho_meeting"]
    assert cfg.conference.provision_for == "any_linkless"
    assert parse_config({}).conference.provision_for == "off"
    with pytest.raises(ConfigError):
        parse_config({"conference": {"provision_for": "always"}})
    with pytest.raises(ConfigError):
        parse_config({"conference": {"replace": "zoho_meeting"}})
    with pytest.raises(ConfigError):
        parse_config({"conference": {"bogus": 1}})
