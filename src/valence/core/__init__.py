"""Valence Core - Shared primitives for the knowledge substrate."""

from .confidence import ConfidenceDimension, DimensionalConfidence
from .db import (
    close_pool,
    generate_id,
    get_connection,
    get_pool_config,
    get_pool_stats,
    put_connection,
)
from .exceptions import (
    ConfigException,
    ConflictError,
    DatabaseException,
    EmbeddingException,
    MCPException,
    NotFoundError,
    ValenceException,
    ValidationException,
)
from .external_sources import (
    ContentMatchResult,
    DOIPrefix,
    DOIStatus,
    DOIVerificationResult,
    # Constants
    ExternalSourceConstants,
    # Models
    ExternalSourceVerification,
    # Service
    ExternalSourceVerificationService,
    L4SourceRequirements,
    # Results
    LivenessCheckResult,
    # Enums
    SourceCategory,
    SourceLivenessStatus,
    SourceReliabilityScore,
    SourceVerificationStatus,
    # Registry
    TrustedDomain,
    TrustedSourceRegistry,
    check_belief_l4_readiness,
    get_registry,
    # Functions
    verify_external_source,
)
from .health import (
    HealthStatus,
    require_healthy,
    run_health_check,
    startup_checks,
    validate_database,
    validate_environment,
)
from .logging import (
    ToolCallLogger,
    configure_logging,
    get_logger,
    tool_logger,
)
from .mcp_base import (
    MCPServerBase,
    ToolRouter,
    error_response,
    not_found_response,
    success_response,
)
from .models import (
    Belief,
    BeliefEntity,
    Entity,
    Exchange,
    Pattern,
    Session,
    SessionInsight,
    Source,
    Tension,
)
from .temporal import TemporalValidity
from .verification import (
    ContradictionType,
    DiscrepancyBounty,
    Dispute,
    DisputeOutcome,
    DisputeStatus,
    DisputeType,
    # Models
    Evidence,
    EvidenceContribution,
    EvidenceType,
    ReputationScore,
    Stake,
    StakeType,
    Verification,
    # Enums
    VerificationResult,
    # Service
    VerificationService,
    VerificationStatus,
    calculate_bounty,
    calculate_max_stake,
    # Functions
    calculate_min_stake,
    create_evidence,
)

__all__ = [
    # Models
    "Belief",
    "Entity",
    "Source",
    "Tension",
    "Session",
    "Exchange",
    "Pattern",
    "BeliefEntity",
    "SessionInsight",
    # Confidence
    "DimensionalConfidence",
    "ConfidenceDimension",
    # Temporal
    "TemporalValidity",
    # Database
    "get_connection",
    "put_connection",
    "close_pool",
    "get_pool_config",
    "get_pool_stats",
    "generate_id",
    # Exceptions
    "ValenceException",
    "DatabaseException",
    "ValidationException",
    "ConfigException",
    "NotFoundError",
    "ConflictError",
    "EmbeddingException",
    "MCPException",
    # Health
    "HealthStatus",
    "run_health_check",
    "require_healthy",
    "startup_checks",
    "validate_environment",
    "validate_database",
    # Logging
    "configure_logging",
    "get_logger",
    "ToolCallLogger",
    "tool_logger",
    # MCP Base
    "MCPServerBase",
    "ToolRouter",
    "success_response",
    "error_response",
    "not_found_response",
    # Verification Protocol
    "VerificationResult",
    "VerificationStatus",
    "StakeType",
    "EvidenceType",
    "EvidenceContribution",
    "ContradictionType",
    "DisputeType",
    "DisputeOutcome",
    "DisputeStatus",
    "Evidence",
    "Verification",
    "Dispute",
    "Stake",
    "ReputationScore",
    "DiscrepancyBounty",
    "VerificationService",
    "calculate_min_stake",
    "calculate_max_stake",
    "calculate_bounty",
    "create_evidence",
    # External Source Verification (L4)
    "ExternalSourceConstants",
    "SourceCategory",
    "SourceVerificationStatus",
    "DOIStatus",
    "SourceLivenessStatus",
    "TrustedDomain",
    "DOIPrefix",
    "TrustedSourceRegistry",
    "get_registry",
    "LivenessCheckResult",
    "ContentMatchResult",
    "DOIVerificationResult",
    "SourceReliabilityScore",
    "ExternalSourceVerification",
    "L4SourceRequirements",
    "ExternalSourceVerificationService",
    "verify_external_source",
    "check_belief_l4_readiness",
]
