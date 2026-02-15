#!/usr/bin/env python3
"""
Valence Federation CLI - Node management and federation operations.

All commands use the Valence REST API via ValenceClient.

Commands:
  valence-federation discover <endpoint>     Discover and register a remote node
  valence-federation list                    List known federation nodes
  valence-federation status                  Show federation status
  valence-federation trust <node_id> <level> Set trust level for a node
  valence-federation sync <node_id>          Trigger sync with a node

Environment Variables:
  VALENCE_SERVER_URL    Valence server URL (default: http://127.0.0.1:8420)
  VALENCE_AUTH_TOKEN    Authentication token

Example:
  # Discover a remote node
  valence-federation discover https://valence.example.com

  # List active federation nodes
  valence-federation list --status active

  # Set trust level for a node
  valence-federation trust abc123-def456 elevated --reason "Trusted research partner"

  # Trigger sync with all active nodes
  valence-federation sync
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from .http_client import ValenceAPIError, ValenceClient, ValenceConnectionError, get_client

logger = logging.getLogger(__name__)


# =============================================================================
# COMMANDS
# =============================================================================


def cmd_discover(args: argparse.Namespace) -> int:
    """Discover and register a remote node."""
    client = get_client()
    endpoint = args.endpoint

    # Normalize endpoint
    if not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"
    endpoint = endpoint.rstrip("/")

    if not args.json:
        print(f"Discovering node at {endpoint}...")

    try:
        result = client.post(
            "/federation/nodes/discover",
            body={
                "url_or_did": endpoint,
                "auto_register": args.register,
            },
        )
    except ValenceConnectionError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    except ValenceAPIError as e:
        print(f"❌ Discovery failed: {e.message}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0

    if not result.get("success"):
        print(f"❌ Discovery failed: {result.get('error', 'Unknown error')}", file=sys.stderr)
        return 1

    node = result.get("node", result)
    did = node.get("did", "unknown")
    print(f"\n✅ Discovered node: {did}")

    if node.get("id"):
        print(f"   Node ID: {node['id']}")
    if node.get("status"):
        print(f"   Status: {node['status']}")

    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List known federation nodes."""
    client = get_client()

    params = {"limit": args.limit}
    if args.status:
        params["status"] = args.status
    if args.trust_phase:
        params["trust_phase"] = args.trust_phase

    try:
        result = client.get("/federation/nodes", params=params)
    except ValenceConnectionError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    except ValenceAPIError as e:
        print(f"❌ Error: {e.message}", file=sys.stderr)
        return 1

    if not result.get("success"):
        print(f"❌ Error: {result.get('error', 'Unknown error')}", file=sys.stderr)
        return 1

    nodes = result.get("nodes", [])

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0

    if not nodes:
        print("No federation nodes found.")
        return 0

    print(f"Federation Nodes ({len(nodes)}):\n")
    print(f"{'ID':<36}  {'DID':<40}  {'Status':<12}  {'Trust':<8}  {'Phase':<12}")
    print("-" * 120)

    for entry in nodes:
        node = entry.get("node", entry)
        trust = entry.get("trust", {})

        node_id = node.get("id", "?")[:36]
        did = node.get("did", "?")
        if len(did) > 40:
            did = did[:37] + "..."
        status = node.get("status", "?")
        trust_score = trust.get("trust", {}).get("overall", 0) if trust else 0
        phase = node.get("trust_phase", "?")

        print(f"{node_id}  {did:<40}  {status:<12}  {trust_score:>6.1%}  {phase:<12}")

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show federation status."""
    client = get_client()

    try:
        result = client.get("/federation/status")
    except ValenceConnectionError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    except ValenceAPIError as e:
        print(f"❌ Error: {e.message}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0

    # Human-readable output
    print("═══════════════════════════════════════════════════════════════")
    print("                     FEDERATION STATUS")
    print("═══════════════════════════════════════════════════════════════\n")

    nodes = result.get("nodes", {})
    total_nodes = nodes.get("total", 0)
    print(f"📡 Nodes: {total_nodes} total")
    for status, count in sorted(nodes.get("by_status", {}).items()):
        icon = {
            "active": "🟢",
            "discovered": "🔵",
            "connecting": "🟡",
            "suspended": "🟠",
            "unreachable": "🔴",
        }.get(status, "⚪")
        print(f"   {icon} {status}: {count}")

    sync = result.get("sync", {})
    print(f"\n🔄 Sync:")
    print(f"   Peers: {sync.get('peers', 0)}")
    print(f"   Beliefs sent: {sync.get('beliefs_sent', 0)}")
    print(f"   Beliefs received: {sync.get('beliefs_received', 0)}")
    if sync.get("last_sync"):
        print(f"   Last sync: {sync['last_sync']}")

    beliefs = result.get("beliefs", {})
    print(f"\n📚 Beliefs:")
    print(f"   Local: {beliefs.get('local', 0)}")
    print(f"   Federated: {beliefs.get('federated', 0)}")

    identity = result.get("identity", {})
    if identity.get("did") or identity.get("public_key"):
        print("\n🔑 Local Identity:")
        if identity.get("did"):
            print(f"   DID: {identity['did']}")
        if identity.get("public_key"):
            print(f"   Public Key: {identity['public_key'][:30]}...")

    print()
    return 0


def cmd_trust(args: argparse.Namespace) -> int:
    """Set trust level for a node."""
    client = get_client()
    node_id = args.node_id
    level = args.level

    valid_levels = ["blocked", "reduced", "automatic", "elevated", "anchor"]
    if level not in valid_levels:
        print(f"❌ Invalid trust level: {level}", file=sys.stderr)
        print(f"   Valid levels: {', '.join(valid_levels)}", file=sys.stderr)
        return 1

    try:
        # Get current trust first
        current = client.get(f"/federation/nodes/{node_id}/trust", params={"details": "true"})

        # Set new preference
        body = {"preference": level}
        if args.score is not None:
            body["manual_score"] = args.score
        if args.reason:
            body["reason"] = args.reason

        result = client.post(f"/federation/nodes/{node_id}/trust", body=body)

    except ValenceConnectionError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    except ValenceAPIError as e:
        if e.status_code == 404:
            print(f"❌ Node not found: {node_id}", file=sys.stderr)
        else:
            print(f"❌ Error: {e.message}", file=sys.stderr)
        return 1

    if not result.get("success"):
        print(f"❌ Error: {result.get('error', 'Unknown error')}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0

    print(f"✅ Trust preference updated for node {node_id}")
    print(f"   Previous: {current.get('effective_trust', 0):.1%}")
    print(f"   New level: {level}")
    print(f"   Effective trust: {result.get('effective_trust', 0):.1%}")
    if args.reason:
        print(f"   Reason: {args.reason}")

    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """Trigger sync with a node or all active nodes."""
    client = get_client()
    node_id = args.node_id

    if node_id:
        print(f"Triggering sync with node {node_id}...")
    else:
        print("Triggering sync with all active nodes...")

    try:
        body = {"node_id": node_id} if node_id else {}
        result = client.post("/federation/sync", body=body)

    except ValenceConnectionError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    except ValenceAPIError as e:
        print(f"❌ Sync failed: {e.message}", file=sys.stderr)
        return 1

    if not result.get("success"):
        print(f"❌ Sync failed: {result.get('error', 'Unknown error')}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0

    print("✅ Sync triggered")

    if result.get("queued_nodes"):
        print(f"   Queued nodes: {result['queued_nodes']}")
    if result.get("beliefs_queued"):
        print(f"   Beliefs queued: {result['beliefs_queued']}")

    # Poll for completion if --wait
    if args.wait:
        print("\nWaiting for sync to complete...")
        for _ in range(30):
            time.sleep(1)
            try:
                params = {"node_id": node_id} if node_id else {}
                status = client.get("/federation/sync", params=params)
                syncing = any(
                    s.get("status") == "syncing"
                    for s in status.get("sync_states", [])
                )
                if not syncing:
                    print("✅ Sync completed")
                    break
            except (ValenceConnectionError, ValenceAPIError):
                pass
        else:
            print("⚠️  Sync still in progress (timeout)")

    return 0


# =============================================================================
# CLI ENTRY POINT
# =============================================================================


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="valence-federation",
        description="Valence Federation CLI - Node management and federation operations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Discover a remote node
  valence-federation discover https://valence.example.com

  # List active nodes
  valence-federation list --status active

  # Show federation status
  valence-federation status

  # Set trust level
  valence-federation trust abc123-def456 elevated --reason "Trusted partner"

  # Trigger sync
  valence-federation sync

Environment Variables:
  VALENCE_SERVER_URL    Server URL (default: http://127.0.0.1:8420)
  VALENCE_AUTH_TOKEN    Authentication token
        """,
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--server",
        metavar="URL",
        help="Server URL (env: VALENCE_SERVER_URL)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # discover command
    discover_parser = subparsers.add_parser(
        "discover",
        help="Discover and register a remote node",
    )
    discover_parser.add_argument(
        "endpoint",
        help="Node URL (e.g., https://valence.example.com) or DID",
    )
    discover_parser.add_argument(
        "--register",
        "-r",
        action="store_true",
        default=True,
        help="Register the node after discovery (default: True)",
    )
    discover_parser.add_argument(
        "--no-register",
        action="store_false",
        dest="register",
        help="Don't register the node, just discover",
    )
    discover_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    # list command
    list_parser = subparsers.add_parser(
        "list",
        help="List known federation nodes",
    )
    list_parser.add_argument(
        "--status",
        "-s",
        choices=["discovered", "connecting", "active", "suspended", "unreachable"],
        help="Filter by node status",
    )
    list_parser.add_argument(
        "--trust-phase",
        "-t",
        choices=["observer", "contributor", "participant", "anchor"],
        help="Filter by trust phase",
    )
    list_parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=50,
        help="Maximum nodes to list (default: 50)",
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    # status command
    status_parser = subparsers.add_parser(
        "status",
        help="Show federation status",
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    # trust command
    trust_parser = subparsers.add_parser(
        "trust",
        help="Set trust level for a node",
    )
    trust_parser.add_argument(
        "node_id",
        help="Node UUID",
    )
    trust_parser.add_argument(
        "level",
        choices=["blocked", "reduced", "automatic", "elevated", "anchor"],
        help="Trust level to set",
    )
    trust_parser.add_argument(
        "--score",
        type=float,
        help="Manual trust score override (0.0 to 1.0)",
    )
    trust_parser.add_argument(
        "--reason",
        help="Reason for the trust preference",
    )
    trust_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    # sync command
    sync_parser = subparsers.add_parser(
        "sync",
        help="Trigger sync with a node or all active nodes",
    )
    sync_parser.add_argument(
        "node_id",
        nargs="?",
        help="Specific node UUID to sync with (syncs all if omitted)",
    )
    sync_parser.add_argument(
        "--wait",
        "-w",
        action="store_true",
        help="Wait for sync to complete",
    )
    sync_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    return parser


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "discover": cmd_discover,
        "list": cmd_list,
        "status": cmd_status,
        "trust": cmd_trust,
        "sync": cmd_sync,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)
    else:
        parser.print_help()
        return 0


# For CLI entry point
app = main


if __name__ == "__main__":
    sys.exit(main())
