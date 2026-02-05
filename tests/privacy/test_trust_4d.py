"""Tests for TrustEdge 4D trust schema (Issue #57)."""

from datetime import UTC, datetime, timedelta

import pytest
from valence.privacy.trust import TrustEdge


class TestTrustEdgeCreation:
    """Tests for TrustEdge creation and validation."""

    def test_basic_creation(self):
        """Test creating a basic trust edge."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.8,
            integrity=0.9,
            confidentiality=0.7,
        )

        assert edge.source_did == "did:key:alice"
        assert edge.target_did == "did:key:bob"
        assert edge.competence == 0.8
        assert edge.integrity == 0.9
        assert edge.confidentiality == 0.7
        assert edge.judgment == 0.1  # default

    def test_all_dimensions(self):
        """Test creating with all four dimensions."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.8,
            integrity=0.9,
            confidentiality=0.7,
            judgment=0.6,
        )

        assert edge.judgment == 0.6

    def test_with_domain(self):
        """Test creating with optional domain."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.5,
            integrity=0.5,
            confidentiality=0.5,
            domain="medical",
        )

        assert edge.domain == "medical"

    def test_with_expiry(self):
        """Test creating with expiration."""
        expiry = datetime(2027, 1, 1, tzinfo=UTC)
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.5,
            integrity=0.5,
            confidentiality=0.5,
            expires_at=expiry,
        )

        assert edge.expires_at == expiry

    def test_timestamps_set_automatically(self):
        """Test that created_at and updated_at are set."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.5,
            integrity=0.5,
            confidentiality=0.5,
        )

        assert edge.created_at is not None
        assert edge.updated_at is not None


class TestTrustEdgeValidation:
    """Tests for TrustEdge validation."""

    def test_score_below_zero_fails(self):
        """Test that scores below 0 are rejected."""
        with pytest.raises(ValueError, match="must be between 0.0 and 1.0"):
            TrustEdge(
                source_did="did:key:alice",
                target_did="did:key:bob",
                competence=-0.1,
                integrity=0.5,
                confidentiality=0.5,
            )

    def test_score_above_one_fails(self):
        """Test that scores above 1 are rejected."""
        with pytest.raises(ValueError, match="must be between 0.0 and 1.0"):
            TrustEdge(
                source_did="did:key:alice",
                target_did="did:key:bob",
                competence=1.1,
                integrity=0.5,
                confidentiality=0.5,
            )

    def test_boundary_values_accepted(self):
        """Test that 0 and 1 are accepted."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.0,
            integrity=1.0,
            confidentiality=0.0,
            judgment=1.0,
        )

        assert edge.competence == 0.0
        assert edge.integrity == 1.0

    def test_self_trust_fails(self):
        """Test that trusting yourself is rejected."""
        with pytest.raises(ValueError, match="Cannot create trust edge to self"):
            TrustEdge(
                source_did="did:key:alice",
                target_did="did:key:alice",
                competence=0.5,
                integrity=0.5,
                confidentiality=0.5,
            )


class TestOverallTrust:
    """Tests for overall_trust computed property."""

    def test_geometric_mean_calculation(self):
        """Test that overall trust is geometric mean."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.8,
            integrity=0.8,
            confidentiality=0.8,
            judgment=0.8,
        )

        # Geometric mean of 4 equal values is the value itself
        assert abs(edge.overall_trust - 0.8) < 0.001

    def test_geometric_mean_with_all_ones(self):
        """Test geometric mean with all ones."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=1.0,
            integrity=1.0,
            confidentiality=1.0,
            judgment=1.0,
        )

        assert abs(edge.overall_trust - 1.0) < 0.001

    def test_zero_dimension_gives_zero_overall(self):
        """Test that any zero dimension results in zero overall trust."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.0,
            integrity=0.9,
            confidentiality=0.9,
            judgment=0.9,
        )

        assert edge.overall_trust == 0.0

    def test_low_judgment_pulls_down_overall(self):
        """Test that low judgment (default) affects overall trust."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.9,
            integrity=0.9,
            confidentiality=0.9,
            # judgment defaults to 0.1
        )

        # geometric mean of (0.9, 0.9, 0.9, 0.1) ≈ 0.548
        assert edge.overall_trust < 0.6
        assert edge.overall_trust > 0.5


class TestExpiration:
    """Tests for trust edge expiration."""

    def test_not_expired_when_no_expiry(self):
        """Test is_expired returns False when no expiry set."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.5,
            integrity=0.5,
            confidentiality=0.5,
        )

        assert not edge.is_expired()

    def test_not_expired_when_future(self):
        """Test is_expired returns False when expiry is in future."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.5,
            integrity=0.5,
            confidentiality=0.5,
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )

        assert not edge.is_expired()

    def test_expired_when_past(self):
        """Test is_expired returns True when expiry is in past."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.5,
            integrity=0.5,
            confidentiality=0.5,
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )

        assert edge.is_expired()


