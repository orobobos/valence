"""
QoS Manager — orchestrates contribution-based traffic prioritization.

Maintains per-node contribution scores, computes priorities using the
dynamic deprioritization curve, and handles new-user grace periods.

The manager adapts to network conditions:
- Low load: flat curve, everyone roughly equal
- High load: steep curve, heavy contributors prioritized
- Attack conditions: naturally rate-limits bad actors (can't attack
  AND contribute meaningfully at the same time)

Issue #276: Network: Contribution-based QoS with dynamic curve.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .qos import (
    ContributionDimension,
    ContributionScore,
    PriorityTier,
    QoSPolicy,
)

logger = logging.getLogger(__name__)


@dataclass
class LoadMetrics:
    """Current network load metrics used for curve adaptation.

    These metrics come from network feedback: queue depth, latency,
    peer reports, etc.
    """

    #: Overall load factor [0, 1].
    load_factor: float = 0.0

    #: Average message queue depth across connections.
    avg_queue_depth: float = 0.0

    #: Average round-trip latency in milliseconds.
    avg_latency_ms: float = 0.0

    #: Number of active peer connections.
    active_connections: int = 0

    #: Maximum capacity (connections).
    max_connections: int = 100

    #: Timestamp of last update.
    updated_at: float = field(default_factory=time.time)

    def compute_load_factor(self) -> float:
        """Derive a composite load factor from metrics.

        Combines connection saturation and queue depth into a single
        factor in [0, 1].
        """
        if self.max_connections <= 0:
            connection_load = 0.0
        else:
            connection_load = min(1.0, self.active_connections / self.max_connections)

        # Queue depth: assume 100 = saturated (configurable via subclass).
        queue_load = min(1.0, self.avg_queue_depth / 100.0)

        # Weighted composite: connections matter more than queue depth.
        composite = 0.6 * connection_load + 0.4 * queue_load
        self.load_factor = max(0.0, min(1.0, composite))
        self.updated_at = time.time()
        return self.load_factor

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "load_factor": round(self.load_factor, 4),
            "avg_queue_depth": round(self.avg_queue_depth, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "active_connections": self.active_connections,
            "max_connections": self.max_connections,
            "updated_at": self.updated_at,
        }


@dataclass
class NodeQoSState:
    """Per-node QoS state including score, tier, and grace tracking."""

    node_id: str
    score: ContributionScore
    tier: PriorityTier = PriorityTier.NORMAL
    priority_value: float = 0.5
    first_seen: float = field(default_factory=time.time)
    is_in_grace_period: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "node_id": self.node_id,
            "score": self.score.to_dict(),
            "tier": self.tier.value,
            "priority_value": round(self.priority_value, 4),
            "first_seen": self.first_seen,
            "is_in_grace_period": self.is_in_grace_period,
        }


class QoSManager:
    """Manages contribution-based QoS for all known nodes.

    Responsibilities:
    - Track contribution scores per node
    - Compute dynamic priorities based on load
    - Handle new-user grace periods
    - Provide priority rankings for message scheduling

    Usage::

        manager = QoSManager()

        # Update a node's contribution
        manager.update_score("node-abc", ContributionDimension.UPTIME_RELIABILITY, 0.9)

        # Get priority for scheduling
        priority = manager.get_priority("node-abc")

        # Update network load (from monitoring)
        manager.update_load(active_connections=80, max_connections=100, avg_queue_depth=45)

        # Get ranked nodes for scheduling
        ranked = manager.get_ranked_nodes()
    """

    def __init__(
        self,
        policy: QoSPolicy | None = None,
        *,
        max_tracked_nodes: int = 10000,
    ) -> None:
        self._policy = policy or QoSPolicy()
        self._nodes: dict[str, NodeQoSState] = {}
        self._load = LoadMetrics()
        self._max_tracked_nodes = max_tracked_nodes

    @property
    def policy(self) -> QoSPolicy:
        """Current QoS policy."""
        return self._policy

    @property
    def load_metrics(self) -> LoadMetrics:
        """Current load metrics."""
        return self._load

    @property
    def node_count(self) -> int:
        """Number of tracked nodes."""
        return len(self._nodes)

    def get_or_create_node(self, node_id: str) -> NodeQoSState:
        """Get existing node state or create new one with defaults.

        New nodes start with ``NEW_USER_MINIMUM_SCORE`` on all dimensions
        and enter a grace period where they receive NORMAL priority.
        """
        if node_id in self._nodes:
            return self._nodes[node_id]

        # Evict oldest node if at capacity.
        if len(self._nodes) >= self._max_tracked_nodes:
            self._evict_oldest()

        score = ContributionScore(node_id=node_id)
        now = time.time()
        state = NodeQoSState(
            node_id=node_id,
            score=score,
            tier=PriorityTier.NORMAL,
            priority_value=self._policy.compute_priority(score.overall, self._load.load_factor),
            first_seen=now,
            is_in_grace_period=True,
        )
        self._nodes[node_id] = state
        logger.debug("New node registered for QoS: %s (grace period active)", node_id)
        return state

    def update_score(
        self,
        node_id: str,
        dimension: ContributionDimension,
        value: float,
    ) -> NodeQoSState:
        """Update a contribution dimension for a node.

        Triggers recomputation of priority and tier.

        Args:
            node_id: The node identifier.
            dimension: Which contribution dimension to update.
            value: New value in [0, 1].

        Returns:
            Updated ``NodeQoSState``.
        """
        state = self.get_or_create_node(node_id)
        state.score.set_dimension(dimension, value)
        self._recompute_node(state)
        return state

    def update_scores_batch(
        self,
        node_id: str,
        updates: dict[ContributionDimension, float],
    ) -> NodeQoSState:
        """Update multiple dimensions at once for efficiency.

        Args:
            node_id: The node identifier.
            updates: Mapping of dimensions to new values.

        Returns:
            Updated ``NodeQoSState``.
        """
        state = self.get_or_create_node(node_id)
        for dim, value in updates.items():
            state.score.set_dimension(dim, value)
        self._recompute_node(state)
        return state

    def get_priority(self, node_id: str) -> float:
        """Get the current priority value for a node.

        Returns a value in [min_service_floor, 1.0]. Higher = more priority.
        Unknown nodes get default (grace period) priority.
        """
        state = self.get_or_create_node(node_id)
        return state.priority_value

    def get_tier(self, node_id: str) -> PriorityTier:
        """Get the current priority tier for a node."""
        state = self.get_or_create_node(node_id)
        return state.tier

    def get_node_state(self, node_id: str) -> NodeQoSState | None:
        """Get full state for a node, or None if untracked."""
        return self._nodes.get(node_id)

    def update_load(
        self,
        *,
        active_connections: int | None = None,
        max_connections: int | None = None,
        avg_queue_depth: float | None = None,
        avg_latency_ms: float | None = None,
    ) -> float:
        """Update network load metrics and recompute all priorities.

        Args:
            active_connections: Current number of active connections.
            max_connections: Maximum connection capacity.
            avg_queue_depth: Average message queue depth.
            avg_latency_ms: Average round-trip latency in ms.

        Returns:
            Updated load factor.
        """
        if active_connections is not None:
            self._load.active_connections = active_connections
        if max_connections is not None:
            self._load.max_connections = max_connections
        if avg_queue_depth is not None:
            self._load.avg_queue_depth = avg_queue_depth
        if avg_latency_ms is not None:
            self._load.avg_latency_ms = avg_latency_ms

        load_factor = self._load.compute_load_factor()
        self._recompute_all()
        logger.debug(
            "Load updated: factor=%.2f, connections=%d/%d, queue=%.1f",
            load_factor,
            self._load.active_connections,
            self._load.max_connections,
            self._load.avg_queue_depth,
        )
        return load_factor

    def get_ranked_nodes(self) -> list[NodeQoSState]:
        """Get all tracked nodes ranked by priority (highest first).

        Returns:
            List of ``NodeQoSState`` sorted by descending priority.
        """
        return sorted(
            self._nodes.values(),
            key=lambda s: s.priority_value,
            reverse=True,
        )

    def get_tier_summary(self) -> dict[str, int]:
        """Get count of nodes in each tier.

        Returns:
            Mapping of tier name to node count.
        """
        counts: dict[str, int] = {tier.value: 0 for tier in PriorityTier}
        for state in self._nodes.values():
            counts[state.tier.value] += 1
        return counts

    def get_status(self) -> dict[str, Any]:
        """Get full QoS system status for CLI/monitoring.

        Returns:
            Dictionary with policy, load, tier summary, and stats.
        """
        tier_summary = self.get_tier_summary()
        return {
            "policy": self._policy.to_dict(),
            "load": self._load.to_dict(),
            "node_count": len(self._nodes),
            "tier_summary": tier_summary,
            "current_steepness": round(self._policy.compute_steepness(self._load.load_factor), 4),
        }

    def remove_node(self, node_id: str) -> bool:
        """Remove a node from QoS tracking.

        Returns:
            True if the node was removed, False if not found.
        """
        if node_id in self._nodes:
            del self._nodes[node_id]
            return True
        return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _recompute_node(self, state: NodeQoSState) -> None:
        """Recompute priority and tier for a single node."""
        now = time.time()
        age = now - state.first_seen

        # Check grace period expiry.
        if state.is_in_grace_period:
            if age > self._policy.new_user_grace_period:
                state.is_in_grace_period = False
                logger.debug(
                    "Grace period expired for node %s after %.0fs",
                    state.node_id,
                    age,
                )

        overall = state.score.overall
        state.priority_value = self._policy.compute_priority(overall, self._load.load_factor)
        state.tier = self._policy.assign_tier(overall, is_new_user=state.is_in_grace_period)

    def _recompute_all(self) -> None:
        """Recompute priorities for all tracked nodes."""
        for state in self._nodes.values():
            self._recompute_node(state)

    def _evict_oldest(self) -> None:
        """Evict the oldest node with the lowest priority."""
        if not self._nodes:
            return
        # Evict the node with the lowest priority, breaking ties by oldest.
        victim = min(
            self._nodes.values(),
            key=lambda s: (s.priority_value, -s.first_seen),
        )
        del self._nodes[victim.node_id]
        logger.debug("Evicted node %s from QoS tracking (capacity limit)", victim.node_id)
