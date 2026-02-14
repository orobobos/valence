"""Maintenance commands: retention, archive, compact, views, vacuum, all (#363)."""

from __future__ import annotations

import argparse

from ..config import get_cli_config
from ..http_client import ValenceAPIError, ValenceConnectionError, get_client
from ..output import output_error, output_result


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register maintenance command on the CLI parser."""
    maint_parser = subparsers.add_parser("maintenance", help="Run database maintenance operations")
    maint_parser.add_argument("--retention", action="store_true", help="Apply retention policies (delete old data)")
    maint_parser.add_argument("--archive", action="store_true", help="Archive stale superseded beliefs")
    maint_parser.add_argument("--tombstones", action="store_true", help="Clean up expired tombstones")
    maint_parser.add_argument("--compact", action="store_true", help="Compact exchanges in completed sessions")
    maint_parser.add_argument("--views", action="store_true", help="Refresh materialized views")
    maint_parser.add_argument("--vacuum", action="store_true", help="Run VACUUM ANALYZE on key tables")
    maint_parser.add_argument("--all", action="store_true", dest="run_all", help="Run full maintenance cycle")
    maint_parser.add_argument("--dry-run", action="store_true", help="Report what would happen without making changes")
    maint_parser.set_defaults(func=cmd_maintenance)


def cmd_maintenance(args: argparse.Namespace) -> int:
    """Run maintenance operations via REST API."""
    config = get_cli_config()

    # Build request body from flags
    body: dict = {}
    if args.run_all:
        body["all"] = True
    if args.retention:
        body["retention"] = True
    if args.archive:
        body["archive"] = True
    if args.tombstones:
        body["tombstones"] = True
    if args.compact:
        body["compact"] = True
    if args.views:
        body["views"] = True
    if args.vacuum:
        body["vacuum"] = True
    if args.dry_run:
        body["dry_run"] = True

    if not args.run_all and not any(getattr(args, op) for op in ("retention", "archive", "tombstones", "compact", "views", "vacuum")):
        print("No operation specified. Use --all for full cycle, or specify individual operations.")
        print("  --retention   Apply retention policies")
        print("  --archive     Archive stale beliefs")
        print("  --tombstones  Clean expired tombstones")
        print("  --compact     Compact exchanges in completed sessions")
        print("  --views       Refresh materialized views")
        print("  --vacuum      VACUUM ANALYZE key tables")
        print("  --all         Run all of the above in order")
        print("  --dry-run     Preview without changes")
        return 1

    params: dict = {"output": config.output}

    client = get_client()
    try:
        result = client.post("/admin/maintenance", body=body, params=params)
        output_result(result)
        return 0
    except ValenceConnectionError as e:
        output_error(str(e))
        return 1
    except ValenceAPIError as e:
        output_error(e.message)
        return 1
