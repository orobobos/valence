"""
Connection state persistence for node recovery.

Implements Issue #111: State persistence and recovery after disconnection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

STATE_VERSION = 1


@dataclass
class ConnectionState:
    """
    Serializable connection state for persistence and recovery.

    This captures the essential state needed to recover after a
    disconnect/reconnect cycle.
    """

    version: int = STATE_VERSION
    node_id: str = ""
    saved_at: float = 0.0
    sequence_number: int = 0
    pending_acks: list[dict[str, Any]] = field(default_factory=list)
    message_queue: list[dict[str, Any]] = field(default_factory=list)
    seen_messages: list[str] = field(default_factory=list)
    failover_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "node_id": self.node_id,
            "saved_at": self.saved_at,
            "sequence_number": self.sequence_number,
            "pending_acks": self.pending_acks,
            "message_queue": self.message_queue,
            "seen_messages": self.seen_messages,
            "failover_states": self.failover_states,
            "stats": self.stats,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConnectionState:
        return cls(
            version=data.get("version", 1),
            node_id=data.get("node_id", ""),
            saved_at=data.get("saved_at", 0.0),
            sequence_number=data.get("sequence_number", 0),
            pending_acks=data.get("pending_acks", []),
            message_queue=data.get("message_queue", []),
            seen_messages=data.get("seen_messages", []),
            failover_states=data.get("failover_states", {}),
            stats=data.get("stats", {}),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> ConnectionState:
        return cls.from_dict(json.loads(json_str))
