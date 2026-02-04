# Tests for Corroboration Detection and Auto-Elevation
"""
Test suite for corroboration detection and auto-elevation features.

Tests cover:
- Semantic similarity detection
- Independent source tracking
- Corroboration threshold management
- Evidence chain tracking
- Auto-elevation proposals
- Owner opt-out controls
"""

import pytest
from datetime import datetime, timezone

from valence.privacy.corroboration import (
    CorroborationStatus,
    SourceInfo,
    CorroborationEvidence,
    CorroborationConfig,
    CorroborationDetector,
    MockEmbeddingSimilarity,
    check_corroboration,
    register_belief,
    is_corroborated,
    get_elevation_candidates,
    get_detector,
)
from valence.privacy.elevation import (
    ElevationLevel,
    ElevationTrigger,
    ProposalStatus,
    ElevationProposal,
    BeliefElevationState,
    AutoElevationConfig,
    ElevationManager,
    get_elevation_manager,
    check_and_propose_elevation,
    approve_elevation,
    reject_elevation,
    opt_out_auto_elevation,
    opt_in_auto_elevation,
)
import valence.privacy.corroboration as corroboration_module
import valence.privacy.elevation as elevation_module


# ============================================================================
# Source Info Tests
# ============================================================================

class TestSourceInfo:
    """Tests for SourceInfo dataclass."""
    
    def test_creation(self):
        """SourceInfo should store all fields."""
        source = SourceInfo(
            source_id="src-1",
            source_type="federation",
            content_hash="abc123",
            similarity=0.95,
        )
        
        assert source.source_id == "src-1"
        assert source.source_type == "federation"
        assert source.content_hash == "abc123"
        assert source.similarity == 0.95
        assert source.corroborated_at is not None
    
    def test_to_dict_serialization(self):
        """to_dict should produce JSON-serializable output."""
        source = SourceInfo(
            source_id="src-1",
            source_type="api",
            content_hash="def456",
            similarity=0.88,
            metadata={"key": "value"},
        )
        
        data = source.to_dict()
        
        assert data["source_id"] == "src-1"
        assert data["source_type"] == "api"
        assert data["similarity"] == 0.88
        assert data["metadata"] == {"key": "value"}
        assert "corroborated_at" in data
    
    def test_from_dict_deserialization(self):
        """from_dict should reconstruct SourceInfo."""
        data = {
            "source_id": "src-2",
            "source_type": "manual",
            "content_hash": "ghi789",
            "similarity": 0.92,
            "corroborated_at": "2025-01-15T10:00:00+00:00",
        }
        
        source = SourceInfo.from_dict(data)
        
        assert source.source_id == "src-2"
        assert source.source_type == "manual"
        assert source.similarity == 0.92


# ============================================================================
# Corroboration Evidence Tests
# ============================================================================

class TestCorroborationEvidence:
    """Tests for CorroborationEvidence tracking."""
    
    def test_empty_evidence(self):
        """New evidence should start empty."""
        evidence = CorroborationEvidence(
            belief_id="belief-1",
            belief_content="Test belief content",
        )
        
        assert evidence.source_count == 0
        assert evidence.status == CorroborationStatus.UNCORROBORATED
        assert evidence.average_similarity == 0.0
    
    def test_add_source(self):
        """Adding a source should increase count."""
        evidence = CorroborationEvidence(
            belief_id="belief-1",
            belief_content="Test belief content",
        )
        
        source = SourceInfo(
            source_id="src-1",
            source_type="api",
            content_hash="abc",
            similarity=0.90,
        )
        
        added = evidence.add_source(source)
        
        assert added is True
        assert evidence.source_count == 1
        assert evidence.first_corroborated_at is not None
    
    def test_add_duplicate_source_rejected(self):
        """Adding same source twice should be rejected."""
        evidence = CorroborationEvidence(
            belief_id="belief-1",
            belief_content="Test belief content",
        )
        
        source = SourceInfo(
            source_id="src-1",
            source_type="api",
            content_hash="abc",
            similarity=0.90,
        )
        
        evidence.add_source(source)
        added = evidence.add_source(source)  # Second time
        
        assert added is False
        assert evidence.source_count == 1
    
    def test_unique_source_types(self):
        """unique_source_types should track distinct types."""
        evidence = CorroborationEvidence(
            belief_id="belief-1",
            belief_content="Test belief content",
        )
        
        evidence.add_source(SourceInfo("src-1", "api", "abc", 0.9))
        evidence.add_source(SourceInfo("src-2", "federation", "def", 0.9))
        evidence.add_source(SourceInfo("src-3", "api", "ghi", 0.9))
        
        assert len(evidence.unique_source_types) == 2
        assert "api" in evidence.unique_source_types
        assert "federation" in evidence.unique_source_types
    
    def test_average_similarity(self):
        """average_similarity should compute mean across sources."""
        evidence = CorroborationEvidence(
            belief_id="belief-1",
            belief_content="Test belief content",
        )
        
        evidence.add_source(SourceInfo("src-1", "api", "a", 0.90))
        evidence.add_source(SourceInfo("src-2", "api", "b", 0.95))
        evidence.add_source(SourceInfo("src-3", "api", "c", 0.85))
        
        assert abs(evidence.average_similarity - 0.90) < 0.001


