"""Tier 1: deterministic structured parse of .ics attachments and known invite templates."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from dateutil import parser as dateparser
from icalendar import Calendar

from cuecal.extract import tier0
from cuecal.models import MeetingCandidate, Message

HIGH = 0.95
LOW = 0.4

# Common display names used by Zoom, Google Calendar and Zoho. Abbreviations that are
# ambiguous across regions (CST, IST, BST...) are deliberately absent.
_TZ_NAMES = {
    "pacific time": "America/Los_Angeles",
    "pacific standard time": "America/Los_Angeles",
    "pacific daylight time": "America/Los_Angeles",
    "mountain time": "America/Denver",
    "mountain standard time": "America/Denver",
    "mountain daylight time": "America/Denver",
    "central time": "America/Chicago",
    "central standard time": "America/Chicago",
    "central daylight time": "America/Chicago",
    "eastern time": "America/New_York",
    "eastern standard time": "America/New_York",
    "eastern daylight time": "America/New_York",
    "alaska time": "America/Anchorage",
    "hawaii time": "Pacific/Honolulu",
    "greenwich mean time": "UTC",
    "coordinated universal time": "UTC",
    "utc": "UTC",
    "gmt": "UTC",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "mst": "America/Denver",
    "mdt": "America/Denver",
    "est": "America/New_York",
    "edt": "America/New_York",
}

_PAREN = re.compile(r"\s*\([^)]*\)")
_DATE = re.compile(
    r"(?:[A-Za-z]{3,9}\.?,?\s+)?"
    r"((?:[A-Za-z]{3,9}\.?\s+\d{1,2}|\d{1,2}\s+[A-Za-z]{3,9}\.?),?\s+\d{4})"
)
_TIME = r"\d{1,2}(?::\d{2})?\s*[AaPp]\.?[Mm]\.?"
_WHEN = re.compile(
    r"^[ \t]*(?:Time|When|Date\s*(?:&|and)\s*Time|Start(?:s)?)[ \t]*:?[ \t]*"
    rf"(?P<date>.+?)[ \t,⋅·@]+(?:at[ \t]+)?(?P<start>{_TIME})"
    rf"(?:[ \t]*(?:[-–—]|to)[ \t]*(?P<end>{_TIME}))?"
    r"(?P<tz>[^\n]*)$",
    re.I | re.M,
)
_TITLE = re.compile(
    r"^[ \t]*(?:Topic|Title|Event|Service|Subject)[ \t]*:[ \t]*(.+?)[ \t]*$", re.I | re.M
)

_zone_index: dict[str, str] | None = None


def resolve_tz(label: str) -> str | None:
    """Map a tz label to an IANA key, or None if unknown or ambiguous."""
    global _zone_index
    outer = label.strip()
    if not outer:
        return None
    candidates = [outer]
    if outer.startswith("(") and outer.endswith(")"):
        candidates.append(outer[1:-1].strip())
    candidates.append(_PAREN.sub("", outer).strip())
    for text in candidates:
        if not text:
            continue
        if text.lower() in _TZ_NAMES:
            return _TZ_NAMES[text.lower()]
        try:
            ZoneInfo(text)
            return text
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass
        # Google style: "Pacific Daylight Time - Los Angeles"
        if " - " in text:
            base, city = (p.strip() for p in text.rsplit(" - ", 1))
            if _zone_index is None:
                _zone_index = {}
                for z in sorted(available_timezones()):
                    _zone_index.setdefault(z.rsplit("/", 1)[-1].lower().replace("_", " "), z)
            found = _zone_index.get(city.lower()) or _TZ_NAMES.get(base.lower())
            if found:
                return found
    return None


def is_unambiguous(local: datetime) -> bool:
    """True when a wall-clock time exists exactly once in its zone (no DST gap or fold)."""
    tz = local.tzinfo
    if tz is None:
        return False
    a = local.replace(fold=0)
    b = local.replace(fold=1)
    if a.utcoffset() != b.utcoffset():
        return False  # repeated hour
    roundtrip = a.astimezone(ZoneInfo("UTC")).astimezone(tz)
    return roundtrip.replace(tzinfo=None) == a.replace(tzinfo=None)  # skipped hour


def _tz_key(dt: datetime) -> str | None:
    tz = dt.tzinfo
    if tz is None:
        return None
    key = getattr(tz, "key", None)
    if key:
        return key
    if dt.utcoffset() == timedelta(0):
        return "UTC"
    return dt.tzname()


def _apply_links(cand: MeetingCandidate, *texts: str) -> None:
    for text in texts:
        links = tier0.find_links(text or "")
        if links:
            link = links[0]
            cand.join_url, cand.meeting_id, cand.passcode = (
                link.join_url,
                link.meeting_id,
                link.passcode,
            )
            return


def parse_ics(text: str, source_ref: str | None = None) -> MeetingCandidate | None:
    """Parse the first VEVENT of an iCalendar body; None if there is none or it has no start."""
    try:
        cal = Calendar.from_ical(text)
    except ValueError:
        return None
    method = str(cal.get("METHOD")).upper() if cal.get("METHOD") else None
    for ev in cal.walk("VEVENT"):
        if "DTSTART" not in ev:
            continue
        start = ev.decoded("DTSTART")
        end = ev.decoded("DTEND") if "DTEND" in ev else None
        confident = isinstance(start, datetime) and is_unambiguous_aware(start)
        if not isinstance(start, datetime):
            start = datetime.combine(start, datetime.min.time())
        if isinstance(end, date) and not isinstance(end, datetime):
            end = datetime.combine(end, datetime.min.time())
        cand = MeetingCandidate(
            title=str(ev.get("SUMMARY", "")).strip() or "Meeting",
            start=start,
            end=end,
            tz=_tz_key(start),
            attendees=[
                str(a).removeprefix("mailto:").removeprefix("MAILTO:")
                for a in _as_list(ev.get("ATTENDEE"))
            ],
            source_ref=source_ref,
            confidence=HIGH if confident else LOW,
            tier="ics",
            method=method,
        )
        _apply_links(
            cand,
            str(ev.get("LOCATION", "")),
            str(ev.get("DESCRIPTION", "")),
            str(ev.get("URL", "")),
        )
        return cand
    return None


def _as_list(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def is_unambiguous_aware(dt: datetime) -> bool:
    return dt.tzinfo is not None and is_unambiguous(dt)


def parse_template(text: str, source_ref: str | None = None) -> MeetingCandidate | None:
    """Parse Zoom invite text, Google Calendar invite emails and Zoho confirmations."""
    m = _WHEN.search(text)
    if not m:
        return None
    dm = _DATE.search(m.group("date"))
    if not dm:
        return None
    try:
        naive = dateparser.parse(f"{dm.group(1)} {m.group('start')}", fuzzy=False)
        end_naive = (
            dateparser.parse(f"{dm.group(1)} {m.group('end')}") if m.group("end") else None
        )
    except (ValueError, OverflowError):
        return None
    tz_key = resolve_tz(m.group("tz"))
    start, end = naive, end_naive
    if tz_key:
        zone = ZoneInfo(tz_key)
        start = naive.replace(tzinfo=zone)
        end = end_naive.replace(tzinfo=zone) if end_naive else None
    if end and start and end <= start:
        end = None
    title = _TITLE.search(text)
    cand = MeetingCandidate(
        title=title.group(1) if title else "Meeting",
        start=start,
        end=end,
        tz=tz_key,
        source_ref=source_ref,
        confidence=HIGH if tz_key and is_unambiguous(start) else LOW,
        tier="template",
    )
    _apply_links(cand, text)
    return cand


def extract(message: Message) -> MeetingCandidate | None:
    """Tier 1 over one message that already passed the Tier 0 gate."""
    for attachment in message.attachments:
        if "BEGIN:VCALENDAR" in attachment:
            cand = parse_ics(attachment, message.permalink or message.id)
            if cand:
                return cand
    return parse_template(message.text, message.permalink or message.id)
