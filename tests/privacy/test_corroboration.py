"""Tests for corroboration-based auto-elevation (Issue #96)."""

from datetime import UTC, datetime

import pytest

from valence.privacy.corroboration import (
    # Constants
    DEFAULT_CORROBORATION_THRESHOLD,
    DEFAULT_SIMILARITY_THRESHOLD,
    DEFAULT_TARGET_LEVEL,
    AutoElevationDisabledError,
    BeliefNotFoundError,
    CorroboratingSource,
    # Classes
    CorroborationDetector,
    # Exceptions
    CorroborationError,
    CorroborationEvidence,
    DuplicateSourceError,
    SimilarBelief,
    add_corroboration,
    # Functions
    cosine_similarity,
    get_corroboration_detector,
    get_evidence,
    opt_out_belief,
    opt_out_owner,
    propose_auto_elevation,
    set_corroboration_detector,
)
from valence.privacy.elevation import ProposalStatus
from valence.privacy.types import ShareLevel


class TestCosineSimilarity:
    """Tests for cosine_similarity function."""

    def test_identical_vectors(self):
        """Identical vectors should have similarity 1.0."""
        vec = [1.0, 2.0, 3.0]
        assert cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        """Orthogonal vectors should have similarity 0.0."""
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [0.0, 1.0, 0.0]
        assert cosine_similarity(vec1, vec2) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        """Opposite vectors should have similarity -1.0."""
        vec1 = [1.0, 2.0, 3.0]
        vec2 = [-1.0, -2.0, -3.0]
        assert cosine_similarity(vec1, vec2) == pytest.approx(-1.0)

    def test_similar_vectors(self):
        """Similar vectors should have high similarity."""
        vec1 = [1.0, 2.0, 3.0]
        vec2 = [1.1, 2.1, 3.1]
        sim = cosine_similarity(vec1, vec2)
        assert sim > 0.99

    def test_zero_vector(self):
        """Zero vectors should return 0.0."""
        vec1 = [0.0, 0.0, 0.0]
        vec2 = [1.0, 2.0, 3.0]
        assert cosine_similarity(vec1, vec2) == 0.0

    def test_dimension_mismatch_raises(self):
        """Mismatched dimensions should raise ValueError."""
        vec1 = [1.0, 2.0]
        vec2 = [1.0, 2.0, 3.0]
        with pytest.raises(ValueError, match="dimension mismatch"):
            cosine_similarity(vec1, vec2)


class TestCorroboratingSource:
    """Tests for CorroboratingSource dataclass."""

    def test_create_source(self):
        """Test creating a basic source."""
        source = CorroboratingSource(
            source_did="did:example:alice",
            belief_id="belief-123",
            similarity=0.95,
        )

        assert source.source_did == "did:example:alice"
        assert source.belief_id == "belief-123"
        assert source.similarity == 0.95
        assert source.corroborated_at is not None
        assert source.content_hash is None
        assert source.metadata == {}

    def test_source_with_all_fields(self):
        """Test source with all fields populated."""
        now = datetime(2026, 2, 4, 12, 0, 0, tzinfo=UTC)

        source = CorroboratingSource(
            source_did="did:example:bob",
            belief_id="belief-456",
            similarity=0.92,
            corroborated_at=now,
            content_hash="sha256:abc123",
            metadata={"note": "verified"},
        )

        assert source.content_hash == "sha256:abc123"
        assert source.metadata == {"note": "verified"}
        assert source.corroborated_at == now

    def test_to_dict(self):
        """Test serialization to dictionary."""
        now = datetime(2026, 2, 4, 12, 0, 0, tzinfo=UTC)

        source = CorroboratingSource(
            source_did="did:example:alice",
            belief_id="belief-123",
            similarity=0.95,
            corroborated_at=now,
            content_hash="hash123",
            metadata={"key": "value"},
        )

        data = source.to_dict()

        assert data["source_did"] == "did:example:alice"
        assert data["belief_id"] == "belief-123"
        assert data["similarity"] == 0.95
        assert data["corroborated_at"] == "2026-02-04T12:00:00+00:00"
        assert data["content_hash"] == "hash123"
        assert data["metadata"] == {"key": "value"}

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "source_did": "did:example:bob",
            "belief_id": "belief-789",
            "similarity": 0.88,
            "corroborated_at": "2026-02-04T10:30:00+00:00",
            "content_hash": None,
            "metadata": {},
        }

        source = CorroboratingSource.from_dict(data)

        assert source.source_did == "did:example:bob"
        assert source.belief_id == "belief-789"
        assert source.similarity == 0.88
        assert source.corroborated_at == datetime(2026, 2, 4, 10, 30, 0, tzinfo=UTC)

    def test_roundtrip_serialization(self):
        """Test that to_dict/from_dict preserves data."""
        original = CorroboratingSource(
            source_did="did:example:carol",
            belief_id="belief-abc",
            similarity=0.91,
            content_hash="xyz",
            metadata={"foo": 42},
        )

        restored = CorroboratingSource.from_dict(original.to_dict())

        assert restored.source_did == original.source_did
        assert restored.belief_id == original.belief_id
        assert restored.similarity == original.similarity
        assert restored.content_hash == original.content_hash
        assert restored.metadata == original.metadata


