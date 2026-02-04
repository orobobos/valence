# Tests for AI-Assisted Insight Extraction
"""
Test suite for insight extraction from private content.
"""

import pytest
from datetime import datetime, timezone

from valence.privacy.extraction import (
    ExtractionLevel,
    ReviewStatus,
    ExtractionRequest,
    ExtractedInsight,
    MockAIExtractor,
    InsightExtractor,
    extract_insight,
    review_insight,
    get_extractor,
)


class TestExtractionLevel:
    """Tests for extraction level definitions."""
    
    def test_levels_exist(self):
        """All expected extraction levels should exist."""
        assert ExtractionLevel.THEMES
        assert ExtractionLevel.KEY_POINTS
        assert ExtractionLevel.SUMMARY
        assert ExtractionLevel.ANONYMIZED
    
    def test_level_values(self):
        """Level values should be meaningful strings."""
        assert ExtractionLevel.THEMES.value == "themes"
        assert ExtractionLevel.KEY_POINTS.value == "key_points"
        assert ExtractionLevel.SUMMARY.value == "summary"
        assert ExtractionLevel.ANONYMIZED.value == "anonymized"


class TestExtractionRequest:
    """Tests for extraction request creation."""
    
    def test_create_request_with_defaults(self):
        """Should create request with sensible defaults."""
        request = ExtractionRequest.create("Test content")
        
        assert request.request_id is not None
        assert request.content == "Test content"
        assert request.level == ExtractionLevel.KEY_POINTS
        assert request.context is None
    
    def test_create_request_with_options(self):
        """Should accept all options."""
        request = ExtractionRequest.create(
            content="Test content",
            level=ExtractionLevel.SUMMARY,
            context="Meeting notes",
        )
        
        assert request.level == ExtractionLevel.SUMMARY
        assert request.context == "Meeting notes"
    
    def test_unique_request_ids(self):
        """Each request should have a unique ID."""
        r1 = ExtractionRequest.create("Content 1")
        r2 = ExtractionRequest.create("Content 2")
        
        assert r1.request_id != r2.request_id


class TestMockAIExtractor:
    """Tests for the mock AI extractor."""
    
    @pytest.fixture
    def extractor(self):
        return MockAIExtractor()
    
    def test_extract_themes(self, extractor):
        """Should extract themes from content."""
        content = "Working on the project deadline. Need to fix a bug."
        result, confidence = extractor.extract(content, ExtractionLevel.THEMES)
        
        assert "Themes:" in result
        assert confidence > 0
        assert confidence <= 1.0
    
    def test_extract_key_points(self, extractor):
        """Should extract key points as bullets."""
        content = "First important point here. Second major idea follows. Third conclusion."
        result, confidence = extractor.extract(content, ExtractionLevel.KEY_POINTS)
        
        assert "•" in result
        assert confidence > 0
    
    def test_extract_summary(self, extractor):
        """Should produce a summary."""
        content = "This is a longer piece of content with many words."
        result, confidence = extractor.extract(content, ExtractionLevel.SUMMARY)
        
        assert "Summary:" in result
        assert confidence > 0
    
    def test_anonymize_emails(self, extractor):
        """Should redact email addresses."""
        content = "Contact john@example.com for details."
        result, confidence = extractor.extract(content, ExtractionLevel.ANONYMIZED)
        
        assert "john@example.com" not in result
        assert "[EMAIL]" in result
    
    def test_anonymize_phone_numbers(self, extractor):
        """Should redact phone numbers."""
        content = "Call me at 555-123-4567."
        result, confidence = extractor.extract(content, ExtractionLevel.ANONYMIZED)
        
        assert "555-123-4567" not in result
        assert "[PHONE]" in result
    
    def test_anonymize_dates(self, extractor):
        """Should redact dates."""
        content = "Meeting scheduled for 12/25/2024."
        result, confidence = extractor.extract(content, ExtractionLevel.ANONYMIZED)
        
        assert "12/25/2024" not in result
        assert "[DATE]" in result


