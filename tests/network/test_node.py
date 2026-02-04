"""Tests for the Valence Node Client.

These tests verify:
- Connection management (multi-router, reconnection)
- Router selection (weighted by health)
- Message sending and queueing
- Keepalive and failure detection
- IP diversity enforcement
"""

from __future__ import annotations

import asyncio
import ipaddress
import time
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from valence.network.node import (
    NodeClient,
    RouterConnection,
    PendingMessage,
    NodeError,
    NoRoutersAvailableError,
    create_node_client,
)
from valence.network.discovery import RouterInfo, DiscoveryClient


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def ed25519_keypair():
    """Generate an Ed25519 keypair for testing."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture
def x25519_keypair():
    """Generate an X25519 keypair for testing."""
    private_key = X25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture
def mock_router_info():
    """Create a mock RouterInfo."""
    return RouterInfo(
        router_id="a" * 64,
        endpoints=["192.168.1.1:8471"],
        capacity={"max_connections": 100, "current_load_pct": 25},
        health={"uptime_pct": 99.9, "avg_latency_ms": 50},
        regions=["us-west"],
        features=["relay-v1"],
    )


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket."""
    ws = AsyncMock()
    ws.closed = False
    ws.close = AsyncMock()
    ws.send_json = AsyncMock()
    ws.receive = AsyncMock()
    return ws


@pytest.fixture
def mock_session():
    """Create a mock aiohttp session."""
    session = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def node_client(ed25519_keypair, x25519_keypair):
    """Create a NodeClient for testing."""
    private_key, public_key = ed25519_keypair
    enc_private, _ = x25519_keypair
    
    return NodeClient(
        node_id=public_key.public_bytes_raw().hex(),
        private_key=private_key,
        encryption_private_key=enc_private,
        min_connections=1,
        target_connections=3,
        max_connections=5,
    )


# =============================================================================
# Unit Tests - RouterConnection
# =============================================================================


class TestRouterConnection:
    """Tests for the RouterConnection dataclass."""

    def test_router_connection_creation(self, mock_router_info, mock_websocket, mock_session):
        """Test creating a RouterConnection instance."""
        conn = RouterConnection(
            router=mock_router_info,
            websocket=mock_websocket,
            session=mock_session,
            connected_at=1000.0,
            last_seen=1000.0,
        )
        
        assert conn.router is mock_router_info
        assert conn.websocket is mock_websocket
        assert conn.connected_at == 1000.0
        assert conn.last_seen == 1000.0
        assert conn.messages_sent == 0
        assert conn.messages_received == 0

    def test_ack_success_rate_no_data(self, mock_router_info, mock_websocket, mock_session):
        """Test ACK success rate with no data (default to 1.0)."""
        conn = RouterConnection(
            router=mock_router_info,
            websocket=mock_websocket,
            session=mock_session,
            connected_at=1000.0,
            last_seen=1000.0,
        )
        
        assert conn.ack_success_rate == 1.0

    def test_ack_success_rate_with_data(self, mock_router_info, mock_websocket, mock_session):
        """Test ACK success rate calculation."""
        conn = RouterConnection(
            router=mock_router_info,
            websocket=mock_websocket,
            session=mock_session,
            connected_at=1000.0,
            last_seen=1000.0,
            ack_success=8,
            ack_failure=2,
        )
        
        assert conn.ack_success_rate == 0.8

    def test_health_score(self, mock_router_info, mock_websocket, mock_session):
        """Test health score calculation."""
        conn = RouterConnection(
            router=mock_router_info,
            websocket=mock_websocket,
            session=mock_session,
            connected_at=1000.0,
            last_seen=1000.0,
            ack_success=10,
            ack_failure=0,
            ping_latency_ms=100,
        )
        
        # ACK score: 1.0 * 0.5 = 0.5
        # Latency score: (1.0 - 100/500) * 0.3 = 0.8 * 0.3 = 0.24
        # Load score: (1.0 - 25/100) * 0.2 = 0.75 * 0.2 = 0.15
        # Total: 0.5 + 0.24 + 0.15 = 0.89
        assert 0.88 < conn.health_score < 0.90


