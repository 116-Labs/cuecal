import time
from datetime import UTC, datetime

from cuecal.extract import tier0
from cuecal.models import Message


def msg(text, attachments=()):
    return Message("1", "slack", "a", datetime(2026, 10, 1, tzinfo=UTC), text, None, attachments)


def only(text):
    links = tier0.find_links(text)
    assert len(links) == 1
    return links[0]


def test_zoom_j_with_pwd():
    link = only("Join https://us02web.zoom.us/j/81234567890?pwd=AbC123xyz.")
    assert link.provider == "zoom"
    assert link.meeting_id == "81234567890"
    assert link.join_url == "https://us02web.zoom.us/j/81234567890?pwd=AbC123xyz"
    assert link.passcode == "AbC123xyz"


def test_zoom_text_passcode_wins():
    link = only(
        "https://zoom.us/j/81234567890?pwd=tok\nMeeting ID: 812 3456 7890\nPasscode: 482913"
    )
    assert link.passcode == "482913"
    assert link.join_url.endswith("?pwd=tok")


def test_zoom_vanity():
    link = only("see https://acme.zoom.us/my/Jane.Doe?pwd=x1 ok")
    assert link.meeting_id == "jane.doe"
    assert link.join_url == "https://acme.zoom.us/my/Jane.Doe?pwd=x1"


def test_zoommtg():
    link = only("zoommtg://zoom.us/join?confno=81234567890&pwd=zz9&uname=x")
    assert link.join_url == "https://zoom.us/j/81234567890?pwd=zz9"
    assert link.meeting_id == "81234567890"


def test_google_meet():
    link = only("meet https://meet.google.com/abc-defg-hij?authuser=0")
    assert (link.provider, link.meeting_id) == ("meet", "abc-defg-hij")
    assert link.join_url == "https://meet.google.com/abc-defg-hij"


def test_teams_with_meeting_id_and_passcode():
    text = (
        "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc%40thread.v2/0?context=x\n"
        "Meeting ID: 261 123 456 789\nPasscode: Qw3rTy"
    )
    link = only(text)
    assert link.provider == "teams"
    assert link.meeting_id == "261123456789"
    assert link.passcode == "Qw3rTy"


def test_ids_and_passcodes_bind_to_their_own_link():
    text = (
        "https://zoom.us/j/81234567890\nMeeting ID: 812 3456 7890\nPasscode: zoomPw\n\n"
        "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc%40thread.v2/0?context=x\n"
    )
    zoom, teams = tier0.find_links(text)
    assert (zoom.meeting_id, zoom.passcode) == ("81234567890", "zoomPw")
    assert teams.meeting_id == "19:meeting_abc@thread.v2"
    assert teams.passcode is None


def test_two_teams_links_keep_separate_ids():
    text = (
        "https://teams.microsoft.com/l/meetup-join/19%3ameeting_a%40thread.v2/0\n"
        "https://teams.microsoft.com/l/meetup-join/19%3ameeting_b%40thread.v2/0\n"
        "Meeting ID: 261 123 456 789"
    )
    first, second = tier0.find_links(text)
    assert first.meeting_id == "19:meeting_a@thread.v2"
    assert second.meeting_id == "261123456789"


def test_teams_without_id_uses_thread():
    link = only("https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc%40thread.v2/0")
    assert link.meeting_id == "19:meeting_abc@thread.v2"


def test_webex():
    link = only("https://acme.webex.com/meet/jane.doe and Password: abc123")
    assert (link.provider, link.meeting_id, link.passcode) == ("webex", "jane.doe", "abc123")
    link = only("https://acme.webex.com/acme/j.php?MTID=m1b2c3")
    assert link.meeting_id == "m1b2c3"
    link = only(
        "https://acme.webex.com/acme/j.php?MTID=m1\nMeeting number (access code): 2551 234 567"
    )
    assert link.meeting_id == "2551234567"


def test_gate_drops_without_link_or_calendar():
    assert tier0.gate(msg("lunch tomorrow?")) is None
    assert tier0.gate(msg("see https://example.com/zoom")) is None


def test_gate_passes_link_or_calendar_attachment():
    assert tier0.gate(msg("https://meet.google.com/abc-defg-hij"))[0].provider == "meet"
    assert tier0.gate(msg("invite", ("BEGIN:VCALENDAR\nEND:VCALENDAR",))) == []


def test_dedupes_same_meeting():
    text = "https://zoom.us/j/81234567890 and again https://zoom.us/j/81234567890?pwd=a"
    assert len(tier0.find_links(text)) == 1


def test_throughput():
    corpus = [msg("hey, are we still on for lunch? " * 5)] * 95 + [
        msg("join https://us02web.zoom.us/j/81234567890?pwd=abc"),
        msg("https://meet.google.com/abc-defg-hij"),
        msg("https://teams.microsoft.com/l/meetup-join/19%3ameeting_a%40thread.v2/0"),
        msg("https://acme.webex.com/meet/jane"),
        msg("nothing here"),
    ]
    n = 0
    start = time.perf_counter()
    while n < 20_000:
        for m in corpus:
            tier0.gate(m)
        n += len(corpus)
    rate = n / (time.perf_counter() - start)
    assert rate >= 10_000, f"{rate:.0f} msg/s"