class TestExtractedInsight:
    """Tests for extracted insight dataclass."""
    
    @pytest.fixture
    def insight(self):
        return ExtractedInsight(
            insight_id="test-insight-1",
            request_id="test-request-1",
            level=ExtractionLevel.KEY_POINTS,
            content="• Key point 1\n• Key point 2",
            source_hash="abc123",
            extraction_method="mock-extractor-v1",
            confidence=0.85,
        )
    
    def test_initial_status_is_pending(self, insight):
        """New insights should be pending review."""
        assert insight.review_status == ReviewStatus.PENDING
        assert not insight.is_shareable
    
    def test_is_shareable_when_approved(self, insight):
        """Approved insights should be shareable."""
        insight.review_status = ReviewStatus.APPROVED
        assert insight.is_shareable
    
    def test_is_shareable_when_modified(self, insight):
        """Modified insights should be shareable."""
        insight.review_status = ReviewStatus.MODIFIED
        assert insight.is_shareable
    
    def test_not_shareable_when_rejected(self, insight):
        """Rejected insights should not be shareable."""
        insight.review_status = ReviewStatus.REJECTED
        assert not insight.is_shareable
    
    def test_provenance_includes_safe_fields(self, insight):
        """Provenance should include safe metadata."""
        prov = insight.provenance
        
        assert prov["insight_id"] == insight.insight_id
        assert prov["extraction_level"] == "key_points"
        assert prov["source_hash"] == "abc123"
        assert "extracted_at" in prov
    
    def test_to_dict_excludes_private_by_default(self, insight):
        """to_dict should exclude private fields by default."""
        insight._original_content_ref = "secret-ref"
        data = insight.to_dict()
        
        assert "_original_ref" not in data
    
    def test_to_dict_includes_private_when_requested(self, insight):
        """to_dict should include private fields when requested."""
        insight._original_content_ref = "secret-ref"
        data = insight.to_dict(include_private=True)
        
        assert data["_original_ref"] == "secret-ref"


