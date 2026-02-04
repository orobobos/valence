# Tests for Privacy Elevation Workflow
"""
Test suite for elevation workflow and integration with AI insight extraction.
"""

import pytest
from datetime import datetime, timezone

from valence.privacy.elevation import (
    ElevationLevel,
    ElevationTrigger,
    ProposalStatus,
    ElevationProposal,
    BeliefElevationState,
    AutoElevationConfig,
    ElevationManager,
    get_elevation_manager,
    approve_elevation,
    reject_elevation,
    opt_out_auto_elevation,
    opt_in_auto_elevation,
)
from valence.privacy.extraction import (
    ExtractionLevel,
    ReviewStatus,
    InsightExtractor,
    ExtractedInsight,
)
from valence.privacy.corroboration import (
    CorroborationDetector,
    CorroborationEvidence,
    CorroborationStatus,
    SourceInfo,
)


class TestElevationLevel:
    """Tests for elevation level definitions."""
    
    def test_levels_exist(self):
        """All expected elevation levels should exist."""
        assert ElevationLevel.PRIVATE
        assert ElevationLevel.TRUSTED
        assert ElevationLevel.COMMUNITY
        assert ElevationLevel.PUBLIC
    
    def test_level_ordering(self):
        """Levels should have meaningful string values."""
        assert ElevationLevel.PRIVATE.value == "private"
        assert ElevationLevel.TRUSTED.value == "trusted"
        assert ElevationLevel.COMMUNITY.value == "community"
        assert ElevationLevel.PUBLIC.value == "public"


class TestElevationProposal:
    """Tests for elevation proposal dataclass."""
    
    @pytest.fixture
    def proposal(self):
        return ElevationProposal(
            proposal_id="prop-1",
            belief_id="belief-1",
            from_level=ElevationLevel.PRIVATE,
            to_level=ElevationLevel.TRUSTED,
            trigger=ElevationTrigger.CORROBORATION,
        )
    
    def test_initial_status_is_pending(self, proposal):
        """New proposals should be pending."""
        assert proposal.status == ProposalStatus.PENDING
    
    def test_to_dict(self, proposal):
        """Should serialize to dictionary."""
        data = proposal.to_dict()
        
        assert data["proposal_id"] == "prop-1"
        assert data["from_level"] == "private"
        assert data["to_level"] == "trusted"
        assert data["trigger"] == "corroboration"
        assert data["status"] == "pending"


class TestBeliefElevationState:
    """Tests for belief elevation state tracking."""
    
    @pytest.fixture
    def state(self):
        return BeliefElevationState(belief_id="belief-1")
    
    def test_initial_level_is_private(self, state):
        """New beliefs should be private."""
        assert state.current_level == ElevationLevel.PRIVATE
    
    def test_auto_elevate_enabled_by_default(self, state):
        """Auto-elevation should be enabled by default."""
        assert state.auto_elevate_enabled is True
    
    def test_record_elevation(self, state):
        """Should record elevation history."""
        state.record_elevation(
            from_level=ElevationLevel.PRIVATE,
            to_level=ElevationLevel.TRUSTED,
            trigger=ElevationTrigger.CORROBORATION,
            reason="3 sources confirmed",
        )
        
        assert state.current_level == ElevationLevel.TRUSTED
        assert len(state.elevation_history) == 1
        assert state.elevation_history[0]["from_level"] == "private"
        assert state.elevation_history[0]["to_level"] == "trusted"


