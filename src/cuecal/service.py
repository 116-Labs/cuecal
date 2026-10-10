"""Background service management for CueCal: launchd on macOS, Task Scheduler on Windows."""

from __future__ import annotations

import getpass
import json
import logging
import os
import plistlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from . import db, paths
from .config import load_config

logger = logging.getLogger("cuecal.service")

DEFAULT_LABEL = "com.cuecal.agent"
DEFAULT_INTERVAL_SECONDS = 600  # 10 minutes
TASK_NAME = "CueCal"

BACKEND_LABELS = {"launchd": "launchd", "task-scheduler": "Task Scheduler"}


class ServiceError(RuntimeError):
    """The platform's service manager refused or failed an operation."""


class UnsupportedPlatformError(ServiceError):
    """No background service backend exists for this platform."""


def _platform() -> str:
    return sys.platform


def service_backend() -> str:
    """Return the service backend for this platform: ``launchd`` or ``task-scheduler``."""
    plat = _platform()
    if plat == "darwin":
        return "launchd"
    if plat == "win32":
        return "task-scheduler"
    raise UnsupportedPlatformError(
        f"the background service is not supported on {plat} "
        "(supported: macOS via launchd, Windows via Task Scheduler)"
    )


def resolve_executable(name: str = "cuecal") -> str:
    """Resolve the absolute path to the installed cuecal executable."""
    override = os.environ.get("CUECAL_BIN")
    if override:
        return str(Path(override).expanduser().resolve())

    # 1. Look up in PATH (resolves uv tool or pipx shim)
    found = shutil.which(name)
    if found:
        return str(Path(found).expanduser().resolve())

    # 2. Look up standard uv tool path (~/.local/bin/cuecal, or cuecal.exe on Windows)
    uv_tool_dir = Path.home() / ".local" / "bin"
    for candidate in (uv_tool_dir / name, uv_tool_dir / f"{name}.exe"):
        if candidate.exists():
            return str(candidate.resolve())

    # 3. If running directly via python CLI entrypoint
    if sys.argv and Path(sys.argv[0]).stem == name:
        return str(Path(sys.argv[0]).expanduser().resolve())

    return sys.executable


def _resolve_interval(interval_seconds: int | None) -> int:
    if interval_seconds is not None:
        return interval_seconds
    try:
        return load_config(paths.config_path()).poll_interval_seconds
    except Exception:
        return DEFAULT_INTERVAL_SECONDS


def generate_launchd_plist(
    *,
    executable: str,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    log_dir: Path | None = None,
    label: str = DEFAULT_LABEL,
) -> bytes:
    """Generate launchd XML plist content for running cuecal periodically."""
    log_d = log_dir or paths.log_dir()
    stdout_path = str(log_d / "cuecal.stdout.log")
    stderr_path = str(log_d / "cuecal.stderr.log")

    plist_data: dict[str, Any] = {
        "Label": label,
        "ProgramArguments": [executable, "run", "--once"],
        "StartInterval": interval_seconds,
        "StandardOutPath": stdout_path,
        "StandardErrorPath": stderr_path,
        "RunAtLoad": True,
    }
    return plistlib.dumps(plist_data, fmt=plistlib.FMT_XML)


def install_launchd(
    *,
    plist_path: Path | None = None,
    executable: str | None = None,
    interval_seconds: int | None = None,
    log_dir: Path | None = None,
) -> Path:
    """Write and load the launchd agent plist."""
    target_plist = plist_path or paths.launchd_plist_path()
    target_plist.parent.mkdir(parents=True, exist_ok=True)

    target_log_dir = log_dir or paths.log_dir()
    target_log_dir.mkdir(parents=True, exist_ok=True)

    exe = executable or resolve_executable()
    interval_seconds = _resolve_interval(interval_seconds)

    if sys.platform == "darwin" and target_plist.exists() and shutil.which("launchctl"):
        subprocess.run(
            ["launchctl", "unload", str(target_plist)],
            check=False,
            capture_output=True,
        )

    plist_bytes = generate_launchd_plist(
        executable=exe,
        interval_seconds=interval_seconds,
        log_dir=target_log_dir,
    )
    target_plist.write_bytes(plist_bytes)

    if sys.platform == "darwin" and shutil.which("launchctl"):
        subprocess.run(
            ["launchctl", "load", str(target_plist)],
            check=False,
            capture_output=True,
        )

    return target_plist


