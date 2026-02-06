"""Tests for contribution-based QoS data structures and policy.

Covers:
- ContributionScore: creation, dimensions, overall score, serialization
- QoSPolicy: steepness curve, priority computation, tier assignment
- PriorityTier: ordering and weights
- Edge cases: new users, clamping, empty weights

Issue #276: Network: Contribution-based QoS with dynamic curve.
"""

from __future__ import annotations

import time

from valence.network.qos import (
    DEFAULT_DIMENSION_WEIGHTS,
    NEW_USER_MINIMUM_SCORE,
    TIER_WEIGHTS,
    ContributionDimension,
    ContributionScore,
    PriorityTier,
    QoSPolicy,
)

# =============================================================================
# ContributionDimension
# =============================================================================


class TestContributionDimension:
    """Tests for the ContributionDimension enum."""

    def test_all_dimensions_exist(self) -> None:
        assert len(ContributionDimension) == 5

    def test_dimension_values(self) -> None:
        assert ContributionDimension.ROUTING_CAPACITY.value == "routing_capacity"
        assert ContributionDimension.UPTIME_RELIABILITY.value == "uptime_reliability"
        assert ContributionDimension.BELIEF_QUALITY.value == "belief_quality"
        assert ContributionDimension.RESOURCE_SHARING.value == "resource_sharing"
        assert ContributionDimension.TRUST_RECEIVED.value == "trust_received"

    def test_is_string_enum(self) -> None:
        for dim in ContributionDimension:
            assert isinstance(dim, str)
            assert isinstance(dim.value, str)


# =============================================================================
# ContributionScore
# =============================================================================


class TestContributionScore:
    """Tests for the ContributionScore dataclass."""

    def test_new_score_has_minimum_dimensions(self) -> None:
        """New scores should have all dimensions initialized to minimum."""
        score = ContributionScore(node_id="test-node")
        for dim in ContributionDimension:
            assert score.dimensions[dim] == NEW_USER_MINIMUM_SCORE

    def test_overall_score_minimum(self) -> None:
        """Overall score of a new user should be at least NEW_USER_MINIMUM_SCORE."""
        score = ContributionScore(node_id="test-node")
        assert score.overall >= NEW_USER_MINIMUM_SCORE

    def test_overall_weighted_average(self) -> None:
        """Overall should be a weighted average of dimensions."""
        score = ContributionScore(node_id="test-node")
        score.set_dimension(ContributionDimension.ROUTING_CAPACITY, 1.0)
        score.set_dimension(ContributionDimension.UPTIME_RELIABILITY, 0.5)
        score.set_dimension(ContributionDimension.BELIEF_QUALITY, 0.5)
        score.set_dimension(ContributionDimension.RESOURCE_SHARING, 0.0)
        score.set_dimension(ContributionDimension.TRUST_RECEIVED, 0.0)

        # Manual calculation with default weights
        expected = (
            1.0 * 0.25  # routing
            + 0.5 * 0.20  # uptime
            + 0.5 * 0.20  # belief
            + 0.0 * 0.15  # resource
            + 0.0 * 0.20  # trust
        )
        assert abs(score.overall - expected) < 1e-6

    def test_overall_max_score(self) -> None:
        """A fully contributing node should have overall = 1.0."""
        score = ContributionScore(node_id="test-node")
        for dim in ContributionDimension:
            score.set_dimension(dim, 1.0)
        assert abs(score.overall - 1.0) < 1e-6

    def test_set_dimension_clamps(self) -> None:
        """Values should be clamped to [0, 1]."""
        score = ContributionScore(node_id="test-node")
        score.set_dimension(ContributionDimension.ROUTING_CAPACITY, 2.0)
        assert score.dimensions[ContributionDimension.ROUTING_CAPACITY] == 1.0

        score.set_dimension(ContributionDimension.ROUTING_CAPACITY, -0.5)
        assert score.dimensions[ContributionDimension.ROUTING_CAPACITY] == 0.0

    def test_set_dimension_updates_timestamp(self) -> None:
        """Setting a dimension should update updated_at."""
        score = ContributionScore(node_id="test-node")
        old_ts = score.updated_at
        time.sleep(0.01)
        score.set_dimension(ContributionDimension.ROUTING_CAPACITY, 0.5)
        assert score.updated_at >= old_ts

    def test_overall_never_below_minimum(self) -> None:
        """Overall should never go below NEW_USER_MINIMUM_SCORE."""
        score = ContributionScore(node_id="test-node")
        for dim in ContributionDimension:
            score.set_dimension(dim, 0.0)
        # With all zeros, the weighted average is 0, but it clamps to minimum
        assert score.overall >= NEW_USER_MINIMUM_SCORE

    def test_overall_with_zero_weights(self) -> None:
        """Edge case: if all weights are zero, return minimum score."""
        score = ContributionScore(
            node_id="test-node",
            weights={dim: 0.0 for dim in ContributionDimension},
        )
        assert score.overall == NEW_USER_MINIMUM_SCORE

    def test_serialization_round_trip(self) -> None:
        """to_dict -> from_dict should preserve data."""
        score = ContributionScore(node_id="node-abc")
        score.set_dimension(ContributionDimension.ROUTING_CAPACITY, 0.8)
        score.set_dimension(ContributionDimension.BELIEF_QUALITY, 0.6)

        data = score.to_dict()
        restored = ContributionScore.from_dict(data)

        assert restored.node_id == score.node_id
        assert abs(restored.overall - score.overall) < 1e-3
        assert abs(restored.dimensions[ContributionDimension.ROUTING_CAPACITY] - score.dimensions[ContributionDimension.ROUTING_CAPACITY]) < 1e-3

    def test_to_dict_structure(self) -> None:
        """to_dict should produce expected keys."""
        score = ContributionScore(node_id="test")
        data = score.to_dict()
        assert "node_id" in data
        assert "overall" in data
        assert "dimensions" in data
        assert "weights" in data
        assert "created_at" in data
        assert "updated_at" in data

    def test_from_dict_with_missing_weights(self) -> None:
        """from_dict with no weights should use defaults."""
        data = {"node_id": "test", "dimensions": {}}
        score = ContributionScore.from_dict(data)
        assert score.weights == DEFAULT_DIMENSION_WEIGHTS

    def test_custom_weights(self) -> None:
        """Custom weights should affect overall score."""
        # All weight on routing_capacity
        weights = {dim: 0.0 for dim in ContributionDimension}
        weights[ContributionDimension.ROUTING_CAPACITY] = 1.0

        score = ContributionScore(node_id="test", weights=weights)
        score.set_dimension(ContributionDimension.ROUTING_CAPACITY, 0.9)
        score.set_dimension(ContributionDimension.BELIEF_QUALITY, 0.1)

        # Overall should be dominated by routing_capacity
        assert abs(score.overall - 0.9) < 1e-6


