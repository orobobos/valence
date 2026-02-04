"""
Valence Seed Node - The "phone book" for router discovery.

Seed nodes maintain a registry of active routers and help new nodes
bootstrap into the network. They implement:

1. Router registration: Routers announce themselves to seed nodes
2. Discovery: Nodes request router lists based on preferences
3. Health tracking: Monitor router availability via heartbeats
4. IP diversity: Ensure returned routers span different networks

Protocol:
- POST /discover - Get a list of routers matching preferences
- POST /register - Register a router with the seed node
- POST /heartbeat - Periodic health check from routers
- GET /status - Seed node status (public)

Security:
- Routers must sign registration with their Ed25519 key
- Proof-of-work required for anti-Sybil protection
- Heartbeats include router signature for verification
- No sensitive data stored - just public routing info
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import aiohttp
from aiohttp import web
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================


@dataclass
class SeedConfig:
    """Configuration for seed node."""
    
    host: str = "0.0.0.0"
    port: int = 8470
    
    # Router health thresholds
    min_uptime_pct: float = 90.0  # Minimum uptime to be considered healthy
    max_stale_seconds: float = 600.0  # Max time since last heartbeat
    
    # Selection weights
    weight_health: float = 0.4
    weight_capacity: float = 0.3
    weight_region: float = 0.2
    weight_random: float = 0.1
    
    # Seed node identity
    seed_id: Optional[str] = None
    
    # Known other seeds for redundancy
    known_seeds: List[str] = field(default_factory=list)
    
    # Proof-of-work difficulty (leading zero bits required)
    pow_difficulty_base: int = 16  # First router from IP
    pow_difficulty_second: int = 20  # Second router from same IP
    pow_difficulty_third_plus: int = 24  # Third+ router from same IP
    
    # Enable/disable signature and PoW verification
    verify_signatures: bool = True
    verify_pow: bool = True
    
    # Endpoint probing settings
    probe_endpoints: bool = True
    probe_timeout_seconds: float = 5.0
    
    def __post_init__(self):
        if self.seed_id is None:
            self.seed_id = f"seed-{secrets.token_hex(8)}"


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass
class RouterRecord:
    """Record of a registered router."""
    
    router_id: str  # Ed25519 public key (hex)
    endpoints: List[str]  # ["ip:port", ...]
    capacity: Dict[str, Any]  # {max_connections, current_load_pct, bandwidth_mbps}
    health: Dict[str, Any]  # {last_seen, uptime_pct, avg_latency_ms, status}
    regions: List[str]  # Geographic regions served
    features: List[str]  # Supported features/protocols
    registered_at: float  # Unix timestamp
    router_signature: str  # Signature of registration data
    proof_of_work: Optional[Dict[str, Any]] = None  # PoW proof
    source_ip: Optional[str] = None  # IP address that registered this router
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "router_id": self.router_id,
            "endpoints": self.endpoints,
            "capacity": self.capacity,
            "health": self.health,
            "regions": self.regions,
            "features": self.features,
            "registered_at": self.registered_at,
            "router_signature": self.router_signature,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RouterRecord":
        """Create from dictionary."""
        return cls(
            router_id=data["router_id"],
            endpoints=data.get("endpoints", []),
            capacity=data.get("capacity", {}),
            health=data.get("health", {}),
            regions=data.get("regions", []),
            features=data.get("features", []),
            registered_at=data.get("registered_at", time.time()),
            router_signature=data.get("router_signature", ""),
            proof_of_work=data.get("proof_of_work"),
            source_ip=data.get("source_ip"),
        )


# =============================================================================
# SEED NODE
# =============================================================================


@dataclass
class SeedNode:
    """
    Seed node for router discovery.
    
    Maintains a registry of routers and responds to discovery requests
    from nodes looking to connect to the network.
    """
    
    config: SeedConfig = field(default_factory=SeedConfig)
    router_registry: Dict[str, RouterRecord] = field(default_factory=dict)
    
    # Track routers per IP for PoW difficulty scaling
    _ip_router_count: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    
    # Runtime state
    _app: Optional[web.Application] = field(default=None, repr=False)
    _runner: Optional[web.AppRunner] = field(default=None, repr=False)
    _site: Optional[web.TCPSite] = field(default=None, repr=False)
    _running: bool = field(default=False, repr=False)
    
    @property
    def seed_id(self) -> str:
        """Get the seed node's ID."""
        return self.config.seed_id
    
    @property
    def known_seeds(self) -> List[str]:
        """Get list of known peer seeds."""
        return self.config.known_seeds
    
    # -------------------------------------------------------------------------
    # ROUTER SELECTION
    # -------------------------------------------------------------------------
    
    def _get_subnet(self, endpoint: str) -> Optional[str]:
        """Extract /16 subnet from an endpoint for diversity checking."""
        try:
            # Handle "ip:port" format
            host = endpoint.split(":")[0] if ":" in endpoint else endpoint
            
            # Skip non-IPv4 addresses
            parts = host.split(".")
            if len(parts) != 4:
                return None
            
            # Return /16 subnet (first two octets)
            return f"{parts[0]}.{parts[1]}"
        except Exception:
            return None
    
    def _is_healthy(self, router: RouterRecord, now: float) -> bool:
        """Check if a router is healthy based on uptime and freshness."""
        uptime = router.health.get("uptime_pct", 0)
        last_seen = router.health.get("last_seen", 0)
        
        if uptime < self.config.min_uptime_pct:
            return False
        
        if now - last_seen > self.config.max_stale_seconds:
            return False
        
        return True
    
    def _score_router(self, router: RouterRecord, preferences: Dict[str, Any]) -> float:
        """
        Score a router for selection.
        
        Higher score = better candidate.
        """
        score = 0.0
        
        # Health component (0-1, weighted)
        uptime = router.health.get("uptime_pct", 0) / 100.0
        score += uptime * self.config.weight_health
        
        # Capacity component (0-1, weighted) - prefer lower load
        load = router.capacity.get("current_load_pct", 100) / 100.0
        score += (1 - load) * self.config.weight_capacity
        
        # Region match bonus
        preferred_region = preferences.get("region")
        if preferred_region and preferred_region in router.regions:
            score += self.config.weight_region
        
        # Feature match bonus (partial)
        required_features = set(preferences.get("features", []))
        if required_features:
            router_features = set(router.features)
            match_ratio = len(required_features & router_features) / len(required_features)
            score += match_ratio * 0.1  # Small bonus for feature match
        
        # Deterministic random factor (based on router_id for consistency)
        random_component = (hash(router.router_id) % 100) / 100.0
        score += random_component * self.config.weight_random
        
        return score
    
    def select_routers(
        self,
        count: int,
        preferences: Optional[Dict[str, Any]] = None,
    ) -> List[RouterRecord]:
        """
        Select routers based on health, capacity, and preferences.
        
        Args:
            count: Number of routers to return
            preferences: Optional dict with region, features, etc.
            
        Returns:
            List of RouterRecord objects (up to count)
        """
        preferences = preferences or {}
        now = time.time()
        
        # Get healthy candidates
        candidates = [
            r for r in self.router_registry.values()
            if self._is_healthy(r, now)
        ]
        
        if not candidates:
            logger.warning("No healthy routers available")
            return []
        
        # Score and sort
        scored = [(self._score_router(r, preferences), r) for r in candidates]
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # Select with IP diversity
        selected: List[RouterRecord] = []
        seen_subnets: set[Optional[str]] = set()
        
        for _, router in scored:
            # Get subnet from first endpoint
            subnet = None
            if router.endpoints:
                subnet = self._get_subnet(router.endpoints[0])
            
            # Skip if we already have a router from this subnet
            # (None subnets are always allowed - could be IPv6 or hostname)
            if subnet is not None and subnet in seen_subnets:
                continue
            
            selected.append(router)
            if subnet is not None:
                seen_subnets.add(subnet)
            
            if len(selected) >= count:
                break
        
        logger.debug(
            f"Selected {len(selected)} routers from {len(candidates)} candidates "
            f"(registry has {len(self.router_registry)} total)"
        )
        
        return selected
    
    # -------------------------------------------------------------------------
    # VERIFICATION METHODS
    # -------------------------------------------------------------------------
    
    def _get_pow_difficulty(self, source_ip: str) -> int:
        """
        Get required PoW difficulty based on number of routers from this IP.
        
        Anti-Sybil measure: More routers from same IP = harder PoW.
        """
        count = self._ip_router_count.get(source_ip, 0)
        
        if count == 0:
            return self.config.pow_difficulty_base
        elif count == 1:
            return self.config.pow_difficulty_second
        else:
            return self.config.pow_difficulty_third_plus
    
    def _verify_signature(
        self,
        router_id: str,
        data: Dict[str, Any],
        signature: str,
    ) -> bool:
        """
        Verify Ed25519 signature of registration data.
        
        Args:
            router_id: Hex-encoded Ed25519 public key
            data: The registration data that was signed
            signature: Hex-encoded signature
            
        Returns:
            True if signature is valid, False otherwise
        """
        if not self.config.verify_signatures:
            return True
        
        try:
            # Parse public key from router_id (hex-encoded)
            public_key_bytes = bytes.fromhex(router_id)
            public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
            
            # Reconstruct the signed message (exclude signature from data)
            signed_data = {k: v for k, v in data.items() if k != "signature"}
            message = json.dumps(signed_data, sort_keys=True, separators=(',', ':')).encode()
            
            # Verify signature
            signature_bytes = bytes.fromhex(signature)
            public_key.verify(signature_bytes, message)
            
            return True
            
        except (ValueError, InvalidSignature) as e:
            logger.warning(f"Signature verification failed for {router_id[:20]}...: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error verifying signature: {e}")
            return False
    
    def _verify_pow(
        self,
        router_id: str,
        proof_of_work: Dict[str, Any],
        required_difficulty: int,
    ) -> bool:
        """
        Verify proof-of-work for anti-Sybil protection.
        
        PoW format:
        {
            "challenge": "<seed-provided or router-generated challenge>",
            "nonce": <integer nonce>,
            "difficulty": <difficulty level achieved>
        }
        
        Verification: sha256(challenge || nonce || router_id) must have
        `required_difficulty` leading zero bits.
        
        Args:
            router_id: The router's public key (hex)
            proof_of_work: The PoW proof dict
            required_difficulty: Number of leading zero bits required
            
        Returns:
            True if PoW is valid, False otherwise
        """
        if not self.config.verify_pow:
            return True
        
        if not proof_of_work:
            logger.warning(f"Missing proof_of_work for {router_id[:20]}...")
            return False
        
        try:
            challenge = proof_of_work.get("challenge", "")
            nonce = proof_of_work.get("nonce", 0)
            
            # Construct the hash input
            hash_input = f"{challenge}{nonce}{router_id}".encode()
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
            
            if leading_zeros >= required_difficulty:
                return True
            else:
                logger.warning(
                    f"PoW insufficient for {router_id[:20]}...: "
                    f"got {leading_zeros} bits, need {required_difficulty}"
                )
                return False
                
        except Exception as e:
            logger.error(f"PoW verification error: {e}")
            return False
    
    async def _probe_endpoint(self, endpoint: str) -> bool:
        """
        Probe router endpoint to verify reachability.
        
        Connects to the router's health endpoint to verify it's accessible.
        
        Args:
            endpoint: "host:port" string
            
        Returns:
            True if endpoint is reachable, False otherwise
        """
        if not self.config.probe_endpoints:
            return True
        
        try:
            # Parse endpoint
            if ":" in endpoint:
                host, port = endpoint.rsplit(":", 1)
                port = int(port)
            else:
                host = endpoint
                port = 8471  # Default router port
            
            # Try HTTP health check
            url = f"http://{host}:{port}/health"
            timeout = aiohttp.ClientTimeout(total=self.config.probe_timeout_seconds)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        logger.debug(f"Endpoint probe successful: {endpoint}")
                        return True
                    else:
                        logger.warning(
                            f"Endpoint probe failed for {endpoint}: "
                            f"status {response.status}"
                        )
                        return False
                        
        except asyncio.TimeoutError:
            logger.warning(f"Endpoint probe timeout for {endpoint}")
            return False
        except Exception as e:
            logger.warning(f"Endpoint probe failed for {endpoint}: {e}")
            return False
    
    def _determine_health_status(self, router: RouterRecord) -> str:
        """
        Determine router health status based on metrics.
        
        Returns: "healthy", "warning", or "degraded"
        """
        load_pct = router.capacity.get("current_load_pct", 0)
        uptime_pct = router.health.get("uptime_pct", 100)
        
        if load_pct > 90 or uptime_pct < 95:
            return "degraded"
        elif load_pct > 70 or uptime_pct < 99:
            return "warning"
        else:
            return "healthy"
    
    # -------------------------------------------------------------------------
    # HTTP HANDLERS
    # -------------------------------------------------------------------------
    
    async def handle_discover(self, request: web.Request) -> web.Response:
        """
        Handle discovery requests from nodes.
        
        POST /discover
        {
            "requested_count": 5,
            "preferences": {
                "region": "us-west",
                "features": ["ipv6", "quic"]
            }
        }
        
        Response:
        {
            "seed_id": "seed-abc123",
            "timestamp": 1706789012.345,
            "routers": [...],
            "other_seeds": ["https://seed2.valence.network"]
        }
        """
        try:
            data = await request.json()
        except Exception:
            data = {}
        
        requested_count = data.get("requested_count", 5)
        preferences = data.get("preferences", {})
        
        # Limit to reasonable range
        requested_count = max(1, min(requested_count, 20))
        
        routers = self.select_routers(requested_count, preferences)
        
        response = {
            "seed_id": self.seed_id,
            "timestamp": time.time(),
            "routers": [r.to_dict() for r in routers],
            "other_seeds": self.known_seeds,
        }
        
        logger.info(
            f"Discovery request: requested={requested_count}, "
            f"returned={len(routers)}, preferences={preferences}"
        )
        
        return web.json_response(response)
    
    async def handle_register(self, request: web.Request) -> web.Response:
        """
        Handle router registration with validation.
        
        POST /register
        {
            "router_id": "<hex-encoded Ed25519 public key>",
            "endpoints": ["192.168.1.100:8471"],
            "capacity": {"max_connections": 1000, "bandwidth_mbps": 100},
            "regions": ["us-west", "us-central"],
            "features": ["ipv6", "quic"],
            "proof_of_work": {"challenge": "...", "nonce": 12345, "difficulty": 16},
            "timestamp": 1706789012.345,
            "signature": "<hex-encoded Ed25519 signature>"
        }
        
        Registration flow:
        1. Validate required fields
        2. Verify Ed25519 signature
        3. Check proof-of-work (anti-Sybil)
        4. Probe endpoint reachability
        5. Register router
        """
        try:
            data = await request.json()
        except Exception as e:
            return web.json_response(
                {"status": "rejected", "reason": "invalid_json", "detail": str(e)},
                status=400
            )
        
        # Get source IP for PoW difficulty calculation
        source_ip = request.remote or "unknown"
        
        # Validate required fields
        router_id = data.get("router_id")
        if not router_id:
            return web.json_response(
                {"status": "rejected", "reason": "missing_router_id"},
                status=400
            )
        
        endpoints = data.get("endpoints", [])
        if not endpoints:
            return web.json_response(
                {"status": "rejected", "reason": "missing_endpoints"},
                status=400
            )
        
        signature = data.get("signature", "")
        proof_of_work = data.get("proof_of_work")
        
        # Check if updating existing router (skip some verifications for updates)
        is_update = router_id in self.router_registry
        
        # Verify Ed25519 signature
        if not self._verify_signature(router_id, data, signature):
            return web.json_response(
                {"status": "rejected", "reason": "invalid_signature"},
                status=400
            )
        
        # Check proof of work (only for new registrations)
        if not is_update:
            required_difficulty = self._get_pow_difficulty(source_ip)
            if not self._verify_pow(router_id, proof_of_work, required_difficulty):
                return web.json_response(
                    {
                        "status": "rejected",
                        "reason": "insufficient_pow",
                        "required_difficulty": required_difficulty,
                    },
                    status=400
                )
        
        # Probe endpoint reachability (only for new registrations or changed endpoints)
        if not is_update or endpoints != self.router_registry[router_id].endpoints:
            if not await self._probe_endpoint(endpoints[0]):
                return web.json_response(
                    {"status": "rejected", "reason": "unreachable"},
                    status=400
                )
        
        now = time.time()
        
        # Create or update record
        record = RouterRecord(
            router_id=router_id,
            endpoints=endpoints,
            capacity=data.get("capacity", {}),
            health={
                "last_seen": now,
                "uptime_pct": 100.0,  # Assume healthy on registration
                "avg_latency_ms": data.get("avg_latency_ms", 0),
                "status": "healthy",
            },
            regions=data.get("regions", []),
            features=data.get("features", []),
            registered_at=now if not is_update else self.router_registry[router_id].registered_at,
            router_signature=signature,
            proof_of_work=proof_of_work,
            source_ip=source_ip,
        )
        
        self.router_registry[router_id] = record
        
        # Track IP router count for new registrations
        if not is_update:
            self._ip_router_count[source_ip] += 1
        
        action = "updated" if is_update else "registered"
        logger.info(
            f"Router {action}: {router_id[:20]}... "
            f"endpoints={endpoints}, regions={record.regions}, source_ip={source_ip}"
        )
        
        return web.json_response({
            "status": "accepted",
            "action": action,
            "router_id": router_id,
            "seed_id": self.seed_id,
        })
    
    async def handle_heartbeat(self, request: web.Request) -> web.Response:
        """
        Handle router heartbeats.
        
        POST /heartbeat
        {
            "router_id": "<hex-encoded Ed25519 public key>",
            "current_connections": 350,
            "load_pct": 35.5,
            "messages_relayed": 12500,
            "uptime_pct": 99.8,
            "avg_latency_ms": 12.5,
            "timestamp": 1706789012.345,
            "signature": "<hex-encoded signature>"
        }
        
        Response includes health status: healthy/warning/degraded
        """
        try:
            data = await request.json()
        except Exception as e:
            return web.json_response(
                {"status": "error", "reason": "invalid_json", "detail": str(e)},
                status=400
            )
        
        router_id = data.get("router_id")
        if not router_id:
            return web.json_response(
                {"status": "error", "reason": "missing_router_id"},
                status=400
            )
        
        # Check if router is registered
        if router_id not in self.router_registry:
            return web.json_response(
                {"status": "error", "reason": "not_registered", "hint": "Call /register first"},
                status=404
            )
        
        # Verify signature if provided
        signature = data.get("signature", "")
        if signature and self.config.verify_signatures:
            if not self._verify_signature(router_id, data, signature):
                return web.json_response(
                    {"status": "error", "reason": "invalid_signature"},
                    status=400
                )
        
        # Update health and capacity
        record = self.router_registry[router_id]
        now = time.time()
        
        record.health["last_seen"] = now
        
        if "uptime_pct" in data:
            record.health["uptime_pct"] = float(data["uptime_pct"])
        if "avg_latency_ms" in data:
            record.health["avg_latency_ms"] = float(data["avg_latency_ms"])
        
        # Update capacity metrics
        if "load_pct" in data:
            record.capacity["current_load_pct"] = float(data["load_pct"])
        elif "current_load_pct" in data:
            record.capacity["current_load_pct"] = float(data["current_load_pct"])
            
        if "current_connections" in data:
            record.capacity["active_connections"] = int(data["current_connections"])
        elif "active_connections" in data:
            record.capacity["active_connections"] = int(data["active_connections"])
            
        if "messages_relayed" in data:
            record.capacity["messages_relayed"] = int(data["messages_relayed"])
        
        # Update endpoints if provided
        if "endpoints" in data:
            record.endpoints = data["endpoints"]
        
        # Determine health status
        health_status = self._determine_health_status(record)
        record.health["status"] = health_status
        
        logger.debug(
            f"Heartbeat from {router_id[:20]}...: "
            f"load={record.capacity.get('current_load_pct')}%, "
            f"connections={record.capacity.get('active_connections')}, "
            f"status={health_status}"
        )
        
        return web.json_response({
            "status": "ok",
            "health_status": health_status,
            "router_id": router_id,
            "seed_id": self.seed_id,
            "next_heartbeat_in": 300,  # 5 minutes
        })
    
    async def handle_status(self, request: web.Request) -> web.Response:
        """
        Handle status requests (public endpoint).
        
        GET /status
        """
        now = time.time()
        healthy_count = sum(
            1 for r in self.router_registry.values()
            if self._is_healthy(r, now)
        )
        
        return web.json_response({
            "seed_id": self.seed_id,
            "status": "running" if self._running else "stopped",
            "timestamp": now,
            "routers": {
                "total": len(self.router_registry),
                "healthy": healthy_count,
            },
            "known_seeds": len(self.known_seeds),
        })
    
    async def handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint for load balancers."""
        return web.json_response({"status": "ok"})
    
    # -------------------------------------------------------------------------
    # LIFECYCLE
    # -------------------------------------------------------------------------
    
    def _create_app(self) -> web.Application:
        """Create the aiohttp application."""
        app = web.Application()
        
        # Discovery endpoints
        app.router.add_post("/discover", self.handle_discover)
        app.router.add_post("/register", self.handle_register)
        app.router.add_post("/heartbeat", self.handle_heartbeat)
        
        # Status endpoints
        app.router.add_get("/status", self.handle_status)
        app.router.add_get("/health", self.handle_health)
        
        return app
    
    async def start(self) -> None:
        """Start the seed node server."""
        if self._running:
            logger.warning("Seed node already running")
            return
        
        self._app = self._create_app()
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        
        self._site = web.TCPSite(
            self._runner,
            self.config.host,
            self.config.port,
        )
        await self._site.start()
        
        self._running = True
        logger.info(
            f"Seed node {self.seed_id} listening on "
            f"{self.config.host}:{self.config.port}"
        )
    
    async def stop(self) -> None:
        """Stop the seed node server."""
        if not self._running:
            return
        
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()
        
        self._running = False
        self._app = None
        self._runner = None
        self._site = None
        
        logger.info(f"Seed node {self.seed_id} stopped")
    
    async def run_forever(self) -> None:
        """Start and run until interrupted."""
        await self.start()
        
        try:
            # Keep running until cancelled
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def create_seed_node(
    host: str = "0.0.0.0",
    port: int = 8470,
    known_seeds: Optional[List[str]] = None,
    **kwargs,
) -> SeedNode:
    """Create a seed node with the given configuration."""
    config = SeedConfig(
        host=host,
        port=port,
        known_seeds=known_seeds or [],
        **kwargs,
    )
    return SeedNode(config=config)


async def run_seed_node(
    host: str = "0.0.0.0",
    port: int = 8470,
    **kwargs,
) -> None:
    """Create and run a seed node (convenience function)."""
    node = create_seed_node(host=host, port=port, **kwargs)
    await node.run_forever()