def uninstall_launchd(*, plist_path: Path | None = None) -> bool:
    """Unload and remove the launchd agent plist."""
    target_plist = plist_path or paths.launchd_plist_path()
    if sys.platform == "darwin" and target_plist.exists() and shutil.which("launchctl"):
        subprocess.run(
            ["launchctl", "unload", str(target_plist)],
            check=False,
            capture_output=True,
        )

    if target_plist.exists():
        target_plist.unlink()
        return True
    return False


# --- Windows Task Scheduler -------------------------------------------------------------------

# Task Scheduler's "has not run yet" result (SCHED_S_TASK_HAS_NOT_RUN).
_TASK_HAS_NOT_RUN = 0x41303

# Read run info as JSON: Get-ScheduledTaskInfo's fields are not localized, unlike schtasks /Query
# output. A never-run task reports a 1999 sentinel time, filtered out here.
_TASK_INFO_SCRIPT = (
    "$i = Get-ScheduledTaskInfo -TaskName '{name}' -ErrorAction Stop; "
    "function f($d) {{ if ($d -and $d.Year -gt 2000) {{ $d.ToString('s') }} else {{ $null }} }}; "
    "[pscustomobject]@{{last_run = (f $i.LastRunTime); last_result = $i.LastTaskResult; "
    "next_run = (f $i.NextRunTime)}} | ConvertTo-Json -Compress"
)


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args, capture_output=True, text=True, errors="replace", check=False
        )
    except OSError as exc:
        raise ServiceError(f"{args[0]} failed: {exc}") from exc


def _task_user() -> str:
    """The installing user, as ``DOMAIN\\user`` when Windows reports a domain."""
    user = os.environ.get("USERNAME") or getpass.getuser()
    domain = os.environ.get("USERDOMAIN")
    return f"{domain}\\{user}" if domain else user