# ============================================================================
# Mock Embedding Similarity Tests
# ============================================================================

class TestMockEmbeddingSimilarity:
    """Tests for the mock embedding similarity backend."""
    
    def test_identical_texts_high_similarity(self):
        """Identical texts should have similarity of 1.0."""
        backend = MockEmbeddingSimilarity()
        similarity = backend.compute_similarity(
            "Python is a programming language",
            "Python is a programming language",
        )
        
        assert similarity == 1.0
    
    def test_completely_different_texts_low_similarity(self):
        """Completely different texts should have low similarity."""
        backend = MockEmbeddingSimilarity()
        similarity = backend.compute_similarity(
            "apple banana cherry",
            "dog elephant fox",
        )
        
        assert similarity == 0.0
    
    def test_partial_overlap_moderate_similarity(self):
        """Texts with some overlap should have moderate similarity."""
        backend = MockEmbeddingSimilarity()
        similarity = backend.compute_similarity(
            "Python is a great programming language",
            "Python is useful for programming tasks",
        )
        
        # Should have some overlap (python, is, programming)
        assert 0.2 < similarity < 0.8
    
    def test_find_similar_returns_matches(self):
        """find_similar should return candidates above threshold."""
        backend = MockEmbeddingSimilarity()
        candidates = [
            ("belief-1", "Python is a programming language"),
            ("belief-2", "Java is a programming language"),
            ("belief-3", "The weather is sunny today"),
        ]
        
        results = backend.find_similar(
            "Python is a great programming language",
            candidates,
            threshold=0.3,
        )
        
        # Should match belief-1 and belief-2 (both about programming)
        matched_ids = [r[0] for r in results]
        assert "belief-1" in matched_ids
        assert "belief-2" in matched_ids


# ============================================================================
# Corroboration Detector Tests
# ============================================================================

