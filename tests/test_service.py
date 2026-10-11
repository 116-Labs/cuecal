import plistlib
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from cuecal import db, service

TASK_NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


@pytest.fixture(autouse=True)
def launchd_platform(monkeypatch):
    # Default to the launchd backend; Windows tests switch to win32 with ``windows``.
    monkeypatch.setattr(service, "_platform", lambda: "darwin")


@pytest.fixture
def windows(monkeypatch):
    """Switch to the Task Scheduler backend with a fake ``subprocess.run``.

    ``calls`` records ``(args, task_xml)``, where ``task_xml`` is the definition file's content
    for ``schtasks /Create`` and None otherwise. ``state`` holds whether the task is registered and
    the JSON the PowerShell task-info query prints.
    """
    monkeypatch.setattr(service, "_platform", lambda: "win32")
    state = {"registered": False, "info": "{}"}
    calls = []

    def fake_run(args, **kwargs):
        task_xml = None
        rc = 0
        stdout = ""
        if args[:2] == ["schtasks", "/Create"]:
            task_xml = Path(args[args.index("/XML") + 1]).read_text(encoding="utf-16")
            state["registered"] = True
        elif args[:2] == ["schtasks", "/Delete"]:
            state["registered"] = False
        elif args[:2] == ["schtasks", "/Query"]:
            rc = 0 if state["registered"] else 1
        elif args[0] == "powershell.exe":
            stdout = state["info"]
        calls.append((args, task_xml))
        return subprocess.CompletedProcess(args, rc, stdout, "")

    monkeypatch.setattr(service.subprocess, "run", fake_run)
    return SimpleNamespace(calls=calls, state=state)


def test_generate_launchd_plist(tmp_path):
    log_dir = tmp_path / "logs"
    plist_bytes = service.generate_launchd_plist(
        executable="/usr/local/bin/cuecal",
        interval_seconds=600,
        log_dir=log_dir,
    )
    parsed = plistlib.loads(plist_bytes)
    assert parsed["Label"] == "com.cuecal.agent"
    assert parsed["ProgramArguments"] == ["/usr/local/bin/cuecal", "run", "--once"]
    assert parsed["StartInterval"] == 600
    assert parsed["StandardOutPath"] == str(log_dir / "cuecal.stdout.log")
    assert parsed["StandardErrorPath"] == str(log_dir / "cuecal.stderr.log")
    assert parsed["RunAtLoad"] is True


def test_resolve_executable(monkeypatch, tmp_path):
    custom_bin = tmp_path / "bin" / "cuecal"
    custom_bin.parent.mkdir(parents=True)
    custom_bin.touch()
    monkeypatch.setenv("CUECAL_BIN", str(custom_bin))
    assert service.resolve_executable() == str(custom_bin.resolve())


def test_install_and_uninstall_service(tmp_path):
    plist_path = tmp_path / "LaunchAgents" / "com.cuecal.agent.plist"
    log_dir = tmp_path / "logs"
    executable = str(tmp_path / "cuecal")

    # Install
    installed_path = service.install_service(
        plist_path=plist_path,
        executable=executable,
        interval_seconds=300,
        log_dir=log_dir,
    )
    assert installed_path == plist_path
    assert plist_path.exists()
    assert log_dir.exists()

    parsed = plistlib.loads(plist_path.read_bytes())
    assert parsed["StartInterval"] == 300
    assert parsed["ProgramArguments"] == [executable, "run", "--once"]

    # Uninstall
    removed = service.uninstall_service(plist_path=plist_path)
    assert removed is True
    assert not plist_path.exists()

    # Repeated uninstall returns False (no residue)
    removed_again = service.uninstall_service(plist_path=plist_path)
    assert removed_again is False


def test_service_status_not_installed(monkeypatch, tmp_path):
    plist_path = tmp_path / "com.cuecal.agent.plist"
    db_path = tmp_path / "state.db"
    conn = db.connect(db_path)
    conn.close()
    # Read the fresh DB, not the host user's real one.
    monkeypatch.setenv("CUECAL_DB", str(db_path))

    status = service.get_service_status(plist_path=plist_path)
    assert status["installed"] is False
    assert status["last_run"] is None
    assert status["last_error"] is None

    output = service.format_status(status)
    assert "service: not installed (launchd)" in output
    assert "last run: never" in output
    assert "last error: none" in output