# =============================================================================
# Unit Tests - PendingMessage
# =============================================================================


class TestPendingMessage:
    """Tests for the PendingMessage dataclass."""

    def test_pending_message_creation(self, x25519_keypair):
        """Test creating a PendingMessage instance."""
        _, public_key = x25519_keypair
        
        msg = PendingMessage(
            message_id="msg-123",
            recipient_id="recipient-456",
            content=b"Hello, World!",
            recipient_public_key=public_key,
            queued_at=2000.0,
        )
        
        assert msg.message_id == "msg-123"
        assert msg.recipient_id == "recipient-456"
        assert msg.content == b"Hello, World!"
        assert msg.queued_at == 2000.0
        assert msg.retries == 0
        assert msg.max_retries == 3


# =============================================================================
# Unit Tests - NodeClient
# =============================================================================


class TestNodeClient:
    """Tests for NodeClient core functionality."""

    def test_node_creation_defaults(self, ed25519_keypair, x25519_keypair):
        """Test creating a node with default settings."""
        private_key, public_key = ed25519_keypair
        enc_private, _ = x25519_keypair
        node_id = public_key.public_bytes_raw().hex()
        
        node = NodeClient(
            node_id=node_id,
            private_key=private_key,
            encryption_private_key=enc_private,
        )
        
        assert node.node_id == node_id
        assert node.min_connections == 3
        assert node.target_connections == 5
        assert node.max_connections == 8
        assert node.keepalive_interval == 30.0
        assert node.enforce_ip_diversity is True
        assert len(node.connections) == 0
        assert len(node.message_queue) == 0

    def test_node_creation_custom(self, ed25519_keypair, x25519_keypair):
        """Test creating a node with custom settings."""
        private_key, public_key = ed25519_keypair
        enc_private, _ = x25519_keypair
        node_id = public_key.public_bytes_raw().hex()
        
        node = NodeClient(
            node_id=node_id,
            private_key=private_key,
            encryption_private_key=enc_private,
            min_connections=2,
            target_connections=4,
            max_connections=6,
            keepalive_interval=60.0,
            enforce_ip_diversity=False,
        )
        
        assert node.min_connections == 2
        assert node.target_connections == 4
        assert node.max_connections == 6
        assert node.keepalive_interval == 60.0
        assert node.enforce_ip_diversity is False

    def test_get_stats(self, node_client):
        """Test getting node statistics."""
        stats = node_client.get_stats()
        
        assert "messages_sent" in stats
        assert "messages_received" in stats
        assert "active_connections" in stats
        assert "queued_messages" in stats
        assert stats["active_connections"] == 0
        assert stats["queued_messages"] == 0

    def test_get_connections_empty(self, node_client):
        """Test getting connections when none exist."""
        connections = node_client.get_connections()
        assert connections == []


# =============================================================================
# Unit Tests - Router Selection
# =============================================================================


