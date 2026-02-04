"""
Valence Node Client - User nodes connect to routers for message relay.

User nodes maintain connections to multiple routers for redundancy and
load balancing. This module provides:

- Multi-router connection management
- Weighted router selection based on health metrics
- Keepalive and automatic failure detection
- Message queueing during failover
- IP diversity enforcement (different /16 subnets)

Architecture:
- Each node connects to target_connections (default 5) routers
- Routers are selected based on ACK success rate and load
- Connections are monitored via periodic pings
- Failed connections are replaced automatically via discovery
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

import aiohttp
from aiohttp import WSMsgType
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

from .discovery import DiscoveryClient, RouterInfo
from .crypto import encrypt_message, decrypt_message

logger = logging.getLogger(__name__)


# =============================================================================
# EXCEPTIONS
# =============================================================================


class NodeError(Exception):
    """Base exception for node errors."""
    pass


class ConnectionError(NodeError):
    """Raised when connection to router fails."""
    pass


class NoRoutersAvailableError(NodeError):
    """Raised when no routers are available."""
    pass


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass
class RouterConnection:
    """Represents an active connection to a router."""
    
    router: RouterInfo
    websocket: aiohttp.ClientWebSocketResponse
    session: aiohttp.ClientSession  # Keep session for cleanup
    connected_at: float
    last_seen: float
    messages_sent: int = 0
    messages_received: int = 0
    ack_pending: int = 0
    ack_success: int = 0
    ack_failure: int = 0
    ping_latency_ms: float = 0.0
    
    @property
    def ack_success_rate(self) -> float:
        """Calculate ACK success rate (0.0 to 1.0)."""
        total = self.ack_success + self.ack_failure
        if total == 0:
            return 1.0  # Assume good until proven otherwise
        return self.ack_success / total
    
    @property
    def health_score(self) -> float:
        """Calculate overall health score (0.0 to 1.0)."""
        # Combine ACK success rate, latency, and load
        ack_score = self.ack_success_rate
        
        # Latency penalty (>500ms is bad)
        latency_score = max(0, 1.0 - (self.ping_latency_ms / 500))
        
        # Load from router capacity
        load_pct = self.router.capacity.get("current_load_pct", 0)
        load_score = 1.0 - (load_pct / 100)
        
        # Weighted combination
        return (ack_score * 0.5) + (latency_score * 0.3) + (load_score * 0.2)


@dataclass
class PendingMessage:
    """Message queued for delivery during failover."""
    
    message_id: str
    recipient_id: str
    content: bytes
    recipient_public_key: X25519PublicKey
    queued_at: float
    retries: int = 0
    max_retries: int = 3


# =============================================================================
# NODE CLIENT
# =============================================================================


@dataclass
class NodeClient:
    """
    User node that connects to routers for message relay.
    
    The node maintains connections to multiple routers for redundancy.
    Messages are encrypted end-to-end; routers only see routing metadata.
    
    Example:
        node = NodeClient(
            node_id="abc123...",
            private_key=my_ed25519_private_key,
            encryption_private_key=my_x25519_private_key,
        )
        await node.start()
        await node.send_message(recipient_id, recipient_pub_key, b"Hello!")
        await node.stop()
    
    Attributes:
        node_id: Our Ed25519 public key (hex)
        private_key: Our Ed25519 private key for signing
        encryption_private_key: Our X25519 private key for decryption
        min_connections: Minimum router connections to maintain
        target_connections: Ideal number of router connections
        max_connections: Maximum router connections allowed
    """
    
    # Identity
    node_id: str  # Ed25519 public key (hex)
    private_key: Ed25519PrivateKey
    encryption_private_key: X25519PrivateKey
    
    # Connection config
    min_connections: int = 3
    target_connections: int = 5
    max_connections: int = 8
    
    # Timing config
    keepalive_interval: float = 30.0  # seconds between pings
    ping_timeout: float = 5.0  # seconds to wait for pong
    maintenance_interval: float = 60.0  # seconds between maintenance runs
    reconnect_delay: float = 5.0  # seconds before reconnecting after failure
    
    # IP diversity: require different /16 subnets
    enforce_ip_diversity: bool = True
    ip_diversity_prefix: int = 16  # /16 subnet diversity
    
    # State
    connections: Dict[str, RouterConnection] = field(default_factory=dict)
    discovery: DiscoveryClient = field(default_factory=DiscoveryClient)
    message_queue: List[PendingMessage] = field(default_factory=list)
    
    # Callbacks for message handling
    on_message: Optional[Callable[[str, bytes], None]] = None
    
    # Internal state
    _running: bool = field(default=False, repr=False)
    _tasks: List[asyncio.Task] = field(default_factory=list, repr=False)
    _connected_subnets: Set[str] = field(default_factory=set, repr=False)
    
    # Statistics
    _stats: Dict[str, int] = field(default_factory=lambda: {
        "messages_sent": 0,
        "messages_received": 0,
        "messages_queued": 0,
        "messages_dropped": 0,
        "connections_established": 0,
        "connections_failed": 0,
        "failovers": 0,
    })
    
    # Queue limits
    MAX_QUEUE_SIZE: int = 1000
    MAX_QUEUE_AGE: float = 3600.0  # 1 hour
    
    # -------------------------------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------------------------------
    
    async def start(self) -> None:
        """
        Start the node - discover routers and connect.
        
        This initiates router discovery, establishes connections,
        and starts background maintenance tasks.
        """
        if self._running:
            logger.warning("Node already running")
            return
        
        self._running = True
        logger.info(f"Starting node {self.node_id[:16]}...")
        
        # Initial connection establishment
        await self._ensure_connections()
        
        # Start background tasks
        self._tasks.append(asyncio.create_task(self._connection_maintenance()))
        self._tasks.append(asyncio.create_task(self._keepalive_loop()))
        self._tasks.append(asyncio.create_task(self._queue_processor()))
        
        logger.info(
            f"Node started with {len(self.connections)} router connections"
        )
    
    async def stop(self) -> None:
        """Stop the node and close all connections."""
        if not self._running:
            return
        
        self._running = False
        logger.info("Stopping node...")
        
        # Cancel background tasks
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        
        # Close all connections
        for router_id, conn in list(self.connections.items()):
            await self._close_connection(router_id, conn)
        self.connections.clear()
        self._connected_subnets.clear()
        
        logger.info("Node stopped")
    
    async def send_message(
        self,
        recipient_id: str,
        recipient_public_key: X25519PublicKey,
        content: bytes,
    ) -> str:
        """
        Send an encrypted message to a recipient via router.
        
        The message is encrypted end-to-end using the recipient's X25519
        public key. The router only sees the encrypted payload and
        routing metadata.
        
        Args:
            recipient_id: Recipient's node ID (Ed25519 public key hex)
            recipient_public_key: Recipient's X25519 public key for encryption
            content: Raw message bytes to encrypt and send
            
        Returns:
            Message ID (UUID string)
            
        Raises:
            NoRoutersAvailableError: If no routers are connected and queue is full
        """
        message_id = str(uuid.uuid4())
        
        # Select best router
        router = self._select_router()
        if not router:
            # Queue message for later delivery
            if len(self.message_queue) >= self.MAX_QUEUE_SIZE:
                self._stats["messages_dropped"] += 1
                raise NoRoutersAvailableError(
                    "No routers available and message queue full"
                )
            
            self.message_queue.append(PendingMessage(
                message_id=message_id,
                recipient_id=recipient_id,
                content=content,
                recipient_public_key=recipient_public_key,
                queued_at=time.time(),
            ))
            self._stats["messages_queued"] += 1
            logger.debug(f"Message {message_id} queued (no routers available)")
            return message_id
        
        # Send via selected router
        await self._send_via_router(
            router,
            message_id,
            recipient_id,
            recipient_public_key,
            content,
        )
        
        return message_id
    
    def get_stats(self) -> Dict[str, Any]:
        """Get node statistics."""
        return {
            **self._stats,
            "active_connections": len(self.connections),
            "queued_messages": len(self.message_queue),
            "connected_subnets": len(self._connected_subnets),
        }
    
    def get_connections(self) -> List[Dict[str, Any]]:
        """Get information about active connections."""
        return [
            {
                "router_id": router_id[:16] + "...",
                "endpoint": conn.router.endpoints[0] if conn.router.endpoints else "unknown",
                "connected_at": conn.connected_at,
                "last_seen": conn.last_seen,
                "health_score": round(conn.health_score, 3),
                "ack_success_rate": round(conn.ack_success_rate, 3),
                "ping_latency_ms": round(conn.ping_latency_ms, 1),
                "messages_sent": conn.messages_sent,
                "messages_received": conn.messages_received,
            }
            for router_id, conn in self.connections.items()
        ]
    
    # -------------------------------------------------------------------------
    # CONNECTION MANAGEMENT
    # -------------------------------------------------------------------------
    
    async def _ensure_connections(self) -> None:
        """Ensure we have enough router connections."""
        attempts = 0
        max_attempts = 3
        
        while len(self.connections) < self.target_connections and attempts < max_attempts:
            needed = self.target_connections - len(self.connections)
            
            # Get excluded router IDs (already connected)
            excluded_ids = set(self.connections.keys())
            
            # Discover routers
            try:
                routers = await self.discovery.discover_routers(
                    count=needed * 2,  # Request extra for filtering
                    preferences={"region": "any"},
                )
            except Exception as e:
                logger.warning(f"Router discovery failed: {e}")
                attempts += 1
                continue
            
            # Filter and connect
            for router in routers:
                if len(self.connections) >= self.target_connections:
                    break
                
                if router.router_id in excluded_ids:
                    continue
                
                # Check IP diversity
                if self.enforce_ip_diversity:
                    if not self._check_ip_diversity(router):
                        logger.debug(
                            f"Skipping router {router.router_id[:16]}... "
                            f"(IP diversity check failed)"
                        )
                        continue
                
                try:
                    await self._connect_to_router(router)
                except Exception as e:
                    logger.warning(
                        f"Failed to connect to router {router.router_id[:16]}...: {e}"
                    )
                    self._stats["connections_failed"] += 1
                    continue
            
            attempts += 1
        
        if len(self.connections) < self.min_connections:
            logger.warning(
                f"Only {len(self.connections)} connections established "
                f"(minimum: {self.min_connections})"
            )
    
    def _check_ip_diversity(self, router: RouterInfo) -> bool:
        """
        Check if connecting to this router maintains IP diversity.
        
        We require routers to be in different /16 subnets to prevent
        a single network operator from controlling all our connections.
        
        Args:
            router: Router to check
            
        Returns:
            True if router passes diversity check
        """
        if not router.endpoints:
            return False
        
        try:
            # Parse IP from first endpoint
            # Formats: "ip:port", "[ipv6]:port", "hostname:port"
            endpoint = router.endpoints[0]
            
            # Handle IPv6 bracket notation: [ipv6]:port
            if endpoint.startswith("["):
                bracket_end = endpoint.find("]")
                if bracket_end == -1:
                    return True  # Malformed, allow
                host = endpoint[1:bracket_end]
            else:
                # IPv4 or hostname: ip:port
                host = endpoint.split(":")[0]
            
            # Try to parse as IP address
            try:
                ip = ipaddress.ip_address(host)
            except ValueError:
                # Not an IP, could be hostname - allow it
                return True
            
            # Get /16 subnet for IPv4, /48 for IPv6
            if ip.version == 4:
                network = ipaddress.ip_network(
                    f"{ip}/{self.ip_diversity_prefix}", strict=False
                )
            else:
                # IPv6: use /48 prefix
                network = ipaddress.ip_network(f"{ip}/48", strict=False)
            
            subnet_key = str(network)
            
            if subnet_key in self._connected_subnets:
                return False
            
            return True
            
        except Exception as e:
            logger.debug(f"IP diversity check error: {e}")
            return True  # Allow on error
    
    def _add_subnet(self, router: RouterInfo) -> None:
        """Track the subnet of a connected router."""
        if not router.endpoints:
            return
        
        try:
            endpoint = router.endpoints[0]
            
            # Handle IPv6 bracket notation: [ipv6]:port
            if endpoint.startswith("["):
                bracket_end = endpoint.find("]")
                if bracket_end == -1:
                    return
                host = endpoint[1:bracket_end]
            else:
                host = endpoint.split(":")[0]
            
            try:
                ip = ipaddress.ip_address(host)
            except ValueError:
                return
            
            if ip.version == 4:
                network = ipaddress.ip_network(
                    f"{ip}/{self.ip_diversity_prefix}", strict=False
                )
            else:
                network = ipaddress.ip_network(f"{ip}/48", strict=False)
            
            self._connected_subnets.add(str(network))
            
        except Exception:
            pass
    
    def _remove_subnet(self, router: RouterInfo) -> None:
        """Remove subnet tracking when disconnecting from router."""
        if not router.endpoints:
            return
        
        try:
            endpoint = router.endpoints[0]
            
            # Handle IPv6 bracket notation: [ipv6]:port
            if endpoint.startswith("["):
                bracket_end = endpoint.find("]")
                if bracket_end == -1:
                    return
                host = endpoint[1:bracket_end]
            else:
                host = endpoint.split(":")[0]
            
            try:
                ip = ipaddress.ip_address(host)
            except ValueError:
                return
            
            if ip.version == 4:
                network = ipaddress.ip_network(
                    f"{ip}/{self.ip_diversity_prefix}", strict=False
                )
            else:
                network = ipaddress.ip_network(f"{ip}/48", strict=False)
            
            self._connected_subnets.discard(str(network))
            
        except Exception:
            pass
    
    async def _connect_to_router(self, router: RouterInfo) -> None:
        """
        Establish WebSocket connection to a router.
        
        Args:
            router: Router to connect to
            
        Raises:
            ConnectionError: If connection fails
        """
        if not router.endpoints:
            raise ConnectionError("Router has no endpoints")
        
        endpoint = router.endpoints[0]
        
        # Try each endpoint
        for endpoint in router.endpoints:
            try:
                ws_url = f"wss://{endpoint}/ws"
                
                session = aiohttp.ClientSession()
                try:
                    ws = await session.ws_connect(
                        ws_url,
                        heartbeat=30,
                        timeout=aiohttp.ClientTimeout(total=10),
                    )
                except Exception:
                    await session.close()
                    continue
                
                # Identify ourselves
                await ws.send_json({
                    "type": "identify",
                    "node_id": self.node_id,
                })
                
                # Wait for identification response
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
                    if msg.type == WSMsgType.TEXT:
                        response = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: __import__('json').loads(msg.data)
                        )
                        if response.get("type") != "identified":
                            raise ConnectionError(
                                f"Unexpected response: {response.get('type')}"
                            )
                    else:
                        raise ConnectionError(f"Unexpected message type: {msg.type}")
                except asyncio.TimeoutError:
                    await ws.close()
                    await session.close()
                    raise ConnectionError("Identification timeout")
                
                # Create connection record
                now = time.time()
                conn = RouterConnection(
                    router=router,
                    websocket=ws,
                    session=session,
                    connected_at=now,
                    last_seen=now,
                )
                
                self.connections[router.router_id] = conn
                self._add_subnet(router)
                self._stats["connections_established"] += 1
                
                # Start receive loop
                self._tasks.append(
                    asyncio.create_task(self._receive_loop(router.router_id))
                )
                
                logger.info(
                    f"Connected to router {router.router_id[:16]}... "
                    f"at {endpoint}"
                )
                return
                
            except ConnectionError:
                raise
            except Exception as e:
                logger.debug(f"Failed to connect to {endpoint}: {e}")
                continue
        
        raise ConnectionError(f"Failed to connect to any endpoint for router")
    
    async def _close_connection(
        self,
        router_id: str,
        conn: RouterConnection,
    ) -> None:
        """Close a router connection and clean up."""
        try:
            if not conn.websocket.closed:
                await conn.websocket.close()
        except Exception:
            pass
        
        try:
            await conn.session.close()
        except Exception:
            pass
        
        self._remove_subnet(conn.router)
    
    # -------------------------------------------------------------------------
    # MESSAGE HANDLING
    # -------------------------------------------------------------------------
    
    async def _send_via_router(
        self,
        router: RouterInfo,
        message_id: str,
        recipient_id: str,
        recipient_public_key: X25519PublicKey,
        content: bytes,
    ) -> None:
        """Send an encrypted message via a specific router."""
        conn = self.connections.get(router.router_id)
        if not conn or conn.websocket.closed:
            raise ConnectionError(f"Not connected to router {router.router_id[:16]}...")
        
        # Encrypt for recipient
        encrypted = encrypt_message(content, recipient_public_key, self.private_key)
        
        # Send via router
        await conn.websocket.send_json({
            "type": "relay",
            "message_id": message_id,
            "next_hop": recipient_id,
            "payload": encrypted,
            "ttl": 10,
        })
        
        conn.messages_sent += 1
        conn.ack_pending += 1
        self._stats["messages_sent"] += 1
        
        logger.debug(f"Sent message {message_id} via router {router.router_id[:16]}...")
    
    async def _receive_loop(self, router_id: str) -> None:
        """Receive messages from a router connection."""
        conn = self.connections.get(router_id)
        if not conn:
            return
        
        try:
            async for msg in conn.websocket:
                if not self._running:
                    break
                
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = __import__('json').loads(msg.data)
                    except __import__('json').JSONDecodeError:
                        logger.warning("Received invalid JSON from router")
                        continue
                    
                    msg_type = data.get("type")
                    
                    if msg_type == "deliver":
                        await self._handle_deliver(data, conn)
                    
                    elif msg_type == "pong":
                        await self._handle_pong(data, conn)
                    
                    elif msg_type == "ack":
                        await self._handle_ack(data, conn)
                    
                    elif msg_type == "error":
                        logger.warning(
                            f"Router error: {data.get('message', 'unknown')}"
                        )
                    
                    else:
                        logger.debug(f"Unknown message type from router: {msg_type}")
                    
                    conn.last_seen = time.time()
                
                elif msg.type == WSMsgType.ERROR:
                    logger.warning(f"WebSocket error: {conn.websocket.exception()}")
                    break
                
                elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED):
                    break
        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"Receive loop error for router {router_id[:16]}...: {e}")
        
        finally:
            # Handle disconnection
            if router_id in self.connections:
                await self._handle_router_failure(router_id)
    
    async def _handle_deliver(
        self,
        data: Dict[str, Any],
        conn: RouterConnection,
    ) -> None:
        """Handle an incoming message delivery."""
        message_id = data.get("message_id")
        payload = data.get("payload")
        
        if not payload:
            logger.warning(f"Received delivery without payload: {message_id}")
            return
        
        conn.messages_received += 1
        self._stats["messages_received"] += 1
        
        # Decrypt and deliver to callback
        if self.on_message:
            try:
                # Extract sender public key from payload
                sender_public_hex = payload.get("sender_public")
                if not sender_public_hex:
                    logger.warning("Received message without sender public key")
                    return
                
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
                sender_public = Ed25519PublicKey.from_public_bytes(
                    bytes.fromhex(sender_public_hex)
                )
                
                # Decrypt
                plaintext = decrypt_message(
                    payload,
                    self.encryption_private_key,
                    sender_public,
                )
                
                # Deliver to callback
                await self.on_message(sender_public_hex, plaintext)
                
            except Exception as e:
                logger.warning(f"Failed to decrypt message {message_id}: {e}")
    
    async def _handle_pong(
        self,
        data: Dict[str, Any],
        conn: RouterConnection,
    ) -> None:
        """Handle pong response to our ping."""
        sent_at = data.get("sent_at")
        if sent_at:
            conn.ping_latency_ms = (time.time() - sent_at) * 1000
    
    async def _handle_ack(
        self,
        data: Dict[str, Any],
        conn: RouterConnection,
    ) -> None:
        """Handle acknowledgment for a sent message."""
        message_id = data.get("message_id")
        success = data.get("success", True)
        
        conn.ack_pending = max(0, conn.ack_pending - 1)
        
        if success:
            conn.ack_success += 1
        else:
            conn.ack_failure += 1
            logger.debug(f"Message {message_id} delivery failed")
    
    # -------------------------------------------------------------------------
    # ROUTER SELECTION
    # -------------------------------------------------------------------------
    
    def _select_router(self) -> Optional[RouterInfo]:
        """
        Select the best router based on health metrics.
        
        Uses weighted random selection based on:
        - ACK success rate
        - Current load
        - Ping latency
        
        Returns:
            Selected RouterInfo or None if no routers available
        """
        if not self.connections:
            return None
        
        # Filter to healthy connections
        candidates = [
            conn for conn in self.connections.values()
            if not conn.websocket.closed
        ]
        
        if not candidates:
            return None
        
        # Calculate weights based on health score
        weights = [max(0.01, conn.health_score) for conn in candidates]
        
        # Weighted random selection
        selected = random.choices(candidates, weights=weights, k=1)[0]
        return selected.router
    
    # -------------------------------------------------------------------------
    # BACKGROUND TASKS
    # -------------------------------------------------------------------------
    
    async def _keepalive_loop(self) -> None:
        """Send periodic pings to detect connection failures."""
        while self._running:
            try:
                await asyncio.sleep(self.keepalive_interval)
                if not self._running:
                    break
                
                for router_id, conn in list(self.connections.items()):
                    if conn.websocket.closed:
                        await self._handle_router_failure(router_id)
                        continue
                    
                    try:
                        sent_at = time.time()
                        await asyncio.wait_for(
                            conn.websocket.send_json({
                                "type": "ping",
                                "sent_at": sent_at,
                            }),
                            timeout=self.ping_timeout,
                        )
                    except (asyncio.TimeoutError, Exception) as e:
                        logger.warning(
                            f"Ping failed for router {router_id[:16]}...: {e}"
                        )
                        await self._handle_router_failure(router_id)
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Keepalive loop error: {e}")
    
    async def _connection_maintenance(self) -> None:
        """Periodically check and maintain connections."""
        while self._running:
            try:
                await asyncio.sleep(self.maintenance_interval)
                if not self._running:
                    break
                
                # Remove stale connections
                now = time.time()
                for router_id, conn in list(self.connections.items()):
                    # Check for stale connection (no activity in 2x keepalive)
                    if now - conn.last_seen > self.keepalive_interval * 2:
                        logger.warning(
                            f"Stale connection to router {router_id[:16]}..."
                        )
                        await self._handle_router_failure(router_id)
                
                # Ensure we have enough connections
                if len(self.connections) < self.min_connections:
                    logger.info(
                        f"Connection count ({len(self.connections)}) below minimum "
                        f"({self.min_connections}), reconnecting..."
                    )
                    await self._ensure_connections()
                
                # Optionally add more connections if below target
                elif len(self.connections) < self.target_connections:
                    await self._ensure_connections()
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Maintenance loop error: {e}")
    
    async def _queue_processor(self) -> None:
        """Process queued messages when routers become available."""
        while self._running:
            try:
                await asyncio.sleep(1.0)  # Check every second
                if not self._running:
                    break
                
                if not self.message_queue:
                    continue
                
                if not self.connections:
                    continue
                
                # Process oldest messages first
                now = time.time()
                processed = []
                
                for i, msg in enumerate(self.message_queue):
                    # Check message age
                    if now - msg.queued_at > self.MAX_QUEUE_AGE:
                        processed.append(i)
                        self._stats["messages_dropped"] += 1
                        logger.debug(f"Dropped expired message {msg.message_id}")
                        continue
                    
                    # Try to send
                    router = self._select_router()
                    if not router:
                        break
                    
                    try:
                        await self._send_via_router(
                            router,
                            msg.message_id,
                            msg.recipient_id,
                            msg.recipient_public_key,
                            msg.content,
                        )
                        processed.append(i)
                        logger.debug(f"Sent queued message {msg.message_id}")
                    except Exception as e:
                        msg.retries += 1
                        if msg.retries >= msg.max_retries:
                            processed.append(i)
                            self._stats["messages_dropped"] += 1
                            logger.warning(
                                f"Dropped message {msg.message_id} after "
                                f"{msg.retries} retries: {e}"
                            )
                
                # Remove processed messages (in reverse order to maintain indices)
                for i in reversed(processed):
                    self.message_queue.pop(i)
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Queue processor error: {e}")
    
    async def _handle_router_failure(self, router_id: str) -> None:
        """Handle a failed router connection."""
        conn = self.connections.pop(router_id, None)
        if not conn:
            return
        
        self._stats["failovers"] += 1
        logger.warning(f"Router {router_id[:16]}... disconnected")
        
        await self._close_connection(router_id, conn)
        
        # Schedule reconnection if below minimum
        if self._running and len(self.connections) < self.min_connections:
            await asyncio.sleep(self.reconnect_delay)
            if self._running:
                await self._ensure_connections()


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def create_node_client(
    private_key: Ed25519PrivateKey,
    encryption_private_key: X25519PrivateKey,
    discovery_client: Optional[DiscoveryClient] = None,
    **kwargs,
) -> NodeClient:
    """
    Create a node client with the given keys.
    
    Args:
        private_key: Ed25519 private key for signing
        encryption_private_key: X25519 private key for decryption
        discovery_client: Optional pre-configured discovery client
        **kwargs: Additional NodeClient parameters
        
    Returns:
        Configured NodeClient
    """
    # Derive node ID from public key
    node_id = private_key.public_key().public_bytes_raw().hex()
    
    client = NodeClient(
        node_id=node_id,
        private_key=private_key,
        encryption_private_key=encryption_private_key,
        **kwargs,
    )
    
    if discovery_client:
        client.discovery = discovery_client
    
    return client
