#!/usr/bin/env python3
"""Valence Demo — walk through the core value loop.

Prerequisites:
    - PostgreSQL running with valence database initialized
    - pip install -e .
    - VKB_DB_HOST, VKB_DB_NAME, VKB_DB_USER env vars set (or defaults)

Usage:
    python examples/demo.py
"""

from __future__ import annotations

import json
import sys
from uuid import uuid4

# Import tool handlers directly
from valence.substrate.tools.beliefs import belief_create, belief_query, belief_get, belief_supersede
from valence.substrate.tools.entities import entity_search
from valence.substrate.tools.tensions import tension_list
from valence.substrate.tools.confidence import confidence_explain
from valence.substrate.tools.trust import trust_check
from valence.vkb.tools.sessions import session_start, session_end
from valence.vkb.tools.insights import insight_extract


def pp(label: str, data: dict) -> None:
    """Pretty-print a result."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    if isinstance(data, dict):
        print(json.dumps(data, indent=2, default=str))
    else:
        print(data)


def main() -> int:
    print("Valence Demo")
    print("============")
    print("Walking through the core value loop.\n")

    # 1. Start a session
    print("[1/7] Starting a session...")
    session = session_start(platform="api", project_context="demo")
    pp("Session started", session)
    session_id = session.get("session_id")

    if not session.get("success"):
        print("ERROR: Could not start session. Is the database running?")
        return 1

    # 2. Create beliefs with confidence
    print("\n[2/7] Creating beliefs with dimensional confidence...")

    b1 = belief_create(
        content="Python's GIL limits true parallelism for CPU-bound tasks",
        domain_path=["tech", "python", "concurrency"],
        confidence={"overall": 0.9, "source_reliability": 0.95},
        source_type="observation",
        entities=[
            {"name": "Python", "type": "tool", "role": "subject"},
            {"name": "GIL", "type": "concept", "role": "subject"},
        ],
    )
    pp("Belief 1 created", b1)

    b2 = belief_create(
        content="asyncio provides effective concurrency for I/O-bound Python applications",
        domain_path=["tech", "python", "concurrency"],
        confidence={"overall": 0.85, "source_reliability": 0.9},
        source_type="observation",
        entities=[
            {"name": "Python", "type": "tool", "role": "subject"},
            {"name": "asyncio", "type": "concept", "role": "subject"},
        ],
    )
    pp("Belief 2 created", b2)

    b3 = belief_create(
        content="PostgreSQL with pgvector enables efficient semantic search at scale",
        domain_path=["tech", "databases"],
        confidence={"overall": 0.8},
        source_type="observation",
        entities=[
            {"name": "PostgreSQL", "type": "tool", "role": "subject"},
            {"name": "pgvector", "type": "tool", "role": "subject"},
        ],
    )
    pp("Belief 3 created", b3)

    # 3. Query semantically
    print("\n[3/7] Querying the knowledge base...")

    results = belief_query(query="Python concurrency patterns")
    pp("Query: 'Python concurrency patterns'", results)

    results2 = belief_query(query="database vector search")
    pp("Query: 'database vector search'", results2)

    # 4. Supersede a belief (update with history)
    print("\n[4/7] Superseding a belief (update with provenance)...")

    if b1.get("success") and b1.get("belief_id"):
        updated = belief_supersede(
            old_belief_id=b1["belief_id"],
            new_content="Python's GIL limits true parallelism for CPU-bound tasks, but Python 3.13+ has experimental free-threaded mode",
            reason="Updated with Python 3.13 free-threading information",
        )
        pp("Belief superseded", updated)

    # 5. Check entities
    print("\n[5/7] Searching entities...")

    entities = entity_search(query="Python")
    pp("Entity search: 'Python'", entities)

    # 6. Check trust
    print("\n[6/7] Checking trust on a topic...")

    trust = trust_check(topic="python")
    pp("Trust check: 'python'", trust)

    # 7. Extract insight and close session
    print("\n[7/7] Extracting insight and closing session...")

    if session_id:
        insight = insight_extract(
            session_id=session_id,
            content="Valence demo successfully demonstrates the core value loop: create, query, supersede, trust",
            domain_path=["meta", "valence"],
        )
        pp("Insight extracted", insight)

        closed = session_end(
            session_id=session_id,
            summary="Demonstrated Valence core value loop with belief CRUD, semantic search, and trust",
            themes=["valence", "demo", "knowledge-substrate"],
        )
        pp("Session closed", closed)

    print("\n" + "=" * 60)
    print("  Demo complete!")
    print("=" * 60)
    print("\nWhat happened:")
    print("  1. Started a tracked session")
    print("  2. Created 3 beliefs with dimensional confidence")
    print("  3. Queried the knowledge base semantically")
    print("  4. Superseded a belief (full history preserved)")
    print("  5. Searched entities (auto-created from beliefs)")
    print("  6. Checked trust scoring on a topic")
    print("  7. Extracted an insight and closed the session")
    print("\nThis is the core value loop. Over time, beliefs accumulate,")
    print("patterns emerge, and the substrate learns what matters to you.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