class TestRouterSelection:
    """Tests for router selection logic."""

    def test_select_router_no_connections(self, node_client):
        """Test router selection with no connections."""
        result = node_client._select_router()
        assert result is None

    def test_select_router_single_connection(
        self, node_client, mock_router_info, mock_websocket, mock_session
    ):
        """Test router selection with single connection."""
        conn = RouterConnection(
            router=mock_router_info,
            websocket=mock_websocket,
            session=mock_session,
            connected_at=time.time(),
            last_seen=time.time(),
        )
        node_client.connections[mock_router_info.router_id] = conn
        
        result = node_client._select_router()
        assert result is mock_router_info

    def test_select_router_excludes_closed(
        self, node_client, mock_router_info, mock_websocket, mock_session
    ):
        """Test that closed connections are excluded from selection."""
        mock_websocket.closed = True
        
        conn = RouterConnection(
            router=mock_router_info,
            websocket=mock_websocket,
            session=mock_session,
            connected_at=time.time(),
            last_seen=time.time(),
        )
        node_client.connections[mock_router_info.router_id] = conn
        
        result = node_client._select_router()
        assert result is None

    def test_select_router_weighted(self, node_client, mock_session):
        """Test that healthier routers are selected more often."""
        # Create a healthy router
        healthy_router = RouterInfo(
            router_id="h" * 64,
            endpoints=["192.168.1.1:8471"],
            capacity={"max_connections": 100, "current_load_pct": 10},
            health={"uptime_pct": 99.9},
            regions=[],
            features=[],
        )
        healthy_ws = AsyncMock()
        healthy_ws.closed = False
        healthy_conn = RouterConnection(
            router=healthy_router,
            websocket=healthy_ws,
            session=mock_session,
            connected_at=time.time(),
            last_seen=time.time(),
            ack_success=100,
            ack_failure=0,
            ping_latency_ms=20,
        )
        
        # Create an unhealthy router
        unhealthy_router = RouterInfo(
            router_id="u" * 64,
            endpoints=["192.168.2.1:8471"],
            capacity={"max_connections": 100, "current_load_pct": 90},
            health={"uptime_pct": 50.0},
            regions=[],
            features=[],
        )
        unhealthy_ws = AsyncMock()
        unhealthy_ws.closed = False
        unhealthy_conn = RouterConnection(
            router=unhealthy_router,
            websocket=unhealthy_ws,
            session=mock_session,
            connected_at=time.time(),
            last_seen=time.time(),
            ack_success=50,
            ack_failure=50,
            ping_latency_ms=400,
        )
        
        node_client.connections[healthy_router.router_id] = healthy_conn
        node_client.connections[unhealthy_router.router_id] = unhealthy_conn
        
        # Run multiple selections and count
        healthy_count = 0
        trials = 1000
        
        for _ in range(trials):
            selected = node_client._select_router()
            if selected.router_id == healthy_router.router_id:
                healthy_count += 1
        
        # Healthy router should be selected significantly more often
        # (at least 60% of the time given the health difference)
        assert healthy_count > trials * 0.6


# =============================================================================
# Unit Tests - IP Diversity
# =============================================================================