class TestInsightExtractor:
    """Tests for the main InsightExtractor service."""
    
    @pytest.fixture
    def extractor(self):
        return InsightExtractor(require_review=True)
    
    @pytest.fixture
    def private_content(self):
        return """
        Meeting Notes - Q3 Planning
        
        Attendees: John Smith, Alice Johnson
        Date: 12/15/2024
        
        Discussion points:
        1. Budget allocation for new project
        2. Team expansion - need 3 more engineers
        3. Timeline concerns - deadline moved to March
        
        Action items:
        - John to prepare budget proposal
        - Alice to start recruiting process
        
        Contact: john.smith@company.com
        """
    
    def test_extract_creates_insight(self, extractor, private_content):
        """Extraction should create an ExtractedInsight."""
        insight = extractor.extract(private_content, ExtractionLevel.KEY_POINTS)
        
        assert insight.insight_id is not None
        assert insight.level == ExtractionLevel.KEY_POINTS
        assert insight.content  # Non-empty
        assert insight.source_hash  # Hash present
    
    def test_extract_preserves_source_hash(self, extractor, private_content):
        """Same content should produce same source hash."""
        insight1 = extractor.extract(private_content, ExtractionLevel.KEY_POINTS)
        insight2 = extractor.extract(private_content, ExtractionLevel.SUMMARY)
        
        assert insight1.source_hash == insight2.source_hash
    
    def test_extract_different_content_different_hash(self, extractor):
        """Different content should produce different hashes."""
        insight1 = extractor.extract("Content A", ExtractionLevel.SUMMARY)
        insight2 = extractor.extract("Content B", ExtractionLevel.SUMMARY)
        
        assert insight1.source_hash != insight2.source_hash
    
    def test_extract_pending_review_by_default(self, extractor, private_content):
        """Extracted insights should be pending review."""
        insight = extractor.extract(private_content)
        
        assert insight.review_status == ReviewStatus.PENDING
        assert not insight.is_shareable
    
    def test_review_approve(self, extractor, private_content):
        """Should be able to approve an insight."""
        insight = extractor.extract(private_content)
        
        reviewed = extractor.review(
            insight_id=insight.insight_id,
            approved=True,
            reviewer_id="reviewer-1",
        )
        
        assert reviewed.review_status == ReviewStatus.APPROVED
        assert reviewed.is_shareable
        assert reviewed.reviewer_id == "reviewer-1"
        assert reviewed.reviewed_at is not None
    
    def test_review_reject(self, extractor, private_content):
        """Should be able to reject an insight."""
        insight = extractor.extract(private_content)
        
        reviewed = extractor.review(
            insight_id=insight.insight_id,
            approved=False,
            reviewer_id="reviewer-1",
            notes="Contains sensitive information",
        )
        
        assert reviewed.review_status == ReviewStatus.REJECTED
        assert not reviewed.is_shareable
        assert reviewed.review_notes == "Contains sensitive information"
    
    def test_review_modify(self, extractor, private_content):
        """Should be able to modify insight during review."""
        insight = extractor.extract(private_content)
        
        reviewed = extractor.review(
            insight_id=insight.insight_id,
            approved=True,
            reviewer_id="reviewer-1",
            modified_content="Edited key points without sensitive data",
        )
        
        assert reviewed.review_status == ReviewStatus.MODIFIED
        assert reviewed.is_shareable
        assert reviewed.content == "Edited key points without sensitive data"
    
    def test_cannot_review_twice(self, extractor, private_content):
        """Should not be able to review an already-reviewed insight."""
        insight = extractor.extract(private_content)
        extractor.review(insight.insight_id, True, "reviewer-1")
        
        with pytest.raises(ValueError, match="already reviewed"):
            extractor.review(insight.insight_id, True, "reviewer-2")
    
    def test_get_insight_not_found(self, extractor):
        """Should return None for non-existent insight."""
        result = extractor.get_insight("non-existent-id")
        assert result is None
    
    def test_get_insight_requires_shareable_for_public(self, extractor, private_content):
        """Non-owners should only see shareable insights."""
        insight = extractor.extract(private_content)
        
        # Before review - not shareable
        result = extractor.get_insight(insight.insight_id, include_private=False)
        assert result is None
        
        # After approval - shareable
        extractor.review(insight.insight_id, True, "reviewer-1")
        result = extractor.get_insight(insight.insight_id, include_private=False)
        assert result is not None
    
    def test_get_original_content_owner_only(self, extractor, private_content):
        """Only owner should be able to get original content."""
        insight = extractor.extract(
            private_content,
            owner_id="owner-1",
        )
        
        # Owner can access
        content = extractor.get_original_content(insight.insight_id, "owner-1")
        assert content == private_content
        
        # Non-owner cannot
        content = extractor.get_original_content(insight.insight_id, "other-user")
        assert content is None
    
    def test_list_pending_reviews(self, extractor, private_content):
        """Should list all pending reviews."""
        insight1 = extractor.extract(private_content)
        insight2 = extractor.extract("Other content")
        extractor.review(insight2.insight_id, True, "reviewer-1")
        
        pending = extractor.list_pending_reviews()
        
        assert len(pending) == 1
        assert pending[0].insight_id == insight1.insight_id
    
    def test_list_shareable(self, extractor, private_content):
        """Should list all shareable insights."""
        insight1 = extractor.extract(private_content)
        insight2 = extractor.extract("Other content")
        extractor.review(insight1.insight_id, True, "reviewer-1")
        extractor.review(insight2.insight_id, False, "reviewer-1")
        
        shareable = extractor.list_shareable()
        
        assert len(shareable) == 1
        assert shareable[0].insight_id == insight1.insight_id
    
    def test_verify_provenance(self, extractor, private_content):
        """Should verify provenance with correct hash."""
        import hashlib
        
        insight = extractor.extract(private_content)
        expected_hash = hashlib.sha256(private_content.encode()).hexdigest()[:16]
        
        assert extractor.verify_provenance(insight.insight_id, expected_hash)
        assert not extractor.verify_provenance(insight.insight_id, "wrong-hash")
    
    def test_review_callback_fired(self, extractor, private_content):
        """Review callback should be invoked."""
        callbacks_received = []
        extractor.add_review_callback(lambda i: callbacks_received.append(i))
        
        insight = extractor.extract(private_content)
        extractor.review(insight.insight_id, True, "reviewer-1")
        
        assert len(callbacks_received) == 1
        assert callbacks_received[0].insight_id == insight.insight_id


class TestHighLevelAPI:
    """Tests for the high-level extraction API."""
    
    def test_extract_insight_function(self):
        """extract_insight should work with default extractor."""
        # Reset global extractor
        import valence.privacy.extraction as extraction_module
        extraction_module._default_extractor = InsightExtractor()
        
        insight = extract_insight(
            content="Important project update with key details.",
            level=ExtractionLevel.KEY_POINTS,
            owner_id="test-owner",
        )
        
        assert insight.insight_id is not None
        assert insight.level == ExtractionLevel.KEY_POINTS
        assert insight.review_status == ReviewStatus.PENDING
    
    def test_review_insight_function(self):
        """review_insight should work with default extractor."""
        import valence.privacy.extraction as extraction_module
        extraction_module._default_extractor = InsightExtractor()
        
        insight = extract_insight("Test content", owner_id="owner")
        reviewed = review_insight(
            insight_id=insight.insight_id,
            approved=True,
            reviewer_id="reviewer",
        )
        
        assert reviewed.is_shareable


