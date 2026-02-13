"""
Spec Compliance Tests: Query Protocol

Verifies the codebase implements the query protocol per
spec/components/query-protocol/SPEC.md.

Key requirements:
- belief_query accepts ranking params (semantic_weight, confidence_weight, recency_weight, explain)
- belief_search accepts ranking params for semantic search
- Multi-signal ranking: final_score = w_semantic * semantic + w_confidence * confidence + w_recency * recency
- Ranking weights are configurable and normalizable
- Results include score_breakdown when explain=True
- Results sorted by final_score descending
"""

from __future__ import annotations

import inspect
import math
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from valence.core.ranking import (
    DEFAULT_RANKING,
    RankingConfig,
    compute_confidence_score,
    compute_recency_score,
    multi_signal_rank,
)
from valence.substrate.tools.beliefs import belief_query, belief_search


# ============================================================================
# Ranking Config Tests
# ============================================================================


class TestRankingConfig:
    """Test RankingConfig matches spec query protocol."""

    def test_default_weights(self):
        """Default weights: semantic=0.50, confidence=0.35, recency=0.15."""
        config = DEFAULT_RANKING
        assert config.semantic_weight == 0.50
        assert config.confidence_weight == 0.35
        assert config.recency_weight == 0.15

    def test_weights_sum_to_one(self):
        """Default weights should sum to 1.0."""
        total = DEFAULT_RANKING.semantic_weight + DEFAULT_RANKING.confidence_weight + DEFAULT_RANKING.recency_weight
        assert abs(total - 1.0) < 0.001

    def test_normalized_preserves_ratios(self):
        """normalized() should preserve weight ratios while summing to 1.0."""
        config = RankingConfig(semantic_weight=1.0, confidence_weight=0.5, recency_weight=0.5)
        normed = config.normalized()
        total = normed.semantic_weight + normed.confidence_weight + normed.recency_weight
        assert abs(total - 1.0) < 0.001
        # Semantic should be 50% of total
        assert abs(normed.semantic_weight - 0.5) < 0.001


# ============================================================================
# Multi-Signal Ranking Tests
# ============================================================================


