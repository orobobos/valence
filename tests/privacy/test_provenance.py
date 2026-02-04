# Tests for Provenance Tiers
"""
Test suite for provenance tier system.
"""

import pytest
from datetime import datetime, timezone

from valence.privacy.provenance import (
    ProvenanceTier,
    TrustLevel,
    ConsentChainEntry,
    ProvenanceChain,
    FilteredProvenance,
    ProvenanceFilter,
    get_filter,
    filter_provenance,
    filter_provenance_for_recipient,
    DEFAULT_TRUST_TIER_MAP,
)
import valence.privacy.provenance as provenance_module


class TestProvenanceTier:
    """Tests for ProvenanceTier enum."""
    
    def test_tier_values(self):
        """Tiers should have expected string values."""
        assert ProvenanceTier.FULL.value == "full"
        assert ProvenanceTier.PARTIAL.value == "partial"
        assert ProvenanceTier.ANONYMOUS.value == "anonymous"
        assert ProvenanceTier.NONE.value == "none"
    
    def test_all_tiers_defined(self):
        """All four tiers should be defined."""
        assert len(ProvenanceTier) == 4


class TestTrustLevel:
    """Tests for TrustLevel enum."""
    
    def test_all_trust_levels_defined(self):
        """All trust levels should be defined."""
        assert len(TrustLevel) == 5
        assert TrustLevel.OWNER is not None
        assert TrustLevel.TRUSTED is not None
        assert TrustLevel.KNOWN is not None
        assert TrustLevel.VERIFIED is not None
        assert TrustLevel.PUBLIC is not None
    
    def test_default_trust_tier_mapping(self):
        """Default mapping should map all trust levels to appropriate tiers."""
        assert DEFAULT_TRUST_TIER_MAP[TrustLevel.OWNER] == ProvenanceTier.FULL
        assert DEFAULT_TRUST_TIER_MAP[TrustLevel.TRUSTED] == ProvenanceTier.FULL
        assert DEFAULT_TRUST_TIER_MAP[TrustLevel.KNOWN] == ProvenanceTier.PARTIAL
        assert DEFAULT_TRUST_TIER_MAP[TrustLevel.VERIFIED] == ProvenanceTier.ANONYMOUS
        assert DEFAULT_TRUST_TIER_MAP[TrustLevel.PUBLIC] == ProvenanceTier.NONE


class TestConsentChainEntry:
    """Tests for ConsentChainEntry."""
    
    def test_create_entry(self):
        """Should create entry with all fields."""
        entry = ConsentChainEntry(
            identity="alice@example.com",
            identity_type="email",
            action="shared",
            context="Shared for review",
            metadata={"department": "engineering"},
        )
        
        assert entry.identity == "alice@example.com"
        assert entry.identity_type == "email"
        assert entry.action == "shared"
        assert entry.context == "Shared for review"
        assert entry.metadata == {"department": "engineering"}
        assert entry.timestamp is not None
    
    def test_entry_default_action(self):
        """Default action should be 'shared'."""
        entry = ConsentChainEntry(
            identity="bob@example.com",
            identity_type="email",
        )
        assert entry.action == "shared"
    
    def test_entry_to_dict(self):
        """Entry should serialize to dict."""
        entry = ConsentChainEntry(
            identity="alice@example.com",
            identity_type="email",
            action="created",
            context="Original creator",
        )
        
        data = entry.to_dict()
        
        assert data["identity"] == "alice@example.com"
        assert data["identity_type"] == "email"
        assert data["action"] == "created"
        assert data["context"] == "Original creator"
        assert "timestamp" in data
    
    def test_entry_from_dict(self):
        """Entry should deserialize from dict."""
        data = {
            "identity": "bob@example.com",
            "identity_type": "user_id",
            "timestamp": "2025-01-15T10:00:00+00:00",
            "action": "forwarded",
            "context": "Forwarded to team",
            "metadata": {"team": "sales"},
        }
        
        entry = ConsentChainEntry.from_dict(data)
        
        assert entry.identity == "bob@example.com"
        assert entry.identity_type == "user_id"
        assert entry.action == "forwarded"
        assert entry.context == "Forwarded to team"
        assert entry.metadata == {"team": "sales"}
    
    def test_entry_anonymize(self):
        """Anonymize should redact identity info."""
        entry = ConsentChainEntry(
            identity="alice@example.com",
            identity_type="email",
            action="shared",
            context="Shared with confidential info",
            metadata={"recipient_name": "Bob"},
        )
        
        anonymized = entry.anonymize()
        
        assert anonymized.identity == "[redacted]"
        assert anonymized.identity_type == "email"  # Type preserved
        assert anonymized.action == "shared"  # Action preserved
        assert anonymized.context is None  # Context removed
        assert anonymized.metadata == {}  # Metadata removed
        assert anonymized.timestamp == entry.timestamp  # Timestamp preserved