def _task_interval(interval_seconds: int) -> str:
    # Task Scheduler repeats in whole minutes, at least one.
    minutes = max(1, -(-interval_seconds // 60))
    return f"PT{minutes}M"


def task_action(*, executable: str, log_dir: Path) -> tuple[str, str]:
    """Return the task's (command, arguments): ``cuecal run --once`` with no console window.

    ``cuecal.exe`` is a console app, so a plain task flashes a window each run. ``conhost.exe
    --headless`` hosts it without one; ``cmd.exe`` appends stdout and stderr to the log dir.
    """
    stdout_path = log_dir / "cuecal.stdout.log"
    stderr_path = log_dir / "cuecal.stderr.log"
    command = r"%SystemRoot%\System32\conhost.exe"
    # cmd strips the outer pair of quotes after /c, leaving each path quoted.
    arguments = (
        f'--headless cmd.exe /d /c ""{executable}" run --once '
        f'1>>"{stdout_path}" 2>>"{stderr_path}""'
    )
    return command, arguments


def generate_task_xml(
    *,
    executable: str,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    log_dir: Path | None = None,
    user: str | None = None,
    start: datetime | None = None,
) -> str:
    """Generate the Task Scheduler definition for running cuecal periodically.

    The task runs as the installing user with an interactive logon only ("Run only when user is
    logged on"): the tokens live in that user's Credential Manager vault, which a non-interactive
    logon cannot read. It repeats every ``interval_seconds`` from logon, and from install time so
    the schedule starts without a fresh logon.
    """
    log_d = log_dir or paths.log_dir()
    user_id = escape(user or _task_user())
    start_boundary = (start or datetime.now()).replace(microsecond=0).isoformat()
    command, arguments = task_action(executable=executable, log_dir=log_d)
    repetition = (
        "      <Repetition>\n"
        f"        <Interval>{_task_interval(interval_seconds)}</Interval>\n"
        "        <StopAtDurationEnd>false</StopAtDurationEnd>\n"
        "      </Repetition>\n"
    )
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        "  <RegistrationInfo>\n"
        "    <Description>CueCal: cuecal run --once on a schedule.</Description>\n"
        "  </RegistrationInfo>\n"
        "  <Triggers>\n"
        "    <LogonTrigger>\n"
        f"{repetition}"
        "      <Enabled>true</Enabled>\n"
        f"      <UserId>{user_id}</UserId>\n"
        "    </LogonTrigger>\n"
        "    <TimeTrigger>\n"
        f"{repetition}"
        f"      <StartBoundary>{start_boundary}</StartBoundary>\n"
        "      <Enabled>true</Enabled>\n"
        "    </TimeTrigger>\n"
        "  </Triggers>\n"
        "  <Principals>\n"
        '    <Principal id="Author">\n'
        f"      <UserId>{user_id}</UserId>\n"
        "      <LogonType>InteractiveToken</LogonType>\n"
        "      <RunLevel>LeastPrivilege</RunLevel>\n"
        "    </Principal>\n"
        "  </Principals>\n"
        "  <Settings>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "    <StartWhenAvailable>true</StartWhenAvailable>\n"
        "    <Enabled>true</Enabled>\n"
        "    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>\n"
        "  </Settings>\n"
        '  <Actions Context="Author">\n'
        "    <Exec>\n"
        f"      <Command>{escape(command)}</Command>\n"
        f"      <Arguments>{escape(arguments)}</Arguments>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>\n"
    )


def install_task(
    *,
    executable: str | None = None,
    interval_seconds: int | None = None,
    log_dir: Path | None = None,
    task_name: str = TASK_NAME,
) -> str:
    """Register (or replace) the scheduled task. Returns the task name."""
    target_log_dir = log_dir or paths.log_dir()
    target_log_dir.mkdir(parents=True, exist_ok=True)

    task_xml = generate_task_xml(
        executable=executable or resolve_executable(),
        interval_seconds=_resolve_interval(interval_seconds),
        log_dir=target_log_dir,
    )
    with tempfile.TemporaryDirectory() as tmp:
        xml_path = Path(tmp) / "cuecal-task.xml"
        # schtasks reads the definition as UTF-16, as its encoding declaration says.
        xml_path.write_text(task_xml, encoding="utf-16")
        result = _run(["schtasks", "/Create", "/TN", task_name, "/XML", str(xml_path), "/F"])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ServiceError(f"schtasks /Create failed: {detail}")
    return task_name


def _task_registered(task_name: str) -> bool:
    return _run(["schtasks", "/Query", "/TN", task_name]).returncode == 0


def uninstall_task(*, task_name: str = TASK_NAME) -> bool:
    """Delete the scheduled task. Returns False when it was not registered."""
    if not _task_registered(task_name):
        return False
    result = _run(["schtasks", "/Delete", "/TN", task_name, "/F"])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ServiceError(f"schtasks /Delete failed: {detail}")
    return True


def _task_info(task_name: str) -> dict[str, Any]:
    script = _TASK_INFO_SCRIPT.format(name=task_name.replace("'", "''"))
    result = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script])
    if result.returncode != 0:
        return {}
    try:
        info = json.loads(result.stdout)
    except ValueError:
        return {}
    return info if isinstance(info, dict) else {}


def _task_status(task_name: str, log_dir: Path | None) -> dict[str, Any]:
    log_d = log_dir or paths.log_dir()
    installed = _task_registered(task_name)
    info = _task_info(task_name) if installed else {}
    last_result = info.get("last_result")
    if last_result == _TASK_HAS_NOT_RUN:
        last_result = None
    return {
        "backend": "task-scheduler",
        "installed": installed,
        "task_name": task_name,
        "task_last_run": info.get("last_run"),
        "task_last_result": last_result,
        "task_next_run": info.get("next_run"),
        "stdout_path": str(log_d / "cuecal.stdout.log"),
        "stderr_path": str(log_d / "cuecal.stderr.log"),
    }