def test_service_status_installed_with_stats(tmp_path):
    plist_path = tmp_path / "com.cuecal.agent.plist"
    log_dir = tmp_path / "logs"
    service.install_service(
        plist_path=plist_path,
        executable="/bin/cuecal",
        interval_seconds=600,
        log_dir=log_dir,
    )

    db_path = tmp_path / "state.db"
    conn = db.connect(db_path)
    # Add a successful run with source and tier stats
    run_id1 = db.record_run_start(conn, started_at="2026-10-03T12:00:00Z")
    db.record_run_finish(
        conn,
        run_id1,
        status="success",
        finished_at="2026-10-03T12:00:05Z",
        stats=[("source", "gmail", 3), ("tier", "regex", 3)],
    )
    # Add an error run
    run_id2 = db.record_run_start(conn, started_at="2026-10-03T12:10:00Z")
    db.record_run_finish(
        conn,
        run_id2,
        status="error",
        error="Network timeout",
        finished_at="2026-10-03T12:10:02Z",
    )

    status = service.get_service_status(conn=conn, plist_path=plist_path)
    assert status["installed"] is True
    assert status["interval_seconds"] == 600
    assert status["last_run"]["id"] == run_id2
    assert status["last_run"]["status"] == "error"
    assert status["last_error"]["error"] == "Network timeout"
    assert status["counts_by_source"].get("gmail") == 3
    assert status["counts_by_tier"].get("regex") == 3

    output = service.format_status(status)
    assert "service: installed (launchd)" in output
    assert "interval: 600s" in output
    assert "last run: 2026-10-03T12:10:00Z (error)" in output
    assert "last error: 2026-10-03T12:10:02Z - Network timeout" in output
    assert "gmail: 3" in output
    assert "regex: 3" in output
    assert "sink deliveries:\n  (none)" in output
    assert "failed sink deliveries" not in output

    conn.close()


def test_service_status_surfaces_failed_sink_deliveries(tmp_path):
    plist_path = tmp_path / "com.cuecal.agent.plist"
    conn = db.connect(tmp_path / "state.db")
    primary = db.add_sink_delivery(
        conn,
        sink="google-calendar",
        candidate_json='{"title": "Budget Sync"}',
        meeting_id="mtg1",
        role="primary",
    )
    db.record_sink_attempt(conn, primary, status="synced", sink_event_id="evt1")
    failed = db.add_sink_delivery(
        conn, sink="zoho", candidate_json='{"title": "Budget Sync"}', meeting_id="mtg1"
    )
    db.record_sink_attempt(
        conn,
        failed,
        status="failed",
        error_message="HTTPError: 401 Unauthorized",
        attempted_at="2026-10-07T09:00:00Z",
    )

    status = service.get_service_status(
        conn=conn, plist_path=plist_path, secondary_sinks=["zoho"]
    )
    assert status["sink_deliveries"] == {
        "google-calendar": {"synced": 1},
        "zoho": {"failed": 1},
    }
    assert [(f["sink"], f["retried"]) for f in status["sink_failures"]] == [("zoho", True)]

    output = service.format_status(status)
    assert "  google-calendar: 0 pending, 1 synced, 0 failed" in output
    assert "  zoho: 0 pending, 0 synced, 1 failed" in output
    assert "failed sink deliveries (1):" in output
    assert "  [zoho] mtg1 (Budget Sync)" in output
    assert "    attempts: 1, last attempt: 2026-10-07T09:00:00Z" in output
    assert "    error: HTTPError: 401 Unauthorized" in output
    assert "not retried" not in output
    assert "the next `cuecal run` retries each sink still listed in `secondary_sinks`" in output
    conn.close()


