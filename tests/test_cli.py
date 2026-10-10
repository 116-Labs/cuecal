import pytest

from cuecal import __version__, cli, db, registry

SUBCOMMANDS = ["init", "auth", "run", "pending", "misses", "missed", "service", "doctor"]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CUECAL_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("CUECAL_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("CUECAL_LAUNCHD_PLIST", str(tmp_path / "com.cuecal.agent.plist"))
    monkeypatch.setenv("CUECAL_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("CUECAL_LOCK_PATH", str(tmp_path / "cuecal.lock"))
    monkeypatch.setattr(registry, "_registry", {kind: {} for kind in registry.KINDS})
    monkeypatch.setattr("cuecal.notify.DesktopNotifier.send", lambda self, notification: None)
    # The launchd backend writes only a plist file, so it runs on any host.
    monkeypatch.setattr("cuecal.service._platform", lambda: "darwin")


def test_help_lists_subcommands(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for name in SUBCOMMANDS:
        assert name in out


def test_version_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out == f"cuecal {__version__}\n"


def test_doctor_reports_paths_backend_and_plugins(tmp_path, capsys):
    registry.register("sinks", "ics", object())
    assert cli.main(["init"]) == 0
    capsys.readouterr()
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert f"config path: {tmp_path / 'config.toml'}" in out
    assert f"db path: {tmp_path / 'state.db'}" in out
    assert "keyring backend:" in out
    assert "sinks: google-calendar, ics" in out
    assert "sources: gmail" in out


def test_doctor_reports_broken_plugin(monkeypatch, capsys):
    class BadEntryPoint:
        name = "bad"

        def load(self):
            raise ImportError("boom")

    monkeypatch.setattr(
        registry,
        "entry_points",
        lambda group: [BadEntryPoint()] if group == "cuecal.sinks" else [],
    )
    assert cli.main(["init"]) == 0
    capsys.readouterr()
    assert cli.main(["doctor"]) == 1
    assert "broken plugin: sinks/bad" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["--dry-run", "-v", "run", "--once"],
        ["run", "--once", "--dry-run", "-v"],
        ["--dry-run", "run", "--once", "-v"],
    ],
)
def test_global_flags_accepted_in_any_position(argv):
    args = cli.build_parser().parse_args(argv)
    assert args.dry_run is True
    assert args.verbose is True


def test_global_flags_default_false():
    args = cli.build_parser().parse_args(["run"])
    assert args.dry_run is False
    assert args.verbose is False


def test_doctor_flags_missing_config(capsys):
    assert cli.main(["doctor"]) == 1
    assert "cuecal init" in capsys.readouterr().out


def test_init_creates_config_and_db(tmp_path):
    assert cli.main(["init"]) == 0
    assert (tmp_path / "config.toml").exists()
    assert (tmp_path / "state.db").exists()


def test_stub_commands_exit_nonzero(capsys):
    assert cli.main(["auth", "google"]) == 2
    assert "not implemented" in capsys.readouterr().err


def test_cli_service_lifecycle(tmp_path, capsys):
    # Initial status: not installed
    assert cli.main(["service", "status"]) == 0
    out = capsys.readouterr().out
    assert "service: not installed (launchd)" in out
    assert "last run: never" in out

    # Install
    assert cli.main(["service", "install"]) == 0
    out = capsys.readouterr().out
    assert "installed launchd service" in out
    assert (tmp_path / "com.cuecal.agent.plist").exists()

    # Status: installed
    assert cli.main(["service", "status"]) == 0
    out = capsys.readouterr().out
    assert "service: installed (launchd)" in out

    # Uninstall
    assert cli.main(["service", "uninstall"]) == 0
    out = capsys.readouterr().out
    assert "uninstalled launchd service" in out
    assert not (tmp_path / "com.cuecal.agent.plist").exists()


@pytest.mark.parametrize("action", ["install", "uninstall", "status"])
def test_cli_service_unsupported_platform(monkeypatch, tmp_path, capsys, action):
    monkeypatch.setattr("cuecal.service._platform", lambda: "linux")
    assert cli.main(["service", action]) == 1
    captured = capsys.readouterr()
    assert "not supported on linux" in captured.err
    assert "installed" not in captured.out
    assert not (tmp_path / "com.cuecal.agent.plist").exists()


def test_cli_service_lifecycle_windows(monkeypatch, capsys):
    import subprocess

    registered = {"value": False}
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        rc = 0
        stdout = ""
        if args[:2] == ["schtasks", "/Create"]:
            registered["value"] = True
        elif args[:2] == ["schtasks", "/Delete"]:
            registered["value"] = False
        elif args[:2] == ["schtasks", "/Query"]:
            rc = 0 if registered["value"] else 1
        elif args[0] == "powershell.exe":
            stdout = '{"last_run":null,"last_result":267011,"next_run":"2026-10-11T09:05:00"}'
        return subprocess.CompletedProcess(args, rc, stdout, "")

    monkeypatch.setattr("cuecal.service._platform", lambda: "win32")
    monkeypatch.setattr("cuecal.service.subprocess.run", fake_run)
    monkeypatch.setenv("CUECAL_BIN", "C:/Users/me/.local/bin/cuecal.exe")

    assert cli.main(["service", "status"]) == 0
    assert "service: not installed (Task Scheduler)" in capsys.readouterr().out

    assert cli.main(["service", "install"]) == 0
    assert "installed Task Scheduler service: CueCal" in capsys.readouterr().out

    assert cli.main(["service", "status"]) == 0
    out = capsys.readouterr().out
    assert "service: installed (Task Scheduler)" in out
    assert "task last run: never" in out
    assert "task next run: 2026-10-11T09:05:00" in out

    assert cli.main(["service", "uninstall"]) == 0
    assert "uninstalled Task Scheduler service" in capsys.readouterr().out
    assert cli.main(["service", "uninstall"]) == 0
    assert "service was not installed" in capsys.readouterr().out
    assert not any(args[0] == "launchctl" for args in calls)


def test_cli_service_install_windows_reports_schtasks_failure(monkeypatch, capsys):
    import subprocess

    monkeypatch.setattr("cuecal.service._platform", lambda: "win32")
    monkeypatch.setattr(
        "cuecal.service.subprocess.run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 1, "", "ERROR: Access is denied."),
    )
    assert cli.main(["service", "install"]) == 1
    captured = capsys.readouterr()
    assert "schtasks /Create failed: ERROR: Access is denied." in captured.err
    assert "installed" not in captured.out


def test_cli_run_once(tmp_path, capsys):
    assert cli.main(["init"]) == 0
    capsys.readouterr()
    assert cli.main(["run", "--once"]) == 0

    assert cli.main(["service", "status"]) == 0
    out = capsys.readouterr().out
    assert "last run:" in out
    assert "(success)" in out


def test_cli_run_lock_contention(tmp_path, capsys):
    from cuecal.lock import SingleInstanceLock

    assert cli.main(["init"]) == 0
    capsys.readouterr()

    # Hold the lock externally
    external_lock = SingleInstanceLock(tmp_path / "cuecal.lock")
    assert external_lock.acquire() is True

    # Overlapping run invocation must exit cleanly with code 0
    assert cli.main(["run", "--once"]) == 0

    external_lock.release()


def test_cli_run_orchestration(tmp_path, monkeypatch):
    import sqlite3

    assert cli.main(["init"]) == 0

    # Mock extract
    from cuecal.models import MeetingCandidate, Message

    class DummySource:
        name = "dummy"

        def fetch_since(self, cursor):
            from datetime import datetime

            msg = Message(
                id="msg1", source="dummy", sender="test", ts=datetime.now(), text="test text"
            )
            return [msg], "cursor_next"

    class DummySink:
        name = "dummy-sink"

        def create_event(self, candidate):
            return "event1"

    def fake_registry_get(kind, name):
        if kind == "sources":
            return DummySource
        if kind == "sinks":
            return DummySink()
        raise KeyError(name)

    monkeypatch.setattr("cuecal.cli.registry.get", fake_registry_get)

    def fake_extract(msg):
        return MeetingCandidate(
            confidence=0.9, meeting_id="mtg1", title="test", start=None, end=None
        )

    monkeypatch.setattr("cuecal.extract.extract", fake_extract)

    # We need to set the config source to dummy
    conn = sqlite3.connect(tmp_path / "state.db")

    # Overwrite config to use dummy source
    config_path = tmp_path / "config.toml"
    with open(config_path) as f:
        content = f.read()
    with open(config_path, "w") as f:
        f.write(content.replace("sources = []", 'sources = ["dummy"]'))

    assert cli.main(["run", "--once"]) == 0

    cur = conn.execute("SELECT cursor FROM source_cursor WHERE source = 'dummy'").fetchone()
    assert cur is not None
    assert cur[0] == "cursor_next"

    cur = conn.execute("SELECT sink_event_id FROM event_link WHERE meeting_id = 'mtg1'").fetchone()
    assert cur is not None
    assert cur[0] == "event1"


def test_cli_run_dry_run_skips_writes(tmp_path, monkeypatch):
    import sqlite3

    assert cli.main(["init"]) == 0

    from cuecal.models import MeetingCandidate, Message

    class DummySource:
        name = "dummy"

        def fetch_since(self, cursor):
            from datetime import datetime

            msg = Message(
                id="msg1", source="dummy", sender="test", ts=datetime.now(), text="test text"
            )
            return [msg], "cursor_next"

    sink_calls = []

    class DummySink:
        name = "dummy-sink"

        def create_event(self, candidate):
            sink_calls.append(candidate)
            return "event1"

    def fake_registry_get(kind, name):
        if kind == "sources":
            return DummySource
        if kind == "sinks":
            return DummySink()
        raise KeyError(name)

    monkeypatch.setattr("cuecal.cli.registry.get", fake_registry_get)
    monkeypatch.setattr(
        "cuecal.extract.extract",
        lambda msg: MeetingCandidate(
            confidence=0.9, meeting_id="mtg1", title="test", start=None, end=None
        ),
    )

    config_path = tmp_path / "config.toml"
    with open(config_path) as f:
        content = f.read()
    with open(config_path, "w") as f:
        f.write(content.replace("sources = []", 'sources = ["dummy"]'))

    assert cli.main(["--dry-run", "run", "--once"]) == 0

    conn = sqlite3.connect(tmp_path / "state.db")
    cur = conn.execute("SELECT cursor FROM source_cursor WHERE source = 'dummy'").fetchone()
    assert cur is None  # cursor unchanged
    assert not sink_calls


def test_cli_run_daemon_loop(tmp_path, monkeypatch):
    assert cli.main(["init"]) == 0

    class DummySource:
        name = "dummy"

        def fetch_since(self, cursor):
            return [], None

    def fake_registry_get(kind, name):
        if kind == "sources":
            return DummySource
        if kind == "sinks":

            class DummySink:
                name = "dummy-sink"

                def create_event(self, candidate):
                    return "event1"

            return DummySink()
        raise KeyError(name)

    monkeypatch.setattr("cuecal.cli.registry.get", fake_registry_get)

    config_path = tmp_path / "config.toml"
    with open(config_path) as f:
        content = f.read()
    with open(config_path, "w") as f:
        f.write(content.replace("sources = []", 'sources = ["dummy"]'))

    sleeps = []

    def fake_sleep(secs):
        sleeps.append(secs)
        raise RuntimeError("stop daemon loop")

    import time

    monkeypatch.setattr(time, "sleep", fake_sleep)

    # RuntimeError is caught by cli.py try block and raised again
    with pytest.raises(RuntimeError, match="stop daemon loop"):
        cli.main(["run"])

    assert len(sleeps) == 1


def test_cli_pending_list_and_empty(tmp_path, capsys):
    assert cli.main(["init"]) == 0
    capsys.readouterr()

    # Empty queue
    assert cli.main(["pending"]) == 0
    assert "no pending candidates" in capsys.readouterr().out

    # Add items to pending
    from cuecal import db
    from cuecal.models import MeetingCandidate

    conn = db.connect(tmp_path / "state.db")
    cand = MeetingCandidate(
        title="Uncertain Sync",
        confidence=0.55,
        meeting_id="zoom_555",
        join_url="https://zoom.us/j/555",
        source_ref="slack:C123",
    )
    db.add_pending(
        conn,
        candidate=cand,
        reason="low confidence (0.55 < 0.85)",
        source_snippet="Sync later? https://zoom.us/j/555",
        source="slack",
        message_id="m123",
    )
    conn.close()

    assert cli.main(["pending"]) == 0
    out = capsys.readouterr().out
    assert "1 pending candidate:" in out
    assert "[1] Uncertain Sync" in out
    assert "Confidence: 0.55" in out
    assert "Reason:     low confidence (0.55 < 0.85)" in out
    assert "Join URL:   https://zoom.us/j/555" in out
    assert "Source:     slack" in out
    assert "Snippet:    Sync later? https://zoom.us/j/555" in out


def test_cli_approve_success_and_dry_run(tmp_path, monkeypatch, capsys):
    from cuecal import db
    from cuecal.models import MeetingCandidate

    assert cli.main(["init"]) == 0
    capsys.readouterr()

    created_events = []

    class DummySink:
        name = "google-calendar"

        def create(self, candidate):
            created_events.append(candidate)
            return "sink_event_999"

    monkeypatch.setattr(
        "cuecal.cli.registry.get",
        lambda kind, name: DummySink() if kind == "sinks" else None,
    )

    conn = db.connect(tmp_path / "state.db")
    cand = MeetingCandidate(
        title="Budget Planning",
        confidence=0.6,
        meeting_id="meet_budget",
        join_url="https://meet.google.com/abc-defg-hij",
        source_ref="gmail:thread_123",
        attendees=["alice@example.com", "bob@example.com"],
    )
    pid = db.add_pending(
        conn,
        candidate=cand,
        reason="low confidence",
        source="gmail",
        message_id="msg_bg",
    )
    conn.close()

    # Dry-run approve
    assert cli.main(["--dry-run", "approve", str(pid)]) == 0
    out = capsys.readouterr().out
    assert "dry-run: would approve #1 and create event for 'Budget Planning'" in out
    assert len(created_events) == 0

    # Non-dry-run approve
    assert cli.main(["approve", str(pid)]) == 0
    out = capsys.readouterr().out
    assert "approved #1: created event sink_event_999 (Budget Planning)" in out
    assert len(created_events) == 1
    assert created_events[0].title == "Budget Planning"
    assert created_events[0].meeting_id == "meet_budget"
    assert created_events[0].source_ref == "gmail:thread_123"
    assert created_events[0].attendees == ["alice@example.com", "bob@example.com"]

    # Verify event_link and status updated in DB
    conn = db.connect(tmp_path / "state.db")
    item = db.get_pending(conn, pid)
    assert item["status"] == "approved"
    link_row = conn.execute(
        "SELECT sink_event_id FROM event_link WHERE meeting_id = 'meet_budget'"
    ).fetchone()
    assert link_row is not None
    assert link_row[0] == "sink_event_999"
    conn.close()

    # Approving already approved candidate fails
    assert cli.main(["approve", str(pid)]) == 1
    assert "error: pending candidate #1 not found" in capsys.readouterr().err


def test_cli_reject_success_and_dry_run(tmp_path, capsys):
    from cuecal import db
    from cuecal.models import MeetingCandidate

    assert cli.main(["init"]) == 0
    capsys.readouterr()

    conn = db.connect(tmp_path / "state.db")
    cand = MeetingCandidate(title="Spam Meeting", confidence=0.4)
    pid = db.add_pending(conn, candidate=cand, reason="spam")
    conn.close()

    # Dry run reject
    assert cli.main(["--dry-run", "reject", str(pid)]) == 0
    assert "dry-run: would reject candidate #1" in capsys.readouterr().out

    conn = db.connect(tmp_path / "state.db")
    assert db.get_pending(conn, pid)["status"] == "pending"
    conn.close()

    # Non dry run reject
    assert cli.main(["reject", str(pid)]) == 0
    assert "rejected #1: Spam Meeting" in capsys.readouterr().out

    conn = db.connect(tmp_path / "state.db")
    assert db.get_pending(conn, pid)["status"] == "rejected"
    conn.close()

    # Rejecting nonexistent candidate fails
    assert cli.main(["reject", "999"]) == 1
    assert "error: pending candidate #999 not found" in capsys.readouterr().err


def test_cli_edit_flags_and_approve(tmp_path, monkeypatch, capsys):
    from cuecal import db
    from cuecal.models import MeetingCandidate

    assert cli.main(["init"]) == 0
    capsys.readouterr()

    created_events = []

    class DummySink:
        name = "google-calendar"

        def create(self, candidate):
            created_events.append(candidate)
            return "evt_edited"

    monkeypatch.setattr(
        "cuecal.cli.registry.get",
        lambda kind, name: DummySink() if kind == "sinks" else None,
    )

    conn = db.connect(tmp_path / "state.db")
    cand = MeetingCandidate(title="Draft Meeting", confidence=0.5)
    pid = db.add_pending(conn, candidate=cand)
    conn.close()

    # Dry-run edit
    assert (
        cli.main(
            [
                "--dry-run",
                "edit",
                str(pid),
                "--title",
                "Correct Title",
                "--start",
                "2026-10-15T14:00:00Z",
            ]
        )
        == 0
    )
    assert "dry-run: would update pending candidate #1" in capsys.readouterr().out

    # Non-dry-run edit with flags
    assert (
        cli.main(
            [
                "edit",
                str(pid),
                "--title",
                "Correct Title",
                "--start",
                "2026-10-15T14:00:00Z",
                "--end",
                "2026-10-15T15:00:00Z",
                "--tz",
                "UTC",
                "--join-url",
                "https://zoom.us/j/999",
                "--meeting-id",
                "999",
                "--passcode",
                "pass123",
                "--attendees",
                "alice@example.com, bob@example.com",
            ]
        )
        == 0
    )
    assert "updated pending candidate #1" in capsys.readouterr().out

    conn = db.connect(tmp_path / "state.db")
    item = db.get_pending(conn, pid)
    updated_cand = MeetingCandidate.from_json(item["candidate_json"])
    assert updated_cand.title == "Correct Title"
    assert updated_cand.start.isoformat().startswith("2026-10-15T14:00:00")
    assert updated_cand.end.isoformat().startswith("2026-10-15T15:00:00")
    assert updated_cand.tz == "UTC"
    assert updated_cand.join_url == "https://zoom.us/j/999"
    assert updated_cand.meeting_id == "999"
    assert updated_cand.passcode == "pass123"
    assert updated_cand.attendees == ["alice@example.com", "bob@example.com"]
    conn.close()

    # Edit with --approve flag
    assert cli.main(["edit", str(pid), "--title", "Final Approved Title", "--approve"]) == 0
    out = capsys.readouterr().out
    assert "updated pending candidate #1" in out
    assert "approved #1: created event evt_edited (Final Approved Title)" in out
    assert len(created_events) == 1
    assert created_events[0].title == "Final Approved Title"


def test_cli_edit_interactive(tmp_path, monkeypatch, capsys):
    from cuecal import db
    from cuecal.models import MeetingCandidate

    assert cli.main(["init"]) == 0
    capsys.readouterr()

    conn = db.connect(tmp_path / "state.db")
    cand = MeetingCandidate(title="Old Title", confidence=0.5)
    pid = db.add_pending(conn, candidate=cand)
    conn.close()

    # Simulate user entering new title and pressing Enter for other prompts
    inputs = iter([
        "New Interactive Title",  # title
        "",  # start
        "",  # end
        "",  # tz
        "",  # join_url
        "",  # meeting_id
        "",  # passcode
        "",  # attendees
        "n",  # approve?
    ])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    assert cli.main(["edit", str(pid)]) == 0
    assert "updated pending candidate #1" in capsys.readouterr().out

    conn = db.connect(tmp_path / "state.db")
    item = db.get_pending(conn, pid)
    updated_cand = MeetingCandidate.from_json(item["candidate_json"])
    assert updated_cand.title == "New Interactive Title"
    conn.close()


def test_cli_run_routes_low_confidence_to_pending(tmp_path, monkeypatch):
    from datetime import datetime

    from cuecal import db
    from cuecal.models import MeetingCandidate, Message

    assert cli.main(["init"]) == 0

    class DummySource:
        name = "dummy"

        def fetch_since(self, cursor):
            msg1 = Message(
                id="msg_low",
                source="dummy",
                sender="alice",
                ts=datetime.now(),
                text="Low confidence text",
            )
            msg2 = Message(
                id="msg_high",
                source="dummy",
                sender="bob",
                ts=datetime.now(),
                text="High confidence text",
            )
            return [msg1, msg2], "next_cursor"

    created_events = []

    class DummySink:
        name = "dummy-sink"

        def create_event(self, candidate):
            created_events.append(candidate)
            return f"evt_{candidate.meeting_id}"

    def fake_registry_get(kind, name):
        if kind == "sources":
            return DummySource
        if kind == "sinks":
            return DummySink()
        raise KeyError(name)

    monkeypatch.setattr("cuecal.cli.registry.get", fake_registry_get)

    def fake_extract(msg):
        if msg.id == "msg_low":
            return MeetingCandidate(
                confidence=0.6,
                meeting_id="mtg_low",
                title="Low Conf Meeting",
                source_ref=msg.id,
            )
        return MeetingCandidate(
            confidence=0.95,
            meeting_id="mtg_high",
            title="High Conf Meeting",
            source_ref=msg.id,
        )

    monkeypatch.setattr("cuecal.extract.extract", fake_extract)

    config_path = tmp_path / "config.toml"
    with open(config_path) as f:
        content = f.read()
    with open(config_path, "w") as f:
        f.write(content.replace("sources = []", 'sources = ["dummy"]'))

    assert cli.main(["run", "--once"]) == 0

    conn = db.connect(tmp_path / "state.db")

    # High confidence was written to sink and event_link recorded
    assert len(created_events) == 1
    link = conn.execute(
        "SELECT sink_event_id FROM event_link WHERE meeting_id = 'mtg_high'"
    ).fetchone()
    assert link is not None
    assert link[0] == "evt_mtg_high"

    # Low confidence was routed to pending table
    pending_items = db.list_pending(conn)
    assert len(pending_items) == 1
    p = pending_items[0]
    assert p["message_id"] == "msg_low"
    assert p["confidence"] == 0.6
    assert "low confidence" in p["reason"]
    assert p["source_snippet"] == "Low confidence text"
    cand_loaded = MeetingCandidate.from_json(p["candidate_json"])
    assert cand_loaded.title == "Low Conf Meeting"
    conn.close()


def test_cli_misses_empty(tmp_path, capsys):
    assert cli.main(["init"]) == 0
    capsys.readouterr()
    assert cli.main(["misses"]) == 0
    out = capsys.readouterr().out
    assert "no near-misses captured" in out


def test_cli_misses_displays_records(tmp_path, capsys):
    assert cli.main(["init"]) == 0
    capsys.readouterr()

    conn = db.connect(tmp_path / "state.db")
    db.record_near_miss(
        conn,
        source="slack",
        message_id="C01:1700000001",
        sender="alice",
        text="Are you free for a quick sync tomorrow?",
        score=0.35,
        reason="dropped by extractor",
    )
    conn.close()

    assert cli.main(["misses"]) == 0
    out = capsys.readouterr().out
    assert "1 captured near-miss:" in out
    assert "[1] slack:C01:1700000001 (score: 0.35)" in out
    assert "Sender:   alice" in out
    assert "Snippet:  Are you free for a quick sync tomorrow?" in out


def test_cli_missed_flags_false_negative_into_dataset(tmp_path, monkeypatch, capsys):
    dataset_dir = tmp_path / "custom_dataset"
    monkeypatch.setenv("CUECAL_DATASET_DIR", str(dataset_dir))

    assert cli.main(["init"]) == 0
    capsys.readouterr()

    conn = db.connect(tmp_path / "state.db")
    db.record_near_miss(
        conn,
        source="gmail",
        message_id="msg_987",
        sender="partner@company.com",
        text="Let's meet at 3pm on Friday for project kickoff.",
        score=0.40,
    )
    conn.close()

    # Dry run
    assert cli.main(["--dry-run", "missed", "gmail", "msg_987"]) == 0
    out = capsys.readouterr().out
    assert "dry-run: would save missed invite fixture" in out
    assert not dataset_dir.exists()

    # Flag missed invite
    assert cli.main(["missed", "gmail", "msg_987"]) == 0
    out = capsys.readouterr().out
    assert "flagged missed invite gmail:msg_987" in out

    fixture_file = dataset_dir / "invites" / "missed-gmail-msg_987.json"
    assert fixture_file.exists()

    from cuecal.eval.schema import load_fixture
    fixture = load_fixture(fixture_file)
    assert fixture.id == "missed-gmail-msg_987"
    assert fixture.category == "invites"
    assert fixture.label == "new_invite"
    assert fixture.input.text == "Let's meet at 3pm on Friday for project kickoff."
    assert fixture.input.sender == "partner@company.com"
    assert fixture.metadata["feedback"] == "false_negative"
    assert fixture.metadata["source"] == "gmail"
    assert fixture.metadata["message_id"] == "msg_987"


def test_cli_run_captures_dropped_near_miss(tmp_path, monkeypatch):
    from datetime import datetime

    from cuecal.models import Message

    assert cli.main(["init"]) == 0

    class DummyChatSource:
        name = "dummy-chat"

        def fetch_since(self, cursor):
            msg = Message(
                id="msg_chat_1",
                source="dummy-chat",
                sender="colleague",
                ts=datetime.now(),
                text="Hey, can we schedule a quick call tomorrow afternoon?",
            )
            return [msg], "cursor_chat"

    def fake_registry_get(kind, name):
        if kind == "sources":
            return DummyChatSource
        raise KeyError(name)

    monkeypatch.setattr("cuecal.cli.registry.get", fake_registry_get)

    config_path = tmp_path / "config.toml"
    with open(config_path) as f:
        content = f.read()
    with open(config_path, "w") as f:
        f.write(content.replace("sources = []", 'sources = ["dummy-chat"]'))

    assert cli.main(["run", "--once"]) == 0

    conn = db.connect(tmp_path / "state.db")
    misses = db.list_near_misses(conn)
    assert len(misses) == 1
    m = misses[0]
    assert m["source"] == "dummy-chat"
    assert m["message_id"] == "msg_chat_1"
    assert m["sender"] == "colleague"
    assert m["score"] > 0.0
    assert "dropped by extractor" in m["reason"]
    conn.close()


def test_cli_run_fans_out_and_retries_failed_secondary(tmp_path, monkeypatch, capsys):
    from datetime import datetime

    from cuecal.models import MeetingCandidate, Message

    assert cli.main(["init"]) == 0
    capsys.readouterr()

    calls = []
    zoho_up = {"value": False}
    fetched = {"done": False}

    class DummySource:
        name = "dummy"

        def fetch_since(self, cursor):
            if fetched["done"]:
                return [], None
            fetched["done"] = True
            msg = Message(id="msg1", source="dummy", sender="t", ts=datetime.now(), text="x")
            return [msg], "cursor_next"

    class PrimarySink:
        name = "google-calendar"

        def create(self, candidate):
            calls.append(("google-calendar", candidate.meeting_id))
            return "gcal-evt"

    class ZohoSink:
        name = "zoho"

        def create(self, candidate):
            calls.append(("zoho", candidate.meeting_id))
            if not zoho_up["value"]:
                raise ConnectionError("zoho unreachable")
            return "zoho-evt"

    sinks = {"google-calendar": PrimarySink, "zoho": ZohoSink}

    def fake_registry_get(kind, name):
        if kind == "sources":
            return DummySource
        if kind == "sinks" and name in sinks:
            return sinks[name]
        raise KeyError(name)

    monkeypatch.setattr("cuecal.cli.registry.get", fake_registry_get)
    monkeypatch.setattr(
        "cuecal.extract.extract",
        lambda msg: MeetingCandidate(confidence=0.9, meeting_id="mtg1", title="Budget"),
    )

    config_path = tmp_path / "config.toml"
    content = config_path.read_text()
    content = content.replace("sources = []", 'sources = ["dummy"]')
    content = content.replace("secondary_sinks = []", 'secondary_sinks = ["zoho"]')
    config_path.write_text(content)

    # First run: primary succeeds, secondary fails; the run itself still succeeds.
    assert cli.main(["run", "--once"]) == 0
    assert calls == [("google-calendar", "mtg1"), ("zoho", "mtg1")]

    assert cli.main(["service", "status"]) == 0
    out = capsys.readouterr().out
    assert "(success)" in out
    assert "  [zoho] mtg1 (Budget)" in out
    assert "error: ConnectionError: zoho unreachable" in out

    # Next run retries the failed secondary without re-creating the primary event.
    zoho_up["value"] = True
    assert cli.main(["run", "--once"]) == 0
    assert calls == [("google-calendar", "mtg1"), ("zoho", "mtg1"), ("zoho", "mtg1")]

    conn = db.connect(tmp_path / "state.db")
    rows = {r["sink"]: r for r in db.list_sink_deliveries(conn)}
    assert rows["google-calendar"]["status"] == "synced"
    assert rows["zoho"]["status"] == "synced"
    assert rows["zoho"]["attempts"] == 2
    assert db.is_duplicate(conn, "mtg1", "zoho")
    conn.close()

    assert cli.main(["service", "status"]) == 0
    out = capsys.readouterr().out
    assert "failed sink deliveries" not in out
    assert "  zoho: 0 pending, 1 synced, 0 failed" in out


def test_cli_approve_fans_out_to_secondary(tmp_path, monkeypatch, capsys):
    from cuecal.models import MeetingCandidate

    assert cli.main(["init"]) == 0
    capsys.readouterr()

    created = []

    class Sink:
        def __init__(self, name):
            self.name = name

        def create(self, candidate):
            created.append(self.name)
            return f"{self.name}-evt"

    monkeypatch.setattr(
        "cuecal.cli.registry.get",
        lambda kind, name: Sink(name) if kind == "sinks" else None,
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        config_path.read_text().replace("secondary_sinks = []", 'secondary_sinks = ["zoho"]')
    )

    conn = db.connect(tmp_path / "state.db")
    pid = db.add_pending(
        conn, candidate=MeetingCandidate(title="Plan", confidence=0.6, meeting_id="m9")
    )
    conn.close()

    assert cli.main(["approve", str(pid)]) == 0
    assert "approved #1: created event google-calendar-evt (Plan)" in capsys.readouterr().out
    assert created == ["google-calendar", "zoho"]

    conn = db.connect(tmp_path / "state.db")
    rows = {r["sink"]: r["status"] for r in db.list_sink_deliveries(conn)}
    assert rows == {"google-calendar": "synced", "zoho": "synced"}
    conn.close()


