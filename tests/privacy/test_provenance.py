"""Tests for provenance tiers (Issue #97).

Tests the ProvenanceTier enum and filter_provenance function
for different audience privacy levels.
"""

from dataclasses import dataclass

from valence.privacy.provenance import (
    ProvenanceChain,
    ProvenanceTier,
    filter_provenance,
    get_tier_for_audience,
)


class TestProvenanceTier:
    """Test ProvenanceTier enum."""

    def test_tier_values(self):
        """Ensure all required tiers exist with correct values."""
        assert ProvenanceTier.FULL.value == "full"
        assert ProvenanceTier.PARTIAL.value == "partial"
        assert ProvenanceTier.ANONYMOUS.value == "anonymous"
        assert ProvenanceTier.NONE.value == "none"

    def test_tier_count(self):
        """Exactly 4 tiers should exist."""
        assert len(ProvenanceTier) == 4


class TestProvenanceChain:
    """Test ProvenanceChain dataclass."""

    def test_empty_chain(self):
        """Empty chain should have sensible defaults."""
        chain = ProvenanceChain()
        assert chain.origin_did is None
        assert chain.hops == []
        assert chain.federation_path == []
        assert chain.corroborating_sources == 0

    def test_chain_with_data(self):
        """Chain should store all provided data."""
        chain = ProvenanceChain(
            origin_did="did:example:alice",
            origin_node="node:alice",
            origin_timestamp=1234567890.0,
            hops=[{"handler": "did:example:bob", "timestamp": 1234567891.0}],
            signature_verified=True,
            federation_path=["node:alice", "node:bob"],
            corroborating_sources=3,
        )

        assert chain.origin_did == "did:example:alice"
        assert chain.origin_node == "node:alice"
        assert len(chain.hops) == 1
        assert chain.signature_verified is True
        assert len(chain.federation_path) == 2
        assert chain.corroborating_sources == 3

    def test_to_dict_roundtrip(self):
        """Chain should survive dict serialization roundtrip."""
        original = ProvenanceChain(
            origin_did="did:example:alice",
            origin_signature=b"signature123",
            chain_signatures=[b"sig1", b"sig2"],
            hops=[{"a": 1}],
            federation_path=["node1", "node2"],
            corroborating_sources=5,
            metadata={"key": "value"},
        )

        as_dict = original.to_dict()
        restored = ProvenanceChain.from_dict(as_dict)

        assert restored.origin_did == original.origin_did
        assert restored.origin_signature == original.origin_signature
        assert restored.chain_signatures == original.chain_signatures
        assert restored.hops == original.hops
        assert restored.federation_path == original.federation_path
        assert restored.corroborating_sources == original.corroborating_sources
        assert restored.metadata == original.metadata


class TestFilterProvenanceNone:
    """Test NONE tier - no provenance information."""

    def test_none_tier_returns_empty(self):
        """NONE tier should return minimal info."""
        chain = ProvenanceChain(
            origin_did="did:example:alice",
            hops=[{"handler": "did:example:bob"}],
            corroborating_sources=10,
        )

        result = filter_provenance(chain, ProvenanceTier.NONE)

        assert result.tier == ProvenanceTier.NONE
        assert result.origin_did is None
        assert result.hops is None
        assert result.verified_by_sources is None

    def test_none_tier_dict(self):
        """NONE tier dict should only contain tier."""
        chain = ProvenanceChain(origin_did="did:example:alice")
        result = filter_provenance(chain, ProvenanceTier.NONE)

        result_dict = result.to_dict()
        assert result_dict == {"tier": "none"}

    def test_none_tier_str(self):
        """NONE tier string representation."""
        result = filter_provenance(ProvenanceChain(), ProvenanceTier.NONE)
        assert str(result) == "No provenance available"


