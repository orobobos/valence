#!/usr/bin/env python3
"""Valence v2 smoke test — full ingest → query → compile → retrieve loop."""
import asyncio
import json
import os
import sys

# Point at v2 database
os.environ["VKB_DB_HOST"] = "localhost"
os.environ["VKB_DB_PORT"] = "5434"
os.environ["VKB_DB_NAME"] = "valence_v2"
os.environ["VKB_DB_USER"] = "valence"
os.environ["VKB_DB_PASSWORD"] = "valence"

from valence.core import sources, articles, provenance, retrieval, compilation, contention, usage, forgetting

# Simple LLM backend for testing — just concatenates and formats
def simple_llm(prompt: str) -> str:
    """Minimal compilation that extracts key info without a real LLM."""
    # For compile prompts, return structured JSON
    if "compile" in prompt.lower() or "summarize" in prompt.lower() or "sources to compile" in prompt.lower():
        return json.dumps({
            "title": "Compiled Article",
            "content": "This is a compiled article from the provided sources. The sources discuss various topics and have been synthesized into a coherent summary.",
            "relationships": [{"source_index": 0, "relationship": "originates"}]
        })
    if "update" in prompt.lower() or "incorporate" in prompt.lower():
        return json.dumps({
            "title": "Updated Article",
            "content": "This article has been updated with new information from the latest source.",
            "relationship": "confirms"
        })
    if "contention" in prompt.lower() or "contradict" in prompt.lower():
        return json.dumps({
            "is_contention": False,
            "materiality": 0.1,
            "explanation": "No significant contention detected."
        })
    return json.dumps({"content": "Processed.", "title": "Result"})

compilation.set_llm_backend(simple_llm)

async def smoke_test():
    print("=" * 60)
    print("VALENCE V2 SMOKE TEST")
    print("=" * 60)
    
    # Step 1: Ingest sources
    print("\n--- Step 1: Ingest Sources ---")
    try:
        s1 = await sources.ingest_source(
            content="Python is a high-level programming language created by Guido van Rossum in 1991. It emphasizes code readability and simplicity.",
            source_type="document",
            title="Python Overview"
        )
        print(f"  ✓ Source 1 ingested: {s1['id']}")
    except Exception as e:
        print(f"  ✗ Source 1 failed: {e}")
        return False

    try:
        s2 = await sources.ingest_source(
            content="Python was first released in 1991 and has become one of the most popular programming languages in the world, used extensively in AI and data science.",
            source_type="web",
            title="Python Popularity"
        )
        print(f"  ✓ Source 2 ingested: {s2['id']}")
    except Exception as e:
        print(f"  ✗ Source 2 failed: {e}")
        return False

    try:
        s3 = await sources.ingest_source(
            content="JavaScript, not Python, is the most important programming language. Python is slow and unsuitable for production systems.",
            source_type="conversation",
            title="Controversial Take"
        )
        print(f"  ✓ Source 3 ingested: {s3['id']}")
    except Exception as e:
        print(f"  ✗ Source 3 failed: {e}")
        return False

    # Step 2: List sources
    print("\n--- Step 2: List Sources ---")
    try:
        all_sources = await sources.list_sources()
        print(f"  ✓ {len(all_sources)} sources found")
    except Exception as e:
        print(f"  ✗ List failed: {e}")
        return False

    # Step 3: Search sources
    print("\n--- Step 3: Search Sources ---")
    try:
        results = await sources.search_sources("Python programming")
        print(f"  ✓ Search returned {len(results)} results")
    except Exception as e:
        print(f"  ✗ Search failed: {e}")
        return False

    # Step 4: Compile article from sources
    print("\n--- Step 4: Compile Article ---")
    try:
        result = await compilation.compile_article(
            source_ids=[s1['id'], s2['id']],
            title_hint="Python Programming Language"
        )
        if not result.get('success'):
            raise Exception(result.get('error', 'Unknown compilation error'))
        article = result['article']
        print(f"  ✓ Article compiled: {article['id']}")
        print(f"    Title: {article.get('title', 'N/A')}")
    except Exception as e:
        print(f"  ✗ Compilation failed: {e}")
        import traceback; traceback.print_exc()
        return False

    # Step 5: Get article with provenance
    print("\n--- Step 5: Get Article + Provenance ---")
    try:
        a = articles.get_article(article['id'], include_provenance=True)
        print(f"  ✓ Article retrieved: {a.get('title', 'N/A')}")
        prov = provenance.get_provenance(article['id'])
        print(f"  ✓ Provenance: {len(prov)} sources linked")
        for p in prov:
            print(f"    - {p.get('relationship', '?')}: {p.get('title', p.get('source_id', '?'))}")
    except Exception as e:
        print(f"  ✗ Get/provenance failed: {e}")
        import traceback; traceback.print_exc()
        return False

    # Step 6: Retrieve (unified search)
    print("\n--- Step 6: Unified Retrieval ---")
    try:
        results = await retrieval.retrieve("Python programming language")
        print(f"  ✓ Retrieval returned {len(results)} results")
        for r in results[:3]:
            print(f"    - [{r.get('type', '?')}] {r.get('title', 'N/A')} (score: {r.get('score', '?')})")
    except Exception as e:
        print(f"  ✗ Retrieval failed: {e}")
        import traceback; traceback.print_exc()
        return False

    # Step 7: Update article with new source
    print("\n--- Step 7: Incremental Update ---")
    try:
        result = await compilation.update_article_from_source(article['id'], s3['id'])
        if not result.get('success'):
            raise Exception(result.get('error', 'Unknown update error'))
        updated = result['article']
        print(f"  ✓ Article updated, version: {updated.get('version', '?')}")
    except Exception as e:
        print(f"  ✗ Update failed: {e}")
        import traceback; traceback.print_exc()
        return False

    # Step 8: Check contention
    print("\n--- Step 8: Contention Check ---")
    try:
        c = await contention.detect_contention(article['id'], s3['id'])
        if c:
            print(f"  ✓ Contention detected: materiality={c.get('materiality', '?')}")
        else:
            print(f"  ✓ No contention detected (below threshold)")
    except Exception as e:
        print(f"  ✗ Contention check failed: {e}")
        import traceback; traceback.print_exc()
        return False

    # Step 9: Usage scores
    print("\n--- Step 9: Usage Scores ---")
    try:
        count = await usage.compute_usage_scores()
        print(f"  ✓ Usage scores computed for {count} articles")
        candidates = await usage.get_decay_candidates(limit=5)
        print(f"  ✓ Decay candidates: {len(candidates)}")
    except Exception as e:
        print(f"  ✗ Usage failed: {e}")
        import traceback; traceback.print_exc()
        return False

    # Step 10: Forgetting
    print("\n--- Step 10: Source Removal ---")
    try:
        result = await forgetting.remove_source(s3['id'])
        print(f"  ✓ Source removed, tombstone created")
        remaining = await sources.list_sources()
        print(f"  ✓ {len(remaining)} sources remain")
    except Exception as e:
        print(f"  ✗ Forgetting failed: {e}")
        import traceback; traceback.print_exc()
        return False

    print("\n" + "=" * 60)
    print("SMOKE TEST COMPLETE ✓")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = asyncio.run(smoke_test())
    sys.exit(0 if success else 1)