# =============================================================================
# QoSPolicy
# =============================================================================


class TestQoSPolicy:
    """Tests for the QoSPolicy dynamic curve."""

    def test_default_policy_values(self) -> None:
        policy = QoSPolicy()
        assert policy.min_service_floor == 0.1
        assert policy.max_steepness == 4.0
        assert policy.min_steepness == 1.0

    def test_steepness_at_zero_load(self) -> None:
        """At zero load, steepness should be min (linear)."""
        policy = QoSPolicy()
        assert policy.compute_steepness(0.0) == policy.min_steepness

    def test_steepness_at_full_load(self) -> None:
        """At full load, steepness should be max."""
        policy = QoSPolicy()
        assert policy.compute_steepness(1.0) == policy.max_steepness

    def test_steepness_increases_with_load(self) -> None:
        """Steepness should monotonically increase with load."""
        policy = QoSPolicy()
        prev = 0.0
        for load in [0.0, 0.25, 0.5, 0.75, 1.0]:
            steep = policy.compute_steepness(load)
            assert steep >= prev
            prev = steep

    def test_steepness_clamps_load(self) -> None:
        """Load factor should be clamped to [0, 1]."""
        policy = QoSPolicy()
        assert policy.compute_steepness(-0.5) == policy.compute_steepness(0.0)
        assert policy.compute_steepness(1.5) == policy.compute_steepness(1.0)

    def test_priority_at_zero_load(self) -> None:
        """At zero load with steepness=1 (linear), priority is proportional."""
        policy = QoSPolicy()
        # Score 1.0: priority = 0.1 + (1.0^1.0) * 0.9 = 1.0
        assert abs(policy.compute_priority(1.0, 0.0) - 1.0) < 1e-6
        # Score 0.5: priority = 0.1 + (0.5^1.0) * 0.9 = 0.55
        assert abs(policy.compute_priority(0.5, 0.0) - 0.55) < 1e-6

    def test_priority_minimum_floor(self) -> None:
        """Priority should never go below min_service_floor."""
        policy = QoSPolicy()
        assert policy.compute_priority(0.0, 0.0) >= policy.min_service_floor
        assert policy.compute_priority(0.0, 1.0) >= policy.min_service_floor

    def test_priority_max_at_full_contribution(self) -> None:
        """Score=1.0 should always give priority=1.0 regardless of load."""
        policy = QoSPolicy()
        for load in [0.0, 0.5, 1.0]:
            assert abs(policy.compute_priority(1.0, load) - 1.0) < 1e-6

    def test_priority_decreases_with_lower_score(self) -> None:
        """Higher score → higher priority at any load."""
        policy = QoSPolicy()
        for load in [0.0, 0.5, 1.0]:
            high = policy.compute_priority(0.9, load)
            low = policy.compute_priority(0.2, load)
            assert high > low

    def test_high_load_steepens_curve(self) -> None:
        """Under high load, low scorers lose more relative to high scorers.

        The steep curve (exponent > 1) deprioritizes low scorers more.
        Specifically: the ratio of high/low priority should increase.
        """
        policy = QoSPolicy()
        score_high, score_low = 0.8, 0.2

        ratio_low_load = policy.compute_priority(score_high, 0.0) / policy.compute_priority(score_low, 0.0)
        ratio_high_load = policy.compute_priority(score_high, 1.0) / policy.compute_priority(score_low, 1.0)

        assert ratio_high_load > ratio_low_load

    def test_priority_clamps_score(self) -> None:
        """Score should be clamped to [0, 1]."""
        policy = QoSPolicy()
        assert policy.compute_priority(-0.5, 0.0) == policy.compute_priority(0.0, 0.0)
        assert policy.compute_priority(1.5, 0.0) == policy.compute_priority(1.0, 0.0)

    def test_assign_tier_high(self) -> None:
        policy = QoSPolicy()
        assert policy.assign_tier(0.8) == PriorityTier.HIGH

    def test_assign_tier_normal(self) -> None:
        policy = QoSPolicy()
        assert policy.assign_tier(0.5) == PriorityTier.NORMAL

    def test_assign_tier_low(self) -> None:
        policy = QoSPolicy()
        assert policy.assign_tier(0.15) == PriorityTier.LOW

    def test_assign_tier_minimum(self) -> None:
        policy = QoSPolicy()
        assert policy.assign_tier(0.05) == PriorityTier.MINIMUM

    def test_assign_tier_new_user_gets_normal(self) -> None:
        """New users always get NORMAL tier during grace period."""
        policy = QoSPolicy()
        assert policy.assign_tier(0.0, is_new_user=True) == PriorityTier.NORMAL
        assert policy.assign_tier(0.05, is_new_user=True) == PriorityTier.NORMAL

    def test_assign_tier_boundary_high(self) -> None:
        """Exactly at the high threshold should be HIGH."""
        policy = QoSPolicy()
        assert policy.assign_tier(policy.high_tier_threshold) == PriorityTier.HIGH

    def test_assign_tier_boundary_normal(self) -> None:
        """Exactly at the normal threshold should be NORMAL."""
        policy = QoSPolicy()
        assert policy.assign_tier(policy.normal_tier_threshold) == PriorityTier.NORMAL

    def test_assign_tier_boundary_low(self) -> None:
        """Exactly at the low threshold should be LOW."""
        policy = QoSPolicy()
        assert policy.assign_tier(policy.low_tier_threshold) == PriorityTier.LOW

    def test_policy_serialization_round_trip(self) -> None:
        policy = QoSPolicy(min_service_floor=0.2, max_steepness=5.0)
        data = policy.to_dict()
        restored = QoSPolicy.from_dict(data)
        assert restored.min_service_floor == policy.min_service_floor
        assert restored.max_steepness == policy.max_steepness

    def test_policy_from_dict_ignores_unknown(self) -> None:
        """from_dict should ignore unknown keys."""
        data = {"min_service_floor": 0.2, "unknown_field": 42}
        policy = QoSPolicy.from_dict(data)
        assert policy.min_service_floor == 0.2


