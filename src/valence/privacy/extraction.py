# Valence AI-Assisted Insight Extraction
"""
Extract shareable insights from private content using AI while preserving privacy.

This module provides AI-powered extraction of insights from private content,
allowing users to share valuable information without exposing raw data.

Key features:
- Multiple extraction levels (summary, key_points, anonymized, themes)
- Human review step before elevation
- Provenance tracking ("extracted from" relationship)
- Original content reference for owner without exposure to recipients
"""

from __future__ import annotations

import hashlib
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional, Protocol


class ExtractionLevel(Enum):
    """
    Levels of insight extraction, from most to least detail.
    
    Higher levels preserve more detail but may leak more information.
    Lower levels are safer but less informative.
    """
    
    THEMES = "themes"  # High-level themes only (safest)
    KEY_POINTS = "key_points"  # Bullet points of main ideas
    SUMMARY = "summary"  # Concise summary of content
    ANONYMIZED = "anonymized"  # Full content with PII removed


class ReviewStatus(Enum):
    """Status of human review for extracted insights."""
    
    PENDING = "pending"  # Awaiting human review
    APPROVED = "approved"  # Human approved for sharing
    REJECTED = "rejected"  # Human rejected, not shareable
    MODIFIED = "modified"  # Human modified before approval


@dataclass
class ExtractionRequest:
    """Request to extract insights from content."""
    
    request_id: str
    content: str
    level: ExtractionLevel
    context: Optional[str] = None  # Additional context for extraction
    preserve_entities: list[str] = field(default_factory=list)  # Entity types to keep
    redact_patterns: list[str] = field(default_factory=list)  # Patterns to redact
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @classmethod
    def create(
        cls,
        content: str,
        level: ExtractionLevel = ExtractionLevel.KEY_POINTS,
        context: Optional[str] = None,
        **kwargs,
    ) -> "ExtractionRequest":
        """Create a new extraction request."""
        return cls(
            request_id=str(uuid.uuid4()),
            content=content,
            level=level,
            context=context,
            **kwargs,
        )


@dataclass
class ExtractedInsight:
    """An insight extracted from private content."""
    
    insight_id: str
    request_id: str  # Links to ExtractionRequest
    level: ExtractionLevel
    content: str  # The extracted insight (safe to share after review)
    
    # Provenance tracking
    source_hash: str  # Hash of original content (for verification, not exposure)
    extraction_method: str  # AI model/method used
    extracted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Review state
    review_status: ReviewStatus = ReviewStatus.PENDING
    reviewed_at: Optional[datetime] = None
    reviewer_id: Optional[str] = None
    review_notes: Optional[str] = None
    
    # For owner: reference to original (not exposed to recipients)
    _original_content_ref: Optional[str] = field(default=None, repr=False)
    
    # Confidence and metadata
    confidence: float = 0.0  # AI confidence in extraction quality
    metadata: dict = field(default_factory=dict)
    
    @property
    def is_shareable(self) -> bool:
        """Check if this insight can be shared."""
        return self.review_status in (ReviewStatus.APPROVED, ReviewStatus.MODIFIED)
    
    @property
    def provenance(self) -> dict:
        """Get provenance information (safe to share)."""
        return {
            "insight_id": self.insight_id,
            "extraction_level": self.level.value,
            "extraction_method": self.extraction_method,
            "extracted_at": self.extracted_at.isoformat(),
            "source_hash": self.source_hash,  # Proves origin without exposing content
            "review_status": self.review_status.value,
        }
    
    def to_dict(self, include_private: bool = False) -> dict:
        """
        Convert to dictionary for serialization.
        
        Args:
            include_private: If True, include owner-only fields
        """
        data = {
            "insight_id": self.insight_id,
            "level": self.level.value,
            "content": self.content,
            "provenance": self.provenance,
            "confidence": self.confidence,
            "is_shareable": self.is_shareable,
        }
        
        if include_private and self._original_content_ref:
            data["_original_ref"] = self._original_content_ref
        
        return data


