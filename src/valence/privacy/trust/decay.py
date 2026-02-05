"""Trust decay models and configuration.

Defines how trust decays over time when not refreshed.
"""

from __future__ import annotations

from datetime import timedelta
from enum import Enum


# Clock skew tolerance for temporal comparisons across federation nodes.
# This accounts for clock drift between nodes that may cause false expiration
# or premature rejection of otherwise valid trust edges.
# Default: 5 minutes (300 seconds). Configurable via environment or settings.
CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)


class DecayModel(str, Enum):
    """Models for how trust decays over time."""

    NONE = "none"  # No decay - trust stays constant
    LINEAR = "linear"  # trust - (decay_rate * days)
    EXPONENTIAL = "exponential"  # trust * (retention_rate ^ days)

    @classmethod
    def from_string(cls, value: str) -> DecayModel:
        """Convert string to DecayModel, case-insensitive."""
        try:
            return cls(value.lower())
        except ValueError:
            return cls.EXPONENTIAL  # Default