class TestCorroborationDetector:
    """Tests for the CorroborationDetector service."""
    
    @pytest.fixture
    def detector(self):
        """Create a fresh detector for each test."""
        return CorroborationDetector()
    
    def test_register_belief(self, detector):
        """register_belief should create initial evidence."""
        evidence = detector.register_belief(
            belief_id="belief-1",
            content="Python 3.12 adds improved error messages",
            source_id="official-docs",
            source_type="documentation",
        )
        
        assert evidence.belief_id == "belief-1"
        assert evidence.source_count == 1  # Original source counts
        assert evidence.status == CorroborationStatus.UNCORROBORATED
    
    def test_check_corroboration_no_match(self, detector):
        """check_corroboration should return None if no similar belief."""
        detector.register_belief(
            belief_id="belief-1",
            content="Python is great for scripting",
            source_id="src-1",
            source_type="manual",
        )
        
        result = detector.check_corroboration(
            content="The weather is nice today",
            source_id="src-2",
            source_type="api",
        )
        
        assert result is None
    
    def test_check_corroboration_finds_match(self):
        """check_corroboration should find similar beliefs."""
        # Use lower threshold for mock backend (word overlap based)
        config = CorroborationConfig(similarity_threshold=0.5)
        detector = CorroborationDetector(config=config)
        
        detector.register_belief(
            belief_id="belief-1",
            content="Python is great for scripting automation",
            source_id="src-1",
            source_type="manual",
        )
        
        # Similar content from different source (high word overlap)
        result = detector.check_corroboration(
            content="Python is great for scripting automation tasks",
            source_id="src-2",
            source_type="api",
        )
        
        assert result is not None
        belief_id, evidence = result
        assert belief_id == "belief-1"
        assert evidence.source_count == 2  # Original + corroborating
    
    def test_multiple_corroborations_reach_threshold(self, detector):
        """Multiple sources should eventually reach corroboration threshold."""
        config = CorroborationConfig(
            similarity_threshold=0.3,  # Lower for mock backend
            corroboration_threshold=3,
        )
        detector = CorroborationDetector(config=config)
        
        detector.register_belief(
            belief_id="belief-1",
            content="Python programming language is versatile",
            source_id="src-1",
            source_type="docs",
        )
        
        # Add corroborating sources
        detector.check_corroboration(
            content="Python programming language is highly versatile",
            source_id="src-2",
            source_type="blog",
        )
        
        detector.check_corroboration(
            content="Python programming is known for being versatile",
            source_id="src-3",
            source_type="tutorial",
        )
        
        # Check status
        assert detector.is_corroborated("belief-1") is True
        evidence = detector.get_evidence("belief-1")
        assert evidence.status == CorroborationStatus.CORROBORATED
    
    def test_same_source_not_counted_twice(self, detector):
        """Same source corroborating twice should only count once."""
        config = CorroborationConfig(similarity_threshold=0.3)
        detector = CorroborationDetector(config=config)
        
        detector.register_belief(
            belief_id="belief-1",
            content="Test belief content here",
            source_id="src-1",
            source_type="manual",
        )
        
        detector.check_corroboration(
            content="Test belief content here with variation",
            source_id="src-2",
            source_type="api",
        )
        
        # Same source again
        detector.check_corroboration(
            content="Test belief content here another version",
            source_id="src-2",  # Same source ID
            source_type="api",
        )
        
        evidence = detector.get_evidence("belief-1")
        assert evidence.source_count == 2  # Not 3
    
    def test_get_elevation_candidates(self, detector):
        """get_elevation_candidates should return beliefs above threshold."""
        config = CorroborationConfig(
            similarity_threshold=0.3,
            corroboration_threshold=2,
        )
        detector = CorroborationDetector(config=config)
        
        # Belief with enough sources
        detector.register_belief("belief-1", "Well corroborated fact", "s1", "a")
        detector.check_corroboration("Well corroborated fact indeed", "s2", "b")
        
        # Belief without enough sources
        detector.register_belief("belief-2", "Lone belief", "s3", "c")
        
        candidates = detector.get_elevation_candidates()
        
        assert len(candidates) == 1
        assert candidates[0].belief_id == "belief-1"
    
    def test_confidence_boost_calculation(self, detector):
        """Confidence boost should increase with more sources."""
        config = CorroborationConfig(
            similarity_threshold=0.3,
            confidence_boost_base=0.3,
            confidence_boost_decay=0.5,
        )
        detector = CorroborationDetector(config=config)
        
        detector.register_belief("belief-1", "Test content", "s1", "a")
        
        evidence_1 = detector.get_evidence("belief-1")
        boost_1 = evidence_1.confidence_boost
        
        detector.check_corroboration("Test content variation", "s2", "b")
        
        evidence_2 = detector.get_evidence("belief-1")
        boost_2 = evidence_2.confidence_boost
        
        detector.check_corroboration("Test content another", "s3", "c")
        
        evidence_3 = detector.get_evidence("belief-1")
        boost_3 = evidence_3.confidence_boost
        
        # Boost should increase with each source
        assert boost_2 > boost_1
        assert boost_3 > boost_2


