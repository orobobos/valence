"""Rate limiting utilities for the Valence server.

Provides IP-based and client-based rate limiting for protecting endpoints
against brute-force and abuse attacks.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import JSONResponse

# Rate limiting state (in-memory, per-instance)
_rate_limits: dict[str, list[float]] = defaultdict(list)


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request, respecting X-Forwarded-For.

    Args:
        request: The incoming request

    Returns:
        Client IP address string
    """
    # Check X-Forwarded-For header (for reverse proxy setups)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take the first IP (original client)
        return forwarded.split(",")[0].strip()

    # Fall back to direct client IP
    if request.client:
        return request.client.host

    return "unknown"


def check_rate_limit(key: str, rpm_limit: int, window_seconds: int = 60) -> bool:
    """Check if a request is within rate limit.

    Args:
        key: Unique identifier for the rate limit bucket (e.g., IP, client_id)
        rpm_limit: Maximum requests allowed in the window
        window_seconds: Time window in seconds (default: 60)

    Returns:
        True if request is allowed, False if rate limited
    """
    now = time.time()
    window_start = now - window_seconds

    # Clean old entries
    _rate_limits[key] = [t for t in _rate_limits[key] if t > window_start]

    # Check limit
    if len(_rate_limits[key]) >= rpm_limit:
        return False

    # Record request
    _rate_limits[key].append(now)
    return True


def check_rate_limit_multi(keys: list[str], rpm_limit: int, window_seconds: int = 60) -> bool:
    """Check rate limit across multiple keys (all must pass).

    Useful for checking both IP and client_id limits simultaneously.

    Args:
        keys: List of rate limit bucket keys
        rpm_limit: Maximum requests allowed per key
        window_seconds: Time window in seconds

    Returns:
        True if all keys are within limits, False if any is rate limited
    """
    # First check all without recording
    now = time.time()
    window_start = now - window_seconds

    for key in keys:
        _rate_limits[key] = [t for t in _rate_limits[key] if t > window_start]
        if len(_rate_limits[key]) >= rpm_limit:
            return False

    # All passed, record for all keys
    for key in keys:
        _rate_limits[key].append(now)

    return True


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    key: str | None = None  # Which key triggered the limit
    retry_after: int = 60  # Seconds until the window resets


def check_oauth_rate_limit(
    request: Request,
    client_id: str | None,
    rpm_limit: int,
) -> RateLimitResult:
    """Check rate limit for OAuth endpoints.

    Applies rate limiting per:
    1. Client IP address (protects against distributed attacks)
    2. Client ID if provided (protects against credential stuffing per-client)

    Args:
        request: The incoming request
        client_id: OAuth client_id if available
        rpm_limit: Requests per minute limit

    Returns:
        RateLimitResult indicating if request is allowed
    """
    ip = _get_client_ip(request)
    ip_key = f"oauth:ip:{ip}"

    # Check IP-based limit first
    if not check_rate_limit(ip_key, rpm_limit):
        return RateLimitResult(allowed=False, key=ip_key)

    # If client_id is provided, also check per-client limit
    if client_id:
        client_key = f"oauth:client:{client_id}"
        if not check_rate_limit(client_key, rpm_limit):
            return RateLimitResult(allowed=False, key=client_key)

    return RateLimitResult(allowed=True)


def rate_limit_response() -> JSONResponse:
    """Create a standard 429 rate limit response for OAuth endpoints."""
    return JSONResponse(
        {
            "error": "rate_limit_exceeded",
            "error_description": "Too many requests. Please try again later.",
        },
        status_code=429,
        headers={"Retry-After": "60"},
    )


def clear_rate_limits() -> None:
    """Clear all rate limit state. Useful for testing."""
    _rate_limits.clear()
