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
# SEED HEALTH TRACKING
# =============================================================================


@dataclass
class SeedHealth:
    """Tracks health metrics for a seed node."""
    
    url: str
    success_count: int = 0
    failure_count: int = 0
    last_success: float = 0
    last_failure: float = 0
    last_latency_ms: float = 0
    total_latency_ms: float = 0
    
    @property
    def total_requests(self) -> int:
        """Total number of requests made to this seed."""
        return self.success_count + self.failure_count
    
    @property
    def success_rate(self) -> float:
        """Success rate (0.0 to 1.0). Returns 1.0 if no requests yet."""
        if self.total_requests == 0:
            return 1.0
        return self.success_count / self.total_requests
    
    @property
    def avg_latency_ms(self) -> float:
        """Average latency in milliseconds. Returns 0 if no successful requests."""
        if self.success_count == 0:
            return 0
        return self.total_latency_ms / self.success_count
    
    def record_success(self, latency_ms: float) -> None:
        """Record a successful request."""
        self.success_count += 1
        self.last_success = time.time()
        self.last_latency_ms = latency_ms
        self.total_latency_ms += latency_ms
    
    def record_failure(self) -> None:
        """Record a failed request."""
        self.failure_count += 1
        self.last_failure = time.time()
    
    @property
    def health_score(self) -> float:
        """
        Calculate overall health score (0.0 to 1.0).
        
        Combines:
        - Success rate (60% weight)
        - Latency score (30% weight) - lower is better
        - Recency bonus (10% weight) - recent success is good
        """
        # Success rate component
        success_score = self.success_rate * 0.6
        
        # Latency component (lower is better, cap at 5000ms)
        if self.success_count > 0:
            latency_score = max(0, 1.0 - (self.avg_latency_ms / 5000)) * 0.3
        else:
            latency_score = 0.15  # Neutral if no data
        
        # Recency component - bonus for recent success
        if self.last_success > 0:
            age = time.time() - self.last_success
            # Full bonus if success within last hour, degrades over 24h
            recency_score = max(0, 1.0 - (age / 86400)) * 0.1
        else:
            recency_score = 0
        
        return success_score + latency_score + recency_score
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for persistence."""
        return {
            "url": self.url,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "last_success": self.last_success,
            "last_failure": self.last_failure,
            "last_latency_ms": self.last_latency_ms,
            "total_latency_ms": self.total_latency_ms,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SeedHealth":
        """Deserialize from dictionary."""
        return cls(
            url=data.get("url", ""),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
            last_success=data.get("last_success", 0),
            last_failure=data.get("last_failure", 0),
            last_latency_ms=data.get("last_latency_ms", 0),
            total_latency_ms=data.get("total_latency_ms", 0),
        )


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
    region: Optional[str] = None  # ISO 3166-1 alpha-2 country code (e.g., "US", "DE")
    coordinates: Optional[List[float]] = None  # [latitude, longitude]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "router_id": self.router_id,
            "endpoints": self.endpoints,
            "capacity": self.capacity,
            "health": self.health,
            "regions": self.regions,
            "features": self.features,
            "router_signature": self.router_signature,
        }
        if self.region:
            result["region"] = self.region
        if self.coordinates:
            result["coordinates"] = self.coordinates
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RouterInfo":
        """Create from dictionary."""
        coords = data.get("coordinates")
        if coords and isinstance(coords, (list, tuple)) and len(coords) == 2:
            coordinates = [float(coords[0]), float(coords[1])]
        else:
            coordinates = None
            
        return cls(
            router_id=data.get("router_id", ""),
            endpoints=data.get("endpoints", []),
            capacity=data.get("capacity", {}),
            health=data.get("health", {}),
            regions=data.get("regions", []),
            features=data.get("features", []),
            router_signature=data.get("router_signature", ""),
            region=data.get("region"),
            coordinates=coordinates,
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
    
    Features:
    - Multi-seed support with automatic fallback
    - Seed health tracking (success rate, latency)
    - Intelligent seed ordering based on health
    - Response caching with configurable TTL
    
    Example:
        client = DiscoveryClient()
        routers = await client.discover_routers(count=5)
        # Connect to routers[0].endpoints[0]
    
    With custom seeds:
        client = DiscoveryClient()
        client.add_seed("https://my-seed.example.com:8470")
        # Or via constructor
        client = create_discovery_client(seeds=["https://seed1.example.com:8470"])
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
    
    # Seed health tracking
    seed_health: Dict[str, SeedHealth] = field(default_factory=dict)
    
    # Last successful seed URL (preferred for next query)
    last_successful_seed: Optional[str] = None
    
    # Whether to order seeds by health score
    order_seeds_by_health: bool = True
    
    # Statistics
    _stats: Dict[str, int] = field(default_factory=lambda: {
        "queries": 0,
        "cache_hits": 0,
        "seed_failures": 0,
        "signature_failures": 0,
        "seed_successes": 0,
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
            preferences: Optional dict with selection preferences:
                - preferred_region: ISO 3166-1 alpha-2 country code (e.g., "US", "DE")
                  Seeds will prefer routers in same region > same continent > any
                - region: Legacy region preference (for backward compatibility)
                - features: List of required features (e.g., ["ipv6", "quic"])
            force_refresh: If True, bypass cache
            
        Returns:
            List of RouterInfo objects
            
        Raises:
            NoSeedsAvailableError: If no seeds could be reached
        
        Example:
            # Prefer routers in Germany, fall back to other European routers
            routers = await client.discover_routers(
                count=5,
                preferences={"preferred_region": "DE"}
            )
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
                    # Track last successful seed for future queries
                    self.last_successful_seed = seed_url
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
        
        Tracks seed health (success/failure, latency) for intelligent
        fallback ordering on future requests.
        
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
        health = self._get_seed_health(seed_url)
        start_time = time.time()
        
        try:
            timeout = aiohttp.ClientTimeout(total=self.request_timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    discover_url,
                    json=request_body,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status != 200:
                        health.record_failure()
                        raise DiscoveryError(
                            f"Seed returned HTTP {resp.status}: {await resp.text()}"
                        )
                    
                    data = await resp.json()
                    
        except aiohttp.ClientError as e:
            health.record_failure()
            raise DiscoveryError(f"Connection error: {e}") from e
        except asyncio.TimeoutError:
            health.record_failure()
            raise DiscoveryError("Request timeout")
        
        # Record success with latency
        latency_ms = (time.time() - start_time) * 1000
        health.record_success(latency_ms)
        self._stats["seed_successes"] += 1
        
        # Process routers (data is guaranteed to exist here - exceptions would have been raised above)
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
        
        Region scoring uses tiered matching:
        - Same region (country): full region bonus (0.2)
        - Same continent: partial region bonus (0.1)
        - Different continent: no bonus
        """
        score = 0.0
        
        # Health component (0-1)
        uptime = router.health.get("uptime_pct", 0) / 100.0
        score += uptime * 0.4
        
        # Capacity component (prefer lower load)
        load = router.capacity.get("current_load_pct", 100) / 100.0
        score += (1 - load) * 0.3
        
        # Region match bonus with tiered scoring
        preferred_region = preferences.get("preferred_region") or preferences.get("region")
        if preferred_region:
            region_score = self._compute_region_score(router.region, preferred_region)
            score += region_score * 0.2
            
            # Legacy: also check regions list for backward compatibility
            if region_score == 0 and preferred_region in router.regions:
                score += 0.05  # Smaller bonus for legacy match
        
        # Feature match bonus
        required_features = set(preferences.get("features", []))
        if required_features:
            router_features = set(router.features)
            match_ratio = len(required_features & router_features) / len(required_features)
            score += match_ratio * 0.1
        
        return score
    
    def _compute_region_score(
        self,
        router_region: Optional[str],
        preferred_region: Optional[str],
    ) -> float:
        """
        Compute region match score for router selection.
        
        Scoring tiers:
        - Same region (country): 1.0 (full match)
        - Same continent: 0.5 (partial match)
        - Different continent or unknown: 0.0 (no match)
        """
        if not preferred_region or not router_region:
            return 0.0
        
        # Normalize to uppercase
        router_region = router_region.upper()
        preferred_region = preferred_region.upper()
        
        # Same country = full match
        if router_region == preferred_region:
            return 1.0
        
        # Same continent = partial match
        router_continent = self._get_continent(router_region)
        preferred_continent = self._get_continent(preferred_region)
        
        if router_continent and preferred_continent and router_continent == preferred_continent:
            return 0.5
        
        return 0.0
    
    def _get_continent(self, country_code: Optional[str]) -> Optional[str]:
        """Get continent code from ISO 3166-1 alpha-2 country code."""
        if not country_code:
            return None
        
        # Simplified continent mapping for common countries
        # Full mapping is in seed.py; this covers the most common cases
        continent_map = {
            # North America
            "US": "NA", "CA": "NA", "MX": "NA",
            # South America
            "BR": "SA", "AR": "SA", "CL": "SA", "CO": "SA",
            # Europe
            "GB": "EU", "DE": "EU", "FR": "EU", "IT": "EU", "ES": "EU",
            "NL": "EU", "BE": "EU", "CH": "EU", "AT": "EU", "SE": "EU",
            "NO": "EU", "DK": "EU", "FI": "EU", "IE": "EU", "PL": "EU",
            "PT": "EU", "CZ": "EU", "RO": "EU", "UA": "EU", "RU": "EU",
            # Asia
            "CN": "AS", "JP": "AS", "KR": "AS", "IN": "AS", "ID": "AS",
            "TH": "AS", "VN": "AS", "MY": "AS", "SG": "AS", "PH": "AS",
            "TW": "AS", "HK": "AS", "IL": "AS", "AE": "AS", "SA": "AS",
            # Africa
            "ZA": "AF", "EG": "AF", "NG": "AF", "KE": "AF",
            # Oceania
            "AU": "OC", "NZ": "OC",
        }
        return continent_map.get(country_code.upper())
    
    def _get_seed_list(self) -> List[str]:
        """
        Get ordered list of seeds to try.
        
        Ordering priority:
        1. Last successful seed (if recent and healthy)
        2. Custom seeds ordered by health
        3. Default seeds ordered by health
        4. Discovered seeds ordered by health (if cache valid)
        
        When order_seeds_by_health is True, seeds within each category
        are sorted by their health score (success rate, latency).
        """
        seeds: List[str] = []
        seen: set[str] = set()
        
        # Helper to add seeds, optionally ordering by health
        def add_seeds(seed_list: List[str]) -> None:
            if self.order_seeds_by_health and len(seed_list) > 1:
                # Sort by health score (highest first)
                sorted_seeds = sorted(
                    seed_list,
                    key=lambda s: self._get_seed_health(s).health_score,
                    reverse=True,
                )
            else:
                sorted_seeds = seed_list
            
            for seed in sorted_seeds:
                if seed not in seen:
                    seeds.append(seed)
                    seen.add(seed)
        
        # Last successful seed first (if it's still healthy)
        if self.last_successful_seed:
            health = self._get_seed_health(self.last_successful_seed)
            # Only prefer if success rate > 50% and had success in last 24h
            if health.success_rate > 0.5 and (
                time.time() - health.last_success < 86400 if health.last_success > 0 else True
            ):
                seeds.append(self.last_successful_seed)
                seen.add(self.last_successful_seed)
        
        # Custom seeds (highest priority after last successful)
        add_seeds(self.custom_seeds)
        
        # Default seeds next
        add_seeds(self.default_seeds)
        
        # Discovered seeds last (if cache valid)
        if self._seed_cache_valid():
            add_seeds(self.seed_cache)
        
        return seeds
    
    def _get_seed_health(self, seed_url: str) -> SeedHealth:
        """
        Get or create health tracking for a seed.
        
        Args:
            seed_url: The seed URL
            
        Returns:
            SeedHealth object for the seed
        """
        seed_url = seed_url.rstrip("/")
        if seed_url not in self.seed_health:
            self.seed_health[seed_url] = SeedHealth(url=seed_url)
        return self.seed_health[seed_url]
    
    def get_seed_health_report(self) -> List[Dict[str, Any]]:
        """
        Get health report for all tracked seeds.
        
        Returns:
            List of seed health dictionaries, sorted by health score
        """
        seeds = self._get_seed_list()
        report = []
        
        for seed_url in seeds:
            health = self._get_seed_health(seed_url)
            report.append({
                "url": seed_url,
                "success_count": health.success_count,
                "failure_count": health.failure_count,
                "success_rate": round(health.success_rate, 3),
                "avg_latency_ms": round(health.avg_latency_ms, 1),
                "health_score": round(health.health_score, 3),
                "last_success": health.last_success,
                "last_failure": health.last_failure,
            })
        
        # Sort by health score
        report.sort(key=lambda x: x["health_score"], reverse=True)
        return report
    
    def reset_seed_health(self, seed_url: Optional[str] = None) -> None:
        """
        Reset seed health tracking.
        
        Args:
            seed_url: If provided, reset only this seed. Otherwise reset all.
        """
        if seed_url:
            seed_url = seed_url.rstrip("/")
            if seed_url in self.seed_health:
                self.seed_health[seed_url] = SeedHealth(url=seed_url)
        else:
            self.seed_health.clear()
            self.last_successful_seed = None


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