class TestSerialization:
    """Tests for to_dict and from_dict."""

    def test_to_dict(self):
        """Test serialization to dictionary."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.8,
            integrity=0.9,
            confidentiality=0.7,
            judgment=0.6,
            domain="medical",
        )

        data = edge.to_dict()

        assert data["source_did"] == "did:key:alice"
        assert data["target_did"] == "did:key:bob"
        assert data["competence"] == 0.8
        assert data["integrity"] == 0.9
        assert data["confidentiality"] == 0.7
        assert data["judgment"] == 0.6
        assert data["domain"] == "medical"
        assert data["created_at"] is not None
        assert data["updated_at"] is not None

    def test_to_dict_with_expiry(self):
        """Test serialization includes expiry."""
        expiry = datetime(2027, 1, 1, 12, 0, 0, tzinfo=UTC)
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.5,
            integrity=0.5,
            confidentiality=0.5,
            expires_at=expiry,
        )

        data = edge.to_dict()

        assert data["expires_at"] == "2027-01-01T12:00:00+00:00"

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "source_did": "did:key:alice",
            "target_did": "did:key:bob",
            "competence": 0.8,
            "integrity": 0.9,
            "confidentiality": 0.7,
            "judgment": 0.6,
            "domain": "finance",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-02-01T00:00:00+00:00",
            "expires_at": "2027-01-01T00:00:00+00:00",
        }

        edge = TrustEdge.from_dict(data)

        assert edge.source_did == "did:key:alice"
        assert edge.target_did == "did:key:bob"
        assert edge.competence == 0.8
        assert edge.integrity == 0.9
        assert edge.confidentiality == 0.7
        assert edge.judgment == 0.6
        assert edge.domain == "finance"
        assert edge.expires_at == datetime(2027, 1, 1, tzinfo=UTC)

    def test_from_dict_with_defaults(self):
        """Test deserialization with minimal data uses defaults."""
        data = {
            "source_did": "did:key:alice",
            "target_did": "did:key:bob",
        }

        edge = TrustEdge.from_dict(data)

        assert edge.competence == 0.5  # default
        assert edge.integrity == 0.5  # default
        assert edge.confidentiality == 0.5  # default
        assert edge.judgment == 0.1  # default
        assert edge.domain is None
        assert edge.expires_at is None

    def test_roundtrip(self):
        """Test serialization roundtrip preserves data."""
        original = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.8,
            integrity=0.9,
            confidentiality=0.7,
            judgment=0.6,
            domain="research",
            expires_at=datetime(2027, 6, 15, tzinfo=UTC),
        )

        restored = TrustEdge.from_dict(original.to_dict())

        assert restored.source_did == original.source_did
        assert restored.target_did == original.target_did
        assert restored.competence == original.competence
        assert restored.integrity == original.integrity
        assert restored.confidentiality == original.confidentiality
        assert restored.judgment == original.judgment
        assert restored.domain == original.domain
        assert restored.expires_at == original.expires_at
