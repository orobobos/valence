"""Query obfuscation with cover traffic (#355).

Mixes real federation queries with k dummy queries drawn from the
network-wide domain distribution. Peers cannot distinguish real
from dummy queries. Results are filtered locally.

Default configuration: k=3 dummy queries per real query.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_COVER_COUNT = 3


@dataclass
class QueryBundle:
    """A bundle of real + dummy queries for obfuscated federation queries."""

    real_query: dict[str, Any]
    dummy_queries: list[dict[str, Any]] = field(default_factory=list)
    cover_count: int = DEFAULT_COVER_COUNT

    @property
    def all_queries(self) -> list[dict[str, Any]]:
        """Return all queries in randomized order."""
        queries = [{"query": self.real_query, "is_real": True}]
        for dq in self.dummy_queries:
            queries.append({"query": dq, "is_real": False})
        random.shuffle(queries)
        return queries

    @property
    def total_queries(self) -> int:
        return 1 + len(self.dummy_queries)


@dataclass
class QueryResult:
    """Filtered results from an obfuscated query."""

    real_results: list[dict[str, Any]]
    dummy_count: int
    total_queries_sent: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": self.real_results,
            "dummy_count": self.dummy_count,
            "total_queries_sent": self.total_queries_sent,
        }


def get_domain_distribution(cur) -> dict[str, float]:
    """Get the network-wide domain distribution from beliefs.

    Args:
        cur: Database cursor.

    Returns:
        Dict mapping top-level domain to relative frequency.
    """
    cur.execute(
        """
        SELECT domain_path[1] as domain, COUNT(*) as cnt
        FROM beliefs
        WHERE domain_path IS NOT NULL AND array_length(domain_path, 1) > 0
        GROUP BY domain_path[1]
        ORDER BY cnt DESC
        LIMIT 50
        """
    )
    rows = cur.fetchall()

    if not rows:
        return {"general": 1.0}

    total = sum(r["cnt"] for r in rows)
    return {r["domain"]: r["cnt"] / total for r in rows}


def generate_dummy_query(domain_distribution: dict[str, float]) -> dict[str, Any]:
    """Generate a statistically plausible dummy query.

    Samples a domain from the network-wide distribution and creates
    a query that looks like a real belief search.

    Args:
        domain_distribution: Mapping of domain -> relative frequency.

    Returns:
        Query dict matching the format of real queries.
    """
    domains = list(domain_distribution.keys())
    weights = list(domain_distribution.values())

    selected_domain = random.choices(domains, weights=weights, k=1)[0]

    return {
        "query": f"beliefs in {selected_domain}",
        "domain_filter": [selected_domain],
        "limit": random.randint(5, 20),
        "is_dummy": True,
    }


def build_query_bundle(
    real_query: dict[str, Any],
    domain_distribution: dict[str, float],
    cover_count: int = DEFAULT_COVER_COUNT,
) -> QueryBundle:
    """Build a query bundle with real + dummy queries.

    Args:
        real_query: The actual query to execute.
        domain_distribution: Network domain distribution for dummy generation.
        cover_count: Number of dummy queries to add.

    Returns:
        QueryBundle with queries in randomized order.
    """
    dummies = [generate_dummy_query(domain_distribution) for _ in range(cover_count)]
    return QueryBundle(
        real_query=real_query,
        dummy_queries=dummies,
        cover_count=cover_count,
    )


def filter_results(
    all_results: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    real_query: dict[str, Any],
) -> QueryResult:
    """Filter query results to extract only the real results.

    Args:
        all_results: List of (query, results) tuples.
        real_query: The original real query (for matching).

    Returns:
        QueryResult with only the real results.
    """
    real_results: list[dict[str, Any]] = []
    dummy_count = 0

    for query, results in all_results:
        if query.get("is_dummy"):
            dummy_count += 1
        else:
            real_results.extend(results)

    return QueryResult(
        real_results=real_results,
        dummy_count=dummy_count,
        total_queries_sent=len(all_results),
    )
