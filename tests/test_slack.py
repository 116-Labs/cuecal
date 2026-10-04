import json
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.response import addinfourl

import pytest

from cuecal import cli, registry, secrets
from cuecal.extract import tier0
from cuecal.sources.slack import (
    SlackClient,
    SlackQueryBuilder,
    SlackRateLimitError,
    SlackSource,
    unwrap_slack_message,
    unwrap_slack_mrkdwn,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "slack"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def clean_registry_and_keyring(monkeypatch):
    keyring_store: dict[str, str] = {}
    monkeypatch.setattr(secrets, "get_secret", lambda ref: keyring_store.get(ref))
    monkeypatch.setattr(secrets, "set_secret", lambda ref, val: keyring_store.update({ref: val}))
    monkeypatch.setattr(registry, "_registry", {kind: {} for kind in registry.KINDS})


# --- AC 1: Fixture-based contract tests for link unwrapping and cursor advancement ---


def test_link_unwrapping_contract():
    data = load_fixture("search_messages.json")
    matches = data["messages"]["matches"]

    # Match 0: Zoom link with mrkdwn label and credentials
    text0, atts0 = unwrap_slack_message(matches[0])
    assert "https://zoom.us/j/98765432101?pwd=secret123 Join Zoom Meeting" in text0
    assert "@bob" in text0
    links0 = tier0.find_links(text0)
    assert len(links0) == 1
    assert links0[0].provider == "zoom"
    assert links0[0].meeting_id == "98765432101"
    assert links0[0].passcode == "secret123"

    # Match 1: Google Meet link
    text1, atts1 = unwrap_slack_message(matches[1])
    assert "https://meet.google.com/abc-defg-hij" in text1
    links1 = tier0.find_links(text1)
    assert len(links1) == 1
    assert links1[0].provider == "meet"
    assert links1[0].meeting_id == "abc-defg-hij"

    # Match 2: Teams unfurl attachment
    text2, atts2 = unwrap_slack_message(matches[2])
    assert "Microsoft Teams Meeting" in text2
    assert "https://teams.microsoft.com/l/meetup-join/" in text2
    links2 = tier0.find_links(text2)
    assert len(links2) == 1
    assert links2[0].provider == "teams"
    assert links2[0].meeting_id == "234567890123"
    assert links2[0].passcode == "allhands"


def test_mrkdwn_unwrapping_variations():
    assert (
        unwrap_slack_mrkdwn("<https://zoom.us/j/123|Join Zoom>")
        == "https://zoom.us/j/123 Join Zoom"
    )
    assert (
        unwrap_slack_mrkdwn("<https://meet.google.com/abc-defg-hij>")
        == "https://meet.google.com/abc-defg-hij"
    )
    assert (
        unwrap_slack_mrkdwn("<mailto:alice@example.com|alice@example.com>") == "alice@example.com"
    )
    assert (
        unwrap_slack_mrkdwn("Ping <@U12345|alice> in <#C12345|general>")
        == "Ping @alice in #general"
    )
    assert unwrap_slack_mrkdwn("Call <!here> and <!subteam^S123|devs>") == "Call @here and @devs"


def test_cursor_advancement_contract(monkeypatch):
    search_data = load_fixture("search_messages.json")
    users_data = load_fixture("users_info.json")

    client = SlackClient(token="xoxp-fake")

    def mock_request(endpoint: str, params: dict | None = None):
        if endpoint == "search.messages":
            return search_data
        if endpoint == "users.info":
            return users_data
        return {"ok": True}

    monkeypatch.setattr(client, "_request", mock_request)
    source = SlackSource(token="xoxp-fake", client=client)

    # 1. Initial fetch without cursor
    messages, next_cursor = source.fetch_since(cursor=None)
    assert len(messages) == 3
    assert next_cursor == "1700000300.000300"
    # Ensure chronological order
    assert messages[0].ts < messages[1].ts < messages[2].ts
    assert messages[0].sender == "Alice W"
    assert messages[0].source == "slack"

    # 2. Subsequent fetch with cursor at second message
    messages2, next_cursor2 = source.fetch_since(cursor="1700000200.000200")
    assert len(messages2) == 1
    assert messages2[0].id == "C099999:1700000300.000300"
    assert next_cursor2 == "1700000300.000300"

    # 3. Subsequent fetch when all messages are before cursor
    messages3, next_cursor3 = source.fetch_since(cursor="1700000300.000300")
    assert len(messages3) == 0
    assert next_cursor3 == "1700000300.000300"


def test_fallback_conversations_history_contract(monkeypatch):
    conv_data = load_fixture("conversations_history.json")
    user_data = load_fixture("users_info.json")
    permalink_data = load_fixture("chat_permalink.json")

    client = SlackClient(token="xoxp-fake")

    def mock_request(endpoint: str, params: dict | None = None):
        if endpoint == "conversations.history":
            return conv_data
        if endpoint == "users.info":
            return user_data
        if endpoint == "chat.getPermalink":
            return permalink_data
        return {"ok": True}

    monkeypatch.setattr(client, "_request", mock_request)
    source = SlackSource(token="xoxp-fake", channels=["C012345"], client=client)

    messages, next_cursor = source.fetch_since(cursor=None)
    assert len(messages) == 2
    assert next_cursor == "1700000400.000400"
    # Webex message
    assert "https://company.webex.com/meet/alice" in messages[1].text
    links = tier0.find_links(messages[1].text)
    assert len(links) == 1
    assert links[0].provider == "webex"
    assert links[0].meeting_id == "123456789"
    assert links[0].passcode == "webexpass"
    assert messages[1].permalink == "https://workspace.slack.com/archives/C012345/p1700000400000400"


def test_fallback_conversations_history_pagination(monkeypatch):
    client = SlackClient(token="xoxp-fake")
    history_calls: list[dict | None] = []

    def mock_request(endpoint: str, params: dict | None = None):
        if endpoint == "conversations.history":
            history_calls.append(params)
            cursor = (params or {}).get("cursor")
            if not cursor:
                return {
                    "ok": True,
                    "has_more": True,
                    "response_metadata": {"next_cursor": "cursor_page_2"},
                    "messages": [
                        {
                            "type": "message",
                            "user": "U12345",
                            "text": "Meeting link <https://zoom.us/j/111222333>",
                            "ts": "1700000500.000500",
                        }
                    ],
                }
            else:
                return {
                    "ok": True,
                    "has_more": False,
                    "response_metadata": {},
                    "messages": [
                        {
                            "type": "message",
                            "user": "U12345",
                            "text": "Meeting link <https://meet.google.com/xyz-uvwx-rst>",
                            "ts": "1700000600.000600",
                        }
                    ],
                }
        if endpoint == "users.info":
            return {"ok": True, "user": {"name": "alice"}}
        if endpoint == "chat.getPermalink":
            return {"ok": True, "permalink": "https://slack.com/link"}
        return {"ok": True}

    monkeypatch.setattr(client, "_request", mock_request)
    source = SlackSource(token="xoxp-fake", channels=["C012345"], client=client)

    messages, next_cursor = source.fetch_since(cursor=None)
    assert len(messages) == 2
    assert len(history_calls) == 2
    assert history_calls[0].get("cursor") is None
    assert history_calls[1].get("cursor") == "cursor_page_2"
    assert next_cursor == "1700000600.000600"


def test_search_messages_cursor_date_filter_and_desc(monkeypatch):
    client = SlackClient(token="xoxp-fake")
    search_calls: list[dict | None] = []

    def mock_request(endpoint: str, params: dict | None = None):
        if endpoint == "search.messages":
            search_calls.append(params)
            return {"ok": True, "messages": {"matches": [], "paging": {"pages": 1}}}
        return {"ok": True}

    monkeypatch.setattr(client, "_request", mock_request)
    source = SlackSource(token="xoxp-fake", client=client)

    # 1. No cursor
    source.fetch_since(cursor=None)
    assert len(search_calls) == 1
    assert search_calls[0]["sort_dir"] == "desc"
    assert "after:" not in search_calls[0]["query"]

    # 2. With cursor (e.g. ts 1700000200 = 2023-11-14T22:16:40Z -> after:2023-11-13)
    source.fetch_since(cursor="1700000200.000200")
    assert len(search_calls) == 2
    assert search_calls[1]["sort_dir"] == "desc"
    assert "after:2023-11-13" in search_calls[1]["query"]


# --- AC 2: Rate-limit backoff covered by a test ---


def test_rate_limit_backoff_retry_success(monkeypatch):
    sleeps: list[float] = []

    def fake_sleep(duration: float):
        sleeps.append(duration)

    client = SlackClient(token="xoxp-test", sleep_fn=fake_sleep)

    call_count = 0

    def mock_urlopen(req):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            headers = {"Retry-After": "3"}
            raise HTTPError(
                url=req.full_url,
                code=429,
                msg="Too Many Requests",
                hdrs=headers,  # type: ignore[arg-type]
                fp=BytesIO(b'{"ok":false,"error":"ratelimited"}'),
            )
        # Second call succeeds
        resp_bytes = json.dumps({"ok": True, "messages": {"matches": []}}).encode("utf-8")
        return addinfourl(BytesIO(resp_bytes), headers={}, url=req.full_url, code=200)

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    res = client.search_messages(query="zoom.us")
    assert res["ok"] is True
    assert call_count == 2
    assert sleeps == [3.0]


def test_rate_limit_exhaustion_raises(monkeypatch):
    sleeps: list[float] = []

    client = SlackClient(token="xoxp-test", max_retries=2, sleep_fn=lambda d: sleeps.append(d))

    def mock_urlopen(req):
        raise HTTPError(
            url=req.full_url,
            code=429,
            msg="Too Many Requests",
            hdrs={"Retry-After": "1"},  # type: ignore[arg-type]
            fp=BytesIO(b'{"ok":false,"error":"ratelimited"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    with pytest.raises(SlackRateLimitError, match="Slack rate limit exhausted"):
        client.search_messages(query="zoom.us")

    assert len(sleeps) == 2


# --- AC 3: Modular search query implementation ---


def test_modular_search_query():
    # Default query
    qb = SlackQueryBuilder()
    assert (
        qb.build_query()
        == "zoom.us OR meet.google.com OR teams.microsoft.com OR teams.live.com OR webex.com"
    )

    # Custom terms
    qb_custom = SlackQueryBuilder(terms=("zoom.us", "meet.google.com"))
    assert qb_custom.build_query() == "zoom.us OR meet.google.com"

    # Single term with extra filter
    qb_extra = SlackQueryBuilder(terms=("zoom.us",), extra_query="after:2026-10-01")
    assert qb_extra.build_query() == "zoom.us after:2026-10-01"

    # Empty terms (future broadened fetch for #21)
    qb_empty = SlackQueryBuilder(terms=(), extra_query="has:link")
    assert qb_empty.build_query() == "has:link"


# --- Metadata resolution & caching ---


def test_user_info_caching(monkeypatch):
    client = SlackClient(token="xoxp-test")
    api_calls = 0

    def mock_request(endpoint: str, params: dict | None = None):
        nonlocal api_calls
        api_calls += 1
        return {
            "ok": True,
            "user": {"id": "U111", "profile": {"display_name": "Charlie"}},
        }

    monkeypatch.setattr(client, "_request", mock_request)

    name1 = client.get_user_info("U111")
    name2 = client.get_user_info("U111")
    assert name1 == "Charlie"
    assert name2 == "Charlie"
    assert api_calls == 1  # Second call served from cache


# --- CLI Auth integration ---


def test_cli_auth_slack_token_flag():
    assert cli.main(["auth", "slack", "--token", "xoxp-user-token-12345"]) == 0
    assert secrets.get_secret("slack") == "xoxp-user-token-12345"

    # SlackSource automatically picks up keyring secret
    source = SlackSource()
    assert source.token == "xoxp-user-token-12345"


def test_cli_auth_slack_interactive(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt: "xoxp-interactive-token")
    assert cli.main(["auth", "slack"]) == 0
    assert secrets.get_secret("slack") == "xoxp-interactive-token"
    assert "stored slack token in keyring" in capsys.readouterr().out