# ============================================================================
# Elevation Manager Tests
# ============================================================================

class TestElevationManager:
    """Tests for the ElevationManager service."""
    
    @pytest.fixture
    def manager_with_detector(self):
        """Create elevation manager with a fresh detector."""
        config = CorroborationConfig(
            similarity_threshold=0.3,
            corroboration_threshold=3,
        )
        detector = CorroborationDetector(config=config)
        
        elev_config = AutoElevationConfig(
            enabled=True,
            corroboration_levels={
                3: ElevationLevel.TRUSTED,
                5: ElevationLevel.COMMUNITY,
            },
            auto_approve=False,
            require_source_diversity=False,
        )
        manager = ElevationManager(
            corroboration_detector=detector,
            config=elev_config,
        )
        
        return manager, detector
    
    def test_proposal_created_when_threshold_met(self, manager_with_detector):
        """Proposal should be created when corroboration threshold is met."""
        manager, detector = manager_with_detector
        
        # Register and corroborate a belief
        detector.register_belief("belief-1", "Test content for corroboration", "s1", "a")
        detector.check_corroboration("Test content for corroboration v2", "s2", "b")
        detector.check_corroboration("Test content for corroboration v3", "s3", "c")
        
        evidence = detector.get_evidence("belief-1")
        proposal = manager.check_and_propose_elevation("belief-1", evidence)
        
        assert proposal is not None
        assert proposal.belief_id == "belief-1"
        assert proposal.to_level == ElevationLevel.TRUSTED
        assert proposal.trigger == ElevationTrigger.CORROBORATION
        assert proposal.status == ProposalStatus.PENDING
    
    def test_no_proposal_below_threshold(self, manager_with_detector):
        """No proposal should be created if below threshold."""
        manager, detector = manager_with_detector
        
        detector.register_belief("belief-1", "Test content", "s1", "a")
        detector.check_corroboration("Test content v2", "s2", "b")
        # Only 2 sources, threshold is 3
        
        evidence = detector.get_evidence("belief-1")
        proposal = manager.check_and_propose_elevation("belief-1", evidence)
        
        assert proposal is None
    
    def test_approve_proposal(self, manager_with_detector):
        """Approving proposal should update belief state."""
        manager, detector = manager_with_detector
        
        detector.register_belief("belief-1", "Test content", "s1", "a")
        detector.check_corroboration("Test content v2", "s2", "b")
        detector.check_corroboration("Test content v3", "s3", "c")
        
        evidence = detector.get_evidence("belief-1")
        proposal = manager.check_and_propose_elevation("belief-1", evidence)
        
        approved = manager.approve_proposal(proposal.proposal_id, "Looks good")
        
        assert approved.status == ProposalStatus.APPROVED
        
        state = manager.get_elevation_state("belief-1")
        assert state.current_level == ElevationLevel.TRUSTED
        assert len(state.elevation_history) == 1
    
    def test_reject_proposal(self, manager_with_detector):
        """Rejecting proposal should not change state."""
        manager, detector = manager_with_detector
        
        detector.register_belief("belief-1", "Test content", "s1", "a")
        detector.check_corroboration("Test content v2", "s2", "b")
        detector.check_corroboration("Test content v3", "s3", "c")
        
        evidence = detector.get_evidence("belief-1")
        proposal = manager.check_and_propose_elevation("belief-1", evidence)
        
        rejected = manager.reject_proposal(proposal.proposal_id, "Not ready")
        
        assert rejected.status == ProposalStatus.REJECTED
        
        state = manager.get_elevation_state("belief-1")
        assert state.current_level == ElevationLevel.PRIVATE
    
    def test_opt_out_prevents_proposal(self, manager_with_detector):
        """Opted-out beliefs should not get proposals."""
        manager, detector = manager_with_detector
        
        detector.register_belief("belief-1", "Test content", "s1", "a")
        
        # Opt out before corroboration
        manager.opt_out("belief-1", "Privacy concerns")
        
        detector.check_corroboration("Test content v2", "s2", "b")
        detector.check_corroboration("Test content v3", "s3", "c")
        
        evidence = detector.get_evidence("belief-1")
        proposal = manager.check_and_propose_elevation("belief-1", evidence)
        
        assert proposal is None
        assert manager.is_opted_out("belief-1") is True
    
    def test_opt_in_after_opt_out(self, manager_with_detector):
        """Opt-in should re-enable auto-elevation."""
        manager, detector = manager_with_detector
        
        manager.opt_out("belief-1")
        assert manager.is_opted_out("belief-1") is True
        
        manager.opt_in("belief-1")
        assert manager.is_opted_out("belief-1") is False
    
    def test_auto_approve_config(self, manager_with_detector):
        """Auto-approve config should skip pending status."""
        _, detector = manager_with_detector
        
        config = AutoElevationConfig(
            enabled=True,
            corroboration_levels={3: ElevationLevel.TRUSTED},
            auto_approve=True,  # Enable auto-approve
            require_source_diversity=False,
        )
        manager = ElevationManager(
            corroboration_detector=detector,
            config=config,
        )
        
        detector.register_belief("belief-1", "Test content", "s1", "a")
        detector.check_corroboration("Test content v2", "s2", "b")
        detector.check_corroboration("Test content v3", "s3", "c")
        
        evidence = detector.get_evidence("belief-1")
        proposal = manager.check_and_propose_elevation("belief-1", evidence)
        
        assert proposal.status == ProposalStatus.AUTO_APPROVED
        
        state = manager.get_elevation_state("belief-1")
        assert state.current_level == ElevationLevel.TRUSTED
    
    def test_manual_elevation(self, manager_with_detector):
        """Manual elevation should bypass corroboration check."""
        manager, detector = manager_with_detector
        
        state = manager.elevate_manually(
            "belief-1",
            ElevationLevel.COMMUNITY,
            "Owner decision",
        )
        
        assert state.current_level == ElevationLevel.COMMUNITY
        assert state.elevation_history[0]["trigger"] == ElevationTrigger.MANUAL.value
    
    def test_higher_level_with_more_sources(self, manager_with_detector):
        """More sources should enable higher elevation levels."""
        manager, detector = manager_with_detector
        
        detector.register_belief("belief-1", "Test content", "s1", "a")
        
        # Add sources to reach COMMUNITY level (5 sources)
        for i in range(2, 6):
            detector.check_corroboration(f"Test content v{i}", f"s{i}", f"t{i}")
        
        evidence = detector.get_evidence("belief-1")
        proposal = manager.check_and_propose_elevation("belief-1", evidence)
        
        assert proposal.to_level == ElevationLevel.COMMUNITY
    
    def test_source_diversity_requirement(self):
        """Source diversity should be enforced when configured."""
        config = CorroborationConfig(
            similarity_threshold=0.3,
            corroboration_threshold=3,
        )
        detector = CorroborationDetector(config=config)
        
        elev_config = AutoElevationConfig(
            enabled=True,
            corroboration_levels={3: ElevationLevel.TRUSTED},
            require_source_diversity=True,
            min_unique_source_types=2,
        )
        manager = ElevationManager(
            corroboration_detector=detector,
            config=elev_config,
        )
        
        # All same source type
        detector.register_belief("belief-1", "Test content", "s1", "api")
        detector.check_corroboration("Test content v2", "s2", "api")
        detector.check_corroboration("Test content v3", "s3", "api")
        
        evidence = detector.get_evidence("belief-1")
        proposal = manager.check_and_propose_elevation("belief-1", evidence)
        
        # Should not create proposal due to lack of diversity
        assert proposal is None
        
        # Now add a diverse source
        detector.check_corroboration("Test content v4", "s4", "federation")
        
        evidence = detector.get_evidence("belief-1")
        proposal = manager.check_and_propose_elevation("belief-1", evidence)
        
        # Now should work
        assert proposal is not None


