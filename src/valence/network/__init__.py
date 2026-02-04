"""
Valence Network - E2E encrypted relay protocol.

This module provides end-to-end encryption for messages relayed through
router nodes, ensuring routers cannot read message content.
"""

from valence.network.crypto import (
    KeyPair,
    generate_identity_keypair,
    generate_encryption_keypair,
    encrypt_message,
    decrypt_message,
)
from valence.network.messages import RelayMessage, DeliverPayload
from valence.network.router import RouterNode, Connection, QueuedMessage, NodeConnectionHistory
from valence.network.seed import (
    SeedNode,
    RouterRecord,
    SeedConfig,
    HealthStatus,
    HealthState,
    HealthMonitor,
    # Regional routing utilities
    COUNTRY_TO_CONTINENT,
    get_continent,
    compute_region_score,
)
from valence.network.discovery import (
    DiscoveryClient,
    RouterInfo,
    DiscoveryError,
    NoSeedsAvailableError,
    SignatureVerificationError,
    create_discovery_client,
    discover_routers,
)
from valence.network.node import (
    NodeClient,
    RouterConnection,
    PendingMessage,
    PendingAck,
    FailoverState,
    ConnectionState,
    StateConflictError,
    StaleStateError,
    NodeError,
    NoRoutersAvailableError,
    create_node_client,
)

__all__ = [
    # Crypto
    "KeyPair",
    "generate_identity_keypair",
    "generate_encryption_keypair",
    "encrypt_message",
    "decrypt_message",
    # Messages
    "RelayMessage",
    "DeliverPayload",
    # Router
    "RouterNode",
    "Connection",
    "QueuedMessage",
    "NodeConnectionHistory",
    # Seed
    "SeedNode",
    "RouterRecord",
    "SeedConfig",
    # Health Monitoring
    "HealthStatus",
    "HealthState",
    "HealthMonitor",
    # Regional Routing
    "COUNTRY_TO_CONTINENT",
    "get_continent",
    "compute_region_score",
    # Discovery
    "DiscoveryClient",
    "RouterInfo",
    "DiscoveryError",
    "NoSeedsAvailableError",
    "SignatureVerificationError",
    "create_discovery_client",
    "discover_routers",
    # Node
    "NodeClient",
    "RouterConnection",
    "PendingMessage",
    "PendingAck",
    "FailoverState",
    "ConnectionState",
    "StateConflictError",
    "StaleStateError",
    "NodeError",
    "NoRoutersAvailableError",
    "create_node_client",
]
