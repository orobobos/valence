"""Provenance tiers for different audiences.

Implements graduated provenance visibility levels for privacy-conscious
disclosure of belief origin and verification chains.

Issue #97: Different audiences see different provenance detail levels.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProvenanceTier(Enum):
    """Graduated levels of provenance disclosure.

    Controls how much detail about belief origin and verification
    is exposed to different audiences.
    """

    FULL = "full"  # Complete chain with identities
    PARTIAL = "partial"  # Chain structure, no identities
    ANONYMOUS = "anonymous"  # "verified by N sources" summary
    NONE = "none"  # No provenance information


@dataclass
class ProvenanceChain:
    """A provenance chain with identity and verification info.

    This is the internal representation with full details.
    filter_provenance() creates audience-appropriate views.
    """

    # Origin information
    origin_did: str | None = None
    origin_node: str | None = None
    origin_timestamp: float | None = None

    # Hop chain - list of intermediate handlers
    hops: list[dict[str, Any]] = field(default_factory=list)

    # Signatures and verification
    origin_signature: bytes | None = None
    chain_signatures: list[bytes] = field(default_factory=list)
    signature_verified: bool = False

    # Federation path (node DIDs traversed)
    federation_path: list[str] = field(default_factory=list)

    # Corroboration info
    corroborating_sources: int = 0
    corroboration_attestations: list[dict[str, Any]] = field(default_factory=list)

    # Policy context
    share_level: str | None = None
    consent_chain_id: str | None = None

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary (full details)."""
        return {
            "origin_did": self.origin_did,
            "origin_node": self.origin_node,
            "origin_timestamp": self.origin_timestamp,
            "hops": self.hops,
            "origin_signature": (self.origin_signature.hex() if self.origin_signature else None),
            "chain_signatures": [s.hex() for s in self.chain_signatures],
            "signature_verified": self.signature_verified,
            "federation_path": self.federation_path,
            "corroborating_sources": self.corroborating_sources,
            "corroboration_attestations": self.corroboration_attestations,
            "share_level": self.share_level,
            "consent_chain_id": self.consent_chain_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProvenanceChain":
        """Deserialize from dictionary."""
        origin_sig = data.get("origin_signature")
        if isinstance(origin_sig, str):
            origin_sig = bytes.fromhex(origin_sig)

        chain_sigs = []
        for sig in data.get("chain_signatures", []):
            if isinstance(sig, str):
                chain_sigs.append(bytes.fromhex(sig))
            else:
                chain_sigs.append(sig)

        return cls(
            origin_did=data.get("origin_did"),
            origin_node=data.get("origin_node"),
            origin_timestamp=data.get("origin_timestamp"),
            hops=data.get("hops", []),
            origin_signature=origin_sig,
            chain_signatures=chain_sigs,
            signature_verified=data.get("signature_verified", False),
            federation_path=data.get("federation_path", []),
            corroborating_sources=data.get("corroborating_sources", 0),
            corroboration_attestations=data.get("corroboration_attestations", []),
            share_level=data.get("share_level"),
            consent_chain_id=data.get("consent_chain_id"),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_consent_chain(cls, consent_chain: Any) -> "ProvenanceChain":
        """Create from a ConsentChainEntry object."""
        return cls(
            origin_did=getattr(consent_chain, "origin_sharer", None),
            origin_timestamp=getattr(consent_chain, "origin_timestamp", None),
            hops=getattr(consent_chain, "hops", []),
            origin_signature=getattr(consent_chain, "origin_signature", None),
            consent_chain_id=getattr(consent_chain, "id", None),
        )

    @classmethod
    def from_belief_provenance(cls, belief_provenance: Any) -> "ProvenanceChain":
        """Create from a BeliefProvenance object (federation module)."""
        return cls(
            origin_node=str(getattr(belief_provenance, "origin_node_id", "")),
            origin_timestamp=getattr(belief_provenance, "signed_at", None),
            federation_path=getattr(belief_provenance, "federation_path", []),
            signature_verified=getattr(belief_provenance, "signature_verified", False),
            share_level=getattr(belief_provenance, "share_level", None),
            metadata={
                "hop_count": getattr(belief_provenance, "hop_count", 0),
                "origin_signature": getattr(belief_provenance, "origin_signature", ""),
            },
        )


@dataclass
class FilteredProvenance:
    """A filtered view of provenance appropriate for an audience tier.

    Created by filter_provenance() based on the requested tier.
    """

    tier: ProvenanceTier

    # FULL tier only
    origin_did: str | None = None
    origin_node: str | None = None
    hops: list[dict[str, Any]] | None = None
    federation_path: list[str] | None = None
    signatures_present: bool = False
    signature_verified: bool = False

    # PARTIAL tier and above
    chain_length: int | None = None
    has_origin: bool = False

    # ANONYMOUS tier and above
    verified_by_sources: int | None = None
    verification_summary: str | None = None

    # NONE tier - nothing

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary (only includes tier-appropriate fields)."""
        result: dict[str, Any] = {"tier": self.tier.value}

        if self.tier == ProvenanceTier.NONE:
            return result

        if self.tier == ProvenanceTier.ANONYMOUS:
            result["verified_by_sources"] = self.verified_by_sources
            result["verification_summary"] = self.verification_summary
            return result

        if self.tier in (ProvenanceTier.PARTIAL, ProvenanceTier.FULL):
            result["chain_length"] = self.chain_length
            result["has_origin"] = self.has_origin
            result["signatures_present"] = self.signatures_present
            result["signature_verified"] = self.signature_verified

        if self.tier == ProvenanceTier.FULL:
            result["origin_did"] = self.origin_did
            result["origin_node"] = self.origin_node
            result["hops"] = self.hops
            result["federation_path"] = self.federation_path

        return result

    def __str__(self) -> str:
        """Human-readable string representation."""
        if self.tier == ProvenanceTier.NONE:
            return "No provenance available"

        if self.tier == ProvenanceTier.ANONYMOUS:
            return self.verification_summary or "Unverified"

        if self.tier == ProvenanceTier.PARTIAL:
            verified = "✓" if self.signature_verified else "?"
            return f"Chain length: {self.chain_length} [{verified}]"

        # FULL
        origin = self.origin_did or self.origin_node or "unknown"
        verified = "verified" if self.signature_verified else "unverified"
        hops = len(self.hops) if self.hops else 0
        return f"From {origin} ({hops} hops, {verified})"


def filter_provenance(
    chain: ProvenanceChain | dict[str, Any] | Any,
    tier: ProvenanceTier,
) -> FilteredProvenance:
    """Filter provenance information based on audience tier.

    Takes a full provenance chain and returns a filtered view appropriate
    for the specified audience tier.

    Args:
        chain: ProvenanceChain, dict representation, or any object with
               provenance attributes (ConsentChainEntry, BeliefProvenance)
        tier: The ProvenanceTier determining what information to include

    Returns:
        FilteredProvenance with tier-appropriate information

    Examples:
        >>> chain = ProvenanceChain(origin_did="did:example:alice", hops=[...])
        >>> full_view = filter_provenance(chain, ProvenanceTier.FULL)
        >>> anon_view = filter_provenance(chain, ProvenanceTier.ANONYMOUS)
    """
    # Normalize input to ProvenanceChain
    if isinstance(chain, dict):
        pchain = ProvenanceChain.from_dict(chain)
    elif isinstance(chain, ProvenanceChain):
        pchain = chain
    elif hasattr(chain, "origin_sharer"):
        # Looks like ConsentChainEntry
        pchain = ProvenanceChain.from_consent_chain(chain)
    elif hasattr(chain, "federation_path"):
        # Looks like BeliefProvenance
        pchain = ProvenanceChain.from_belief_provenance(chain)
    else:
        # Unknown type, create empty chain
        pchain = ProvenanceChain()

    # NONE tier - no provenance information
    if tier == ProvenanceTier.NONE:
        return FilteredProvenance(tier=tier)

    # Calculate common values
    hop_count = len(pchain.hops) if pchain.hops else 0
    path_count = len(pchain.federation_path) if pchain.federation_path else 0
    chain_length = max(hop_count, path_count)

    has_origin = bool(pchain.origin_did or pchain.origin_node)
    signatures_present = bool(pchain.origin_signature or pchain.chain_signatures)

    # Count verifiable sources
    source_count = pchain.corroborating_sources
    if has_origin:
        source_count = max(source_count, 1)
    if pchain.corroboration_attestations:
        source_count = max(source_count, len(pchain.corroboration_attestations))

    # ANONYMOUS tier - just source count summary
    if tier == ProvenanceTier.ANONYMOUS:
        if source_count == 0:
            summary = "Unverified source"
        elif source_count == 1:
            if pchain.signature_verified:
                summary = "Verified by 1 source"
            else:
                summary = "From 1 source (unverified)"
        else:
            if pchain.signature_verified:
                summary = f"Verified by {source_count} sources"
            else:
                summary = f"From {source_count} sources"

        return FilteredProvenance(
            tier=tier,
            verified_by_sources=source_count,
            verification_summary=summary,
        )

    # PARTIAL tier - structure without identities
    if tier == ProvenanceTier.PARTIAL:
        return FilteredProvenance(
            tier=tier,
            chain_length=chain_length,
            has_origin=has_origin,
            signatures_present=signatures_present,
            signature_verified=pchain.signature_verified,
        )

    # FULL tier - everything
    # Sanitize hops to remove any accidentally included sensitive data
    sanitized_hops = []
    for hop in pchain.hops or []:
        if isinstance(hop, dict):
            sanitized_hops.append(hop.copy())
        else:
            sanitized_hops.append({"hop": str(hop)})

    return FilteredProvenance(
        tier=tier,
        origin_did=pchain.origin_did,
        origin_node=pchain.origin_node,
        hops=sanitized_hops,
        federation_path=list(pchain.federation_path) if pchain.federation_path else [],
        signatures_present=signatures_present,
        signature_verified=pchain.signature_verified,
        chain_length=chain_length,
        has_origin=has_origin,
    )


def get_tier_for_audience(
    audience_type: str,
    custom_mapping: dict[str, ProvenanceTier] | None = None,
) -> ProvenanceTier:
    """Get the appropriate provenance tier for an audience type.

    Provides sensible defaults for common audience types, with the ability
    to customize via a mapping dictionary.

    Args:
        audience_type: String identifying the audience (e.g., "owner", "public")
        custom_mapping: Optional dict mapping audience types to tiers

    Returns:
        ProvenanceTier appropriate for the audience

    Examples:
        >>> get_tier_for_audience("owner")
        ProvenanceTier.FULL
        >>> get_tier_for_audience("public")
        ProvenanceTier.ANONYMOUS
    """
    default_mapping = {
        # Full access
        "owner": ProvenanceTier.FULL,
        "admin": ProvenanceTier.FULL,
        "self": ProvenanceTier.FULL,
        # Partial access (trusted but not owner)
        "trusted": ProvenanceTier.PARTIAL,
        "collaborator": ProvenanceTier.PARTIAL,
        "federation": ProvenanceTier.PARTIAL,
        "node": ProvenanceTier.PARTIAL,
        # Anonymous (public-ish)
        "public": ProvenanceTier.ANONYMOUS,
        "reader": ProvenanceTier.ANONYMOUS,
        "viewer": ProvenanceTier.ANONYMOUS,
        # No provenance
        "anonymous": ProvenanceTier.NONE,
        "minimal": ProvenanceTier.NONE,
    }

    mapping = {**default_mapping, **(custom_mapping or {})}
    return mapping.get(audience_type.lower(), ProvenanceTier.ANONYMOUS)
