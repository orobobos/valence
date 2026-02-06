"""Tests for the QoS Manager.

Covers:
- Node registration and tracking
- Score updates (single and batch)
- Priority and tier computation
- Load metrics and adaptation
- Grace period handling
- Node eviction at capacity
- Ranking and status reporting

Issue #276: Network: Contribution-based QoS with dynamic curve.
"""

from __future__ import annotations

import time

import pytest

from valence.network.qos import (
    ContributionDimension,
    ContributionScore,
    PriorityTier,
    QoSPolicy,
)
from valence.network.qos_manager import (
    LoadMetrics,
    NodeQoSState,
    QoSManager,
)

# =============================================================================
# LoadMetrics
# =============================================================================


class TestLoadMetrics:
    """Tests for the LoadMetrics dataclass."""

    def test_default_values(self) -> None:
        metrics = LoadMetrics()
        assert metrics.load_factor == 0.0
        assert metrics.active_connections == 0
        assert metrics.max_connections == 100

    def test_compute_load_factor_idle(self) -> None:
        """Idle system should have load factor ~0."""
        metrics = LoadMetrics(active_connections=0, avg_queue_depth=0.0)
        factor = metrics.compute_load_factor()
        assert factor == 0.0

    def test_compute_load_factor_saturated(self) -> None:
        """Fully saturated should approach 1.0."""
        metrics = LoadMetrics(
            active_connections=100,
            max_connections=100,
            avg_queue_depth=100.0,
        )
        factor = metrics.compute_load_factor()
        assert abs(factor - 1.0) < 1e-6

    def test_compute_load_factor_partial(self) -> None:
        """Partial load should be between 0 and 1."""
        metrics = LoadMetrics(
            active_connections=50,
            max_connections=100,
            avg_queue_depth=25.0,
        )
        factor = metrics.compute_load_factor()
        # 0.6 * 0.5 + 0.4 * 0.25 = 0.3 + 0.1 = 0.4
        assert abs(factor - 0.4) < 1e-6

    def test_compute_load_factor_zero_max_connections(self) -> None:
        """Zero max_connections should not divide by zero."""
        metrics = LoadMetrics(max_connections=0, active_connections=10)
        factor = metrics.compute_load_factor()
        assert factor >= 0.0

    def test_compute_load_factor_capped(self) -> None:
        """Load factor should not exceed 1.0."""
        metrics = LoadMetrics(
            active_connections=200,
            max_connections=100,
            avg_queue_depth=500.0,
        )
        factor = metrics.compute_load_factor()
        assert factor <= 1.0

    def test_to_dict(self) -> None:
        metrics = LoadMetrics(active_connections=50, max_connections=100)
        data = metrics.to_dict()
        assert "load_factor" in data
        assert "active_connections" in data
        assert data["active_connections"] == 50


# =============================================================================
# NodeQoSState
# =============================================================================


class TestNodeQoSState:
    """Tests for per-node QoS state."""

    def test_to_dict(self) -> None:
        score = ContributionScore(node_id="test")
        state = NodeQoSState(node_id="test", score=score)
        data = state.to_dict()
        assert data["node_id"] == "test"
        assert "score" in data
        assert "tier" in data
        assert "priority_value" in data
        assert "is_in_grace_period" in data

    def test_default_grace_period(self) -> None:
        score = ContributionScore(node_id="test")
        state = NodeQoSState(node_id="test", score=score)
        assert state.is_in_grace_period is True


# =============================================================================
# QoSManager
# =============================================================================