class TestElevationManager:
    """Tests for the ElevationManager service."""
    
    @pytest.fixture
    def manager(self):
        """Create manager with mock corroboration detector."""
        return ElevationManager(
            config=AutoElevationConfig(
                enabled=True,
                auto_approve=False,
                corroboration_levels={
                    3: ElevationLevel.TRUSTED,
                    5: ElevationLevel.COMMUNITY,
                },
            )
        )
    
    def test_get_or_create_state(self, manager):
        """Should create state on first access."""
        state = manager.get_or_create_state("belief-1")
        
        assert state.belief_id == "belief-1"
        assert state.current_level == ElevationLevel.PRIVATE
    
    def test_opt_out(self, manager):
        """Should be able to opt out of auto-elevation."""
        manager.opt_out("belief-1", "Privacy concerns")
        
        assert manager.is_opted_out("belief-1")
        state = manager.get_elevation_state("belief-1")
        assert state.opt_out_reason == "Privacy concerns"
    
    def test_opt_in(self, manager):
        """Should be able to opt back in."""
        manager.opt_out("belief-1")
        manager.opt_in("belief-1")
        
        assert not manager.is_opted_out("belief-1")
    
    def test_manual_elevation(self, manager):
        """Should be able to elevate manually."""
        state = manager.elevate_manually(
            belief_id="belief-1",
            to_level=ElevationLevel.TRUSTED,
            reason="Owner requested",
        )
        
        assert state.current_level == ElevationLevel.TRUSTED
        assert len(state.elevation_history) == 1
        assert state.elevation_history[0]["trigger"] == "manual"
    
    def test_approve_proposal(self, manager):
        """Should be able to approve proposals."""
        # Create a proposal directly for testing
        proposal = ElevationProposal(
            proposal_id="prop-1",
            belief_id="belief-1",
            from_level=ElevationLevel.PRIVATE,
            to_level=ElevationLevel.TRUSTED,
            trigger=ElevationTrigger.CORROBORATION,
        )
        manager._proposals["prop-1"] = proposal
        
        approved = manager.approve_proposal("prop-1", "Looks good")
        
        assert approved.status == ProposalStatus.APPROVED
        assert approved.decision_reason == "Looks good"
        
        # State should be updated
        state = manager.get_elevation_state("belief-1")
        assert state.current_level == ElevationLevel.TRUSTED
    
    def test_reject_proposal(self, manager):
        """Should be able to reject proposals."""
        proposal = ElevationProposal(
            proposal_id="prop-1",
            belief_id="belief-1",
            from_level=ElevationLevel.PRIVATE,
            to_level=ElevationLevel.TRUSTED,
            trigger=ElevationTrigger.CORROBORATION,
        )
        manager._proposals["prop-1"] = proposal
        
        rejected = manager.reject_proposal("prop-1", "Not ready")
        
        assert rejected.status == ProposalStatus.REJECTED
        assert rejected.decision_reason == "Not ready"
        
        # State should NOT be updated
        state = manager.get_or_create_state("belief-1")
        assert state.current_level == ElevationLevel.PRIVATE
    
    def test_get_pending_proposals(self, manager):
        """Should list pending proposals."""
        # Create mixed proposals
        prop1 = ElevationProposal(
            proposal_id="prop-1",
            belief_id="belief-1",
            from_level=ElevationLevel.PRIVATE,
            to_level=ElevationLevel.TRUSTED,
            trigger=ElevationTrigger.CORROBORATION,
        )
        prop2 = ElevationProposal(
            proposal_id="prop-2",
            belief_id="belief-2",
            from_level=ElevationLevel.PRIVATE,
            to_level=ElevationLevel.TRUSTED,
            trigger=ElevationTrigger.CORROBORATION,
            status=ProposalStatus.APPROVED,
        )
        manager._proposals["prop-1"] = prop1
        manager._proposals["prop-2"] = prop2
        
        pending = manager.get_pending_proposals()
        
        assert len(pending) == 1
        assert pending[0].proposal_id == "prop-1"
    
    def test_elevation_callback_fired(self, manager):
        """Elevation callback should be invoked."""
        callbacks = []
        manager.on_elevation(lambda bid, f, t: callbacks.append((bid, f, t)))
        
        manager.elevate_manually("belief-1", ElevationLevel.TRUSTED)
        
        assert len(callbacks) == 1
        assert callbacks[0] == ("belief-1", ElevationLevel.PRIVATE, ElevationLevel.TRUSTED)


