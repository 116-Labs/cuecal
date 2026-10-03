import pytest

from cuecal import __version__, cli, registry

SUBCOMMANDS = ["init", "auth", "run", "pending", "service", "doctor"]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CUECAL_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("CUECAL_DB", str(tmp_path / "state.db"))
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
    assert "sources: (none registered)" in out


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
    assert cli.main(["run", "--once"]) == 2
    assert cli.main(["--dry-run", "pending"]) == 2
    assert cli.main(["service", "install"]) == 2
    assert cli.main(["auth", "slack"]) == 2
    assert "not implemented" in capsys.readouterr().err