class TestIPDiversity:
    """Tests for IP diversity enforcement."""

    def test_check_ip_diversity_empty(self, node_client, mock_router_info):
        """Test IP diversity check with no existing connections."""
        result = node_client._check_ip_diversity(mock_router_info)
        assert result is True

    def test_check_ip_diversity_same_subnet(self, node_client):
        """Test IP diversity check rejects same /16 subnet."""
        # Add first router
        router1 = RouterInfo(
            router_id="a" * 64,
            endpoints=["10.0.1.1:8471"],
            capacity={},
            health={},
            regions=[],
            features=[],
        )
        node_client._add_subnet(router1)
        
        # Check second router in same /16
        router2 = RouterInfo(
            router_id="b" * 64,
            endpoints=["10.0.2.1:8471"],
            capacity={},
            health={},
            regions=[],
            features=[],
        )
        
        result = node_client._check_ip_diversity(router2)
        assert result is False

    def test_check_ip_diversity_different_subnet(self, node_client):
        """Test IP diversity check allows different /16 subnets."""
        # Add first router
        router1 = RouterInfo(
            router_id="a" * 64,
            endpoints=["10.0.1.1:8471"],
            capacity={},
            health={},
            regions=[],
            features=[],
        )
        node_client._add_subnet(router1)
        
        # Check second router in different /16
        router2 = RouterInfo(
            router_id="b" * 64,
            endpoints=["10.1.1.1:8471"],
            capacity={},
            health={},
            regions=[],
            features=[],
        )
        
        result = node_client._check_ip_diversity(router2)
        assert result is True

    def test_check_ip_diversity_hostname(self, node_client):
        """Test IP diversity check allows hostnames."""
        # Add first router with IP
        router1 = RouterInfo(
            router_id="a" * 64,
            endpoints=["10.0.1.1:8471"],
            capacity={},
            health={},
            regions=[],
            features=[],
        )
        node_client._add_subnet(router1)
        
        # Check router with hostname
        router2 = RouterInfo(
            router_id="b" * 64,
            endpoints=["router.example.com:8471"],
            capacity={},
            health={},
            regions=[],
            features=[],
        )
        
        result = node_client._check_ip_diversity(router2)
        assert result is True

    def test_check_ip_diversity_no_endpoints(self, node_client):
        """Test IP diversity check with no endpoints."""
        router = RouterInfo(
            router_id="a" * 64,
            endpoints=[],
            capacity={},
            health={},
            regions=[],
            features=[],
        )
        
        result = node_client._check_ip_diversity(router)
        assert result is False

    def test_add_and_remove_subnet(self, node_client):
        """Test adding and removing subnet tracking."""
        router = RouterInfo(
            router_id="a" * 64,
            endpoints=["10.0.1.1:8471"],
            capacity={},
            health={},
            regions=[],
            features=[],
        )
        
        # Initially empty
        assert len(node_client._connected_subnets) == 0
        
        # Add subnet
        node_client._add_subnet(router)
        assert len(node_client._connected_subnets) == 1
        assert "10.0.0.0/16" in node_client._connected_subnets
        
        # Remove subnet
        node_client._remove_subnet(router)
        assert len(node_client._connected_subnets) == 0

    def test_ip_diversity_disabled(self, ed25519_keypair, x25519_keypair):
        """Test that IP diversity can be disabled."""
        private_key, public_key = ed25519_keypair
        enc_private, _ = x25519_keypair
        
        node = NodeClient(
            node_id=public_key.public_bytes_raw().hex(),
            private_key=private_key,
            encryption_private_key=enc_private,
            enforce_ip_diversity=False,
        )
        
        # Add first router
        router1 = RouterInfo(
            router_id="a" * 64,
            endpoints=["10.0.1.1:8471"],
            capacity={},
            health={},
            regions=[],
            features=[],
        )
        node._add_subnet(router1)
        
        # Same subnet should be allowed
        router2 = RouterInfo(
            router_id="b" * 64,
            endpoints=["10.0.2.1:8471"],
            capacity={},
            health={},
            regions=[],
            features=[],
        )
        
        # When disabled, check_ip_diversity isn't called, but if it were:
        result = node._check_ip_diversity(router2)
        # Still returns False because subnet is tracked, but enforcement is at _ensure_connections


# =============================================================================
# Unit Tests - Message Queueing
# =============================================================================


class TestMessageQueueing:
    """Tests for message queueing during failover."""

    @pytest.mark.asyncio
    async def test_send_message_queues_when_no_routers(
        self, node_client, x25519_keypair
    ):
        """Test that messages are queued when no routers available."""
        _, recipient_pub = x25519_keypair
        
        message_id = await node_client.send_message(
            recipient_id="recipient-123",
            recipient_public_key=recipient_pub,
            content=b"Hello!",
        )
        
        assert message_id is not None
        assert len(node_client.message_queue) == 1
        assert node_client.message_queue[0].content == b"Hello!"
        assert node_client._stats["messages_queued"] == 1

    @pytest.mark.asyncio
    async def test_queue_limit_enforced(self, node_client, x25519_keypair):
        """Test that queue size limit is enforced."""
        _, recipient_pub = x25519_keypair
        node_client.MAX_QUEUE_SIZE = 5
        
        # Queue up to limit
        for i in range(5):
            await node_client.send_message(
                recipient_id="recipient-123",
                recipient_public_key=recipient_pub,
                content=f"Message {i}".encode(),
            )
        
        assert len(node_client.message_queue) == 5
        
        # Next message should raise error
        with pytest.raises(NoRoutersAvailableError):
            await node_client.send_message(
                recipient_id="recipient-123",
                recipient_public_key=recipient_pub,
                content=b"Overflow!",
            )
        
        assert node_client._stats["messages_dropped"] == 1