class TestFilterProvenanceAnonymous:
    """Test ANONYMOUS tier - "verified by N sources" summary."""

    def test_anonymous_single_source(self):
        """Single source should show as '1 source'."""
        chain = ProvenanceChain(origin_did="did:example:alice")

        result = filter_provenance(chain, ProvenanceTier.ANONYMOUS)

        assert result.tier == ProvenanceTier.ANONYMOUS
        assert result.verified_by_sources == 1
        assert "1 source" in result.verification_summary
        # Should NOT expose identity
        assert result.origin_did is None

    def test_anonymous_multiple_sources(self):
        """Multiple sources should show count."""
        chain = ProvenanceChain(
            origin_did="did:example:alice",
            corroborating_sources=5,
        )

        result = filter_provenance(chain, ProvenanceTier.ANONYMOUS)

        assert result.verified_by_sources == 5
        assert "5 sources" in result.verification_summary

    def test_anonymous_verified(self):
        """Verified chain should indicate verification."""
        chain = ProvenanceChain(
            origin_did="did:example:alice",
            signature_verified=True,
        )

        result = filter_provenance(chain, ProvenanceTier.ANONYMOUS)

        assert "Verified" in result.verification_summary

    def test_anonymous_no_sources(self):
        """Empty chain should show unverified."""
        chain = ProvenanceChain()

        result = filter_provenance(chain, ProvenanceTier.ANONYMOUS)

        assert result.verified_by_sources == 0
        assert "Unverified" in result.verification_summary

    def test_anonymous_dict_structure(self):
        """ANONYMOUS tier dict should only have summary fields."""
        chain = ProvenanceChain(origin_did="did:example:alice")
        result = filter_provenance(chain, ProvenanceTier.ANONYMOUS)

        result_dict = result.to_dict()
        assert "tier" in result_dict
        assert "verified_by_sources" in result_dict
        assert "verification_summary" in result_dict
        # Should NOT have identity fields
        assert "origin_did" not in result_dict
        assert "hops" not in result_dict


class TestFilterProvenancePartial:
    """Test PARTIAL tier - chain structure, no identities."""

    def test_partial_shows_structure(self):
        """PARTIAL should show chain structure."""
        chain = ProvenanceChain(
            origin_did="did:example:alice",
            hops=[{"handler": "did:example:bob"}, {"handler": "did:example:carol"}],
            origin_signature=b"sig",
        )

        result = filter_provenance(chain, ProvenanceTier.PARTIAL)

        assert result.tier == ProvenanceTier.PARTIAL
        assert result.chain_length == 2
        assert result.has_origin is True
        assert result.signatures_present is True
        # Should NOT expose identities
        assert result.origin_did is None
        assert result.hops is None

    def test_partial_shows_verification_status(self):
        """PARTIAL should show if signatures are verified."""
        chain = ProvenanceChain(
            origin_did="did:example:alice",
            signature_verified=True,
        )

        result = filter_provenance(chain, ProvenanceTier.PARTIAL)

        assert result.signature_verified is True

    def test_partial_federation_path_length(self):
        """PARTIAL should count federation path length."""
        chain = ProvenanceChain(
            federation_path=["node1", "node2", "node3", "node4"],
        )

        result = filter_provenance(chain, ProvenanceTier.PARTIAL)

        assert result.chain_length == 4
        # Should NOT expose the actual path
        assert result.federation_path is None

    def test_partial_str(self):
        """PARTIAL tier string should show structure."""
        chain = ProvenanceChain(
            hops=[{}, {}, {}],
            signature_verified=True,
        )
        result = filter_provenance(chain, ProvenanceTier.PARTIAL)

        assert "3" in str(result)
        assert "✓" in str(result)


class TestFilterProvenanceFull:
    """Test FULL tier - complete chain with identities."""

    def test_full_exposes_origin(self):
        """FULL should expose origin identity."""
        chain = ProvenanceChain(
            origin_did="did:example:alice",
            origin_node="node:alice",
        )

        result = filter_provenance(chain, ProvenanceTier.FULL)

        assert result.tier == ProvenanceTier.FULL
        assert result.origin_did == "did:example:alice"
        assert result.origin_node == "node:alice"

    def test_full_exposes_hops(self):
        """FULL should expose hop details."""
        hops = [
            {"handler": "did:example:bob", "timestamp": 1234567891.0},
            {"handler": "did:example:carol", "timestamp": 1234567892.0},
        ]
        chain = ProvenanceChain(
            origin_did="did:example:alice",
            hops=hops,
        )

        result = filter_provenance(chain, ProvenanceTier.FULL)

        assert result.hops is not None
        assert len(result.hops) == 2
        assert result.hops[0]["handler"] == "did:example:bob"

    def test_full_exposes_federation_path(self):
        """FULL should expose federation path."""
        chain = ProvenanceChain(
            federation_path=["node:alice", "node:bob", "node:carol"],
        )

        result = filter_provenance(chain, ProvenanceTier.FULL)

        assert result.federation_path == ["node:alice", "node:bob", "node:carol"]

    def test_full_includes_structure_info(self):
        """FULL should also include structural info."""
        chain = ProvenanceChain(
            origin_did="did:example:alice",
            hops=[{}, {}],
            origin_signature=b"sig",
            signature_verified=True,
        )

        result = filter_provenance(chain, ProvenanceTier.FULL)

        assert result.chain_length == 2
        assert result.has_origin is True
        assert result.signatures_present is True
        assert result.signature_verified is True

    def test_full_dict_has_all_fields(self):
        """FULL tier dict should have all fields."""
        chain = ProvenanceChain(
            origin_did="did:example:alice",
            origin_node="node:alice",
            hops=[{"a": 1}],
            federation_path=["n1", "n2"],
            origin_signature=b"sig",
            signature_verified=True,
        )
        result = filter_provenance(chain, ProvenanceTier.FULL)

        result_dict = result.to_dict()
        assert result_dict["origin_did"] == "did:example:alice"
        assert result_dict["origin_node"] == "node:alice"
        assert result_dict["hops"] == [{"a": 1}]
        assert result_dict["federation_path"] == ["n1", "n2"]
        assert result_dict["chain_length"] == 2
        assert result_dict["has_origin"] is True
        assert result_dict["signatures_present"] is True
        assert result_dict["signature_verified"] is True

    def test_full_str(self):
        """FULL tier string should show origin."""
        chain = ProvenanceChain(
            origin_did="did:example:alice",
            hops=[{}, {}],
            signature_verified=True,
        )
        result = filter_provenance(chain, ProvenanceTier.FULL)

        output = str(result)
        assert "did:example:alice" in output
        assert "2 hops" in output
        assert "verified" in output