class TestHighLevelElevationAPI:
    """Tests for the high-level elevation API."""
    
    def test_opt_out_function(self):
        """opt_out_auto_elevation should work."""
        import valence.privacy.elevation as elevation_module
        elevation_module._default_manager = ElevationManager()
        
        result = opt_out_auto_elevation("belief-1", "Test reason")
        
        assert result is True
        assert get_elevation_manager().is_opted_out("belief-1")
    
    def test_opt_in_function(self):
        """opt_in_auto_elevation should work."""
        import valence.privacy.elevation as elevation_module
        elevation_module._default_manager = ElevationManager()
        
        opt_out_auto_elevation("belief-1")
        opt_in_auto_elevation("belief-1")
        
        assert not get_elevation_manager().is_opted_out("belief-1")


class TestExtractionElevationIntegration:
    """
    Tests for integration between AI insight extraction and elevation.
    
    Key scenarios:
    1. Extract insight from private content
    2. Review and approve insight
    3. Elevate approved insight through visibility levels
    """
    
    @pytest.fixture
    def extractor(self):
        return InsightExtractor(require_review=True)
    
    @pytest.fixture
    def elevation_manager(self):
        return ElevationManager(
            config=AutoElevationConfig(
                enabled=True,
                auto_approve=False,
            )
        )
    
    @pytest.fixture
    def private_content(self):
        return """
        Internal Project Update
        
        Contact: john@company.com
        Phone: 555-123-4567
        
        Key milestones:
        - Completed phase 1 development
        - Budget on track at $50,000
        - Team expanding to 8 engineers
        """
    
    def test_workflow_extract_then_elevate(
        self,
        extractor,
        elevation_manager,
        private_content,
    ):
        """
        Full workflow: private content -> extraction -> review -> elevation.
        """
        # Step 1: Extract insight from private content
        insight = extractor.extract(
            content=private_content,
            level=ExtractionLevel.KEY_POINTS,
            owner_id="owner-1",
        )
        
        assert insight.review_status == ReviewStatus.PENDING
        assert not insight.is_shareable
        
        # Step 2: Review and approve insight
        reviewed = extractor.review(
            insight_id=insight.insight_id,
            approved=True,
            reviewer_id="reviewer-1",
        )
        
        assert reviewed.is_shareable
        
        # Step 3: Track insight in elevation system (as a "belief")
        state = elevation_manager.get_or_create_state(insight.insight_id)
        assert state.current_level == ElevationLevel.PRIVATE
        
        # Step 4: Elevate the insight (manually, as it's now safe to share)
        elevated = elevation_manager.elevate_manually(
            belief_id=insight.insight_id,
            to_level=ElevationLevel.TRUSTED,
            reason="Approved insight ready for trusted network",
        )
        
        assert elevated.current_level == ElevationLevel.TRUSTED
        assert len(elevated.elevation_history) == 1
    
    def test_extraction_anonymization_enables_elevation(
        self,
        extractor,
        elevation_manager,
        private_content,
    ):
        """
        Anonymized extraction removes PII, making elevation safer.
        """
        # Extract with anonymization
        insight = extractor.extract(
            content=private_content,
            level=ExtractionLevel.ANONYMIZED,
            owner_id="owner-1",
        )
        
        # PII should be removed
        assert "john@company.com" not in insight.content
        assert "555-123-4567" not in insight.content
        
        # After review, this can be elevated more widely
        extractor.review(insight.insight_id, True, "reviewer-1")
        
        # Elevate to community level (safe because PII removed)
        elevated = elevation_manager.elevate_manually(
            belief_id=insight.insight_id,
            to_level=ElevationLevel.COMMUNITY,
            reason="Anonymized content safe for community",
        )
        
        assert elevated.current_level == ElevationLevel.COMMUNITY
    
    def test_owner_retains_original_access(
        self,
        extractor,
        private_content,
    ):
        """
        After extraction and elevation, owner still has original.
        """
        insight = extractor.extract(
            content=private_content,
            level=ExtractionLevel.KEY_POINTS,
            owner_id="owner-1",
        )
        
        # Owner can still access original
        original = extractor.get_original_content(
            insight.insight_id,
            owner_id="owner-1",
        )
        
        assert original == private_content
        
        # Non-owner cannot
        original_for_other = extractor.get_original_content(
            insight.insight_id,
            owner_id="other-user",
        )
        
        assert original_for_other is None
    
    def test_provenance_tracks_extraction(
        self,
        extractor,
        private_content,
    ):
        """
        Provenance should track that insight was extracted from source.
        """
        import hashlib
        
        insight = extractor.extract(
            content=private_content,
            level=ExtractionLevel.SUMMARY,
            owner_id="owner-1",
        )
        
        # Provenance shows extraction info
        prov = insight.provenance
        
        assert prov["extraction_level"] == "summary"
        assert prov["extraction_method"] == "mock-extractor-v1"
        
        # Source hash can verify origin
        expected_hash = hashlib.sha256(private_content.encode()).hexdigest()[:16]
        assert prov["source_hash"] == expected_hash
        
        # Verification works
        assert extractor.verify_provenance(insight.insight_id, expected_hash)
    
    def test_rejected_insight_not_elevated(
        self,
        extractor,
        elevation_manager,
        private_content,
    ):
        """
        Rejected insights should not be elevated.
        """
        insight = extractor.extract(
            content=private_content,
            level=ExtractionLevel.KEY_POINTS,
            owner_id="owner-1",
        )
        
        # Reject the insight
        extractor.review(
            insight_id=insight.insight_id,
            approved=False,
            reviewer_id="reviewer-1",
            notes="Contains sensitive information",
        )
        
        assert not insight.is_shareable
        
        # Should not elevate (in real system, would check shareability)
        # This demonstrates the pattern: check shareability before elevation
        if insight.is_shareable:
            elevation_manager.elevate_manually(
                belief_id=insight.insight_id,
                to_level=ElevationLevel.TRUSTED,
            )
        
        # Insight remains at private level (no elevation occurred)
        state = elevation_manager.get_or_create_state(insight.insight_id)
        assert state.current_level == ElevationLevel.PRIVATE
    
    def test_different_extraction_levels_for_different_audiences(
        self,
        extractor,
        private_content,
    ):
        """
        Can extract at different levels for different audiences.
        """
        # Themes for public
        themes = extractor.extract(
            content=private_content,
            level=ExtractionLevel.THEMES,
            owner_id="owner-1",
        )
        
        # Key points for trusted
        key_points = extractor.extract(
            content=private_content,
            level=ExtractionLevel.KEY_POINTS,
            owner_id="owner-1",
        )
        
        # Both from same source
        assert themes.source_hash == key_points.source_hash
        
        # But different detail levels
        assert "Themes:" in themes.content
        assert "•" in key_points.content
        
        # Themes is safer for wider distribution
        assert len(themes.content) < len(key_points.content)


