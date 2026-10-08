import plistlib

from cuecal import db, service


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


def test_service_status_not_installed(tmp_path):
    plist_path = tmp_path / "com.cuecal.agent.plist"
    db_path = tmp_path / "state.db"
    conn = db.connect(db_path)
    conn.close()

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
