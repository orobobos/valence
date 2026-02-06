"""
Pending message and acknowledgment tracking.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey


@dataclass
class PendingAck:
    """Tracks a message awaiting acknowledgment."""

    message_id: str
    recipient_id: str
    content: bytes
    recipient_public_key: X25519PublicKey
    sent_at: float
    router_id: str
    timeout_ms: int = 30000
    retries: int = 0
    max_retries: int = 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "recipient_id": self.recipient_id,
            "content": (self.content.hex() if isinstance(self.content, bytes) else self.content),
            "recipient_public_key_hex": self.recipient_public_key.public_bytes_raw().hex(),
            "sent_at": self.sent_at,
            "router_id": self.router_id,
            "timeout_ms": self.timeout_ms,
            "retries": self.retries,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PendingAck:
        content = data["content"]
        if isinstance(content, str):
            content = bytes.fromhex(content)

        pub_key_hex = data["recipient_public_key_hex"]
        pub_key = X25519PublicKey.from_public_bytes(bytes.fromhex(pub_key_hex))

        return cls(
            message_id=data["message_id"],
            recipient_id=data["recipient_id"],
            content=content,
            recipient_public_key=pub_key,
            sent_at=data["sent_at"],
            router_id=data["router_id"],
            timeout_ms=data.get("timeout_ms", 30000),
            retries=data.get("retries", 0),
            max_retries=data.get("max_retries", 2),
        )


@dataclass
class PendingMessage:
    """Message queued for delivery during failover."""

    message_id: str
    recipient_id: str
    content: bytes
    recipient_public_key: X25519PublicKey
    queued_at: float
    retries: int = 0
    max_retries: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "recipient_id": self.recipient_id,
            "content": (self.content.hex() if isinstance(self.content, bytes) else self.content),
            "recipient_public_key_hex": self.recipient_public_key.public_bytes_raw().hex(),
            "queued_at": self.queued_at,
            "retries": self.retries,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PendingMessage:
        content = data["content"]
        if isinstance(content, str):
            content = bytes.fromhex(content)

        pub_key_hex = data["recipient_public_key_hex"]
        pub_key = X25519PublicKey.from_public_bytes(bytes.fromhex(pub_key_hex))

        return cls(
            message_id=data["message_id"],
            recipient_id=data["recipient_id"],
            content=content,
            recipient_public_key=pub_key,
            queued_at=data["queued_at"],
            retries=data.get("retries", 0),
            max_retries=data.get("max_retries", 3),
        )