class TestAuditTrail:
    """Tests for audit trail completeness."""
    
    @pytest.fixture
    def manager(self):
        return ElevationManager()
    
    def test_elevation_history_preserved(self, manager):
        """Elevation history should be preserved."""
        # Multiple elevations
        manager.elevate_manually("belief-1", ElevationLevel.TRUSTED, "Initial share")
        manager.elevate_manually("belief-1", ElevationLevel.COMMUNITY, "Wider share")
        
        state = manager.get_elevation_state("belief-1")
        
        assert len(state.elevation_history) == 2
        assert state.elevation_history[0]["to_level"] == "trusted"
        assert state.elevation_history[1]["to_level"] == "community"
    
    def test_history_includes_timestamps(self, manager):
        """History entries should have timestamps."""
        manager.elevate_manually("belief-1", ElevationLevel.TRUSTED)
        
        state = manager.get_elevation_state("belief-1")
        
        assert "elevated_at" in state.elevation_history[0]
        # Should be parseable as ISO datetime
        datetime.fromisoformat(state.elevation_history[0]["elevated_at"].replace("Z", "+00:00"))
    
    def test_history_includes_trigger(self, manager):
        """History should track what triggered elevation."""
        manager.elevate_manually("belief-1", ElevationLevel.TRUSTED)
        
        state = manager.get_elevation_state("belief-1")
        
        assert state.elevation_history[0]["trigger"] == "manual"