def test_service_status_marks_failures_for_unconfigured_sinks(tmp_path):
    plist_path = tmp_path / "com.cuecal.agent.plist"
    conn = db.connect(tmp_path / "state.db")
    failed = db.add_sink_delivery(
        conn, sink="zoho", candidate_json='{"title": "Budget Sync"}', meeting_id="mtg1"
    )
    db.record_sink_attempt(conn, failed, status="failed", error_message="HTTPError: 401")

    # zoho was removed from secondary_sinks: no run retries it, so no retry is promised.
    status = service.get_service_status(conn=conn, plist_path=plist_path, secondary_sinks=[])
    assert [(f["sink"], f["retried"]) for f in status["sink_failures"]] == [("zoho", False)]

    output = service.format_status(status)
    assert "  [zoho] mtg1 (Budget Sync)" in output
    assert "    not retried: sink no longer configured in `secondary_sinks`" in output
    assert "retries each sink" not in output
    conn.close()


def test_resolve_executable_finds_windows_uv_tool_exe(monkeypatch, tmp_path):
    exe = tmp_path / ".local" / "bin" / "cuecal.exe"
    exe.parent.mkdir(parents=True)
    exe.touch()
    monkeypatch.delenv("CUECAL_BIN", raising=False)
    monkeypatch.setattr(service.shutil, "which", lambda name: None)
    monkeypatch.setattr(service.Path, "home", classmethod(lambda cls: tmp_path))
    assert service.resolve_executable() == str(exe.resolve())


@pytest.mark.parametrize(
    ("plat", "backend"), [("darwin", "launchd"), ("win32", "task-scheduler")]
)
def test_service_backend_dispatches_by_platform(monkeypatch, plat, backend):
    monkeypatch.setattr(service, "_platform", lambda: plat)
    assert service.service_backend() == backend


def test_service_backend_rejects_other_platforms(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "_platform", lambda: "linux")
    with pytest.raises(service.UnsupportedPlatformError, match="not supported on linux"):
        service.service_backend()
    plist_path = tmp_path / "com.cuecal.agent.plist"
    with pytest.raises(service.UnsupportedPlatformError):
        service.install_service(plist_path=plist_path, executable="/bin/cuecal")
    assert not plist_path.exists()


def _task(task_xml):
    return ET.fromstring(task_xml.split("\n", 1)[1])


def test_generate_task_xml(tmp_path):
    log_dir = tmp_path / "Logs"
    exe = r"C:\Users\me\.local\bin\cuecal.exe"
    task = _task(
        service.generate_task_xml(
            executable=exe,
            interval_seconds=300,
            log_dir=log_dir,
            user=r"DESK\me",
            start=datetime(2026, 10, 10, 9, 0, 0, 123),
        )
    )

    principal = task.find("t:Principals/t:Principal", TASK_NS)
    assert principal.findtext("t:UserId", namespaces=TASK_NS) == r"DESK\me"
    assert principal.findtext("t:LogonType", namespaces=TASK_NS) == "InteractiveToken"
    assert principal.findtext("t:RunLevel", namespaces=TASK_NS) == "LeastPrivilege"

    logon = task.find("t:Triggers/t:LogonTrigger", TASK_NS)
    assert logon.findtext("t:UserId", namespaces=TASK_NS) == r"DESK\me"
    timed = task.find("t:Triggers/t:TimeTrigger", TASK_NS)
    assert timed.findtext("t:StartBoundary", namespaces=TASK_NS) == "2026-10-10T09:00:00"
    for trigger in (logon, timed):
        rep = trigger.find("t:Repetition", TASK_NS)
        assert rep.findtext("t:Interval", namespaces=TASK_NS) == "PT5M"
        # No Duration: the repetition runs indefinitely.
        assert rep.find("t:Duration", TASK_NS) is None

    settings = task.find("t:Settings", TASK_NS)
    assert settings.findtext("t:MultipleInstancesPolicy", namespaces=TASK_NS) == "IgnoreNew"

    action = task.find("t:Actions/t:Exec", TASK_NS)
    assert action.findtext("t:Command", namespaces=TASK_NS) == (
        r"%SystemRoot%\System32\conhost.exe"
    )
    stdout = log_dir / "cuecal.stdout.log"
    stderr = log_dir / "cuecal.stderr.log"
    assert action.findtext("t:Arguments", namespaces=TASK_NS) == (
        f'--headless cmd.exe /d /c ""{exe}" run --once 1>>"{stdout}" 2>>"{stderr}""'
    )