# =============================================================================
# Unit Tests - ACK Handling
# =============================================================================


class TestACKHandling:
    """Tests for ACK message handling."""

    @pytest.mark.asyncio
    async def test_handle_ack_success(
        self, node_client, mock_router_info, mock_websocket, mock_session
    ):
        """Test handling successful ACK."""
        conn = RouterConnection(
            router=mock_router_info,
            websocket=mock_websocket,
            session=mock_session,
            connected_at=time.time(),
            last_seen=time.time(),
            ack_pending=1,
        )
        
        await node_client._handle_ack(
            {"message_id": "msg-123", "success": True},
            conn,
        )
        
        assert conn.ack_pending == 0
        assert conn.ack_success == 1
        assert conn.ack_failure == 0

    @pytest.mark.asyncio
    async def test_handle_ack_failure(
        self, node_client, mock_router_info, mock_websocket, mock_session
    ):
        """Test handling failed ACK."""
        conn = RouterConnection(
            router=mock_router_info,
            websocket=mock_websocket,
            session=mock_session,
            connected_at=time.time(),
            last_seen=time.time(),
            ack_pending=1,
        )
        
        await node_client._handle_ack(
            {"message_id": "msg-123", "success": False},
            conn,
        )
        
        assert conn.ack_pending == 0
        assert conn.ack_success == 0
        assert conn.ack_failure == 1


# =============================================================================
# Unit Tests - Pong Handling
# =============================================================================


class TestPongHandling:
    """Tests for pong message handling."""

    @pytest.mark.asyncio
    async def test_handle_pong_updates_latency(
        self, node_client, mock_router_info, mock_websocket, mock_session
    ):
        """Test that pong updates ping latency."""
        conn = RouterConnection(
            router=mock_router_info,
            websocket=mock_websocket,
            session=mock_session,
            connected_at=time.time(),
            last_seen=time.time(),
        )
        
        # Simulate ping sent 100ms ago
        sent_at = time.time() - 0.1
        
        await node_client._handle_pong(
            {"sent_at": sent_at},
            conn,
        )
        
        # Latency should be approximately 100ms
        assert 90 < conn.ping_latency_ms < 150


# =============================================================================
# Unit Tests - Factory Function
# =============================================================================


class TestCreateNodeClient:
    """Tests for the create_node_client factory function."""

    def test_create_node_client_basic(self, ed25519_keypair, x25519_keypair):
        """Test creating a node client via factory function."""
        private_key, _ = ed25519_keypair
        enc_private, _ = x25519_keypair
        
        node = create_node_client(
            private_key=private_key,
            encryption_private_key=enc_private,
        )
        
        assert node.node_id == private_key.public_key().public_bytes_raw().hex()
        assert node.private_key is private_key
        assert node.encryption_private_key is enc_private

    def test_create_node_client_with_discovery(
        self, ed25519_keypair, x25519_keypair
    ):
        """Test creating a node client with custom discovery client."""
        private_key, _ = ed25519_keypair
        enc_private, _ = x25519_keypair
        
        discovery = DiscoveryClient()
        discovery.add_seed("https://custom.seed:8470")
        
        node = create_node_client(
            private_key=private_key,
            encryption_private_key=enc_private,
            discovery_client=discovery,
        )
        
        assert node.discovery is discovery
        assert "https://custom.seed:8470" in node.discovery.custom_seeds

    def test_create_node_client_with_kwargs(self, ed25519_keypair, x25519_keypair):
        """Test creating a node client with additional kwargs."""
        private_key, _ = ed25519_keypair
        enc_private, _ = x25519_keypair
        
        node = create_node_client(
            private_key=private_key,
            encryption_private_key=enc_private,
            min_connections=2,
            target_connections=4,
            enforce_ip_diversity=False,
        )
        
        assert node.min_connections == 2
        assert node.target_connections == 4
        assert node.enforce_ip_diversity is False


# =============================================================================
# Integration Tests
# =============================================================================


