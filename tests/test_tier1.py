from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from cuecal.extract import tier1

LA = ZoneInfo("America/Los_Angeles")


def ics(dtstart, method="REQUEST", extra=""):
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\n"
        f"METHOD:{method}\r\nBEGIN:VEVENT\r\nUID:1\r\nDTSTAMP:20260901T000000Z\r\n"
        f"{dtstart}\r\nDTEND{dtstart[7:].replace('140000', '150000')}\r\n"
        "SUMMARY:Design sync\r\nLOCATION:https://zoom.us/j/81234567890?pwd=abc\r\n"
        f"ATTENDEE:mailto:bob@example.com\r\n{extra}END:VEVENT\r\nEND:VCALENDAR\r\n"
    )


def test_ics_utc_high_confidence_and_method():
    c = tier1.parse_ics(ics("DTSTART:20261003T210000Z", "CANCEL"))
    assert c.method == "CANCEL"
    assert c.start == datetime(2026, 10, 3, 21, tzinfo=UTC)
    assert c.confidence == tier1.HIGH
    assert c.tz == "UTC"
    assert c.title == "Design sync"
    assert c.meeting_id == "81234567890"
    assert c.attendees == ["bob@example.com"]
    assert tier1.parse_ics(ics("DTSTART:20261003T210000Z")).method == "REQUEST"


def test_ics_tzid():
    c = tier1.parse_ics(ics("DTSTART;TZID=America/Los_Angeles:20261003T140000"))
    assert c.start == datetime(2026, 10, 3, 14, tzinfo=LA)
    assert c.tz == "America/Los_Angeles"
    assert c.confidence == tier1.HIGH
    assert c.end == datetime(2026, 10, 3, 15, tzinfo=LA)


def test_ics_floating_is_low():
    c = tier1.parse_ics(ics("DTSTART:20261003T140000"))
    assert c.confidence == tier1.LOW
    assert c.tz is None
    assert c.meeting_id == "81234567890"


def test_ics_dst_gap_is_low():
    c = tier1.parse_ics(ics("DTSTART;TZID=America/Los_Angeles:20260308T023000"))
    assert c.confidence == tier1.LOW


def test_ics_garbage():
    assert tier1.parse_ics("not a calendar") is None


ZOOM = """Jane is inviting you to a scheduled Zoom meeting.

Topic: Roadmap review
Time: Oct 3, 2026 02:00 PM Pacific Time (US and Canada)

Join Zoom Meeting
https://us02web.zoom.us/j/81234567890?pwd=AbC
Meeting ID: 812 3456 7890
Passcode: 482913
"""


def test_zoom_template_us_and_canada():
    c = tier1.parse_template(ZOOM)
    assert c.title == "Roadmap review"
    assert c.start == datetime(2026, 10, 3, 14, tzinfo=LA)
    assert c.start.utcoffset() == timedelta(hours=-7)
    assert c.tz == "America/Los_Angeles"
    assert c.confidence == tier1.HIGH
    assert (c.meeting_id, c.passcode) == ("81234567890", "482913")


def test_zoom_template_winter_offset():
    c = tier1.parse_template(ZOOM.replace("Oct 3", "Nov 5"))
    assert c.start.utcoffset() == timedelta(hours=-8)
    assert c.confidence == tier1.HIGH


def test_template_dst_boundaries_low_confidence():
    gap = tier1.parse_template(ZOOM.replace("Oct 3, 2026 02:00 PM", "Mar 8, 2026 02:30 AM"))
    assert gap.confidence == tier1.LOW
    fold = tier1.parse_template(ZOOM.replace("Oct 3, 2026 02:00 PM", "Nov 1, 2026 01:30 AM"))
    assert fold.confidence == tier1.LOW
    after = tier1.parse_template(ZOOM.replace("Oct 3, 2026 02:00 PM", "Mar 8, 2026 03:30 AM"))
    assert after.confidence == tier1.HIGH


def test_zoom_template_unknown_tz_is_partial():
    c = tier1.parse_template(ZOOM.replace("Pacific Time (US and Canada)", "CST"))
    assert c.tz is None
    assert c.confidence == tier1.LOW
    assert c.meeting_id == "81234567890"


GOOGLE = """Invitation from Google Calendar

Roadmap review
When: Saturday Oct 3, 2026 2:00pm – 3:00pm (Pacific Daylight Time - Los Angeles)
Joining info: https://meet.google.com/abc-defg-hij
"""


def test_google_calendar_template():
    c = tier1.parse_template(GOOGLE)
    assert c.start == datetime(2026, 10, 3, 14, tzinfo=LA)
    assert c.end == datetime(2026, 10, 3, 15, tzinfo=LA)
    assert c.tz == "America/Los_Angeles"
    assert c.confidence == tier1.HIGH
    assert c.meeting_id == "abc-defg-hij"


ZOHO = """Your booking is confirmed.
Service: Intro call
Date & Time: 03 Oct 2026, 02:00 PM - 02:30 PM (America/Los_Angeles)
Join: https://acme.webex.com/meet/jane
"""


def test_zoho_template():
    c = tier1.parse_template(ZOHO)
    assert c.title == "Intro call"
    assert c.start == datetime(2026, 10, 3, 14, tzinfo=LA)
    assert c.end == datetime(2026, 10, 3, 14, 30, tzinfo=LA)
    assert c.confidence == tier1.HIGH
    assert c.meeting_id == "jane"


def test_template_without_time_returns_none():
    assert tier1.parse_template("join https://zoom.us/j/81234567890") is None


def test_resolve_tz():
    assert tier1.resolve_tz("Eastern Time (US and Canada)") == "America/New_York"
    assert tier1.resolve_tz("Europe/London") == "Europe/London"
    assert tier1.resolve_tz("IST") is None
