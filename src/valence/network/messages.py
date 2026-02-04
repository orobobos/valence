"""
Message formats for Valence Relay Protocol.

RelayMessage: What routers see (encrypted payload, routing info)
DeliverPayload: What recipients see after decryption (actual content)
"""

from dataclasses import dataclass, field
from typing import Optional
import json
import time
import uuid


@dataclass
class RelayMessage:
    """
    Message format for router relay - router sees only this.
    
    The payload is an encrypted blob that routers cannot decrypt.
    Routers only need next_hop to forward the message.
    """
    message_id: str
    next_hop: str  # Recipient node ID or "local"
    payload: str   # Encrypted blob (hex), router cannot decrypt
    ttl: int
    timestamp: float
    
    @classmethod
    def create(
        cls,
        next_hop: str,
        payload: str,
        ttl: int = 10,
        message_id: Optional[str] = None,
        timestamp: Optional[float] = None
    ) -> "RelayMessage":
        """Create a new relay message with auto-generated ID and timestamp."""
        return cls(
            message_id=message_id or str(uuid.uuid4()),
            next_hop=next_hop,
            payload=payload,
            ttl=ttl,
            timestamp=timestamp or time.time()
        )
    
    def to_dict(self) -> dict:
        """Serialize to dict for transmission."""
        return {
            "type": "relay",
            "message_id": self.message_id,
            "next_hop": self.next_hop,
            "payload": self.payload,
            "ttl": self.ttl,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "RelayMessage":
        """Deserialize from dict."""
        return cls(
            message_id=data["message_id"],
            next_hop=data["next_hop"],
            payload=data["payload"],
            ttl=data["ttl"],
            timestamp=data["timestamp"]
        )
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_json(cls, json_str: str) -> "RelayMessage":
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))


@dataclass
class DeliverPayload:
    """
    Inner payload - only recipient can decrypt and see this.
    
    Contains the actual message content, sender identity,
    and optional reply path for responses.
    """
    sender_id: str
    message_type: str  # "belief", "query", "response", "ack"
    content: dict
    reply_path: Optional[str] = None  # Encrypted return path
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "sender_id": self.sender_id,
            "message_type": self.message_type,
            "content": self.content,
            "reply_path": self.reply_path,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "DeliverPayload":
        """Deserialize from dict."""
        return cls(
            sender_id=data["sender_id"],
            message_type=data["message_type"],
            content=data["content"],
            reply_path=data.get("reply_path"),
            timestamp=data.get("timestamp", time.time())
        )
    
    def to_bytes(self) -> bytes:
        """Serialize to bytes for encryption."""
        return json.dumps(self.to_dict()).encode()
    
    @classmethod
    def from_bytes(cls, data: bytes) -> "DeliverPayload":
        """Deserialize from bytes after decryption."""
        return cls.from_dict(json.loads(data.decode()))
