"""Launchd background service management for CueCal."""

from __future__ import annotations

import logging
import os
import plistlib
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import db, paths
from .config import load_config

logger = logging.getLogger("cuecal.service")

DEFAULT_LABEL = "com.cuecal.agent"
DEFAULT_INTERVAL_SECONDS = 600  # 10 minutes


def resolve_executable(name: str = "cuecal") -> str:
    """Resolve the absolute path to the installed cuecal executable."""
    override = os.environ.get("CUECAL_BIN")
    if override:
        return str(Path(override).expanduser().resolve())

    # 1. Look up in PATH (resolves uv tool or pipx shim)
    found = shutil.which(name)
    if found:
        return str(Path(found).expanduser().resolve())

    # 2. Look up standard uv tool path (~/.local/bin/cuecal)
    uv_tool_bin = Path.home() / ".local" / "bin" / name
    if uv_tool_bin.exists():
        return str(uv_tool_bin.resolve())

    # 3. If running directly via python CLI entrypoint
    if sys.argv and Path(sys.argv[0]).stem == name:
        return str(Path(sys.argv[0]).expanduser().resolve())

    return sys.executable


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


def install_service(
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
    if interval_seconds is None:
        try:
            cfg = load_config(paths.config_path())
            interval_seconds = cfg.poll_interval_seconds
        except Exception:
            interval_seconds = DEFAULT_INTERVAL_SECONDS

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


def uninstall_service(*, plist_path: Path | None = None) -> bool:
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


def get_service_status(
    *,
    conn: sqlite3.Connection | None = None,
    plist_path: Path | None = None,
) -> dict[str, Any]:
    """Retrieve full service status including launchd state and run statistics."""
    target_plist = plist_path or paths.launchd_plist_path()
    installed = target_plist.exists()
    plist_info: dict[str, Any] = {}
    if installed:
        try:
            plist_info = plistlib.loads(target_plist.read_bytes())
        except Exception:
            pass

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

    if conn is not None:
        try:
            last_run = db.get_last_run(conn)
            last_error = db.get_last_error(conn)
            counts_source = db.get_counts_by_source(conn)
            counts_tier = db.get_counts_by_tier(conn)
        finally:
            if close_conn:
                conn.close()

    return {
        "installed": installed,
        "plist_path": str(target_plist),
        "label": plist_info.get("Label", DEFAULT_LABEL),
        "interval_seconds": plist_info.get("StartInterval"),
        "stdout_path": plist_info.get("StandardOutPath"),
        "stderr_path": plist_info.get("StandardErrorPath"),
        "last_run": last_run,
        "last_error": last_error,
        "counts_by_source": counts_source,
        "counts_by_tier": counts_tier,
    }


def format_status(status: dict[str, Any]) -> str:
    """Format the service status dictionary for CLI output."""
    lines: list[str] = []
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

    return "\n".join(lines)
