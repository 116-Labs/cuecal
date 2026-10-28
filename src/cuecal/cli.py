"""Command line entry point. Subcommands other than init/doctor are stubs for later issues."""

from __future__ import annotations

import argparse
import dataclasses
import getpass
import json
import logging
import re
import sqlite3
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import (
    __version__,
    db,
    dedupe,
    google_auth,
    lock,
    log,
    notify,
    paths,
    registry,
    secrets,
    service,
)
from .config import (
    DEFAULT_CONFIG_TOML,
    Config,
    ConfigError,
    load_config,
    set_target_calendar,
    write_default_config,
)
from .extract.escalate import Escalator, paid_key_problem
from .models import MeetingCandidate
from .sinks import fanout
from .sinks.base import SinkCredentialsError
from .sinks.google import GoogleCalendarSink
from .sources.calendar import CalendarInfo, CalendarSource, reset_sync_cursors
from .sources.gmail import GmailNotAuthorizedError

logger = logging.getLogger("cuecal.cli")


def _not_implemented(name: str) -> int:
    print(f"cuecal {name}: not implemented yet", file=sys.stderr)
    return 2


def _google_sink(cfg: Config, cls: type[GoogleCalendarSink] = GoogleCalendarSink) -> Any:
    # Invites and mirrors share one calendar so dedupe sees both.
    return cls(calendar_id=cfg.mirror.target_calendar, secret_ref=cfg.secrets.get("google"))


def _sink(cfg: Config, name: str) -> Any:
    """Resolve a sink plugin; the Google sink is configured with the target calendar."""
    plugin = registry.get("sinks", name)
    if isinstance(plugin, type) and issubclass(plugin, GoogleCalendarSink):
        return _google_sink(cfg, plugin)
    return plugin


def _secondary_sinks(cfg: Config) -> dict[str, object | None]:
    """Resolve configured secondary sinks; an unregistered one maps to None and fails per write."""
    resolved: dict[str, object | None] = {}
    for name in cfg.secondary_sinks:
        try:
            resolved[name] = _sink(cfg, name)
        except KeyError:
            logger.warning("secondary sink %r not found; its writes are recorded as failed", name)
            resolved[name] = None
    return resolved


def _calendar_source(cfg: Config) -> CalendarSource:
    return CalendarSource(cfg.mirror, target=_google_sink(cfg))


def _sync_mirrors(conn: sqlite3.Connection, source: CalendarSource, *, dry_run: bool) -> None:
    for op in source.sync(conn, dry_run=dry_run):
        if dry_run:
            print(f"dry-run: would {op.describe()}")
        else:
            logger.info("mirror: %s", op.describe())


def _matches_sink_event(cand: MeetingCandidate, sink: Any | None) -> bool:
    # A sink with find_match patches its own match in create; the marker tier is left to create.
    if sink is None or hasattr(sink, "find_match"):
        return False
    # A sink that cannot be queried must not block the write: create reports its own errors.
    try:
        return dedupe.matches_nearby_event(cand, sink)
    except Exception as exc:  # noqa: BLE001
        logger.warning("sink dedupe lookup failed for %r: %s", cand.title, exc)
        return False


def _provision_conference(cfg: Config, sink_plugin: Any, event_id: str) -> None:
    """Add a Meet link to a just-created linkless event; the event exists, so never fatal.

    cuecal is always the organizer of what it creates, so the organizer guard proves nothing
    here: `organizer_only` is skipped and no provider link is replaced.
    """
    if cfg.conference.provision_for != "any_linkless":
        return
    conf = dataclasses.replace(cfg.conference, replace=[])
    try:
        sink = fanout.instantiate(sink_plugin)
        if not hasattr(sink, "provision_conference"):
            return
        sink.provision_conference(event_id, conf)
    except Exception as exc:  # noqa: BLE001 - the event is created; provisioning is best effort
        logger.warning("conference provisioning failed for event %s: %s", event_id, exc)


def _warn_unsupported_conference(cfg: Config) -> None:
    if cfg.conference.provision_for == "organizer_only":
        logger.warning(
            "conference provisioning for 'organizer_only' is not applied on cuecal run: "
            "cuecal creates events as organizer; only 'any_linkless' is supported"
        )
    if cfg.conference.replace:
        logger.warning(
            "conference link replacement (%s) is not applied on cuecal run: "
            "created events only receive links when linkless",
            ", ".join(cfg.conference.replace),
        )


def _queue_pending(
    conn: sqlite3.Connection,
    notifiers: list[Any],
    cand: MeetingCandidate,
    *,
    reason: str,
    snippet: str,
    source: str,
    message_id: str,
    dedupe_by_meeting_id: bool = False,
) -> None:
    """Queue and notify once for a message, even if it is replayed on a later pass."""
    source = source or cand.source_ref or ""
    existing = None
    if dedupe_by_meeting_id and cand.meeting_id:
        existing = db.find_pending_by_meeting_id(conn, cand.meeting_id)
    if dedupe_by_meeting_id and existing is None and cand.dedupe_key:
        existing = db.find_pending_by_dedupe_key(conn, cand.dedupe_key)
    if existing is None:
        existing = db.find_pending_by_message(conn, source=source, message_id=message_id)
    if existing is not None:
        logger.info(
            "candidate %r already queued (id: %d, status: %s); not queued again",
            cand.title,
            existing["id"],
            existing["status"],
        )
        return
    pending_id = db.add_pending(
        conn,
        candidate=cand,
        confidence=cand.confidence,
        reason=reason,
        source_snippet=snippet,
        source=source,
        message_id=message_id,
    )
    logger.info(
        "queued candidate %r to pending (id: %d, reason: %s)", cand.title, pending_id, reason
    )
    notify.notify_pending(notifiers, cand, snippet=snippet, pending_id=pending_id)