def _launchd_status(plist_path: Path | None) -> dict[str, Any]:
    target_plist = plist_path or paths.launchd_plist_path()
    installed = target_plist.exists()
    plist_info: dict[str, Any] = {}
    if installed:
        try:
            plist_info = plistlib.loads(target_plist.read_bytes())
        except Exception:
            pass
    return {
        "backend": "launchd",
        "installed": installed,
        "plist_path": str(target_plist),
        "label": plist_info.get("Label", DEFAULT_LABEL),
        "interval_seconds": plist_info.get("StartInterval"),
        "stdout_path": plist_info.get("StandardOutPath"),
        "stderr_path": plist_info.get("StandardErrorPath"),
    }


# --- Platform dispatch ------------------------------------------------------------------------


def install_service(
    *,
    plist_path: Path | None = None,
    executable: str | None = None,
    interval_seconds: int | None = None,
    log_dir: Path | None = None,
    task_name: str = TASK_NAME,
) -> Path | str:
    """Install the service for this platform: the plist path (launchd) or task name (Windows)."""
    if service_backend() == "task-scheduler":
        return install_task(
            executable=executable,
            interval_seconds=interval_seconds,
            log_dir=log_dir,
            task_name=task_name,
        )
    return install_launchd(
        plist_path=plist_path,
        executable=executable,
        interval_seconds=interval_seconds,
        log_dir=log_dir,
    )


def uninstall_service(*, plist_path: Path | None = None, task_name: str = TASK_NAME) -> bool:
    """Remove the service for this platform. Returns False when it was not installed."""
    if service_backend() == "task-scheduler":
        return uninstall_task(task_name=task_name)
    return uninstall_launchd(plist_path=plist_path)


def get_service_status(
    *,
    conn: sqlite3.Connection | None = None,
    plist_path: Path | None = None,
    secondary_sinks: list[str] | None = None,
    task_name: str = TASK_NAME,
    log_dir: Path | None = None,
) -> dict[str, Any]:
    """Retrieve full service status including the service manager's state and run statistics.

    ``secondary_sinks`` (read from the config when omitted) decides which failed deliveries the
    next run retries; a failure for a sink no longer listed there is marked ``retried: False``.
    """
    if service_backend() == "task-scheduler":
        manager_status = _task_status(task_name, log_dir)
    else:
        manager_status = _launchd_status(plist_path)

    if secondary_sinks is None:
        try:
            secondary_sinks = load_config(paths.config_path()).secondary_sinks
        except Exception:
            secondary_sinks = None

    close_conn = False
    if conn is None:
        try:
            conn = db.connect(paths.db_path())
            close_conn = True
        except Exception:
            conn = None

    last_run = None
    last_error = None
    counts_source: dict[str, int] = {}
    counts_tier: dict[str, int] = {
        "regex": 0,
        "deterministic": 0,
        "local": 0,
        "paid": 0,
    }
    sink_deliveries: dict[str, dict[str, int]] = {}
    sink_failures: list[dict[str, Any]] = []

    if conn is not None:
        try:
            last_run = db.get_last_run(conn)
            last_error = db.get_last_error(conn)
            counts_source = db.get_counts_by_source(conn)
            counts_tier = db.get_counts_by_tier(conn)
            sink_deliveries = db.get_sink_delivery_counts(conn)
            sink_failures = db.list_sink_deliveries(conn, statuses=("failed",))
        finally:
            if close_conn:
                conn.close()

    for item in sink_failures:
        # None: config unreadable, so whether the next run retries this sink is unknown.
        item["retried"] = None if secondary_sinks is None else item["sink"] in secondary_sinks

    return {
        **manager_status,
        "last_run": last_run,
        "last_error": last_error,
        "counts_by_source": counts_source,
        "counts_by_tier": counts_tier,
        "sink_deliveries": sink_deliveries,
        "sink_failures": sink_failures,
    }


def _format_task_result(code: int) -> str:
    if code == 0:
        return "0 (success)"
    return f"0x{code & 0xFFFFFFFF:X}"


