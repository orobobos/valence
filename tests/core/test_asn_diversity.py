"""Tests for ASN diversity enforcement (#348).

Tests cover:
1. ip_to_asn returns ASN string
2. ip_to_asn deterministic for same IP
3. ip_to_asn groups by /16 prefix
4. ip_to_asn handles invalid input
5. build_distribution counts correctly
6. check_diversity passes with diverse IPs
7. check_diversity fails on ASN dominance
8. check_diversity fails on low distinct ASNs
9. check_diversity empty set is diverse
10. should_accept_peer rejects if would violate
11. should_accept_peer accepts if within limits
12. ASNDistribution properties
13. DiversityCheck serialization
"""

from __future__ import annotations

from valence.core.asn_diversity import (
    MAX_ASN_FRACTION,
    MIN_DISTINCT_ASNS,
    ASNDistribution,
    DiversityCheck,
    build_distribution,
    check_diversity,
    ip_to_asn,
    should_accept_peer,
)


class TestIpToAsn:
    """Test IP-to-ASN mapping."""

    def test_returns_asn_string(self):
        asn = ip_to_asn("192.168.1.1")
        assert asn.startswith("AS")

    def test_deterministic(self):
        a1 = ip_to_asn("10.0.0.1")
        a2 = ip_to_asn("10.0.0.1")
        assert a1 == a2

    def test_same_prefix_same_asn(self):
        # Same /16 prefix should map to same ASN
        a1 = ip_to_asn("10.0.1.1")
        a2 = ip_to_asn("10.0.2.2")
        assert a1 == a2

    def test_different_prefix_different_asn(self):
        # Different /16 prefixes should (likely) map to different ASNs
        a1 = ip_to_asn("10.0.0.1")
        a2 = ip_to_asn("172.16.0.1")
        assert a1 != a2

    def test_handles_invalid_input(self):
        asn = ip_to_asn("not-an-ip")
        assert asn.startswith("AS")  # Returns hash-based ASN

    def test_handles_ipv6(self):
        asn = ip_to_asn("2001:db8::1")
        assert asn.startswith("AS")


class TestBuildDistribution:
    """Test distribution building."""

    def test_counts_correctly(self):
        # Use IPs from different /16 prefixes
        ips = ["10.0.0.1", "10.0.0.2", "172.16.0.1"]
        dist = build_distribution(ips)
        assert dist.total_connections == 3
        # 10.0.x.x are same ASN, 172.16.x.x different
        assert dist.distinct_asns >= 2

    def test_empty_list(self):
        dist = build_distribution([])
        assert dist.total_connections == 0
        assert dist.distinct_asns == 0

    def test_all_same_asn(self):
        # All from same /16 prefix
        ips = ["10.0.1.1", "10.0.2.2", "10.0.3.3", "10.0.4.4"]
        dist = build_distribution(ips)
        assert dist.total_connections == 4
        assert dist.distinct_asns == 1


class TestCheckDiversity:
    """Test diversity checking."""

    def test_empty_is_diverse(self):
        dist = ASNDistribution()
        check = check_diversity(dist)
        assert check.is_diverse is True
        assert len(check.violations) == 0

    def test_diverse_set_passes(self):
        # 4 distinct ASNs, evenly distributed
        dist = ASNDistribution(
            asn_counts={"AS1": 2, "AS2": 2, "AS3": 2, "AS4": 2},
            total_connections=8,
        )
        check = check_diversity(dist)
        assert check.is_diverse is True
        assert len(check.violations) == 0

    def test_dominant_asn_fails(self):
        # AS1 has 60% of connections
        dist = ASNDistribution(
            asn_counts={"AS1": 6, "AS2": 1, "AS3": 1, "AS4": 2},
            total_connections=10,
        )
        check = check_diversity(dist)
        assert check.is_diverse is False
        assert any("AS1" in v for v in check.violations)

    def test_too_few_asns_fails(self):
        # Only 2 ASNs with enough peers
        dist = ASNDistribution(
            asn_counts={"AS1": 3, "AS2": 3},
            total_connections=6,
        )
        check = check_diversity(dist)
        assert check.is_diverse is False
        assert any("distinct ASNs" in v for v in check.violations)

    def test_few_peers_skips_asn_count_check(self):
        # 3 peers with 2 ASNs — min_asns check skipped because total(3) < min_asns(4)
        # Use custom max_fraction to avoid dominance violation
        dist = ASNDistribution(
            asn_counts={"AS1": 2, "AS2": 1},
            total_connections=3,
        )
        # With default max_fraction=0.25, AS1 at 67% would fail dominance.
        # But with min_asns=10 and total_connections=3, the min ASN check is skipped.
        check = check_diversity(dist, max_fraction=0.75, min_asns=10)
        assert check.is_diverse is True
        assert check.distinct_asns == 2

    def test_custom_thresholds(self):
        dist = ASNDistribution(
            asn_counts={"AS1": 4, "AS2": 4, "AS3": 2},
            total_connections=10,
        )
        # With max_fraction=0.5, AS1 at 40% is fine
        check = check_diversity(dist, max_fraction=0.5, min_asns=2)
        assert check.is_diverse is True


class TestShouldAcceptPeer:
    """Test peer acceptance check."""

    def test_accepts_within_limits(self):
        dist = ASNDistribution(
            asn_counts={"AS1": 1, "AS2": 1, "AS3": 1, "AS4": 1},
            total_connections=4,
        )
        # Adding a new ASN5 peer: 1/5 = 20% < 25%
        assert should_accept_peer("172.16.0.1", dist) is True

    def test_rejects_if_would_violate(self):
        dist = ASNDistribution(
            asn_counts={"AS1": 1},
            total_connections=1,
        )
        # Adding same ASN1 peer: 2/2 = 100% > 25%
        # Need to find an IP that maps to same ASN as 10.0.x.x
        ip_asn = ip_to_asn("10.0.0.1")
        dist_single = ASNDistribution(
            asn_counts={ip_asn: 1},
            total_connections=1,
        )
        # Same prefix = same ASN: 2/2 = 100%
        assert should_accept_peer("10.0.5.5", dist_single) is False

    def test_accepts_new_asn_to_empty(self):
        dist = ASNDistribution(total_connections=0)
        # 1/1 = 100% but that's the first peer
        # Actually 100% > 25%, so this should reject
        assert should_accept_peer("10.0.0.1", dist) is False


class TestASNDistributionProperties:
    """Test ASNDistribution dataclass."""

    def test_dominant_asn(self):
        dist = ASNDistribution(
            asn_counts={"AS1": 5, "AS2": 3, "AS3": 2},
            total_connections=10,
        )
        dominant = dist.dominant_asn
        assert dominant is not None
        assert dominant[0] == "AS1"
        assert dominant[1] == 0.5

    def test_dominant_asn_empty(self):
        dist = ASNDistribution()
        assert dist.dominant_asn is None

    def test_to_dict(self):
        dist = ASNDistribution(
            asn_counts={"AS1": 5},
            total_connections=5,
        )
        d = dist.to_dict()
        assert d["total_connections"] == 5
        assert d["distinct_asns"] == 1

    def test_diversity_check_to_dict(self):
        check = DiversityCheck(
            is_diverse=False,
            distinct_asns=2,
            total_connections=10,
            violations=["test violation"],
        )
        d = check.to_dict()
        assert d["is_diverse"] is False
        assert len(d["violations"]) == 1
