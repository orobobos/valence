"""Tests for the transport adapter layer.

Covers:
* Interface contract (``TransportAdapter`` protocol conformance)
* Dataclass helpers (``Connection``, ``PeerInfo``, ``TransportConfig``)
* ``get_transport`` factory function
* ``LegacyTransportAdapter`` lifecycle and basic behaviour
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from valence.transport import (
    BACKEND_REGISTRY,
    Connection,
    PeerInfo,
    TransportAdapter,
    TransportConfig,
    TransportState,
    get_transport,
    register_backend,
)
from valence.transport.legacy import LegacyTransportAdapter

# =========================================================================
# Dataclass unit tests
# =========================================================================


class TestConnection:
    """Tests for :class:`Connection`."""

    def test_basic_fields(self) -> None:
        conn = Connection(peer_id="peer-1", remote_addr="127.0.0.1:4001")
        assert conn.peer_id == "peer-1"
        assert conn.remote_addr == "127.0.0.1:4001"
        assert conn.local_addr == ""
        assert conn.metadata == {}
        assert conn.established_at is not None

    def test_is_open_with_handle(self) -> None:
        conn = Connection(peer_id="p", remote_addr="addr", _handle="something")
        assert conn.is_open is True

    def test_is_open_without_handle(self) -> None:
        conn = Connection(peer_id="p", remote_addr="addr")
        assert conn.is_open is False

    @pytest.mark.asyncio
    async def test_close_clears_handle(self) -> None:
        conn = Connection(peer_id="p", remote_addr="addr", _handle="handle")
        assert conn.is_open
        await conn.close()
        assert not conn.is_open

    @pytest.mark.asyncio
    async def test_close_calls_async_handle(self) -> None:
        mock_handle = AsyncMock()
        mock_handle.close = AsyncMock()
        conn = Connection(peer_id="p", remote_addr="addr", _handle=mock_handle)
        await conn.close()
        mock_handle.close.assert_awaited_once()
        assert conn._handle is None

    @pytest.mark.asyncio
    async def test_close_calls_sync_handle(self) -> None:
        mock_handle = MagicMock()
        mock_handle.close = MagicMock()
        conn = Connection(peer_id="p", remote_addr="addr", _handle=mock_handle)
        await conn.close()
        mock_handle.close.assert_called_once()
        assert conn._handle is None

    @pytest.mark.asyncio
    async def test_close_noop_when_no_handle(self) -> None:
        conn = Connection(peer_id="p", remote_addr="addr")
        await conn.close()  # should not raise
        assert conn._handle is None


class TestPeerInfo:
    """Tests for :class:`PeerInfo`."""

    def test_primary_addr(self) -> None:
        p = PeerInfo(peer_id="peer-1", addrs=["addr1", "addr2"])
        assert p.primary_addr == "addr1"

    def test_primary_addr_empty(self) -> None:
        p = PeerInfo(peer_id="peer-1")
        assert p.primary_addr is None

    def test_defaults(self) -> None:
        p = PeerInfo(peer_id="x")
        assert p.addrs == []
        assert p.protocols == []
        assert p.metadata == {}
        assert p.last_seen is None


class TestTransportConfig:
    """Tests for :class:`TransportConfig`."""

    def test_defaults(self) -> None:
        cfg = TransportConfig()
        assert cfg.backend == "legacy"
        assert cfg.node_id == ""
        assert cfg.connect_timeout == 10.0
        assert cfg.send_timeout == 30.0
        assert cfg.enable_discovery is True
        assert cfg.extra == {}
        assert cfg.bootstrap_peers == []
        assert cfg.listen_addrs == []

    def test_override(self) -> None:
        cfg = TransportConfig(backend="quic", node_id="node-1", connect_timeout=5.0)
        assert cfg.backend == "quic"
        assert cfg.node_id == "node-1"
        assert cfg.connect_timeout == 5.0


class TestTransportState:
    """Tests for :class:`TransportState` enum."""

    def test_values(self) -> None:
        assert TransportState.STOPPED == "stopped"
        assert TransportState.STARTING == "starting"
        assert TransportState.RUNNING == "running"
        assert TransportState.STOPPING == "stopping"
        assert TransportState.ERROR == "error"


# =========================================================================
# Protocol conformance
# =========================================================================


class TestProtocolConformance:
    """Verify that LegacyTransportAdapter satisfies TransportAdapter."""

    def test_isinstance_check(self) -> None:
        adapter = LegacyTransportAdapter()
        assert isinstance(adapter, TransportAdapter)

    def test_required_methods_exist(self) -> None:
        adapter = LegacyTransportAdapter()
        assert hasattr(adapter, "start")
        assert hasattr(adapter, "stop")
        assert hasattr(adapter, "connect")
        assert hasattr(adapter, "listen")
        assert hasattr(adapter, "send")
        assert hasattr(adapter, "broadcast")
        assert hasattr(adapter, "subscribe")
        assert hasattr(adapter, "discover_peers")


class _MinimalTransport:
    """A minimal class that satisfies the TransportAdapter protocol.

    Used to verify the protocol definition itself is coherent.
    """

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def connect(self, peer_id: str, addrs: list[str]) -> Connection:
        return Connection(peer_id=peer_id, remote_addr=addrs[0] if addrs else "")

    async def listen(self, addr: str) -> AsyncIterator[Connection]:
        return
        yield

    async def send(self, peer_id: str, protocol: str, message: bytes) -> bytes:
        return b""

    async def broadcast(self, topic: str, message: bytes) -> None:
        pass

    async def subscribe(self, topic: str, handler: Callable[[str, bytes], Any]) -> None:
        pass

    async def discover_peers(self) -> list[PeerInfo]:
        return []


class TestMinimalTransportConformance:
    def test_isinstance(self) -> None:
        assert isinstance(_MinimalTransport(), TransportAdapter)


# =========================================================================
# Factory tests
# =========================================================================


class TestGetTransport:
    """Tests for :func:`get_transport`."""

    def test_default_returns_legacy(self) -> None:
        transport = get_transport()
        assert isinstance(transport, LegacyTransportAdapter)

    def test_explicit_legacy(self) -> None:
        transport = get_transport(TransportConfig(backend="legacy"))
        assert isinstance(transport, LegacyTransportAdapter)

    def test_unknown_backend_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown transport backend"):
            get_transport(TransportConfig(backend="does-not-exist"))

    def test_config_forwarded(self) -> None:
        cfg = TransportConfig(backend="legacy", node_id="test-node")
        transport = get_transport(cfg)
        assert isinstance(transport, LegacyTransportAdapter)
        assert transport._config.node_id == "test-node"


class TestRegisterBackend:
    """Tests for :func:`register_backend`."""

    def test_register_and_retrieve(self) -> None:
        # Register a fake backend
        register_backend("test-dummy", "valence.transport.legacy:LegacyTransportAdapter")
        try:
            transport = get_transport(TransportConfig(backend="test-dummy"))
            assert isinstance(transport, LegacyTransportAdapter)
        finally:
            # Clean up
            BACKEND_REGISTRY.pop("test-dummy", None)


# =========================================================================
# LegacyTransportAdapter tests
# =========================================================================


class TestLegacyLifecycle:
    """Tests for start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_stop(self) -> None:
        adapter = LegacyTransportAdapter()
        assert adapter.state == TransportState.STOPPED

        await adapter.start()
        assert adapter.state == TransportState.RUNNING

        await adapter.stop()
        assert adapter.state == TransportState.STOPPED

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self) -> None:
        adapter = LegacyTransportAdapter()
        await adapter.start()
        await adapter.start()  # should not raise
        assert adapter.state == TransportState.RUNNING
        await adapter.stop()

    @pytest.mark.asyncio
    async def test_double_stop_is_idempotent(self) -> None:
        adapter = LegacyTransportAdapter()
        await adapter.start()
        await adapter.stop()
        await adapter.stop()  # should not raise
        assert adapter.state == TransportState.STOPPED


