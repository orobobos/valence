"""
Failover state tracking for router connections.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .pending import PendingMessage


@dataclass
class FailoverState:
    """Tracks failover state for a router."""

    router_id: str
    failed_at: float
    fail_count: int
    cooldown_until: float
    queued_messages: list[PendingMessage] = field(default_factory=list)

    def is_in_cooldown(self) -> bool:
        return time.time() < self.cooldown_until

    def remaining_cooldown(self) -> float:
        return max(0, self.cooldown_until - time.time())

    def to_dict(self) -> dict[str, Any]:
        return {
            "router_id": self.router_id,
            "failed_at": self.failed_at,
            "fail_count": self.fail_count,
            "cooldown_until": self.cooldown_until,
            "queued_messages": [msg.to_dict() for msg in self.queued_messages],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FailoverState:
        queued = [PendingMessage.from_dict(msg_data) for msg_data in data.get("queued_messages", [])]
        return cls(
            router_id=data["router_id"],
            failed_at=data["failed_at"],
            fail_count=data["fail_count"],
            cooldown_until=data["cooldown_until"],
            queued_messages=queued,
        )
