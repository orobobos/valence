"""Comprehensive tests for valence.core.external_sources module.

Tests cover:
- Source categories and enums
- Trusted source registry
- Liveness checking
- Content matching
- Reliability scoring
- L4 elevation requirements
- Full verification workflow
- Edge cases and error handling

Per THREAT-MODEL.md §1.4.2, external source verification is critical
for preventing independence oracle manipulation in L4 elevation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest

from valence.core.external_sources import (
    # Constants
    ExternalSourceConstants,
    # Enums
    SourceCategory,
    SourceVerificationStatus,
    DOIStatus,
    SourceLivenessStatus,
    # Registry
    TrustedDomain,
    DOIPrefix,
    TrustedSourceRegistry,
    get_registry,
    # Results
    LivenessCheckResult,
    ContentMatchResult,
    DOIVerificationResult,
    SourceReliabilityScore,
    # Main models
    ExternalSourceVerification,
    L4SourceRequirements,
    # Service
    ExternalSourceVerificationService,
    # Convenience functions
    verify_external_source,
    check_belief_l4_readiness,
)


# ============================================================================
# Source Category Tests
# ============================================================================

class TestSourceCategory:
    """Tests for SourceCategory enum."""
    
    def test_all_categories_exist(self):
        """Verify all expected categories are defined."""
        expected = {
            "ACADEMIC_JOURNAL", "ACADEMIC_PREPRINT", "GOVERNMENT",
            "NEWS_MAJOR", "NEWS_REGIONAL", "ENCYCLOPEDIA",
            "TECHNICAL_DOCS", "SOCIAL_VERIFIED", "CORPORATE",
            "PERSONAL_BLOG", "UNKNOWN"
        }
        actual = {c.name for c in SourceCategory}
        assert actual == expected
    
    def test_base_reliability_ordering(self):
        """Academic sources should be more reliable than personal blogs."""
        assert SourceCategory.ACADEMIC_JOURNAL.base_reliability > SourceCategory.PERSONAL_BLOG.base_reliability
        assert SourceCategory.GOVERNMENT.base_reliability > SourceCategory.UNKNOWN.base_reliability
        assert SourceCategory.TECHNICAL_DOCS.base_reliability > SourceCategory.CORPORATE.base_reliability
    
    def test_all_categories_have_reliability(self):
        """Every category should have a base reliability score."""
        for category in SourceCategory:
            assert 0.0 <= category.base_reliability <= 1.0
    
    def test_academic_journal_highest_reliability(self):
        """Academic journals should have highest reliability."""
        assert SourceCategory.ACADEMIC_JOURNAL.base_reliability == 0.90
        for category in SourceCategory:
            assert category.base_reliability <= SourceCategory.ACADEMIC_JOURNAL.base_reliability


class TestSourceVerificationStatus:
    """Tests for SourceVerificationStatus enum."""
    
    def test_all_statuses_exist(self):
        expected = {
            "PENDING", "VERIFIED", "FAILED_LIVENESS", "FAILED_CONTENT",
            "FAILED_RELIABILITY", "EXPIRED", "BLOCKED"
        }
        actual = {s.name for s in SourceVerificationStatus}
        assert actual == expected
    
    def test_failure_statuses(self):
        """Verify failure statuses have consistent naming."""
        failure_statuses = [s for s in SourceVerificationStatus if s.value.startswith("failed")]
        assert len(failure_statuses) == 3


# ============================================================================
# Trusted Domain Tests
# ============================================================================

class TestTrustedDomain:
    """Tests for TrustedDomain data class."""
    
    def test_create_basic_domain(self):
        """Create a basic trusted domain."""
        domain = TrustedDomain(
            domain="example.com",
            category=SourceCategory.NEWS_MAJOR
        )
        assert domain.domain == "example.com"
        assert domain.category == SourceCategory.NEWS_MAJOR
        assert domain.reliability == SourceCategory.NEWS_MAJOR.base_reliability
    
    def test_reliability_override(self):
        """Reliability override should take precedence."""
        domain = TrustedDomain(
            domain="special.com",
            category=SourceCategory.UNKNOWN,
            reliability_override=0.95
        )
        assert domain.reliability == 0.95
    
    def test_matches_exact_url(self):
        """URL matching for exact domain."""
        domain = TrustedDomain(
            domain="nature.com",
            category=SourceCategory.ACADEMIC_JOURNAL
        )
        assert domain.matches_url("https://nature.com/articles/123")
        assert domain.matches_url("https://www.nature.com/articles/123")
        assert not domain.matches_url("https://fakenature.com/articles")
    
    def test_https_requirement(self):
        """HTTPS requirement should block HTTP URLs."""
        domain = TrustedDomain(
            domain="secure.com",
            category=SourceCategory.GOVERNMENT,
            require_https=True
        )
        assert domain.matches_url("https://secure.com/page")
        assert not domain.matches_url("http://secure.com/page")
    
    def test_allowed_paths(self):
        """Only allowed paths should match."""
        domain = TrustedDomain(
            domain="example.com",
            category=SourceCategory.NEWS_MAJOR,
            allowed_paths=[r"^/news/.*", r"^/articles/.*"]
        )
        assert domain.matches_url("https://example.com/news/story")
        assert domain.matches_url("https://example.com/articles/123")
        assert not domain.matches_url("https://example.com/ads/spam")
    
    def test_blocked_paths(self):
        """Blocked paths should not match."""
        domain = TrustedDomain(
            domain="example.com",
            category=SourceCategory.NEWS_MAJOR,
            blocked_paths=[r"^/sponsored/.*", r"^/ads/.*"]
        )
        assert domain.matches_url("https://example.com/news/story")
        assert not domain.matches_url("https://example.com/sponsored/content")
        assert not domain.matches_url("https://example.com/ads/banner")
    
    def test_to_dict(self):
        """Serialization to dictionary."""
        domain = TrustedDomain(
            domain="test.com",
            category=SourceCategory.TECHNICAL_DOCS,
            notes="Test domain"
        )
        d = domain.to_dict()
        assert d["domain"] == "test.com"
        assert d["category"] == "technical_docs"
        assert d["notes"] == "Test domain"


class TestDOIPrefix:
    """Tests for DOIPrefix data class."""
    
    def test_create_prefix(self):
        prefix = DOIPrefix(
            prefix="10.1038",
            publisher="Nature Publishing Group"
        )
        assert prefix.prefix == "10.1038"
        assert prefix.publisher == "Nature Publishing Group"
        assert prefix.category == SourceCategory.ACADEMIC_JOURNAL
    
    def test_preprint_category(self):
        prefix = DOIPrefix(
            prefix="10.48550",
            publisher="arXiv",
            category=SourceCategory.ACADEMIC_PREPRINT
        )
        assert prefix.reliability == SourceCategory.ACADEMIC_PREPRINT.base_reliability


# ============================================================================
# Trusted Source Registry Tests
# ============================================================================

class TestTrustedSourceRegistry:
    """Tests for TrustedSourceRegistry."""
    
    @pytest.fixture
    def registry(self):
        """Fresh registry for each test."""
        return TrustedSourceRegistry()
    
    def test_default_domains_loaded(self, registry):
        """Default trusted domains should be loaded."""
        # Check some expected defaults
        assert registry.get_domain_info("https://arxiv.org/abs/1234") is not None
        assert registry.get_domain_info("https://pubmed.ncbi.nlm.nih.gov/123") is not None
    
    def test_default_doi_prefixes_loaded(self, registry):
        """Default DOI prefixes should be loaded."""
        assert registry.get_doi_prefix_info("10.1038/nature12345") is not None
        assert registry.get_doi_prefix_info("10.1126/science.abc") is not None
    
    def test_register_custom_domain(self, registry):
        """Register a custom trusted domain."""
        registry.register_domain(TrustedDomain(
            domain="custom.org",
            category=SourceCategory.TECHNICAL_DOCS
        ))
        info = registry.get_domain_info("https://custom.org/spec")
        assert info is not None
        assert info.category == SourceCategory.TECHNICAL_DOCS
    
    def test_unregister_domain(self, registry):
        """Remove a domain from registry."""
        registry.register_domain(TrustedDomain(
            domain="temp.com",
            category=SourceCategory.UNKNOWN
        ))
        assert registry.get_domain_info("https://temp.com/page") is not None
        
        assert registry.unregister_domain("temp.com")
        assert registry.get_domain_info("https://temp.com/page") is None
    
    def test_blocklist(self, registry):
        """Blocklisted domains should be flagged."""
        registry.add_to_blocklist("malicious.com", "Known spam")
        
        assert registry.is_blocklisted("https://malicious.com/page")
        assert registry.is_blocklisted("https://sub.malicious.com/page")
        assert not registry.is_blocklisted("https://legitimate.com/page")
    
    def test_remove_from_blocklist(self, registry):
        """Remove domain from blocklist."""
        registry.add_to_blocklist("temp-block.com")
        assert registry.is_blocklisted("https://temp-block.com/x")
        
        registry.remove_from_blocklist("temp-block.com")
        assert not registry.is_blocklisted("https://temp-block.com/x")
    
    def test_classify_source_by_url(self, registry):
        """Source classification from URL."""
        assert registry.classify_source(url="https://arxiv.org/abs/1234") == SourceCategory.ACADEMIC_PREPRINT
        assert registry.classify_source(url="https://whitehouse.gov/news") == SourceCategory.GOVERNMENT
        assert registry.classify_source(url="https://random-blog.com/post") == SourceCategory.UNKNOWN
    
    def test_classify_source_by_doi(self, registry):
        """Source classification from DOI."""
        assert registry.classify_source(doi="10.1038/nature12345") == SourceCategory.ACADEMIC_JOURNAL
        assert registry.classify_source(doi="10.48550/arxiv.1234") == SourceCategory.ACADEMIC_PREPRINT
    
    def test_get_source_reliability(self, registry):
        """Get reliability score for sources."""
        # Known academic source
        reliability = registry.get_source_reliability(doi="10.1038/nature12345")
        assert reliability >= 0.8
        
        # Blocklisted source
        registry.add_to_blocklist("spam.com")
        assert registry.get_source_reliability(url="https://spam.com/page") == 0.0
        
        # Unknown source
        unknown = registry.get_source_reliability(url="https://random.xyz/page")
        assert unknown <= 0.5
    
    def test_suffix_domain_matching(self, registry):
        """Match domains by suffix (e.g., .gov)."""
        # .gov should match any .gov domain
        info = registry.get_domain_info("https://whitehouse.gov/news")
        assert info is not None
        assert info.category == SourceCategory.GOVERNMENT
        
        info2 = registry.get_domain_info("https://cdc.gov/health")
        assert info2 is not None
    
    def test_to_dict(self, registry):
        """Export registry as dictionary."""
        d = registry.to_dict()
        assert "domains" in d
        assert "doi_prefixes" in d
        assert "blocklist" in d


# ============================================================================
# Liveness Check Tests
# ============================================================================

class TestLivenessCheckResult:
    """Tests for LivenessCheckResult."""
    
    def test_live_source(self):
        result = LivenessCheckResult(
            status=SourceLivenessStatus.LIVE,
            http_status=200
        )
        assert result.is_live
    
    def test_dead_source(self):
        result = LivenessCheckResult(
            status=SourceLivenessStatus.DEAD,
            http_status=404
        )
        assert not result.is_live
    
    def test_timeout(self):
        result = LivenessCheckResult(
            status=SourceLivenessStatus.TIMEOUT,
            error_message="Connection timed out"
        )
        assert not result.is_live
    
    def test_to_dict(self):
        result = LivenessCheckResult(
            status=SourceLivenessStatus.LIVE,
            http_status=200,
            final_url="https://example.com/final",
            content_type="text/html",
            response_time_ms=150
        )
        d = result.to_dict()
        assert d["status"] == "live"
        assert d["is_live"] is True
        assert d["http_status"] == 200


# ============================================================================
# Content Match Tests
# ============================================================================

class TestContentMatchResult:
    """Tests for ContentMatchResult."""
    
    def test_meets_threshold(self):
        result = ContentMatchResult(similarity_score=0.75)
        assert result.meets_threshold
        
        low = ContentMatchResult(similarity_score=0.5)
        assert not low.meets_threshold
    
    def test_strongly_supports(self):
        strong = ContentMatchResult(similarity_score=0.90)
        assert strong.strongly_supports
        
        moderate = ContentMatchResult(similarity_score=0.70)
        assert not moderate.strongly_supports
    
    def test_boundary_conditions(self):
        """Test exact boundary values."""
        at_threshold = ContentMatchResult(
            similarity_score=ExternalSourceConstants.MIN_CONTENT_SIMILARITY
        )
        assert at_threshold.meets_threshold
        
        just_below = ContentMatchResult(
            similarity_score=ExternalSourceConstants.MIN_CONTENT_SIMILARITY - 0.01
        )
        assert not just_below.meets_threshold


# ============================================================================
# DOI Verification Tests  
# ============================================================================

class TestDOIVerificationResult:
    """Tests for DOIVerificationResult."""
    
    def test_valid_doi(self):
        result = DOIVerificationResult(
            doi="10.1038/nature12345",
            status=DOIStatus.VALID,
            title="A Great Paper",
            retracted=False
        )
        assert result.is_valid
    
    def test_retracted_doi(self):
        """Retracted papers should not be valid."""
        result = DOIVerificationResult(
            doi="10.1234/retracted",
            status=DOIStatus.VALID,
            retracted=True,
            retraction_reason="Data fabrication"
        )
        assert not result.is_valid
    
    def test_invalid_doi(self):
        result = DOIVerificationResult(
            doi="10.0000/nonexistent",
            status=DOIStatus.INVALID
        )
        assert not result.is_valid


# ============================================================================
# Source Reliability Score Tests
# ============================================================================

class TestSourceReliabilityScore:
    """Tests for SourceReliabilityScore."""
    
    def test_meets_l4_threshold(self):
        high = SourceReliabilityScore(
            overall=0.75,
            category_score=0.8,
            liveness_score=1.0,
            content_match_score=0.7,
            freshness_score=1.0,
            registry_score=1.1
        )
        assert high.meets_l4_threshold
        
        low = SourceReliabilityScore(
            overall=0.3,
            category_score=0.3,
            liveness_score=1.0,
            content_match_score=0.4,
            freshness_score=0.8,
            registry_score=1.0
        )
        assert not low.meets_l4_threshold
    
    def test_boundary_threshold(self):
        """Test exact L4 threshold."""
        at_threshold = SourceReliabilityScore(
            overall=ExternalSourceConstants.MIN_VERIFIED_SOURCE_RELIABILITY,
            category_score=0.5,
            liveness_score=1.0,
            content_match_score=0.65,
            freshness_score=1.0,
            registry_score=1.0
        )
        assert at_threshold.meets_l4_threshold


# ============================================================================
# External Source Verification Tests
# ============================================================================

class TestExternalSourceVerification:
    """Tests for ExternalSourceVerification model."""
    
    def test_create_url_verification(self):
        v = ExternalSourceVerification(
            id=uuid4(),
            belief_id=uuid4(),
            url="https://example.com/article"
        )
        assert v.source_identifier == "https://example.com/article"
        assert v.status == SourceVerificationStatus.PENDING
        assert not v.is_verified
    
    def test_create_doi_verification(self):
        v = ExternalSourceVerification(
            id=uuid4(),
            belief_id=uuid4(),
            doi="10.1038/nature12345"
        )
        assert v.source_identifier == "doi:10.1038/nature12345"
    
    def test_verified_status(self):
        v = ExternalSourceVerification(
            id=uuid4(),
            belief_id=uuid4(),
            url="https://nature.com/article",
            status=SourceVerificationStatus.VERIFIED,
            verified_at=datetime.now()
        )
        assert v.is_verified
    
    def test_to_dict(self):
        v = ExternalSourceVerification(
            id=uuid4(),
            belief_id=uuid4(),
            url="https://example.com",
            doi="10.1234/test",
            category=SourceCategory.ACADEMIC_JOURNAL
        )
        d = v.to_dict()
        assert "id" in d
        assert d["url"] == "https://example.com"
        assert d["category"] == "academic_journal"


# ============================================================================
# L4 Source Requirements Tests
# ============================================================================

class TestL4SourceRequirements:
    """Tests for L4SourceRequirements."""
    
    def test_no_sources(self):
        req = L4SourceRequirements(
            belief_id=uuid4(),
            has_external_sources=False,
            total_sources=0
        )
        assert not req.all_requirements_met
        assert not req.has_external_sources
    
    def test_all_requirements_met(self):
        req = L4SourceRequirements(
            belief_id=uuid4(),
            has_external_sources=True,
            has_verified_sources=True,
            meets_reliability_threshold=True,
            meets_content_match_threshold=True,
            all_requirements_met=True,
            total_sources=2,
            verified_sources=1,
            best_reliability_score=0.8,
            best_content_match_score=0.75
        )
        assert req.all_requirements_met
    
    def test_partial_requirements(self):
        req = L4SourceRequirements(
            belief_id=uuid4(),
            has_external_sources=True,
            has_verified_sources=True,
            meets_reliability_threshold=False,
            meets_content_match_threshold=True,
            issues=["Best source reliability 0.40 < 0.50"]
        )
        assert not req.all_requirements_met
        assert len(req.issues) == 1


# ============================================================================
# Verification Service Tests
# ============================================================================

class TestExternalSourceVerificationService:
    """Tests for ExternalSourceVerificationService."""
    
    @pytest.fixture
    def service(self):
        """Fresh service for each test."""
        return ExternalSourceVerificationService()
    
    @pytest.fixture
    def belief_id(self):
        return uuid4()
    
    def test_create_verification(self, service, belief_id):
        """Create a new verification."""
        v = service.create_verification(
            belief_id=belief_id,
            url="https://nature.com/article"
        )
        assert v.belief_id == belief_id
        assert v.url == "https://nature.com/article"
        assert v.status == SourceVerificationStatus.PENDING
    
    def test_create_verification_requires_identifier(self, service, belief_id):
        """Must provide at least one source identifier."""
        with pytest.raises(ValueError, match="(?i)at least one"):
            service.create_verification(belief_id=belief_id)
    
    def test_create_verification_blocklisted(self, service, belief_id):
        """Blocklisted sources should be marked as blocked."""
        service.registry.add_to_blocklist("spam.com")
        v = service.create_verification(
            belief_id=belief_id,
            url="https://spam.com/fake"
        )
        assert v.status == SourceVerificationStatus.BLOCKED
    
    def test_check_liveness(self, service, belief_id):
        """Liveness check should populate result."""
        v = service.create_verification(
            belief_id=belief_id,
            url="https://example.com/article"
        )
        result = service.check_liveness(v.id)
        assert result.is_live  # Simulated as live
        assert v.liveness is not None
    
    def test_check_liveness_caching(self, service, belief_id):
        """Liveness results should be cached."""
        v = service.create_verification(
            belief_id=belief_id,
            url="https://example.com/cached"
        )
        result1 = service.check_liveness(v.id)
        result2 = service.check_liveness(v.id, use_cache=True)
        assert result1.checked_at == result2.checked_at
    
    def test_verify_doi(self, service, belief_id):
        """DOI verification should return metadata."""
        v = service.create_verification(
            belief_id=belief_id,
            doi="10.1038/nature12345"
        )
        result = service.verify_doi(v.id)
        assert result is not None
        assert result.status == DOIStatus.VALID
        assert result.publisher_reliability > 0.5
    
    def test_check_content_match(self, service, belief_id):
        """Content matching should compute similarity."""
        v = service.create_verification(
            belief_id=belief_id,
            url="https://example.com/article"
        )
        result = service.check_content_match(
            v.id,
            belief_content="The sky is blue"
        )
        assert result.similarity_score > 0
        assert v.content_match is not None
    
    def test_compute_reliability(self, service, belief_id):
        """Reliability computation should combine factors."""
        v = service.create_verification(
            belief_id=belief_id,
            url="https://nature.com/article"
        )
        service.check_liveness(v.id)
        service.check_content_match(v.id, "Test belief content")
        
        reliability = service.compute_reliability(v.id)
        assert 0.0 <= reliability.overall <= 1.0
        assert reliability.liveness_score == 1.0
    
    def test_verify_source_full_workflow(self, service, belief_id):
        """Full verification workflow."""
        v = service.create_verification(
            belief_id=belief_id,
            url="https://nature.com/relevant-article"
        )
        result = service.verify_source(
            v.id,
            belief_content="Scientific research on relevant topic"
        )
        
        assert result.status == SourceVerificationStatus.VERIFIED
        assert result.is_verified
        assert result.liveness is not None
        assert result.content_match is not None
        assert result.reliability is not None
        assert result.verified_at is not None
    
    def test_verify_source_blocked(self, service, belief_id):
        """Blocked sources should not verify."""
        service.registry.add_to_blocklist("blocked.com")
        v = service.create_verification(
            belief_id=belief_id,
            url="https://blocked.com/article"
        )
        result = service.verify_source(v.id, "Some content")
        assert result.status == SourceVerificationStatus.BLOCKED
    
    def test_check_l4_requirements_no_sources(self, service, belief_id):
        """L4 check with no sources should fail."""
        req = service.check_l4_requirements(belief_id, "Belief content")
        assert not req.all_requirements_met
        assert not req.has_external_sources
        assert "Insufficient external sources" in req.issues[0]
    
    def test_check_l4_requirements_with_verified_source(self, service, belief_id):
        """L4 check with verified source should pass."""
        # Create and verify a source
        v = service.create_verification(
            belief_id=belief_id,
            url="https://nature.com/article"
        )
        service.verify_source(v.id, "Relevant scientific content")
        
        req = service.check_l4_requirements(belief_id, "Relevant scientific content")
        assert req.has_external_sources
        assert req.has_verified_sources
        assert req.verified_sources == 1
    
    def test_get_verification(self, service, belief_id):
        """Get verification by ID."""
        v = service.create_verification(
            belief_id=belief_id,
            url="https://example.com"
        )
        retrieved = service.get_verification(v.id)
        assert retrieved is not None
        assert retrieved.id == v.id
        
        # Non-existent
        assert service.get_verification(uuid4()) is None
    
    def test_get_verifications_for_belief(self, service, belief_id):
        """Get all verifications for a belief."""
        service.create_verification(belief_id=belief_id, url="https://one.com")
        service.create_verification(belief_id=belief_id, url="https://two.com")
        service.create_verification(belief_id=belief_id, doi="10.1234/test")
        
        verifications = service.get_verifications_for_belief(belief_id)
        assert len(verifications) == 3
    
    def test_get_verified_sources_for_belief(self, service, belief_id):
        """Get only verified sources."""
        v1 = service.create_verification(belief_id=belief_id, url="https://one.com")
        v2 = service.create_verification(belief_id=belief_id, url="https://two.com")
        
        service.verify_source(v1.id, "Content")
        # v2 not verified
        
        verified = service.get_verified_sources_for_belief(belief_id)
        assert len(verified) == 1
        assert verified[0].id == v1.id


# ============================================================================
# Convenience Function Tests
# ============================================================================

class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""
    
    def test_verify_external_source(self):
        """Simple source verification."""
        belief_id = uuid4()
        result = verify_external_source(
            belief_id=belief_id,
            belief_content="Scientific fact about biology",
            url="https://pubmed.ncbi.nlm.nih.gov/12345"
        )
        assert result.belief_id == belief_id
        assert result.is_verified
    
    def test_verify_external_source_with_doi(self):
        """Source verification with DOI."""
        belief_id = uuid4()
        result = verify_external_source(
            belief_id=belief_id,
            belief_content="Research findings",
            doi="10.1038/nature12345"
        )
        assert result.doi == "10.1038/nature12345"
        assert result.is_verified
    
    def test_check_belief_l4_readiness(self):
        """Check L4 readiness with multiple sources."""
        belief_id = uuid4()
        result = check_belief_l4_readiness(
            belief_id=belief_id,
            belief_content="Well-supported scientific claim",
            sources=[
                {"url": "https://nature.com/article"},
                {"doi": "10.1126/science.abc123"},
            ]
        )
        assert result.total_sources == 2
        assert result.has_external_sources


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""
    
    @pytest.fixture
    def service(self):
        return ExternalSourceVerificationService()
    
    def test_invalid_url(self, service):
        """Handle invalid URLs gracefully."""
        v = service.create_verification(
            belief_id=uuid4(),
            url="not-a-valid-url"
        )
        # Should still create but may fail verification
        assert v.url == "not-a-valid-url"
    
    def test_empty_belief_content(self, service):
        """Handle empty belief content."""
        v = service.create_verification(
            belief_id=uuid4(),
            url="https://example.com"
        )
        result = service.check_content_match(v.id, "")
        # Should handle gracefully
        assert result.similarity_score >= 0
    
    def test_multiple_identifiers(self, service):
        """Source with multiple identifiers."""
        v = service.create_verification(
            belief_id=uuid4(),
            url="https://nature.com/article",
            doi="10.1038/nature12345",
            citation="Smith et al., Nature 2024"
        )
        assert v.url is not None
        assert v.doi is not None
        assert v.citation is not None
        # DOI should be preferred identifier
        assert v.source_identifier == "doi:10.1038/nature12345"
    
    def test_verification_not_found(self, service):
        """Handle non-existent verification."""
        with pytest.raises(ValueError, match="not found"):
            service.check_liveness(uuid4())
    
    def test_stale_source_penalty(self, service):
        """Old sources should receive staleness penalty."""
        v = service.create_verification(
            belief_id=uuid4(),
            url="https://example.com/old-article"
        )
        service.check_liveness(v.id)
        service.check_content_match(v.id, "Test content")
        
        # Source from 3 years ago
        old_date = datetime.now() - timedelta(days=365 * 3)
        reliability = service.compute_reliability(v.id, source_date=old_date)
        
        assert reliability.staleness_penalty > 0
        assert reliability.freshness_score < 1.0
    
    def test_recent_source_bonus(self, service):
        """Recent sources should receive freshness bonus."""
        v = service.create_verification(
            belief_id=uuid4(),
            url="https://example.com/new-article"
        )
        service.check_liveness(v.id)
        service.check_content_match(v.id, "Test content")
        
        # Source from yesterday
        recent_date = datetime.now() - timedelta(days=1)
        reliability = service.compute_reliability(v.id, source_date=recent_date)
        
        assert reliability.freshness_score > 1.0
    
    def test_multiple_beliefs_same_source(self, service):
        """Same source can verify multiple beliefs."""
        url = "https://nature.com/universal-truth"
        belief1 = uuid4()
        belief2 = uuid4()
        
        v1 = service.create_verification(belief_id=belief1, url=url)
        v2 = service.create_verification(belief_id=belief2, url=url)
        
        service.verify_source(v1.id, "First belief")
        service.verify_source(v2.id, "Second belief")
        
        assert service.get_verifications_for_belief(belief1)[0].is_verified
        assert service.get_verifications_for_belief(belief2)[0].is_verified


# ============================================================================
# Integration with Consensus Tests
# ============================================================================

class TestConsensusIntegration:
    """Tests for integration with consensus/elevation system."""
    
    @pytest.fixture
    def service(self):
        return ExternalSourceVerificationService()
    
    def test_l4_elevation_requirements_comprehensive(self, service):
        """Full L4 requirements check scenario."""
        belief_id = uuid4()
        belief_content = "Climate change is primarily driven by human activities"
        
        # Add multiple high-quality sources
        sources = [
            {"url": "https://climate.nasa.gov/evidence/"},
            {"doi": "10.1038/nature12345"},
            {"url": "https://ipcc.ch/report/ar6/"},
        ]
        
        for source in sources:
            v = service.create_verification(belief_id=belief_id, **source)
            service.verify_source(v.id, belief_content)
        
        req = service.check_l4_requirements(belief_id, belief_content)
        
        assert req.all_requirements_met
        assert req.total_sources == 3
        assert req.verified_sources >= 1
        assert req.best_reliability_score >= ExternalSourceConstants.MIN_VERIFIED_SOURCE_RELIABILITY
        assert req.best_content_match_score >= ExternalSourceConstants.MIN_CONTENT_MATCH_SCORE
    
    def test_l4_elevation_fails_without_sources(self, service):
        """L4 elevation should fail without external sources."""
        belief_id = uuid4()
        req = service.check_l4_requirements(belief_id, "Unverified claim")
        
        assert not req.all_requirements_met
        assert req.total_sources == 0
        assert len(req.issues) > 0
    
    def test_l4_elevation_fails_with_only_failed_sources(self, service):
        """L4 elevation should fail if all sources fail verification."""
        belief_id = uuid4()
        
        # Add a blocklisted source
        service.registry.add_to_blocklist("fake-science.com")
        v = service.create_verification(
            belief_id=belief_id,
            url="https://fake-science.com/article"
        )
        
        req = service.check_l4_requirements(belief_id, "Content")
        
        assert not req.all_requirements_met
        assert req.total_sources == 1
        assert req.verified_sources == 0


# ============================================================================
# Global Registry Tests
# ============================================================================

class TestGlobalRegistry:
    """Tests for global registry singleton."""
    
    def test_get_registry_returns_same_instance(self):
        """get_registry should return singleton."""
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2
    
    def test_registry_is_populated(self):
        """Global registry should have default sources."""
        registry = get_registry()
        # Should have at least the default domains
        assert len(registry._domains) > 0
        assert len(registry._doi_prefixes) > 0
