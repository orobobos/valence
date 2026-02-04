"""
Valence Discovery Client - Bootstrap router discovery for user nodes.

User nodes need to find routers to connect to the network. This module
provides the client side of the discovery protocol:

1. Query seed nodes for available routers
2. Verify router signatures (Ed25519)
3. Cache results to reduce seed load
4. Fall back across multiple seeds for resilience

Protocol:
- POST /discover to seed node
- Receive signed router list
- Verify signatures before using
- Cache with TTL

Security:
- All router entries are signed with Ed25519
- Client verifies signatures before trusting router info
- Multiple seeds for resilience against single point of failure
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import aiohttp
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger(__name__)


# =============================================================================
# EXCEPTIONS
# =============================================================================


class DiscoveryError(Exception):
    """Base exception for discovery errors."""
    pass


class NoSeedsAvailableError(DiscoveryError):
    """Raised when no seeds could be reached."""
    pass


class SignatureVerificationError(DiscoveryError):
    """Raised when router signature verification fails."""
    pass


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass
class RouterInfo:
    """Information about a discovered router."""
    
    router_id: str  # Ed25519 public key (hex)
    endpoints: List[str]  # ["ip:port", ...]
    capacity: Dict[str, Any]  # {max_connections, current_load_pct, bandwidth_mbps}
    health: Dict[str, Any]  # {last_seen, uptime_pct, avg_latency_ms}
    regions: List[str]  # Geographic regions served
    features: List[str]  # Supported features/protocols
    router_signature: str = ""  # Signature of registration data
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "router_id": self.router_id,
            "endpoints": self.endpoints,
            "capacity": self.capacity,
            "health": self.health,
            "regions": self.regions,
            "features": self.features,
            "router_signature": self.router_signature,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RouterInfo":
        """Create from dictionary."""
        return cls(
            router_id=data.get("router_id", ""),
            endpoints=data.get("endpoints", []),
            capacity=data.get("capacity", {}),
            health=data.get("health", {}),
            regions=data.get("regions", []),
            features=data.get("features", []),
            router_signature=data.get("router_signature", ""),
        )


# =============================================================================
# DISCOVERY CLIENT
# =============================================================================


@dataclass
class DiscoveryClient:
    """
    Client for discovering routers via seed nodes.
    
    User nodes use this to bootstrap their connection to the network.
    The client queries seed nodes for available routers, verifies their
    signatures, and caches results for efficiency.
    
    Example:
        client = DiscoveryClient()
        routers = await client.discover_routers(count=5)
        # Connect to routers[0].endpoints[0]
    """
    
    # Hardcoded bootstrap seeds (can be overridden)
    default_seeds: List[str] = field(default_factory=lambda: [
        "https://seed1.valence.network:8470",
        "https://seed2.valence.network:8470",
    ])
    
    # Custom seeds added by user/config
    custom_seeds: List[str] = field(default_factory=list)
    
    # Cache for discovered routers
    router_cache: Dict[str, RouterInfo] = field(default_factory=dict)
    
    # Cache for discovered seeds (from other_seeds responses)
    seed_cache: List[str] = field(default_factory=list)
    
    # Cache timestamps
    router_cache_timestamp: float = 0
    seed_cache_timestamp: float = 0
    
    # TTL settings (in seconds)
    router_cache_ttl: int = 6 * 3600   # 6 hours
    seed_cache_ttl: int = 24 * 3600    # 24 hours
    
    # Request timeout (seconds)
    request_timeout: float = 10.0
    
    # Whether to verify router signatures (disable for testing)
    verify_signatures: bool = True
    
    # Statistics
    _stats: Dict[str, int] = field(default_factory=lambda: {
        "queries": 0,
        "cache_hits": 0,
        "seed_failures": 0,
        "signature_failures": 0,
    })
    
    # -------------------------------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------------------------------
    
    async def discover_routers(
        self,
        count: int = 5,
        preferences: Optional[Dict[str, Any]] = None,
        force_refresh: bool = False,
    ) -> List[RouterInfo]:
        """
        Discover routers from seed nodes.
        
        Args:
            count: Number of routers to request
            preferences: Optional dict with region, features, etc.
            force_refresh: If True, bypass cache
            
        Returns:
            List of RouterInfo objects
            
        Raises:
            NoSeedsAvailableError: If no seeds could be reached
        """
        self._stats["queries"] += 1
        
        # Check cache first (unless force refresh)
        if not force_refresh and self._router_cache_valid():
            cached = self._select_from_cache(count, preferences)
            if cached:
                self._stats["cache_hits"] += 1
                logger.debug(f"Returning {len(cached)} routers from cache")
                return cached
        
        # Build ordered seed list: custom > default > discovered
        seeds = self._get_seed_list()
        
        if not seeds:
            raise NoSeedsAvailableError("No seeds configured or discovered")
        
        # Try each seed until one succeeds
        last_error: Optional[Exception] = None
        
        for seed_url in seeds:
            try:
                routers = await self._query_seed(seed_url, count, preferences)
                if routers:
                    self._update_router_cache(routers)
                    logger.info(
                        f"Discovered {len(routers)} routers from {seed_url}"
                    )
                    return routers
            except Exception as e:
                self._stats["seed_failures"] += 1
                last_error = e
                logger.warning(f"Seed {seed_url} failed: {e}")
                continue  # Try next seed
        
        # All seeds failed
        raise NoSeedsAvailableError(
            f"Could not reach any seed. Last error: {last_error}"
        )
    
    def add_seed(self, seed_url: str) -> None:
        """
        Add a custom seed URL.
        
        Args:
            seed_url: URL of the seed node (e.g., "https://seed.example.com:8470")
        """
        # Normalize URL
        seed_url = seed_url.rstrip("/")
        
        if seed_url not in self.custom_seeds:
            self.custom_seeds.append(seed_url)
            logger.debug(f"Added custom seed: {seed_url}")
    
    def remove_seed(self, seed_url: str) -> None:
        """Remove a custom seed URL."""
        seed_url = seed_url.rstrip("/")
        if seed_url in self.custom_seeds:
            self.custom_seeds.remove(seed_url)
    
    def clear_cache(self) -> None:
        """Clear all caches."""
        self.router_cache.clear()
        self.seed_cache.clear()
        self.router_cache_timestamp = 0
        self.seed_cache_timestamp = 0
        logger.debug("Cleared discovery caches")
    
    def get_stats(self) -> Dict[str, int]:
        """Get discovery statistics."""
        return dict(self._stats)
    
    def get_cached_routers(self) -> List[RouterInfo]:
        """Get all cached routers (for inspection)."""
        return list(self.router_cache.values())
    
    # -------------------------------------------------------------------------
    # SEED QUERYING
    # -------------------------------------------------------------------------
    
    async def _query_seed(
        self,
        seed_url: str,
        count: int,
        preferences: Optional[Dict[str, Any]],
    ) -> List[RouterInfo]:
        """
        Query a single seed node for routers.
        
        Args:
            seed_url: Base URL of the seed node
            count: Number of routers to request
            preferences: Optional preferences dict
            
        Returns:
            List of verified RouterInfo objects
            
        Raises:
            DiscoveryError: If query fails
        """
        request_body = {
            "protocol_version": "1.0",
            "requested_count": count,
            "preferences": preferences or {},
        }
        
        discover_url = f"{seed_url}/discover"
        
        try:
            timeout = aiohttp.ClientTimeout(total=self.request_timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    discover_url,
                    json=request_body,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status != 200:
                        raise DiscoveryError(
                            f"Seed returned HTTP {resp.status}: {await resp.text()}"
                        )
                    
                    data = await resp.json()
        except aiohttp.ClientError as e:
            raise DiscoveryError(f"Connection error: {e}") from e
        except asyncio.TimeoutError as e:
            raise DiscoveryError(f"Request timeout") from e
        
        # Process routers
        routers: List[RouterInfo] = []
        for router_data in data.get("routers", []):
            try:
                # Verify signature if enabled
                if self.verify_signatures:
                    if not self._verify_router_signature(router_data):
                        self._stats["signature_failures"] += 1
                        logger.warning(
                            f"Invalid signature for router {router_data.get('router_id', 'unknown')[:20]}..."
                        )
                        continue
                
                router = RouterInfo.from_dict(router_data)
                routers.append(router)
            except Exception as e:
                logger.warning(f"Failed to parse router: {e}")
                continue
        
        # Update seed cache from response
        other_seeds = data.get("other_seeds", [])
        if other_seeds:
            self._update_seed_cache(other_seeds)
        
        return routers
    
    # -------------------------------------------------------------------------
    # SIGNATURE VERIFICATION
    # -------------------------------------------------------------------------
    
    def _verify_router_signature(self, router_data: Dict[str, Any]) -> bool:
        """
        Verify a router's Ed25519 signature.
        
        The router signs its registration data with its private key.
        We verify using the router_id (which is the public key).
        
        Args:
            router_data: Router data dict including router_signature
            
        Returns:
            True if signature is valid, False otherwise
        """
        try:
            router_id = router_data.get("router_id", "")
            signature_hex = router_data.get("router_signature", "")
            
            if not router_id or not signature_hex:
                logger.debug("Missing router_id or signature")
                return False
            
            # Parse public key from router_id (hex-encoded Ed25519 public key)
            try:
                public_key_bytes = bytes.fromhex(router_id)
                public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
            except (ValueError, TypeError) as e:
                logger.debug(f"Invalid public key format: {e}")
                return False
            
            # Parse signature
            try:
                signature = bytes.fromhex(signature_hex)
            except (ValueError, TypeError) as e:
                logger.debug(f"Invalid signature format: {e}")
                return False
            
            # Build signed data (same as router builds it)
            # Sign the canonical JSON of router data (excluding signature)
            signed_data = {
                "router_id": router_data.get("router_id"),
                "endpoints": router_data.get("endpoints", []),
                "capacity": router_data.get("capacity", {}),
                "regions": router_data.get("regions", []),
                "features": router_data.get("features", []),
                "registered_at": router_data.get("registered_at"),
            }
            message = json.dumps(signed_data, sort_keys=True).encode()
            
            # Verify signature
            public_key.verify(signature, message)
            return True
            
        except InvalidSignature:
            logger.debug("Signature verification failed")
            return False
        except Exception as e:
            logger.debug(f"Signature verification error: {e}")
            return False
    
    # -------------------------------------------------------------------------
    # CACHING
    # -------------------------------------------------------------------------
    
    def _router_cache_valid(self) -> bool:
        """Check if router cache is still valid."""
        if not self.router_cache:
            return False
        
        age = time.time() - self.router_cache_timestamp
        return age < self.router_cache_ttl
    
    def _seed_cache_valid(self) -> bool:
        """Check if seed cache is still valid."""
        if not self.seed_cache:
            return False
        
        age = time.time() - self.seed_cache_timestamp
        return age < self.seed_cache_ttl
    
    def _update_router_cache(self, routers: List[RouterInfo]) -> None:
        """Update the router cache with new routers."""
        for router in routers:
            self.router_cache[router.router_id] = router
        self.router_cache_timestamp = time.time()
    
    def _update_seed_cache(self, seeds: List[str]) -> None:
        """Update the seed cache with newly discovered seeds."""
        # Merge with existing, deduplicate
        existing = set(self.seed_cache)
        for seed in seeds:
            seed = seed.rstrip("/")
            if seed not in existing:
                self.seed_cache.append(seed)
        self.seed_cache_timestamp = time.time()
    
    def _select_from_cache(
        self,
        count: int,
        preferences: Optional[Dict[str, Any]],
    ) -> List[RouterInfo]:
        """
        Select routers from cache based on preferences.
        
        Args:
            count: Number of routers to return
            preferences: Optional preferences dict
            
        Returns:
            List of RouterInfo objects
        """
        preferences = preferences or {}
        candidates = list(self.router_cache.values())
        
        if not candidates:
            return []
        
        # Score candidates based on preferences
        scored = [(self._score_router(r, preferences), r) for r in candidates]
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # Return top N
        return [r for _, r in scored[:count]]
    
    def _score_router(
        self,
        router: RouterInfo,
        preferences: Dict[str, Any],
    ) -> float:
        """
        Score a router based on health, capacity, and preferences.
        
        Higher score = better candidate.
        """
        score = 0.0
        
        # Health component (0-1)
        uptime = router.health.get("uptime_pct", 0) / 100.0
        score += uptime * 0.4
        
        # Capacity component (prefer lower load)
        load = router.capacity.get("current_load_pct", 100) / 100.0
        score += (1 - load) * 0.3
        
        # Region match bonus
        preferred_region = preferences.get("region")
        if preferred_region and preferred_region in router.regions:
            score += 0.2
        
        # Feature match bonus
        required_features = set(preferences.get("features", []))
        if required_features:
            router_features = set(router.features)
            match_ratio = len(required_features & router_features) / len(required_features)
            score += match_ratio * 0.1
        
        return score
    
    def _get_seed_list(self) -> List[str]:
        """Get ordered list of seeds to try."""
        seeds: List[str] = []
        seen: set[str] = set()
        
        # Custom seeds first (highest priority)
        for seed in self.custom_seeds:
            if seed not in seen:
                seeds.append(seed)
                seen.add(seed)
        
        # Default seeds next
        for seed in self.default_seeds:
            if seed not in seen:
                seeds.append(seed)
                seen.add(seed)
        
        # Discovered seeds last (if cache valid)
        if self._seed_cache_valid():
            for seed in self.seed_cache:
                if seed not in seen:
                    seeds.append(seed)
                    seen.add(seed)
        
        return seeds


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def create_discovery_client(
    seeds: Optional[List[str]] = None,
    verify_signatures: bool = True,
) -> DiscoveryClient:
    """
    Create a discovery client with optional custom seeds.
    
    Args:
        seeds: Optional list of seed URLs to use
        verify_signatures: Whether to verify router signatures
        
    Returns:
        Configured DiscoveryClient
    """
    client = DiscoveryClient(verify_signatures=verify_signatures)
    
    if seeds:
        for seed in seeds:
            client.add_seed(seed)
    
    return client


async def discover_routers(
    count: int = 5,
    seeds: Optional[List[str]] = None,
    preferences: Optional[Dict[str, Any]] = None,
) -> List[RouterInfo]:
    """
    Convenience function to discover routers.
    
    Creates a temporary client and performs discovery.
    
    Args:
        count: Number of routers to request
        seeds: Optional list of seed URLs
        preferences: Optional preferences dict
        
    Returns:
        List of RouterInfo objects
    """
    client = create_discovery_client(seeds=seeds)
    return await client.discover_routers(count=count, preferences=preferences)
