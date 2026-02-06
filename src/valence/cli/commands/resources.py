"""Resource sharing CLI commands.

Commands:
  valence resources list [--type prompt|config|pattern]
  valence resources share <file> --type prompt [--trust 0.5] [--name "My Prompt"]
  valence resources get <id>

Part of Issue #270: Resource sharing with trust gating.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID, uuid4


def cmd_resources(args: argparse.Namespace) -> int:
    """Dispatch resources subcommands."""
    subcmd = getattr(args, "resources_command", None)
    if subcmd == "list":
        return cmd_resources_list(args)
    elif subcmd == "share":
        return cmd_resources_share(args)
    elif subcmd == "get":
        return cmd_resources_get(args)
    else:
        print("Usage: valence resources {list|share|get}")
        return 1


def cmd_resources_list(args: argparse.Namespace) -> int:
    """List shared resources."""
    from ...core.resource_sharing import ResourceSharingService
    from ...core.resources import ResourceType

    service = ResourceSharingService()

    resource_type = None
    if hasattr(args, "type") and args.type:
        try:
            resource_type = ResourceType(args.type)
        except ValueError:
            print(f"❌ Invalid resource type: {args.type}")
            print(f"   Valid types: {', '.join(t.value for t in ResourceType)}")
            return 1

    limit = getattr(args, "limit", 50)
    resources = service.list_resources(resource_type=resource_type, limit=limit)

    if getattr(args, "json", False):
        print(json.dumps([r.to_dict() for r in resources], indent=2))
        return 0

    if not resources:
        print("📭 No resources found")
        return 0

    print(f"📦 Resources ({len(resources)})")
    print("─" * 60)
    for r in resources:
        status_icon = {
            "unreviewed": "⬜",
            "safe": "✅",
            "suspicious": "⚠️",
            "blocked": "🚫",
        }.get(r.safety_status.value, "❓")

        name = r.name or "(unnamed)"
        print(f"  {status_icon} {r.id}  [{r.type.value}]  {name}")
        if r.description:
            print(f"     {r.description[:80]}")
        print(f"     trust≥{r.trust_level_required:.1f}  uses={r.usage_count}  by {r.author_did}")
    print()
    return 0


def cmd_resources_share(args: argparse.Namespace) -> int:
    """Share a resource from a file."""
    from ...core.resource_sharing import ResourceSharingService
    from ...core.resources import Resource, ResourceType

    # Parse resource type
    try:
        resource_type = ResourceType(args.type)
    except ValueError:
        print(f"❌ Invalid resource type: {args.type}")
        print(f"   Valid types: {', '.join(t.value for t in ResourceType)}")
        return 1

    # Read content from file or stdin
    file_path = args.file
    if file_path == "-":
        content = sys.stdin.read()
    else:
        path = Path(file_path)
        if not path.exists():
            print(f"❌ File not found: {file_path}")
            return 1
        content = path.read_text()

    if not content.strip():
        print("❌ File is empty")
        return 1

    # Build resource
    author_did = getattr(args, "author", None) or "did:vkb:local"
    trust_level = getattr(args, "trust", 0.5)
    name = getattr(args, "name", None) or (Path(file_path).stem if file_path != "-" else None)

    resource = Resource(
        id=uuid4(),
        type=resource_type,
        content=content,
        author_did=author_did,
        name=name,
        description=getattr(args, "description", None),
        tags=getattr(args, "tag", None) or [],
    )

    service = ResourceSharingService()
    result = service.share_resource(resource, trust_level_required=trust_level)

    if result.shared:
        print(f"✅ Resource shared: {result.resource_id}")
        print(f"   Type: {resource_type.value}")
        print(f"   Trust required: {trust_level:.1f}")
        if name:
            print(f"   Name: {name}")
    else:
        print(f"❌ Sharing failed: {result.message}")
        if result.safety_scan.injection_matches:
            print(f"   ⚠️  Injection patterns: {result.safety_scan.injection_matches}")
        if result.safety_scan.exfil_matches:
            print(f"   ⚠️  Exfil patterns: {result.safety_scan.exfil_matches}")
        return 1

    return 0


def cmd_resources_get(args: argparse.Namespace) -> int:
    """Get a resource by ID."""
    from ...core.resource_sharing import ResourceSharingService

    try:
        resource_id = UUID(args.id)
    except ValueError:
        print(f"❌ Invalid UUID: {args.id}")
        return 1

    service = ResourceSharingService()
    requester_did = getattr(args, "requester", None) or "did:vkb:local"

    result = service.request_resource(resource_id, requester_did)

    if not result.granted or result.resource is None:
        print(f"❌ Access denied: {result.reason}")
        return 1

    r = result.resource

    if getattr(args, "json", False):
        print(json.dumps(r.to_dict(), indent=2))
        return 0

    print(f"📦 Resource: {r.id}")
    print(f"   Type: {r.type.value}")
    print(f"   Name: {r.name or '(unnamed)'}")
    print(f"   Author: {r.author_did}")
    print(f"   Safety: {r.safety_status.value}")
    print(f"   Trust required: {r.trust_level_required:.1f}")
    print(f"   Uses: {r.usage_count}")
    if r.success_rate is not None:
        print(f"   Success rate: {r.success_rate:.0%}")
    if r.description:
        print(f"   Description: {r.description}")
    if r.tags:
        print(f"   Tags: {', '.join(r.tags)}")
    print(f"\n{'─' * 60}")
    print(r.content)
    print(f"{'─' * 60}")

    return 0
