import pytest

from cuecal import __version__, cli, registry

SUBCOMMANDS = ["init", "auth", "run", "pending", "service", "doctor"]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CUECAL_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("CUECAL_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("CUECAL_LAUNCHD_PLIST", str(tmp_path / "com.cuecal.agent.plist"))
    monkeypatch.setenv("CUECAL_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("CUECAL_LOCK_PATH", str(tmp_path / "cuecal.lock"))
    monkeypatch.setattr(registry, "_registry", {kind: {} for kind in registry.KINDS})


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
    assert "sinks: ics" in out
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
    assert cli.main(["--dry-run", "pending"]) == 2
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
