"""Tests for velocity anomaly detection (#352).

Tests cover:
1. VelocityConfig defaults and custom values
2. check_velocity allows within threshold
3. check_velocity blocks at threshold
4. Separate windows per action type
5. Separate windows per identity
6. Window expiry (old entries cleaned)
7. get_velocity_status reporting
8. clear_velocity_state
9. VelocityResult.to_dict
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from valence.core.velocity_monitor import (
    VelocityConfig,
    VelocityResult,
    check_velocity,
    clear_velocity_state,
    get_velocity_status,
)


@pytest.fixture(autouse=True)
def clean_state():
    """Clear velocity state before and after each test."""
    clear_velocity_state()
    yield
    clear_velocity_state()


class TestVelocityConfig:
    """Test configuration defaults."""

    def test_defaults(self):
        config = VelocityConfig()
        assert config.beliefs_per_hour == 100
        assert config.shares_per_hour == 50
        assert config.window_seconds == 3600

    def test_custom(self):
        config = VelocityConfig(beliefs_per_hour=10, shares_per_hour=5, window_seconds=60)
        assert config.beliefs_per_hour == 10


class TestCheckVelocity:
    """Test velocity checking logic."""

    def test_allows_first_action(self):
        result = check_velocity("did:test:1", "belief_create")
        assert result.allowed is True
        assert result.current_count == 1

    def test_allows_up_to_threshold(self):
        config = VelocityConfig(beliefs_per_hour=3)
        for _ in range(3):
            result = check_velocity("did:test:1", "belief_create", config)
        assert result.allowed is True
        assert result.current_count == 3

    def test_blocks_at_threshold(self):
        config = VelocityConfig(beliefs_per_hour=3)
        for _ in range(3):
            check_velocity("did:test:1", "belief_create", config)
        result = check_velocity("did:test:1", "belief_create", config)
        assert result.allowed is False
        assert result.current_count == 3
        assert "limit exceeded" in result.message.lower()

    def test_separate_windows_per_action(self):
        config = VelocityConfig(beliefs_per_hour=2, shares_per_hour=2)
        check_velocity("did:test:1", "belief_create", config)
        check_velocity("did:test:1", "belief_create", config)
        # belief_create is at limit, but belief_share should still be allowed
        result = check_velocity("did:test:1", "belief_share", config)
        assert result.allowed is True

    def test_separate_windows_per_identity(self):
        config = VelocityConfig(beliefs_per_hour=2)
        check_velocity("did:test:1", "belief_create", config)
        check_velocity("did:test:1", "belief_create", config)
        # did:test:1 is at limit, did:test:2 should be fine
        result = check_velocity("did:test:2", "belief_create", config)
        assert result.allowed is True

    def test_window_expiry(self):
        config = VelocityConfig(beliefs_per_hour=2, window_seconds=60)
        # Simulate old entries by patching time
        with patch("valence.core.velocity_monitor.time") as mock_time:
            mock_time.time.return_value = 1000.0
            check_velocity("did:test:1", "belief_create", config)
            check_velocity("did:test:1", "belief_create", config)

            # Move time forward past window
            mock_time.time.return_value = 1061.0
            result = check_velocity("did:test:1", "belief_create", config)
            assert result.allowed is True
            assert result.current_count == 1

    def test_uses_shares_threshold_for_shares(self):
        config = VelocityConfig(beliefs_per_hour=100, shares_per_hour=1)
        check_velocity("did:test:1", "belief_share", config)
        result = check_velocity("did:test:1", "belief_share", config)
        assert result.allowed is False


class TestGetVelocityStatus:
    """Test velocity status reporting."""

    def test_empty_status(self):
        status = get_velocity_status("did:test:1")
        assert status["identity_id"] == "did:test:1"
        assert status["actions"]["belief_create"]["current"] == 0
        assert status["actions"]["belief_share"]["current"] == 0

    def test_status_after_actions(self):
        config = VelocityConfig(beliefs_per_hour=10)
        check_velocity("did:test:1", "belief_create", config)
        check_velocity("did:test:1", "belief_create", config)
        status = get_velocity_status("did:test:1", config)
        assert status["actions"]["belief_create"]["current"] == 2
        assert status["actions"]["belief_create"]["remaining"] == 8
        assert status["actions"]["belief_create"]["exceeded"] is False


class TestVelocityResult:
    """Test result serialization."""

    def test_to_dict(self):
        result = VelocityResult(
            allowed=False,
            identity_id="did:test:1",
            action="belief_create",
            current_count=100,
            threshold=100,
            message="Rate limit exceeded",
        )
        d = result.to_dict()
        assert d["allowed"] is False
        assert d["identity_id"] == "did:test:1"
        assert d["threshold"] == 100
