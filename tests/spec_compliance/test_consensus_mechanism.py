"""
Spec Compliance Tests: Consensus Mechanism

Verifies the codebase implements the consensus mechanism per
spec/components/consensus-mechanism/SPEC.md.

Key requirements:
- Four trust layers: L1 Personal, L2 Federated, L3 Domain, L4 Communal
- Corroboration with independence scoring
- Independence uses weighted combination: 0.4*evidential + 0.3*source + 0.2*method + 0.1*temporal
- Elevation thresholds for L1->L2, L2->L3, L3->L4
- Challenge submission and resolution
- Finality levels: TENTATIVE, PROVISIONAL, ESTABLISHED, SETTLED
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from valence.core.consensus import (
    ELEVATION_THRESHOLDS,
    BeliefConsensusStatus,
    Challenge,
    ChallengeStatus,
    Corroboration,
    FinalityLevel,
    IndependenceScore,
    TrustLayer,
    _compute_finality,
    _next_layer,
    _prev_layer,
    calculate_independence,
)


# ============================================================================
# Trust Layer Enum Tests
# ============================================================================


class TestTrustLayerEnum:
    """Test TrustLayer matches spec Section 1.1 - The Four Layers."""

    def test_has_l1_personal(self):
        """L1: Personal Belief - self-attested."""
        assert TrustLayer.L1_PERSONAL.value == "l1_personal"

    def test_has_l2_federated(self):
        """L2: Federated Knowledge - group trust boundary."""
        assert TrustLayer.L2_FEDERATED.value == "l2_federated"

    def test_has_l3_domain(self):
        """L3: Domain Knowledge - expert gatekeeping."""
        assert TrustLayer.L3_DOMAIN.value == "l3_domain"

    def test_has_l4_communal(self):
        """L4: Communal Consensus - network-wide independent verification."""
        assert TrustLayer.L4_COMMUNAL.value == "l4_communal"

    def test_exactly_four_layers(self):
        """Spec defines exactly four trust layers."""
        assert len(TrustLayer) == 4

    def test_layer_ordering(self):
        """Layers must be ordered L1 < L2 < L3 < L4."""
        order = [TrustLayer.L1_PERSONAL, TrustLayer.L2_FEDERATED, TrustLayer.L3_DOMAIN, TrustLayer.L4_COMMUNAL]
        for i in range(len(order) - 1):
            assert _next_layer(order[i]) == order[i + 1]


# ============================================================================
# Independence Scoring Tests
# ============================================================================


class TestIndependenceScore:
    """Test IndependenceScore matches spec Section 2.2."""

    def test_independence_score_has_all_components(self):
        """IndependenceScore: evidential, source, method, temporal, overall."""
        score = IndependenceScore(evidential=0.8, source=0.7, method=0.5, temporal=0.3, overall=0.6)
        assert score.evidential == 0.8
        assert score.source == 0.7
        assert score.method == 0.5
        assert score.temporal == 0.3
        assert score.overall == 0.6

    def test_independence_score_serialization(self):
        """to_dict should include all components."""
        score = IndependenceScore(evidential=0.8, source=0.7, method=0.5, temporal=0.3, overall=0.6)
        d = score.to_dict()
        assert "evidential" in d
        assert "source" in d
        assert "method" in d
        assert "temporal" in d
        assert "overall" in d


class TestIndependenceCalculation:
    """Test calculate_independence per spec Section 2.2."""

    def test_fully_independent_sources(self):
        """No overlap in sources -> high evidential independence."""
        score = calculate_independence(
            belief_a_sources=["source_1", "source_2"],
            belief_b_sources=["source_3", "source_4"],
        )
        assert score.evidential == 1.0

    def test_fully_overlapping_sources(self):
        """Identical sources -> zero evidential independence."""
        score = calculate_independence(
            belief_a_sources=["source_1", "source_2"],
            belief_b_sources=["source_1", "source_2"],
        )
        assert score.evidential == 0.0

    def test_partial_overlap_sources(self):
        """Partial overlap -> intermediate independence."""
        score = calculate_independence(
            belief_a_sources=["source_1", "source_2"],
            belief_b_sources=["source_2", "source_3"],
        )
        # Jaccard similarity: 1/3 -> independence = 2/3
        assert 0.0 < score.evidential < 1.0

    def test_different_methods_give_high_method_independence(self):
        """Different derivation methods -> method independence = 1.0."""
        score = calculate_independence(
            belief_a_sources=["a"],
            belief_b_sources=["b"],
            belief_a_method="observation",
            belief_b_method="inference",
        )
        assert score.method == 1.0

    def test_same_method_gives_zero_method_independence(self):
        """Same derivation method -> method independence = 0.0."""
        score = calculate_independence(
            belief_a_sources=["a"],
            belief_b_sources=["b"],
            belief_a_method="observation",
            belief_b_method="observation",
        )
        assert score.method == 0.0

    def test_temporal_independence_increases_with_time_gap(self):
        """Larger time gap -> higher temporal independence (max at 7 days)."""
        short = calculate_independence(
            belief_a_sources=["a"], belief_b_sources=["b"], time_gap_days=1.0,
        )
        long = calculate_independence(
            belief_a_sources=["a"], belief_b_sources=["b"], time_gap_days=7.0,
        )
        assert long.temporal > short.temporal
        assert long.temporal == 1.0  # Max at 7 days

    def test_overall_is_weighted_combination(self):
        """Overall = 0.4*evidential + 0.3*source + 0.2*method + 0.1*temporal."""
        score = calculate_independence(
            belief_a_sources=["source_1"],
            belief_b_sources=["source_2"],
            belief_a_method="observation",
            belief_b_method="inference",
            time_gap_days=7.0,
        )
        expected = 0.4 * score.evidential + 0.3 * score.source + 0.2 * score.method + 0.1 * score.temporal
        assert abs(score.overall - expected) < 0.01


# ============================================================================
# Elevation Threshold Tests
# ============================================================================


class TestElevationThresholds:
    """Test elevation thresholds per spec Section 3."""

    def test_l2_thresholds(self):
        """L1->L2: 5 contributors, agreement > 0.6, no independence required."""
        t = ELEVATION_THRESHOLDS[TrustLayer.L2_FEDERATED]
        assert t["min_contributors"] == 5
        assert t["min_agreement_score"] == 0.6
        assert t["min_independence"] == 0.0

    def test_l3_thresholds(self):
        """L2->L3: 3+ federations, independence > 0.5, 2+ domain experts."""
        t = ELEVATION_THRESHOLDS[TrustLayer.L3_DOMAIN]
        assert t["min_contributors"] >= 3
        assert t["min_independence"] == 0.5
        assert t["min_expert_count"] == 2
        assert t["min_expert_reputation"] == 0.7

    def test_l4_thresholds(self):
        """L3->L4: independence > 0.7, Byzantine threshold."""
        t = ELEVATION_THRESHOLDS[TrustLayer.L4_COMMUNAL]
        assert t["min_independence"] == 0.7
        assert "min_stake_threshold" in t

    def test_all_target_layers_have_thresholds(self):
        """Thresholds defined for L2, L3, L4 (L1 is self-attested)."""
        assert TrustLayer.L2_FEDERATED in ELEVATION_THRESHOLDS
        assert TrustLayer.L3_DOMAIN in ELEVATION_THRESHOLDS
        assert TrustLayer.L4_COMMUNAL in ELEVATION_THRESHOLDS
        assert TrustLayer.L1_PERSONAL not in ELEVATION_THRESHOLDS


# ============================================================================
# Finality Level Tests
# ============================================================================


class TestFinalityLevels:
    """Test finality computation per spec Section 5."""

    def test_finality_enum_values(self):
        """Finality levels: TENTATIVE, PROVISIONAL, ESTABLISHED, SETTLED."""
        assert FinalityLevel.TENTATIVE.value == "tentative"
        assert FinalityLevel.PROVISIONAL.value == "provisional"
        assert FinalityLevel.ESTABLISHED.value == "established"
        assert FinalityLevel.SETTLED.value == "settled"

    def test_l1_finality_is_tentative(self):
        """L1 personal beliefs have tentative finality."""
        result = _compute_finality(TrustLayer.L1_PERSONAL, None)
        assert result == FinalityLevel.TENTATIVE

    def test_l2_finality_is_provisional(self):
        """L2 federated beliefs have provisional finality."""
        result = _compute_finality(TrustLayer.L2_FEDERATED, None)
        assert result == FinalityLevel.PROVISIONAL

    def test_l3_finality_is_established(self):
        """L3 domain knowledge has established finality (if unchallenged)."""
        result = _compute_finality(TrustLayer.L3_DOMAIN, None)
        assert result == FinalityLevel.ESTABLISHED

    def test_l4_finality_is_settled(self):
        """L4 communal consensus has settled finality (if unchallenged)."""
        result = _compute_finality(TrustLayer.L4_COMMUNAL, None)
        assert result == FinalityLevel.SETTLED


# ============================================================================
# Corroboration Model Tests
# ============================================================================


class TestCorroborationModel:
    """Test Corroboration matches spec Section 2.3."""

    def test_corroboration_has_required_fields(self):
        """Corroboration: primary_belief_id, corroborating_belief_id, independence, effective_weight."""
        c = Corroboration(
            id=uuid4(),
            primary_belief_id=uuid4(),
            corroborating_belief_id=uuid4(),
            primary_holder="did:test:alice",
            corroborator="did:test:bob",
            semantic_similarity=0.9,
            independence=IndependenceScore(overall=0.7),
            effective_weight=0.35,
        )
        assert c.semantic_similarity == 0.9
        assert c.effective_weight == 0.35


# ============================================================================
# Challenge Model Tests
# ============================================================================


class TestChallengeModel:
    """Test Challenge matches spec Section 5.3."""

    def test_challenge_has_required_fields(self):
        """Challenge: belief_id, challenger_id, target_layer, reasoning, status."""
        ch = Challenge(
            id=uuid4(),
            belief_id=uuid4(),
            challenger_id="did:test:challenger",
            target_layer=TrustLayer.L3_DOMAIN,
            reasoning="Evidence is outdated",
        )
        assert ch.status == ChallengeStatus.PENDING
        assert ch.target_layer == TrustLayer.L3_DOMAIN

    def test_challenge_status_values(self):
        """ChallengeStatus: PENDING, REVIEWING, UPHELD, REJECTED, EXPIRED."""
        assert ChallengeStatus.PENDING.value == "pending"
        assert ChallengeStatus.REVIEWING.value == "reviewing"
        assert ChallengeStatus.UPHELD.value == "upheld"
        assert ChallengeStatus.REJECTED.value == "rejected"
        assert ChallengeStatus.EXPIRED.value == "expired"


# ============================================================================
# Layer Navigation Tests
# ============================================================================


class TestLayerNavigation:
    """Test layer traversal helpers."""

    def test_next_layer_from_l1(self):
        assert _next_layer(TrustLayer.L1_PERSONAL) == TrustLayer.L2_FEDERATED

    def test_next_layer_from_l3(self):
        assert _next_layer(TrustLayer.L3_DOMAIN) == TrustLayer.L4_COMMUNAL

    def test_next_layer_from_l4_is_none(self):
        assert _next_layer(TrustLayer.L4_COMMUNAL) is None

    def test_prev_layer_from_l4(self):
        assert _prev_layer(TrustLayer.L4_COMMUNAL) == TrustLayer.L3_DOMAIN

    def test_prev_layer_from_l1_is_none(self):
        assert _prev_layer(TrustLayer.L1_PERSONAL) is None
