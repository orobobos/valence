# Valence Corroboration Detection
"""
Detect semantically similar beliefs from different sources.

When multiple independent sources confirm the same information, 
the belief gains corroboration confidence and may be auto-elevated.

Key features:
- Semantic similarity detection using embeddings
- Independent source tracking
- Corroboration threshold management
- Evidence chain tracking for provenance
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Protocol


class CorroborationStatus(Enum):
    """Status of corroboration for a belief."""
    
    UNCORROBORATED = "uncorroborated"  # No independent sources
    PARTIALLY_CORROBORATED = "partially_corroborated"  # Some sources, below threshold
    CORROBORATED = "corroborated"  # Meets threshold
    HIGHLY_CORROBORATED = "highly_corroborated"  # Exceeds threshold significantly


@dataclass
class SourceInfo:
    """Information about a corroborating source."""
    
    source_id: str
    source_type: str  # e.g., "federation", "api", "manual", "ingestion"
    content_hash: str  # Hash of the corroborating content
    similarity: float  # Semantic similarity score
    corroborated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "content_hash": self.content_hash,
            "similarity": self.similarity,
            "corroborated_at": self.corroborated_at.isoformat(),
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceInfo":
        """Create from dictionary."""
        corroborated_at = data.get("corroborated_at")
        if isinstance(corroborated_at, str):
            corroborated_at = datetime.fromisoformat(corroborated_at)
        elif corroborated_at is None:
            corroborated_at = datetime.now(timezone.utc)
        
        return cls(
            source_id=data["source_id"],
            source_type=data.get("source_type", "unknown"),
            content_hash=data.get("content_hash", ""),
            similarity=data.get("similarity", 0.0),
            corroborated_at=corroborated_at,
            metadata=data.get("metadata", {}),
        )


@dataclass
class CorroborationEvidence:
    """Evidence chain for a corroborated belief."""
    
    belief_id: str
    belief_content: str
    sources: list[SourceInfo] = field(default_factory=list)
    status: CorroborationStatus = CorroborationStatus.UNCORROBORATED
    confidence_boost: float = 0.0  # How much this boosts corroboration confidence
    first_corroborated_at: Optional[datetime] = None
    last_corroborated_at: Optional[datetime] = None
    
    @property
    def source_count(self) -> int:
        """Number of independent corroborating sources."""
        return len(self.sources)
    
    @property
    def unique_source_types(self) -> set[str]:
        """Unique types of sources that corroborated."""
        return {s.source_type for s in self.sources}
    
    @property
    def average_similarity(self) -> float:
        """Average semantic similarity across sources."""
        if not self.sources:
            return 0.0
        return sum(s.similarity for s in self.sources) / len(self.sources)
    
    def add_source(self, source: SourceInfo) -> bool:
        """
        Add a corroborating source.
        
        Returns True if source was added (wasn't already present).
        """
        # Check if this source already corroborated
        existing_ids = {s.source_id for s in self.sources}
        if source.source_id in existing_ids:
            return False
        
        self.sources.append(source)
        
        # Update timestamps
        now = source.corroborated_at
        if self.first_corroborated_at is None:
            self.first_corroborated_at = now
        self.last_corroborated_at = now
        
        return True
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "belief_id": self.belief_id,
            "belief_content": self.belief_content,
            "sources": [s.to_dict() for s in self.sources],
            "status": self.status.value,
            "confidence_boost": self.confidence_boost,
            "source_count": self.source_count,
            "average_similarity": self.average_similarity,
            "first_corroborated_at": (
                self.first_corroborated_at.isoformat() 
                if self.first_corroborated_at else None
            ),
            "last_corroborated_at": (
                self.last_corroborated_at.isoformat() 
                if self.last_corroborated_at else None
            ),
        }


class EmbeddingSimilarity(Protocol):
    """Protocol for embedding similarity computation."""
    
    def compute_similarity(
        self,
        text_a: str,
        text_b: str,
    ) -> float:
        """Compute semantic similarity between two texts (0-1)."""
        ...
    
    def find_similar(
        self,
        query: str,
        candidates: list[tuple[str, str]],  # (id, content) pairs
        threshold: float,
    ) -> list[tuple[str, float]]:
        """Find similar candidates above threshold. Returns (id, similarity) pairs."""
        ...


class MockEmbeddingSimilarity:
    """
    Mock embedding similarity for testing.
    
    Uses simple word overlap for similarity calculation.
    In production, use actual embedding models (OpenAI, sentence-transformers, etc.)
    """
    
    def __init__(self):
        self._cache: dict[tuple[str, str], float] = {}
    
    def _tokenize(self, text: str) -> set[str]:
        """Simple tokenization."""
        return set(text.lower().split())
    
    def compute_similarity(self, text_a: str, text_b: str) -> float:
        """Compute Jaccard similarity between tokenized texts."""
        cache_key = (text_a, text_b)
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        tokens_a = self._tokenize(text_a)
        tokens_b = self._tokenize(text_b)
        
        if not tokens_a or not tokens_b:
            return 0.0
        
        intersection = len(tokens_a & tokens_b)
        union = len(tokens_a | tokens_b)
        
        similarity = intersection / union if union > 0 else 0.0
        self._cache[cache_key] = similarity
        return similarity
    
    def find_similar(
        self,
        query: str,
        candidates: list[tuple[str, str]],
        threshold: float,
    ) -> list[tuple[str, float]]:
        """Find candidates above similarity threshold."""
        results = []
        for cand_id, cand_content in candidates:
            similarity = self.compute_similarity(query, cand_content)
            if similarity >= threshold:
                results.append((cand_id, similarity))
        return sorted(results, key=lambda x: -x[1])


@dataclass
class CorroborationConfig:
    """Configuration for corroboration detection."""
    
    # Minimum semantic similarity to consider corroborating
    similarity_threshold: float = 0.85
    
    # Number of independent sources needed for full corroboration
    corroboration_threshold: int = 3
    
    # Confidence boost formula: base * (1 - decay^count)
    confidence_boost_base: float = 0.3
    confidence_boost_decay: float = 0.5
    
    # Maximum confidence boost (asymptotic limit)
    max_confidence_boost: float = 0.9
    
    # Whether to count same-type sources or require diversity
    require_source_diversity: bool = False
    min_unique_source_types: int = 2


class CorroborationDetector:
    """
    Detects and tracks corroboration across beliefs.
    
    This service:
    1. Finds semantically similar beliefs from different sources
    2. Tracks corroboration evidence chains
    3. Calculates confidence boosts based on corroboration
    4. Determines when auto-elevation threshold is met
    """
    
    def __init__(
        self,
        similarity_backend: Optional[EmbeddingSimilarity] = None,
        config: Optional[CorroborationConfig] = None,
    ):
        """
        Initialize the corroboration detector.
        
        Args:
            similarity_backend: Backend for semantic similarity (defaults to mock)
            config: Corroboration configuration
        """
        self.similarity = similarity_backend or MockEmbeddingSimilarity()
        self.config = config or CorroborationConfig()
        
        # Storage (in production, use database)
        self._evidence: dict[str, CorroborationEvidence] = {}
        self._by_content_hash: dict[str, list[str]] = {}  # content_hash -> belief_ids
    
    def _hash_content(self, content: str) -> str:
        """Create a hash of content for deduplication."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _calculate_confidence_boost(self, source_count: int) -> float:
        """
        Calculate confidence boost from source count.
        
        Uses asymptotic formula: base * (1 - decay^count)
        This approaches max_confidence_boost as count increases.
        """
        if source_count <= 0:
            return 0.0
        
        boost = self.config.confidence_boost_base * (
            1.0 - (self.config.confidence_boost_decay ** source_count)
        )
        return min(boost, self.config.max_confidence_boost)
    
    def _determine_status(
        self,
        evidence: CorroborationEvidence,
    ) -> CorroborationStatus:
        """Determine corroboration status based on evidence."""
        count = evidence.source_count
        
        # Check source diversity if required
        if self.config.require_source_diversity:
            unique_types = len(evidence.unique_source_types)
            if unique_types < self.config.min_unique_source_types:
                count = min(count, unique_types)  # Cap effective count
        
        if count == 0:
            return CorroborationStatus.UNCORROBORATED
        elif count < self.config.corroboration_threshold:
            return CorroborationStatus.PARTIALLY_CORROBORATED
        elif count < self.config.corroboration_threshold * 2:
            return CorroborationStatus.CORROBORATED
        else:
            return CorroborationStatus.HIGHLY_CORROBORATED
    
    def check_corroboration(
        self,
        content: str,
        source_id: str,
        source_type: str = "manual",
        existing_beliefs: Optional[list[tuple[str, str]]] = None,
        metadata: Optional[dict] = None,
    ) -> Optional[tuple[str, CorroborationEvidence]]:
        """
        Check if content corroborates an existing belief.
        
        Args:
            content: The content to check
            source_id: ID of the source
            source_type: Type of source (federation, api, manual, etc.)
            existing_beliefs: List of (id, content) pairs to check against
                              If None, checks against tracked beliefs
            metadata: Additional metadata about the source
        
        Returns:
            Tuple of (belief_id, evidence) if corroboration found, None otherwise
        """
        # Get candidates to check against
        if existing_beliefs is not None:
            candidates = existing_beliefs
        else:
            # Use tracked beliefs
            candidates = [
                (belief_id, ev.belief_content)
                for belief_id, ev in self._evidence.items()
            ]
        
        if not candidates:
            return None
        
        # Find similar beliefs
        similar = self.similarity.find_similar(
            content,
            candidates,
            self.config.similarity_threshold,
        )
        
        if not similar:
            return None
        
        # Take the most similar match
        best_id, best_similarity = similar[0]
        
        # Create source info
        source = SourceInfo(
            source_id=source_id,
            source_type=source_type,
            content_hash=self._hash_content(content),
            similarity=best_similarity,
            metadata=metadata or {},
        )
        
        # Get or create evidence
        evidence = self._evidence.get(best_id)
        if evidence is None:
            # Create new evidence for existing belief
            existing_content = dict(candidates).get(best_id, content)
            evidence = CorroborationEvidence(
                belief_id=best_id,
                belief_content=existing_content,
            )
            self._evidence[best_id] = evidence
        
        # Add source (returns False if already present)
        if not evidence.add_source(source):
            # Already corroborated by this source
            return best_id, evidence
        
        # Update status and confidence boost
        evidence.status = self._determine_status(evidence)
        evidence.confidence_boost = self._calculate_confidence_boost(evidence.source_count)
        
        # Track by content hash
        content_hash = self._hash_content(content)
        if content_hash not in self._by_content_hash:
            self._by_content_hash[content_hash] = []
        if best_id not in self._by_content_hash[content_hash]:
            self._by_content_hash[content_hash].append(best_id)
        
        return best_id, evidence
    
    def register_belief(
        self,
        belief_id: str,
        content: str,
        source_id: str,
        source_type: str = "manual",
        metadata: Optional[dict] = None,
    ) -> CorroborationEvidence:
        """
        Register a new belief for corroboration tracking.
        
        Args:
            belief_id: Unique ID for the belief
            content: Belief content
            source_id: ID of the original source
            source_type: Type of source
            metadata: Additional metadata
        
        Returns:
            CorroborationEvidence for the registered belief
        """
        evidence = CorroborationEvidence(
            belief_id=belief_id,
            belief_content=content,
        )
        
        # Add the original source
        source = SourceInfo(
            source_id=source_id,
            source_type=source_type,
            content_hash=self._hash_content(content),
            similarity=1.0,  # Perfect match with itself
            metadata=metadata or {},
        )
        evidence.add_source(source)
        evidence.status = CorroborationStatus.UNCORROBORATED  # One source doesn't count
        
        self._evidence[belief_id] = evidence
        
        # Track by content hash
        content_hash = self._hash_content(content)
        if content_hash not in self._by_content_hash:
            self._by_content_hash[content_hash] = []
        self._by_content_hash[content_hash].append(belief_id)
        
        return evidence
    
    def get_evidence(self, belief_id: str) -> Optional[CorroborationEvidence]:
        """Get corroboration evidence for a belief."""
        return self._evidence.get(belief_id)
    
    def is_corroborated(self, belief_id: str) -> bool:
        """Check if a belief meets the corroboration threshold."""
        evidence = self._evidence.get(belief_id)
        if evidence is None:
            return False
        return evidence.status in (
            CorroborationStatus.CORROBORATED,
            CorroborationStatus.HIGHLY_CORROBORATED,
        )
    
    def get_elevation_candidates(
        self,
        min_sources: Optional[int] = None,
    ) -> list[CorroborationEvidence]:
        """
        Get beliefs that are ready for elevation.
        
        Args:
            min_sources: Minimum source count (defaults to config threshold)
        
        Returns:
            List of CorroborationEvidence for elevation candidates
        """
        threshold = min_sources or self.config.corroboration_threshold
        
        return [
            ev for ev in self._evidence.values()
            if ev.source_count >= threshold
        ]
    
    def list_all_evidence(self) -> list[CorroborationEvidence]:
        """List all tracked corroboration evidence."""
        return list(self._evidence.values())
    
    def clear(self) -> None:
        """Clear all tracked evidence (for testing)."""
        self._evidence.clear()
        self._by_content_hash.clear()


# Module-level default detector
_default_detector: Optional[CorroborationDetector] = None


def get_detector() -> CorroborationDetector:
    """Get the default corroboration detector."""
    global _default_detector
    if _default_detector is None:
        _default_detector = CorroborationDetector()
    return _default_detector


def check_corroboration(
    content: str,
    source_id: str,
    source_type: str = "manual",
    existing_beliefs: Optional[list[tuple[str, str]]] = None,
) -> Optional[tuple[str, CorroborationEvidence]]:
    """
    High-level function to check if content corroborates existing beliefs.
    
    Args:
        content: The content to check
        source_id: ID of the source
        source_type: Type of source
        existing_beliefs: Optional list of (id, content) pairs to check against
    
    Returns:
        Tuple of (belief_id, evidence) if corroboration found, None otherwise
    
    Example:
        >>> result = check_corroboration(
        ...     "Python 3.12 adds improved error messages",
        ...     source_id="news-feed-1",
        ...     source_type="rss",
        ... )
        >>> if result:
        ...     belief_id, evidence = result
        ...     print(f"Corroborates belief {belief_id} ({evidence.source_count} sources)")
    """
    return get_detector().check_corroboration(
        content=content,
        source_id=source_id,
        source_type=source_type,
        existing_beliefs=existing_beliefs,
    )


def register_belief(
    belief_id: str,
    content: str,
    source_id: str,
    source_type: str = "manual",
) -> CorroborationEvidence:
    """
    High-level function to register a belief for corroboration tracking.
    
    Args:
        belief_id: Unique ID for the belief
        content: Belief content
        source_id: ID of the source
        source_type: Type of source
    
    Returns:
        CorroborationEvidence for the registered belief
    """
    return get_detector().register_belief(
        belief_id=belief_id,
        content=content,
        source_id=source_id,
        source_type=source_type,
    )


def is_corroborated(belief_id: str) -> bool:
    """Check if a belief meets the corroboration threshold."""
    return get_detector().is_corroborated(belief_id)


def get_elevation_candidates(min_sources: Optional[int] = None) -> list[CorroborationEvidence]:
    """Get beliefs ready for elevation."""
    return get_detector().get_elevation_candidates(min_sources)