@pytest.mark.parametrize(("seconds", "interval"), [(30, "PT1M"), (60, "PT1M"), (90, "PT2M")])
def test_generate_task_xml_rounds_interval_up_to_minutes(seconds, interval):
    task = _task(service.generate_task_xml(executable="cuecal.exe", interval_seconds=seconds))
    rep = task.find("t:Triggers/t:LogonTrigger/t:Repetition", TASK_NS)
    assert rep.findtext("t:Interval", namespaces=TASK_NS) == interval


def test_generate_task_xml_defaults_to_installing_user(monkeypatch):
    monkeypatch.setenv("USERNAME", "me")
    monkeypatch.setenv("USERDOMAIN", "DESK")
    task = _task(service.generate_task_xml(executable="cuecal.exe"))
    assert task.findtext("t:Principals/t:Principal/t:UserId", namespaces=TASK_NS) == r"DESK\me"


def test_install_and_uninstall_task(windows, tmp_path):
    log_dir = tmp_path / "Logs"
    exe = r"C:\Users\me\.local\bin\cuecal.exe"

    assert service.install_service(executable=exe, interval_seconds=300, log_dir=log_dir) == (
        "CueCal"
    )
    assert log_dir.exists()
    create_args, task_xml = windows.calls[-1]
    assert create_args[:4] == ["schtasks", "/Create", "/TN", "CueCal"]
    assert create_args[-1] == "/F"
    task = _task(task_xml)
    assert task.findtext("t:Principals/t:Principal/t:LogonType", namespaces=TASK_NS) == (
        "InteractiveToken"
    )
    assert exe in task.findtext("t:Actions/t:Exec/t:Arguments", namespaces=TASK_NS)

    assert service.uninstall_service() is True
    assert windows.calls[-1][0] == ["schtasks", "/Delete", "/TN", "CueCal", "/F"]
    # Repeated uninstall finds no task and deletes nothing.
    assert service.uninstall_service() is False
    assert windows.calls[-1][0] == ["schtasks", "/Query", "/TN", "CueCal"]
    assert not any(args[0] == "launchctl" for args, _ in windows.calls)


def test_install_task_raises_on_schtasks_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "_platform", lambda: "win32")
    monkeypatch.setattr(
        service.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 1, "", "ERROR: Access is denied."),
    )
    with pytest.raises(service.ServiceError, match="Access is denied"):
        service.install_service(executable="cuecal.exe", log_dir=tmp_path)


def test_install_task_raises_when_schtasks_missing(monkeypatch, tmp_path):
    def missing(args, **kwargs):
        raise FileNotFoundError(args[0])

    monkeypatch.setattr(service, "_platform", lambda: "win32")
    monkeypatch.setattr(service.subprocess, "run", missing)
    with pytest.raises(service.ServiceError, match="schtasks failed"):
        service.install_service(executable="cuecal.exe", log_dir=tmp_path)


def test_task_status_not_installed(windows, tmp_path):
    conn = db.connect(tmp_path / "state.db")
    status = service.get_service_status(conn=conn, secondary_sinks=[])
    assert status["backend"] == "task-scheduler"
    assert status["installed"] is False
    assert not any(args[0] == "powershell.exe" for args, _ in windows.calls)

    output = service.format_status(status)
    assert "service: not installed (Task Scheduler)" in output
    assert "task: CueCal (missing)" in output
    assert "last run: never" in output
    conn.close()