class TestExtractionLevelBehavior:
    """Tests for different extraction level behaviors."""
    
    @pytest.fixture
    def extractor(self):
        return InsightExtractor()
    
    @pytest.fixture
    def detailed_content(self):
        return """
        Project Status Report
        
        The Q4 marketing campaign reached 1.2M impressions.
        John Smith led the team of 5 engineers.
        Budget: $50,000 spent of $75,000 allocated.
        
        Key achievements:
        - Launched new product line
        - Expanded to 3 new markets
        - Customer satisfaction up 15%
        
        Contact: john.smith@company.com
        Phone: 555-123-4567
        """
    
    def test_themes_extracts_high_level(self, extractor, detailed_content):
        """THEMES should extract only high-level topics."""
        insight = extractor.extract(detailed_content, ExtractionLevel.THEMES)
        
        # Should have themes, not specific details
        assert "Themes:" in insight.content
        # Specific numbers shouldn't be in themes
        assert "1.2M" not in insight.content
        assert "$50,000" not in insight.content
    
    def test_key_points_extracts_bullets(self, extractor, detailed_content):
        """KEY_POINTS should extract bullet points."""
        insight = extractor.extract(detailed_content, ExtractionLevel.KEY_POINTS)
        
        assert "•" in insight.content
    
    def test_summary_is_concise(self, extractor, detailed_content):
        """SUMMARY should be more concise than original."""
        insight = extractor.extract(detailed_content, ExtractionLevel.SUMMARY)
        
        # Summary should be shorter
        assert len(insight.content) < len(detailed_content)
        assert "Summary:" in insight.content
    
    def test_anonymized_removes_pii(self, extractor, detailed_content):
        """ANONYMIZED should remove all PII."""
        insight = extractor.extract(detailed_content, ExtractionLevel.ANONYMIZED)
        
        # PII should be redacted
        assert "john.smith@company.com" not in insight.content
        assert "555-123-4567" not in insight.content
        assert "[EMAIL]" in insight.content
        assert "[PHONE]" in insight.content


class TestProvenanceTracking:
    """Tests for provenance ("extracted from") relationship."""
    
    @pytest.fixture
    def extractor(self):
        return InsightExtractor()
    
    def test_provenance_links_to_source(self, extractor):
        """Provenance should link insight to source via hash."""
        content = "Original sensitive content"
        insight = extractor.extract(content)
        
        # Provenance should have source hash
        assert "source_hash" in insight.provenance
        assert len(insight.provenance["source_hash"]) == 16
    
    def test_provenance_verifiable(self, extractor):
        """Provenance should be verifiable without exposing content."""
        import hashlib
        
        content = "Secret document contents"
        insight = extractor.extract(content)
        
        # External party can verify they have the original
        claimed_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        assert extractor.verify_provenance(insight.insight_id, claimed_hash)
    
    def test_provenance_not_reversible(self, extractor):
        """Source hash should not reveal original content."""
        content = "Confidential information"
        insight = extractor.extract(content)
        
        # Hash is one-way - can't derive content from it
        # (This is a design assertion, not a functional test)
        assert insight.provenance["source_hash"] != content
        assert len(insight.provenance["source_hash"]) == 16
    
    def test_multiple_insights_same_provenance(self, extractor):
        """Multiple extractions from same source share provenance hash."""
        content = "Same source document"
        
        insight1 = extractor.extract(content, ExtractionLevel.THEMES)
        insight2 = extractor.extract(content, ExtractionLevel.KEY_POINTS)
        insight3 = extractor.extract(content, ExtractionLevel.SUMMARY)
        
        # All should have same source hash
        assert insight1.source_hash == insight2.source_hash
        assert insight2.source_hash == insight3.source_hash
        
        # But different insight IDs
        assert insight1.insight_id != insight2.insight_id
        assert insight2.insight_id != insight3.insight_id