class TestProvenanceChain:
    """Tests for ProvenanceChain."""
    
    def test_empty_chain(self):
        """Empty chain should have length 0."""
        chain = ProvenanceChain()
        
        assert chain.length == 0
        assert chain.source_count == 0
        assert chain.origin is None
        assert chain.latest is None
    
    def test_add_entry(self):
        """Should add entries to chain."""
        chain = ProvenanceChain()
        
        entry = chain.add_entry(
            identity="alice@example.com",
            identity_type="email",
            action="created",
        )
        
        assert chain.length == 1
        assert entry.identity == "alice@example.com"
        assert chain.origin == entry
        assert chain.latest == entry
    
    def test_chain_tracks_order(self):
        """Chain should preserve entry order."""
        chain = ProvenanceChain()
        
        entry1 = chain.add_entry("alice@example.com", "email", action="created")
        entry2 = chain.add_entry("bob@example.com", "email", action="shared")
        entry3 = chain.add_entry("charlie@example.com", "email", action="forwarded")
        
        assert chain.length == 3
        assert chain.origin == entry1
        assert chain.latest == entry3
        assert chain.entries[1] == entry2
    
    def test_source_count_unique(self):
        """Source count should count unique identities."""
        chain = ProvenanceChain()
        
        chain.add_entry("alice@example.com", "email")
        chain.add_entry("bob@example.com", "email")
        chain.add_entry("alice@example.com", "email")  # Duplicate
        
        assert chain.source_count == 2  # alice and bob
    
    def test_chain_to_dict(self):
        """Chain should serialize to dict."""
        chain = ProvenanceChain()
        chain.add_entry("alice@example.com", "email", action="created")
        chain.add_entry("bob@example.com", "email", action="shared")
        
        data = chain.to_dict()
        
        assert "entries" in data
        assert len(data["entries"]) == 2
    
    def test_chain_from_dict(self):
        """Chain should deserialize from dict."""
        data = {
            "entries": [
                {
                    "identity": "alice@example.com",
                    "identity_type": "email",
                    "timestamp": "2025-01-15T10:00:00+00:00",
                    "action": "created",
                },
                {
                    "identity": "bob@example.com",
                    "identity_type": "email",
                    "timestamp": "2025-01-15T11:00:00+00:00",
                    "action": "shared",
                },
            ]
        }
        
        chain = ProvenanceChain.from_dict(data)
        
        assert chain.length == 2
        assert chain.origin.identity == "alice@example.com"
        assert chain.latest.identity == "bob@example.com"
    
    def test_chain_copy_is_deep(self):
        """Copy should create independent chain."""
        chain = ProvenanceChain()
        chain.add_entry("alice@example.com", "email", metadata={"key": "value"})
        
        copy = chain.copy()
        
        # Modify original
        chain.add_entry("bob@example.com", "email")
        chain.entries[0].metadata["new_key"] = "new_value"
        
        # Copy should be unchanged
        assert copy.length == 1
        assert "new_key" not in copy.entries[0].metadata


