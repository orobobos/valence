"""Belief management commands: init, add, query, list, verify-chains."""

from __future__ import annotations

import argparse
import json

from ..config import get_cli_config
from ..http_client import ValenceAPIError, ValenceConnectionError, get_client
from ..output import output_error, output_result


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register belief commands (init, add, query, list) on the CLI parser."""
    # init
    init_parser = subparsers.add_parser("init", help="Initialize database schema (apply all migrations)")
    init_parser.add_argument("--dry-run", action="store_true", help="Show what would be applied")
    init_parser.set_defaults(func=cmd_init)

    # add
    add_parser = subparsers.add_parser("add", help="Add a new belief")
    add_parser.add_argument("content", help="Belief content")
    add_parser.add_argument("--confidence", "-c", help="Confidence (JSON or float 0-1)")
    add_parser.add_argument("--domain", "-d", action="append", help="Domain tag (repeatable)")
    add_parser.add_argument(
        "--derivation-type",
        "-t",
        choices=[
            "observation",
            "inference",
            "aggregation",
            "hearsay",
            "assumption",
            "correction",
            "synthesis",
        ],
        default="observation",
        help="How this belief was derived",
    )
    add_parser.add_argument("--visibility", "-v", default="private", help="Visibility: private, federated, public")
    add_parser.set_defaults(func=cmd_add)

    # query
    query_parser = subparsers.add_parser("query", help="Search beliefs with multi-signal ranking")
    query_parser.add_argument("query", help="Search query")
    query_parser.add_argument("--limit", "-n", type=int, default=10, help="Max results")
    query_parser.add_argument("--domain", "-d", help="Filter by domain")
    query_parser.add_argument(
        "--recency-weight",
        "-r",
        type=float,
        default=None,
        help="Recency weight 0.0-1.0 (default 0.15). Higher = prefer newer beliefs",
    )
    query_parser.add_argument(
        "--min-confidence",
        "-c",
        type=float,
        default=None,
        help="Filter beliefs below this confidence threshold (0.0-1.0)",
    )
    query_parser.add_argument(
        "--explain",
        "-e",
        action="store_true",
        help="Show detailed score breakdown per result",
    )
    query_parser.add_argument("--include-archived", action="store_true", help="Include archived beliefs")
    query_parser.set_defaults(func=cmd_query)

    # list
    list_parser = subparsers.add_parser("list", help="List recent beliefs")
    list_parser.add_argument("--limit", "-n", type=int, default=10, help="Max results")
    list_parser.add_argument("--domain", "-d", help="Filter by domain")
    list_parser.set_defaults(func=cmd_list)

    # verify-chains
    verify_parser = subparsers.add_parser("verify-chains", help="Verify supersession chain integrity")
    verify_parser.set_defaults(func=cmd_verify_chains)


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize valence database via server migration endpoint."""
    client = get_client()
    try:
        dry_run = getattr(args, "dry_run", False)
        result = client.post("/admin/migrate/up", body={"dry_run": dry_run})
        output_result(result)
        return 0
    except ValenceConnectionError as e:
        output_error(str(e))
        return 1
    except ValenceAPIError as e:
        output_error(e.message)
        return 1


def cmd_add(args: argparse.Namespace) -> int:
    """Add a new belief via REST API."""
    content = args.content
    if not content:
        output_error("Content is required")
        return 1

    # Parse confidence
    confidence = None
    if args.confidence:
        try:
            parsed = json.loads(args.confidence)
            if isinstance(parsed, dict):
                confidence = parsed
            else:
                confidence = {"overall": float(parsed)}
        except (json.JSONDecodeError, TypeError, ValueError):
            try:
                confidence = {"overall": float(args.confidence)}
            except ValueError:
                output_error(f"Invalid confidence: {args.confidence}")
                return 1

    # Build request body
    body: dict = {"content": content}
    if confidence:
        body["confidence"] = confidence
    if args.domain:
        body["domain_path"] = args.domain
    if args.derivation_type:
        body["source_type"] = args.derivation_type
    if args.visibility:
        body["visibility"] = args.visibility

    client = get_client()
    try:
        result = client.post("/beliefs", body=body)
        output_result(result)
        return 0
    except ValenceConnectionError as e:
        output_error(str(e))
        return 1
    except ValenceAPIError as e:
        output_error(e.message)
        return 1


def cmd_query(args: argparse.Namespace) -> int:
    """Search beliefs via REST API."""
    config = get_cli_config()
    params: dict = {
        "query": args.query,
        "limit": str(args.limit),
        "output": config.output,
    }
    if args.domain:
        params["domain_filter"] = args.domain
    if getattr(args, "include_archived", False):
        params["include_archived"] = "true"

    # Build ranking config
    ranking: dict = {}
    if args.recency_weight is not None:
        ranking["recency_weight"] = args.recency_weight
    if args.min_confidence is not None:
        ranking["min_confidence"] = args.min_confidence
    if args.explain:
        ranking["explain"] = True
    if ranking:
        params["ranking"] = json.dumps(ranking)

    client = get_client()
    try:
        result = client.get("/beliefs", params=params)
        output_result(result)
        return 0
    except ValenceConnectionError as e:
        output_error(str(e))
        return 1
    except ValenceAPIError as e:
        output_error(e.message)
        return 1


def cmd_list(args: argparse.Namespace) -> int:
    """List recent beliefs via REST API."""
    config = get_cli_config()
    params: dict = {
        "query": "*",
        "limit": str(args.limit),
        "output": config.output,
    }
    if args.domain:
        params["domain_filter"] = args.domain

    client = get_client()
    try:
        result = client.get("/beliefs", params=params)
        output_result(result)
        return 0
    except ValenceConnectionError as e:
        output_error(str(e))
        return 1
    except ValenceAPIError as e:
        output_error(e.message)
        return 1


def cmd_verify_chains(args: argparse.Namespace) -> int:
    """Verify supersession chain integrity via REST API."""
    config = get_cli_config()
    params: dict = {"output": config.output}

    client = get_client()
    try:
        result = client.get("/admin/verify-chains", params=params)
        output_result(result)
        return 0
    except ValenceConnectionError as e:
        output_error(str(e))
        return 1
    except ValenceAPIError as e:
        output_error(e.message)
        return 1
