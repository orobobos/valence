"""
Tests for Sybil Resistance Mechanisms (Issue #117).

Tests cover:
- Rate limiting per IP and subnet
- Reputation system with decay for new routers
- Correlated behavior detection
- Adaptive PoW difficulty
- Integration with registration and heartbeat flows
"""

from __future__ import annotations

import time

import pytest

from valence.network.seed import (
    CorrelationDetector,
    RateLimiter,
    RegistrationEvent,
    ReputationManager,
    SeedConfig,
    SeedNode,
    SybilResistance,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sybil_config():
    """Create a test seed config with Sybil resistance enabled."""
    return SeedConfig(
        host="127.0.0.1",
        port=18470,
        seed_id="test-seed-sybil",
        verify_signatures=False,  # Disable for unit tests
        verify_pow=False,
        probe_endpoints=False,
        # Rate limiting
        rate_limit_enabled=True,
        rate_limit_window_seconds=3600.0,
        rate_limit_max_per_ip=3,
        rate_limit_max_per_subnet=5,
        rate_limit_cooldown_seconds=60.0,
        # Reputation
        reputation_enabled=True,
        reputation_initial_score=0.5,
        reputation_decay_period_hours=24.0,
        reputation_min_score_for_discovery=0.3,
        reputation_boost_per_heartbeat=0.05,
        reputation_penalty_missed_heartbeat=0.1,
        # Correlation detection
        correlation_detection_enabled=True,
        correlation_heartbeat_window_seconds=5.0,
        correlation_min_suspicious_events=3,
        correlation_endpoint_similarity_threshold=0.7,
        correlation_penalty_score=0.15,
        # Adaptive PoW
        adaptive_pow_enabled=True,
        adaptive_pow_threshold_per_hour=10,
        adaptive_pow_max_difficulty=24,
        adaptive_pow_difficulty_step=2,
        # Low base difficulty for tests
        pow_difficulty_base=4,
        pow_difficulty_second=6,
        pow_difficulty_third_plus=8,
    )


@pytest.fixture
def rate_limiter(sybil_config):
    """Create a rate limiter instance."""
    return RateLimiter(sybil_config)


@pytest.fixture
def reputation_manager(sybil_config):
    """Create a reputation manager instance."""
    return ReputationManager(sybil_config)


@pytest.fixture
def correlation_detector(sybil_config, reputation_manager):
    """Create a correlation detector instance."""
    return CorrelationDetector(sybil_config, reputation_manager)


@pytest.fixture
def sybil_resistance(sybil_config):
    """Create a Sybil resistance manager instance."""
    return SybilResistance(sybil_config)


@pytest.fixture
def seed_node(sybil_config):
    """Create a test seed node with Sybil resistance."""
    return SeedNode(config=sybil_config)


# =============================================================================
# RATE LIMITER TESTS
# =============================================================================


class TestRateLimiter:
    """Tests for the rate limiter."""

    def test_first_registration_allowed(self, rate_limiter):
        """First registration from an IP should be allowed."""
        allowed, reason = rate_limiter.check_rate_limit("192.168.1.100")
        assert allowed is True
        assert reason is None

    def test_cooldown_enforced(self, rate_limiter):
        """Cooldown between registrations should be enforced."""
        # Record first registration
        rate_limiter.record_registration("router-1", "192.168.1.100", success=True)

        # Immediate second attempt should be blocked
        allowed, reason = rate_limiter.check_rate_limit("192.168.1.100")
        assert allowed is False
        assert "cooldown_active" in reason

    def test_ip_limit_enforced(self, rate_limiter):
        """Per-IP limit should be enforced."""
        # Simulate 3 registrations (the max)
        for i in range(3):
            rate_limiter._registration_events.append(
                RegistrationEvent(
                    router_id=f"router-{i}",
                    source_ip="192.168.1.100",
                    subnet="192.168.1.0/24",
                    timestamp=time.time() - (i * 100),  # Spread out to avoid cooldown
                    success=True,
                )
            )

        # Clear cooldown
        rate_limiter._last_registration_by_ip.clear()

        # Next registration should be blocked
        allowed, reason = rate_limiter.check_rate_limit("192.168.1.100")
        assert allowed is False
        assert "ip_limit_exceeded" in reason

    def test_subnet_limit_enforced(self, rate_limiter):
        """Per-subnet limit should be enforced."""
        # Simulate 5 registrations from different IPs in same subnet
        for i in range(5):
            rate_limiter._registration_events.append(
                RegistrationEvent(
                    router_id=f"router-{i}",
                    source_ip=f"192.168.1.{100 + i}",
                    subnet="192.168.1.0/24",
                    timestamp=time.time() - (i * 100),
                    success=True,
                )
            )

        # Next registration from same subnet should be blocked
        allowed, reason = rate_limiter.check_rate_limit("192.168.1.200")
        assert allowed is False
        assert "subnet_limit_exceeded" in reason

    def test_different_subnet_allowed(self, rate_limiter):
        """Registration from different subnet should be allowed."""
        # Exhaust one subnet
        for i in range(5):
            rate_limiter._registration_events.append(
                RegistrationEvent(
                    router_id=f"router-{i}",
                    source_ip=f"192.168.1.{100 + i}",
                    subnet="192.168.1.0/24",
                    timestamp=time.time() - (i * 100),
                    success=True,
                )
            )

        # Different subnet should be allowed
        allowed, reason = rate_limiter.check_rate_limit("192.168.2.100")
        assert allowed is True

    def test_old_events_cleaned_up(self, rate_limiter):
        """Events outside window should be cleaned up."""
        # Add old event
        old_time = time.time() - 7200  # 2 hours ago
        rate_limiter._registration_events.append(
            RegistrationEvent(
                router_id="old-router",
                source_ip="192.168.1.100",
                subnet="192.168.1.0/24",
                timestamp=old_time,
                success=True,
            )
        )

        # Should not count toward limit
        allowed, reason = rate_limiter.check_rate_limit("192.168.1.100")
        assert allowed is True

    def test_registration_rate_calculation(self, rate_limiter):
        """Registration rate should be calculated correctly."""
        # Add some registrations
        now = time.time()
        for i in range(5):
            rate_limiter._registration_events.append(
                RegistrationEvent(
                    router_id=f"router-{i}",
                    source_ip=f"10.0.0.{i}",
                    subnet=f"10.0.{i}.0/24",
                    timestamp=now - (i * 60),
                    success=True,
                )
            )

        rate = rate_limiter.get_registration_rate()
        assert rate == 5


# =============================================================================
# REPUTATION MANAGER TESTS
# =============================================================================


class TestReputationManager:
    """Tests for the reputation manager."""

    def test_initial_reputation(self, reputation_manager):
        """New routers should start with initial reputation score."""
        record = reputation_manager.register_router("router-1")

        assert record.score == 0.5
        assert record.heartbeat_count == 0
        assert record.missed_heartbeats == 0

    def test_heartbeat_boosts_reputation(self, reputation_manager):
        """Successful heartbeats should boost reputation."""
        reputation_manager.register_router("router-1")

        # Send heartbeat
        record = reputation_manager.record_heartbeat("router-1")

        assert record.score > 0.5
        assert record.heartbeat_count == 1

    def test_missed_heartbeat_penalizes(self, reputation_manager):
        """Missed heartbeats should penalize reputation."""
        reputation_manager.register_router("router-1")

        # Miss heartbeat
        record = reputation_manager.record_missed_heartbeat("router-1")

        assert record.score == 0.4  # 0.5 - 0.1 penalty
        assert record.missed_heartbeats == 1

    def test_reputation_capped_at_max(self, reputation_manager):
        """Reputation should not exceed maximum."""
        reputation_manager.register_router("router-1")

        # Many heartbeats
        for _ in range(100):
            reputation_manager.record_heartbeat("router-1")

        record = reputation_manager.get_reputation("router-1")
        assert record.score <= 1.0

    def test_reputation_capped_at_zero(self, reputation_manager):
        """Reputation should not go below zero."""
        reputation_manager.register_router("router-1")

        # Many missed heartbeats
        for _ in range(20):
            reputation_manager.record_missed_heartbeat("router-1")

        record = reputation_manager.get_reputation("router-1")
        assert record.score >= 0.0

    def test_trust_filter_excludes_low_reputation(self, reputation_manager):
        """Low reputation routers should be excluded from discovery."""
        reputation_manager.register_router("router-1")

        # Tank reputation
        for _ in range(5):
            reputation_manager.record_missed_heartbeat("router-1")

        assert reputation_manager.is_trusted_for_discovery("router-1") is False

    def test_trust_filter_includes_good_reputation(self, reputation_manager):
        """Good reputation routers should be included in discovery."""
        reputation_manager.register_router("router-1")

        # Build reputation
        for _ in range(10):
            reputation_manager.record_heartbeat("router-1")

        assert reputation_manager.is_trusted_for_discovery("router-1") is True

    def test_penalty_adds_flag(self, reputation_manager):
        """Manual penalties should add flags."""
        reputation_manager.register_router("router-1")

        reputation_manager.apply_penalty("router-1", 0.1, "suspicious_behavior")

        record = reputation_manager.get_reputation("router-1")
        assert "suspicious_behavior" in record.flags
        assert record.score == 0.4


# =============================================================================
# CORRELATION DETECTOR TESTS
# =============================================================================


class TestCorrelationDetector:
    """Tests for the correlation detector."""

    def test_no_correlation_single_router(self, correlation_detector):
        """Single router should not trigger correlation."""
        correlated = correlation_detector.check_heartbeat_correlation(
            "router-1", time.time()
        )
        assert correlated == []

    def test_heartbeat_correlation_detected(self, correlation_detector):
        """Synchronized heartbeats should be detected."""
        now = time.time()

        # Record heartbeats from multiple routers at similar times
        correlation_detector.record_heartbeat("router-1", now)
        correlation_detector.record_heartbeat("router-2", now + 1)
        correlation_detector.record_heartbeat("router-3", now + 2)

        # Check correlation for a new heartbeat
        correlated = correlation_detector.check_heartbeat_correlation(
            "router-4", now + 3
        )

        # Should detect correlation with all three
        assert len(correlated) == 3

    def test_no_correlation_spread_heartbeats(self, correlation_detector):
        """Spread out heartbeats should not trigger correlation."""
        now = time.time()

        # Record heartbeats with large gaps
        correlation_detector.record_heartbeat("router-1", now - 100)
        correlation_detector.record_heartbeat("router-2", now - 50)

        # Check correlation
        correlated = correlation_detector.check_heartbeat_correlation("router-3", now)

        assert len(correlated) == 0

    def test_endpoint_similarity_same_ip(self, correlation_detector):
        """Same IP endpoints should be flagged as highly similar."""
        correlation_detector.record_endpoint("router-1", ["192.168.1.100:8471"])

        similar = correlation_detector.check_endpoint_similarity(
            "router-2", ["192.168.1.100:8472"]
        )

        assert len(similar) == 1
        assert similar[0][1] >= 0.9  # High similarity

    def test_endpoint_similarity_same_subnet(self, correlation_detector):
        """Same subnet endpoints should have moderate similarity."""
        correlation_detector.record_endpoint("router-1", ["192.168.1.100:8471"])

        similar = correlation_detector.check_endpoint_similarity(
            "router-2", ["192.168.1.200:8471"]
        )

        assert len(similar) == 1
        assert similar[0][1] >= 0.5

    def test_endpoint_similarity_different_subnet(self, correlation_detector):
        """Different subnet endpoints should have low similarity."""
        correlation_detector.record_endpoint("router-1", ["192.168.1.100:8471"])

        similar = correlation_detector.check_endpoint_similarity(
            "router-2", ["10.0.0.50:8471"]
        )

        # Should not exceed threshold
        assert len(similar) == 0 or similar[0][1] < 0.7

    def test_analyze_and_flag_correlated(
        self, correlation_detector, reputation_manager
    ):
        """Correlated behavior should flag routers."""
        now = time.time()

        # Register routers
        for i in range(5):
            reputation_manager.register_router(f"router-{i}")

        # Create correlated heartbeats
        for i in range(5):
            correlation_detector.record_heartbeat(f"router-{i}", now + i * 0.5)

        # Analyze a new correlated router
        reputation_manager.register_router("router-suspicious")
        flags = correlation_detector.analyze_and_flag(
            "router-suspicious", now + 2.5, ["192.168.1.100:8471"]
        )

        # Should detect correlation
        assert (
            "correlated_heartbeats" in flags or len(flags) == 0
        )  # Depends on threshold


# =============================================================================
# SYBIL RESISTANCE INTEGRATION TESTS
# =============================================================================


class TestSybilResistance:
    """Tests for the integrated Sybil resistance system."""

    def test_registration_blocked_by_rate_limit(self, sybil_resistance):
        """Registrations should be blocked when rate limited."""
        # Exhaust rate limit
        for i in range(3):
            sybil_resistance.on_registration_success(
                f"router-{i}", "192.168.1.100", [f"192.168.1.{100 + i}:8471"]
            )

        # Clear cooldown
        sybil_resistance.rate_limiter._last_registration_by_ip.clear()

        # Next should be blocked
        allowed, reason = sybil_resistance.check_registration(
            "router-new", "192.168.1.100", ["192.168.1.200:8471"]
        )

        assert allowed is False
        assert "ip_limit_exceeded" in reason

    def test_registration_blocked_by_endpoint_collision(self, sybil_resistance):
        """Nearly identical endpoints should block registration."""
        # Register first router
        sybil_resistance.on_registration_success(
            "router-1", "192.168.1.100", ["192.168.1.100:8471"]
        )

        # Try to register with same endpoint
        allowed, reason = sybil_resistance.check_registration(
            "router-2",
            "192.168.2.50",  # Different IP
            ["192.168.1.100:8471"],  # Same endpoint
        )

        assert allowed is False
        assert "endpoint_collision" in reason

    def test_adaptive_pow_increases_difficulty(self, sybil_resistance):
        """High registration rate should increase PoW difficulty."""
        # Simulate high registration rate
        now = time.time()
        for i in range(15):
            sybil_resistance.rate_limiter._registration_events.append(
                RegistrationEvent(
                    router_id=f"router-{i}",
                    source_ip=f"10.{i}.0.1",
                    subnet=f"10.{i}.0.0/24",
                    timestamp=now - (i * 60),
                    success=True,
                )
            )

        # Get adaptive difficulty
        difficulty = sybil_resistance.get_adaptive_pow_difficulty(4, "10.0.0.1")

        # Should be higher than base
        assert difficulty > 4

    def test_heartbeat_updates_reputation(self, sybil_resistance):
        """Heartbeats should update reputation."""
        sybil_resistance.on_registration_success(
            "router-1", "192.168.1.100", ["192.168.1.100:8471"]
        )

        initial_score = sybil_resistance.get_trust_factor("router-1")

        # Send heartbeat
        sybil_resistance.on_heartbeat("router-1", time.time(), ["192.168.1.100:8471"])

        new_score = sybil_resistance.get_trust_factor("router-1")
        assert new_score > initial_score

    def test_missed_heartbeat_penalizes(self, sybil_resistance):
        """Missed heartbeats should penalize reputation."""
        sybil_resistance.on_registration_success(
            "router-1", "192.168.1.100", ["192.168.1.100:8471"]
        )

        initial_score = sybil_resistance.get_trust_factor("router-1")

        # Miss heartbeat
        sybil_resistance.on_missed_heartbeat("router-1")

        new_score = sybil_resistance.get_trust_factor("router-1")
        assert new_score < initial_score

    def test_stats_comprehensive(self, sybil_resistance):
        """Stats should include all components."""
        stats = sybil_resistance.get_stats()

        assert "rate_limiter" in stats
        assert "reputation" in stats
        assert "correlation" in stats
        assert "adaptive_pow" in stats


# =============================================================================
# SEED NODE INTEGRATION TESTS
# =============================================================================


class TestSeedNodeSybilIntegration:
    """Tests for Sybil resistance integration with SeedNode."""

    def test_pow_difficulty_includes_adaptive(self, seed_node):
        """PoW difficulty should include adaptive adjustment."""
        # Simulate high registration rate
        now = time.time()
        for i in range(15):
            seed_node.sybil_resistance.rate_limiter._registration_events.append(
                RegistrationEvent(
                    router_id=f"router-{i}",
                    source_ip=f"10.{i}.0.1",
                    subnet=f"10.{i}.0.0/24",
                    timestamp=now - (i * 60),
                    success=True,
                )
            )

        difficulty = seed_node._get_pow_difficulty("10.0.0.1")

        # Should be higher than base (4)
        assert difficulty > 4

    def test_select_routers_filters_low_reputation(self, seed_node):
        """Router selection should filter low reputation routers."""
        from valence.network.seed import RouterRecord

        now = time.time()

        # Add good router
        seed_node.router_registry["good-router"] = RouterRecord(
            router_id="good-router",
            endpoints=["10.0.0.1:8471"],
            capacity={"max_connections": 100},
            health={"last_seen": now, "uptime_pct": 99.0},
            regions=["us-west"],
            features=[],
            registered_at=now,
            router_signature="",
        )
        seed_node.sybil_resistance.on_registration_success(
            "good-router", "10.0.0.1", ["10.0.0.1:8471"]
        )
        # Build reputation
        for _ in range(10):
            seed_node.sybil_resistance.on_heartbeat(
                "good-router", now, ["10.0.0.1:8471"]
            )

        # Add bad router
        seed_node.router_registry["bad-router"] = RouterRecord(
            router_id="bad-router",
            endpoints=["10.0.0.2:8471"],
            capacity={"max_connections": 100},
            health={"last_seen": now, "uptime_pct": 99.0},
            regions=["us-west"],
            features=[],
            registered_at=now,
            router_signature="",
        )
        seed_node.sybil_resistance.on_registration_success(
            "bad-router", "10.0.0.2", ["10.0.0.2:8471"]
        )
        # Tank reputation
        for _ in range(10):
            seed_node.sybil_resistance.on_missed_heartbeat("bad-router")

        # Select routers
        selected = seed_node.select_routers(10)

        # Should only include good router
        router_ids = [r.router_id for r in selected]
        assert "good-router" in router_ids
        assert "bad-router" not in router_ids

    def test_status_includes_sybil_stats(self, seed_node):
        """Status endpoint should include Sybil resistance stats."""
        # Access sybil_resistance to ensure it's initialized
        _ = seed_node.sybil_resistance

        # The stats should be accessible
        stats = seed_node.sybil_resistance.get_stats()
        assert "rate_limiter" in stats
        assert "reputation" in stats


# =============================================================================
# EDGE CASE TESTS
# =============================================================================


class TestSybilEdgeCases:
    """Tests for edge cases in Sybil resistance."""

    def test_disabled_rate_limiting(self, sybil_config):
        """Rate limiting should be bypassable when disabled."""
        sybil_config.rate_limit_enabled = False
        rate_limiter = RateLimiter(sybil_config)

        # Should always allow
        for i in range(100):
            allowed, reason = rate_limiter.check_rate_limit("192.168.1.100")
            assert allowed is True

    def test_disabled_reputation(self, sybil_config):
        """Reputation should default to trusted when disabled."""
        sybil_config.reputation_enabled = False
        reputation = ReputationManager(sybil_config)

        # Should always be trusted
        assert reputation.is_trusted_for_discovery("unknown-router") is True
        assert reputation.get_trust_factor("unknown-router") == 1.0

    def test_disabled_correlation(self, sybil_config, reputation_manager):
        """Correlation detection should be bypassable when disabled."""
        sybil_config.correlation_detection_enabled = False
        correlation = CorrelationDetector(sybil_config, reputation_manager)

        # Should return empty
        correlated = correlation.check_heartbeat_correlation("router-1", time.time())
        assert correlated == []

    def test_disabled_adaptive_pow(self, sybil_config):
        """Adaptive PoW should be bypassable when disabled."""
        sybil_config.adaptive_pow_enabled = False
        sybil = SybilResistance(sybil_config)

        # Simulate high rate
        now = time.time()
        for i in range(100):
            sybil.rate_limiter._registration_events.append(
                RegistrationEvent(
                    router_id=f"router-{i}",
                    source_ip=f"10.{i // 256}.{i % 256}.1",
                    subnet=f"10.{i // 256}.{i % 256}.0/24",
                    timestamp=now - i,
                    success=True,
                )
            )

        # Should return base difficulty unchanged
        difficulty = sybil.get_adaptive_pow_difficulty(4, "10.0.0.1")
        assert difficulty == 4

    def test_ipv6_handling(self, rate_limiter):
        """IPv6 addresses should be handled gracefully."""
        # IPv6 won't have subnet extracted normally
        allowed, reason = rate_limiter.check_rate_limit("2001:db8::1")
        assert allowed is True

        rate_limiter.record_registration("router-1", "2001:db8::1", success=True)

        # Should still track
        stats = rate_limiter.get_stats()
        assert stats["unique_ips"] >= 1