def _format_manager_status(status: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if status.get("backend") == "task-scheduler":
        if status["installed"]:
            lines.append("service: installed (Task Scheduler)")
            lines.append(f"task: {status['task_name']}")
            last = status.get("task_last_run")
            if last:
                result = status.get("task_last_result")
                suffix = f" (result {_format_task_result(result)})" if result is not None else ""
                lines.append(f"task last run: {last}{suffix}")
            else:
                lines.append("task last run: never")
            lines.append(f"task next run: {status.get('task_next_run') or 'none scheduled'}")
            lines.append(f"stdout: {status['stdout_path']}")
            lines.append(f"stderr: {status['stderr_path']}")
        else:
            lines.append("service: not installed (Task Scheduler)")
            lines.append(f"task: {status['task_name']} (missing)")
        return lines

    if status["installed"]:
        lines.append("service: installed (launchd)")
        lines.append(f"plist: {status['plist_path']}")
        if status.get("interval_seconds"):
            lines.append(f"interval: {status['interval_seconds']}s")
        if status.get("stdout_path"):
            lines.append(f"stdout: {status['stdout_path']}")
        if status.get("stderr_path"):
            lines.append(f"stderr: {status['stderr_path']}")
    else:
        lines.append("service: not installed (launchd)")
        lines.append(f"plist: {status['plist_path']} (missing)")
    return lines


def format_status(status: dict[str, Any]) -> str:
    """Format the service status dictionary for CLI output."""
    lines = _format_manager_status(status)

    lines.append("")
    last_run = status.get("last_run")
    if last_run:
        status_str = last_run.get("status", "unknown")
        started = last_run.get("started_at", "unknown")
        lines.append(f"last run: {started} ({status_str})")
    else:
        lines.append("last run: never")

    last_err = status.get("last_error")
    if last_err and last_err.get("error"):
        err_msg = last_err["error"]
        err_time = last_err.get("finished_at") or last_err.get("started_at") or ""
        lines.append(f"last error: {err_time} - {err_msg}")
    else:
        lines.append("last error: none")

    lines.append("")
    lines.append("counts by source:")
    sources = status.get("counts_by_source", {})
    if sources:
        for src, cnt in sorted(sources.items()):
            lines.append(f"  {src}: {cnt}")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("counts by tier:")
    tiers = status.get("counts_by_tier", {})
    for tier in ["regex", "deterministic", "local", "paid"]:
        lines.append(f"  {tier}: {tiers.get(tier, 0)}")

    lines.append("")
    lines.append("sink deliveries:")
    deliveries = status.get("sink_deliveries", {})
    if deliveries:
        for sink, by_status in sorted(deliveries.items()):
            parts = [f"{by_status.get(s, 0)} {s}" for s in db.SINK_DELIVERY_STATUSES]
            lines.append(f"  {sink}: {', '.join(parts)}")
    else:
        lines.append("  (none)")

    failures = status.get("sink_failures", [])
    if failures:
        lines.append("")
        lines.append(f"failed sink deliveries ({len(failures)}):")
        for item in failures:
            title = ""
            try:
                title = json.loads(item.get("candidate_json") or "{}").get("title") or ""
            except (ValueError, AttributeError):
                pass
            label = item.get("meeting_id") or f"delivery #{item['id']}"
            lines.append(f"  [{item['sink']}] {label}" + (f" ({title})" if title else ""))
            lines.append(
                f"    attempts: {item.get('attempts', 0)}, "
                f"last attempt: {item.get('last_attempt_at') or 'never'}"
            )
            lines.append(f"    error: {item.get('error_message') or 'unknown'}")
            if item.get("retried") is False:
                lines.append("    not retried: sink no longer configured in `secondary_sinks`")
        if any(item.get("retried") is not False for item in failures):
            lines.append(
                "  fix the sink's credentials or config (`cuecal doctor`); "
                "the next `cuecal run` retries each sink still listed in `secondary_sinks`"
            )

    return "\n".join(lines)
