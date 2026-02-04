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
from valence.network.router import RouterNode, Connection, QueuedMessage
from valence.network.seed import SeedNode, RouterRecord, SeedConfig
from valence.network.discovery import (
    DiscoveryClient,
    RouterInfo,
    DiscoveryError,
    NoSeedsAvailableError,
    SignatureVerificationError,
    create_discovery_client,
    discover_routers,
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
    # Seed
    "SeedNode",
    "RouterRecord",
    "SeedConfig",
    # Discovery
    "DiscoveryClient",
    "RouterInfo",
    "DiscoveryError",
    "NoSeedsAvailableError",
    "SignatureVerificationError",
    "create_discovery_client",
    "discover_routers",
]
