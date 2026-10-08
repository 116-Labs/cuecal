"""Notifiers that alert the user when a meeting candidate enters the pending queue."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .config import Config
from .models import MeetingCandidate

logger = logging.getLogger("cuecal.notify")

SNIPPET_LIMIT = 120
NTFY_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class Notification:
    title: str
    body: str
    url: str | None = None


@runtime_checkable
class Notifier(Protocol):
    """Protocol implemented by notification channels."""

    name: str

    def send(self, notification: Notification) -> None:
        """Deliver the notification; raise on failure."""
        ...


def build_notification(
    candidate: MeetingCandidate, *, snippet: str | None = None, pending_id: int | None = None
) -> Notification:
    """Compose a concise payload: start time, join URL and a short source snippet."""
    title = f"Meeting pending approval: {candidate.title or 'untitled'}"
    lines = []
    if candidate.start:
        lines.append(f"Starts: {candidate.start.strftime('%a %Y-%m-%d %H:%M')}")
    if candidate.join_url:
        lines.append(f"Join: {candidate.join_url}")
    if snippet:
        text = " ".join(snippet.split())
        if len(text) > SNIPPET_LIMIT:
            text = text[: SNIPPET_LIMIT - 1].rstrip() + "…"
        lines.append(f"Source: {text}")
    if pending_id is not None:
        lines.append(f"Review: cuecal approve {pending_id}")
    return Notification(title=title, body="\n".join(lines), url=candidate.join_url)


def _applescript_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


class DesktopNotifier:
    """macOS desktop notifications via terminal-notifier, falling back to osascript."""

    name = "desktop"

    def send(self, notification: Notification) -> None:
        if sys.platform != "darwin":
            logger.debug("desktop notifications are only supported on macOS; skipping")
            return
        terminal_notifier = shutil.which("terminal-notifier")
        if terminal_notifier:
            cmd = [terminal_notifier, "-title", notification.title, "-message", notification.body]
            if notification.url:
                cmd += ["-open", notification.url]
        else:
            script = (
                f"display notification {_applescript_quote(notification.body)} "
                f"with title {_applescript_quote(notification.title)}"
            )
            cmd = ["osascript", "-e", script]
        subprocess.run(cmd, check=True, capture_output=True, timeout=10)


class NtfyNotifier:
    """Remote notifications through an ntfy server (https://ntfy.sh by default)."""

    name = "ntfy"

    def __init__(self, topic: str, server: str = "https://ntfy.sh") -> None:
        self.topic = topic
        self.server = server.rstrip("/")

    def send(self, notification: Notification) -> None:
        payload: dict[str, str] = {
            "topic": self.topic,
            "title": notification.title,
            "message": notification.body,
        }
        if notification.url:
            payload["click"] = notification.url
        req = urllib.request.Request(  # noqa: S310 - scheme validated in config
            self.server,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=NTFY_TIMEOUT_SECONDS):  # noqa: S310
            pass


def build_notifiers(cfg: Config) -> list[Notifier]:
    notifiers: list[Notifier] = []
    if cfg.notify_desktop:
        notifiers.append(DesktopNotifier())
    if cfg.notify_ntfy_topic:
        notifiers.append(NtfyNotifier(cfg.notify_ntfy_topic, cfg.notify_ntfy_server))
    return notifiers


def notify_pending(
    notifiers: list[Notifier],
    candidate: MeetingCandidate,
    *,
    snippet: str | None = None,
    pending_id: int | None = None,
) -> None:
    """Send to every notifier; a failing channel is logged and never breaks the run."""
    if not notifiers:
        return
    notification = build_notification(candidate, snippet=snippet, pending_id=pending_id)
    for notifier in notifiers:
        try:
            notifier.send(notification)
        except Exception as exc:  # noqa: BLE001 - notification failure must not stop polling
            logger.warning("%s notification failed: %s", notifier.name, exc)
