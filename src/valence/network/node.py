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
from .messages import AckMessage, DeliverPayload

logger = logging.getLogger(__name__)


# =============================================================================
# ACK TRACKING
# =============================================================================


@dataclass
class PendingAck:
    """Tracks a message awaiting acknowledgment."""
    
    message_id: str
    recipient_id: str
    content: bytes
    recipient_public_key: X25519PublicKey
    sent_at: float
    router_id: str
    timeout_ms: int = 30000  # 30 seconds default
    retries: int = 0
    max_retries: int = 2  # Retry once via same router, then via different router


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
    
    # ACK tracking
    pending_acks: Dict[str, PendingAck] = field(default_factory=dict)
    seen_messages: Set[str] = field(default_factory=set)  # For idempotent delivery
    
    # ACK configuration
    default_ack_timeout_ms: int = 30000  # 30 seconds
    max_seen_messages: int = 10000  # Limit seen message cache size
    
    # Callbacks for message handling
    on_message: Optional[Callable[[str, bytes], None]] = None
    on_ack_timeout: Optional[Callable[[str, str], None]] = None  # (message_id, recipient_id)
    
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
        "messages_deduplicated": 0,
        "connections_established": 0,
        "connections_failed": 0,
        "failovers": 0,
        "ack_successes": 0,
        "ack_failures": 0,
        "acks_sent": 0,
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
        require_ack: bool = True,
        ack_timeout_ms: Optional[int] = None,
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
            require_ack: Whether to require end-to-end acknowledgment
            ack_timeout_ms: ACK timeout in milliseconds (default: 30000)
            
        Returns:
            Message ID (UUID string)
            
        Raises:
            NoRoutersAvailableError: If no routers are connected and queue is full
        """
        message_id = str(uuid.uuid4())
        timeout_ms = ack_timeout_ms or self.default_ack_timeout_ms
        
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
            require_ack=require_ack,
        )
        
        # Track pending ACK if required
        if require_ack:
            self.pending_acks[message_id] = PendingAck(
                message_id=message_id,
                recipient_id=recipient_id,
                content=content,
                recipient_public_key=recipient_public_key,
                sent_at=time.time(),
                router_id=router.router_id,
                timeout_ms=timeout_ms,
            )
            asyncio.create_task(self._wait_for_ack(message_id))
        
        return message_id
    
    def get_stats(self) -> Dict[str, Any]:
        """Get node statistics."""
        return {
            **self._stats,
            "active_connections": len(self.connections),
            "queued_messages": len(self.message_queue),
            "connected_subnets": len(self._connected_subnets),
            "pending_acks": len(self.pending_acks),
            "seen_messages_cached": len(self.seen_messages),
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
        require_ack: bool = True,
    ) -> None:
        """Send an encrypted message via a specific router."""
        conn = self.connections.get(router.router_id)
        if not conn or conn.websocket.closed:
            raise ConnectionError(f"Not connected to router {router.router_id[:16]}...")
        
        # Encrypt for recipient - include message_id and require_ack in payload
        # The content should include ACK metadata for the recipient
        payload_with_ack = {
            "content": content.decode() if isinstance(content, bytes) else content,
            "message_id": message_id,
            "require_ack": require_ack,
            "sender_id": self.node_id,
        }
        encrypted = encrypt_message(
            __import__('json').dumps(payload_with_ack).encode(),
            recipient_public_key,
            self.private_key
        )
        
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
        relay_message_id = data.get("message_id")
        payload = data.get("payload")
        
        if not payload:
            logger.warning(f"Received delivery without payload: {relay_message_id}")
            return
        
        conn.messages_received += 1
        self._stats["messages_received"] += 1
        
        # Decrypt and deliver to callback
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
            
            # Parse the decrypted payload
            try:
                inner_payload = __import__('json').loads(plaintext.decode())
            except (ValueError, UnicodeDecodeError):
                # Fallback for non-JSON payloads (legacy)
                inner_payload = {"content": plaintext.decode()}
            
            # Extract message metadata
            inner_message_id = inner_payload.get("message_id")
            require_ack = inner_payload.get("require_ack", False)
            sender_id = inner_payload.get("sender_id", sender_public_hex)
            content = inner_payload.get("content", plaintext)
            
            # Check if this is an ACK message
            if isinstance(content, str):
                try:
                    content_data = __import__('json').loads(content)
                    if content_data.get("type") == "ack":
                        ack = AckMessage.from_dict(content_data)
                        await self._handle_e2e_ack(ack)
                        return
                except (ValueError, TypeError):
                    pass
            
            # Idempotent delivery - skip if we've already seen this message
            if inner_message_id and self._is_duplicate_message(inner_message_id):
                logger.debug(f"Duplicate message {inner_message_id}, skipping")
                self._stats["messages_deduplicated"] += 1
                # Still send ACK for duplicates (sender may not have received our first ACK)
                if require_ack:
                    # Get sender's encryption key from directory (simplified: use signing key)
                    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
                    # Note: In production, we'd look up the sender's X25519 key
                    # For now, we log a warning
                    logger.debug(f"Would send ACK for duplicate {inner_message_id}")
                return
            
            # Deliver to callback
            if self.on_message:
                if isinstance(content, str):
                    content_bytes = content.encode()
                else:
                    content_bytes = content if isinstance(content, bytes) else str(content).encode()
                await self.on_message(sender_id, content_bytes)
            
            # Send E2E ACK if requested
            if require_ack and inner_message_id:
                # Note: We need the sender's X25519 public key for encrypted ACK
                # For now, log that we would send an ACK
                # In production, this would look up the key from a directory
                self._stats["acks_sent"] = self._stats.get("acks_sent", 0) + 1
                logger.debug(f"ACK requested for {inner_message_id} from {sender_id[:16]}...")
            
        except Exception as e:
            logger.warning(f"Failed to process message {relay_message_id}: {e}")
    
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
    # E2E ACK HANDLING
    # -------------------------------------------------------------------------
    
    async def _wait_for_ack(self, message_id: str) -> None:
        """Wait for an E2E ACK with timeout, then retry if needed."""
        pending = self.pending_acks.get(message_id)
        if not pending:
            return
        
        await asyncio.sleep(pending.timeout_ms / 1000)
        
        # Check if ACK was received while we waited
        if message_id not in self.pending_acks:
            return  # ACK received, all good
        
        # Timeout - attempt retry
        pending = self.pending_acks.get(message_id)
        if not pending:
            return
        
        if pending.retries < 1:
            # First retry - try same router
            pending.retries += 1
            logger.debug(f"ACK timeout for {message_id}, retrying via same router")
            await self._retry_message(message_id)
        else:
            # Second timeout - try different router
            logger.debug(f"ACK timeout for {message_id}, trying different router")
            await self._retry_via_different_router(message_id)
    
    async def _retry_message(self, message_id: str) -> None:
        """Retry sending a message via the same router."""
        pending = self.pending_acks.get(message_id)
        if not pending:
            return
        
        conn = self.connections.get(pending.router_id)
        if not conn or conn.websocket.closed:
            # Router unavailable, try different one
            await self._retry_via_different_router(message_id)
            return
        
        try:
            await self._send_via_router(
                conn.router,
                message_id,
                pending.recipient_id,
                pending.recipient_public_key,
                pending.content,
                require_ack=True,
            )
            pending.sent_at = time.time()
            # Schedule another wait
            asyncio.create_task(self._wait_for_ack(message_id))
        except Exception as e:
            logger.warning(f"Retry failed for {message_id}: {e}")
            await self._retry_via_different_router(message_id)
    
    async def _retry_via_different_router(self, message_id: str) -> None:
        """Retry sending a message via a different router."""
        pending = self.pending_acks.get(message_id)
        if not pending:
            return
        
        # Find a different router
        original_router_id = pending.router_id
        new_router = None
        
        for router_id, conn in self.connections.items():
            if router_id != original_router_id and not conn.websocket.closed:
                new_router = conn.router
                break
        
        if not new_router:
            # No alternative router, mark as failed
            logger.warning(
                f"No alternative router for {message_id}, giving up"
            )
            self._handle_ack_failure(message_id, pending)
            return
        
        try:
            pending.retries += 1
            pending.router_id = new_router.router_id
            
            await self._send_via_router(
                new_router,
                message_id,
                pending.recipient_id,
                pending.recipient_public_key,
                pending.content,
                require_ack=True,
            )
            pending.sent_at = time.time()
            # Schedule another wait
            asyncio.create_task(self._wait_for_ack(message_id))
        except Exception as e:
            logger.warning(f"Retry via different router failed for {message_id}: {e}")
            self._handle_ack_failure(message_id, pending)
    
    def _handle_ack_failure(self, message_id: str, pending: PendingAck) -> None:
        """Handle final ACK failure after all retries exhausted."""
        self.pending_acks.pop(message_id, None)
        
        # Update router stats for the last router used
        router_conn = self.connections.get(pending.router_id)
        if router_conn:
            router_conn.ack_failure += 1
        
        self._stats["ack_failures"] = self._stats.get("ack_failures", 0) + 1
        
        # Notify callback if registered
        if self.on_ack_timeout:
            try:
                self.on_ack_timeout(message_id, pending.recipient_id)
            except Exception as e:
                logger.warning(f"on_ack_timeout callback error: {e}")
        
        logger.warning(
            f"Message {message_id} to {pending.recipient_id[:16]}... "
            f"failed after {pending.retries} retries"
        )
    
    async def _handle_e2e_ack(self, ack: AckMessage) -> None:
        """Handle an E2E acknowledgment from the recipient."""
        message_id = ack.original_message_id
        
        if message_id not in self.pending_acks:
            logger.debug(f"Received ACK for unknown message {message_id}")
            return
        
        pending = self.pending_acks.pop(message_id)
        
        # Verify signature (recipient signed the message_id)
        # For now, we trust the ACK came through encrypted channel
        # TODO: Verify signature if recipient's signing key is known
        
        # Update router stats
        router_conn = self.connections.get(pending.router_id)
        if router_conn:
            router_conn.ack_success += 1
        
        self._stats["ack_successes"] = self._stats.get("ack_successes", 0) + 1
        
        latency_ms = (ack.received_at - pending.sent_at) * 1000
        logger.debug(
            f"E2E ACK received for {message_id} from {ack.recipient_id[:16]}... "
            f"(latency: {latency_ms:.1f}ms)"
        )
    
    async def _send_ack_to_sender(
        self,
        message_id: str,
        sender_id: str,
        sender_public_key: X25519PublicKey,
        reply_router_id: Optional[str] = None,
    ) -> None:
        """Send an E2E ACK back to the message sender."""
        # Create ACK message
        ack = AckMessage(
            original_message_id=message_id,
            received_at=time.time(),
            recipient_id=self.node_id,
            signature=self._sign_ack(message_id),
        )
        
        # Select router - prefer the one that delivered the message
        router = None
        if reply_router_id and reply_router_id in self.connections:
            conn = self.connections[reply_router_id]
            if not conn.websocket.closed:
                router = conn.router
        
        if not router:
            router = self._select_router()
        
        if not router:
            logger.warning(f"No router available to send ACK for {message_id}")
            return
        
        # Send ACK as a message
        ack_content = __import__('json').dumps(ack.to_dict()).encode()
        await self._send_via_router(
            router,
            str(uuid.uuid4()),  # ACK has its own message_id
            sender_id,
            sender_public_key,
            ack_content,
            require_ack=False,  # ACKs don't require ACKs (no infinite loop)
        )
        
        logger.debug(f"Sent E2E ACK for {message_id} to {sender_id[:16]}...")
    
    def _sign_ack(self, message_id: str) -> str:
        """Sign a message_id to prove we received it."""
        signature = self.private_key.sign(message_id.encode())
        return signature.hex()
    
    def _is_duplicate_message(self, message_id: str) -> bool:
        """Check if we've already seen this message (idempotent delivery)."""
        if message_id in self.seen_messages:
            return True
        
        # Add to seen messages
        self.seen_messages.add(message_id)
        
        # Prune if too large (FIFO-ish, just clear half)
        if len(self.seen_messages) > self.max_seen_messages:
            # Convert to list, remove oldest half
            seen_list = list(self.seen_messages)
            self.seen_messages = set(seen_list[len(seen_list)//2:])
        
        return False
    
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
