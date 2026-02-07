"""Transport Adapter — abstract interface for pluggable P2P networking.

Defines the ``TransportAdapter`` protocol that every networking backend must
satisfy, along with supporting dataclasses (``Connection``, ``PeerInfo``,
``TransportConfig``).

Design goals:
* Pure protocol — no concrete base class so backends stay decoupled.
* Async-first — every I/O operation is a coroutine.
* Minimal surface — only the operations the upper layers actually need.

See Also:
    ``valence.transport.legacy`` for the adapter that wraps the existing
    federation / network stack.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class TransportState(StrEnum):
    """Lifecycle state of a transport backend."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class TransportConfig:
    """Configuration blob handed to :func:`get_transport`.

    Every field has a sensible default so callers can start with
    ``TransportConfig()`` and override as needed.
    """

    # Which backend to instantiate (e.g. "legacy", "libp2p", "quic")
    backend: str = "legacy"

    # Network identity
    node_id: str = ""
    listen_addrs: list[str] = field(default_factory=list)

    # Timeouts (seconds)
    connect_timeout: float = 10.0
    send_timeout: float = 30.0

    # Discovery
    bootstrap_peers: list[str] = field(default_factory=list)
    enable_discovery: bool = True

    # Extra backend-specific options
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PeerInfo:
    """Lightweight description of a discovered peer."""

    peer_id: str
    addrs: list[str] = field(default_factory=list)
    protocols: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_seen: datetime | None = None

    # Convenience helpers --------------------------------------------------

    @property
    def primary_addr(self) -> str | None:
        """Return the first address, if any."""
        return self.addrs[0] if self.addrs else None


@dataclass
class Connection:
    """Represents an open connection to a remote peer.

    Transports populate this with whatever handles they need; the upper
    layer only reads the public fields.
    """

    peer_id: str
    remote_addr: str
    local_addr: str = ""
    established_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Internals (the transport backend stashes its own handles here)
    _handle: Any = field(default=None, repr=False)

    @property
    def is_open(self) -> bool:
        """Whether the connection is still considered open."""
        return self._handle is not None

    async def close(self) -> None:
        """Close the connection.

        Delegates to the transport backend via the stashed ``_handle``.
        If the handle exposes a ``close`` coroutine it is awaited;
        otherwise we just clear the reference.
        """
        if self._handle is not None:
            close_fn = getattr(self._handle, "close", None)
            if close_fn is not None and asyncio.iscoroutinefunction(close_fn):
                await close_fn()
            elif callable(close_fn):
                close_fn()
            self._handle = None


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class TransportAdapter(Protocol):
    """Protocol every transport backend must implement.

    Using ``typing.Protocol`` (with ``@runtime_checkable``) rather than
    ``abc.ABC`` so that backends never need to inherit from a shared base.
    """

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Initialise the transport (bind ports, start listeners, …)."""
        ...

    async def stop(self) -> None:
        """Tear down the transport gracefully."""
        ...

    # -- connections -------------------------------------------------------

    async def connect(self, peer_id: str, addrs: list[str]) -> Connection:
        """Open a connection to *peer_id* at one of *addrs*."""
        ...

    async def listen(self, addr: str) -> AsyncIterator[Connection]:
        """Yield incoming connections on *addr*."""
        ...  # pragma: no cover — Protocol stub

    # -- messaging ---------------------------------------------------------

    async def send(self, peer_id: str, protocol: str, message: bytes) -> bytes:
        """Send *message* using *protocol* and return the response."""
        ...

    async def broadcast(self, topic: str, message: bytes) -> None:
        """Publish *message* to a pubsub *topic*."""
        ...

    async def subscribe(self, topic: str, handler: Callable[[str, bytes], Any]) -> None:
        """Subscribe to *topic*; call ``handler(peer_id, data)`` on each message."""
        ...

    # -- discovery ---------------------------------------------------------

    async def discover_peers(self) -> list[PeerInfo]:
        """Return a snapshot of currently known peers."""
        ...


# ---------------------------------------------------------------------------
# Supporting types used by transport backends
# ---------------------------------------------------------------------------


class TransportError(Exception):
    """Raised when a transport operation fails."""


@dataclass
class MessageEnvelope:
    """Wraps a message with routing metadata for transport."""

    payload: bytes
    topic: str = ""
    sender_id: str = ""
    source: str = ""
    correlation_id: str = ""
    message_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            import time

            self.timestamp = time.time()


# Callback type for message subscriptions
MessageHandler = Callable[[MessageEnvelope], Any]
