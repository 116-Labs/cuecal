"""Command line entry point. Subcommands other than init/doctor are stubs for later issues."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from . import __version__, db, log, paths, registry, secrets
from .config import ConfigError, load_config, write_default_config

logger = logging.getLogger("cuecal.cli")


def _not_implemented(name: str) -> int:
    print(f"cuecal {name}: not implemented yet", file=sys.stderr)
    return 2


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
    return _not_implemented("run")


def cmd_pending(args: argparse.Namespace) -> int:
    return _not_implemented("pending")


def cmd_service(args: argparse.Namespace) -> int:
    return _not_implemented(f"service {args.action}")


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

    p = sub.add_parser("service", parents=[common], help="install or remove the background service")
    p.add_argument("action", choices=["install", "uninstall"])
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
