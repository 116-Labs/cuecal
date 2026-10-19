"""Tests for Google sign-in, stored-credential refresh and the calendar picker."""

from __future__ import annotations

import json
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from google.oauth2.credentials import Credentials

from cuecal import cli, db, google_auth, registry
from cuecal.config import load_config, parse_config
from cuecal.sinks.google import GoogleCalendarSink
from cuecal.sources.gmail import GmailNotAuthorizedError

TEAM = "team@group.calendar.google.com"
CALENDAR_LIST = {
    "items": [
        {"id": "me@example.com", "summary": "Me", "accessRole": "owner", "primary": True},
        {"id": TEAM, "summary": "Team", "accessRole": "writer"},
        {"id": "holidays@group.v.calendar.google.com", "summary": "Holidays",
         "accessRole": "reader"},
        {"id": "busy@group.calendar.google.com", "summary": "Busy",
         "accessRole": "freeBusyReader"},
    ]
}


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def creds_blob(token: str = "access-0", *, expires_in: timedelta = timedelta(hours=1),
               client_id: str = "cid", client_secret: str = "csecret") -> str:
    return Credentials(
        token=token,
        refresh_token="refresh-0",
        token_uri=google_auth.TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=list(google_auth.GOOGLE_SCOPES),
        expiry=_utcnow() + expires_in,
    ).to_json()


