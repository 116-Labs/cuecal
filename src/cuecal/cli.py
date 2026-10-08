"""Command line entry point. Subcommands other than init/doctor are stubs for later issues."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime

from . import __version__, db, lock, log, notify, paths, registry, secrets, service
from .config import Config, ConfigError, load_config, write_default_config
from .models import MeetingCandidate
from .sinks import fanout
from .sources.calendar import CalendarSource

logger = logging.getLogger("cuecal.cli")


def _not_implemented(name: str) -> int:
    print(f"cuecal {name}: not implemented yet", file=sys.stderr)
    return 2


def _secondary_sinks(cfg: Config) -> dict[str, object | None]:
    """Resolve configured secondary sinks; an unregistered one maps to None and fails per write."""
    resolved: dict[str, object | None] = {}
    for name in cfg.secondary_sinks:
        try:
            resolved[name] = registry.get("sinks", name)
        except KeyError:
            logger.warning("secondary sink %r not found; its writes are recorded as failed", name)
            resolved[name] = None
    return resolved


def _calendar_source(cfg: Config) -> CalendarSource:
    return CalendarSource(cfg.mirror)


def _sync_mirrors(conn: sqlite3.Connection, source: CalendarSource, *, dry_run: bool) -> None:
    for op in source.sync(conn, dry_run=dry_run):
        if dry_run:
            print(f"dry-run: would {op.describe()}")
        else:
            logger.info("mirror: %s", op.describe())


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
                token = input("Slack user token (xoxp-...): ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nauth cancelled", file=sys.stderr)
                return 1
        if not token:
            print("error: token cannot be empty", file=sys.stderr)
            return 1
        secrets.set_secret("slack", token)
        print("stored slack token in keyring")
        return 0
    return _not_implemented(f"auth {args.provider}")


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
            from cuecal.extract import extract

            sink_plugin = None
            try:
                sink_plugin = registry.get("sinks", cfg.sink)
            except KeyError:
                logger.warning("sink %r not found; skipping sink writes", cfg.sink)

            secondaries = _secondary_sinks(cfg)
            notifiers = notify.build_notifiers(cfg)

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

            while True:
                if secondaries and not args.dry_run:
                    fanout.retry_failed(conn, secondaries)

                if mirror_source is not None:
                    _sync_mirrors(conn, mirror_source, dry_run=args.dry_run)

                for source in sources:
                    cursor = db.get_cursor(conn, source.name)
                    messages, next_cursor = source.fetch_since(cursor)

                    for msg in messages:
                        cand = extract(msg)
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
                            continue

                        if cand.meeting_id and db.is_duplicate(conn, cand.meeting_id, cfg.sink):
                            logger.info(
                                "skipped duplicate meeting %r from %s", cand.meeting_id, msg.source
                            )
                            continue

                        # Check validation and confidence
                        is_valid = True
                        val_reason = None
                        if cand.start and cand.end and cand.end <= cand.start:
                            is_valid = False
                            val_reason = "end time must be after start time"

                        snippet = msg.text[:200] if hasattr(msg, "text") and msg.text else ""

                        if is_valid and cand.confidence >= cfg.auto_create_threshold:
                            if args.dry_run:
                                logger.info("dry-run: would create event for %r", cand.title)
                            elif sink_plugin:
                                event_id = fanout.deliver(
                                    conn,
                                    cand,
                                    primary_name=cfg.sink,
                                    primary=sink_plugin,
                                    secondaries=secondaries,
                                )
                                logger.info("created event %r", event_id)
                        else:
                            reason = (
                                val_reason
                                if not is_valid
                                else (
                                    f"low confidence ({cand.confidence:.2f} < "
                                    f"{cfg.auto_create_threshold:.2f})"
                                )
                            )
                            if args.dry_run:
                                logger.info(
                                    "dry-run: would add candidate %r to pending queue (%s)",
                                    cand.title,
                                    reason,
                                )
                            else:
                                pending_id = db.add_pending(
                                    conn,
                                    candidate=cand,
                                    confidence=cand.confidence,
                                    reason=reason,
                                    source_snippet=snippet,
                                    source=msg.source if hasattr(msg, "source") else "",
                                    message_id=msg.id if hasattr(msg, "id") else "",
                                )
                                logger.info(
                                    "queued candidate %r to pending (id: %d, reason: %s)",
                                    cand.title,
                                    pending_id,
                                    reason,
                                )
                                notify.notify_pending(
                                    notifiers, cand, snippet=snippet, pending_id=pending_id
                                )

                    if next_cursor and not args.dry_run:
                        db.set_cursor(conn, source.name, next_cursor)

                if args.once:
                    break

                logger.info("sleeping for %d seconds", cfg.poll_interval_seconds)
                time.sleep(cfg.poll_interval_seconds)

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
            sink_plugin = registry.get("sinks", cfg.sink)
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
                sink_plugin = registry.get("sinks", cfg.sink)
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

            db.approve_pending(conn, args.id)
            print(f"approved #{args.id}: created event {event_id} ({cand.title})")

        return 0
    finally:
        conn.close()


def cmd_service(args: argparse.Namespace) -> int:
    if args.action == "install":
        plist = service.install_service()
        print(f"installed launchd service: {plist}")
        return 0
    if args.action == "uninstall":
        removed = service.uninstall_service()
        if removed:
            print("uninstalled launchd service")
        else:
            print("service was not installed")
        return 0
    if args.action == "status":
        st = service.get_service_status()
        print(service.format_status(st))
        return 0
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

    print(f"db path: {paths.db_path()}")
    try:
        print(f"keyring backend: {secrets.backend_name()}")
    except Exception as exc:  # noqa: BLE001 - doctor must report, not crash
        ok = False
        print(f"keyring backend: unavailable ({exc})")
    for kind, name, exc in registry.load_entry_points():
        ok = False
        print(f"broken plugin: {kind}/{name} ({exc!r})")
    for kind, names in registry.registered().items():
        print(f"{kind}: {', '.join(names) if names else '(none registered)'}")
    return 0 if ok else 1


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
    p.add_argument("provider")
    p.add_argument("--token", help="token to store directly instead of prompting")
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

    p = sub.add_parser("doctor", parents=[common], help="report config, DB, keyring and plugins")
    p.set_defaults(func=cmd_doctor)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log.configure(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