class TestCorroborationEvidence:
    """Tests for CorroborationEvidence dataclass."""

    def test_create_evidence(self):
        """Test creating basic evidence."""
        evidence = CorroborationEvidence(
            belief_id="belief-123",
            owner_did="did:example:owner",
        )

        assert evidence.belief_id == "belief-123"
        assert evidence.owner_did == "did:example:owner"
        assert evidence.sources == []
        assert evidence.source_count == 0
        assert not evidence.threshold_met
        assert evidence.auto_elevation_enabled

    def test_add_source(self):
        """Test adding sources to evidence."""
        evidence = CorroborationEvidence(
            belief_id="belief-123",
            owner_did="did:example:owner",
        )

        source1 = CorroboratingSource(
            source_did="did:example:alice",
            belief_id="alice-belief",
            similarity=0.95,
        )
        source2 = CorroboratingSource(
            source_did="did:example:bob",
            belief_id="bob-belief",
            similarity=0.90,
        )

        assert evidence.add_source(source1)
        assert evidence.source_count == 1
        assert "did:example:alice" in evidence.source_dids

        assert evidence.add_source(source2)
        assert evidence.source_count == 2

    def test_add_duplicate_source_returns_false(self):
        """Test that adding same source twice returns False."""
        evidence = CorroborationEvidence(
            belief_id="belief-123",
            owner_did="did:example:owner",
        )

        source = CorroboratingSource(
            source_did="did:example:alice",
            belief_id="alice-belief",
            similarity=0.95,
        )

        assert evidence.add_source(source)

        # Try to add same source again
        duplicate = CorroboratingSource(
            source_did="did:example:alice",
            belief_id="alice-belief-2",
            similarity=0.92,
        )
        assert not evidence.add_source(duplicate)
        assert evidence.source_count == 1

    def test_similarity_metrics(self):
        """Test similarity metrics computation."""
        evidence = CorroborationEvidence(
            belief_id="belief-123",
            owner_did="did:example:owner",
        )

        # No sources
        assert evidence.average_similarity == 0.0
        assert evidence.min_similarity == 0.0
        assert evidence.max_similarity == 0.0

        # Add sources with varying similarity
        evidence.add_source(CorroboratingSource("did:a", "b1", 0.90))
        evidence.add_source(CorroboratingSource("did:b", "b2", 0.95))
        evidence.add_source(CorroboratingSource("did:c", "b3", 0.88))

        assert evidence.average_similarity == pytest.approx(0.91, abs=0.01)
        assert evidence.min_similarity == 0.88
        assert evidence.max_similarity == 0.95

    def test_to_dict(self):
        """Test serialization to dictionary."""
        now = datetime(2026, 2, 4, 12, 0, 0, tzinfo=UTC)

        evidence = CorroborationEvidence(
            belief_id="belief-123",
            owner_did="did:example:owner",
            threshold_met=True,
            threshold_met_at=now,
            auto_elevation_proposed=True,
            proposal_id="proposal-456",
        )
        evidence.add_source(CorroboratingSource("did:a", "b1", 0.95))

        data = evidence.to_dict()

        assert data["belief_id"] == "belief-123"
        assert data["owner_did"] == "did:example:owner"
        assert data["source_count"] == 1
        assert len(data["sources"]) == 1
        assert data["threshold_met"] is True
        assert data["threshold_met_at"] == "2026-02-04T12:00:00+00:00"
        assert data["auto_elevation_proposed"] is True
        assert data["proposal_id"] == "proposal-456"

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "belief_id": "belief-789",
            "owner_did": "did:example:alice",
            "sources": [
                {
                    "source_did": "did:example:bob",
                    "belief_id": "bob-belief",
                    "similarity": 0.92,
                    "corroborated_at": "2026-02-04T10:00:00+00:00",
                    "content_hash": None,
                    "metadata": {},
                }
            ],
            "threshold_met": False,
            "threshold_met_at": None,
            "auto_elevation_proposed": False,
            "proposal_id": None,
            "auto_elevation_enabled": True,
        }

        evidence = CorroborationEvidence.from_dict(data)

        assert evidence.belief_id == "belief-789"
        assert evidence.owner_did == "did:example:alice"
        assert evidence.source_count == 1
        assert evidence.sources[0].source_did == "did:example:bob"