class TestMultiSignalRanking:
    """Test multi_signal_rank function per spec."""

    def test_returns_sorted_by_final_score(self):
        """Results must be sorted by final_score descending."""
        results = [
            {"similarity": 0.5, "confidence": {"overall": 0.3}, "created_at": datetime.now(UTC).isoformat()},
            {"similarity": 0.9, "confidence": {"overall": 0.8}, "created_at": datetime.now(UTC).isoformat()},
            {"similarity": 0.7, "confidence": {"overall": 0.6}, "created_at": datetime.now(UTC).isoformat()},
        ]
        ranked = multi_signal_rank(results)
        scores = [r["final_score"] for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_semantic_weight_affects_ranking(self):
        """Higher semantic weight should favor high-similarity results."""
        results = [
            {"similarity": 0.9, "confidence": {"overall": 0.3}, "created_at": datetime.now(UTC).isoformat()},
            {"similarity": 0.3, "confidence": {"overall": 0.9}, "created_at": datetime.now(UTC).isoformat()},
        ]
        # With high semantic weight, first result should rank higher
        ranked = multi_signal_rank(results, semantic_weight=0.9, confidence_weight=0.05, recency_weight=0.05)
        assert ranked[0]["similarity"] == 0.9

    def test_confidence_weight_affects_ranking(self):
        """Higher confidence weight should favor high-confidence results."""
        results = [
            {"similarity": 0.3, "confidence": {"overall": 0.9}, "created_at": datetime.now(UTC).isoformat()},
            {"similarity": 0.9, "confidence": {"overall": 0.3}, "created_at": datetime.now(UTC).isoformat()},
        ]
        ranked = multi_signal_rank(results, semantic_weight=0.05, confidence_weight=0.9, recency_weight=0.05)
        conf_scores = [r.get("confidence", {}).get("overall", 0) for r in ranked]
        assert conf_scores[0] == 0.9

    def test_explain_mode_includes_breakdown(self):
        """When explain=True, results include score_breakdown."""
        results = [
            {"similarity": 0.8, "confidence": {"overall": 0.7}, "created_at": datetime.now(UTC).isoformat()},
        ]
        ranked = multi_signal_rank(results, explain=True)
        assert "score_breakdown" in ranked[0]
        breakdown = ranked[0]["score_breakdown"]
        assert "semantic" in breakdown
        assert "confidence" in breakdown
        assert "recency" in breakdown
        assert "final" in breakdown

    def test_explain_breakdown_has_value_weight_contribution(self):
        """Each breakdown signal has value, weight, and contribution."""
        results = [
            {"similarity": 0.8, "confidence": {"overall": 0.7}, "created_at": datetime.now(UTC).isoformat()},
        ]
        ranked = multi_signal_rank(results, explain=True)
        for signal in ["semantic", "confidence", "recency"]:
            assert "value" in ranked[0]["score_breakdown"][signal]
            assert "weight" in ranked[0]["score_breakdown"][signal]
            assert "contribution" in ranked[0]["score_breakdown"][signal]

    def test_weights_are_normalized(self):
        """Weights should be normalized to sum to 1.0 before scoring."""
        results = [
            {"similarity": 0.5, "confidence": {"overall": 0.5}, "created_at": datetime.now(UTC).isoformat()},
        ]
        # Use unnormalized weights
        ranked = multi_signal_rank(results, semantic_weight=2.0, confidence_weight=2.0, recency_weight=1.0, explain=True)
        breakdown = ranked[0]["score_breakdown"]
        total_weight = breakdown["semantic"]["weight"] + breakdown["confidence"]["weight"] + breakdown["recency"]["weight"]
        assert abs(total_weight - 1.0) < 0.001

    def test_min_confidence_filter(self):
        """min_confidence filters out low-confidence beliefs."""
        results = [
            {"similarity": 0.9, "confidence": {"overall": 0.3}, "created_at": datetime.now(UTC).isoformat()},
            {"similarity": 0.8, "confidence": {"overall": 0.8}, "created_at": datetime.now(UTC).isoformat()},
        ]
        ranked = multi_signal_rank(results, min_confidence=0.5)
        assert len(ranked) == 1
        assert ranked[0]["confidence"]["overall"] == 0.8


# ============================================================================
# Confidence Score Computation Tests
# ============================================================================


class TestConfidenceScoreComputation:
    """Test compute_confidence_score per spec."""

    def test_6d_confidence_uses_geometric_mean(self):
        """When 6D columns present, uses weighted geometric mean."""
        belief = {
            "confidence_source": 0.8,
            "confidence_method": 0.7,
            "confidence_consistency": 0.9,
            "confidence_freshness": 1.0,
            "confidence_corroboration": 0.5,
            "confidence_applicability": 0.6,
        }
        score = compute_confidence_score(belief)
        assert 0.0 <= score <= 1.0
        # Geometric mean should produce a value
        assert score > 0.0

    def test_fallback_to_jsonb_overall(self):
        """When no 6D columns, falls back to confidence.overall."""
        belief = {"confidence": {"overall": 0.85}}
        score = compute_confidence_score(belief)
        assert score == 0.85

    def test_default_score_is_0_5(self):
        """Default when no confidence data is 0.5."""
        belief = {}
        score = compute_confidence_score(belief)
        assert score == 0.5


# ============================================================================
# Recency Score Tests
# ============================================================================


class TestRecencyScore:
    """Test compute_recency_score per spec."""

    def test_recent_belief_scores_high(self):
        """Just-created belief should have recency near 1.0."""
        now = datetime.now(UTC)
        score = compute_recency_score(now)
        assert score > 0.95

    def test_old_belief_scores_low(self):
        """Old belief should have decayed recency."""
        old = datetime.now(UTC) - timedelta(days=365)
        score = compute_recency_score(old)
        assert score < 0.1

    def test_exponential_decay(self):
        """Recency follows exponential decay: exp(-decay_rate * age_days)."""
        now = datetime.now(UTC)
        score_30d = compute_recency_score(now - timedelta(days=30))
        score_60d = compute_recency_score(now - timedelta(days=60))
        # Exponential: score at 60d should be roughly score_30d^2
        assert score_60d < score_30d

    def test_none_returns_default(self):
        """None created_at returns 0.5 default."""
        assert compute_recency_score(None) == 0.5


# ============================================================================
# Query Tool Interface Tests
# ============================================================================


class TestBeliefQueryInterface:
    """Test belief_query accepts ranking parameters per spec."""

    def test_accepts_ranking_parameter(self):
        """belief_query must accept ranking dict parameter."""
        sig = inspect.signature(belief_query)
        assert "ranking" in sig.parameters

    def test_ranking_parameter_is_optional(self):
        """Ranking parameter should be optional (default None)."""
        sig = inspect.signature(belief_query)
        assert sig.parameters["ranking"].default is None

    def test_accepts_limit_parameter(self):
        """Spec: limit controls max results."""
        sig = inspect.signature(belief_query)
        assert "limit" in sig.parameters

    def test_accepts_domain_filter(self):
        """Spec: domain filtering for scoped queries."""
        sig = inspect.signature(belief_query)
        assert "domain_filter" in sig.parameters


class TestBeliefSearchInterface:
    """Test belief_search accepts ranking parameters per spec."""

    def test_accepts_ranking_parameter(self):
        """belief_search must accept ranking dict parameter."""
        sig = inspect.signature(belief_search)
        assert "ranking" in sig.parameters

    def test_accepts_min_similarity(self):
        """Spec: min_similarity threshold for semantic search."""
        sig = inspect.signature(belief_search)
        assert "min_similarity" in sig.parameters
        assert sig.parameters["min_similarity"].default == 0.5

    def test_accepts_min_confidence(self):
        """Spec: min_confidence threshold for filtering."""
        sig = inspect.signature(belief_search)
        assert "min_confidence" in sig.parameters

    def test_accepts_domain_filter(self):
        """Spec: domain filtering."""
        sig = inspect.signature(belief_search)
        assert "domain_filter" in sig.parameters