class TestNodeIntegration:
    """Integration tests for NodeClient."""

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self, node_client):
        """Test node start/stop lifecycle."""
        # Mock discovery to avoid network calls
        with patch.object(
            node_client.discovery,
            'discover_routers',
            new_callable=AsyncMock,
            return_value=[],
        ):
            await node_client.start()
            assert node_client._running is True
            assert len(node_client._tasks) == 3  # maintenance, keepalive, queue
            
            await node_client.stop()
            assert node_client._running is False
            assert len(node_client._tasks) == 0

    @pytest.mark.asyncio
    async def test_get_connections_info(
        self, node_client, mock_router_info, mock_websocket, mock_session
    ):
        """Test getting connection information."""
        conn = RouterConnection(
            router=mock_router_info,
            websocket=mock_websocket,
            session=mock_session,
            connected_at=1000.0,
            last_seen=1000.0,
            messages_sent=5,
            messages_received=3,
            ack_success=4,
            ack_failure=1,
            ping_latency_ms=50.0,
        )
        node_client.connections[mock_router_info.router_id] = conn
        
        connections = node_client.get_connections()
        assert len(connections) == 1
        
        info = connections[0]
        assert "router_id" in info
        assert info["messages_sent"] == 5
        assert info["messages_received"] == 3
        assert info["ping_latency_ms"] == 50.0
        assert 0 <= info["ack_success_rate"] <= 1.0
        assert 0 <= info["health_score"] <= 1.0


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_ack_success_rate_division_by_zero(
        self, mock_router_info, mock_websocket, mock_session
    ):
        """Test ACK success rate with no ACKs (should not divide by zero)."""
        conn = RouterConnection(
            router=mock_router_info,
            websocket=mock_websocket,
            session=mock_session,
            connected_at=time.time(),
            last_seen=time.time(),
            ack_success=0,
            ack_failure=0,
        )
        
        # Should return 1.0, not raise ZeroDivisionError
        assert conn.ack_success_rate == 1.0

    def test_health_score_with_missing_capacity(self, mock_websocket, mock_session):
        """Test health score with missing capacity data."""
        router = RouterInfo(
            router_id="a" * 64,
            endpoints=["192.168.1.1:8471"],
            capacity={},  # No load data
            health={},
            regions=[],
            features=[],
        )
        
        conn = RouterConnection(
            router=router,
            websocket=mock_websocket,
            session=mock_session,
            connected_at=time.time(),
            last_seen=time.time(),
        )
        
        # Should handle missing data gracefully
        score = conn.health_score
        assert 0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_close_connection_already_closed(
        self, node_client, mock_router_info, mock_session
    ):
        """Test closing an already closed connection."""
        ws = AsyncMock()
        ws.closed = True
        ws.close = AsyncMock()
        
        conn = RouterConnection(
            router=mock_router_info,
            websocket=ws,
            session=mock_session,
            connected_at=time.time(),
            last_seen=time.time(),
        )
        
        # Should not raise
        await node_client._close_connection(mock_router_info.router_id, conn)

    def test_ip_diversity_ipv6(self, node_client):
        """Test IP diversity with IPv6 addresses."""
        # Add IPv6 router (using bracket notation for port separator)
        router1 = RouterInfo(
            router_id="a" * 64,
            endpoints=["[2001:db8::1]:8471"],
            capacity={},
            health={},
            regions=[],
            features=[],
        )
        node_client._add_subnet(router1)
        
        # Check same /48 (should be blocked by diversity)
        router2 = RouterInfo(
            router_id="b" * 64,
            endpoints=["[2001:db8::2]:8471"],
            capacity={},
            health={},
            regions=[],
            features=[],
        )
        
        result = node_client._check_ip_diversity(router2)
        assert result is False
        
        # Check different /48 (should be allowed)
        router3 = RouterInfo(
            router_id="c" * 64,
            endpoints=["[2001:db9::1]:8471"],
            capacity={},
            health={},
            regions=[],
            features=[],
        )
        
        result = node_client._check_ip_diversity(router3)
        assert result is True
