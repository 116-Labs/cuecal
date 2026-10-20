"""Google OAuth: installed-app sign-in, credentials in the OS keyring, and token refresh.

The keyring entry holds ``Credentials.to_json()`` (tokens plus the OAuth client ID and secret),
so a refreshed token is written back and a later sign-in can reuse the client.
"""

from __future__ import annotations

import json
import webbrowser
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow, WSGITimeoutError
from oauthlib.oauth2.rfc6749.errors import OAuth2Error

from cuecal import secrets

SECRET_NAME = "google"
AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"

SCOPE_EVENTS = "https://www.googleapis.com/auth/calendar.events"
SCOPE_CALENDAR_LIST = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
# The scopes ADR 0005 grants. `calendar.events` reads events on every calendar the user can
# access, so mirroring needs nothing beyond them.
GOOGLE_SCOPES = (SCOPE_EVENTS, SCOPE_CALENDAR_LIST)

REAUTH_HINT = "run `cuecal auth google` again"
SIGN_IN_TIMEOUT_SECONDS = 300
NO_BROWSER_MESSAGE = (
    "cannot open a web browser on this machine; run `cuecal auth google` in a desktop session "
    "on the machine itself (Google only redirects a Desktop app sign-in to 127.0.0.1)"
)

TokenProvider = str | Callable[[], str] | None


class GoogleAuthError(RuntimeError):
    """Raised when Google credentials cannot be obtained, read or refreshed."""


class GoogleCredentialsMissing(GoogleAuthError):
    """Raised when no Google sign-in is stored in the keyring."""


class GoogleUnreachable(GoogleAuthError):
    """Raised when the token endpoint cannot be reached; the stored sign-in stays valid."""


def secret_name(secret_refs: Mapping[str, str] | None = None) -> str:
    """The keyring entry for Google credentials, honouring a ``[secrets] google`` override."""
    return (secret_refs or {}).get("google") or SECRET_NAME


def _stored_info(name: str) -> dict[str, Any]:
    raw = secrets.get_secret(name)
    if not raw:
        raise GoogleCredentialsMissing(
            f"no Google sign-in in keyring entry {name!r}; run `cuecal auth google`"
        )
    try:
        info = json.loads(raw)
    except ValueError:
        info = None
    if not isinstance(info, dict):
        raise GoogleAuthError(
            f"keyring entry {name!r} does not hold Google credentials; {REAUTH_HINT}"
        )
    return info


def load_credentials(name: str = SECRET_NAME) -> Credentials:
    info = _stored_info(name)
    try:
        return Credentials.from_authorized_user_info(info)
    except (ValueError, TypeError) as exc:
        raise GoogleAuthError(
            f"keyring entry {name!r} holds incomplete Google credentials; {REAUTH_HINT}"
        ) from exc


def get_access_token(name: str = SECRET_NAME) -> str:
    """Return a valid access token, refreshing and storing the credentials when expired."""
    creds = load_credentials(name)
    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            raise GoogleAuthError(
                f"Google refused to refresh the stored sign-in ({exc}); {REAUTH_HINT}"
            ) from exc
        except TransportError as exc:
            raise GoogleUnreachable(f"cannot reach Google to refresh the sign-in: {exc}") from exc
        secrets.set_secret(name, creds.to_json())
    return creds.token


def resolve_token(provider: TokenProvider, secret_ref: str | None = None) -> str:
    """An injected token or callable wins; otherwise the stored, refreshed credentials."""
    if callable(provider):
        return provider()
    if isinstance(provider, str):
        return provider
    return get_access_token(secret_ref or SECRET_NAME)


def read_client_file(path: Path) -> dict[str, Any]:
    """Read a Desktop app OAuth client JSON downloaded from Google Cloud."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GoogleAuthError(f"cannot read OAuth client file {path}: {exc.strerror}") from exc
    except ValueError as exc:
        raise GoogleAuthError(f"OAuth client file {path} is not valid JSON") from exc
    client = data.get("installed") if isinstance(data, dict) else None
    if not isinstance(client, dict) or not client.get("client_id"):
        raise GoogleAuthError(
            f"OAuth client file {path} is not a Desktop app client; create an OAuth client "
            'of type "Desktop app" in Google Cloud and download its JSON'
        )
    return data


def stored_client_config(name: str = SECRET_NAME) -> dict[str, Any]:
    """The OAuth client kept in the stored credentials, for a sign-in without --client-json."""
    try:
        info = _stored_info(name)
    except GoogleCredentialsMissing as exc:
        raise GoogleAuthError(
            "no stored Google OAuth client; pass --client-json PATH with the Desktop app "
            "client JSON from Google Cloud"
        ) from exc
    if not info.get("client_id") or not info.get("client_secret"):
        raise GoogleAuthError(
            f"keyring entry {name!r} holds no OAuth client; pass --client-json PATH"
        )
    return {
        "installed": {
            "client_id": info["client_id"],
            "client_secret": info["client_secret"],
            "auth_uri": AUTH_URI,
            "token_uri": info.get("token_uri") or TOKEN_URI,
        }
    }


def sign_in(client_config: dict[str, Any]) -> Credentials:
    """Run the loopback sign-in in the local browser and return the granted credentials."""
    try:
        webbrowser.get()
    except webbrowser.Error as exc:
        raise GoogleAuthError(NO_BROWSER_MESSAGE) from exc
    flow = InstalledAppFlow.from_client_config(client_config, scopes=list(GOOGLE_SCOPES))
    try:
        return flow.run_local_server(
            host="127.0.0.1",
            port=0,
            authorization_prompt_message="Sign in to Google in the browser window that opened.",
            timeout_seconds=SIGN_IN_TIMEOUT_SECONDS,
        )
    except webbrowser.Error as exc:
        raise GoogleAuthError(NO_BROWSER_MESSAGE) from exc
    except WSGITimeoutError as exc:
        raise GoogleAuthError(
            f"no answer from the browser sign-in within {SIGN_IN_TIMEOUT_SECONDS} seconds"
        ) from exc
    except Warning as exc:
        # oauthlib warns, as an exception, when the user unticks a requested permission.
        raise GoogleAuthError(
            f"Google granted fewer permissions than cuecal needs ({exc}); sign in again and "
            "allow all requested access"
        ) from exc
    except OAuth2Error as exc:
        raise GoogleAuthError(f"Google sign-in failed: {exc.description or exc}") from exc