def _sync_secondaries(
    conn: sqlite3.Connection,
    notifiers: list[Any],
    cfg: Config,
    primary: Any,
    secondaries: dict[str, object | None],
    *,
    dry_run: bool,
) -> None:
    """Propagate primary-event edits and deletions to secondary copies (one-way)."""
    result = fanout.sync_secondaries(
        conn, primary_name=cfg.sink, primary=primary, secondaries=secondaries, dry_run=dry_run
    )
    for op in result.ops:
        if dry_run:
            print(f"dry-run: would {op.describe()}")
        else:
            logger.info("secondary sync: %s", op.describe())
    for failure in result.permission_failures:
        # The copy is one the user cannot edit there: a human has to decide what to do with it.
        _queue_pending(
            conn,
            notifiers,
            failure.candidate,
            reason=(
                f"{failure.sink} refused to update event {failure.sink_event_id}: "
                f"{failure.payload}"
            ),
            snippet=failure.payload[:200],
            source=f"sink:{failure.sink}",
            message_id=failure.sink_event_id,
            dedupe_by_meeting_id=False,
        )


def cmd_init(args: argparse.Namespace) -> int:
    path = paths.config_path()
    created = write_default_config(path, force=args.force)
    print(f"{'wrote' if created else 'kept existing'} config: {path}")
    conn = db.connect(paths.db_path())
    conn.close()
    print(f"state db ready: {paths.db_path()}")
    return 0


def cmd_auth(args: argparse.Namespace) -> int:
    if args.provider == "slack":
        token = getattr(args, "token", None)
        if not token:
            try:
                token = getpass.getpass("Slack user token (xoxp-...): ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nauth cancelled", file=sys.stderr)
                return 1
        if not token:
            print("error: token cannot be empty", file=sys.stderr)
            return 1
        secrets.set_secret("slack", token)
        print("stored slack token in keyring")
        return 0
    if args.provider == "google":
        return _auth_google(args)
    return _not_implemented(f"auth {args.provider}")


def _pick_calendar(cfg: Config, secret_ref: str) -> str | None:
    source = CalendarSource(cfg.mirror, target=GoogleCalendarSink(secret_ref=secret_ref))
    try:
        choices: list[CalendarInfo] = [c for c in source.list_calendars() if c.writable]
    except (OSError, SinkCredentialsError) as exc:
        print(f"error: cannot list your calendars ({exc}); pass --calendar ID", file=sys.stderr)
        return None
    if not choices:
        print("error: this Google account has no calendar you can write to", file=sys.stderr)
        return None
    print("Calendars you can write to:")
    for number, cal in enumerate(choices, 1):
        tag = " [primary]" if cal.primary else ""
        print(f"  {number}. {cal.summary or cal.id} ({cal.id}){tag}")
    while True:
        try:
            answer = input(f"Calendar for CueCal events [1-{len(choices)}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nauth cancelled", file=sys.stderr)
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            picked = choices[int(answer) - 1]
            return "primary" if picked.primary else picked.id
        print(f"enter a number from 1 to {len(choices)}")


