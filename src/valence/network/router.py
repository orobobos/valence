"""
Valence Router Node - Relays encrypted messages without reading them.

The router node is a key component of the Valence mesh network. It:
- Accepts WebSocket connections from other nodes
- Relays encrypted messages to their destinations
- Queues messages for offline nodes
- Maintains no persistent state about message contents (privacy-preserving)

Messages are end-to-end encrypted; routers only see routing metadata.

Registration Protocol:
- Router generates Ed25519 keypair for identity
- Registration includes PoW (proof-of-work) for anti-Sybil
- Heartbeats sent every 5 minutes with load metrics
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp
from aiohttp import WSMsgType, web
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

logger = logging.getLogger(__name__)


class RegistrationError(Exception):
    """Raised when router registration fails."""
    pass


@dataclass
class Connection:
    """Represents a connected node."""

    node_id: str
    websocket: web.WebSocketResponse
    connected_at: float
    last_seen: float


@dataclass
class QueuedMessage:
    """A message queued for an offline node."""

    message_id: str
    payload: str  # Encrypted payload (base64 or similar)
    queued_at: float
    ttl: int


@dataclass
class RouterNode:
    """Router node that relays encrypted messages between Valence nodes.

    The router is privacy-preserving:
    - Message payloads are end-to-end encrypted; router cannot read them
    - Only routing metadata (next_hop, ttl) is visible
    - No per-user tracking or logging

    Attributes:
        host: Bind address for the WebSocket server
        port: Port to listen on
        max_connections: Maximum concurrent connections
        seed_url: URL of seed node to register with (optional)
        heartbeat_interval: Seconds between seed heartbeats
        regions: Geographic regions this router serves
        features: Supported features/protocols
    """

    host: str = "0.0.0.0"
    port: int = 8471
    max_connections: int = 100
    seed_url: str | None = None
    heartbeat_interval: int = 300  # 5 minutes
    
    # Router identity and capabilities
    regions: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    
    # Ed25519 identity keypair (generated on init if not provided)
    _private_key: Ed25519PrivateKey | None = field(default=None, repr=False)
    _router_id: str | None = field(default=None, repr=False)

    # Runtime state
    connections: dict[str, Connection] = field(default_factory=dict)
    offline_queues: dict[str, list[QueuedMessage]] = field(default_factory=dict)

    # Metrics (aggregate only for privacy)
    messages_relayed: int = 0
    messages_queued: int = 0
    messages_delivered: int = 0
    connections_total: int = 0
    
    # Registration state
    _registered: bool = field(default=False, repr=False)
    _seed_id: str | None = field(default=None, repr=False)

    # Internal state
    _app: web.Application | None = field(default=None, repr=False)
    _runner: web.AppRunner | None = field(default=None, repr=False)
    _heartbeat_task: asyncio.Task | None = field(default=None, repr=False)
    _running: bool = field(default=False, repr=False)

    # Queue limits
    MAX_QUEUE_SIZE: int = 1000
    MAX_QUEUE_AGE: int = 3600  # 1 hour
    
    # PoW settings
    POW_DIFFICULTY: int = 16  # Default difficulty (leading zero bits)
    
    def __post_init__(self):
        """Initialize identity keypair if not provided."""
        if self._private_key is None:
            self._private_key = Ed25519PrivateKey.generate()
        
        if self._router_id is None:
            # Router ID is the hex-encoded public key
            public_key = self._private_key.public_key()
            self._router_id = public_key.public_bytes_raw().hex()
    
    @property
    def router_id(self) -> str:
        """Get the router's public identity (hex-encoded Ed25519 public key)."""
        return self._router_id
    
    @property
    def endpoints(self) -> list[str]:
        """Get the router's advertised endpoints."""
        return [f"{self.host}:{self.port}"]
    
    def get_capacity(self) -> dict[str, Any]:
        """Get current router capacity metrics."""
        return {
            "max_connections": self.max_connections,
            "current_connections": len(self.connections),
            "bandwidth_mbps": 100,  # Could be configurable
        }
    
    def _sign(self, data: dict[str, Any]) -> str:
        """Sign data with router's Ed25519 private key.
        
        Args:
            data: Dictionary to sign (will be JSON-serialized)
            
        Returns:
            Hex-encoded signature
        """
        message = json.dumps(data, sort_keys=True, separators=(',', ':')).encode()
        signature = self._private_key.sign(message)
        return signature.hex()
    
    def _generate_pow(self, difficulty: int | None = None) -> dict[str, Any]:
        """Generate proof-of-work for registration.
        
        PoW: Find nonce where sha256(challenge || nonce || router_id)
        has `difficulty` leading zero bits.
        
        Args:
            difficulty: Number of leading zero bits required (default: POW_DIFFICULTY)
            
        Returns:
            Dict with challenge, nonce, and difficulty
        """
        if difficulty is None:
            difficulty = self.POW_DIFFICULTY
        
        # Generate random challenge
        challenge = secrets.token_hex(16)
        
        nonce = 0
        while True:
            # Construct hash input
            hash_input = f"{challenge}{nonce}{self.router_id}".encode()
            hash_result = hashlib.sha256(hash_input).digest()
            
            # Count leading zero bits
            leading_zeros = 0
            for byte in hash_result:
                if byte == 0:
                    leading_zeros += 8
                else:
                    # Count leading zeros in this byte
                    for i in range(7, -1, -1):
                        if byte & (1 << i):
                            break
                        leading_zeros += 1
                    break
            
            if leading_zeros >= difficulty:
                logger.debug(f"PoW found: nonce={nonce}, zeros={leading_zeros}")
                return {
                    "challenge": challenge,
                    "nonce": nonce,
                    "difficulty": difficulty,
                }
            
            nonce += 1
            
            # Safety limit to avoid infinite loop in tests with high difficulty
            if nonce > 10_000_000:
                raise RuntimeError(f"PoW generation exceeded limit at difficulty {difficulty}")

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Handle incoming WebSocket connections from nodes."""
        if len(self.connections) >= self.max_connections:
            logger.warning("Max connections reached, rejecting new connection")
            return web.Response(status=503, text="Server at capacity")

        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)

        node_id: str | None = None
        self.connections_total += 1

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        logger.warning("Received invalid JSON")
                        continue

                    msg_type = data.get("type")

                    if msg_type == "identify":
                        node_id = await self._handle_identify(data, ws)

                    elif msg_type == "relay":
                        await self._handle_relay(data)

                    elif msg_type == "ping":
                        await ws.send_json({"type": "pong", "timestamp": time.time()})
                        if node_id and node_id in self.connections:
                            self.connections[node_id].last_seen = time.time()

                    else:
                        logger.debug(f"Unknown message type: {msg_type}")

                elif msg.type == WSMsgType.ERROR:
                    logger.warning(f"WebSocket error: {ws.exception()}")
                    break

                elif msg.type == WSMsgType.CLOSE:
                    break

        except Exception as e:
            logger.exception(f"Error handling WebSocket: {e}")

        finally:
            if node_id and node_id in self.connections:
                del self.connections[node_id]
                logger.info(f"Node disconnected: {node_id}")

        return ws

    async def _handle_identify(
        self, data: dict[str, Any], ws: web.WebSocketResponse
    ) -> str | None:
        """Handle node identification message."""
        node_id = data.get("node_id")
        if not node_id:
            await ws.send_json({"type": "error", "message": "Missing node_id"})
            return None

        # Check if already connected
        if node_id in self.connections:
            old_conn = self.connections[node_id]
            if not old_conn.websocket.closed:
                # Existing connection still active - reject new one
                await ws.send_json(
                    {"type": "error", "message": "Node already connected"}
                )
                return None

        # Register connection
        self.connections[node_id] = Connection(
            node_id=node_id,
            websocket=ws,
            connected_at=time.time(),
            last_seen=time.time(),
        )

        logger.info(f"Node connected: {node_id}")

        # Send acknowledgment
        await ws.send_json(
            {
                "type": "identified",
                "node_id": node_id,
                "timestamp": time.time(),
            }
        )

        # Deliver any queued messages
        delivered = await self._deliver_queued(node_id, ws)
        if delivered > 0:
            logger.info(f"Delivered {delivered} queued messages to {node_id}")

        return node_id

    async def _handle_relay(self, data: dict[str, Any]) -> None:
        """Relay a message to its destination.

        The payload is encrypted and opaque to us. We only look at routing metadata.
        """
        message_id = data.get("message_id")
        next_hop = data.get("next_hop")
        payload = data.get("payload")  # Encrypted - we can't read it
        ttl = data.get("ttl", 10)

        if not all([message_id, next_hop, payload]):
            logger.warning("Relay message missing required fields")
            return

        if ttl <= 0:
            logger.debug(f"Dropping expired message {message_id}")
            return

        self.messages_relayed += 1

        if next_hop in self.connections:
            # Deliver directly to connected node
            conn = self.connections[next_hop]
            try:
                await conn.websocket.send_json(
                    {
                        "type": "deliver",
                        "message_id": message_id,
                        "payload": payload,
                        "ttl": ttl - 1,
                    }
                )
                self.messages_delivered += 1
                logger.debug(f"Delivered message {message_id} to {next_hop}")
            except Exception as e:
                logger.warning(f"Failed to deliver to {next_hop}: {e}")
                # Queue for retry
                self._queue_message(
                    next_hop,
                    QueuedMessage(
                        message_id=message_id,
                        payload=payload,
                        queued_at=time.time(),
                        ttl=ttl - 1,
                    ),
                )
        else:
            # Node offline - queue message
            self._queue_message(
                next_hop,
                QueuedMessage(
                    message_id=message_id,
                    payload=payload,
                    queued_at=time.time(),
                    ttl=ttl - 1,
                ),
            )
            logger.debug(f"Queued message {message_id} for offline node {next_hop}")

    def _queue_message(self, node_id: str, msg: QueuedMessage) -> bool:
        """Queue a message for an offline node.

        Returns True if queued, False if queue is full.
        """
        if node_id not in self.offline_queues:
            self.offline_queues[node_id] = []

        queue = self.offline_queues[node_id]

        # Enforce queue size limit
        if len(queue) >= self.MAX_QUEUE_SIZE:
            logger.warning(f"Queue full for {node_id}, dropping oldest message")
            queue.pop(0)

        queue.append(msg)
        self.messages_queued += 1
        return True

    async def _deliver_queued(
        self, node_id: str, ws: web.WebSocketResponse
    ) -> int:
        """Deliver queued messages to a newly connected node.

        Returns the number of messages delivered.
        """
        if node_id not in self.offline_queues:
            return 0

        queue = self.offline_queues[node_id]
        delivered = 0
        now = time.time()

        for msg in queue:
            # Check if message has expired
            if now - msg.queued_at >= self.MAX_QUEUE_AGE:
                continue

            try:
                await ws.send_json(
                    {
                        "type": "deliver",
                        "message_id": msg.message_id,
                        "payload": msg.payload,
                        "ttl": msg.ttl,
                    }
                )
                delivered += 1
                self.messages_delivered += 1
            except Exception as e:
                logger.warning(f"Failed to deliver queued message: {e}")
                break

        # Clear the queue
        del self.offline_queues[node_id]

        return delivered

    async def handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response(
            {
                "status": "healthy",
                "connections": len(self.connections),
                "queued_nodes": len(self.offline_queues),
                "metrics": {
                    "messages_relayed": self.messages_relayed,
                    "messages_queued": self.messages_queued,
                    "messages_delivered": self.messages_delivered,
                    "connections_total": self.connections_total,
                },
            }
        )

    async def handle_status(self, request: web.Request) -> web.Response:
        """Detailed status endpoint."""
        return web.json_response(
            {
                "host": self.host,
                "port": self.port,
                "running": self._running,
                "seed_url": self.seed_url,
                "connections": {
                    "current": len(self.connections),
                    "max": self.max_connections,
                    "total": self.connections_total,
                },
                "queues": {
                    "nodes": len(self.offline_queues),
                    "total_messages": sum(
                        len(q) for q in self.offline_queues.values()
                    ),
                },
                "metrics": {
                    "messages_relayed": self.messages_relayed,
                    "messages_queued": self.messages_queued,
                    "messages_delivered": self.messages_delivered,
                },
            }
        )

    async def register_with_seed(self, seed_url: str | None = None) -> bool:
        """Register this router with the seed node.
        
        Registration includes:
        - Ed25519 signed payload
        - Proof-of-work for anti-Sybil protection
        - Router capabilities (regions, features, capacity)

        Args:
            seed_url: Override seed URL (uses self.seed_url if not provided)

        Returns:
            True if registration successful.
            
        Raises:
            RegistrationError: If registration is rejected by seed.
        """
        url = seed_url or self.seed_url
        if not url:
            return False

        registration_url = f"{url.rstrip('/')}/register"
        
        # Generate proof-of-work
        logger.info(f"Generating proof-of-work (difficulty={self.POW_DIFFICULTY})...")
        proof_of_work = self._generate_pow()
        
        # Build registration payload
        registration = {
            "router_id": self.router_id,
            "endpoints": self.endpoints,
            "capacity": self.get_capacity(),
            "regions": self.regions,
            "features": self.features,
            "proof_of_work": proof_of_work,
            "timestamp": time.time(),
        }
        
        # Sign the registration
        registration["signature"] = self._sign(registration)

        try:
            timeout = aiohttp.ClientTimeout(total=30)  # Longer timeout for PoW verification
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(registration_url, json=registration) as response:
                    result = await response.json()
                    
                    if result.get("status") == "accepted":
                        self._registered = True
                        self._seed_id = result.get("seed_id")
                        logger.info(
                            f"Registered with seed node {self._seed_id}: {url}"
                        )
                        return True
                    else:
                        reason = result.get("reason", "unknown")
                        logger.warning(
                            f"Seed registration rejected: {reason}"
                        )
                        raise RegistrationError(reason)
                        
        except RegistrationError:
            raise
        except Exception as e:
            logger.warning(f"Failed to register with seed: {e}")
            return False
    
    async def _register_with_seed(self) -> bool:
        """Legacy method for backward compatibility."""
        try:
            return await self.register_with_seed()
        except RegistrationError:
            return False

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to the seed node."""
        while self._running:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                if not self._running:
                    break

                await self._send_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Heartbeat error: {e}")

    async def _send_heartbeat(self) -> bool:
        """Send a heartbeat to the seed node.
        
        Heartbeat includes:
        - current_connections: Active WebSocket connections
        - load_pct: Estimated load percentage
        - messages_relayed: Total messages relayed since start
        - uptime_pct: Estimated uptime (placeholder)

        Returns True if heartbeat acknowledged.
        """
        if not self.seed_url:
            return False

        heartbeat_url = f"{self.seed_url.rstrip('/')}/heartbeat"
        
        # Calculate load percentage
        load_pct = (len(self.connections) / self.max_connections) * 100 if self.max_connections > 0 else 0
        
        # Build heartbeat payload
        heartbeat = {
            "router_id": self.router_id,
            "current_connections": len(self.connections),
            "load_pct": round(load_pct, 1),
            "messages_relayed": self.messages_relayed,
            "uptime_pct": 99.9,  # Placeholder - could track actual uptime
            "timestamp": time.time(),
        }
        
        # Sign the heartbeat
        heartbeat["signature"] = self._sign(heartbeat)

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(heartbeat_url, json=heartbeat) as response:
                    if response.status == 200:
                        result = await response.json()
                        health_status = result.get("health_status", "unknown")
                        next_interval = result.get("next_heartbeat_in", self.heartbeat_interval)
                        
                        logger.debug(
                            f"Heartbeat acknowledged: status={health_status}, "
                            f"next_in={next_interval}s"
                        )
                        return True
                    else:
                        text = await response.text()
                        logger.warning(f"Heartbeat failed ({response.status}): {text}")
                        return False
        except Exception as e:
            logger.warning(f"Heartbeat error: {e}")
            return False

    async def start(self) -> None:
        """Start the router node."""
        if self._running:
            logger.warning("Router already running")
            return

        self._app = web.Application()
        self._app.router.add_get("/ws", self.handle_websocket)
        self._app.router.add_get("/health", self.handle_health)
        self._app.router.add_get("/status", self.handle_status)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()

        self._running = True
        logger.info(f"Router node listening on {self.host}:{self.port}")

        # Register with seed if configured
        if self.seed_url:
            await self._register_with_seed()
            # Start heartbeat task
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        """Stop the router node."""
        if not self._running:
            return

        self._running = False

        # Cancel heartbeat task
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        # Close all WebSocket connections
        for node_id, conn in list(self.connections.items()):
            try:
                await conn.websocket.close()
            except Exception:
                pass
        self.connections.clear()

        # Cleanup runner
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

        self._app = None
        logger.info("Router node stopped")

    async def run_forever(self) -> None:
        """Start the router and run until interrupted."""
        await self.start()
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()
