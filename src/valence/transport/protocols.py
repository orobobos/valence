"""
Protocol identifiers for Valence over libp2p.

Stream protocols follow the libp2p convention ``/<name>/<version>``.
GossipSub topics use ``/<name>`` (no version; topic evolution is handled
via message schema versions inside the payload).

These constants are the canonical source of truth — import them from
``valence.transport.protocols`` everywhere.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Stream protocols (request/response over a dedicated libp2p stream)
# ---------------------------------------------------------------------------

VALENCE_SYNC_PROTOCOL: str = "/valence/sync/1.0.0"
"""Belief synchronisation between peers (SYNC_REQUEST / SYNC_RESPONSE)."""

VALENCE_AUTH_PROTOCOL: str = "/valence/auth/1.0.0"
"""DID-based authentication challenge/verify handshake."""

VALENCE_TRUST_PROTOCOL: str = "/valence/trust/1.0.0"
"""Trust attestation exchange (TRUST_ATTESTATION / response)."""

# ---------------------------------------------------------------------------
# GossipSub topics (pub/sub broadcast)
# ---------------------------------------------------------------------------

VALENCE_BELIEFS_TOPIC: str = "/valence/beliefs"
"""GossipSub topic for broadcasting new/updated beliefs to the mesh."""

VALENCE_PEERS_TOPIC: str = "/valence/peers"
"""GossipSub topic for peer discovery announcements."""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_STREAM_PROTOCOLS: list[str] = [
    VALENCE_SYNC_PROTOCOL,
    VALENCE_AUTH_PROTOCOL,
    VALENCE_TRUST_PROTOCOL,
]
"""Every stream protocol this node should register on startup."""

ALL_GOSSIPSUB_TOPICS: list[str] = [
    VALENCE_BELIEFS_TOPIC,
    VALENCE_PEERS_TOPIC,
]
"""Every GossipSub topic this node should subscribe to on startup."""


def protocol_for_message_type(message_type: str) -> str | None:
    """Map a VFP ``MessageType`` value to its libp2p protocol ID.

    Returns ``None`` for message types that are carried over GossipSub
    rather than a dedicated stream.

    >>> protocol_for_message_type("SYNC_REQUEST")
    '/valence/sync/1.0.0'
    >>> protocol_for_message_type("AUTH_CHALLENGE")
    '/valence/auth/1.0.0'
    >>> protocol_for_message_type("TRUST_ATTESTATION")
    '/valence/trust/1.0.0'
    """
    mapping: dict[str, str] = {
        # Sync
        "SYNC_REQUEST": VALENCE_SYNC_PROTOCOL,
        "SYNC_RESPONSE": VALENCE_SYNC_PROTOCOL,
        # Auth
        "AUTH_CHALLENGE": VALENCE_AUTH_PROTOCOL,
        "AUTH_CHALLENGE_RESPONSE": VALENCE_AUTH_PROTOCOL,
        "AUTH_VERIFY": VALENCE_AUTH_PROTOCOL,
        "AUTH_VERIFY_RESPONSE": VALENCE_AUTH_PROTOCOL,
        # Trust
        "TRUST_ATTESTATION": VALENCE_TRUST_PROTOCOL,
        "TRUST_ATTESTATION_RESPONSE": VALENCE_TRUST_PROTOCOL,
        # Beliefs (share/request also use sync stream)
        "SHARE_BELIEF": VALENCE_SYNC_PROTOCOL,
        "SHARE_BELIEF_RESPONSE": VALENCE_SYNC_PROTOCOL,
        "REQUEST_BELIEFS": VALENCE_SYNC_PROTOCOL,
        "BELIEFS_RESPONSE": VALENCE_SYNC_PROTOCOL,
    }
    return mapping.get(message_type)