# ============================================================================
# Integration Tests
# ============================================================================

class TestCorroborationElevationIntegration:
    """Integration tests for corroboration and elevation working together."""
    
    def test_end_to_end_flow(self):
        """Test complete flow from belief to elevation."""
        # Setup
        config = CorroborationConfig(
            similarity_threshold=0.3,
            corroboration_threshold=3,
        )
        detector = CorroborationDetector(config=config)
        
        elev_config = AutoElevationConfig(
            enabled=True,
            corroboration_levels={
                3: ElevationLevel.TRUSTED,
            },
            auto_approve=False,
        )
        manager = ElevationManager(
            corroboration_detector=detector,
            config=elev_config,
        )
        
        # Track events
        proposals_created = []
        elevations_done = []
        
        manager.on_proposal_created(lambda p: proposals_created.append(p))
        manager.on_elevation(lambda b, f, t: elevations_done.append((b, f, t)))
        
        # Step 1: Register initial belief
        detector.register_belief(
            "belief-1",
            "Climate change is causing rising sea levels",
            "scientific-paper-1",
            "research",
        )
        
        # Step 2: First corroboration
        result = detector.check_corroboration(
            "Rising sea levels are caused by climate change",
            "news-source-1",
            "journalism",
        )
        
        evidence = detector.get_evidence("belief-1")
        manager.process_corroboration_update("belief-1", evidence)
        
        # No proposal yet (only 2 sources)
        assert len(proposals_created) == 0
        
        # Step 3: Second corroboration
        detector.check_corroboration(
            "Climate change leads to increasing sea levels",
            "govt-report-1",
            "government",
        )
        
        evidence = detector.get_evidence("belief-1")
        manager.process_corroboration_update("belief-1", evidence)
        
        # Now proposal should be created
        assert len(proposals_created) == 1
        assert proposals_created[0].to_level == ElevationLevel.TRUSTED
        
        # Step 4: Approve the proposal
        proposal = proposals_created[0]
        manager.approve_proposal(proposal.proposal_id)
        
        # Elevation should have occurred
        assert len(elevations_done) == 1
        assert elevations_done[0] == (
            "belief-1",
            ElevationLevel.PRIVATE,
            ElevationLevel.TRUSTED,
        )
        
        # Final state check
        state = manager.get_elevation_state("belief-1")
        assert state.current_level == ElevationLevel.TRUSTED
        
        evidence = detector.get_evidence("belief-1")
        assert evidence.status == CorroborationStatus.CORROBORATED
    
    def test_disabled_config_prevents_all(self):
        """Disabled config should prevent all auto-elevation."""
        config = CorroborationConfig(similarity_threshold=0.3, corroboration_threshold=2)
        detector = CorroborationDetector(config=config)
        
        elev_config = AutoElevationConfig(enabled=False)
        manager = ElevationManager(corroboration_detector=detector, config=elev_config)
        
        detector.register_belief("b1", "Test", "s1", "a")
        detector.check_corroboration("Test v2", "s2", "b")
        
        evidence = detector.get_evidence("b1")
        proposal = manager.check_and_propose_elevation("b1", evidence)
        
        assert proposal is None


# ============================================================================
# Module-Level Function Tests
# ============================================================================

class TestModuleFunctions:
    """Tests for module-level convenience functions."""
    
    @pytest.fixture(autouse=True)
    def reset_module_state(self):
        """Reset module-level state before each test."""
        # Reset detector
        corroboration_module._default_detector = None
        elevation_module._default_manager = None
        yield
        # Cleanup
        corroboration_module._default_detector = None
        elevation_module._default_manager = None
    
    def test_register_and_check_corroboration(self):
        """Module functions should work with default detector."""
        register_belief(
            belief_id="mod-belief-1",
            content="Module test content",
            source_id="src-1",
            source_type="test",
        )
        
        assert is_corroborated("mod-belief-1") is False
    
    def test_get_detector_singleton(self):
        """get_detector should return singleton."""
        d1 = get_detector()
        d2 = get_detector()
        
        assert d1 is d2
    
    def test_get_elevation_manager_singleton(self):
        """get_elevation_manager should return singleton."""
        m1 = get_elevation_manager()
        m2 = get_elevation_manager()
        
        assert m1 is m2
