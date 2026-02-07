"""Tests for valence.transport.protocols — protocol IDs and helpers."""

from __future__ import annotations

import pytest

from valence.transport.protocols import (
    ALL_GOSSIPSUB_TOPICS,
    ALL_STREAM_PROTOCOLS,
    VALENCE_AUTH_PROTOCOL,
    VALENCE_BELIEFS_TOPIC,
    VALENCE_PEERS_TOPIC,
    VALENCE_SYNC_PROTOCOL,
    VALENCE_TRUST_PROTOCOL,
    protocol_for_message_type,
)

# ============================================================================
# Protocol ID constants
# ============================================================================


class TestProtocolConstants:
    """Verify that protocol ID strings are well-formed."""

    def test_sync_protocol_format(self) -> None:
        assert VALENCE_SYNC_PROTOCOL == "/valence/sync/1.0.0"
        assert VALENCE_SYNC_PROTOCOL.startswith("/")

    def test_auth_protocol_format(self) -> None:
        assert VALENCE_AUTH_PROTOCOL == "/valence/auth/1.0.0"

    def test_trust_protocol_format(self) -> None:
        assert VALENCE_TRUST_PROTOCOL == "/valence/trust/1.0.0"

    def test_beliefs_topic_format(self) -> None:
        assert VALENCE_BELIEFS_TOPIC == "/valence/beliefs"

    def test_peers_topic_format(self) -> None:
        assert VALENCE_PEERS_TOPIC == "/valence/peers"

    def test_all_stream_protocols_list(self) -> None:
        assert len(ALL_STREAM_PROTOCOLS) == 3
        assert VALENCE_SYNC_PROTOCOL in ALL_STREAM_PROTOCOLS
        assert VALENCE_AUTH_PROTOCOL in ALL_STREAM_PROTOCOLS
        assert VALENCE_TRUST_PROTOCOL in ALL_STREAM_PROTOCOLS

    def test_all_gossipsub_topics_list(self) -> None:
        assert len(ALL_GOSSIPSUB_TOPICS) == 2
        assert VALENCE_BELIEFS_TOPIC in ALL_GOSSIPSUB_TOPICS
        assert VALENCE_PEERS_TOPIC in ALL_GOSSIPSUB_TOPICS

    def test_no_overlap_between_streams_and_topics(self) -> None:
        """Stream protocols and GossipSub topics must not collide."""
        assert set(ALL_STREAM_PROTOCOLS).isdisjoint(set(ALL_GOSSIPSUB_TOPICS))


# ============================================================================
# protocol_for_message_type
# ============================================================================


class TestProtocolForMessageType:
    """Map VFP MessageType values to libp2p protocol IDs."""

    @pytest.mark.parametrize(
        ("message_type", "expected"),
        [
            ("SYNC_REQUEST", VALENCE_SYNC_PROTOCOL),
            ("SYNC_RESPONSE", VALENCE_SYNC_PROTOCOL),
            ("AUTH_CHALLENGE", VALENCE_AUTH_PROTOCOL),
            ("AUTH_CHALLENGE_RESPONSE", VALENCE_AUTH_PROTOCOL),
            ("AUTH_VERIFY", VALENCE_AUTH_PROTOCOL),
            ("AUTH_VERIFY_RESPONSE", VALENCE_AUTH_PROTOCOL),
            ("TRUST_ATTESTATION", VALENCE_TRUST_PROTOCOL),
            ("TRUST_ATTESTATION_RESPONSE", VALENCE_TRUST_PROTOCOL),
            ("SHARE_BELIEF", VALENCE_SYNC_PROTOCOL),
            ("SHARE_BELIEF_RESPONSE", VALENCE_SYNC_PROTOCOL),
            ("REQUEST_BELIEFS", VALENCE_SYNC_PROTOCOL),
            ("BELIEFS_RESPONSE", VALENCE_SYNC_PROTOCOL),
        ],
    )
    def test_known_types_map_correctly(self, message_type: str, expected: str) -> None:
        assert protocol_for_message_type(message_type) == expected

    def test_error_type_returns_none(self) -> None:
        assert protocol_for_message_type("ERROR") is None

    def test_unknown_type_returns_none(self) -> None:
        assert protocol_for_message_type("BOGUS_TYPE") is None
