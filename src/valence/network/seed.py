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
import random
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import aiohttp
from aiohttp import web
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

if TYPE_CHECKING:
    from valence.network.seed import SeedNode

logger = logging.getLogger(__name__)


# =============================================================================
# HEALTH MONITORING
# =============================================================================


class HealthStatus(Enum):
    """Health status for monitored routers."""
    HEALTHY = "healthy"
    WARNING = "warning"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    REMOVED = "removed"


@dataclass
class HealthState:
    """Health state for a monitored router."""
    status: HealthStatus
    missed_heartbeats: int
    last_heartbeat: float
    last_probe: float
    probe_latency_ms: float
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize health state."""
        return {
            "status": self.status.value,
            "missed_heartbeats": self.missed_heartbeats,
            "last_heartbeat": self.last_heartbeat,
            "last_probe": self.last_probe,
            "probe_latency_ms": self.probe_latency_ms,
            "warnings": self.warnings.copy(),
        }


class HealthMonitor:
    """
    Monitors router health for seed node.
    
    Implements:
    - Heartbeat tracking with miss counting
    - Status state machine: HEALTHY → WARNING → DEGRADED → UNHEALTHY → REMOVED
    - Active probing of router subsets
    - Integration with discovery to filter unhealthy routers
    """
    
    def __init__(self, seed: "SeedNode"):
        self.seed = seed
        self.health_states: Dict[str, HealthState] = {}
        self.heartbeat_interval = 300  # 5 minutes
        self.probe_interval = 900  # 15 minutes
        self.check_interval = 60  # 1 minute
        self.probe_sample_size = 10
        self.high_latency_threshold_ms = 1000.0
        self._running = False
        self._tasks: List[asyncio.Task] = []
    
    async def start(self) -> None:
        """Start health monitoring loops."""
        if self._running:
            return
        
        self._running = True
        self._tasks = [
            asyncio.create_task(self._heartbeat_checker()),
            asyncio.create_task(self._active_prober()),
        ]
        logger.info("Health monitor started")
    
    async def stop(self) -> None:
        """Stop health monitoring loops."""
        self._running = False
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []
        logger.info("Health monitor stopped")
    
    async def _heartbeat_checker(self) -> None:
        """Check for missed heartbeats every minute."""
        while self._running:
            await asyncio.sleep(self.check_interval)
            
            now = time.time()
            removed_routers: List[str] = []
            
            for router_id, state in list(self.health_states.items()):
                time_since_heartbeat = now - state.last_heartbeat
                missed = int(time_since_heartbeat / self.heartbeat_interval)
                
                if missed != state.missed_heartbeats:
                    old_status = state.status
                    state.missed_heartbeats = missed
                    state.status = self._compute_status(missed)
                    
                    if state.status != old_status:
                        logger.info(
                            f"Router {router_id[:20]}... health: "
                            f"{old_status.value} → {state.status.value} "
                            f"(missed={missed})"
                        )
                    
                    if state.status == HealthStatus.REMOVED:
                        removed_routers.append(router_id)
            
            # Remove expired routers
            for router_id in removed_routers:
                self.seed.router_registry.pop(router_id, None)
                self.health_states.pop(router_id, None)
                logger.info(f"Removed router {router_id[:20]}... due to missed heartbeats")
    
    def _compute_status(self, missed: int) -> HealthStatus:
        """
        Compute health status from missed heartbeats.
        
        State machine:
        - 0 missed: HEALTHY
        - 1 missed (5 min): WARNING
        - 2 missed (10 min): DEGRADED
        - 3-5 missed (15-25 min): UNHEALTHY
        - 6+ missed (30+ min): REMOVED
        """
        if missed == 0:
            return HealthStatus.HEALTHY
        elif missed == 1:
            return HealthStatus.WARNING
        elif missed == 2:
            return HealthStatus.DEGRADED
        elif missed >= 6:
            return HealthStatus.REMOVED
        else:  # 3, 4, 5
            return HealthStatus.UNHEALTHY
    
    async def _active_prober(self) -> None:
        """Actively probe a subset of routers every probe_interval."""
        while self._running:
            await asyncio.sleep(self.probe_interval)
            
            # Probe subset of routers
            routers = list(self.seed.router_registry.values())
            if not routers:
                continue
            
            sample_size = min(self.probe_sample_size, len(routers))
            sample = random.sample(routers, sample_size)
            
            logger.debug(f"Probing {len(sample)} routers")
            
            for router in sample:
                await self._probe_router(router)
    
    async def _probe_router(self, router: "RouterRecord") -> None:
        """
        Probe router health endpoint.
        
        Records probe latency and warnings for high latency or failures.
        """
        if not router.endpoints:
            return
        
        endpoint = router.endpoints[0]
        
        try:
            # Parse endpoint
            if ":" in endpoint:
                host, port = endpoint.rsplit(":", 1)
            else:
                host = endpoint
                port = "8471"
            
            url = f"http://{host}:{port}/health"
            start = time.time()
            
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    latency_ms = (time.time() - start) * 1000
                    
                    if router.router_id in self.health_states:
                        state = self.health_states[router.router_id]
                        state.last_probe = time.time()
                        state.probe_latency_ms = latency_ms
                        
                        # Check for high latency
                        if latency_ms > self.high_latency_threshold_ms:
                            if "high_latency" not in state.warnings:
                                state.warnings.append("high_latency")
                                logger.debug(
                                    f"Router {router.router_id[:20]}... "
                                    f"high latency: {latency_ms:.1f}ms"
                                )
                        else:
                            # Remove high_latency warning if latency is now OK
                            if "high_latency" in state.warnings:
                                state.warnings.remove("high_latency")
                    
                    logger.debug(
                        f"Probe successful: {router.router_id[:20]}... "
                        f"latency={latency_ms:.1f}ms"
                    )
                    
        except asyncio.TimeoutError:
            if router.router_id in self.health_states:
                state = self.health_states[router.router_id]
                if "probe_timeout" not in state.warnings:
                    state.warnings.append("probe_timeout")
            logger.debug(f"Probe timeout: {router.router_id[:20]}...")
            
        except Exception as e:
            if router.router_id in self.health_states:
                state = self.health_states[router.router_id]
                if "probe_failed" not in state.warnings:
                    state.warnings.append("probe_failed")
            logger.debug(f"Probe failed: {router.router_id[:20]}... - {e}")
    
    def record_heartbeat(self, router_id: str, metrics: Optional[Dict[str, Any]] = None) -> HealthState:
        """
        Record a heartbeat from router.
        
        Creates health state if new, resets missed count and status to healthy.
        
        Args:
            router_id: The router's ID
            metrics: Optional metrics from heartbeat (unused, for future extension)
            
        Returns:
            The current HealthState for this router
        """
        now = time.time()
        
        if router_id not in self.health_states:
            self.health_states[router_id] = HealthState(
                status=HealthStatus.HEALTHY,
                missed_heartbeats=0,
                last_heartbeat=now,
                last_probe=0,
                probe_latency_ms=0,
                warnings=[],
            )
            logger.debug(f"New health state for router {router_id[:20]}...")
        else:
            state = self.health_states[router_id]
            old_status = state.status
            state.last_heartbeat = now
            state.missed_heartbeats = 0
            state.status = HealthStatus.HEALTHY
            # Clear transient warnings on heartbeat
            state.warnings = [w for w in state.warnings if w not in ["probe_timeout", "probe_failed"]]
            
            if old_status != HealthStatus.HEALTHY:
                logger.info(
                    f"Router {router_id[:20]}... recovered: "
                    f"{old_status.value} → healthy"
                )
        
        return self.health_states[router_id]
    
    def get_health_state(self, router_id: str) -> Optional[HealthState]:
        """Get health state for a router."""
        return self.health_states.get(router_id)
    
    def is_healthy_for_discovery(self, router_id: str) -> bool:
        """
        Check if router should be included in discovery results.
        
        Routers with HEALTHY or WARNING status are included.
        DEGRADED, UNHEALTHY, and REMOVED are excluded.
        """
        state = self.health_states.get(router_id)
        if state is None:
            # No health state = new router, assume healthy
            return True
        
        return state.status in (HealthStatus.HEALTHY, HealthStatus.WARNING)
    
    def get_stats(self) -> Dict[str, int]:
        """Get health monitoring statistics."""
        stats = {status.value: 0 for status in HealthStatus}
        for state in self.health_states.values():
            stats[state.status.value] += 1
        stats["total"] = len(self.health_states)
        return stats


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
    
    # Health monitoring
    _health_monitor: Optional[HealthMonitor] = field(default=None, repr=False)
    
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
    
    @property
    def health_monitor(self) -> HealthMonitor:
        """Get the health monitor, creating if needed."""
        if self._health_monitor is None:
            self._health_monitor = HealthMonitor(self)
        return self._health_monitor
    
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
        include_unhealthy: bool = False,
    ) -> List[RouterRecord]:
        """
        Select routers based on health, capacity, and preferences.
        
        Args:
            count: Number of routers to return
            preferences: Optional dict with region, features, etc.
            include_unhealthy: If True, skip health monitor filtering
            
        Returns:
            List of RouterRecord objects (up to count)
        """
        preferences = preferences or {}
        now = time.time()
        
        # Get healthy candidates (both legacy health check and health monitor)
        candidates = []
        for r in self.router_registry.values():
            # Legacy health check (based on uptime and staleness)
            if not self._is_healthy(r, now):
                continue
            
            # Health monitor check (based on heartbeat tracking)
            if not include_unhealthy and not self.health_monitor.is_healthy_for_discovery(r.router_id):
                continue
            
            candidates.append(r)
        
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
        
        # Record heartbeat with health monitor
        self.health_monitor.record_heartbeat(router_id, data)
        
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
        
        # Get health monitor stats
        health_stats = self.health_monitor.get_stats()
        
        return web.json_response({
            "seed_id": self.seed_id,
            "status": "running" if self._running else "stopped",
            "timestamp": now,
            "routers": {
                "total": len(self.router_registry),
                "healthy": healthy_count,
            },
            "health_monitor": health_stats,
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
        
        # Start health monitoring
        await self.health_monitor.start()
        
        self._running = True
        logger.info(
            f"Seed node {self.seed_id} listening on "
            f"{self.config.host}:{self.config.port}"
        )
    
    async def stop(self) -> None:
        """Stop the seed node server."""
        if not self._running:
            return
        
        # Stop health monitoring
        if self._health_monitor:
            await self._health_monitor.stop()
        
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
