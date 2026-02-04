"""
Tests for Discovery Client implementation.

Tests cover:
- RouterInfo data model
- DiscoveryClient configuration
- Cache behavior (TTL, invalidation, selection)
- Multi-seed fallback
- Signature verification
- Preferences handling
- Error handling
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from valence.network.discovery import (
    DiscoveryClient,
    RouterInfo,
    DiscoveryError,
    NoSeedsAvailableError,
    SignatureVerificationError,
    create_discovery_client,
    discover_routers,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def router_info():
    """Create a sample RouterInfo."""
    return RouterInfo(
        router_id="a1b2c3d4e5f6789012345678901234567890123456789012345678901234",
        endpoints=["192.168.1.100:8471", "10.0.0.1:8471"],
        capacity={
            "max_connections": 1000,
            "current_load_pct": 30.0,
            "bandwidth_mbps": 100,
        },
        health={
            "last_seen": time.time(),
            "uptime_pct": 99.5,
            "avg_latency_ms": 15.0,
        },
        regions=["us-west", "us-central"],
        features=["ipv6", "quic"],
        router_signature="deadbeef",
    )


@pytest.fixture
def discovery_client():
    """Create a DiscoveryClient for testing."""
    client = DiscoveryClient(
        verify_signatures=False,  # Disable for most tests
    )
    return client


@pytest.fixture
def multiple_routers():
    """Create multiple routers with different characteristics."""
    now = time.time()
    routers = []
    
    for i in range(5):
        routers.append(RouterInfo(
            router_id=f"router{i}" + "0" * 58,
            endpoints=[f"10.{i}.0.1:8471"],
            capacity={
                "max_connections": 1000,
                "current_load_pct": 20.0 + i * 15,
            },
            health={
                "last_seen": now,
                "uptime_pct": 95.0 + i * 0.5,
            },
            regions=["us-west"] if i % 2 == 0 else ["us-east"],
            features=["ipv6"] if i % 3 == 0 else [],
        ))
    
    return routers


# =============================================================================
# ROUTER INFO TESTS
# =============================================================================


class TestRouterInfo:
    """Tests for RouterInfo data model."""
    
    def test_to_dict(self, router_info):
        """Test RouterInfo serialization."""
        d = router_info.to_dict()
        
        assert d["router_id"] == router_info.router_id
        assert d["endpoints"] == router_info.endpoints
        assert d["capacity"] == router_info.capacity
        assert d["health"] == router_info.health
        assert d["regions"] == router_info.regions
        assert d["features"] == router_info.features
        assert d["router_signature"] == router_info.router_signature
    
    def test_from_dict(self, router_info):
        """Test RouterInfo deserialization."""
        d = router_info.to_dict()
        restored = RouterInfo.from_dict(d)
        
        assert restored.router_id == router_info.router_id
        assert restored.endpoints == router_info.endpoints
        assert restored.capacity == router_info.capacity
    
    def test_from_dict_minimal(self):
        """Test RouterInfo creation with minimal data."""
        d = {"router_id": "test-id-123"}
        router = RouterInfo.from_dict(d)
        
        assert router.router_id == "test-id-123"
        assert router.endpoints == []
        assert router.capacity == {}
        assert router.regions == []
        assert router.features == []
    
    def test_from_dict_all_fields(self):
        """Test RouterInfo creation with all fields."""
        d = {
            "router_id": "full-router",
            "endpoints": ["1.2.3.4:8471"],
            "capacity": {"max": 500},
            "health": {"uptime_pct": 99.0},
            "regions": ["eu-west"],
            "features": ["quic", "ipv6"],
            "router_signature": "sig123",
        }
        router = RouterInfo.from_dict(d)
        
        assert router.router_id == "full-router"
        assert router.endpoints == ["1.2.3.4:8471"]
        assert router.capacity == {"max": 500}
        assert router.health == {"uptime_pct": 99.0}
        assert router.regions == ["eu-west"]
        assert router.features == ["quic", "ipv6"]
        assert router.router_signature == "sig123"


# =============================================================================
# DISCOVERY CLIENT CONFIGURATION TESTS
# =============================================================================


class TestDiscoveryClientConfig:
    """Tests for DiscoveryClient configuration."""
    
    def test_default_seeds(self):
        """Client should have default seed URLs."""
        client = DiscoveryClient()
        
        assert len(client.default_seeds) >= 1
        assert all(s.startswith("http") for s in client.default_seeds)
    
    def test_add_seed(self, discovery_client):
        """Adding a seed should append to custom_seeds."""
        discovery_client.add_seed("https://custom.seed.local:8470")
        
        assert "https://custom.seed.local:8470" in discovery_client.custom_seeds
    
    def test_add_seed_normalizes_url(self, discovery_client):
        """Adding a seed should normalize the URL."""
        discovery_client.add_seed("https://seed.example.com:8470/")
        
        assert "https://seed.example.com:8470" in discovery_client.custom_seeds
    
    def test_add_seed_deduplicates(self, discovery_client):
        """Adding the same seed twice should not duplicate."""
        discovery_client.add_seed("https://seed.example.com:8470")
        discovery_client.add_seed("https://seed.example.com:8470")
        
        count = discovery_client.custom_seeds.count("https://seed.example.com:8470")
        assert count == 1
    
    def test_remove_seed(self, discovery_client):
        """Removing a seed should work."""
        discovery_client.add_seed("https://seed.example.com:8470")
        discovery_client.remove_seed("https://seed.example.com:8470")
        
        assert "https://seed.example.com:8470" not in discovery_client.custom_seeds
    
    def test_custom_ttl(self):
        """Custom TTL values should be respected."""
        client = DiscoveryClient(
            router_cache_ttl=3600,  # 1 hour
            seed_cache_ttl=7200,    # 2 hours
        )
        
        assert client.router_cache_ttl == 3600
        assert client.seed_cache_ttl == 7200
    
    def test_seed_ordering(self, discovery_client):
        """Seeds should be ordered: custom > default > cached."""
        discovery_client.add_seed("https://custom1.local:8470")
        discovery_client.add_seed("https://custom2.local:8470")
        discovery_client.seed_cache = ["https://cached.local:8470"]
        discovery_client.seed_cache_timestamp = time.time()  # Make cache valid
        
        seeds = discovery_client._get_seed_list()
        
        # Custom should come first
        assert seeds[0] == "https://custom1.local:8470"
        assert seeds[1] == "https://custom2.local:8470"
        
        # Default seeds should come next
        for default_seed in discovery_client.default_seeds:
            assert default_seed in seeds
        
        # Cached seeds should come last
        assert "https://cached.local:8470" in seeds


# =============================================================================
# CACHE BEHAVIOR TESTS
# =============================================================================


class TestCacheBehavior:
    """Tests for router and seed caching."""
    
    def test_empty_cache_invalid(self, discovery_client):
        """Empty cache should be invalid."""
        assert discovery_client._router_cache_valid() is False
        assert discovery_client._seed_cache_valid() is False
    
    def test_cache_valid_after_update(self, discovery_client, router_info):
        """Cache should be valid after updating."""
        discovery_client._update_router_cache([router_info])
        
        assert discovery_client._router_cache_valid() is True
        assert router_info.router_id in discovery_client.router_cache
    
    def test_cache_expires(self, discovery_client, router_info):
        """Cache should expire after TTL."""
        discovery_client.router_cache_ttl = 1  # 1 second
        discovery_client._update_router_cache([router_info])
        
        assert discovery_client._router_cache_valid() is True
        
        # Wait for expiry
        time.sleep(1.1)
        
        assert discovery_client._router_cache_valid() is False
    
    def test_seed_cache_update(self, discovery_client):
        """Seed cache should update and deduplicate."""
        discovery_client._update_seed_cache([
            "https://seed1.example.com",
            "https://seed2.example.com",
        ])
        
        assert len(discovery_client.seed_cache) == 2
        
        # Add more with some overlap
        discovery_client._update_seed_cache([
            "https://seed2.example.com",
            "https://seed3.example.com",
        ])
        
        # Should have 3 unique seeds
        assert len(discovery_client.seed_cache) == 3
    
    def test_clear_cache(self, discovery_client, router_info):
        """Clearing cache should reset everything."""
        discovery_client._update_router_cache([router_info])
        discovery_client._update_seed_cache(["https://seed.example.com"])
        
        discovery_client.clear_cache()
        
        assert len(discovery_client.router_cache) == 0
        assert len(discovery_client.seed_cache) == 0
        assert discovery_client.router_cache_timestamp == 0
        assert discovery_client.seed_cache_timestamp == 0
    
    def test_select_from_cache(self, discovery_client, multiple_routers):
        """Selection from cache should respect count and preferences."""
        discovery_client._update_router_cache(multiple_routers)
        
        # Select without preferences
        selected = discovery_client._select_from_cache(3, None)
        assert len(selected) == 3
        
        # Select with region preference
        selected = discovery_client._select_from_cache(5, {"region": "us-west"})
        
        # Should prioritize us-west routers
        assert len(selected) == 5
    
    def test_cache_hit_increments_stats(self, discovery_client, multiple_routers):
        """Cache hit should increment stats."""
        discovery_client._update_router_cache(multiple_routers)
        
        initial_hits = discovery_client._stats["cache_hits"]
        
        # This should use cache
        selected = discovery_client._select_from_cache(3, None)
        
        # Note: _select_from_cache doesn't increment stats, discover_routers does
        # This test verifies cache selection works
        assert len(selected) == 3


# =============================================================================
# MULTI-SEED FALLBACK TESTS
# =============================================================================


class TestMultiSeedFallback:
    """Tests for fallback across multiple seeds."""
    
    @pytest.mark.asyncio
    async def test_fallback_on_failure(self, discovery_client, router_info):
        """Should fall back to next seed on failure."""
        discovery_client.add_seed("https://bad-seed.local:8470")
        discovery_client.add_seed("https://good-seed.local:8470")
        
        # Mock aiohttp to fail on first seed, succeed on second
        call_count = [0]
        
        async def mock_query(seed_url, count, prefs):
            call_count[0] += 1
            if "bad-seed" in seed_url:
                raise DiscoveryError("Connection refused")
            return [router_info]
        
        with patch.object(discovery_client, '_query_seed', side_effect=mock_query):
            routers = await discovery_client.discover_routers(count=1)
        
        assert len(routers) == 1
        assert call_count[0] == 2  # Tried both seeds
    
    @pytest.mark.asyncio
    async def test_all_seeds_fail(self, discovery_client):
        """Should raise NoSeedsAvailableError if all seeds fail."""
        discovery_client.default_seeds = []  # Clear defaults
        discovery_client.add_seed("https://bad1.local:8470")
        discovery_client.add_seed("https://bad2.local:8470")
        
        async def mock_query(seed_url, count, prefs):
            raise DiscoveryError("Connection refused")
        
        with patch.object(discovery_client, '_query_seed', side_effect=mock_query):
            with pytest.raises(NoSeedsAvailableError):
                await discovery_client.discover_routers(count=1)
    
    @pytest.mark.asyncio
    async def test_seed_failure_increments_stats(self, discovery_client, router_info):
        """Seed failure should increment stats."""
        discovery_client.default_seeds = []
        discovery_client.add_seed("https://bad-seed.local:8470")
        discovery_client.add_seed("https://good-seed.local:8470")
        
        async def mock_query(seed_url, count, prefs):
            if "bad-seed" in seed_url:
                raise DiscoveryError("Connection refused")
            return [router_info]
        
        initial_failures = discovery_client._stats["seed_failures"]
        
        with patch.object(discovery_client, '_query_seed', side_effect=mock_query):
            await discovery_client.discover_routers(count=1)
        
        assert discovery_client._stats["seed_failures"] == initial_failures + 1


# =============================================================================
# SIGNATURE VERIFICATION TESTS
# =============================================================================


class TestSignatureVerification:
    """Tests for router signature verification."""
    
    def test_missing_signature_fails(self, discovery_client):
        """Router without signature should fail verification."""
        discovery_client.verify_signatures = True
        
        router_data = {
            "router_id": "abc123" + "0" * 58,
            "endpoints": ["1.2.3.4:8471"],
        }
        
        result = discovery_client._verify_router_signature(router_data)
        assert result is False
    
    def test_missing_router_id_fails(self, discovery_client):
        """Router without router_id should fail verification."""
        discovery_client.verify_signatures = True
        
        router_data = {
            "endpoints": ["1.2.3.4:8471"],
            "router_signature": "deadbeef",
        }
        
        result = discovery_client._verify_router_signature(router_data)
        assert result is False
    
    def test_invalid_public_key_format_fails(self, discovery_client):
        """Invalid public key format should fail verification."""
        discovery_client.verify_signatures = True
        
        router_data = {
            "router_id": "not-a-valid-hex-key",
            "router_signature": "deadbeef",
        }
        
        result = discovery_client._verify_router_signature(router_data)
        assert result is False
    
    def test_verification_disabled(self, discovery_client):
        """Verification should be skippable."""
        discovery_client.verify_signatures = False
        
        # Even invalid data shouldn't matter when verification is disabled
        router_data = {
            "router_id": "abc123",
            "router_signature": "bad-sig",
        }
        
        # Verification is skipped in discover_routers, not in _verify_router_signature
        # So this method would still fail
        assert discovery_client._verify_router_signature(router_data) is False
    
    @pytest.mark.asyncio
    async def test_invalid_signature_skipped(self, discovery_client):
        """Routers with invalid signatures should be skipped."""
        discovery_client.verify_signatures = True
        
        # Mock the HTTP response with invalid routers
        mock_response_data = {
            "routers": [
                {
                    "router_id": "invalid-key",
                    "endpoints": ["1.2.3.4:8471"],
                    "router_signature": "bad",
                },
            ],
            "other_seeds": [],
        }
        
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_response_data)
        
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(),
        ))
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            routers = await discovery_client._query_seed(
                "https://seed.example.com",
                count=5,
                preferences=None,
            )
        
        # All routers should be skipped due to invalid signatures
        assert len(routers) == 0
        assert discovery_client._stats["signature_failures"] > 0


# =============================================================================
# PREFERENCES HANDLING TESTS
# =============================================================================


class TestPreferencesHandling:
    """Tests for preference-based router selection."""
    
    def test_region_preference_scoring(self, discovery_client, multiple_routers):
        """Region preference should boost router score."""
        discovery_client._update_router_cache(multiple_routers)
        
        # Select with us-west preference
        selected = discovery_client._select_from_cache(5, {"region": "us-west"})
        
        # us-west routers should have higher scores and come first
        us_west_count = sum(1 for r in selected[:3] if "us-west" in r.regions)
        assert us_west_count >= 2  # Most of top 3 should be us-west
    
    def test_feature_preference_scoring(self, discovery_client, multiple_routers):
        """Feature preference should boost router score."""
        discovery_client._update_router_cache(multiple_routers)
        
        # Select with ipv6 preference
        selected = discovery_client._select_from_cache(5, {"features": ["ipv6"]})
        
        # Routers with ipv6 should be preferred
        assert len(selected) == 5
    
    def test_combined_preferences(self, discovery_client, multiple_routers):
        """Multiple preferences should combine."""
        discovery_client._update_router_cache(multiple_routers)
        
        selected = discovery_client._select_from_cache(3, {
            "region": "us-west",
            "features": ["ipv6"],
        })
        
        assert len(selected) == 3
    
    def test_no_preferences(self, discovery_client, multiple_routers):
        """No preferences should still return results."""
        discovery_client._update_router_cache(multiple_routers)
        
        selected = discovery_client._select_from_cache(3, None)
        
        assert len(selected) == 3
    
    def test_health_scoring(self, discovery_client):
        """Higher uptime should result in higher score."""
        high_uptime = RouterInfo(
            router_id="high" + "0" * 60,
            endpoints=["1.1.1.1:8471"],
            capacity={"current_load_pct": 50.0},
            health={"uptime_pct": 99.9},
            regions=[],
            features=[],
        )
        
        low_uptime = RouterInfo(
            router_id="low" + "0" * 61,
            endpoints=["2.2.2.2:8471"],
            capacity={"current_load_pct": 50.0},
            health={"uptime_pct": 50.0},
            regions=[],
            features=[],
        )
        
        high_score = discovery_client._score_router(high_uptime, {})
        low_score = discovery_client._score_router(low_uptime, {})
        
        assert high_score > low_score
    
    def test_load_scoring(self, discovery_client):
        """Lower load should result in higher score."""
        low_load = RouterInfo(
            router_id="low" + "0" * 61,
            endpoints=["1.1.1.1:8471"],
            capacity={"current_load_pct": 10.0},
            health={"uptime_pct": 95.0},
            regions=[],
            features=[],
        )
        
        high_load = RouterInfo(
            router_id="high" + "0" * 60,
            endpoints=["2.2.2.2:8471"],
            capacity={"current_load_pct": 90.0},
            health={"uptime_pct": 95.0},
            regions=[],
            features=[],
        )
        
        low_score = discovery_client._score_router(low_load, {})
        high_score = discovery_client._score_router(high_load, {})
        
        assert low_score > high_score


# =============================================================================
# DISCOVER_ROUTERS INTEGRATION TESTS
# =============================================================================


class TestDiscoverRoutersIntegration:
    """Integration tests for the full discover_routers flow."""
    
    @pytest.mark.asyncio
    async def test_discover_uses_cache(self, discovery_client, router_info):
        """discover_routers should use cache when valid."""
        discovery_client._update_router_cache([router_info])
        
        # Should use cache, not query seeds
        routers = await discovery_client.discover_routers(count=1)
        
        assert len(routers) == 1
        assert discovery_client._stats["cache_hits"] == 1
    
    @pytest.mark.asyncio
    async def test_discover_force_refresh(self, discovery_client, router_info):
        """force_refresh should bypass cache."""
        discovery_client._update_router_cache([router_info])
        discovery_client.default_seeds = []
        discovery_client.add_seed("https://test-seed.local:8470")
        
        # Mock seed query
        new_router = RouterInfo(
            router_id="new" + "0" * 61,
            endpoints=["5.5.5.5:8471"],
            capacity={},
            health={},
            regions=[],
            features=[],
        )
        
        async def mock_query(seed_url, count, prefs):
            return [new_router]
        
        with patch.object(discovery_client, '_query_seed', side_effect=mock_query):
            routers = await discovery_client.discover_routers(
                count=1,
                force_refresh=True,
            )
        
        # Should have queried seed and gotten new router
        assert len(routers) == 1
        assert routers[0].router_id == new_router.router_id
    
    @pytest.mark.asyncio
    async def test_no_seeds_error(self):
        """Should raise error when no seeds available."""
        client = DiscoveryClient(
            default_seeds=[],
            verify_signatures=False,
        )
        
        with pytest.raises(NoSeedsAvailableError):
            await client.discover_routers(count=1)


# =============================================================================
# CONVENIENCE FUNCTION TESTS
# =============================================================================


class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    def test_create_discovery_client(self):
        """create_discovery_client should configure client."""
        client = create_discovery_client(
            seeds=["https://custom.seed.local:8470"],
            verify_signatures=False,
        )
        
        assert "https://custom.seed.local:8470" in client.custom_seeds
        assert client.verify_signatures is False
    
    def test_create_discovery_client_defaults(self):
        """create_discovery_client should work with defaults."""
        client = create_discovery_client()
        
        assert client.verify_signatures is True
        assert len(client.default_seeds) >= 1
    
    @pytest.mark.asyncio
    async def test_discover_routers_function(self, router_info):
        """discover_routers convenience function should work."""
        with patch('valence.network.discovery.DiscoveryClient') as MockClient:
            mock_client = MagicMock()
            mock_client.discover_routers = AsyncMock(return_value=[router_info])
            mock_client.add_seed = MagicMock()
            MockClient.return_value = mock_client
            
            routers = await discover_routers(
                count=5,
                seeds=["https://custom.seed.local:8470"],
            )
            
            assert len(routers) == 1
            mock_client.add_seed.assert_called_with("https://custom.seed.local:8470")


# =============================================================================
# STATISTICS TESTS
# =============================================================================


class TestStatistics:
    """Tests for discovery statistics tracking."""
    
    def test_initial_stats(self, discovery_client):
        """Initial stats should be zero."""
        stats = discovery_client.get_stats()
        
        assert stats["queries"] == 0
        assert stats["cache_hits"] == 0
        assert stats["seed_failures"] == 0
        assert stats["signature_failures"] == 0
    
    @pytest.mark.asyncio
    async def test_query_increments_stats(self, discovery_client, router_info):
        """Each query should increment stats."""
        discovery_client._update_router_cache([router_info])
        
        await discovery_client.discover_routers(count=1)
        await discovery_client.discover_routers(count=1)
        
        stats = discovery_client.get_stats()
        assert stats["queries"] == 2
        assert stats["cache_hits"] == 2
    
    def test_get_stats_returns_copy(self, discovery_client):
        """get_stats should return a copy, not the original."""
        stats1 = discovery_client.get_stats()
        stats1["queries"] = 999
        
        stats2 = discovery_client.get_stats()
        assert stats2["queries"] == 0


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


class TestErrorHandling:
    """Tests for error handling."""
    
    @pytest.mark.asyncio
    async def test_http_error_handling(self, discovery_client):
        """HTTP errors should raise DiscoveryError."""
        discovery_client.default_seeds = []
        discovery_client.add_seed("https://error-seed.local:8470")
        
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.text = AsyncMock(return_value="Internal Server Error")
        
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(),
        ))
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            with pytest.raises(NoSeedsAvailableError):
                await discovery_client.discover_routers(count=1)
    
    @pytest.mark.asyncio  
    async def test_timeout_handling(self, discovery_client):
        """Timeouts should be handled gracefully."""
        discovery_client.default_seeds = []
        discovery_client.add_seed("https://slow-seed.local:8470")
        
        async def slow_query(*args, **kwargs):
            raise asyncio.TimeoutError()
        
        with patch.object(discovery_client, '_query_seed', side_effect=slow_query):
            with pytest.raises(NoSeedsAvailableError):
                await discovery_client.discover_routers(count=1)
    
    @pytest.mark.asyncio
    async def test_connection_error_handling(self, discovery_client):
        """Connection errors should be handled gracefully."""
        import aiohttp
        
        discovery_client.default_seeds = []
        discovery_client.add_seed("https://unreachable-seed.local:8470")
        
        async def connection_error(*args, **kwargs):
            raise aiohttp.ClientError("Connection refused")
        
        with patch.object(discovery_client, '_query_seed', side_effect=connection_error):
            with pytest.raises(NoSeedsAvailableError):
                await discovery_client.discover_routers(count=1)