class TestCorroborationDetector:
    """Tests for CorroborationDetector class."""

    @pytest.fixture
    def detector(self):
        """Create a fresh detector for each test."""
        return CorroborationDetector(
            corroboration_threshold=3,
            similarity_threshold=0.85,
        )

    @pytest.fixture
    def mock_embedding_func(self):
        """Create a mock embedding function for testing."""

        # Simple mock that returns a vector based on content length
        def embed(content: str) -> list[float]:
            # Create a 3D vector based on content characteristics
            length = min(len(content), 100) / 100
            has_tech = 1.0 if "tech" in content.lower() else 0.0
            has_ai = (
                1.0
                if "ai" in content.lower() or "machine learning" in content.lower()
                else 0.0
            )
            return [length, has_tech, has_ai]

        return embed

    def test_default_configuration(self):
        """Test detector with default configuration."""
        detector = CorroborationDetector()

        assert detector.corroboration_threshold == DEFAULT_CORROBORATION_THRESHOLD
        assert detector.similarity_threshold == DEFAULT_SIMILARITY_THRESHOLD
        assert detector.target_level == DEFAULT_TARGET_LEVEL

    def test_custom_configuration(self, detector):
        """Test detector with custom configuration."""
        assert detector.corroboration_threshold == 3
        assert detector.similarity_threshold == 0.85

    def test_add_corroboration_basic(self, detector):
        """Test adding basic corroboration."""
        evidence = detector.add_corroboration(
            belief_id="belief-123",
            owner_did="did:example:owner",
            source_did="did:example:alice",
            source_belief_id="alice-belief",
            similarity=0.95,
        )

        assert evidence.belief_id == "belief-123"
        assert evidence.source_count == 1
        assert "did:example:alice" in evidence.source_dids
        assert not evidence.threshold_met

    def test_add_corroboration_reaches_threshold(self, detector):
        """Test that threshold is detected when reached."""
        # Add 3 sources (threshold)
        detector.add_corroboration("belief-1", "did:owner", "did:a", "a1", 0.95)
        detector.add_corroboration("belief-1", "did:owner", "did:b", "b1", 0.92)
        evidence = detector.add_corroboration(
            "belief-1", "did:owner", "did:c", "c1", 0.90
        )

        assert evidence.threshold_met
        assert evidence.threshold_met_at is not None
        assert evidence.source_count == 3

    def test_add_corroboration_below_similarity_threshold(self, detector):
        """Test that low similarity is rejected."""
        with pytest.raises(ValueError, match="below threshold"):
            detector.add_corroboration(
                belief_id="belief-123",
                owner_did="did:owner",
                source_did="did:alice",
                source_belief_id="alice-belief",
                similarity=0.50,  # Below 0.85 threshold
            )

    def test_add_corroboration_duplicate_source(self, detector):
        """Test that duplicate source raises error."""
        detector.add_corroboration("belief-1", "did:owner", "did:alice", "a1", 0.95)

        with pytest.raises(DuplicateSourceError):
            detector.add_corroboration("belief-1", "did:owner", "did:alice", "a2", 0.92)

    def test_get_evidence(self, detector):
        """Test retrieving evidence."""
        detector.add_corroboration("belief-1", "did:owner", "did:alice", "a1", 0.95)

        evidence = detector.get_evidence("belief-1")
        assert evidence is not None
        assert evidence.source_count == 1

        # Non-existent
        assert detector.get_evidence("belief-999") is None

    def test_propose_auto_elevation(self, detector):
        """Test proposing auto-elevation after threshold met."""
        # Reach threshold
        detector.add_corroboration("belief-1", "did:owner", "did:a", "a1", 0.95)
        detector.add_corroboration("belief-1", "did:owner", "did:b", "b1", 0.92)
        detector.add_corroboration("belief-1", "did:owner", "did:c", "c1", 0.90)

        proposal = detector.propose_auto_elevation("belief-1")

        assert proposal.belief_id == "belief-1"
        assert proposal.status == ProposalStatus.PENDING
        assert proposal.to_level == detector.target_level
        assert "auto_elevation" in proposal.metadata
        assert proposal.metadata["source_count"] == 3

        # Evidence updated
        evidence = detector.get_evidence("belief-1")
        assert evidence.auto_elevation_proposed
        assert evidence.proposal_id == proposal.proposal_id

    def test_propose_auto_elevation_returns_existing(self, detector):
        """Test that proposing again returns existing proposal."""
        # Reach threshold and propose
        detector.add_corroboration("belief-1", "did:owner", "did:a", "a1", 0.95)
        detector.add_corroboration("belief-1", "did:owner", "did:b", "b1", 0.92)
        detector.add_corroboration("belief-1", "did:owner", "did:c", "c1", 0.90)

        proposal1 = detector.propose_auto_elevation("belief-1")
        proposal2 = detector.propose_auto_elevation("belief-1")

        assert proposal1.proposal_id == proposal2.proposal_id

    def test_propose_auto_elevation_threshold_not_met(self, detector):
        """Test that proposing before threshold raises error."""
        detector.add_corroboration("belief-1", "did:owner", "did:a", "a1", 0.95)

        with pytest.raises(ValueError, match="threshold not met"):
            detector.propose_auto_elevation("belief-1")

    def test_propose_auto_elevation_no_evidence(self, detector):
        """Test that proposing without evidence raises error."""
        with pytest.raises(BeliefNotFoundError):
            detector.propose_auto_elevation("nonexistent-belief")

    def test_propose_auto_elevation_custom_level(self, detector):
        """Test proposing with custom target level."""
        detector.add_corroboration("belief-1", "did:owner", "did:a", "a1", 0.95)
        detector.add_corroboration("belief-1", "did:owner", "did:b", "b1", 0.92)
        detector.add_corroboration("belief-1", "did:owner", "did:c", "c1", 0.90)

        proposal = detector.propose_auto_elevation(
            "belief-1",
            to_level=ShareLevel.PUBLIC,
            reason="High community interest",
        )

        assert proposal.to_level == ShareLevel.PUBLIC
        assert "High community interest" in proposal.reason

    def test_opt_out_belief(self, detector):
        """Test opting out a specific belief."""
        detector.add_corroboration("belief-1", "did:owner", "did:a", "a1", 0.95)

        detector.opt_out_belief("belief-1")

        evidence = detector.get_evidence("belief-1")
        assert not evidence.auto_elevation_enabled
        assert detector.is_belief_opted_out("belief-1")

    def test_opt_out_prevents_auto_elevation(self, detector):
        """Test that opt-out prevents auto-elevation."""
        # Reach threshold
        detector.add_corroboration("belief-1", "did:owner", "did:a", "a1", 0.95)
        detector.add_corroboration("belief-1", "did:owner", "did:b", "b1", 0.92)
        detector.add_corroboration("belief-1", "did:owner", "did:c", "c1", 0.90)

        # Opt out
        detector.opt_out_belief("belief-1")

        with pytest.raises(AutoElevationDisabledError):
            detector.propose_auto_elevation("belief-1")

    def test_opt_in_belief(self, detector):
        """Test opting back in a belief."""
        detector.add_corroboration("belief-1", "did:owner", "did:a", "a1", 0.95)

        detector.opt_out_belief("belief-1")
        assert not detector.get_evidence("belief-1").auto_elevation_enabled

        detector.opt_in_belief("belief-1")
        assert detector.get_evidence("belief-1").auto_elevation_enabled

    def test_opt_out_owner_global(self, detector):
        """Test opting out owner globally."""
        detector.add_corroboration("belief-1", "did:owner", "did:a", "a1", 0.95)
        detector.add_corroboration("belief-2", "did:owner", "did:b", "b1", 0.92)

        detector.opt_out_owner("did:owner")

        assert detector.is_owner_opted_out("did:owner")
        assert not detector.get_evidence("belief-1").auto_elevation_enabled
        assert not detector.get_evidence("belief-2").auto_elevation_enabled

    def test_opt_in_owner(self, detector):
        """Test opting owner back in."""
        detector.add_corroboration("belief-1", "did:owner", "did:a", "a1", 0.95)

        detector.opt_out_owner("did:owner")
        detector.opt_in_owner("did:owner")

        assert not detector.is_owner_opted_out("did:owner")
        assert detector.get_evidence("belief-1").auto_elevation_enabled

    def test_opt_in_owner_respects_belief_opt_out(self, detector):
        """Test that owner opt-in doesn't override belief opt-out."""
        detector.add_corroboration("belief-1", "did:owner", "did:a", "a1", 0.95)

        # Opt out belief specifically
        detector.opt_out_belief("belief-1")
        # Then opt out and opt in owner
        detector.opt_out_owner("did:owner")
        detector.opt_in_owner("did:owner")

        # Belief should still be opted out
        assert not detector.get_evidence("belief-1").auto_elevation_enabled

    def test_get_threshold_met(self, detector):
        """Test getting all beliefs that met threshold."""
        # Belief 1: meets threshold
        detector.add_corroboration("belief-1", "did:owner", "did:a", "a1", 0.95)
        detector.add_corroboration("belief-1", "did:owner", "did:b", "b1", 0.92)
        detector.add_corroboration("belief-1", "did:owner", "did:c", "c1", 0.90)

        # Belief 2: doesn't meet threshold
        detector.add_corroboration("belief-2", "did:owner", "did:x", "x1", 0.95)

        threshold_met = detector.get_threshold_met()

        assert len(threshold_met) == 1
        assert threshold_met[0].belief_id == "belief-1"

    def test_get_pending_elevations(self, detector):
        """Test getting beliefs awaiting elevation decision."""
        # Belief 1: threshold met, auto-elevation enabled
        detector.add_corroboration("belief-1", "did:owner", "did:a", "a1", 0.95)
        detector.add_corroboration("belief-1", "did:owner", "did:b", "b1", 0.92)
        detector.add_corroboration("belief-1", "did:owner", "did:c", "c1", 0.90)

        # Belief 2: threshold met but opted out
        detector.add_corroboration("belief-2", "did:owner", "did:x", "x1", 0.95)
        detector.add_corroboration("belief-2", "did:owner", "did:y", "y1", 0.92)
        detector.add_corroboration("belief-2", "did:owner", "did:z", "z1", 0.90)
        detector.opt_out_belief("belief-2")

        pending = detector.get_pending_elevations()

        assert len(pending) == 1
        assert pending[0].belief_id == "belief-1"

    def test_check_similarity_no_embedding_func(self, detector):
        """Test similarity check without embedding function returns 0."""
        sim = detector.check_similarity("content1", "content2")
        assert sim == 0.0

    def test_check_similarity_with_embedding_func(self, detector, mock_embedding_func):
        """Test similarity check with embedding function."""
        detector.embedding_func = mock_embedding_func

        # Same content type should be similar
        sim = detector.check_similarity(
            "AI and machine learning tech",
            "AI and machine learning technology",
        )
        assert sim > 0.9

        # Different content should be less similar
        sim2 = detector.check_similarity(
            "AI and machine learning tech",
            "short",
        )
        assert sim2 < sim

    def test_find_similar_beliefs(self, detector, mock_embedding_func):
        """Test finding similar beliefs."""
        detector.embedding_func = mock_embedding_func

        beliefs = [
            {
                "id": "b1",
                "owner_did": "did:alice",
                "content": "AI tech machine learning",
                "share_level": "private",
            },
            {
                "id": "b2",
                "owner_did": "did:bob",
                "content": "AI tech",
                "share_level": "direct",
            },
            {
                "id": "b3",
                "owner_did": "did:carol",
                "content": "short",
                "share_level": "public",
            },
            {
                "id": "b4",
                "owner_did": "did:source",
                "content": "AI tech machine learning",
                "share_level": "private",
            },  # Same source
        ]

        similar = detector.find_similar_beliefs(
            content="AI and tech machine learning stuff",
            source_did="did:source",
            beliefs=beliefs,
            min_similarity=0.5,
        )

        # Should find beliefs from other sources
        belief_ids = [s.belief_id for s in similar]
        assert "b1" in belief_ids
        assert "b2" in belief_ids
        # Should not include same source
        assert "b4" not in belief_ids

    def test_process_incoming_belief(self, detector, mock_embedding_func):
        """Test processing incoming belief for corroboration."""
        detector.embedding_func = mock_embedding_func

        # Set up local beliefs
        local_beliefs = [
            {
                "id": "local-1",
                "owner_did": "did:local",
                "content": "AI tech machine learning research",
                "share_level": "private",
            },
        ]

        # Process incoming belief
        updated = detector.process_incoming_belief(
            source_did="did:remote",
            source_belief_id="remote-belief-1",
            content="AI tech and machine learning studies",
            local_beliefs=local_beliefs,
        )

        assert len(updated) == 1
        assert updated[0].belief_id == "local-1"
        assert updated[0].source_count == 1

    def test_process_incoming_belief_auto_proposes(self, detector, mock_embedding_func):
        """Test that processing can trigger auto-elevation proposal."""
        detector.embedding_func = mock_embedding_func

        local_beliefs = [
            {
                "id": "local-1",
                "owner_did": "did:local",
                "content": "AI tech machine learning",
                "share_level": "private",
            },
        ]

        # Add 2 sources manually
        detector.add_corroboration("local-1", "did:local", "did:a", "a1", 0.95)
        detector.add_corroboration("local-1", "did:local", "did:b", "b1", 0.92)

        # Process incoming that will be the 3rd
        detector.process_incoming_belief(
            source_did="did:remote",
            source_belief_id="remote-1",
            content="AI tech machine learning",
            local_beliefs=local_beliefs,
        )

        # Should have proposed elevation
        evidence = detector.get_evidence("local-1")
        assert evidence.threshold_met
        assert evidence.auto_elevation_proposed
        assert evidence.proposal_id is not None

    def test_clear_embedding_cache(self, detector, mock_embedding_func):
        """Test clearing embedding cache."""
        detector.embedding_func = mock_embedding_func

        # Generate some embeddings
        detector.check_similarity("content1", "content2")
        assert len(detector._embedding_cache) > 0

        detector.clear_embedding_cache()
        assert len(detector._embedding_cache) == 0


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset the singleton before each test."""
        set_corroboration_detector(None)
        yield
        set_corroboration_detector(None)

    def test_get_corroboration_detector_creates_default(self):
        """Test that get_corroboration_detector creates a default."""
        detector = get_corroboration_detector()

        assert detector is not None
        assert isinstance(detector, CorroborationDetector)
        assert detector.corroboration_threshold == DEFAULT_CORROBORATION_THRESHOLD

    def test_set_corroboration_detector(self):
        """Test setting a custom detector."""
        custom = CorroborationDetector(corroboration_threshold=5)
        set_corroboration_detector(custom)

        assert get_corroboration_detector() is custom
        assert get_corroboration_detector().corroboration_threshold == 5

    def test_add_corroboration_function(self):
        """Test add_corroboration convenience function."""
        evidence = add_corroboration(
            belief_id="belief-123",
            owner_did="did:owner",
            source_did="did:source",
            source_belief_id="source-belief",
            similarity=0.95,
        )

        assert evidence.belief_id == "belief-123"
        assert evidence.source_count == 1

    def test_get_evidence_function(self):
        """Test get_evidence convenience function."""
        add_corroboration("belief-1", "did:owner", "did:a", "a1", 0.95)

        evidence = get_evidence("belief-1")
        assert evidence is not None
        assert evidence.source_count == 1

    def test_opt_out_belief_function(self):
        """Test opt_out_belief convenience function."""
        add_corroboration("belief-1", "did:owner", "did:a", "a1", 0.95)
        opt_out_belief("belief-1")

        evidence = get_evidence("belief-1")
        assert not evidence.auto_elevation_enabled

    def test_opt_out_owner_function(self):
        """Test opt_out_owner convenience function."""
        add_corroboration("belief-1", "did:owner", "did:a", "a1", 0.95)
        opt_out_owner("did:owner")

        assert get_corroboration_detector().is_owner_opted_out("did:owner")

    def test_propose_auto_elevation_function(self):
        """Test propose_auto_elevation convenience function."""
        # Reach threshold
        add_corroboration("belief-1", "did:owner", "did:a", "a1", 0.95)
        add_corroboration("belief-1", "did:owner", "did:b", "b1", 0.92)
        add_corroboration("belief-1", "did:owner", "did:c", "c1", 0.90)

        proposal = propose_auto_elevation("belief-1")

        assert proposal.belief_id == "belief-1"
        assert proposal.status == ProposalStatus.PENDING


class TestExceptionHierarchy:
    """Tests for exception hierarchy."""

    def test_all_exceptions_inherit_from_base(self):
        """Verify exception inheritance."""
        assert issubclass(BeliefNotFoundError, CorroborationError)
        assert issubclass(DuplicateSourceError, CorroborationError)
        assert issubclass(AutoElevationDisabledError, CorroborationError)
        assert issubclass(CorroborationError, Exception)

    def test_exceptions_have_messages(self):
        """Test that exceptions carry meaningful messages."""
        e1 = BeliefNotFoundError("Belief xyz not found")
        e2 = DuplicateSourceError("Source already added")
        e3 = AutoElevationDisabledError("Auto-elevation disabled")

        assert "xyz" in str(e1)
        assert "Source" in str(e2)
        assert "disabled" in str(e3)


class TestSimilarBelief:
    """Tests for SimilarBelief dataclass."""

    def test_create_similar_belief(self):
        """Test creating a SimilarBelief."""
        belief = SimilarBelief(
            belief_id="belief-123",
            owner_did="did:owner",
            content="Test content",
            similarity=0.95,
            current_level=ShareLevel.PRIVATE,
        )

        assert belief.belief_id == "belief-123"
        assert belief.similarity == 0.95
        assert belief.current_level == ShareLevel.PRIVATE

    def test_to_dict(self):
        """Test serialization to dictionary."""
        belief = SimilarBelief(
            belief_id="belief-123",
            owner_did="did:owner",
            content="Test content",
            similarity=0.95,
            current_level=ShareLevel.BOUNDED,
        )

        data = belief.to_dict()

        assert data["belief_id"] == "belief-123"
        assert data["similarity"] == 0.95
        assert data["current_level"] == "bounded"


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.fixture
    def detector(self):
        return CorroborationDetector(
            corroboration_threshold=3,
            similarity_threshold=0.85,
        )

    def test_threshold_of_one(self):
        """Test detector with threshold of 1."""
        detector = CorroborationDetector(corroboration_threshold=1)

        evidence = detector.add_corroboration(
            "belief-1", "did:owner", "did:a", "a1", 0.95
        )

        assert evidence.threshold_met

    def test_exact_similarity_threshold(self, detector):
        """Test belief at exact similarity threshold."""
        evidence = detector.add_corroboration(
            "belief-1", "did:owner", "did:a", "a1", 0.85
        )

        assert evidence.source_count == 1

    def test_similarity_just_below_threshold(self, detector):
        """Test belief just below similarity threshold."""
        with pytest.raises(ValueError, match="below threshold"):
            detector.add_corroboration("belief-1", "did:owner", "did:a", "a1", 0.849)

    def test_many_sources(self, detector):
        """Test with many corroborating sources."""
        for i in range(10):
            detector.add_corroboration(
                "belief-1", "did:owner", f"did:source{i}", f"belief{i}", 0.90
            )

        evidence = detector.get_evidence("belief-1")
        assert evidence.source_count == 10
        assert evidence.threshold_met

    def test_multiple_beliefs(self, detector):
        """Test tracking multiple beliefs simultaneously."""
        for i in range(5):
            for j in range(3):
                detector.add_corroboration(
                    f"belief-{i}",
                    "did:owner",
                    f"did:source{j}",
                    f"src-belief-{i}-{j}",
                    0.90,
                )

        # All should have met threshold
        threshold_met = detector.get_threshold_met()
        assert len(threshold_met) == 5
