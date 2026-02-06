"""
Valence Network - E2E encrypted relay protocol.

This module provides end-to-end encryption for messages relayed through
router nodes, ensuring routers cannot read message content.
"""

from valence.network.config import (
    PRIVACY_HIGH,
    PRIVACY_LOW,
    PRIVACY_MEDIUM,
    PRIVACY_PARANOID,
    BatchingConfig,
    ConstantRateConfig,
    MixNetworkConfig,
    PrivacyLevel,
    TimingJitterConfig,
    TrafficAnalysisMitigationConfig,
    get_recommended_config,
)

# Decomposed NodeClient components (Issue #128)
from valence.network.connection_manager import (
    ConnectionManager,
    ConnectionManagerConfig,
)
from valence.network.crypto import (
    KeyPair,
    create_onion,
    decrypt_backward_layers,
    decrypt_circuit_layer,
    decrypt_message,
    decrypt_onion_layer,
    derive_circuit_key,
    encrypt_backward_payload,
    encrypt_circuit_payload,
    encrypt_message,
    encrypt_onion_layer,
    # Circuit encryption (Issue #115)
    generate_circuit_keypair,
    generate_encryption_keypair,
    generate_identity_keypair,
    peel_onion,
)
from valence.network.discovery import (
    DiscoveryClient,
    DiscoveryError,
    NoSeedsAvailableError,
    RouterInfo,
    SignatureVerificationError,
    create_discovery_client,
    discover_routers,
)
from valence.network.health_monitor import (
    HealthMonitor,
    HealthMonitorConfig,
)
from valence.network.message_handler import (
    MessageHandler,
    MessageHandlerConfig,
)
from valence.network.messages import (
    # Circuit messages (Issue #115)
    Circuit,
    CircuitCreatedMessage,
    CircuitCreateMessage,
    CircuitDestroyMessage,
    CircuitExtendMessage,
    CircuitHop,
    CircuitRelayMessage,
    DeliverPayload,
    RelayMessage,
)
from valence.network.node import (
    ConnectionState,
    CoverTrafficConfig,
    FailoverState,
    NodeClient,
    NodeError,
    NoRoutersAvailableError,
    PendingAck,
    PendingMessage,
    RouterConnection,
    StaleStateError,
    StateConflictError,
    create_node_client,
)
from valence.network.qos import (
    DEFAULT_DIMENSION_WEIGHTS,
    MAX_CONTRIBUTION_SCORE,
    NEW_USER_MINIMUM_SCORE,
    TIER_WEIGHTS,
    ContributionDimension,
    ContributionScore,
    PriorityTier,
    QoSPolicy,
)
from valence.network.qos_manager import (
    LoadMetrics,
    NodeQoSState,
    QoSManager,
)
from valence.network.router import (
    # Circuit state (Issue #115)
    CircuitHopState,
    CircuitState,
    Connection,
    NodeConnectionHistory,
    QueuedMessage,
    RouterNode,
)
from valence.network.router_client import (
    RouterClient,
    RouterClientConfig,
)
from valence.network.seed import (
    # Regional routing utilities
    COUNTRY_TO_CONTINENT,
    HealthState,
    HealthStatus,
    RouterRecord,
    SeedConfig,
    SeedNode,
    compute_region_score,
    get_continent,
)
from valence.network.seed import (
    HealthMonitor as SeedHealthMonitor,  # Renamed to avoid conflict with health_monitor.HealthMonitor
)

__all__ = [
    # Crypto
    "KeyPair",
    "generate_identity_keypair",
    "generate_encryption_keypair",
    "encrypt_message",
    "decrypt_message",
    # Circuit encryption (Issue #115)
    "generate_circuit_keypair",
    "derive_circuit_key",
    "create_onion",
    "peel_onion",
    "encrypt_onion_layer",
    "decrypt_onion_layer",
    "encrypt_circuit_payload",
    "decrypt_circuit_layer",
    "encrypt_backward_payload",
    "decrypt_backward_layers",
    # Messages
    "RelayMessage",
    "DeliverPayload",
    # Circuit messages (Issue #115)
    "Circuit",
    "CircuitHop",
    "CircuitCreateMessage",
    "CircuitCreatedMessage",
    "CircuitRelayMessage",
    "CircuitDestroyMessage",
    "CircuitExtendMessage",
    # Router
    "RouterNode",
    "Connection",
    "QueuedMessage",
    "NodeConnectionHistory",
    # Circuit state (Issue #115)
    "CircuitHopState",
    "CircuitState",
    # Seed
    "SeedNode",
    "RouterRecord",
    "SeedConfig",
    # Health Monitoring (from seed)
    "HealthStatus",
    "HealthState",
    "SeedHealthMonitor",
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
    "CoverTrafficConfig",
    "StateConflictError",
    "StaleStateError",
    "NodeError",
    "NoRoutersAvailableError",
    "create_node_client",
    # NodeClient components (Issue #128)
    "ConnectionManager",
    "ConnectionManagerConfig",
    "MessageHandler",
    "MessageHandlerConfig",
    "RouterClient",
    "RouterClientConfig",
    "HealthMonitor",
    "HealthMonitorConfig",
    # QoS (Issue #276)
    "ContributionDimension",
    "ContributionScore",
    "DEFAULT_DIMENSION_WEIGHTS",
    "MAX_CONTRIBUTION_SCORE",
    "NEW_USER_MINIMUM_SCORE",
    "PriorityTier",
    "QoSPolicy",
    "TIER_WEIGHTS",
    "LoadMetrics",
    "NodeQoSState",
    "QoSManager",
    # Traffic Analysis Mitigations (Issue #120)
    "TrafficAnalysisMitigationConfig",
    "PrivacyLevel",
    "BatchingConfig",
    "TimingJitterConfig",
    "ConstantRateConfig",
    "MixNetworkConfig",
    "PRIVACY_LOW",
    "PRIVACY_MEDIUM",
    "PRIVACY_HIGH",
    "PRIVACY_PARANOID",
    "get_recommended_config",
]
