import json
import subprocess
from datetime import datetime

import pytest

from cuecal import cli, notify
from cuecal.config import Config, ConfigError, parse_config
from cuecal.models import MeetingCandidate, Message
from cuecal.notify import DesktopNotifier, Notification, Notifier, NtfyNotifier


def _cand(**kw):
    base = {
        "title": "Standup",
        "start": datetime(2026, 10, 12, 9, 30),
        "join_url": "https://zoom.us/j/123",
    }
    base.update(kw)
    return MeetingCandidate(**base)


def test_payload_has_start_url_and_snippet():
    n = notify.build_notification(_cand(), snippet="join us\n for standup", pending_id=7)
    assert "Standup" in n.title
    assert "2026-10-12 09:30" in n.body
    assert "https://zoom.us/j/123" in n.body
    assert "Source: join us for standup" in n.body
    assert "cuecal approve 7" in n.body
    assert n.url == "https://zoom.us/j/123"


def test_payload_truncates_long_snippet_and_skips_missing_fields():
    n = notify.build_notification(_cand(start=None, join_url=None), snippet="x" * 500)
    assert "Starts" not in n.body
    assert "Join" not in n.body
    assert len(n.body) < 200
    assert n.url is None


def test_desktop_uses_osascript(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.sys, "platform", "darwin")
    monkeypatch.setattr(notify.shutil, "which", lambda name: None)
    monkeypatch.setattr(notify.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    DesktopNotifier().send(Notification(title='He said "hi"', body="body"))
    assert calls[0][0] == "osascript"
    assert 'with title "He said \\"hi\\""' in calls[0][2]


def test_desktop_prefers_terminal_notifier(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.sys, "platform", "darwin")
    monkeypatch.setattr(notify.shutil, "which", lambda name: "/bin/terminal-notifier")
    monkeypatch.setattr(notify.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    DesktopNotifier().send(Notification(title="t", body="b", url="https://x.test"))
    assert calls[0][0] == "/bin/terminal-notifier"
    assert calls[0][-2:] == ["-open", "https://x.test"]


def test_desktop_noop_off_macos(monkeypatch):
    monkeypatch.setattr(notify.sys, "platform", "linux")
    monkeypatch.setattr(notify.subprocess, "run", lambda *a, **k: pytest.fail("ran"))
    DesktopNotifier().send(Notification(title="t", body="b"))


def test_ntfy_posts_json(monkeypatch):
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data)
        seen["method"] = req.get_method()
        return Resp()

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    NtfyNotifier("my-topic", "https://ntfy.example/").send(
        Notification(title="T", body="B", url="https://zoom.us/j/1")
    )
    assert seen["url"] == "https://ntfy.example"
    assert seen["method"] == "POST"
    assert seen["body"] == {
        "topic": "my-topic",
        "title": "T",
        "message": "B",
        "click": "https://zoom.us/j/1",
    }


def test_build_notifiers_from_config():
    assert [n.name for n in notify.build_notifiers(Config())] == ["desktop"]
    cfg = Config(notify_desktop=False, notify_ntfy_topic="t")
    notifiers = notify.build_notifiers(cfg)
    assert [n.name for n in notifiers] == ["ntfy"]
    assert all(isinstance(n, Notifier) for n in notifiers)
    assert notify.build_notifiers(Config(notify_desktop=False)) == []


def test_notify_pending_survives_failing_notifier():
    got = []

    class Bad:
        name = "bad"

        def send(self, notification):
            raise RuntimeError("boom")

    class Good:
        name = "good"

        def send(self, notification):
            got.append(notification)

    notify.notify_pending([Bad(), Good()], _cand())
    assert len(got) == 1


def test_config_notify_parsing():
    cfg = parse_config(
        {"notify": {"desktop": False, "ntfy_topic": " t ", "ntfy_server": "http://h:8080"}}
    )
    assert (cfg.notify_desktop, cfg.notify_ntfy_topic, cfg.notify_ntfy_server) == (
        False,
        "t",
        "http://h:8080",
    )
    for bad in ({"desktop": "yes"}, {"ntfy_topic": 3}, {"ntfy_server": "ftp://x"}, {"x": 1}):
        with pytest.raises(ConfigError):
            parse_config({"notify": bad})


def test_cli_run_notifies_when_item_enters_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("CUECAL_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("CUECAL_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("CUECAL_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("CUECAL_LOCK_PATH", str(tmp_path / "cuecal.lock"))
    assert cli.main(["init"]) == 0
    (tmp_path / "config.toml").write_text(
        'sources = ["dummy"]\nsink = "none"\n[notify]\ndesktop = true\n', encoding="utf-8"
    )

    class DummySource:
        name = "dummy"

        def fetch_since(self, cursor):
            msg = Message(
                id="m1", source="dummy", sender="a", ts=datetime.now(), text="lunch sync maybe"
            )
            return [msg], "c"

    def fake_get(kind, name):
        if kind == "sources":
            return DummySource
        raise KeyError(name)

    sent = []
    monkeypatch.setattr("cuecal.cli.registry.get", fake_get)
    monkeypatch.setattr(
        "cuecal.extract.extract",
        lambda msg: _cand(confidence=0.6, meeting_id="mtg1", source_ref=msg.id),
    )
    monkeypatch.setattr(DesktopNotifier, "send", lambda self, n: sent.append(n))

    assert cli.main(["run", "--once"]) == 0
    assert len(sent) == 1
    assert "Standup" in sent[0].title
    assert "lunch sync maybe" in sent[0].body


def test_subprocess_error_is_swallowed(monkeypatch):
    monkeypatch.setattr(notify.sys, "platform", "darwin")
    monkeypatch.setattr(notify.shutil, "which", lambda name: None)

    def boom(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(notify.subprocess, "run", boom)
    notify.notify_pending([DesktopNotifier()], _cand())