class TestLegacyConnect:
    """Tests for connect/discover on the legacy adapter."""

    @pytest.mark.asyncio
    async def test_connect_returns_connection(self) -> None:
        adapter = LegacyTransportAdapter()
        await adapter.start()
        try:
            conn = await adapter.connect("did:vkb:test", ["http://localhost:8080"])
            assert conn.peer_id == "did:vkb:test"
            assert conn.remote_addr == "http://localhost:8080"
            assert conn.is_open
        finally:
            await adapter.stop()

    @pytest.mark.asyncio
    async def test_connect_when_not_running_raises(self) -> None:
        adapter = LegacyTransportAdapter()
        with pytest.raises(RuntimeError, match="not running"):
            await adapter.connect("peer", ["addr"])

    @pytest.mark.asyncio
    async def test_discover_peers_after_connect(self) -> None:
        adapter = LegacyTransportAdapter()
        await adapter.start()
        try:
            await adapter.connect("did:vkb:alice", ["http://alice.example.com"])
            peers = await adapter.discover_peers()
            peer_ids = [p.peer_id for p in peers]
            assert "did:vkb:alice" in peer_ids
        finally:
            await adapter.stop()


class TestLegacyPubsub:
    """Tests for broadcast/subscribe."""

    @pytest.mark.asyncio
    async def test_subscribe_and_broadcast(self) -> None:
        adapter = LegacyTransportAdapter()
        await adapter.start()
        try:
            received: list[tuple[str, bytes]] = []

            def handler(peer_id: str, data: bytes) -> None:
                received.append((peer_id, data))

            await adapter.subscribe("test-topic", handler)
            await adapter.broadcast("test-topic", b"hello world")

            assert len(received) == 1
            assert received[0][1] == b"hello world"
        finally:
            await adapter.stop()

    @pytest.mark.asyncio
    async def test_broadcast_to_empty_topic(self) -> None:
        adapter = LegacyTransportAdapter()
        await adapter.start()
        try:
            # Should not raise even with no subscribers
            await adapter.broadcast("empty-topic", b"data")
        finally:
            await adapter.stop()

    @pytest.mark.asyncio
    async def test_subscribe_async_handler(self) -> None:
        adapter = LegacyTransportAdapter()
        await adapter.start()
        try:
            received: list[bytes] = []

            async def handler(peer_id: str, data: bytes) -> None:
                received.append(data)

            await adapter.subscribe("async-topic", handler)
            await adapter.broadcast("async-topic", b"async-msg")

            assert received == [b"async-msg"]
        finally:
            await adapter.stop()

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self) -> None:
        adapter = LegacyTransportAdapter()
        await adapter.start()
        try:
            counts = {"a": 0, "b": 0}

            def handler_a(peer_id: str, data: bytes) -> None:
                counts["a"] += 1

            def handler_b(peer_id: str, data: bytes) -> None:
                counts["b"] += 1

            await adapter.subscribe("multi", handler_a)
            await adapter.subscribe("multi", handler_b)
            await adapter.broadcast("multi", b"x")

            assert counts["a"] == 1
            assert counts["b"] == 1
        finally:
            await adapter.stop()


class TestLegacyListen:
    """Tests for the listen method."""

    @pytest.mark.asyncio
    async def test_listen_is_empty_iterator(self) -> None:
        adapter = LegacyTransportAdapter()
        await adapter.start()
        try:
            connections = []
            async for conn in adapter.listen("0.0.0.0:4001"):
                connections.append(conn)
            assert connections == []
        finally:
            await adapter.stop()


class TestLegacyBootstrap:
    """Tests for bootstrap peer configuration."""

    @pytest.mark.asyncio
    async def test_bootstrap_peers_registered(self) -> None:
        config = TransportConfig(
            backend="legacy",
            bootstrap_peers=["http://seed1.example.com", "http://seed2.example.com"],
        )
        adapter = LegacyTransportAdapter(config)
        await adapter.start()
        try:
            peers = await adapter.discover_peers()
            addrs = []
            for p in peers:
                addrs.extend(p.addrs)
            assert "http://seed1.example.com" in addrs
            assert "http://seed2.example.com" in addrs
        finally:
            await adapter.stop()