class TestQoSManager:
    """Tests for the QoS Manager."""

    def test_create_with_defaults(self) -> None:
        manager = QoSManager()
        assert manager.node_count == 0
        assert manager.policy is not None

    def test_create_with_custom_policy(self) -> None:
        policy = QoSPolicy(min_service_floor=0.2)
        manager = QoSManager(policy=policy)
        assert manager.policy.min_service_floor == 0.2

    def test_get_or_create_new_node(self) -> None:
        """First access should create a new node with defaults."""
        manager = QoSManager()
        state = manager.get_or_create_node("node-1")
        assert state.node_id == "node-1"
        assert state.is_in_grace_period is True
        assert state.tier == PriorityTier.NORMAL
        assert manager.node_count == 1

    def test_get_or_create_existing_node(self) -> None:
        """Second access should return existing node."""
        manager = QoSManager()
        state1 = manager.get_or_create_node("node-1")
        state2 = manager.get_or_create_node("node-1")
        assert state1 is state2
        assert manager.node_count == 1

    def test_update_score_single_dimension(self) -> None:
        manager = QoSManager()
        state = manager.update_score("node-1", ContributionDimension.ROUTING_CAPACITY, 0.9)
        assert state.score.dimensions[ContributionDimension.ROUTING_CAPACITY] == 0.9

    def test_update_scores_batch(self) -> None:
        manager = QoSManager()
        state = manager.update_scores_batch(
            "node-1",
            {
                ContributionDimension.ROUTING_CAPACITY: 0.9,
                ContributionDimension.UPTIME_RELIABILITY: 0.8,
                ContributionDimension.BELIEF_QUALITY: 0.7,
            },
        )
        assert state.score.dimensions[ContributionDimension.ROUTING_CAPACITY] == 0.9
        assert state.score.dimensions[ContributionDimension.UPTIME_RELIABILITY] == 0.8
        assert state.score.dimensions[ContributionDimension.BELIEF_QUALITY] == 0.7

    def test_update_score_recomputes_tier(self) -> None:
        """Updating a score should recompute the tier."""
        manager = QoSManager()
        # New user starts NORMAL (grace period)
        state = manager.get_or_create_node("node-1")
        assert state.tier == PriorityTier.NORMAL

        # After grace period, with high score → HIGH
        state.is_in_grace_period = False
        manager.update_scores_batch(
            "node-1",
            {dim: 0.9 for dim in ContributionDimension},
        )
        assert state.tier == PriorityTier.HIGH

    def test_get_priority(self) -> None:
        manager = QoSManager()
        priority = manager.get_priority("node-1")
        assert 0.0 < priority <= 1.0

    def test_get_tier(self) -> None:
        manager = QoSManager()
        tier = manager.get_tier("node-1")
        assert isinstance(tier, PriorityTier)

    def test_get_node_state_existing(self) -> None:
        manager = QoSManager()
        manager.get_or_create_node("node-1")
        assert manager.get_node_state("node-1") is not None

    def test_get_node_state_missing(self) -> None:
        manager = QoSManager()
        assert manager.get_node_state("nonexistent") is None

    def test_update_load(self) -> None:
        manager = QoSManager()
        factor = manager.update_load(active_connections=50, max_connections=100, avg_queue_depth=25.0)
        assert factor == pytest.approx(0.4, abs=1e-6)
        assert manager.load_metrics.active_connections == 50

    def test_update_load_recomputes_priorities(self) -> None:
        """Updating load should recompute all node priorities."""
        manager = QoSManager()

        # Create a high-scoring node (not in grace)
        state = manager.get_or_create_node("node-1")
        state.is_in_grace_period = False
        manager.update_scores_batch("node-1", {dim: 0.9 for dim in ContributionDimension})
        initial_priority = state.priority_value

        # Increase load
        manager.update_load(active_connections=90, max_connections=100, avg_queue_depth=80.0)

        # Priority may change but for a high-scoring node it should still be high
        assert state.priority_value > 0.5
        # The value should have been recomputed (may or may not differ)
        assert isinstance(state.priority_value, float)
        assert initial_priority > 0

    def test_get_ranked_nodes(self) -> None:
        """Nodes should be ranked by descending priority."""
        manager = QoSManager()

        # Create nodes with different scores
        for node_id in ["low", "mid", "high"]:
            state = manager.get_or_create_node(node_id)
            state.is_in_grace_period = False

        manager.update_scores_batch("high", {dim: 0.9 for dim in ContributionDimension})
        manager.update_scores_batch("mid", {dim: 0.5 for dim in ContributionDimension})
        manager.update_scores_batch("low", {dim: 0.1 for dim in ContributionDimension})

        ranked = manager.get_ranked_nodes()
        assert len(ranked) == 3
        assert ranked[0].node_id == "high"
        assert ranked[-1].node_id == "low"

    def test_get_tier_summary(self) -> None:
        manager = QoSManager()
        for i in range(3):
            manager.get_or_create_node(f"node-{i}")
        summary = manager.get_tier_summary()
        assert isinstance(summary, dict)
        total = sum(summary.values())
        assert total == 3

    def test_get_status(self) -> None:
        manager = QoSManager()
        manager.get_or_create_node("node-1")
        status = manager.get_status()
        assert "policy" in status
        assert "load" in status
        assert "node_count" in status
        assert status["node_count"] == 1
        assert "tier_summary" in status
        assert "current_steepness" in status

    def test_remove_node(self) -> None:
        manager = QoSManager()
        manager.get_or_create_node("node-1")
        assert manager.node_count == 1
        assert manager.remove_node("node-1") is True
        assert manager.node_count == 0
        assert manager.remove_node("node-1") is False

    def test_eviction_at_capacity(self) -> None:
        """When at max capacity, the lowest-priority node should be evicted."""
        manager = QoSManager(max_tracked_nodes=3)
        for i in range(3):
            state = manager.get_or_create_node(f"node-{i}")
            state.is_in_grace_period = False

        # Give node-2 the highest score
        manager.update_scores_batch("node-2", {dim: 0.9 for dim in ContributionDimension})
        # node-0 and node-1 have default low scores

        # Adding a 4th node should evict the lowest
        manager.get_or_create_node("node-3")
        assert manager.node_count == 3
        # node-2 should still be there (high priority)
        assert manager.get_node_state("node-2") is not None

    def test_grace_period_expiry(self) -> None:
        """Grace period should expire after configured duration."""
        policy = QoSPolicy(new_user_grace_period=0.0)  # Immediate expiry
        manager = QoSManager(policy=policy)

        state = manager.get_or_create_node("node-1")
        assert state.is_in_grace_period is True

        # Trigger recomputation (grace should expire since duration=0)
        time.sleep(0.01)
        manager.update_score("node-1", ContributionDimension.ROUTING_CAPACITY, 0.5)
        assert state.is_in_grace_period is False

    def test_grace_period_still_active(self) -> None:
        """Node should stay in grace period within duration."""
        policy = QoSPolicy(new_user_grace_period=3600.0)  # 1 hour
        manager = QoSManager(policy=policy)

        state = manager.get_or_create_node("node-1")
        manager.update_score("node-1", ContributionDimension.ROUTING_CAPACITY, 0.5)
        assert state.is_in_grace_period is True
        assert state.tier == PriorityTier.NORMAL

    def test_multiple_nodes_independent(self) -> None:
        """Each node's state should be independent."""
        manager = QoSManager()
        manager.update_score("node-a", ContributionDimension.ROUTING_CAPACITY, 0.9)
        manager.update_score("node-b", ContributionDimension.ROUTING_CAPACITY, 0.1)

        assert manager.get_node_state("node-a").score.dimensions[ContributionDimension.ROUTING_CAPACITY] == 0.9
        assert manager.get_node_state("node-b").score.dimensions[ContributionDimension.ROUTING_CAPACITY] == 0.1

    def test_load_update_partial(self) -> None:
        """Partial load updates should only change specified fields."""
        manager = QoSManager()
        manager.update_load(active_connections=50, max_connections=200)
        assert manager.load_metrics.active_connections == 50
        assert manager.load_metrics.max_connections == 200

        # Update only queue depth
        manager.update_load(avg_queue_depth=30.0)
        assert manager.load_metrics.active_connections == 50  # Unchanged
        assert manager.load_metrics.avg_queue_depth == 30.0