class TestFilterProvenanceInputTypes:
    """Test filter_provenance with different input types."""

    def test_dict_input(self):
        """Should accept dict input."""
        chain_dict = {
            "origin_did": "did:example:alice",
            "hops": [{"handler": "bob"}],
            "corroborating_sources": 3,
        }

        result = filter_provenance(chain_dict, ProvenanceTier.FULL)

        assert result.origin_did == "did:example:alice"
        assert len(result.hops) == 1

    def test_consent_chain_like_input(self):
        """Should accept ConsentChainEntry-like objects."""

        @dataclass
        class FakeConsentChain:
            id: str = "chain-123"
            origin_sharer: str = "did:example:alice"
            origin_timestamp: float = 1234567890.0
            hops: list = None
            origin_signature: bytes = b"sig"

            def __post_init__(self):
                if self.hops is None:
                    self.hops = []

        fake_chain = FakeConsentChain(hops=[{"handler": "bob"}])

        result = filter_provenance(fake_chain, ProvenanceTier.FULL)

        assert result.origin_did == "did:example:alice"

    def test_belief_provenance_like_input(self):
        """Should accept BeliefProvenance-like objects."""

        @dataclass
        class FakeBeliefProvenance:
            origin_node_id: str = "node-123"
            federation_path: list = None
            signature_verified: bool = True
            share_level: str = "with_provenance"
            hop_count: int = 2
            origin_signature: str = "sig123"
            signed_at: float = 1234567890.0

            def __post_init__(self):
                if self.federation_path is None:
                    self.federation_path = []

        fake_prov = FakeBeliefProvenance(federation_path=["n1", "n2"])

        result = filter_provenance(fake_prov, ProvenanceTier.PARTIAL)

        assert result.chain_length == 2
        assert result.signature_verified is True

    def test_unknown_type_creates_empty(self):
        """Unknown types should create empty chain."""
        result = filter_provenance("not a chain", ProvenanceTier.FULL)

        assert result.tier == ProvenanceTier.FULL
        assert result.origin_did is None
        assert result.chain_length == 0


