# Valence Privacy Module
"""
Privacy controls for Valence including canary tokens, secure sharing,
AI-assisted insight extraction, privacy elevation workflows, provenance tiers,
and corroboration-based auto-elevation.

This module provides tools for:
- Canary tokens: Detect unauthorized sharing via embedded markers
- Secure sharing: Share content with expiry, view limits, and leak detection
- Insight extraction: AI-powered extraction of shareable insights from private content
- Privacy elevation: Controlled workflow for transitioning content between privacy levels
- Provenance tiers: Control what provenance info different audiences see
- Corroboration: Detect beliefs confirmed by multiple independent sources
- Auto-elevation: Automatically elevate beliefs based on corroboration thresholds
"""

from .canary import (
    # Core types
    CanaryToken,
    CanaryDetection,
    EmbedStrategy,
    # Components
    CanaryEmbedder,
    CanaryExtractor,
    CanaryRegistry,
    # High-level functions
    create_canary,
    embed_canary,
    detect_canaries,
    get_registry,
)

from .provenance import (
    # Core types
    ProvenanceTier,
    TrustLevel,
    ConsentChainEntry,
    ProvenanceChain,
    FilteredProvenance,
    # Components
    ProvenanceFilter,
    # High-level functions
    get_filter as get_provenance_filter,
    filter_provenance,
    filter_provenance_for_recipient,
)

from .sharing import (
    # Core types
    Share,
    ShareOptions,
    ShareVisibility,
    ShareAccessLevel,
    # Manager
    ShareManager,
    get_manager,
    # High-level function
    share_content,
)

from .extraction import (
    # Core types
    ExtractionLevel,
    ReviewStatus,
    ExtractionRequest,
    ExtractedInsight,
    # Components
    AIExtractor,
    MockAIExtractor,
    InsightExtractor,
    # High-level functions
    get_extractor,
    extract_insight,
    review_insight,
)

from .corroboration import (
    # Core types
    CorroborationStatus,
    SourceInfo,
    CorroborationEvidence,
    CorroborationConfig,
    # Components
    CorroborationDetector,
    MockEmbeddingSimilarity,
    # High-level functions
    check_corroboration,
    register_belief,
    is_corroborated,
    get_elevation_candidates,
    get_detector,
)

from .elevation import (
    # Core types
    ElevationLevel,
    ElevationTrigger,
    ProposalStatus,
    ElevationProposal,
    BeliefElevationState,
    AutoElevationConfig,
    # Manager
    ElevationManager,
    get_elevation_manager,
    # High-level functions
    check_and_propose_elevation,
    approve_elevation,
    reject_elevation,
    opt_out_auto_elevation,
    opt_in_auto_elevation,
)

from .elevation_proposals import (
    # Core types (aliased to avoid collision with elevation module)
    ProposalStatus as ShareLevelProposalStatus,
    TransformType,
    ContentTransform,
    ElevationProposal as ShareLevelElevationProposal,
    ElevationHistoryEntry,
    # Validation
    is_valid_elevation as is_valid_share_level_elevation,
    SHARE_LEVEL_ORDER,
    # Request/Result types
    ProposeRequest,
    ProposeResult,
    ApproveRequest,
    ApproveResult,
    RejectRequest,
    RejectResult,
    # Service
    ElevationProposalService,
)

__all__ = [
    # Canary tokens
    "CanaryToken",
    "CanaryDetection",
    "EmbedStrategy",
    "CanaryEmbedder",
    "CanaryExtractor",
    "CanaryRegistry",
    "create_canary",
    "embed_canary",
    "detect_canaries",
    "get_registry",
    # Provenance tiers
    "ProvenanceTier",
    "TrustLevel",
    "ConsentChainEntry",
    "ProvenanceChain",
    "FilteredProvenance",
    "ProvenanceFilter",
    "get_provenance_filter",
    "filter_provenance",
    "filter_provenance_for_recipient",
    # Sharing
    "Share",
    "ShareOptions",
    "ShareVisibility",
    "ShareAccessLevel",
    "ShareManager",
    "get_manager",
    "share_content",
    # Insight extraction
    "ExtractionLevel",
    "ReviewStatus",
    "ExtractionRequest",
    "ExtractedInsight",
    "AIExtractor",
    "MockAIExtractor",
    "InsightExtractor",
    "get_extractor",
    "extract_insight",
    "review_insight",
    # Corroboration
    "CorroborationStatus",
    "SourceInfo",
    "CorroborationEvidence",
    "CorroborationConfig",
    "CorroborationDetector",
    "MockEmbeddingSimilarity",
    "check_corroboration",
    "register_belief",
    "is_corroborated",
    "get_elevation_candidates",
    "get_detector",
    # Elevation (auto-elevation based on corroboration)
    "ElevationLevel",
    "ElevationTrigger",
    "ProposalStatus",
    "ElevationProposal",
    "BeliefElevationState",
    "AutoElevationConfig",
    "ElevationManager",
    "get_elevation_manager",
    "check_and_propose_elevation",
    "approve_elevation",
    "reject_elevation",
    "opt_out_auto_elevation",
    "opt_in_auto_elevation",
    # Elevation proposals (explicit ShareLevel proposal-approval workflow)
    "ShareLevelProposalStatus",
    "TransformType",
    "ContentTransform",
    "ShareLevelElevationProposal",
    "ElevationHistoryEntry",
    "is_valid_share_level_elevation",
    "SHARE_LEVEL_ORDER",
    "ProposeRequest",
    "ProposeResult",
    "ApproveRequest",
    "ApproveResult",
    "RejectRequest",
    "RejectResult",
    "ElevationProposalService",
]
