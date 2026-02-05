"""Tests for Federation Server (federation/server.py).

Tests cover:
1. NodeIdentity dataclass
2. LocalBelief dataclass
3. FederationNode initialization and identity
4. Endpoint handlers (_info, _introduce, _share, _query, _list_peers)
5. Client methods (introduce_to, share_belief, query_peer)
6. PII scanning integration
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from valence.federation.server import (
    FederationNode,
    LocalBelief,
    NodeIdentity,
    create_node,
)

# ============================================================================
# NodeIdentity Tests
# ============================================================================


class TestNodeIdentity:
    """Test NodeIdentity dataclass."""

    def test_node_identity_creation(self):
        """Create NodeIdentity with all fields."""
        mock_keypair = MagicMock()
        mock_keypair.public_key_multibase = "z6MkTest123"

        identity = NodeIdentity(
            did="did:vkb:key:z6MkTest123",
            keypair=mock_keypair,
            name="Test Node",
            endpoint="http://localhost:8000",
        )

        assert identity.did == "did:vkb:key:z6MkTest123"
        assert identity.name == "Test Node"
        assert identity.endpoint == "http://localhost:8000"

    def test_node_identity_public_key_property(self):
        """Access public key through property."""
        mock_keypair = MagicMock()
        mock_keypair.public_key_multibase = "z6MkTest456"

        identity = NodeIdentity(
            did="did:vkb:key:z6MkTest456",
            keypair=mock_keypair,
        )

        assert identity.public_key_multibase == "z6MkTest456"

    def test_node_identity_to_dict(self):
        """Convert identity to dictionary."""
        mock_keypair = MagicMock()
        mock_keypair.public_key_multibase = "z6MkTestKey"

        identity = NodeIdentity(
            did="did:vkb:key:z6MkTestKey",
            keypair=mock_keypair,
            name="Test Node",
            endpoint="http://localhost:8000",
        )

        d = identity.to_dict()

        assert d["did"] == "did:vkb:key:z6MkTestKey"
        assert d["name"] == "Test Node"
        assert d["endpoint"] == "http://localhost:8000"
        assert d["public_key_multibase"] == "z6MkTestKey"


# ============================================================================
# LocalBelief Tests
# ============================================================================


class TestLocalBelief:
    """Test LocalBelief dataclass."""

    def test_local_belief_creation(self):
        """Create LocalBelief with required fields."""
        belief = LocalBelief(
            id="belief-001",
            content="Test belief content",
            confidence=0.85,
            domains=["tech", "python"],
        )

        assert belief.id == "belief-001"
        assert belief.content == "Test belief content"
        assert belief.confidence == 0.85
        assert belief.domains == ["tech", "python"]
        assert belief.signature is None
        assert belief.origin_did is None
        assert isinstance(belief.created_at, datetime)

    def test_local_belief_with_optional_fields(self):
        """Create LocalBelief with optional fields."""
        created = datetime(2024, 1, 15, 10, 30, 0)

        belief = LocalBelief(
            id="belief-002",
            content="Signed belief",
            confidence=0.9,
            domains=["security"],
            created_at=created,
            signature="base64signature",
            origin_did="did:vkb:key:z6MkOrigin",
        )

        assert belief.created_at == created
        assert belief.signature == "base64signature"
        assert belief.origin_did == "did:vkb:key:z6MkOrigin"

    def test_local_belief_to_dict(self):
        """Convert belief to dictionary."""
        created = datetime(2024, 1, 15, 10, 30, 0)

        belief = LocalBelief(
            id="belief-003",
            content="Dict test",
            confidence=0.75,
            domains=["test"],
            created_at=created,
            signature="sig123",
            origin_did="did:vkb:key:z6MkTest",
        )

        d = belief.to_dict()

        assert d["id"] == "belief-003"
        assert d["content"] == "Dict test"
        assert d["confidence"] == 0.75
        assert d["domains"] == ["test"]
        assert d["created_at"] == created.isoformat()
        assert d["signature"] == "sig123"
        assert d["origin_did"] == "did:vkb:key:z6MkTest"


# ============================================================================
# FederationNode Tests
# ============================================================================


class TestFederationNodeInit:
    """Test FederationNode initialization."""

    def test_node_creation_generates_keypair(self):
        """Node generates keypair if not provided."""
        with patch("valence.federation.server.generate_keypair") as mock_gen:
            mock_keypair = MagicMock()
            mock_keypair.public_key_multibase = "z6MkGenerated"
            mock_gen.return_value = mock_keypair

            with patch("valence.federation.server.create_key_did") as mock_did:
                mock_did_obj = MagicMock()
                mock_did_obj.full = "did:vkb:key:z6MkGenerated"
                mock_did.return_value = mock_did_obj

                node = FederationNode(name="Test Node", port=8000)

        assert node.name == "Test Node"
        assert node.port == 8000
        assert node.endpoint == "http://127.0.0.1:8000"
        assert node.identity.did == "did:vkb:key:z6MkGenerated"

    def test_node_creation_with_keypair(self):
        """Node uses provided keypair."""
        mock_keypair = MagicMock()
        mock_keypair.public_key_multibase = "z6MkProvided"

        with patch("valence.federation.server.create_key_did") as mock_did:
            mock_did_obj = MagicMock()
            mock_did_obj.full = "did:vkb:key:z6MkProvided"
            mock_did.return_value = mock_did_obj

            node = FederationNode(
                name="Test Node",
                port=8001,
                keypair=mock_keypair,
            )

        assert node.keypair == mock_keypair

    def test_node_has_empty_stores(self):
        """New node has empty peer and belief stores."""
        with patch("valence.federation.server.generate_keypair"):
            with patch("valence.federation.server.create_key_did") as mock_did:
                mock_did_obj = MagicMock()
                mock_did_obj.full = "did:test"
                mock_did.return_value = mock_did_obj

                node = FederationNode(name="Empty Node", port=8002)

        assert node.beliefs == {}
        assert len(node.peer_store.list_peers()) == 0


# ============================================================================
# Endpoint Handler Tests
# ============================================================================


class TestFederationEndpoints:
    """Test federation HTTP endpoint handlers."""

    @pytest.fixture
    def node(self):
        """Create a test federation node."""
        with patch("valence.federation.server.generate_keypair") as mock_gen:
            mock_keypair = MagicMock()
            mock_keypair.public_key_multibase = "z6MkTestNode"
            mock_keypair.private_key_bytes = b"test_private_key"
            mock_gen.return_value = mock_keypair

            with patch("valence.federation.server.create_key_did") as mock_did:
                mock_did_obj = MagicMock()
                mock_did_obj.full = "did:vkb:key:z6MkTestNode"
                mock_did.return_value = mock_did_obj

                return FederationNode(name="Test Node", port=9000)

    @pytest.fixture
    def client(self, node):
        """Create a test client for the node."""
        return TestClient(node.app)

    def test_info_endpoint(self, client, node):
        """GET / returns node info."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()

        assert "node" in data
        assert data["node"]["name"] == "Test Node"
        assert data["beliefs_count"] == 0
        assert data["peers_count"] == 0

    def test_introduce_endpoint_success(self, client, node):
        """POST /federation/introduce registers peer."""
        payload = {
            "did": "did:vkb:key:z6MkPeer1",
            "endpoint": "http://peer1.example.com:8000",
            "public_key_multibase": "z6MkPeer1Key",
            "name": "Peer Node",
        }

        response = client.post("/federation/introduce", json=payload)

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert "Test Node" in data["message"]
        assert data["node"]["did"] == node.identity.did

    def test_introduce_endpoint_missing_field(self, client):
        """POST /federation/introduce rejects missing required field."""
        payload = {
            "did": "did:vkb:key:z6MkPeer1",
            # Missing endpoint and public_key_multibase
        }

        response = client.post("/federation/introduce", json=payload)

        assert response.status_code == 400
        assert "endpoint" in response.json()["error"]

    def test_introduce_endpoint_invalid_json(self, client):
        """POST /federation/introduce rejects invalid JSON."""
        response = client.post(
            "/federation/introduce",
            content="not json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400
        assert "Invalid JSON" in response.json()["error"]

    def test_share_endpoint_success(self, client, node):
        """POST /federation/share accepts valid belief."""
        # First register the peer
        peer_did = "did:vkb:key:z6MkSender"
        node.peer_store.add_peer(
            did=peer_did,
            endpoint="http://sender.example.com",
            public_key_multibase="z6MkSenderKey",
        )

        payload = {
            "belief": {
                "id": "belief-shared-001",
                "content": "Shared belief content",
                "confidence": 0.8,
                "domains": ["test"],
                "origin_did": peer_did,
            },
            "sender_did": peer_did,
        }

        with patch(
            "valence.federation.server.verify_belief_signature", return_value=True
        ):
            response = client.post("/federation/share", json=payload)

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["belief_id"] == "belief-shared-001"
        assert "belief-shared-001" in node.beliefs

    def test_share_endpoint_unknown_sender(self, client):
        """POST /federation/share rejects unknown sender."""
        payload = {
            "belief": {
                "id": "belief-001",
                "content": "Test",
                "confidence": 0.8,
            },
            "sender_did": "did:vkb:key:z6MkUnknown",
        }

        response = client.post("/federation/share", json=payload)

        assert response.status_code == 403
        assert "Unknown sender" in response.json()["error"]

    def test_share_endpoint_invalid_signature(self, client, node):
        """POST /federation/share rejects invalid signature."""
        peer_did = "did:vkb:key:z6MkBadSig"
        node.peer_store.add_peer(
            did=peer_did,
            endpoint="http://bad.example.com",
            public_key_multibase="z6MkBadKey",
        )

        payload = {
            "belief": {
                "id": "belief-badsig",
                "content": "Bad signature",
                "confidence": 0.8,
                "origin_did": peer_did,
                "signature": "invalid_signature",
            },
            "sender_did": peer_did,
        }

        with patch(
            "valence.federation.server.verify_belief_signature", return_value=False
        ):
            response = client.post("/federation/share", json=payload)

        assert response.status_code == 403
        assert "Invalid signature" in response.json()["error"]

    def test_query_endpoint_success(self, client, node):
        """POST /federation/query returns matching beliefs."""
        # Add some beliefs
        node.beliefs["b1"] = LocalBelief(
            id="b1",
            content="Python is a great programming language",
            confidence=0.9,
            domains=["tech", "programming"],
        )
        node.beliefs["b2"] = LocalBelief(
            id="b2",
            content="JavaScript runs in browsers",
            confidence=0.85,
            domains=["tech", "web"],
        )

        payload = {
            "query": "python",
            "min_confidence": 0.5,
        }

        response = client.post("/federation/query", json=payload)

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["total"] == 1
        assert data["results"][0]["id"] == "b1"

    def test_query_endpoint_with_domain_filter(self, client, node):
        """POST /federation/query filters by domain."""
        node.beliefs["b1"] = LocalBelief(
            id="b1",
            content="Web development",
            confidence=0.9,
            domains=["tech", "web"],
        )
        node.beliefs["b2"] = LocalBelief(
            id="b2",
            content="Data science",
            confidence=0.9,
            domains=["tech", "data"],
        )

        payload = {
            "query": "",  # Match all
            "domains": ["web"],
        }

        response = client.post("/federation/query", json=payload)

        assert response.status_code == 200
        data = response.json()

        assert data["total"] == 1
        assert data["results"][0]["id"] == "b1"

    def test_query_endpoint_with_confidence_filter(self, client, node):
        """POST /federation/query filters by min confidence."""
        node.beliefs["low"] = LocalBelief(
            id="low",
            content="Low confidence belief",
            confidence=0.3,
            domains=[],
        )
        node.beliefs["high"] = LocalBelief(
            id="high",
            content="High confidence belief",
            confidence=0.95,
            domains=[],
        )

        payload = {
            "query": "belief",
            "min_confidence": 0.8,
        }

        response = client.post("/federation/query", json=payload)

        assert response.status_code == 200
        data = response.json()

        assert data["total"] == 1
        assert data["results"][0]["id"] == "high"

    def test_list_peers_endpoint(self, client, node):
        """GET /federation/peers returns peer list."""
        node.peer_store.add_peer(
            did="did:vkb:key:z6MkPeer1",
            endpoint="http://peer1.example.com",
            public_key_multibase="z6MkPeer1Key",
        )
        node.peer_store.add_peer(
            did="did:vkb:key:z6MkPeer2",
            endpoint="http://peer2.example.com",
            public_key_multibase="z6MkPeer2Key",
        )

        response = client.get("/federation/peers")

        assert response.status_code == 200
        data = response.json()

        assert data["count"] == 2
        assert len(data["peers"]) == 2


# ============================================================================
# Client Method Tests
# ============================================================================


class TestFederationNodeClientMethods:
    """Test FederationNode client methods."""

    @pytest.fixture
    def node(self):
        """Create a test federation node."""
        with patch("valence.federation.server.generate_keypair") as mock_gen:
            mock_keypair = MagicMock()
            mock_keypair.public_key_multibase = "z6MkClient"
            mock_keypair.private_key_bytes = b"private_key_bytes"
            mock_gen.return_value = mock_keypair

            with patch("valence.federation.server.create_key_did") as mock_did:
                mock_did_obj = MagicMock()
                mock_did_obj.full = "did:vkb:key:z6MkClient"
                mock_did.return_value = mock_did_obj

                return FederationNode(name="Client Node", port=9001)

    @pytest.mark.asyncio
    async def test_introduce_to_success(self, node):
        """Successfully introduce to another node."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(
            return_value={
                "success": True,
                "node": {
                    "did": "did:vkb:key:z6MkRemote",
                    "endpoint": "http://remote.example.com",
                    "public_key_multibase": "z6MkRemoteKey",
                    "name": "Remote Node",
                },
            }
        )

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_ctx)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_ctx):
            result = await node.introduce_to("http://remote.example.com")

        assert result["success"] is True
        # Peer should be registered
        peer = node.peer_store.get_peer("did:vkb:key:z6MkRemote")
        assert peer is not None
        assert peer.name == "Remote Node"

    @pytest.mark.asyncio
    async def test_share_belief_success(self, node):
        """Successfully share a belief with a peer."""
        # Register peer first
        peer_did = "did:vkb:key:z6MkTarget"
        node.peer_store.add_peer(
            did=peer_did,
            endpoint="http://target.example.com",
            public_key_multibase="z6MkTargetKey",
        )

        mock_response = AsyncMock()
        mock_response.json = AsyncMock(
            return_value={
                "success": True,
                "belief_id": "shared-001",
            }
        )

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_ctx)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_ctx):
            with patch(
                "valence.federation.server.sign_belief_content",
                return_value="signature",
            ):
                with patch(
                    "valence.federation.server.check_federation_allowed",
                    return_value=(True, MagicMock()),
                ):
                    result = await node.share_belief(
                        peer_did=peer_did,
                        content="Shared belief content",
                        confidence=0.8,
                        domains=["test"],
                    )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_share_belief_pii_blocked(self, node):
        """Share is blocked when PII is detected."""
        peer_did = "did:vkb:key:z6MkTarget"
        node.peer_store.add_peer(
            did=peer_did,
            endpoint="http://target.example.com",
            public_key_multibase="z6MkTargetKey",
        )

        mock_scan_result = MagicMock()
        mock_scan_result.to_dict.return_value = {"level": "L3", "findings": ["email"]}

        with patch(
            "valence.federation.server.check_federation_allowed",
            return_value=(False, mock_scan_result),
        ):
            result = await node.share_belief(
                peer_did=peer_did,
                content="Contact me at john@example.com",
                confidence=0.8,
            )

        assert result["success"] is False
        assert "PII" in result["error"]

    @pytest.mark.asyncio
    async def test_share_belief_pii_force_override(self, node):
        """Share with force=True overrides PII block."""
        peer_did = "did:vkb:key:z6MkTarget"
        node.peer_store.add_peer(
            did=peer_did,
            endpoint="http://target.example.com",
            public_key_multibase="z6MkTargetKey",
        )

        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={"success": True, "belief_id": "x"})

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_ctx)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_ctx):
            with patch(
                "valence.federation.server.sign_belief_content", return_value="sig"
            ):
                with patch(
                    "valence.federation.server.check_federation_allowed",
                    return_value=(True, MagicMock()),
                ):
                    result = await node.share_belief(
                        peer_did=peer_did,
                        content="Contact me at john@example.com",
                        confidence=0.8,
                        force=True,
                    )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_share_belief_unknown_peer(self, node):
        """Share fails for unknown peer."""
        result = await node.share_belief(
            peer_did="did:vkb:key:z6MkUnknown",
            content="Test",
            confidence=0.8,
        )

        assert result["success"] is False
        assert "Unknown peer" in result["error"]

    @pytest.mark.asyncio
    async def test_query_peer_success(self, node):
        """Successfully query a peer."""
        peer_did = "did:vkb:key:z6MkQueryTarget"
        node.peer_store.add_peer(
            did=peer_did,
            endpoint="http://query-target.example.com",
            public_key_multibase="z6MkKey",
        )

        mock_response = AsyncMock()
        mock_response.json = AsyncMock(
            return_value={
                "success": True,
                "results": [
                    {"id": "result-1", "content": "Match 1", "confidence": 0.9},
                ],
            }
        )

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_ctx)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_ctx):
            result = await node.query_peer(
                peer_did=peer_did,
                query="test query",
                min_confidence=0.5,
            )

        assert result["success"] is True
        assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_query_peer_unknown(self, node):
        """Query fails for unknown peer."""
        result = await node.query_peer(
            peer_did="did:vkb:key:z6MkUnknown",
            query="test",
        )

        assert result["success"] is False
        assert "Unknown peer" in result["error"]


# ============================================================================
# create_node Factory Tests
# ============================================================================


class TestCreateNode:
    """Test create_node factory function."""

    @pytest.mark.asyncio
    async def test_create_node(self):
        """Create a node using factory function."""
        with patch("valence.federation.server.generate_keypair") as mock_gen:
            mock_keypair = MagicMock()
            mock_keypair.public_key_multibase = "z6MkFactory"
            mock_gen.return_value = mock_keypair

            with patch("valence.federation.server.create_key_did") as mock_did:
                mock_did_obj = MagicMock()
                mock_did_obj.full = "did:vkb:key:z6MkFactory"
                mock_did.return_value = mock_did_obj

                node = await create_node(name="Factory Node", port=9999)

        assert isinstance(node, FederationNode)
        assert node.name == "Factory Node"
        assert node.port == 9999
        assert node.host == "127.0.0.1"