class TestProvenanceFilter:
    """Tests for ProvenanceFilter."""
    
    @pytest.fixture
    def sample_chain(self):
        """Create a sample provenance chain for testing."""
        chain = ProvenanceChain()
        chain.add_entry(
            "alice@example.com",
            "email",
            action="created",
            context="Original document",
        )
        chain.add_entry(
            "bob@example.com",
            "email",
            action="shared",
            context="Shared with team",
        )
        chain.add_entry(
            "charlie@example.com",
            "email",
            action="forwarded",
            context="Forwarded to client",
        )
        return chain
    
    @pytest.fixture
    def filter(self):
        return ProvenanceFilter()
    
    def test_filter_full_returns_complete_chain(self, filter, sample_chain):
        """FULL tier should return complete chain."""
        result = filter.filter(sample_chain, ProvenanceTier.FULL)
        
        assert result.tier == ProvenanceTier.FULL
        assert result.chain is not None
        assert result.chain.length == 3
        assert result.chain.origin.identity == "alice@example.com"
    
    def test_filter_full_returns_copy(self, filter, sample_chain):
        """FULL tier should return a copy, not the original."""
        result = filter.filter(sample_chain, ProvenanceTier.FULL)
        
        # Modify original
        sample_chain.add_entry("dave@example.com", "email")
        
        # Result should be unchanged
        assert result.chain.length == 3
    
    def test_filter_partial_removes_identities(self, filter, sample_chain):
        """PARTIAL tier should remove identities but keep structure."""
        result = filter.filter(sample_chain, ProvenanceTier.PARTIAL)
        
        assert result.tier == ProvenanceTier.PARTIAL
        assert result.chain is None  # No full chain
        assert result.chain_length == 3
        assert result.chain_structure is not None
        assert len(result.chain_structure) == 3
        
        # Check structure has timestamps and actions but no identities
        for entry in result.chain_structure:
            assert "identity" not in entry
            assert "context" not in entry
            assert "identity_type" in entry
            assert "timestamp" in entry
            assert "action" in entry
    
    def test_filter_anonymous_returns_count(self, filter, sample_chain):
        """ANONYMOUS tier should return source count and statement."""
        result = filter.filter(sample_chain, ProvenanceTier.ANONYMOUS)
        
        assert result.tier == ProvenanceTier.ANONYMOUS
        assert result.chain is None
        assert result.chain_structure is None
        assert result.source_count == 3
        assert result.verification_statement == "Verified by 3 sources"
    
    def test_filter_anonymous_singular(self, filter):
        """ANONYMOUS tier should use singular for 1 source."""
        chain = ProvenanceChain()
        chain.add_entry("alice@example.com", "email")
        
        result = filter.filter(chain, ProvenanceTier.ANONYMOUS)
        
        assert result.verification_statement == "Verified by 1 source"
    
    def test_filter_anonymous_empty_chain(self, filter):
        """ANONYMOUS tier should handle empty chain."""
        chain = ProvenanceChain()
        
        result = filter.filter(chain, ProvenanceTier.ANONYMOUS)
        
        assert result.source_count == 0
        assert result.verification_statement == "Unverified content"
    
    def test_filter_none_returns_minimal(self, filter, sample_chain):
        """NONE tier should return minimal information."""
        result = filter.filter(sample_chain, ProvenanceTier.NONE)
        
        assert result.tier == ProvenanceTier.NONE
        assert result.chain is None
        assert result.chain_structure is None
        assert result.source_count is None
        assert result.verification_statement is None
    
    def test_filter_for_recipient_owner(self, filter, sample_chain):
        """Owner should get FULL provenance."""
        result = filter.filter_for_recipient(sample_chain, TrustLevel.OWNER)
        
        assert result.tier == ProvenanceTier.FULL
        assert result.chain is not None
    
    def test_filter_for_recipient_trusted(self, filter, sample_chain):
        """Trusted recipient should get FULL provenance."""
        result = filter.filter_for_recipient(sample_chain, TrustLevel.TRUSTED)
        
        assert result.tier == ProvenanceTier.FULL
        assert result.chain is not None
    
    def test_filter_for_recipient_known(self, filter, sample_chain):
        """Known recipient should get PARTIAL provenance."""
        result = filter.filter_for_recipient(sample_chain, TrustLevel.KNOWN)
        
        assert result.tier == ProvenanceTier.PARTIAL
        assert result.chain_structure is not None
    
    def test_filter_for_recipient_verified(self, filter, sample_chain):
        """Verified recipient should get ANONYMOUS provenance."""
        result = filter.filter_for_recipient(sample_chain, TrustLevel.VERIFIED)
        
        assert result.tier == ProvenanceTier.ANONYMOUS
        assert result.verification_statement is not None
    
    def test_filter_for_recipient_public(self, filter, sample_chain):
        """Public recipient should get NONE provenance."""
        result = filter.filter_for_recipient(sample_chain, TrustLevel.PUBLIC)
        
        assert result.tier == ProvenanceTier.NONE
    
    def test_custom_trust_tier_mapping(self, sample_chain):
        """Should support custom trust tier mapping."""
        custom_map = {
            TrustLevel.OWNER: ProvenanceTier.FULL,
            TrustLevel.TRUSTED: ProvenanceTier.PARTIAL,  # More restrictive
            TrustLevel.KNOWN: ProvenanceTier.ANONYMOUS,
            TrustLevel.VERIFIED: ProvenanceTier.NONE,
            TrustLevel.PUBLIC: ProvenanceTier.NONE,
        }
        
        filter = ProvenanceFilter(trust_tier_map=custom_map)
        
        result = filter.filter_for_recipient(sample_chain, TrustLevel.TRUSTED)
        assert result.tier == ProvenanceTier.PARTIAL
        
        result = filter.filter_for_recipient(sample_chain, TrustLevel.KNOWN)
        assert result.tier == ProvenanceTier.ANONYMOUS
    
    def test_set_tier_for_trust_level(self, filter, sample_chain):
        """Should be able to update mapping dynamically."""
        filter.set_tier_for_trust_level(TrustLevel.PUBLIC, ProvenanceTier.ANONYMOUS)
        
        result = filter.filter_for_recipient(sample_chain, TrustLevel.PUBLIC)
        
        assert result.tier == ProvenanceTier.ANONYMOUS


