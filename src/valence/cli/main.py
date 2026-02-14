#!/usr/bin/env python3
"""
Valence CLI - Personal knowledge substrate for AI agents.

Commands:
  valence init              Initialize database (creates schema)
  valence add <content>     Add a new belief
  valence query <text>      Search beliefs with derivation chains
  valence list              List recent beliefs
  valence conflicts         Detect contradicting beliefs
  valence stats             Show database statistics
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Re-export for backward compatibility (tests import from valence.cli.main)
from .commands import (
    COMMAND_MODULES,
    cmd_add,
    cmd_attestations,
    cmd_conflicts,
    cmd_discover,
    cmd_embeddings,
    cmd_export,
    cmd_identity,
    cmd_import,
    cmd_init,
    cmd_list,
    cmd_maintenance,
    cmd_migrate,
    cmd_peer,
    cmd_peer_add,
    cmd_peer_list,
    cmd_peer_remove,
    cmd_qos,
    cmd_query,
    cmd_query_federated,
    cmd_resources,
    cmd_schema,
    cmd_stats,
    cmd_trust,
    register_identity_commands,
)
from .config import CLIConfig, set_cli_config
from .utils import (
    compute_confidence_score,
    compute_recency_score,
    format_age,
    format_confidence,
    multi_signal_rank,
)

__all__ = [
    "app",
    "cmd_add",
    "cmd_attestations",
    "cmd_conflicts",
    "cmd_discover",
    "cmd_embeddings",
    "cmd_export",
    "cmd_identity",
    "cmd_import",
    "cmd_init",
    "cmd_list",
    "cmd_maintenance",
    "cmd_migrate",
    "cmd_peer",
    "cmd_peer_add",
    "cmd_peer_list",
    "cmd_peer_remove",
    "cmd_qos",
    "cmd_query",
    "cmd_query_federated",
    "cmd_resources",
    "cmd_schema",
    "cmd_stats",
    "cmd_trust",
    "compute_confidence_score",
    "compute_recency_score",
    "format_age",
    "format_confidence",
    "main",
    "multi_signal_rank",
    "register_identity_commands",
]

# Try to load .env from common locations
for env_path in [Path.cwd() / ".env", Path.home() / ".valence" / ".env"]:
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())
        break


def app() -> argparse.ArgumentParser:
    """Build the argument parser.

    Each command module in ``valence.cli.commands`` provides a
    ``register(subparsers)`` function that adds its parser(s) and sets
    ``parser.set_defaults(func=handler)`` so dispatch is automatic.
    """
    parser = argparse.ArgumentParser(
        prog="valence",
        description="Personal knowledge substrate for AI agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  valence query "search terms"            Search beliefs
  valence add "Fact here" -d tech         Add belief with domain
  valence list -n 20                      List recent beliefs
  valence stats                           Show statistics
  valence conflicts                       Detect contradictions

  valence --json stats                    Output as JSON
  valence --server http://host:8420 query Search remote server

Network:
  valence discover                        Discover network routers
  valence discover --seed <url>           Use custom seed

Federation:
  valence peer add <did> --trust 0.8      Add trusted peer
  valence peer list                       Show trusted peers
  valence export --to <did> -o file.json  Export beliefs for peer
  valence import file.json --from <did>   Import from peer
        """,
    )

    # Global flags for REST client mode
    parser.add_argument("--server", metavar="URL", help="Server URL (env: VALENCE_SERVER_URL, default: http://127.0.0.1:8420)")
    parser.add_argument("--token", metavar="TOKEN", help="Auth token (env: VALENCE_TOKEN)")
    parser.add_argument("--output", choices=["json", "text", "table"], help="Output format (env: VALENCE_OUTPUT, default: text)")
    parser.add_argument("--json", action="store_const", const="json", dest="output", help="Shorthand for --output json")
    parser.add_argument("--timeout", type=float, metavar="SECS", help="Request timeout in seconds (default: 30)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Let each command module register its own parsers
    for module in COMMAND_MODULES:
        module.register(subparsers)

    return parser


def main() -> int:
    """Main entry point."""
    parser = app()
    args = parser.parse_args()

    # Initialize CLI config from global flags (overrides env and file)
    config = CLIConfig.load(
        server_url=getattr(args, "server", None),
        token=getattr(args, "token", None),
        output=getattr(args, "output", None),
        timeout=getattr(args, "timeout", None),
    )
    set_cli_config(config)

    # Dispatch via the func default set by each command's register()
    handler = getattr(args, "func", None)
    if handler:
        return handler(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
