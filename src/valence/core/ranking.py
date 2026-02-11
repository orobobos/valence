"""Multi-signal ranking for belief retrieval.

Combines semantic similarity, confidence, and recency into a single
final score. Used by MCP tools and CLI for result ordering.

Extracted from cli/utils.py for reuse across the codebase.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class RankingConfig:
    """Configuration for multi-signal ranking weights."""

    semantic_weight: float = 0.50
    confidence_weight: float = 0.35
    recency_weight: float = 0.15
    decay_rate: float = 0.01  # ~69 day half-life

    def normalized(self) -> RankingConfig:
        """Return a copy with weights normalized to sum to 1.0."""
        total = self.semantic_weight + self.confidence_weight + self.recency_weight
        if total <= 0:
            return RankingConfig()
        return RankingConfig(
            semantic_weight=self.semantic_weight / total,
            confidence_weight=self.confidence_weight / total,
            recency_weight=self.recency_weight / total,
            decay_rate=self.decay_rate,
        )


DEFAULT_RANKING = RankingConfig()


def compute_confidence_score(belief: dict) -> float:
    """Compute aggregated confidence score from 6D confidence vector.

    Uses geometric mean to penalize beliefs with any weak dimension.
    Falls back to JSONB 'overall' field for backward compatibility.
    """
    # Try 6D confidence columns first
    src = belief.get("confidence_source", 0.5)
    meth = belief.get("confidence_method", 0.5)
    cons = belief.get("confidence_consistency", 1.0)
    fresh = belief.get("confidence_freshness", 1.0)
    corr = belief.get("confidence_corroboration", 0.1)
    app = belief.get("confidence_applicability", 0.8)

    has_6d = any(
        [
            belief.get("confidence_source") is not None,
            belief.get("confidence_method") is not None,
        ]
    )

    if has_6d:
        # Geometric mean with spec weights
        # w_sr=0.25, w_mq=0.20, w_ic=0.15, w_tf=0.15, w_cor=0.15, w_da=0.10
        try:
            score = (src**0.25) * (meth**0.20) * (cons**0.15) * (fresh**0.15) * (corr**0.15) * (app**0.10)
            return min(1.0, max(0.0, score))
        except (ValueError, ZeroDivisionError):
            pass

    # Fallback to JSONB overall
    conf = belief.get("confidence", {})
    if isinstance(conf, dict):
        overall = conf.get("overall", 0.5)
        if isinstance(overall, int | float):
            return min(1.0, max(0.0, float(overall)))

    return 0.5


def compute_recency_score(created_at: datetime | str | None, decay_rate: float = 0.01) -> float:
    """Compute recency score with exponential decay.

    Default decay_rate=0.01 gives a half-life of ~69 days.
    Handles datetime objects, ISO format strings, and None.
    """
    if not created_at:
        return 0.5

    # Handle string dates (from serialized data)
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at)
        except (ValueError, TypeError):
            return 0.5

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)

    now = datetime.now(UTC)
    age_days = (now - created_at).total_seconds() / 86400

    recency = math.exp(-decay_rate * age_days)
    return min(1.0, max(0.0, recency))


def multi_signal_rank(
    results: list[dict],
    semantic_weight: float = 0.50,
    confidence_weight: float = 0.35,
    recency_weight: float = 0.15,
    decay_rate: float = 0.01,
    min_confidence: float | None = None,
    explain: bool = False,
) -> list[dict]:
    """Apply multi-signal ranking to query results.

    Formula: final_score = w_semantic * semantic + w_confidence * confidence + w_recency * recency

    Args:
        results: List of belief dicts with 'similarity' (semantic score)
        semantic_weight: Weight for semantic similarity (default 0.50)
        confidence_weight: Weight for confidence score (default 0.35)
        recency_weight: Weight for recency score (default 0.15)
        decay_rate: Exponential decay rate for recency (default 0.01)
        min_confidence: Filter out beliefs below this confidence (optional)
        explain: Include score breakdown in results

    Returns:
        Sorted results with 'final_score' and optional 'score_breakdown'
    """
    # Normalize weights to sum to 1.0
    total_weight = semantic_weight + confidence_weight + recency_weight
    if total_weight > 0:
        semantic_weight /= total_weight
        confidence_weight /= total_weight
        recency_weight /= total_weight

    ranked = []
    for r in results:
        # Semantic score (already computed from embedding similarity or ts_rank)
        semantic = r.get("similarity", 0.0)
        if isinstance(semantic, int | float):
            semantic = min(1.0, max(0.0, float(semantic)))
        else:
            semantic = 0.0

        # Confidence score
        confidence = compute_confidence_score(r)

        # Filter by minimum confidence if specified
        if min_confidence is not None and confidence < min_confidence:
            continue

        # Recency score
        created_at = r.get("created_at")
        recency = compute_recency_score(created_at, decay_rate) if created_at else 0.5

        # Final score
        final_score = semantic_weight * semantic + confidence_weight * confidence + recency_weight * recency

        r["final_score"] = final_score

        if explain:
            r["score_breakdown"] = {
                "semantic": {
                    "value": semantic,
                    "weight": semantic_weight,
                    "contribution": semantic_weight * semantic,
                },
                "confidence": {
                    "value": confidence,
                    "weight": confidence_weight,
                    "contribution": confidence_weight * confidence,
                },
                "recency": {
                    "value": recency,
                    "weight": recency_weight,
                    "contribution": recency_weight * recency,
                },
                "final": final_score,
            }

        ranked.append(r)

    ranked.sort(key=lambda x: x.get("final_score", 0), reverse=True)

    return ranked