def test_task_status_installed_reports_run_times(windows, tmp_path):
    windows.state["registered"] = True
    windows.state["info"] = (
        '{"last_run":"2026-10-10T09:05:00","last_result":0,"next_run":"2026-10-10T09:10:00"}'
    )
    conn = db.connect(tmp_path / "state.db")
    failed = db.add_sink_delivery(
        conn, sink="zoho", candidate_json='{"title": "Budget Sync"}', meeting_id="mtg1"
    )
    db.record_sink_attempt(conn, failed, status="failed", error_message="HTTPError: 401")

    status = service.get_service_status(
        conn=conn, secondary_sinks=["zoho"], log_dir=tmp_path / "Logs"
    )
    assert status["installed"] is True
    assert status["task_last_run"] == "2026-10-10T09:05:00"
    assert status["task_last_result"] == 0
    assert status["task_next_run"] == "2026-10-10T09:10:00"

    output = service.format_status(status)
    assert "service: installed (Task Scheduler)" in output
    assert "task: CueCal" in output
    assert "task last run: 2026-10-10T09:05:00 (result 0 (success))" in output
    assert "task next run: 2026-10-10T09:10:00" in output
    assert f"stdout: {tmp_path / 'Logs' / 'cuecal.stdout.log'}" in output
    # The secondary-sink failure section is kept.
    assert "failed sink deliveries (1):" in output
    assert "  [zoho] mtg1 (Budget Sync)" in output
    conn.close()


def test_task_status_failed_and_never_run_results(windows, tmp_path):
    conn = db.connect(tmp_path / "state.db")
    windows.state["registered"] = True
    windows.state["info"] = '{"last_run":"2026-10-10T09:05:00","last_result":-2147024891}'
    status = service.get_service_status(conn=conn, secondary_sinks=[])
    output = service.format_status(status)
    assert "task last run: 2026-10-10T09:05:00 (result 0x80070005)" in output
    assert "task next run: none scheduled" in output

    windows.state["info"] = '{"last_run":null,"last_result":267011,"next_run":null}'
    status = service.get_service_status(conn=conn, secondary_sinks=[])
    assert status["task_last_result"] is None
    assert "task last run: never" in service.format_status(status)
    conn.close()


def test_task_status_tolerates_unreadable_task_info(windows, tmp_path):
    conn = db.connect(tmp_path / "state.db")
    windows.state["registered"] = True
    windows.state["info"] = "not json"
    status = service.get_service_status(conn=conn, secondary_sinks=[])
    assert status["installed"] is True
    assert status["task_last_run"] is None
    assert status["task_info_error"] == "Get-ScheduledTaskInfo printed no JSON object"

    output = service.format_status(status)
    assert (
        "task last run: unknown (could not read task info: "
        "Get-ScheduledTaskInfo printed no JSON object)"
    ) in output
    assert "task next run: unknown" in output
    assert "task last run: never" not in output
    assert "none scheduled" not in output
    conn.close()


def test_task_status_reports_failed_task_info_query(monkeypatch, tmp_path):
    def fake_run(args, **kwargs):
        if args[0] == "powershell.exe":
            stderr = "Get-ScheduledTaskInfo : Access is denied.\r\nAt line:1 char:6\r\n"
            return subprocess.CompletedProcess(args, 1, "", stderr)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(service, "_platform", lambda: "win32")
    monkeypatch.setattr(service.subprocess, "run", fake_run)
    conn = db.connect(tmp_path / "state.db")
    status = service.get_service_status(conn=conn, secondary_sinks=[])
    assert status["installed"] is True
    output = service.format_status(status)
    assert (
        "task last run: unknown (could not read task info: "
        "Get-ScheduledTaskInfo failed: Get-ScheduledTaskInfo : Access is denied.)"
    ) in output
    assert "task next run: unknown" in output
    conn.close()


def test_task_status_reports_missing_powershell(monkeypatch, tmp_path):
    def fake_run(args, **kwargs):
        if args[0] == "powershell.exe":
            raise FileNotFoundError(args[0])
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(service, "_platform", lambda: "win32")
    monkeypatch.setattr(service.subprocess, "run", fake_run)
    conn = db.connect(tmp_path / "state.db")
    status = service.get_service_status(conn=conn, secondary_sinks=[])
    assert status["installed"] is True
    assert status["task_info_error"].startswith("powershell.exe failed:")
    assert "task next run: unknown" in service.format_status(status)
    conn.close()