class AIExtractor(Protocol):
    """Protocol for AI extraction backends."""
    
    def extract(
        self,
        content: str,
        level: ExtractionLevel,
        context: Optional[str] = None,
    ) -> tuple[str, float]:
        """
        Extract insights from content.
        
        Args:
            content: The private content to extract from
            level: Extraction level
            context: Optional context to guide extraction
        
        Returns:
            Tuple of (extracted_content, confidence_score)
        """
        ...


class MockAIExtractor:
    """
    Mock AI extractor for testing and development.
    
    In production, this would call an actual AI service (OpenAI, Claude, etc.)
    """
    
    def __init__(self, model_name: str = "mock-extractor-v1"):
        self.model_name = model_name
    
    def extract(
        self,
        content: str,
        level: ExtractionLevel,
        context: Optional[str] = None,
    ) -> tuple[str, float]:
        """Mock extraction based on level."""
        
        if level == ExtractionLevel.THEMES:
            return self._extract_themes(content), 0.85
        elif level == ExtractionLevel.KEY_POINTS:
            return self._extract_key_points(content), 0.80
        elif level == ExtractionLevel.SUMMARY:
            return self._extract_summary(content), 0.75
        elif level == ExtractionLevel.ANONYMIZED:
            return self._anonymize(content), 0.90
        else:
            raise ValueError(f"Unknown extraction level: {level}")
    
    def _extract_themes(self, content: str) -> str:
        """Extract high-level themes."""
        # Mock: extract "themes" from content
        words = content.lower().split()
        # Simulate theme extraction
        themes = []
        if any(w in words for w in ["project", "work", "task", "deadline"]):
            themes.append("Work/Projects")
        if any(w in words for w in ["meeting", "call", "discuss", "team"]):
            themes.append("Collaboration")
        if any(w in words for w in ["idea", "think", "consider", "plan"]):
            themes.append("Planning/Ideas")
        if any(w in words for w in ["problem", "issue", "fix", "bug"]):
            themes.append("Problem Solving")
        
        if not themes:
            themes.append("General Discussion")
        
        return f"Themes: {', '.join(themes)}"
    
    def _extract_key_points(self, content: str) -> str:
        """Extract key points as bullet list."""
        # Mock: create bullet points from sentences
        sentences = content.replace("\n", " ").split(".")
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
        
        if not sentences:
            return "• No significant points extracted"
        
        # Take first few sentences as "key points"
        key_points = sentences[:min(3, len(sentences))]
        return "\n".join(f"• {point}" for point in key_points)
    
    def _extract_summary(self, content: str) -> str:
        """Extract a concise summary."""
        # Mock: truncate and add summary prefix
        words = content.split()
        if len(words) > 30:
            summary = " ".join(words[:30]) + "..."
        else:
            summary = content
        
        return f"Summary: {summary}"
    
    def _anonymize(self, content: str) -> str:
        """Remove PII and sensitive information."""
        import re
        
        result = content
        
        # Mock PII removal patterns
        # Email addresses
        result = re.sub(
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            '[EMAIL]',
            result
        )
        
        # Phone numbers (simple pattern)
        result = re.sub(
            r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
            '[PHONE]',
            result
        )
        
        # Names (very basic - just capitalize words that might be names)
        # In real implementation, use NER
        result = re.sub(
            r'\b(Mr\.|Mrs\.|Ms\.|Dr\.)\s+[A-Z][a-z]+',
            '[NAME]',
            result
        )
        
        # Dates
        result = re.sub(
            r'\b\d{1,2}/\d{1,2}/\d{2,4}\b',
            '[DATE]',
            result
        )
        
        # Credit card-like numbers
        result = re.sub(
            r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',
            '[CARD]',
            result
        )
        
        return result


