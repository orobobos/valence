# Valence Provenance Tiers
"""
Provenance tier system for controlling what provenance information
different audiences can see.

Tiers:
- FULL: Complete chain with all identities
- PARTIAL: Chain structure without identities  
- ANONYMOUS: "Verified by N sources" without details
- NONE: No provenance exposed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Optional


class ProvenanceTier(Enum):
    """Provenance visibility tiers for different audiences."""
    
    FULL = "full"  # Complete chain with all identities
    PARTIAL = "partial"  # Chain structure without identities
    ANONYMOUS = "anonymous"  # "Verified by N sources" without details
    NONE = "none"  # No provenance exposed


class TrustLevel(Enum):
    """Trust levels that determine provenance tier access."""
    
    OWNER = auto()  # Original owner - sees everything
    TRUSTED = auto()  # Highly trusted recipients - full provenance
    KNOWN = auto()  # Known but not fully trusted - partial provenance
    VERIFIED = auto()  # Verified but anonymous - anonymous provenance
    PUBLIC = auto()  # Public/unknown - no provenance


# Default mapping from trust level to provenance tier
DEFAULT_TRUST_TIER_MAP: dict[TrustLevel, ProvenanceTier] = {
    TrustLevel.OWNER: ProvenanceTier.FULL,
    TrustLevel.TRUSTED: ProvenanceTier.FULL,
    TrustLevel.KNOWN: ProvenanceTier.PARTIAL,
    TrustLevel.VERIFIED: ProvenanceTier.ANONYMOUS,
    TrustLevel.PUBLIC: ProvenanceTier.NONE,
}


@dataclass
class ConsentChainEntry:
    """
    A single entry in the consent/provenance chain.
    
    Tracks who consented to share and when.
    """
    
    identity: str  # Who shared (email, user ID, etc.)
    identity_type: str  # Type of identity (email, user_id, agent_id, etc.)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    action: str = "shared"  # What action was taken (shared, forwarded, etc.)
    context: Optional[str] = None  # Optional context about the share
    metadata: dict = field(default_factory=dict)  # Additional metadata
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "identity": self.identity,
            "identity_type": self.identity_type,
            "timestamp": self.timestamp.isoformat(),
            "action": self.action,
            "context": self.context,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ConsentChainEntry":
        """Create from dictionary."""
        return cls(
            identity=data["identity"],
            identity_type=data["identity_type"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            action=data.get("action", "shared"),
            context=data.get("context"),
            metadata=data.get("metadata", {}),
        )
    
    def anonymize(self) -> "ConsentChainEntry":
        """Return anonymized version of this entry (no identity info)."""
        return ConsentChainEntry(
            identity="[redacted]",
            identity_type=self.identity_type,
            timestamp=self.timestamp,
            action=self.action,
            context=None,  # Context may leak identity info
            metadata={},  # Metadata may contain sensitive info
        )


@dataclass
class ProvenanceChain:
    """
    The full provenance chain tracking consent and sharing history.
    
    Maintains an ordered list of who shared content and when.
    """
    
    entries: list[ConsentChainEntry] = field(default_factory=list)
    
    @property
    def length(self) -> int:
        """Number of entries in the chain."""
        return len(self.entries)
    
    @property
    def source_count(self) -> int:
        """Number of unique sources in the chain."""
        return len(set(e.identity for e in self.entries))
    
    @property
    def origin(self) -> Optional[ConsentChainEntry]:
        """The original source entry."""
        return self.entries[0] if self.entries else None
    
    @property
    def latest(self) -> Optional[ConsentChainEntry]:
        """The most recent entry."""
        return self.entries[-1] if self.entries else None
    
    def add_entry(
        self,
        identity: str,
        identity_type: str,
        action: str = "shared",
        context: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> ConsentChainEntry:
        """Add a new entry to the chain."""
        entry = ConsentChainEntry(
            identity=identity,
            identity_type=identity_type,
            action=action,
            context=context,
            metadata=metadata or {},
        )
        self.entries.append(entry)
        return entry
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "entries": [e.to_dict() for e in self.entries],
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ProvenanceChain":
        """Create from dictionary."""
        return cls(
            entries=[ConsentChainEntry.from_dict(e) for e in data.get("entries", [])],
        )
    
    def copy(self) -> "ProvenanceChain":
        """Create a deep copy of this chain."""
        return ProvenanceChain(
            entries=[
                ConsentChainEntry(
                    identity=e.identity,
                    identity_type=e.identity_type,
                    timestamp=e.timestamp,
                    action=e.action,
                    context=e.context,
                    metadata=e.metadata.copy(),
                )
                for e in self.entries
            ]
        )


@dataclass
class FilteredProvenance:
    """
    Provenance information filtered according to a tier.
    
    This is what gets exposed to recipients based on their trust level.
    """
    
    tier: ProvenanceTier
    
    # FULL tier fields
    chain: Optional[ProvenanceChain] = None
    
    # PARTIAL tier fields (chain structure without identities)
    chain_length: Optional[int] = None
    chain_structure: Optional[list[dict]] = None  # Anonymized entries
    
    # ANONYMOUS tier fields
    source_count: Optional[int] = None
    verification_statement: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        result = {"tier": self.tier.value}
        
        if self.tier == ProvenanceTier.FULL and self.chain:
            result["chain"] = self.chain.to_dict()
        elif self.tier == ProvenanceTier.PARTIAL:
            result["chain_length"] = self.chain_length
            result["chain_structure"] = self.chain_structure
        elif self.tier == ProvenanceTier.ANONYMOUS:
            result["source_count"] = self.source_count
            result["verification_statement"] = self.verification_statement
        # NONE tier - return minimal info
        
        return result


class ProvenanceFilter:
    """
    Filters provenance chains based on recipient trust level.
    
    Implements the tiered visibility system.
    """
    
    def __init__(
        self,
        trust_tier_map: Optional[dict[TrustLevel, ProvenanceTier]] = None,
    ):
        """
        Initialize the filter.
        
        Args:
            trust_tier_map: Optional custom mapping from trust level to tier.
                           Defaults to DEFAULT_TRUST_TIER_MAP.
        """
        self._trust_tier_map = trust_tier_map or DEFAULT_TRUST_TIER_MAP.copy()
    
    def get_tier_for_trust_level(self, trust_level: TrustLevel) -> ProvenanceTier:
        """Get the provenance tier for a given trust level."""
        return self._trust_tier_map.get(trust_level, ProvenanceTier.NONE)
    
    def set_tier_for_trust_level(
        self,
        trust_level: TrustLevel,
        tier: ProvenanceTier,
    ) -> None:
        """Set a custom tier mapping for a trust level."""
        self._trust_tier_map[trust_level] = tier
    
    def filter(
        self,
        chain: ProvenanceChain,
        tier: ProvenanceTier,
    ) -> FilteredProvenance:
        """
        Filter a provenance chain according to the specified tier.
        
        Args:
            chain: The full provenance chain
            tier: The tier to filter to
        
        Returns:
            FilteredProvenance with appropriate level of detail
        """
        if tier == ProvenanceTier.NONE:
            return FilteredProvenance(tier=ProvenanceTier.NONE)
        
        if tier == ProvenanceTier.ANONYMOUS:
            return self._filter_anonymous(chain)
        
        if tier == ProvenanceTier.PARTIAL:
            return self._filter_partial(chain)
        
        # FULL tier - return complete chain
        return FilteredProvenance(
            tier=ProvenanceTier.FULL,
            chain=chain.copy(),
        )
    
    def filter_for_recipient(
        self,
        chain: ProvenanceChain,
        trust_level: TrustLevel,
    ) -> FilteredProvenance:
        """
        Filter provenance based on recipient's trust level.
        
        Args:
            chain: The full provenance chain
            trust_level: The recipient's trust level
        
        Returns:
            FilteredProvenance appropriate for the trust level
        """
        tier = self.get_tier_for_trust_level(trust_level)
        return self.filter(chain, tier)
    
    def _filter_anonymous(self, chain: ProvenanceChain) -> FilteredProvenance:
        """Create anonymous provenance (just counts and verification)."""
        source_count = chain.source_count
        
        if source_count == 0:
            statement = "Unverified content"
        elif source_count == 1:
            statement = "Verified by 1 source"
        else:
            statement = f"Verified by {source_count} sources"
        
        return FilteredProvenance(
            tier=ProvenanceTier.ANONYMOUS,
            source_count=source_count,
            verification_statement=statement,
        )
    
    def _filter_partial(self, chain: ProvenanceChain) -> FilteredProvenance:
        """Create partial provenance (structure without identities)."""
        anonymized_entries = []
        
        for entry in chain.entries:
            anonymized_entries.append({
                "identity_type": entry.identity_type,
                "timestamp": entry.timestamp.isoformat(),
                "action": entry.action,
                # No identity, context, or metadata
            })
        
        return FilteredProvenance(
            tier=ProvenanceTier.PARTIAL,
            chain_length=chain.length,
            chain_structure=anonymized_entries,
        )


# Module-level default filter
_default_filter: Optional[ProvenanceFilter] = None


def get_filter() -> ProvenanceFilter:
    """Get the default provenance filter."""
    global _default_filter
    if _default_filter is None:
        _default_filter = ProvenanceFilter()
    return _default_filter


def filter_provenance(
    chain: ProvenanceChain,
    tier: ProvenanceTier,
) -> FilteredProvenance:
    """
    High-level function to filter provenance by tier.
    
    Args:
        chain: The full provenance chain
        tier: The tier to filter to
    
    Returns:
        FilteredProvenance with appropriate level of detail
    """
    return get_filter().filter(chain, tier)


def filter_provenance_for_recipient(
    chain: ProvenanceChain,
    trust_level: TrustLevel,
) -> FilteredProvenance:
    """
    High-level function to filter provenance by recipient trust level.
    
    Args:
        chain: The full provenance chain
        trust_level: The recipient's trust level
    
    Returns:
        FilteredProvenance appropriate for the trust level
    """
    return get_filter().filter_for_recipient(chain, trust_level)