class TestGetTierForAudience:
    """Test audience-to-tier mapping."""

    def test_owner_gets_full(self):
        """Owner should get FULL tier."""
        assert get_tier_for_audience("owner") == ProvenanceTier.FULL
        assert get_tier_for_audience("admin") == ProvenanceTier.FULL
        assert get_tier_for_audience("self") == ProvenanceTier.FULL

    def test_trusted_gets_partial(self):
        """Trusted collaborators should get PARTIAL tier."""
        assert get_tier_for_audience("trusted") == ProvenanceTier.PARTIAL
        assert get_tier_for_audience("collaborator") == ProvenanceTier.PARTIAL
        assert get_tier_for_audience("federation") == ProvenanceTier.PARTIAL
        assert get_tier_for_audience("node") == ProvenanceTier.PARTIAL

    def test_public_gets_anonymous(self):
        """Public audience should get ANONYMOUS tier."""
        assert get_tier_for_audience("public") == ProvenanceTier.ANONYMOUS
        assert get_tier_for_audience("reader") == ProvenanceTier.ANONYMOUS
        assert get_tier_for_audience("viewer") == ProvenanceTier.ANONYMOUS

    def test_anonymous_gets_none(self):
        """Minimal/anonymous audience gets NONE tier."""
        assert get_tier_for_audience("anonymous") == ProvenanceTier.NONE
        assert get_tier_for_audience("minimal") == ProvenanceTier.NONE

    def test_case_insensitive(self):
        """Audience type should be case-insensitive."""
        assert get_tier_for_audience("OWNER") == ProvenanceTier.FULL
        assert get_tier_for_audience("Public") == ProvenanceTier.ANONYMOUS

    def test_unknown_defaults_to_anonymous(self):
        """Unknown audience types default to ANONYMOUS."""
        assert get_tier_for_audience("unknown_type") == ProvenanceTier.ANONYMOUS
        assert get_tier_for_audience("random") == ProvenanceTier.ANONYMOUS

    def test_custom_mapping(self):
        """Custom mapping should override defaults."""
        custom = {
            "vip": ProvenanceTier.FULL,
            "public": ProvenanceTier.NONE,  # Override default
        }

        assert get_tier_for_audience("vip", custom) == ProvenanceTier.FULL
        assert get_tier_for_audience("public", custom) == ProvenanceTier.NONE
        # Default still works for non-overridden
        assert get_tier_for_audience("owner", custom) == ProvenanceTier.FULL


class TestTierProgression:
    """Test that tiers form a proper progression of detail."""

    def test_full_has_more_than_partial(self):
        """FULL should have more info than PARTIAL."""
        chain = ProvenanceChain(
            origin_did="did:example:alice",
            origin_node="node:alice",
            hops=[{"a": 1}, {"b": 2}],
            federation_path=["n1", "n2"],
            origin_signature=b"sig",
        )

        full = filter_provenance(chain, ProvenanceTier.FULL)
        partial = filter_provenance(chain, ProvenanceTier.PARTIAL)

        # FULL has identities, PARTIAL doesn't
        assert full.origin_did is not None
        assert partial.origin_did is None

        # Both have structure
        assert full.chain_length == partial.chain_length

    def test_partial_has_more_than_anonymous(self):
        """PARTIAL should have more info than ANONYMOUS."""
        chain = ProvenanceChain(
            origin_did="did:example:alice",
            hops=[{}, {}],
            origin_signature=b"sig",
        )

        partial = filter_provenance(chain, ProvenanceTier.PARTIAL)
        anon = filter_provenance(chain, ProvenanceTier.ANONYMOUS)

        # PARTIAL has structure
        assert partial.chain_length is not None
        assert anon.chain_length is None

        # ANONYMOUS has summary
        assert anon.verification_summary is not None

    def test_anonymous_has_more_than_none(self):
        """ANONYMOUS should have more info than NONE."""
        chain = ProvenanceChain(
            origin_did="did:example:alice",
            corroborating_sources=5,
        )

        anon = filter_provenance(chain, ProvenanceTier.ANONYMOUS)
        none = filter_provenance(chain, ProvenanceTier.NONE)

        # ANONYMOUS has summary
        assert anon.verified_by_sources == 5
        assert anon.verification_summary is not None

        # NONE has nothing
        assert none.verified_by_sources is None
        assert none.verification_summary is None


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_chain_all_tiers(self):
        """Empty chain should work for all tiers."""
        chain = ProvenanceChain()

        for tier in ProvenanceTier:
            result = filter_provenance(chain, tier)
            assert result.tier == tier

    def test_hops_are_copied_not_referenced(self):
        """Filtered hops should be a copy, not reference."""
        original_hops = [{"handler": "alice", "secret": "data"}]
        chain = ProvenanceChain(hops=original_hops)

        result = filter_provenance(chain, ProvenanceTier.FULL)

        # Modify filtered result
        result.hops[0]["modified"] = True

        # Original should be unchanged
        assert "modified" not in original_hops[0]

    def test_federation_path_copied(self):
        """Federation path should be copied."""
        original_path = ["n1", "n2"]
        chain = ProvenanceChain(federation_path=original_path)

        result = filter_provenance(chain, ProvenanceTier.FULL)

        # Modify result
        result.federation_path.append("n3")

        # Original unchanged
        assert len(original_path) == 2

    def test_corroboration_from_attestations(self):
        """Source count should consider attestations."""
        chain = ProvenanceChain(
            corroboration_attestations=[
                {"issuer": "a", "claim": "x"},
                {"issuer": "b", "claim": "x"},
                {"issuer": "c", "claim": "x"},
            ],
        )

        result = filter_provenance(chain, ProvenanceTier.ANONYMOUS)

        assert result.verified_by_sources >= 3