class InsightExtractor:
    """
    Main service for extracting shareable insights from private content.
    
    This service:
    1. Accepts private content
    2. Uses AI to extract insights at specified level
    3. Tracks provenance (extracted-from relationship)
    4. Manages human review workflow
    5. Provides safe access to approved insights
    """
    
    def __init__(
        self,
        ai_extractor: Optional[AIExtractor] = None,
        require_review: bool = True,
    ):
        """
        Initialize the insight extractor.
        
        Args:
            ai_extractor: AI backend for extraction (defaults to mock)
            require_review: Whether human review is required before sharing
        """
        self.ai_extractor = ai_extractor or MockAIExtractor()
        self.require_review = require_review
        
        # Storage (in production, use database)
        self._requests: dict[str, ExtractionRequest] = {}
        self._insights: dict[str, ExtractedInsight] = {}
        self._by_source_hash: dict[str, list[str]] = {}  # source_hash -> insight_ids
        
        # Callbacks
        self._review_callbacks: list[Callable[[ExtractedInsight], None]] = []
    
    def extract(
        self,
        content: str,
        level: ExtractionLevel = ExtractionLevel.KEY_POINTS,
        context: Optional[str] = None,
        auto_approve: bool = False,
        owner_id: Optional[str] = None,
        **metadata,
    ) -> ExtractedInsight:
        """
        Extract insights from private content.
        
        Args:
            content: The private content to extract from
            level: Extraction level (themes, key_points, summary, anonymized)
            context: Optional context to guide the AI
            auto_approve: Skip review (use carefully!)
            owner_id: ID of content owner (for provenance)
            **metadata: Additional metadata to store
        
        Returns:
            ExtractedInsight ready for review
        """
        # Create request
        request = ExtractionRequest.create(
            content=content,
            level=level,
            context=context,
            metadata={"owner_id": owner_id, **metadata},
        )
        self._requests[request.request_id] = request
        
        # Compute source hash (for provenance, not exposure)
        source_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        
        # Extract using AI
        extracted_content, confidence = self.ai_extractor.extract(
            content, level, context
        )
        
        # Determine initial review status
        if auto_approve and not self.require_review:
            review_status = ReviewStatus.APPROVED
        else:
            review_status = ReviewStatus.PENDING
        
        # Create insight
        insight = ExtractedInsight(
            insight_id=str(uuid.uuid4()),
            request_id=request.request_id,
            level=level,
            content=extracted_content,
            source_hash=source_hash,
            extraction_method=getattr(self.ai_extractor, "model_name", "unknown"),
            review_status=review_status,
            confidence=confidence,
            _original_content_ref=request.request_id,  # Owner can lookup original
            metadata=metadata,
        )
        
        # Store
        self._insights[insight.insight_id] = insight
        if source_hash not in self._by_source_hash:
            self._by_source_hash[source_hash] = []
        self._by_source_hash[source_hash].append(insight.insight_id)
        
        return insight
    
    def review(
        self,
        insight_id: str,
        approved: bool,
        reviewer_id: str,
        modified_content: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> ExtractedInsight:
        """
        Human review of an extracted insight.
        
        Args:
            insight_id: ID of insight to review
            approved: Whether to approve for sharing
            reviewer_id: ID of the reviewer
            modified_content: Optional modified version of the insight
            notes: Optional review notes
        
        Returns:
            Updated ExtractedInsight
        
        Raises:
            KeyError: If insight not found
            ValueError: If insight already reviewed
        """
        insight = self._insights.get(insight_id)
        if insight is None:
            raise KeyError(f"Insight not found: {insight_id}")
        
        if insight.review_status != ReviewStatus.PENDING:
            raise ValueError(
                f"Insight already reviewed: {insight.review_status.value}"
            )
        
        # Update review state
        insight.reviewed_at = datetime.now(timezone.utc)
        insight.reviewer_id = reviewer_id
        insight.review_notes = notes
        
        if approved:
            if modified_content:
                insight.content = modified_content
                insight.review_status = ReviewStatus.MODIFIED
            else:
                insight.review_status = ReviewStatus.APPROVED
        else:
            insight.review_status = ReviewStatus.REJECTED
        
        # Fire callbacks
        for callback in self._review_callbacks:
            try:
                callback(insight)
            except Exception:
                pass
        
        return insight
    
    def get_insight(
        self,
        insight_id: str,
        include_private: bool = False,
    ) -> Optional[ExtractedInsight]:
        """
        Get an insight by ID.
        
        Args:
            insight_id: ID of the insight
            include_private: Whether caller can see private fields
        
        Returns:
            The insight, or None if not found
        """
        insight = self._insights.get(insight_id)
        if insight is None:
            return None
        
        # For non-owners, only return if shareable
        if not include_private and not insight.is_shareable:
            return None
        
        return insight
    
    def get_original_content(
        self,
        insight_id: str,
        owner_id: str,
    ) -> Optional[str]:
        """
        Get the original content for an insight (owner only).
        
        Args:
            insight_id: ID of the insight
            owner_id: ID claiming ownership
        
        Returns:
            Original content if owner matches, None otherwise
        """
        insight = self._insights.get(insight_id)
        if insight is None:
            return None
        
        # Verify ownership
        request_id = insight._original_content_ref
        if request_id is None:
            return None
        
        request = self._requests.get(request_id)
        if request is None:
            return None
        
        # Check owner
        if request.metadata.get("owner_id") != owner_id:
            return None
        
        return request.content
    
    def list_pending_reviews(self) -> list[ExtractedInsight]:
        """List all insights pending review."""
        return [
            i for i in self._insights.values()
            if i.review_status == ReviewStatus.PENDING
        ]
    
    def list_shareable(self) -> list[ExtractedInsight]:
        """List all shareable insights."""
        return [i for i in self._insights.values() if i.is_shareable]
    
    def get_insights_for_source(self, source_hash: str) -> list[ExtractedInsight]:
        """Get all insights extracted from a specific source."""
        insight_ids = self._by_source_hash.get(source_hash, [])
        return [self._insights[iid] for iid in insight_ids if iid in self._insights]
    
    def add_review_callback(
        self,
        callback: Callable[[ExtractedInsight], None],
    ) -> None:
        """Add callback to be invoked when an insight is reviewed."""
        self._review_callbacks.append(callback)
    
    def verify_provenance(
        self,
        insight_id: str,
        claimed_source_hash: str,
    ) -> bool:
        """
        Verify that an insight was extracted from a claimed source.
        
        Args:
            insight_id: ID of the insight
            claimed_source_hash: Hash of the claimed source content
        
        Returns:
            True if the insight was extracted from content with that hash
        """
        insight = self._insights.get(insight_id)
        if insight is None:
            return False
        
        return insight.source_hash == claimed_source_hash


# Module-level default extractor
_default_extractor: Optional[InsightExtractor] = None


def get_extractor() -> InsightExtractor:
    """Get the default insight extractor."""
    global _default_extractor
    if _default_extractor is None:
        _default_extractor = InsightExtractor()
    return _default_extractor


def extract_insight(
    content: str,
    level: ExtractionLevel = ExtractionLevel.KEY_POINTS,
    context: Optional[str] = None,
    owner_id: Optional[str] = None,
) -> ExtractedInsight:
    """
    High-level function to extract an insight from private content.
    
    Args:
        content: The private content to extract from
        level: Extraction level
        context: Optional context for the AI
        owner_id: ID of content owner
    
    Returns:
        ExtractedInsight (pending review)
    
    Example:
        >>> insight = extract_insight(
        ...     "Meeting notes: discussed Q3 budget with Alice...",
        ...     level=ExtractionLevel.KEY_POINTS,
        ... )
        >>> print(insight.content)  # Key points extracted
        >>> print(insight.is_shareable)  # False until reviewed
    """
    return get_extractor().extract(
        content=content,
        level=level,
        context=context,
        owner_id=owner_id,
    )


def review_insight(
    insight_id: str,
    approved: bool,
    reviewer_id: str,
    modified_content: Optional[str] = None,
) -> ExtractedInsight:
    """
    Review an extracted insight for sharing.
    
    Args:
        insight_id: ID of insight to review
        approved: Whether to approve
        reviewer_id: ID of reviewer
        modified_content: Optional modified version
    
    Returns:
        Updated insight
    """
    return get_extractor().review(
        insight_id=insight_id,
        approved=approved,
        reviewer_id=reviewer_id,
        modified_content=modified_content,
    )
