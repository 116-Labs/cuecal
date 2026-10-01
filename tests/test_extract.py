from datetime import UTC, datetime

from cuecal import extract
from cuecal.extract import tier1
from cuecal.models import Message


def msg(text, attachments=()):
    return Message("m1", "gmail", "a", datetime(2026, 10, 1, tzinfo=UTC), text, None, attachments)


def test_dropped_without_link_or_calendar():
    assert extract.extract(msg("see you at 2")) is None


def test_link_only_gives_partial_candidate():
    c = extract.extract(msg("call: https://meet.google.com/abc-defg-hij"))
    assert c.start is None
    assert c.meeting_id == "abc-defg-hij"
    assert c.confidence < tier1.HIGH


def test_zoom_invite_is_high():
    text = "Topic: Sync\nTime: Oct 3, 2026 02:00 PM Pacific Time (US and Canada)\nhttps://zoom.us/j/81234567890"
    c = extract.extract(msg(text))
    assert c.confidence == tier1.HIGH
    assert c.meeting_id == "81234567890"


def test_ics_attachment_without_link():
    body = (
        "BEGIN:VCALENDAR\r\nMETHOD:REQUEST\r\nBEGIN:VEVENT\r\nUID:1\r\n"
        "DTSTART:20261003T210000Z\r\nSUMMARY:X\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    c = extract.extract(msg("see attached", (body,)))
    assert c.tier == "ics"
    assert c.meeting_id is None
    assert c.confidence == tier1.HIGH