class TestFilteredProvenance:
    """Tests for FilteredProvenance serialization."""
    
    def test_to_dict_full(self):
        """FULL tier should serialize chain."""
        chain = ProvenanceChain()
        chain.add_entry("alice@example.com", "email")
        
        filtered = FilteredProvenance(
            tier=ProvenanceTier.FULL,
            chain=chain,
        )
        
        data = filtered.to_dict()
        
        assert data["tier"] == "full"
        assert "chain" in data
        assert len(data["chain"]["entries"]) == 1
    
    def test_to_dict_partial(self):
        """PARTIAL tier should serialize structure."""
        filtered = FilteredProvenance(
            tier=ProvenanceTier.PARTIAL,
            chain_length=3,
            chain_structure=[
                {"identity_type": "email", "action": "shared"},
            ],
        )
        
        data = filtered.to_dict()
        
        assert data["tier"] == "partial"
        assert data["chain_length"] == 3
        assert "chain_structure" in data
    
    def test_to_dict_anonymous(self):
        """ANONYMOUS tier should serialize statement."""
        filtered = FilteredProvenance(
            tier=ProvenanceTier.ANONYMOUS,
            source_count=5,
            verification_statement="Verified by 5 sources",
        )
        
        data = filtered.to_dict()
        
        assert data["tier"] == "anonymous"
        assert data["source_count"] == 5
        assert data["verification_statement"] == "Verified by 5 sources"
    
    def test_to_dict_none(self):
        """NONE tier should serialize minimally."""
        filtered = FilteredProvenance(tier=ProvenanceTier.NONE)
        
        data = filtered.to_dict()
        
        assert data == {"tier": "none"}


class TestHighLevelAPI:
    """Tests for high-level provenance API."""
    
    @pytest.fixture(autouse=True)
    def reset_globals(self):
        """Reset global state before each test."""
        provenance_module._default_filter = None
    
    def test_get_filter_returns_singleton(self):
        """get_filter should return the same instance."""
        filter1 = get_filter()
        filter2 = get_filter()
        
        assert filter1 is filter2
    
    def test_filter_provenance_function(self):
        """filter_provenance should work as expected."""
        chain = ProvenanceChain()
        chain.add_entry("alice@example.com", "email")
        
        result = filter_provenance(chain, ProvenanceTier.ANONYMOUS)
        
        assert result.tier == ProvenanceTier.ANONYMOUS
        assert result.source_count == 1
    
    def test_filter_provenance_for_recipient_function(self):
        """filter_provenance_for_recipient should work as expected."""
        chain = ProvenanceChain()
        chain.add_entry("alice@example.com", "email")
        chain.add_entry("bob@example.com", "email")
        
        result = filter_provenance_for_recipient(chain, TrustLevel.KNOWN)
        
        assert result.tier == ProvenanceTier.PARTIAL
        assert result.chain_length == 2