def _auth_google(args: argparse.Namespace) -> int:
    path = paths.config_path()
    try:
        cfg = load_config(path) if path.exists() else Config()
        name = google_auth.secret_name(cfg.secrets)
        client = (
            google_auth.read_client_file(Path(args.client_json))
            if args.client_json
            else google_auth.stored_client_config(name)
        )
    except (ConfigError, google_auth.GoogleAuthError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(f"dry-run: would sign in to Google and store the result in keyring entry {name!r}")
        return 0

    # A running cuecal keeps the old target and would write back the mirror cursors that a
    # target switch resets.
    instance_lock = lock.SingleInstanceLock()
    if not instance_lock.acquire():
        print(
            "error: cuecal is running; stop it before `cuecal auth google`, then start it again",
            file=sys.stderr,
        )
        return 1
    try:
        return _sign_in_and_set_target(args, cfg, name, client, path)
    finally:
        instance_lock.release()


def _sign_in_and_set_target(
    args: argparse.Namespace, cfg: Config, name: str, client: dict[str, Any], path: Path
) -> int:
    try:
        creds = google_auth.sign_in(client)
    except google_auth.GoogleAuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    previous = secrets.get_secret(name)
    secrets.set_secret(name, creds.to_json())
    print(f"stored Google sign-in in keyring entry {name!r}")

    if not _set_target_calendar(args, cfg, name, path):
        # A new account paired with the old target could write invites to the wrong calendar.
        if previous is None:
            secrets.delete_secret(name)
        else:
            secrets.set_secret(name, previous)
        print("the new Google sign-in was not kept", file=sys.stderr)
        return 1
    return 0


def _set_target_calendar(args: argparse.Namespace, cfg: Config, name: str, path: Path) -> bool:
    calendar_id = args.calendar or _pick_calendar(cfg, name)
    if not calendar_id:
        return False
    try:
        current = path.read_text(encoding="utf-8") if path.exists() else DEFAULT_CONFIG_TOML
        text = set_target_calendar(current, calendar_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except (ConfigError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return False
    print(f"set mirror.target_calendar = {calendar_id!r} in {path}")
    if calendar_id != cfg.mirror.target_calendar:
        _restart_mirror_sync(cfg)
    return True


def _restart_mirror_sync(cfg: Config) -> None:
    # Incremental sync tokens would skip unedited in-window events on the new target.
    if paths.db_path().exists():
        conn = db.connect(paths.db_path())
        try:
            reset_sync_cursors(conn)
        finally:
            conn.close()
    if cfg.mirror.source_calendars:
        print(
            f"mirrors already on {cfg.mirror.target_calendar!r} stay there and stop updating; "
            "delete them in Google Calendar if you no longer want them"
        )


def cmd_run(args: argparse.Namespace) -> int:
    logger.info("run requested", extra={"once": args.once, "dry_run": args.dry_run})
    instance_lock = lock.SingleInstanceLock()
    if not instance_lock.acquire():
        logger.info("another cuecal instance is already running; exiting cleanly")
        return 0
    try:
        conn = db.connect(paths.db_path())
        run_id = db.record_run_start(conn)
        try:
            cfg = load_config(paths.config_path())
            _warn_unsupported_conference(cfg)
            from cuecal.extract import extract

            sink_plugin = None
            try:
                sink_plugin = _sink(cfg, cfg.sink)
            except KeyError:
                logger.warning("sink %r not found; skipping sink writes", cfg.sink)
            sink_inst = None
            if sink_plugin is not None:
                try:
                    sink_inst = fanout.instantiate(sink_plugin)
                except Exception as exc:  # noqa: BLE001 - deliver reports it per candidate
                    logger.warning("sink %r could not be initialised: %s", cfg.sink, exc)

            secondaries = _secondary_sinks(cfg)
            notifiers = notify.build_notifiers(cfg)
            escalator = Escalator.from_config(
                cfg, conn=conn, notifiers=notifiers, record=not args.dry_run
            )

            sources = []
            mirror_source = None
            for source_name in cfg.sources:
                if source_name == "calendar":
                    # Calendar events are structured: they bypass the extractor and the queue.
                    mirror_source = _calendar_source(cfg)
                elif source_name.startswith("mcp:") or source_name in ["zoho-mail", "zoho-cliq"]:
                    name = source_name.split(":", 1)[1] if ":" in source_name else source_name
                    from cuecal.sources.mcp import load_source

                    sources.append(
                        load_source(
                            name,
                            fetch_limit=cfg.fetch_limit,
                            latency_budget_seconds=cfg.latency_budget_seconds,
                        )
                    )
                else:
                    cls = registry.get("sources", source_name)
                    if source_name == "gmail":
                        sources.append(
                            cls(
                                secret_ref=cfg.secrets.get("google"),
                                query=cfg.gmail.query,
                                lookback_days=cfg.gmail.lookback_days,
                                fetch_limit=cfg.gmail.fetch_limit,
                                latency_budget_seconds=cfg.gmail.latency_budget_seconds,
                            )
                        )
                    elif source_name == "slack":
                        sources.append(
                            cls(
                                fetch_limit=cfg.fetch_limit,
                                latency_budget_seconds=cfg.latency_budget_seconds,
                            )
                        )
                    else:
                        sources.append(cls())

            sink_failures: list[str] = []
            auth_failures: list[str] = []
            while True:
                credentials_reported = False
                if secondaries and not args.dry_run:
                    fanout.retry_failed(conn, secondaries)

                if mirror_source is not None:
                    try:
                        _sync_mirrors(conn, mirror_source, dry_run=args.dry_run)
                    except SinkCredentialsError as exc:
                        logger.error("calendar mirroring skipped: %s", exc)
                        auth_failures.append(f"calendar: {exc}")

                for source in sources:
                    cursor = db.get_cursor(conn, source.name)
                    try:
                        messages, next_cursor = source.fetch_since(cursor)
                    except (google_auth.GoogleAuthError, GmailNotAuthorizedError) as exc:
                        logger.error("source %r skipped: %s", source.name, exc)
                        auth_failures.append(f"{source.name}: {exc}")
                        continue

                    for msg in messages:
                        if db.is_seen(conn, msg.source, msg.id):
                            continue
                        started = time.perf_counter()
                        cand = extract(msg)
                        extract_ms = (time.perf_counter() - started) * 1000
                        if not cand:
                            # Dropped candidate: record near-miss with score based on
                            # meeting signals
                            score = 0.0
                            text_lower = (msg.text or "").lower()
                            meeting_words = (
                                "meet",
                                "meeting",
                                "sync",
                                "call",
                                "chat",
                                "zoom",
                                "hangout",
                                "schedule",
                                "calendar",
                                "invite",
                                "catch up",
                                "talk",
                            )
                            matches = sum(1 for w in meeting_words if w in text_lower)
                            if matches > 0:
                                score = min(0.1 * matches, 0.49)
                            if not args.dry_run:
                                db.record_near_miss(
                                    conn,
                                    source=msg.source if hasattr(msg, "source") else source.name,
                                    message_id=msg.id if hasattr(msg, "id") else "",
                                    sender=msg.sender if hasattr(msg, "sender") else "",
                                    text=msg.text if hasattr(msg, "text") else "",
                                    score=score,
                                    confidence=0.0,
                                    reason="dropped by extractor (no link or template match)",
                                )
                                db.mark_seen(conn, msg.source, msg.id)
                            continue

                        outcome = escalator.process(msg, cand, base_latency_ms=extract_ms)
                        cand = outcome.candidate

                        is_linkless = False
                        if not cand.meeting_id:
                            is_linkless = True
                            cand.dedupe_key = dedupe.linkless_dedupe_key(
                                start=cand.start,
                                organizer=cand.organizer or getattr(msg, "sender", None),
                                title=cand.title,
                                source=getattr(msg, "source", ""),
                                message_id=getattr(msg, "id", ""),
                            )

                        # Check validation and confidence
                        is_valid = True
                        val_reason = None
                        if cand.start and cand.end and cand.end <= cand.start:
                            is_valid = False
                            val_reason = "end time must be after start time"

                        snippet = msg.text[:200] if hasattr(msg, "text") and msg.text else ""
                        source_name = msg.source if hasattr(msg, "source") else ""
                        message_id = msg.id if hasattr(msg, "id") else ""

                        if (
                            is_valid
                            and not is_linkless
                            and outcome.pending_reason is None
                            and cand.confidence >= cfg.auto_create_threshold
                        ):
                            if _matches_sink_event(cand, sink_inst):
                                logger.info(
                                    "skipped meeting %r from %s: matches a calendar event",
                                    cand.title,
                                    msg.source,
                                )
                                if not args.dry_run:
                                    db.mark_seen(conn, msg.source, msg.id)
                            elif args.dry_run:
                                logger.info("dry-run: would create event for %r", cand.title)
                            elif sink_plugin:
                                try:
                                    event_id = fanout.deliver(
                                        conn,
                                        cand,
                                        primary_name=cfg.sink,
                                        primary=sink_plugin,
                                        secondaries=secondaries,
                                    )
                                except Exception as exc:  # noqa: BLE001 - isolate each candidate write
                                    if isinstance(exc, SinkCredentialsError):
                                        error = str(exc)
                                        if not credentials_reported:
                                            logger.error("%s", exc)
                                            credentials_reported = True
                                    else:
                                        error = f"{type(exc).__name__}: {exc}"
                                        logger.error(
                                            "sink %r failed for %r: %s", cfg.sink, cand.title, error
                                        )
                                        logger.debug("sink failure traceback", exc_info=exc)
                                    sink_failures.append(error)
                                    _queue_pending(
                                        conn,
                                        notifiers,
                                        cand,
                                        reason=f"sink error: {error}",
                                        snippet=snippet,
                                        source=source_name,
                                        message_id=message_id,
                                        dedupe_by_meeting_id=True,
                                    )
                                else:
                                    logger.info("created event %r", event_id)
                                    _provision_conference(cfg, sink_plugin, event_id)
                                db.mark_seen(conn, msg.source, msg.id)
                        else:
                            if not is_valid:
                                reason = val_reason
                            elif is_linkless:
                                reason = "linkless invite"
                            elif outcome.pending_reason is not None:
                                reason = outcome.pending_reason
                            else:
                                reason = (
                                    f"low confidence ({cand.confidence:.2f} < "
                                    f"{cfg.auto_create_threshold:.2f})"
                                )
                            if args.dry_run:
                                logger.info(
                                    "dry-run: would add candidate %r to pending queue (%s)",
                                    cand.title,
                                    reason,
                                )
                            else:
                                _queue_pending(
                                    conn,
                                    notifiers,
                                    cand,
                                    reason=reason,
                                    snippet=snippet,
                                    source=source_name,
                                    message_id=message_id,
                                    dedupe_by_meeting_id=True,
                                )
                                db.mark_seen(conn, msg.source, msg.id)

                    if next_cursor and not args.dry_run:
                        db.set_cursor(conn, source.name, next_cursor)

                if secondaries and sink_plugin is not None:
                    _sync_secondaries(
                        conn, notifiers, cfg, sink_plugin, secondaries, dry_run=args.dry_run
                    )

                if args.once:
                    break

                logger.info("sleeping for %d seconds", cfg.poll_interval_seconds)
                time.sleep(cfg.poll_interval_seconds)

            errors = list(auth_failures)
            if sink_failures:
                errors.append(
                    f"{len(sink_failures)} candidate(s) queued after sink {cfg.sink!r} failed: "
                    f"{sink_failures[-1]}"
                )
            if errors:
                db.record_run_finish(conn, run_id, status="error", error="; ".join(errors))
                conn.close()
                return 1
            db.record_run_finish(conn, run_id, status="success")
            conn.close()
            return 0

        except Exception as exc:
            db.record_run_finish(conn, run_id, status="error", error=str(exc))
            conn.close()
            raise
    finally:
        instance_lock.release()


def cmd_pending(args: argparse.Namespace) -> int:
    conn = db.connect(paths.db_path())
    try:
        items = db.list_pending(conn, status="pending")
        if not items:
            print("no pending candidates")
            return 0

        print(f"{len(items)} pending candidate{'s' if len(items) != 1 else ''}:\n")
        for item in items:
            cand = MeetingCandidate.from_json(item["candidate_json"])
            print(f"[{item['id']}] {cand.title}")
            if item.get("confidence") is not None:
                print(f"  Confidence: {item['confidence']:.2f}")
            if item.get("reason"):
                print(f"  Reason:     {item['reason']}")
            start_str = cand.start.strftime("%Y-%m-%d %H:%M %Z") if cand.start else "n/a"
            end_str = cand.end.strftime("%Y-%m-%d %H:%M %Z") if cand.end else "n/a"
            if cand.start:
                print(f"  Time:       {start_str} - {end_str}")
            if cand.join_url:
                print(f"  Join URL:   {cand.join_url}")
            if cand.meeting_id:
                print(f"  Meeting ID: {cand.meeting_id}")
            if item.get("source"):
                print(f"  Source:     {item['source']}")
            if item.get("source_snippet"):
                snippet = item["source_snippet"].strip().replace("\n", " ")
                if len(snippet) > 80:
                    snippet = snippet[:77] + "..."
                print(f"  Snippet:    {snippet}")
            print()
        return 0
    finally:
        conn.close()


def cmd_approve(args: argparse.Namespace) -> int:
    conn = db.connect(paths.db_path())
    try:
        item = db.get_pending(conn, args.id)
        if not item or item.get("status") != "pending":
            print(f"error: pending candidate #{args.id} not found", file=sys.stderr)
            return 1

        cand = MeetingCandidate.from_json(item["candidate_json"])
        cfg = load_config(paths.config_path())

        if args.dry_run:
            print(f"dry-run: would approve #{args.id} and create event for {cand.title!r}")
            return 0

        sink_plugin = None
        try:
            sink_plugin = _sink(cfg, cfg.sink)
        except KeyError:
            print(f"error: sink {cfg.sink!r} not found", file=sys.stderr)
            return 1

        sink_inst = fanout.instantiate(sink_plugin)
        if not hasattr(sink_inst, "create") and not hasattr(sink_inst, "create_event"):
            print(f"error: sink {cfg.sink!r} has no create method", file=sys.stderr)
            return 1

        event_id = fanout.deliver(
            conn,
            cand,
            primary_name=cfg.sink,
            primary=sink_inst,
            secondaries=_secondary_sinks(cfg),
        )
        _provision_conference(cfg, sink_plugin, event_id)

        db.approve_pending(conn, args.id)
        print(f"approved #{args.id}: created event {event_id} ({cand.title})")
        return 0
    finally:
        conn.close()


def cmd_reject(args: argparse.Namespace) -> int:
    conn = db.connect(paths.db_path())
    try:
        item = db.get_pending(conn, args.id)
        if not item or item.get("status") != "pending":
            print(f"error: pending candidate #{args.id} not found", file=sys.stderr)
            return 1

        cand = MeetingCandidate.from_json(item["candidate_json"])
        if args.dry_run:
            print(f"dry-run: would reject candidate #{args.id}")
            return 0

        db.reject_pending(conn, args.id)
        print(f"rejected #{args.id}: {cand.title}")
        return 0
    finally:
        conn.close()


def cmd_edit(args: argparse.Namespace) -> int:
    conn = db.connect(paths.db_path())
    try:
        item = db.get_pending(conn, args.id)
        if not item or item.get("status") != "pending":
            print(f"error: pending candidate #{args.id} not found", file=sys.stderr)
            return 1

        cand = MeetingCandidate.from_json(item["candidate_json"])

        from dateutil import parser as dateparser

        has_flags = any(
            [
                getattr(args, "title", None) is not None,
                getattr(args, "start", None) is not None,
                getattr(args, "end", None) is not None,
                getattr(args, "tz", None) is not None,
                getattr(args, "join_url", None) is not None,
                getattr(args, "meeting_id", None) is not None,
                getattr(args, "passcode", None) is not None,
                getattr(args, "attendees", None) is not None,
            ]
        )

        if has_flags:
            if getattr(args, "title", None) is not None:
                cand.title = args.title
            if getattr(args, "start", None) is not None:
                cand.start = dateparser.parse(args.start) if args.start else None
            if getattr(args, "end", None) is not None:
                cand.end = dateparser.parse(args.end) if args.end else None
            if getattr(args, "tz", None) is not None:
                cand.tz = args.tz
            if getattr(args, "join_url", None) is not None:
                cand.join_url = args.join_url
            if getattr(args, "meeting_id", None) is not None:
                cand.meeting_id = args.meeting_id
            if getattr(args, "passcode", None) is not None:
                cand.passcode = args.passcode
            if getattr(args, "attendees", None) is not None:
                cand.attendees = [a.strip() for a in args.attendees.split(",") if a.strip()]
        else:
            try:
                t = input(f"Title [{cand.title}]: ").strip()
                if t:
                    cand.title = t

                s = input(f"Start [{cand.start.isoformat() if cand.start else ''}]: ").strip()
                if s:
                    cand.start = dateparser.parse(s)

                e = input(f"End [{cand.end.isoformat() if cand.end else ''}]: ").strip()
                if e:
                    cand.end = dateparser.parse(e)

                tz_val = input(f"Timezone [{cand.tz or ''}]: ").strip()
                if tz_val:
                    cand.tz = tz_val

                url = input(f"Join URL [{cand.join_url or ''}]: ").strip()
                if url:
                    cand.join_url = url

                mid = input(f"Meeting ID [{cand.meeting_id or ''}]: ").strip()
                if mid:
                    cand.meeting_id = mid

                pw = input(f"Passcode [{cand.passcode or ''}]: ").strip()
                if pw:
                    cand.passcode = pw

                att = input(f"Attendees [{', '.join(cand.attendees)}]: ").strip()
                if att:
                    cand.attendees = [a.strip() for a in att.split(",") if a.strip()]

                appr = input("Approve and write to calendar now? [y/N]: ").strip().lower()
                if appr in ("y", "yes"):
                    args.approve = True
            except (EOFError, KeyboardInterrupt):
                print("\nedit cancelled", file=sys.stderr)
                return 1

        if args.dry_run:
            print(f"dry-run: would update pending candidate #{args.id}")
            return 0

        db.update_pending(conn, args.id, candidate_json=cand.to_json())
        print(f"updated pending candidate #{args.id}")

        if getattr(args, "approve", False):
            cfg = load_config(paths.config_path())
            sink_plugin = None
            try:
                sink_plugin = _sink(cfg, cfg.sink)
            except KeyError:
                print(f"error: sink {cfg.sink!r} not found", file=sys.stderr)
                return 1

            sink_inst = fanout.instantiate(sink_plugin)
            if not hasattr(sink_inst, "create") and not hasattr(sink_inst, "create_event"):
                print(f"error: sink {cfg.sink!r} has no create method", file=sys.stderr)
                return 1

            event_id = fanout.deliver(
                conn,
                cand,
                primary_name=cfg.sink,
                primary=sink_inst,
                secondaries=_secondary_sinks(cfg),
            )
            _provision_conference(cfg, sink_plugin, event_id)

            db.approve_pending(conn, args.id)
            print(f"approved #{args.id}: created event {event_id} ({cand.title})")

        return 0
    finally:
        conn.close()


def cmd_service(args: argparse.Namespace) -> int:
    try:
        backend = service.BACKEND_LABELS[service.service_backend()]
        if args.action == "install":
            where = service.install_service()
            print(f"installed {backend} service: {where}")
            return 0
        if args.action == "uninstall":
            removed = service.uninstall_service()
            if removed:
                print(f"uninstalled {backend} service")
            else:
                print("service was not installed")
            return 0
        if args.action == "status":
            st = service.get_service_status()
            print(service.format_status(st))
            return 0
    except service.ServiceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return _not_implemented(f"service {args.action}")


def cmd_mirror(args: argparse.Namespace) -> int:
    cfg = load_config(paths.config_path())
    source = _calendar_source(cfg)
    if args.action == "calendars":
        targets = source.target_ids()
        for cal in source.list_calendars():
            tags = []
            if cal.primary:
                tags.append("primary")
            if cal.id.lower() in targets:
                tags.append("target")
            if cal.id in cfg.mirror.source_calendars:
                tags.append("source")
            if cal.free_busy_only:
                tags.append("free/busy only: cannot be mirrored")
            print(f"{cal.id}  {cal.summary}" + (f"  [{', '.join(tags)}]" if tags else ""))
        for cal_id, why in source.source_warnings().items():
            print(f"warning: source calendar {cal_id!r} {why}")
        return 0

    ops = source.prune(dry_run=args.dry_run)
    if not ops:
        print("no mirrors to prune")
    for op in ops:
        print(f"dry-run: would {op.describe()}" if args.dry_run else f"{op.describe()}: done")
    return 0


def cmd_misses(args: argparse.Namespace) -> int:
    conn = db.connect(paths.db_path())
    try:
        limit = getattr(args, "limit", 50)
        items = db.list_near_misses(conn, limit=limit)
        if not items:
            print("no near-misses captured")
            return 0

        print(f"{len(items)} captured near-miss{'es' if len(items) != 1 else ''}:\n")
        for item in items:
            raw_score = item.get("score")
            score = raw_score if raw_score is not None else item.get("confidence", 0.0)
            print(f"[{item['id']}] {item['source']}:{item['message_id']} (score: {score:.2f})")
            if item.get("sender"):
                print(f"  Sender:   {item['sender']}")
            if item.get("reason"):
                print(f"  Reason:   {item['reason']}")
            if item.get("text"):
                snippet = item["text"].strip().replace("\n", " ")
                if len(snippet) > 80:
                    snippet = snippet[:77] + "..."
                print(f"  Snippet:  {snippet}")
            if item.get("created_at"):
                print(f"  Captured: {item['created_at']}")
            print()
        return 0
    finally:
        conn.close()


def cmd_missed(args: argparse.Namespace) -> int:
    source = args.source
    msg_id = args.msg_id
    label = getattr(args, "label", "new_invite") or "new_invite"
    category = getattr(args, "category", "invites") or "invites"

    conn = db.connect(paths.db_path())
    try:
        near_miss = db.get_near_miss(conn, source, msg_id)

        text = getattr(args, "text", None)
        sender = getattr(args, "sender", None)
        ts_iso = None

        if near_miss:
            if not text:
                text = near_miss.get("text", "")
            if not sender:
                sender = near_miss.get("sender", "")
            ts_iso = near_miss.get("created_at")

        if not text:
            text = f"Missed invite from {source}:{msg_id}"

        if not sender:
            sender = "unknown@example.com"

        sanitized_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", f"missed-{source}-{msg_id}")

        from cuecal.eval.schema import EvalFixture, EvalFixtureInput, ExpectedOutput

        fixture = EvalFixture(
            id=sanitized_id,
            category=category,
            label=label,
            input=EvalFixtureInput(
                text=text,
                received_at=ts_iso or datetime.now(UTC).isoformat(),
                sender=sender,
            ),
            expected=ExpectedOutput(
                label=label,
            ),
            metadata={
                "source": source,
                "message_id": msg_id,
                "feedback": "false_negative",
                "flagged_at": datetime.now(UTC).isoformat(),
            },
        )

        dataset_path = paths.dataset_dir() / category
        fixture_file = dataset_path / f"{sanitized_id}.json"

        if args.dry_run:
            print(f"dry-run: would save missed invite fixture to {fixture_file}")
            return 0

        dataset_path.mkdir(parents=True, exist_ok=True)
        fixture_file.write_text(json.dumps(fixture.to_dict(), indent=2), encoding="utf-8")
        print(
            f"flagged missed invite {source}:{msg_id} -> saved to training dataset ({fixture_file})"
        )
        return 0
    finally:
        conn.close()


def _doctor_check_sink(cfg: Config, name: str) -> bool:
    """Print one sink credential status line and return whether it is ready."""
    try:
        plugin = _sink(cfg, name)
    except KeyError:
        print(f"sink {name}: not registered")
        return False
    try:
        sink = fanout.instantiate(plugin)
        check = getattr(sink, "check_credentials", None)
        if check is not None:
            check()
    except SinkCredentialsError as exc:
        print(f"sink {name}: {exc}")
        return False
    except Exception as exc:  # noqa: BLE001 - doctor reports bad plugin state without crashing
        print(f"sink {name}: credentials check failed ({exc})")
        return False
    # MCP-backed sinks confirm the server exposes their mapped write tools.
    validate = getattr(sink, "validate", None)
    if validate is not None:
        try:
            validate()
        except Exception as exc:  # noqa: BLE001 - doctor reports, not crashes
            print(f"sink {name}: tool check failed ({exc})")
            return False
    print(f"sink {name}: ok")
    return True


def cmd_doctor(args: argparse.Namespace) -> int:
    ok = True
    cfg_path = paths.config_path()
    print(f"config path: {cfg_path}")
    try:
        cfg = load_config(cfg_path)
        print("config: ok")
    except ConfigError as exc:
        ok = False
        print(f"config: {exc}")
        cfg = None

    if cfg:
        for source_name in cfg.sources:
            if source_name.startswith("mcp:") or source_name in ["zoho-mail", "zoho-cliq"]:
                # Try to validate mapping
                name = source_name.split(":", 1)[1] if ":" in source_name else source_name
                try:
                    from cuecal.sources.mcp import load_source

                    src = load_source(name)
                    try:
                        src.validate()
                        print(f"source {source_name}: ok")
                    except Exception as exc:
                        ok = False
                        print(f"source {source_name}: validation failed ({exc})")
                except Exception as exc:
                    ok = False
                    print(f"source {source_name}: mapping load failed ({exc})")
        for sink_name in (cfg.sink, *cfg.secondary_sinks):
            if not _doctor_check_sink(cfg, sink_name):
                ok = False
        if cfg.llm.paid is not None:
            problem = paid_key_problem(cfg)
            if problem:
                ok = False
                print(f"llm.paid: {problem}")
            else:
                print(f"llm.paid: ok ({cfg.llm.paid.provider} {cfg.llm.paid.model})")

    print(f"db path: {paths.db_path()}")
    try:
        print(f"keyring backend: {secrets.backend_name()}")
    except Exception as exc:  # noqa: BLE001 - doctor must report, not crash
        ok = False
        print(f"keyring backend: unavailable ({exc})")
    entry_point_errors = getattr(args, "entry_point_errors", None)
    if entry_point_errors is None:
        entry_point_errors = registry.load_entry_points()
    for kind, name, exc in entry_point_errors:
        ok = False
        print(f"broken plugin: {kind}/{name} ({exc!r})")
    for kind, names in registry.registered().items():
        print(f"{kind}: {', '.join(names) if names else '(none registered)'}")
    return 0 if ok else 1


def cmd_eval(args: argparse.Namespace) -> int:
    from cuecal.eval import FixtureValidationError, load_fixtures, runner

    try:
        runner.require_built_tier(args.tier)
        fixtures = load_fixtures(args.fixtures)
    except (runner.TierNotBuiltError, NotADirectoryError, FixtureValidationError) as exc:
        print(f"eval: {exc}", file=sys.stderr)
        return 1
    if not fixtures:
        print(f"eval: no fixtures found under {args.fixtures}", file=sys.stderr)
        return 1
    cfg = None
    # Tier 2 runs on built-in Ollama defaults when there is no config file yet.
    if args.tier >= 2 and paths.config_path().exists():
        try:
            cfg = load_config(paths.config_path())
        except ConfigError as exc:
            print(f"eval: {exc}", file=sys.stderr)
            return 1
    try:
        report = runner.evaluate(
            fixtures,
            tier=args.tier,
            provider=args.provider,
            model=args.model,
            llm=cfg.llm if cfg else None,
            secret_names=cfg.secrets if cfg else None,
        )
    except (runner.TierNotBuiltError, runner.EvalConfigError) as exc:
        print(f"eval: {exc}", file=sys.stderr)
        return 1
    render = runner.render_markdown if args.format == "markdown" else runner.render_table
    print(render(report))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cuecal", description="Meeting invites to calendar events."
    )
    parser.add_argument("--version", action="version", version=f"cuecal {__version__}")
    # Global flags are accepted before and after the subcommand. The subparser copies default to
    # SUPPRESS so they do not overwrite a value given before the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    for target, default in ((parser, False), (common, argparse.SUPPRESS)):
        target.add_argument(
            "--dry-run", action="store_true", default=default, help="never write to the sink"
        )
        target.add_argument(
            "-v", "--verbose", action="store_true", default=default, help="debug logging"
        )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    p = sub.add_parser("init", parents=[common], help="create the default config and state DB")
    p.add_argument("--force", action="store_true", help="overwrite an existing config")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("auth", parents=[common], help="store credentials for a provider")
    p.add_argument("provider", help="slack or google")
    p.add_argument("--token", help="slack: token to store directly instead of prompting")
    p.add_argument(
        "--client-json",
        metavar="PATH",
        help="google: Desktop app OAuth client JSON; omit to reuse the stored client",
    )
    p.add_argument(
        "--calendar", metavar="ID", help="google: calendar to write to, skipping the picker"
    )
    p.set_defaults(func=cmd_auth)

    p = sub.add_parser("run", parents=[common], help="poll sources and create events")
    p.add_argument("--once", action="store_true", help="run a single pass and exit")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("pending", parents=[common], help="review low-confidence candidates")
    p.set_defaults(func=cmd_pending)

    p = sub.add_parser("approve", parents=[common], help="approve a pending candidate")
    p.add_argument("id", type=int, help="id of the pending candidate")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("reject", parents=[common], help="reject a pending candidate")
    p.add_argument("id", type=int, help="id of the pending candidate")
    p.set_defaults(func=cmd_reject)

    p = sub.add_parser("edit", parents=[common], help="edit fields of a pending candidate")
    p.add_argument("id", type=int, help="id of the pending candidate")
    p.add_argument("--title", help="new title")
    p.add_argument("--start", help="new start time")
    p.add_argument("--end", help="new end time")
    p.add_argument("--tz", help="new timezone")
    p.add_argument("--join-url", help="new join URL")
    p.add_argument("--meeting-id", help="new meeting ID")
    p.add_argument("--passcode", help="new passcode")
    p.add_argument("--attendees", help="comma-separated attendee emails/names")
    p.add_argument("--approve", action="store_true", help="approve immediately after editing")
    p.set_defaults(func=cmd_edit)

    p = sub.add_parser(
        "misses", parents=[common], help="list captured near-misses with classification scores"
    )
    p.add_argument("--limit", type=int, default=50, help="maximum number of misses to display")
    p.set_defaults(func=cmd_misses)

    p = sub.add_parser(
        "missed", parents=[common], help="flag a missed invite to stage it for retraining"
    )
    p.add_argument("source", help="source name (gmail, slack, etc.)")
    p.add_argument("msg_id", help="message id")
    p.add_argument(
        "--label", default="new_invite", help="classification label (default: new_invite)"
    )
    p.add_argument("--category", default="invites", help="fixture category (default: invites)")
    p.add_argument("--text", help="override or provide message text")
    p.add_argument("--sender", help="override or provide sender email/name")
    p.set_defaults(func=cmd_missed)

    p = sub.add_parser(
        "mirror", parents=[common], help="list calendars to mirror, or prune unused mirrors"
    )
    p.add_argument(
        "action",
        choices=["calendars", "prune"],
        help="calendars: pick source/target IDs; prune: delete mirrors of removed sources",
    )
    p.set_defaults(func=cmd_mirror)

    p = sub.add_parser("service", parents=[common], help="manage the background service")
    p.add_argument("action", choices=["install", "uninstall", "status"])
    p.set_defaults(func=cmd_service)

    p = sub.add_parser("eval", parents=[common], help="benchmark extraction against fixtures")
    p.add_argument("--tier", type=int, choices=[1, 2, 3], default=1, help="extraction tier")
    p.add_argument("--provider", help="LLM provider (tiers 2-3)")
    p.add_argument("--model", help="LLM model (tiers 2-3)")
    p.add_argument("--fixtures", default="tests/fixtures/eval", help="fixture directory")
    p.add_argument("--format", choices=["table", "markdown"], default="table")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("doctor", parents=[common], help="report config, DB, keyring and plugins")
    p.set_defaults(func=cmd_doctor)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log.configure(args.verbose)
    # Sources and sinks advertised by installed packages must be available to every command,
    # not just doctor, before command dispatch resolves them by name.
    args.entry_point_errors = registry.load_entry_points()
    for kind, name, exc in args.entry_point_errors:
        logger.warning("failed to load %s plugin %r: %r", kind, name, exc)
    try:
        return args.func(args)
    except (google_auth.GoogleAuthError, SinkCredentialsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
