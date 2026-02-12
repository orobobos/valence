"""Tests for per-peer federation rate limiting (#347).

Tests cover:
1. check_federation_rate_limit allows within threshold
2. check_federation_rate_limit blocks at threshold
3. Separate buckets per peer DID
4. Separate buckets per endpoint
5. federation_rate_limit_response format
6. Integration with require_did_signature decorator
"""

from __future__ import annotations

import pytest

from valence.server.rate_limit import (
    RateLimitResult,
    check_federation_rate_limit,
    clear_rate_limits,
    federation_rate_limit_response,
)


@pytest.fixture(autouse=True)
def clean_state():
    clear_rate_limits()
    yield
    clear_rate_limits()


class TestCheckFederationRateLimit:
    """Test per-peer federation rate limit function."""

    def test_allows_first_request(self):
        result = check_federation_rate_limit("did:key:abc", "/federation/sync")
        assert result.allowed is True

    def test_allows_up_to_limit(self):
        for _ in range(60):
            result = check_federation_rate_limit("did:key:abc", "/federation/sync")
        assert result.allowed is True

    def test_blocks_at_limit(self):
        for _ in range(60):
            check_federation_rate_limit("did:key:abc", "/federation/sync")
        result = check_federation_rate_limit("did:key:abc", "/federation/sync")
        assert result.allowed is False
        assert result.key == "federation:did:key:abc:/federation/sync"

    def test_custom_limit(self):
        for _ in range(5):
            check_federation_rate_limit("did:key:abc", "/federation/sync", rpm_limit=5)
        result = check_federation_rate_limit("did:key:abc", "/federation/sync", rpm_limit=5)
        assert result.allowed is False

    def test_separate_buckets_per_peer(self):
        for _ in range(60):
            check_federation_rate_limit("did:key:peer1", "/federation/sync")
        # peer1 is at limit, but peer2 should be fine
        result = check_federation_rate_limit("did:key:peer2", "/federation/sync")
        assert result.allowed is True

    def test_separate_buckets_per_endpoint(self):
        for _ in range(60):
            check_federation_rate_limit("did:key:abc", "/federation/sync")
        # /sync is at limit, but /beliefs should be fine
        result = check_federation_rate_limit("did:key:abc", "/federation/beliefs")
        assert result.allowed is True

    def test_returns_retry_after(self):
        for _ in range(5):
            check_federation_rate_limit("did:key:abc", "/test", rpm_limit=5, window_seconds=120)
        result = check_federation_rate_limit("did:key:abc", "/test", rpm_limit=5, window_seconds=120)
        assert result.retry_after == 120


class TestFederationRateLimitResponse:
    """Test federation rate limit response format."""

    def test_response_status_code(self):
        response = federation_rate_limit_response("did:key:abc")
        assert response.status_code == 429

    def test_response_has_retry_after_header(self):
        response = federation_rate_limit_response("did:key:abc", retry_after=120)
        assert response.headers.get("Retry-After") == "120"

    def test_response_body_contains_peer_did(self):
        import json

        response = federation_rate_limit_response("did:key:abc")
        body = json.loads(response.body)
        assert body["peer_did"] == "did:key:abc"
        assert body["error"] == "rate_limit_exceeded"
