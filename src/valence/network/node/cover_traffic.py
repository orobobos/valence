"""
Cover traffic configuration for traffic analysis resistance.

Implements Issue #116: Cover traffic generation.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class CoverTrafficConfig:
    """Configuration for cover traffic generation."""

    enabled: bool = False
    rate_per_minute: float = 2.0
    idle_threshold_seconds: float = 30.0
    pad_messages: bool = True
    target_peers: list[str] = field(default_factory=list)
    randomize_timing: bool = True
    min_interval_seconds: float = 15.0
    max_interval_seconds: float = 60.0

    def get_next_interval(self) -> float:
        if not self.enabled:
            return float("inf")

        base_interval = 60.0 / self.rate_per_minute if self.rate_per_minute > 0 else 60.0

        if self.randomize_timing:
            interval = random.expovariate(1.0 / base_interval)
            interval = max(self.min_interval_seconds, min(self.max_interval_seconds, interval))
        else:
            interval = base_interval

        return interval