@pytest.fixture
def store(monkeypatch) -> dict[str, str]:
    entries: dict[str, str] = {}
    monkeypatch.setattr("cuecal.secrets.get_secret", entries.get)
    monkeypatch.setattr("cuecal.secrets.set_secret", entries.__setitem__)
    return entries


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, store):
    monkeypatch.setenv("CUECAL_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("CUECAL_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("CUECAL_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("CUECAL_LOCK_PATH", str(tmp_path / "cuecal.lock"))
    monkeypatch.setattr(registry, "_registry", {kind: {} for kind in registry.KINDS})
    monkeypatch.setattr(registry, "load_entry_points", lambda: [])
    monkeypatch.setattr("cuecal.notify.DesktopNotifier.send", lambda self, notification: None)
    monkeypatch.setattr(google_auth.webbrowser, "get", lambda *args: object())

    def no_network(*args, **kwargs):
        raise AssertionError("test reached the network")

    monkeypatch.setattr("urllib.request.urlopen", no_network)


@dataclass
class FlowRecorder:
    client_configs: list[dict[str, Any]] = field(default_factory=list)
    scopes: list[list[str]] = field(default_factory=list)
    server_kwargs: list[dict[str, Any]] = field(default_factory=list)


@pytest.fixture
def flow(monkeypatch) -> FlowRecorder:
    recorder = FlowRecorder()

    class FakeFlow:
        def __init__(self, client_config: dict[str, Any], scopes: list[str]) -> None:
            self.client = client_config["installed"]
            self.scopes = scopes

        @classmethod
        def from_client_config(cls, client_config, scopes):
            recorder.client_configs.append(client_config)
            recorder.scopes.append(list(scopes))
            return cls(client_config, scopes)

        def run_local_server(self, **kwargs):
            recorder.server_kwargs.append(kwargs)
            return Credentials(
                token="access-1",
                refresh_token="refresh-1",
                token_uri=self.client.get("token_uri", google_auth.TOKEN_URI),
                client_id=self.client["client_id"],
                client_secret=self.client["client_secret"],
                scopes=self.scopes,
                expiry=_utcnow() + timedelta(hours=1),
            )

    monkeypatch.setattr(google_auth, "InstalledAppFlow", FakeFlow)
    return recorder


@pytest.fixture
def client_json(tmp_path):
    path = tmp_path / "client.json"
    path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "desktop-id",
                    "client_secret": "desktop-secret",
                    "auth_uri": google_auth.AUTH_URI,
                    "token_uri": google_auth.TOKEN_URI,
                    "redirect_uris": ["http://localhost"],
                }
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def calendar_api(monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    def fake_request(self, method, path, params=None, body=None):
        calls.append((method, path))
        assert path == "/users/me/calendarList"
        return CALENDAR_LIST

    monkeypatch.setattr(GoogleCalendarSink, "_request", fake_request)
    return calls


class FakeTokenEndpoint:
    """Stands in for google-auth's HTTP transport on the token endpoint."""

    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status = status
        self.payload = payload
        self.urls: list[str] = []

    def __call__(self, url, method="GET", body=None, headers=None, timeout=None, **kwargs):
        self.urls.append(url)
        return type(
            "Response",
            (),
            {"status": self.status, "headers": {}, "data": json.dumps(self.payload).encode()},
        )()


def _token_endpoint(monkeypatch, status: int, payload: dict[str, Any]) -> FakeTokenEndpoint:
    endpoint = FakeTokenEndpoint(status, payload)
    monkeypatch.setattr(google_auth, "Request", lambda: endpoint)
    return endpoint


INVALID_GRANT = {"error": "invalid_grant", "error_description": "Token has been revoked."}


# -- cuecal auth google ------------------------------------------------------------------


def test_auth_google_runs_flow_with_exactly_the_calendar_scopes_and_stores_blob(
    store, flow, client_json, tmp_path
):
    argv = ["auth", "google", "--client-json", str(client_json), "--calendar", TEAM]
    assert cli.main(argv) == 0

    assert flow.scopes == [[google_auth.SCOPE_EVENTS, google_auth.SCOPE_CALENDAR_LIST]]
    assert flow.server_kwargs[0]["host"] == "127.0.0.1"
    assert flow.server_kwargs[0]["port"] == 0
    stored = json.loads(store["google"])
    assert stored["token"] == "access-1"
    assert stored["refresh_token"] == "refresh-1"
    assert stored["client_id"] == "desktop-id"
    assert stored["client_secret"] == "desktop-secret"
    assert set(stored["scopes"]) == set(google_auth.GOOGLE_SCOPES)
    assert "expiry" in stored


def test_auth_google_stores_blob_under_secrets_override(store, flow, client_json, tmp_path):
    (tmp_path / "config.toml").write_text('[secrets]\ngoogle = "gcal-work"\n', encoding="utf-8")
    argv = ["auth", "google", "--client-json", str(client_json), "--calendar", TEAM]
    assert cli.main(argv) == 0
    assert set(store) == {"gcal-work"}
    assert json.loads(store["gcal-work"])["token"] == "access-1"


def test_auth_google_rerun_without_client_json_reuses_client_and_replaces_tokens(store, flow):
    store["google"] = creds_blob("old-access", client_id="kept-id", client_secret="kept-secret")
    assert cli.main(["auth", "google", "--calendar", TEAM]) == 0

    client = flow.client_configs[0]["installed"]
    assert (client["client_id"], client["client_secret"]) == ("kept-id", "kept-secret")
    stored = json.loads(store["google"])
    assert stored["token"] == "access-1"
    assert stored["refresh_token"] == "refresh-1"
    assert stored["client_id"] == "kept-id"


def test_auth_google_without_client_json_or_stored_client_fails(store, flow, capsys):
    assert cli.main(["auth", "google"]) == 1
    assert "--client-json" in capsys.readouterr().err
    assert flow.client_configs == []
    assert store == {}


def test_auth_google_rejects_a_non_desktop_client_file(store, flow, tmp_path, capsys):
    path = tmp_path / "web.json"
    path.write_text(json.dumps({"web": {"client_id": "x"}}), encoding="utf-8")
    assert cli.main(["auth", "google", "--client-json", str(path)]) == 1
    assert "Desktop app" in capsys.readouterr().err
    assert store == {}


def test_auth_google_fails_clearly_when_no_browser_can_open(
    monkeypatch, store, flow, client_json, capsys
):
    def no_browser(*args):
        raise webbrowser.Error("could not locate runnable browser")

    monkeypatch.setattr(google_auth.webbrowser, "get", no_browser)
    assert cli.main(["auth", "google", "--client-json", str(client_json)]) == 1
    err = capsys.readouterr().err
    assert "cannot open a web browser" in err
    assert "Traceback" not in err
    assert flow.server_kwargs == []
    assert store == {}


def test_auth_google_dry_run_signs_in_to_nothing(store, flow, client_json, tmp_path, capsys):
    assert cli.main(["--dry-run", "auth", "google", "--client-json", str(client_json)]) == 0
    assert "dry-run" in capsys.readouterr().out
    assert flow.client_configs == []
    assert store == {}
    assert not (tmp_path / "config.toml").exists()


# -- calendar picker ---------------------------------------------------------------------


def test_picker_lists_only_owner_and_writer_calendars_and_takes_a_number(
    monkeypatch, flow, client_json, calendar_api, tmp_path, capsys
):
    answers = iter(["9", "two", "2"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    assert cli.main(["auth", "google", "--client-json", str(client_json)]) == 0

    out = capsys.readouterr().out
    assert "1. Me (me@example.com) [primary]" in out
    assert f"2. Team ({TEAM})" in out
    assert "Holidays" not in out
    assert "Busy" not in out
    assert "enter a number from 1 to 2" in out
    assert load_config(tmp_path / "config.toml").mirror.target_calendar == TEAM


def test_picker_writes_primary_for_the_primary_calendar(
    monkeypatch, flow, client_json, calendar_api, tmp_path
):
    monkeypatch.setattr("builtins.input", lambda prompt: "1")
    assert cli.main(["auth", "google", "--client-json", str(client_json)]) == 0
    assert load_config(tmp_path / "config.toml").mirror.target_calendar == "primary"


def test_calendar_flag_skips_the_picker(monkeypatch, flow, client_json, calendar_api, tmp_path):
    def no_prompt(prompt):
        raise AssertionError("picker prompted despite --calendar")

    monkeypatch.setattr("builtins.input", no_prompt)
    argv = ["auth", "google", "--client-json", str(client_json), "--calendar", TEAM]
    assert cli.main(argv) == 0
    assert calendar_api == []
    assert load_config(tmp_path / "config.toml").mirror.target_calendar == TEAM


def test_picker_refuses_a_target_listed_as_mirror_source(
    store, flow, client_json, tmp_path, capsys
):
    config = tmp_path / "config.toml"
    original = f'# mine\n[mirror]\nsource_calendars = ["{TEAM}"]\n'
    config.write_text(original, encoding="utf-8")
    argv = ["auth", "google", "--client-json", str(client_json), "--calendar", TEAM]
    assert cli.main(argv) == 1
    assert "must not include the target calendar" in capsys.readouterr().err
    assert config.read_text(encoding="utf-8") == original


# -- shared credentials helper -----------------------------------------------------------


def test_expired_credential_is_refreshed_and_written_back(monkeypatch, store):
    store["google"] = creds_blob("stale", expires_in=timedelta(hours=-1))
    endpoint = _token_endpoint(monkeypatch, 200, {"access_token": "fresh", "expires_in": 3600})

    assert google_auth.get_access_token() == "fresh"
    assert endpoint.urls == [google_auth.TOKEN_URI]
    stored = json.loads(store["google"])
    assert stored["token"] == "fresh"
    assert stored["refresh_token"] == "refresh-0"
    assert stored["client_id"] == "cid"


def test_valid_credential_is_not_refreshed(monkeypatch, store):
    blob = creds_blob("still-good")
    store["google"] = blob

    def no_refresh():
        raise AssertionError("valid credentials refreshed")

    monkeypatch.setattr(google_auth, "Request", no_refresh)
    assert google_auth.get_access_token() == "still-good"
    assert store["google"] == blob


def test_refresh_error_names_cuecal_auth_google(monkeypatch, store):
    store["google"] = creds_blob("stale", expires_in=timedelta(hours=-1))
    _token_endpoint(monkeypatch, 400, INVALID_GRANT)
    with pytest.raises(google_auth.GoogleAuthError, match="run `cuecal auth google` again"):
        google_auth.get_access_token()


def test_unreadable_keyring_entry_asks_for_sign_in_again(store):
    store["google"] = "ya29.raw-access-token"
    with pytest.raises(google_auth.GoogleAuthError, match="cuecal auth google"):
        google_auth.get_access_token()


def test_explicit_token_provider_bypasses_the_keyring(store):
    assert google_auth.resolve_token("injected") == "injected"
    assert google_auth.resolve_token(lambda: "from-callable") == "from-callable"
    assert store == {}


# -- refresh failures in commands --------------------------------------------------------


def test_run_with_revoked_sign_in_exits_nonzero_without_traceback(
    monkeypatch, store, tmp_path, caplog, capsys
):
    (tmp_path / "config.toml").write_text('sources = ["calendar"]\n', encoding="utf-8")
    store["google"] = creds_blob("stale", expires_in=timedelta(hours=-1))
    _token_endpoint(monkeypatch, 400, INVALID_GRANT)

    with caplog.at_level("ERROR", logger="cuecal"):
        assert cli.main(["run", "--once"]) == 1

    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert errors and all(r.exc_info is None for r in errors)
    assert any("cuecal auth google" in r.getMessage() for r in errors)
    assert "Traceback" not in capsys.readouterr().err
    conn = db.connect(tmp_path / "state.db")
    try:
        last = conn.execute("SELECT status, error FROM service_run ORDER BY id DESC").fetchone()
    finally:
        conn.close()
    assert last[0] == "error"
    assert "cuecal auth google" in last[1]


def test_command_with_revoked_sign_in_prints_message_and_exits_nonzero(
    monkeypatch, store, tmp_path, capsys
):
    (tmp_path / "config.toml").write_text("", encoding="utf-8")
    store["google"] = creds_blob("stale", expires_in=timedelta(hours=-1))
    _token_endpoint(monkeypatch, 400, INVALID_GRANT)

    assert cli.main(["mirror", "calendars"]) == 1
    err = capsys.readouterr().err
    assert "cuecal auth google" in err
    assert "Traceback" not in err


def test_run_reports_gmail_not_authorized_and_keeps_other_sources(tmp_path, caplog):
    fetched: list[str] = []

    class CalendarOnlyGmail:
        name = "gmail"

        def __init__(self, **kwargs: Any) -> None:
            pass

        def fetch_since(self, cursor):
            raise GmailNotAuthorizedError("Gmail not authorized: no Gmail scope")

    class Other:
        name = "other"

        def fetch_since(self, cursor):
            fetched.append("other")
            return [], "other-cursor"

    registry.register("sources", "gmail", CalendarOnlyGmail)
    registry.register("sources", "other", Other)
    (tmp_path / "config.toml").write_text('sources = ["gmail", "other"]\n', encoding="utf-8")

    with caplog.at_level("ERROR", logger="cuecal"):
        assert cli.main(["run", "--once"]) == 1

    assert "Gmail not authorized" in caplog.text
    assert fetched == ["other"]
    conn = db.connect(tmp_path / "state.db")
    try:
        assert db.get_cursor(conn, "other") == "other-cursor"
    finally:
        conn.close()


# -- target calendar ---------------------------------------------------------------------


class RecordingCalendarApi:
    def __init__(self) -> None:
        self.paths: list[tuple[str, str]] = []

    def request(self, method, path, params=None, json=None):
        self.paths.append((method, path))
        if method == "POST":
            return {"id": "created", "start": {"dateTime": "2026-10-20T10:00:00Z"}}
        return {"items": []}


def test_google_sink_writes_to_and_dedupe_searches_the_target_calendar():
    from cuecal.models import MeetingCandidate

    registry.register("sinks", "google-calendar", GoogleCalendarSink)
    cfg = parse_config({"mirror": {"target_calendar": TEAM}, "secrets": {"google": "gcal"}})
    sink = cli._sink(cfg, "google-calendar")
    assert (sink.calendar_id, sink.secret_ref) == (TEAM, "gcal")
    assert cli._calendar_source(cfg).target.calendar_id == TEAM

    api = RecordingCalendarApi()
    sink._http_client = api
    start = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
    sink.busy(start, start + timedelta(hours=1))
    sink.create(MeetingCandidate(title="Sync", start=start, meeting_id="123", confidence=1.0))

    prefix = f"/calendars/{urllib.parse.quote(TEAM, safe='')}/events"
    assert [m for m, _ in api.paths] == ["GET", "GET", "POST"]
    assert all(path.startswith(prefix) for _, path in api.paths)


def test_google_sink_defaults_to_primary_calendar():
    registry.register("sinks", "google-calendar", GoogleCalendarSink)
    assert cli._sink(parse_config({}), "google-calendar").calendar_id == "primary"
