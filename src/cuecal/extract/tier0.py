"""Tier 0: regex gate. Finds meeting links, IDs and passcodes. Pure regex, no I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit

from cuecal.models import Message

_URL_TAIL = r"[^\s<>\"'\])]*"

_ZOOM_J = re.compile(
    rf"https?://(?:[\w-]+\.)*zoom\.(?:us|com)/(?:j|w)/(\d{{9,11}})(\?{_URL_TAIL})?", re.I
)
_ZOOM_MY = re.compile(rf"https?://(?:[\w-]+\.)*zoom\.(?:us|com)/my/([\w.-]+)(\?{_URL_TAIL})?", re.I)
_ZOOM_MTG = re.compile(r"zoommtg://[\w.-]*zoom\.(?:us|com)/join\?" + _URL_TAIL, re.I)
_MEET = re.compile(r"https?://meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})(?![\w-])", re.I)
_TEAMS = re.compile(
    rf"https?://teams\.microsoft\.com/l/meetup-join/([^/\s<>\"']+){_URL_TAIL}"
    rf"|https?://teams\.live\.com/meet/(\d+){_URL_TAIL}",
    re.I,
)
_WEBEX = re.compile(
    rf"https?://[\w-]+\.webex\.com/(?:meet/([\w.-]+)|(?:[\w./-]*/)?j\.php\?{_URL_TAIL}"
    rf"|join/([\w.-]+))",
    re.I,
)
_ANY = re.compile(
    r"zoommtg://|zoom\.(?:us|com)/|meet\.google\.com/|teams\.microsoft\.com/|teams\.live\.com/"
    r"|\.webex\.com/",
    re.I,
)

_PASSCODE = re.compile(r"(?:passcode|password)\s*:\s*([\w-]{3,32})", re.I)
_TEAMS_ID = re.compile(r"meeting id\s*:\s*(\d[\d ]{6,18}\d)", re.I)
_WEBEX_NUMBER = re.compile(r"meeting number(?: \(access code\))?\s*:\s*(\d[\d ]{6,18}\d)", re.I)
_TRAILING = ".,;:!?"


@dataclass(frozen=True)
class MeetingLink:
    provider: str
    join_url: str
    meeting_id: str
    passcode: str | None = None


def has_calendar_attachment(attachments: tuple[str, ...]) -> bool:
    return any("BEGIN:VCALENDAR" in a for a in attachments)


def _clean(url: str) -> str:
    return url.rstrip(_TRAILING)


def _text_passcode(text: str) -> str | None:
    m = _PASSCODE.search(text)
    return m.group(1) if m else None


def _zoom(id_: str, query: str | None, host_path: str, text: str) -> MeetingLink:
    pwd = (parse_qs(_clean(query or "").lstrip("?")).get("pwd") or [None])[0]
    url = f"https://{host_path}" + (f"?pwd={pwd}" if pwd else "")
    return MeetingLink("zoom", url, id_, _text_passcode(text) or pwd)


_ALL_LINKS = (_ZOOM_J, _ZOOM_MY, _ZOOM_MTG, _MEET, _TEAMS, _WEBEX)


def _window(text: str, start: int, starts: list[int]) -> str:
    """Text from this link up to the next link, so IDs and passcodes bind to their own invite."""
    end = next((s for s in starts if s > start), len(text))
    return text[start:end]


def find_links(text: str) -> list[MeetingLink]:
    """Return every distinct meeting link in `text`, in order of appearance."""
    if not _ANY.search(text):
        return []
    starts = sorted({m.start() for pattern in _ALL_LINKS for m in pattern.finditer(text)})
    found: list[tuple[int, MeetingLink]] = []
    for m in _ZOOM_J.finditer(text):
        host = urlsplit(_clean(m.group(0))).netloc.lower()
        win = _window(text, m.start(), starts)
        found.append((m.start(), _zoom(m.group(1), m.group(2), f"{host}/j/{m.group(1)}", win)))
    for m in _ZOOM_MY.finditer(text):
        host = urlsplit(_clean(m.group(0))).netloc.lower()
        vanity = m.group(1).rstrip(_TRAILING)
        win = _window(text, m.start(), starts)
        found.append((m.start(), _zoom(vanity.lower(), m.group(2), f"{host}/my/{vanity}", win)))
    for m in _ZOOM_MTG.finditer(text):
        q = parse_qs(urlsplit(_clean(m.group(0))).query)
        confno = (q.get("confno") or [""])[0]
        if confno.isdigit():
            pwd = (q.get("pwd") or [None])[0]
            url = f"https://zoom.us/j/{confno}" + (f"?pwd={pwd}" if pwd else "")
            win = _window(text, m.start(), starts)
            found.append((m.start(), MeetingLink("zoom", url, confno, _text_passcode(win) or pwd)))
    for m in _MEET.finditer(text):
        code = m.group(1).lower()
        found.append((m.start(), MeetingLink("meet", f"https://meet.google.com/{code}", code)))
    for m in _TEAMS.finditer(text):
        url = _clean(m.group(0))
        win = _window(text, m.start(), starts)
        tid = _TEAMS_ID.search(win)
        if m.group(2):
            mid = m.group(2)
        elif tid:
            mid = re.sub(r"\s", "", tid.group(1))
        else:
            mid = unquote(m.group(1))
        found.append((m.start(), MeetingLink("teams", url, mid, _text_passcode(win))))
    for m in _WEBEX.finditer(text):
        url = _clean(m.group(0))
        win = _window(text, m.start(), starts)
        num = _WEBEX_NUMBER.search(win)
        mtid = (parse_qs(urlsplit(url).query).get("MTID") or [None])[0]
        if num:
            mid = re.sub(r"\s", "", num.group(1))
        else:
            mid = mtid or m.group(1) or m.group(2) or url
        found.append((m.start(), MeetingLink("webex", url, mid, _text_passcode(win))))
    seen: set[tuple[str, str]] = set()
    out: list[MeetingLink] = []
    for _, link in sorted(found, key=lambda t: t[0]):
        key = (link.provider, link.meeting_id)
        if key not in seen:
            seen.add(key)
            out.append(link)
    return out


def gate(message: Message) -> list[MeetingLink] | None:
    """Return links to carry forward, or None to drop the message.

    A message with a calendar attachment passes even when it has no link.
    """
    links = find_links(message.text)
    if links or has_calendar_attachment(message.attachments):
        return links
    return None
