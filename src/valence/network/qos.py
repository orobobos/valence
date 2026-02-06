"""
Contribution-based Quality of Service (QoS) for Valence network.

Prioritizes network traffic based on contribution reputation. Nodes that
contribute more (routing, uptime, belief quality, resource sharing, trust)
get better access under load.

Issue #276: Network: Contribution-based QoS with dynamic curve.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ContributionDimension(StrEnum):
    """Dimensions of node contribution to the network."""

    ROUTING_CAPACITY = "routing_capacity"
    UPTIME_RELIABILITY = "uptime_reliability"
    BELIEF_QUALITY = "belief_quality"
    RESOURCE_SHARING = "resource_sharing"
    TRUST_RECEIVED = "trust_received"


#: Default weights for each contribution dimension (sum to 1.0).
DEFAULT_DIMENSION_WEIGHTS: dict[ContributionDimension, float] = {
    ContributionDimension.ROUTING_CAPACITY: 0.25,
    ContributionDimension.UPTIME_RELIABILITY: 0.20,
    ContributionDimension.BELIEF_QUALITY: 0.20,
    ContributionDimension.RESOURCE_SHARING: 0.15,
    ContributionDimension.TRUST_RECEIVED: 0.20,
}

#: Minimum score for new users — they start here, not at zero.
NEW_USER_MINIMUM_SCORE = 0.1

#: Maximum possible contribution score.
MAX_CONTRIBUTION_SCORE = 1.0


@dataclass
class ContributionScore:
    """Aggregated contribution score for a node.

    Each dimension is a float in [0, 1]. The overall score is a weighted
    average of all dimensions.

    New users start with ``NEW_USER_MINIMUM_SCORE`` on all dimensions,
    ensuring they always receive minimum service.
    """

    node_id: str
    dimensions: dict[ContributionDimension, float] = field(default_factory=dict)
    weights: dict[ContributionDimension, float] = field(default_factory=lambda: dict(DEFAULT_DIMENSION_WEIGHTS))
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        # Ensure all dimensions exist with at least the minimum score.
        for dim in ContributionDimension:
            if dim not in self.dimensions:
                self.dimensions[dim] = NEW_USER_MINIMUM_SCORE

    @property
    def overall(self) -> float:
        """Weighted average of all contribution dimensions.

        Returns a value in [0, 1]. Clamps to ``NEW_USER_MINIMUM_SCORE``
        at the low end to ensure new users are never at zero.
        """
        total = 0.0
        weight_sum = 0.0
        for dim, weight in self.weights.items():
            total += self.dimensions.get(dim, NEW_USER_MINIMUM_SCORE) * weight
            weight_sum += weight
        if weight_sum == 0:
            return NEW_USER_MINIMUM_SCORE
        raw = total / weight_sum
        return max(raw, NEW_USER_MINIMUM_SCORE)

    def set_dimension(self, dim: ContributionDimension, value: float) -> None:
        """Set a dimension value, clamped to [0, 1]."""
        self.dimensions[dim] = max(0.0, min(1.0, value))
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "node_id": self.node_id,
            "overall": round(self.overall, 4),
            "dimensions": {dim.value: round(val, 4) for dim, val in self.dimensions.items()},
            "weights": {dim.value: round(w, 4) for dim, w in self.weights.items()},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContributionScore:
        """Deserialize from dictionary."""
        dimensions = {ContributionDimension(k): v for k, v in data.get("dimensions", {}).items()}
        weights = {ContributionDimension(k): v for k, v in data.get("weights", {}).items()}
        return cls(
            node_id=data["node_id"],
            dimensions=dimensions,
            weights=weights if weights else dict(DEFAULT_DIMENSION_WEIGHTS),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


class PriorityTier(StrEnum):
    """Priority tiers for message handling."""

    CRITICAL = "critical"  # Essential protocol messages
    HIGH = "high"  # High-contribution nodes
    NORMAL = "normal"  # Average contributors
    LOW = "low"  # Low contribution / new users
    MINIMUM = "minimum"  # Minimum service floor (never blocked)


#: Maps tiers to relative queue weights.
TIER_WEIGHTS: dict[PriorityTier, float] = {
    PriorityTier.CRITICAL: 10.0,
    PriorityTier.HIGH: 4.0,
    PriorityTier.NORMAL: 2.0,
    PriorityTier.LOW: 1.0,
    PriorityTier.MINIMUM: 0.5,
}


@dataclass
class QoSPolicy:
    """Dynamic deprioritization policy based on network load.

    The core idea: at low load, everyone is roughly equal. As load
    increases, the deprioritization curve steepens — contributors get
    prioritized more sharply.

    The curve function:
        priority = base + (score ^ steepness) * (1 - base)

    Where:
        - base is the minimum service floor (everyone gets at least this)
        - score is the contribution score [0, 1]
        - steepness is load-adaptive: higher load → steeper curve

    Steepness mapping (load → steepness):
        - load 0.0 → steepness 1.0 (linear, everyone roughly equal)
        - load 0.5 → steepness 2.0 (quadratic, contributors get a boost)
        - load 1.0 → steepness 4.0 (steep, strong prioritization)
    """

    #: Minimum service floor — even lowest-priority nodes get this fraction
    #: of service. Prevents starvation. Range [0, 1].
    min_service_floor: float = 0.1

    #: Maximum steepness of the deprioritization curve. Reached at full load.
    max_steepness: float = 4.0

    #: Minimum steepness (at zero load). 1.0 = linear/equal treatment.
    min_steepness: float = 1.0

    #: Grace period (seconds) for new nodes. During grace, they receive
    #: NORMAL priority regardless of contribution score.
    new_user_grace_period: float = 3600.0  # 1 hour

    #: Score threshold for HIGH priority tier.
    high_tier_threshold: float = 0.7

    #: Score threshold for NORMAL priority tier.
    normal_tier_threshold: float = 0.3

    #: Score threshold for LOW priority tier (below this → MINIMUM).
    low_tier_threshold: float = 0.1

    def compute_steepness(self, load_factor: float) -> float:
        """Compute curve steepness from current network load.

        Args:
            load_factor: Network load in [0, 1] where 0 = idle, 1 = full.

        Returns:
            Steepness exponent for the priority curve.
        """
        load_factor = max(0.0, min(1.0, load_factor))
        return self.min_steepness + (self.max_steepness - self.min_steepness) * (load_factor**2)

    def compute_priority(self, score: float, load_factor: float = 0.0) -> float:
        """Compute a node's priority value from its contribution score.

        Args:
            score: Contribution score in [0, 1].
            load_factor: Current network load in [0, 1].

        Returns:
            Priority value in [min_service_floor, 1.0].
        """
        score = max(0.0, min(1.0, score))
        steepness = self.compute_steepness(load_factor)
        base = self.min_service_floor
        return base + (score**steepness) * (1.0 - base)

    def assign_tier(self, score: float, *, is_new_user: bool = False) -> PriorityTier:
        """Assign a priority tier based on contribution score.

        Args:
            score: Contribution score in [0, 1].
            is_new_user: If True, assign NORMAL regardless of score
                         (grace period).

        Returns:
            The assigned ``PriorityTier``.
        """
        if is_new_user:
            return PriorityTier.NORMAL

        if score >= self.high_tier_threshold:
            return PriorityTier.HIGH
        elif score >= self.normal_tier_threshold:
            return PriorityTier.NORMAL
        elif score >= self.low_tier_threshold:
            return PriorityTier.LOW
        else:
            return PriorityTier.MINIMUM

    def to_dict(self) -> dict[str, Any]:
        """Serialize policy to dictionary."""
        return {
            "min_service_floor": self.min_service_floor,
            "max_steepness": self.max_steepness,
            "min_steepness": self.min_steepness,
            "new_user_grace_period": self.new_user_grace_period,
            "high_tier_threshold": self.high_tier_threshold,
            "normal_tier_threshold": self.normal_tier_threshold,
            "low_tier_threshold": self.low_tier_threshold,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QoSPolicy:
        """Deserialize from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
