"""Conference provider detection and provisioning decisions (pure logic, no I/O)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from cuecal.config import ConferenceConfig
from cuecal.extract.tier0 import find_links

MEET_HOST = "meet.google.com"
MIRROR_PROPERTY = "cuecalMirror"

_MEET_CODE_RE = re.compile(r"^([a-z]{3})-?([a-z]{4})-?([a-z]{3})$")

_PROVIDER_HOSTS = (
    ("google_meet", ("meet.google.com",)),
    ("zoho_meeting", ("meeting.zoho.com", "meeting.zoho.eu", "meeting.zoho.in", "zohomeet.com")),
    ("zoom", ("zoom.us",)),
)


@dataclass(frozen=True)
class ConferencePlan:
    action: str  # "skip" | "provision" | "replace"
    reason: str = ""


def normalize_meet_code(value: str | None) -> str | None:
    """Return the canonical ``abc-defg-hij`` Meet code from a URL or bare code, else None."""
    if not value:
        return None
    text = value.strip().lower()
    if "://" in text or text.startswith(MEET_HOST):
        parsed = urlparse(text if "://" in text else f"https://{text}")
        if parsed.hostname != MEET_HOST:
            return None
        text = parsed.path.strip("/").split("/")[0]
    match = _MEET_CODE_RE.match(text)
    if not match:
        return None
    return "-".join(match.groups())


def meet_join_url(code: str) -> str:
    return f"https://{MEET_HOST}/{code}"


def _provider_for_uri(uri: str) -> str:
    host = (urlparse(uri).hostname or "").lower()
    for provider, hosts in _PROVIDER_HOSTS:
        if any(host == h or host.endswith(f".{h}") for h in hosts):
            return provider
    return "other"


def event_conference_uris(event: dict[str, Any]) -> list[str]:
    uris: list[str] = []
    hangout = event.get("hangoutLink")
    if hangout:
        uris.append(hangout)
    for entry in (event.get("conferenceData") or {}).get("entryPoints", []) or []:
        uri = entry.get("uri")
        if uri and uri not in uris:
            uris.append(uri)
    return uris


def event_meeting_ids(event: dict[str, Any]) -> tuple[str, ...]:
    """Every Zoom/Meet/Teams meeting ID in the event's conference data, location and description."""
    parts = [*event_conference_uris(event), event.get("location") or ""]
    parts.append(event.get("description") or "")
    return tuple(link.meeting_id for link in find_links("\n".join(parts)))


def event_providers(event: dict[str, Any]) -> set[str]:
    return {_provider_for_uri(u) for u in event_conference_uris(event)}


def is_organizer(event: dict[str, Any]) -> bool:
    return (event.get("organizer") or {}).get("self") is True


def is_mirrored(event: dict[str, Any]) -> bool:
    private = (event.get("extendedProperties") or {}).get("private") or {}
    return bool(private.get(MIRROR_PROPERTY))


def plan_conference(event: dict[str, Any], conf: ConferenceConfig) -> ConferencePlan:
    """Decide whether to provision a Meet link, replace a provider link, or leave alone."""
    if is_mirrored(event):
        return ConferencePlan("skip", "mirrored event")
    if conf.provision_for == "off":
        return ConferencePlan("skip", "provisioning off")
    if conf.preferred != "google_meet":
        return ConferencePlan("skip", f"unsupported preferred provider {conf.preferred!r}")

    providers = event_providers(event)
    if not providers:
        if conf.provision_for == "organizer_only" and not is_organizer(event):
            return ConferencePlan("skip", "not organizer")
        return ConferencePlan("provision")
    if "google_meet" in providers:
        return ConferencePlan("skip", "already has Meet link")
    if providers & set(conf.replace):
        if not is_organizer(event):
            return ConferencePlan("skip", "replacement requires organizer")
        return ConferencePlan("replace")
    return ConferencePlan("skip", "has non-replaceable conference link")
