"""Trust check tool implementation.

Functions:
    trust_check
"""

from __future__ import annotations

from typing import Any

from . import _common
from ._common import logger


def trust_check(
    topic: str,
    entity_name: str | None = None,
    include_federated: bool = True,
    min_trust: float = 0.3,
    limit: int = 10,
    domain: str | None = None,
) -> dict[str, Any]:
    """Check trust levels for a topic/domain.

    Args:
        topic: Topic or domain to check trust for
        entity_name: Optional entity name filter
        include_federated: Include federated node trust
        min_trust: Minimum trust threshold
        limit: Maximum results
        domain: Optional domain scope for trust scoring. When provided,
                uses domain-specific trust from node_trust.trust->'domain_expertise'->domain
                with fallback to overall trust.
    """
    result: dict[str, Any] = {
        "success": True,
        "topic": topic,
        "domain": domain,
        "trusted_entities": [],
        "trusted_nodes": [],
    }

    with _common.get_cursor() as cur:
        # Find entities that have high-confidence beliefs in this domain
        entity_sql = """
            SELECT e.id, e.name, e.type,
                   COUNT(b.id) as belief_count,
                   AVG((b.confidence->>'overall')::numeric) as avg_confidence,
                   MAX((b.confidence->>'overall')::numeric) as max_confidence
            FROM entities e
            JOIN belief_entities be ON e.id = be.entity_id
            JOIN beliefs b ON be.belief_id = b.id
            WHERE b.status = 'active'
            AND (
                b.domain_path && ARRAY[%s]
                OR b.content ILIKE %s
            )
        """
        params: list[Any] = [topic, f"%{topic}%"]

        if entity_name:
            entity_sql += " AND e.name ILIKE %s"
            params.append(f"%{entity_name}%")

        entity_sql += """
            GROUP BY e.id
            HAVING AVG((b.confidence->>'overall')::numeric) >= %s
            ORDER BY avg_confidence DESC, belief_count DESC
            LIMIT %s
        """
        params.extend([min_trust, limit])

        cur.execute(entity_sql, params)
        for row in cur.fetchall():
            result["trusted_entities"].append(
                {
                    "id": str(row["id"]),
                    "name": row["name"],
                    "type": row["type"],
                    "belief_count": row["belief_count"],
                    "avg_confidence": (float(row["avg_confidence"]) if row["avg_confidence"] else None),
                    "max_confidence": (float(row["max_confidence"]) if row["max_confidence"] else None),
                    "trust_reason": f"Has {row['belief_count']} beliefs about {topic} with avg confidence {float(row['avg_confidence']):.2f}",
                }
            )

        # Check federated node trust if enabled
        if include_federated:
            try:
                # When domain is specified, use domain-specific trust with fallback to overall
                if domain:
                    trust_sql = """
                        SELECT fn.id, fn.name, fn.instance_url,
                               nt.trust, nt.beliefs_corroborated, nt.beliefs_disputed,
                               COALESCE(
                                   (nt.trust->'domain_expertise'->>%s)::numeric,
                                   (nt.trust->>'overall')::numeric,
                                   0
                               ) AS effective_trust
                        FROM federation_nodes fn
                        JOIN node_trust nt ON fn.id = nt.node_id
                        WHERE fn.status = 'active'
                        AND COALESCE(
                            (nt.trust->'domain_expertise'->>%s)::numeric,
                            (nt.trust->>'overall')::numeric,
                            0
                        ) >= %s
                        ORDER BY effective_trust DESC
                        LIMIT %s
                    """
                    trust_params: list[Any] = [domain, domain, min_trust, limit]
                else:
                    trust_sql = """
                        SELECT fn.id, fn.name, fn.instance_url,
                               nt.trust, nt.beliefs_corroborated, nt.beliefs_disputed,
                               (nt.trust->>'overall')::numeric AS effective_trust
                        FROM federation_nodes fn
                        JOIN node_trust nt ON fn.id = nt.node_id
                        WHERE fn.status = 'active'
                        AND (nt.trust->>'overall')::numeric >= %s
                        ORDER BY effective_trust DESC
                        LIMIT %s
                    """
                    trust_params = [min_trust, limit]

                cur.execute(trust_sql, trust_params)
                for row in cur.fetchall():
                    effective_trust = float(row["effective_trust"]) if row["effective_trust"] else 0
                    overall_trust = row["trust"].get("overall", 0) if row["trust"] else 0
                    domain_trust = None
                    if domain and row["trust"] and row["trust"].get("domain_expertise"):
                        domain_trust = row["trust"]["domain_expertise"].get(domain)

                    node_entry: dict[str, Any] = {
                        "id": str(row["id"]),
                        "name": row["name"],
                        "instance_url": row["instance_url"],
                        "trust_score": effective_trust,
                        "overall_trust": overall_trust,
                        "beliefs_corroborated": row["beliefs_corroborated"],
                        "beliefs_disputed": row["beliefs_disputed"],
                        "trust_reason": f"Corroborated {row['beliefs_corroborated']} beliefs, disputed {row['beliefs_disputed']}",
                    }
                    if domain:
                        node_entry["domain_trust"] = domain_trust
                        node_entry["domain"] = domain

                    result["trusted_nodes"].append(node_entry)
            except Exception as e:
                logger.debug(f"Federation tables may not exist: {e}")

    return result
