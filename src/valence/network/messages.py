"""
Message formats for Valence Relay Protocol.

RelayMessage: What routers see (encrypted payload, routing info)
DeliverPayload: What recipients see after decryption (actual content)
AckRequest: Configuration for acknowledgment behavior
AckMessage: End-to-end acknowledgment that proves recipient received message
BackPressureMessage: Router signals load status to connected nodes

Circuit Messages (Issue #115):
CircuitCreateMessage: Request to establish circuit hop
CircuitCreatedMessage: Confirmation of circuit hop establishment
CircuitRelayMessage: Message relayed through circuit
CircuitDestroyMessage: Teardown circuit
"""

from dataclasses import dataclass, field
from typing import Optional, List
import json
import time
import uuid


# =============================================================================
# BACK-PRESSURE MESSAGES
# =============================================================================


@dataclass
class BackPressureMessage:
    """
    Back-pressure signal from router to connected nodes.
    
    When a router is under heavy load, it sends this message to
    connected nodes to request they slow down or try alternative routers.
    
    Attributes:
        type: Always "back_pressure"
        active: True when back-pressure is active, False when released
        load_pct: Current load percentage (0-100)
        retry_after_ms: Suggested delay before retrying (milliseconds)
        reason: Human-readable reason for back-pressure
    """
    type: str = field(default="back_pressure", init=False)
    active: bool = True
    load_pct: float = 0.0
    retry_after_ms: int = 1000
    reason: str = ""
    
    def to_dict(self) -> dict:
        """Serialize to dict for transmission."""
        return {
            "type": self.type,
            "active": self.active,
            "load_pct": self.load_pct,
            "retry_after_ms": self.retry_after_ms,
            "reason": self.reason,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "BackPressureMessage":
        """Deserialize from dict."""
        return cls(
            active=data.get("active", True),
            load_pct=data.get("load_pct", 0.0),
            retry_after_ms=data.get("retry_after_ms", 1000),
            reason=data.get("reason", ""),
        )


# =============================================================================
# ACKNOWLEDGMENT MESSAGES
# =============================================================================


@dataclass
class AckRequest:
    """
    Configuration for message acknowledgment behavior.
    
    Attached to outgoing messages to specify whether ACK is required
    and timeout settings.
    """
    message_id: str
    require_ack: bool = True
    ack_timeout_ms: int = 30000  # 30 seconds default


@dataclass
class AckMessage:
    """
    End-to-end acknowledgment message.
    
    Sent by the recipient back to the sender to prove message delivery.
    The signature proves the recipient actually received and processed
    the message (not just that it was relayed).
    """
    type: str = field(default="ack", init=False)
    original_message_id: str = ""
    received_at: float = 0.0
    recipient_id: str = ""
    signature: str = ""  # Hex-encoded signature proving receipt
    
    def to_dict(self) -> dict:
        """Serialize to dict for transmission."""
        return {
            "type": self.type,
            "original_message_id": self.original_message_id,
            "received_at": self.received_at,
            "recipient_id": self.recipient_id,
            "signature": self.signature,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "AckMessage":
        """Deserialize from dict."""
        return cls(
            original_message_id=data.get("original_message_id", ""),
            received_at=data.get("received_at", 0.0),
            recipient_id=data.get("recipient_id", ""),
            signature=data.get("signature", ""),
        )


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


# =============================================================================
# HEALTH GOSSIP MESSAGES
# =============================================================================


@dataclass
class RouterHealthObservation:
    """
    A single router health observation from a node's perspective.
    
    Nodes track health metrics for routers they connect to and share
    these observations with peers via gossip.
    """
    router_id: str
    latency_ms: float = 0.0
    success_rate: float = 1.0  # 0.0 to 1.0
    failure_count: int = 0
    success_count: int = 0
    last_seen: float = 0.0
    load_pct: float = 0.0
    
    def to_dict(self) -> dict:
        """Serialize to dict for transmission."""
        return {
            "router_id": self.router_id,
            "latency_ms": self.latency_ms,
            "success_rate": self.success_rate,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_seen": self.last_seen,
            "load_pct": self.load_pct,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "RouterHealthObservation":
        """Deserialize from dict."""
        return cls(
            router_id=data.get("router_id", ""),
            latency_ms=data.get("latency_ms", 0.0),
            success_rate=data.get("success_rate", 1.0),
            failure_count=data.get("failure_count", 0),
            success_count=data.get("success_count", 0),
            last_seen=data.get("last_seen", 0.0),
            load_pct=data.get("load_pct", 0.0),
        )


@dataclass
class HealthGossip:
    """
    Health gossip message for sharing router observations between nodes.
    
    Nodes periodically share their router health observations with peers
    to improve collective routing decisions. Observations are sampled
    to keep gossip lightweight.
    
    Attributes:
        type: Always "health_gossip"
        source_node_id: The node sharing these observations
        timestamp: When the gossip was generated
        observations: List of router health observations (sampled)
        ttl: Hop limit for gossip propagation (default 2)
    """
    type: str = field(default="health_gossip", init=False)
    source_node_id: str = ""
    timestamp: float = 0.0
    observations: list = field(default_factory=list)  # List[RouterHealthObservation]
    ttl: int = 2  # Limit propagation depth
    
    def to_dict(self) -> dict:
        """Serialize to dict for transmission."""
        return {
            "type": self.type,
            "source_node_id": self.source_node_id,
            "timestamp": self.timestamp,
            "observations": [
                obs.to_dict() if hasattr(obs, 'to_dict') else obs
                for obs in self.observations
            ],
            "ttl": self.ttl,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "HealthGossip":
        """Deserialize from dict."""
        observations = [
            RouterHealthObservation.from_dict(obs) if isinstance(obs, dict) else obs
            for obs in data.get("observations", [])
        ]
        return cls(
            source_node_id=data.get("source_node_id", ""),
            timestamp=data.get("timestamp", 0.0),
            observations=observations,
            ttl=data.get("ttl", 2),
        )


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
    message_id: Optional[str] = None  # For ACK correlation
    require_ack: bool = False  # Whether sender wants ACK
    
    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "sender_id": self.sender_id,
            "message_type": self.message_type,
            "content": self.content,
            "reply_path": self.reply_path,
            "timestamp": self.timestamp,
            "message_id": self.message_id,
            "require_ack": self.require_ack,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "DeliverPayload":
        """Deserialize from dict."""
        return cls(
            sender_id=data["sender_id"],
            message_type=data["message_type"],
            content=data["content"],
            reply_path=data.get("reply_path"),
            timestamp=data.get("timestamp", time.time()),
            message_id=data.get("message_id"),
            require_ack=data.get("require_ack", False),
        )
    
    def to_bytes(self) -> bytes:
        """Serialize to bytes for encryption."""
        return json.dumps(self.to_dict()).encode()
    
    @classmethod
    def from_bytes(cls, data: bytes) -> "DeliverPayload":
        """Deserialize from bytes after decryption."""
        return cls.from_dict(json.loads(data.decode()))


# =============================================================================
# CIRCUIT MESSAGES (Issue #115 - Privacy-Enhanced Routing)
# =============================================================================


@dataclass
class CircuitHop:
    """
    Represents a single hop in a circuit.
    
    Each hop contains the router ID and the shared key established
    during circuit creation (via Diffie-Hellman key exchange).
    """
    router_id: str
    shared_key: bytes = field(default=b"", repr=False)  # 32-byte AES key
    
    def to_dict(self) -> dict:
        """Serialize to dict (excluding secret key)."""
        return {
            "router_id": self.router_id,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "CircuitHop":
        """Deserialize from dict."""
        return cls(
            router_id=data["router_id"],
        )


@dataclass
class Circuit:
    """
    Represents an established circuit through multiple routers.
    
    A circuit provides enhanced privacy by routing messages through
    2-3 routers, with layered (onion) encryption. Each router only
    knows the previous and next hop, never the full path.
    
    Attributes:
        circuit_id: Unique identifier for this circuit
        hops: List of CircuitHop objects (in order from node to destination)
        created_at: Timestamp when circuit was established
        expires_at: Timestamp when circuit should be torn down
        message_count: Number of messages sent through this circuit
        max_messages: Maximum messages before rotation (default 100)
    """
    circuit_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    hops: List[CircuitHop] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0  # 0 means no expiry set
    message_count: int = 0
    max_messages: int = 100
    
    def __post_init__(self):
        if self.expires_at == 0.0:
            # Default 10 minute lifetime
            self.expires_at = self.created_at + 600
    
    @property
    def is_expired(self) -> bool:
        """Check if circuit has expired."""
        return time.time() > self.expires_at
    
    @property
    def needs_rotation(self) -> bool:
        """Check if circuit needs rotation (expired or too many messages)."""
        return self.is_expired or self.message_count >= self.max_messages
    
    @property
    def hop_count(self) -> int:
        """Number of hops in the circuit."""
        return len(self.hops)
    
    def to_dict(self) -> dict:
        """Serialize to dict (excluding secret keys)."""
        return {
            "circuit_id": self.circuit_id,
            "hops": [hop.to_dict() for hop in self.hops],
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "message_count": self.message_count,
            "max_messages": self.max_messages,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Circuit":
        """Deserialize from dict."""
        return cls(
            circuit_id=data["circuit_id"],
            hops=[CircuitHop.from_dict(h) for h in data.get("hops", [])],
            created_at=data.get("created_at", time.time()),
            expires_at=data.get("expires_at", 0.0),
            message_count=data.get("message_count", 0),
            max_messages=data.get("max_messages", 100),
        )


@dataclass
class CircuitCreateMessage:
    """
    Request to create a circuit hop at a router.
    
    Sent to each router in the circuit path during establishment.
    The router responds with CircuitCreatedMessage containing its
    ephemeral public key for the Diffie-Hellman key exchange.
    
    Attributes:
        type: Always "circuit_create"
        circuit_id: Unique circuit identifier
        ephemeral_public: Sender's ephemeral X25519 public key (hex)
        next_hop: Router ID of the next hop (None for exit node)
        extend_payload: Encrypted payload for next hop (onion layer)
    """
    type: str = field(default="circuit_create", init=False)
    circuit_id: str = ""
    ephemeral_public: str = ""  # Hex-encoded X25519 public key
    next_hop: Optional[str] = None  # None means this is the exit node
    extend_payload: Optional[str] = None  # Encrypted for next router
    
    def to_dict(self) -> dict:
        """Serialize to dict for transmission."""
        return {
            "type": self.type,
            "circuit_id": self.circuit_id,
            "ephemeral_public": self.ephemeral_public,
            "next_hop": self.next_hop,
            "extend_payload": self.extend_payload,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "CircuitCreateMessage":
        """Deserialize from dict."""
        return cls(
            circuit_id=data.get("circuit_id", ""),
            ephemeral_public=data.get("ephemeral_public", ""),
            next_hop=data.get("next_hop"),
            extend_payload=data.get("extend_payload"),
        )


@dataclass
class CircuitCreatedMessage:
    """
    Response confirming circuit hop establishment.
    
    Sent by a router after successfully processing CircuitCreateMessage.
    Contains the router's ephemeral public key for completing the
    Diffie-Hellman key exchange.
    
    Attributes:
        type: Always "circuit_created"
        circuit_id: The circuit identifier
        ephemeral_public: Router's ephemeral X25519 public key (hex)
        extend_response: Encrypted response from next hop (if extended)
    """
    type: str = field(default="circuit_created", init=False)
    circuit_id: str = ""
    ephemeral_public: str = ""  # Hex-encoded X25519 public key
    extend_response: Optional[str] = None  # Response from next hop
    
    def to_dict(self) -> dict:
        """Serialize to dict for transmission."""
        return {
            "type": self.type,
            "circuit_id": self.circuit_id,
            "ephemeral_public": self.ephemeral_public,
            "extend_response": self.extend_response,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "CircuitCreatedMessage":
        """Deserialize from dict."""
        return cls(
            circuit_id=data.get("circuit_id", ""),
            ephemeral_public=data.get("ephemeral_public", ""),
            extend_response=data.get("extend_response"),
        )


@dataclass
class CircuitRelayMessage:
    """
    Message relayed through an established circuit.
    
    The payload is onion-encrypted: each router peels one layer
    and forwards to the next hop. Only the final recipient can
    read the innermost payload.
    
    Attributes:
        type: Always "circuit_relay"
        circuit_id: The circuit this message is traveling through
        payload: Onion-encrypted payload (hex)
        direction: "forward" (toward recipient) or "backward" (toward sender)
    """
    type: str = field(default="circuit_relay", init=False)
    circuit_id: str = ""
    payload: str = ""  # Hex-encoded onion payload
    direction: str = "forward"  # "forward" or "backward"
    
    def to_dict(self) -> dict:
        """Serialize to dict for transmission."""
        return {
            "type": self.type,
            "circuit_id": self.circuit_id,
            "payload": self.payload,
            "direction": self.direction,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "CircuitRelayMessage":
        """Deserialize from dict."""
        return cls(
            circuit_id=data.get("circuit_id", ""),
            payload=data.get("payload", ""),
            direction=data.get("direction", "forward"),
        )


@dataclass
class CircuitDestroyMessage:
    """
    Request to tear down a circuit.
    
    Sent when a circuit expires, has been used for max messages,
    or is explicitly closed. Each router should clean up its
    circuit state upon receiving this.
    
    Attributes:
        type: Always "circuit_destroy"
        circuit_id: The circuit to destroy
        reason: Optional reason for teardown
    """
    type: str = field(default="circuit_destroy", init=False)
    circuit_id: str = ""
    reason: str = ""
    
    def to_dict(self) -> dict:
        """Serialize to dict for transmission."""
        return {
            "type": self.type,
            "circuit_id": self.circuit_id,
            "reason": self.reason,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "CircuitDestroyMessage":
        """Deserialize from dict."""
        return cls(
            circuit_id=data.get("circuit_id", ""),
            reason=data.get("reason", ""),
        )


@dataclass
class CircuitExtendMessage:
    """
    Internal message to extend circuit to next hop.
    
    This is the decrypted content of extend_payload in CircuitCreateMessage.
    It contains the information needed to create the next hop.
    
    Attributes:
        next_router_id: Router ID to extend to
        ephemeral_public: Client's ephemeral key for next hop
        next_extend_payload: Encrypted payload for hop after next (if any)
    """
    next_router_id: str = ""
    ephemeral_public: str = ""
    next_extend_payload: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "next_router_id": self.next_router_id,
            "ephemeral_public": self.ephemeral_public,
            "next_extend_payload": self.next_extend_payload,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "CircuitExtendMessage":
        """Deserialize from dict."""
        return cls(
            next_router_id=data.get("next_router_id", ""),
            ephemeral_public=data.get("ephemeral_public", ""),
            next_extend_payload=data.get("next_extend_payload"),
        )
    
    def to_bytes(self) -> bytes:
        """Serialize to bytes for encryption."""
        return json.dumps(self.to_dict()).encode()
    
    @classmethod
    def from_bytes(cls, data: bytes) -> "CircuitExtendMessage":
        """Deserialize from bytes."""
        return cls.from_dict(json.loads(data.decode()))
