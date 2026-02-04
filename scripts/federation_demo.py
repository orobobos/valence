#!/usr/bin/env python3
"""Federation MVP Demo.

Demonstrates two Valence nodes discovering each other, exchanging beliefs,
and querying each other. This proves the interconnection thesis.

Usage:
    python3 scripts/federation_demo.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path for development
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

# Direct imports to avoid pulling in db dependencies through valence/__init__.py
# We import the specific modules we need from the federation package
import importlib.util

def load_module(name: str, path: Path):
    """Load a module directly without going through __init__.py."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

# Load federation modules directly
identity = load_module("valence.federation.identity", src_path / "valence/federation/identity.py")
peers = load_module("valence.federation.peers", src_path / "valence/federation/peers.py")
server = load_module("valence.federation.server", src_path / "valence/federation/server.py")

FederationNode = server.FederationNode

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def print_header(text: str) -> None:
    """Print a section header."""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60 + "\n")


def print_step(step: int, text: str) -> None:
    """Print a step description."""
    print(f"\n[Step {step}] {text}")
    print("-" * 40)


async def run_demo():
    """Run the federation demo."""
    print_header("Valence Federation MVP Demo")
    
    print("""
This demo creates two Valence nodes and demonstrates:
1. Node identity generation (ed25519 keypairs, DIDs)
2. Peer discovery (introduction handshake)
3. Belief sharing (signed beliefs with verification)
4. Cross-node queries (ask peer about topics)

Let's prove the interconnection thesis!
""")
    
    # =========================================================================
    # Step 1: Create two nodes
    # =========================================================================
    print_step(1, "Creating two federation nodes...")
    
    node_alice = FederationNode(name="Alice", port=8001)
    node_bob = FederationNode(name="Bob", port=8002)
    
    print(f"  Node Alice:")
    print(f"    DID: {node_alice.identity.did}")
    print(f"    Endpoint: {node_alice.endpoint}")
    print(f"    Public Key: {node_alice.identity.public_key_multibase[:20]}...")
    print()
    print(f"  Node Bob:")
    print(f"    DID: {node_bob.identity.did}")
    print(f"    Endpoint: {node_bob.endpoint}")
    print(f"    Public Key: {node_bob.identity.public_key_multibase[:20]}...")
    
    # =========================================================================
    # Step 2: Start the servers
    # =========================================================================
    print_step(2, "Starting federation servers...")
    
    # Start servers in background
    task_alice = node_alice.start_background()
    task_bob = node_bob.start_background()
    
    # Give servers time to start
    await asyncio.sleep(1)
    print("  ✓ Both servers running")
    
    # =========================================================================
    # Step 3: Exchange introductions
    # =========================================================================
    print_step(3, "Exchanging introductions...")
    
    # Alice introduces herself to Bob
    result = await node_alice.introduce_to(node_bob.endpoint)
    if result.get("success"):
        print(f"  ✓ Alice → Bob: Introduction accepted")
        print(f"    Bob says: \"{result.get('message')}\"")
    else:
        print(f"  ✗ Alice → Bob: {result.get('error')}")
        return
    
    # Bob introduces himself to Alice (bidirectional)
    result = await node_bob.introduce_to(node_alice.endpoint)
    if result.get("success"):
        print(f"  ✓ Bob → Alice: Introduction accepted")
        print(f"    Alice says: \"{result.get('message')}\"")
    else:
        print(f"  ✗ Bob → Alice: {result.get('error')}")
        return
    
    # Show peer lists
    print("\n  Peer registry:")
    print(f"    Alice knows: {[p.name for p in node_alice.peer_store.list_peers()]}")
    print(f"    Bob knows: {[p.name for p in node_bob.peer_store.list_peers()]}")
    
    # =========================================================================
    # Step 4: Alice shares beliefs with Bob
    # =========================================================================
    print_step(4, "Alice shares beliefs with Bob...")
    
    beliefs_to_share = [
        ("The best programming language is the one that gets the job done.", 0.9, ["tech", "philosophy"]),
        ("Coffee is essential for productive coding sessions.", 0.85, ["productivity", "wellness"]),
        ("Distributed systems are hard but worth the complexity.", 0.8, ["tech", "architecture"]),
    ]
    
    bob_did = node_bob.identity.did
    
    for content, confidence, domains in beliefs_to_share:
        result = await node_alice.share_belief(
            peer_did=bob_did,
            content=content,
            confidence=confidence,
            domains=domains,
        )
        if result.get("success"):
            print(f"  ✓ Shared: \"{content[:50]}...\"")
        else:
            print(f"  ✗ Failed: {result.get('error')}")
    
    # Show belief counts
    print(f"\n  Belief counts:")
    print(f"    Alice has {len(node_alice.beliefs)} beliefs")
    print(f"    Bob has {len(node_bob.beliefs)} beliefs (received from Alice)")
    
    # =========================================================================
    # Step 5: Bob shares beliefs with Alice
    # =========================================================================
    print_step(5, "Bob shares beliefs with Alice...")
    
    bob_beliefs = [
        ("Testing in production is fine if your monitoring is good enough.", 0.7, ["tech", "devops"]),
        ("Documentation is a love letter to your future self.", 0.95, ["tech", "practices"]),
    ]
    
    alice_did = node_alice.identity.did
    
    for content, confidence, domains in bob_beliefs:
        result = await node_bob.share_belief(
            peer_did=alice_did,
            content=content,
            confidence=confidence,
            domains=domains,
        )
        if result.get("success"):
            print(f"  ✓ Shared: \"{content[:50]}...\"")
        else:
            print(f"  ✗ Failed: {result.get('error')}")
    
    # Show updated counts
    print(f"\n  Updated belief counts:")
    print(f"    Alice has {len(node_alice.beliefs)} beliefs")
    print(f"    Bob has {len(node_bob.beliefs)} beliefs")
    
    # =========================================================================
    # Step 6: Cross-node queries
    # =========================================================================
    print_step(6, "Cross-node queries...")
    
    # Alice asks Bob about tech
    print("\n  Alice queries Bob for 'tech' beliefs:")
    result = await node_alice.query_peer(
        peer_did=bob_did,
        query="",
        domains=["tech"],
        min_confidence=0.5,
    )
    
    if result.get("success"):
        print(f"  Found {result.get('total', 0)} results:")
        for belief in result.get("results", [])[:3]:
            print(f"    - [{belief['confidence']:.0%}] {belief['content'][:60]}...")
    
    # Bob asks Alice about philosophy
    print("\n  Bob queries Alice for 'programming' mentions:")
    result = await node_bob.query_peer(
        peer_did=alice_did,
        query="programming",
        min_confidence=0.0,
    )
    
    if result.get("success"):
        print(f"  Found {result.get('total', 0)} results:")
        for belief in result.get("results", [])[:3]:
            print(f"    - [{belief['confidence']:.0%}] {belief['content'][:60]}...")
    
    # =========================================================================
    # Step 7: Show trust scores
    # =========================================================================
    print_step(7, "Trust scores after interaction...")
    
    alice_peer = node_alice.peer_store.get_peer(bob_did)
    bob_peer = node_bob.peer_store.get_peer(alice_did)
    
    if alice_peer:
        print(f"  Alice's view of Bob:")
        print(f"    Trust score: {alice_peer.trust_score:.2%}")
        print(f"    Beliefs received: {alice_peer.beliefs_received}")
        print(f"    Beliefs sent: {alice_peer.beliefs_sent}")
        print(f"    Queries: {alice_peer.queries_sent} sent, {alice_peer.queries_received} received")
    
    if bob_peer:
        print(f"\n  Bob's view of Alice:")
        print(f"    Trust score: {bob_peer.trust_score:.2%}")
        print(f"    Beliefs received: {bob_peer.beliefs_received}")
        print(f"    Beliefs sent: {bob_peer.beliefs_sent}")
        print(f"    Queries: {bob_peer.queries_sent} sent, {bob_peer.queries_received} received")
    
    # =========================================================================
    # Summary
    # =========================================================================
    print_header("Demo Complete!")
    
    print("""
What we demonstrated:

✓ Identity: Each node generated ed25519 keypairs and derived DIDs
✓ Discovery: Nodes introduced themselves and registered as peers
✓ Sharing: Beliefs were cryptographically signed and shared
✓ Verification: Receiving nodes verified signatures before accepting
✓ Querying: Nodes queried each other for relevant beliefs
✓ Trust: Interactions updated trust scores

This proves the interconnection thesis: two Valence nodes can discover
each other, share knowledge securely, and query across the federation.

Next steps:
- Add vector similarity search for semantic queries
- Implement sync protocol for continuous updates
- Add belief provenance tracking across hops
- Build trust propagation from endorsements
- Deploy to real infrastructure
""")
    
    # Cleanup
    print("\nShutting down servers...")
    await node_alice.stop()
    await node_bob.stop()
    
    # Cancel background tasks
    task_alice.cancel()
    task_bob.cancel()
    
    try:
        await task_alice
    except asyncio.CancelledError:
        pass
    
    try:
        await task_bob
    except asyncio.CancelledError:
        pass
    
    print("Done!")


if __name__ == "__main__":
    try:
        asyncio.run(run_demo())
    except KeyboardInterrupt:
        print("\nDemo interrupted.")