# =============================================================================
# PriorityTier
# =============================================================================


class TestPriorityTier:
    """Tests for PriorityTier enum and tier weights."""

    def test_all_tiers_exist(self) -> None:
        assert len(PriorityTier) == 5

    def test_tier_weight_ordering(self) -> None:
        """Higher tiers should have higher weights."""
        assert TIER_WEIGHTS[PriorityTier.CRITICAL] > TIER_WEIGHTS[PriorityTier.HIGH]
        assert TIER_WEIGHTS[PriorityTier.HIGH] > TIER_WEIGHTS[PriorityTier.NORMAL]
        assert TIER_WEIGHTS[PriorityTier.NORMAL] > TIER_WEIGHTS[PriorityTier.LOW]
        assert TIER_WEIGHTS[PriorityTier.LOW] > TIER_WEIGHTS[PriorityTier.MINIMUM]

    def test_all_tiers_have_weights(self) -> None:
        for tier in PriorityTier:
            assert tier in TIER_WEIGHTS

    def test_minimum_tier_weight_positive(self) -> None:
        """Even MINIMUM tier should get some service (non-zero weight)."""
        assert TIER_WEIGHTS[PriorityTier.MINIMUM] > 0

    def test_is_string_enum(self) -> None:
        for tier in PriorityTier:
            assert isinstance(tier, str)


# =============================================================================
# Default weights
# =============================================================================


class TestDefaultWeights:
    """Tests for DEFAULT_DIMENSION_WEIGHTS."""

    def test_weights_sum_to_one(self) -> None:
        total = sum(DEFAULT_DIMENSION_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-6

    def test_all_dimensions_have_weights(self) -> None:
        for dim in ContributionDimension:
            assert dim in DEFAULT_DIMENSION_WEIGHTS

    def test_all_weights_positive(self) -> None:
        for weight in DEFAULT_DIMENSION_WEIGHTS.values():
            assert weight > 0
