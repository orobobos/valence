"""ASN diversity enforcement for eclipse resistance (#348).

Tracks the Autonomous System Number (ASN) distribution of connected
federation peers. Enforces:
- No single ASN > 25% of connections
- Minimum 4 distinct ASNs (when enough peers available)

Uses IP-to-ASN mapping via a pluggable resolver. Falls back to
unknown ASN when lookup fails (doesn't block connections).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

MAX_ASN_FRACTION = 0.25  # No single ASN > 25%
MIN_DISTINCT_ASNS = 4


@dataclass
class ASNDistribution:
    """Current ASN distribution across connections."""

    asn_counts: dict[str, int] = field(default_factory=dict)
    total_connections: int = 0

    @property
    def distinct_asns(self) -> int:
        return len(self.asn_counts)

    @property
    def dominant_asn(self) -> tuple[str, float] | None:
        """Return the most common ASN and its fraction."""
        if not self.asn_counts or self.total_connections == 0:
            return None
        asn = max(self.asn_counts, key=self.asn_counts.get)  # type: ignore[arg-type]
        fraction = self.asn_counts[asn] / self.total_connections
        return asn, fraction

    def to_dict(self) -> dict[str, Any]:
        return {
            "asn_counts": self.asn_counts,
            "total_connections": self.total_connections,
            "distinct_asns": self.distinct_asns,
        }


@dataclass
class DiversityCheck:
    """Result of an ASN diversity check."""

    is_diverse: bool
    distinct_asns: int
    total_connections: int
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_diverse": self.is_diverse,
            "distinct_asns": self.distinct_asns,
            "total_connections": self.total_connections,
            "violations": self.violations,
        }


def ip_to_asn(ip: str) -> str:
    """Map an IP address to its ASN.

    Currently uses a deterministic hash-based mapping for development.
    In production, this would use MaxMind GeoLite2-ASN or pyasn.

    Args:
        ip: IPv4 or IPv6 address string.

    Returns:
        ASN string (e.g., "AS13335"). Returns "AS0" for unknown.
    """
    # Deterministic mapping based on IP prefix for consistent behavior
    # In production: use pyasn or MaxMind GeoLite2-ASN database
    try:
        parts = ip.split(".")
        if len(parts) == 4:
            # IPv4: group by /16 prefix for realistic ASN distribution
            prefix = f"{parts[0]}.{parts[1]}"
            asn_num = int(hashlib.sha256(prefix.encode()).hexdigest()[:8], 16) % 65535
            return f"AS{asn_num}"
        # IPv6 or other: hash the whole thing
        asn_num = int(hashlib.sha256(ip.encode()).hexdigest()[:8], 16) % 65535
        return f"AS{asn_num}"
    except Exception:
        return "AS0"


def build_distribution(peer_ips: list[str]) -> ASNDistribution:
    """Build an ASN distribution from a list of peer IP addresses.

    Args:
        peer_ips: List of peer IP addresses.

    Returns:
        ASNDistribution with counts per ASN.
    """
    dist = ASNDistribution(total_connections=len(peer_ips))
    for ip in peer_ips:
        asn = ip_to_asn(ip)
        dist.asn_counts[asn] = dist.asn_counts.get(asn, 0) + 1
    return dist


def check_diversity(
    distribution: ASNDistribution,
    max_fraction: float = MAX_ASN_FRACTION,
    min_asns: int = MIN_DISTINCT_ASNS,
) -> DiversityCheck:
    """Check if the current ASN distribution meets diversity requirements.

    Args:
        distribution: Current ASN distribution.
        max_fraction: Maximum fraction for any single ASN (default 0.25).
        min_asns: Minimum distinct ASNs required (default 4).

    Returns:
        DiversityCheck with violations if any.
    """
    violations = []

    if distribution.total_connections == 0:
        return DiversityCheck(
            is_diverse=True,
            distinct_asns=0,
            total_connections=0,
        )

    # Check single-ASN dominance
    dominant = distribution.dominant_asn
    if dominant:
        asn, fraction = dominant
        if fraction > max_fraction:
            violations.append(
                f"ASN {asn} has {fraction:.0%} of connections (max {max_fraction:.0%})"
            )

    # Check minimum distinct ASNs (only when enough peers to be meaningful)
    if distribution.total_connections >= min_asns and distribution.distinct_asns < min_asns:
        violations.append(
            f"Only {distribution.distinct_asns} distinct ASNs (minimum {min_asns})"
        )

    return DiversityCheck(
        is_diverse=len(violations) == 0,
        distinct_asns=distribution.distinct_asns,
        total_connections=distribution.total_connections,
        violations=violations,
    )


def should_accept_peer(
    peer_ip: str,
    current_distribution: ASNDistribution,
    max_fraction: float = MAX_ASN_FRACTION,
) -> bool:
    """Check if accepting a new peer would violate ASN diversity.

    Args:
        peer_ip: IP of the proposed new peer.
        current_distribution: Current distribution before adding.
        max_fraction: Maximum allowed fraction.

    Returns:
        True if the peer can be accepted without violating constraints.
    """
    peer_asn = ip_to_asn(peer_ip)
    current_count = current_distribution.asn_counts.get(peer_asn, 0)
    new_total = current_distribution.total_connections + 1
    new_fraction = (current_count + 1) / new_total

    return new_fraction <= max_fraction
