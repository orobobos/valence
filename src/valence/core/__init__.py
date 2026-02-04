"""Valence Core - Shared primitives for the knowledge substrate."""

from .models import (
    Belief,
    Entity,
    Source,
    Tension,
    Session,
    Exchange,
    Pattern,
    BeliefEntity,
    SessionInsight,
)
from .confidence import DimensionalConfidence, ConfidenceDimension
from .temporal import TemporalValidity
from .db import get_connection, generate_id
from .exceptions import (
    ValenceException,
    DatabaseException,
    ValidationException,
    ConfigException,
    NotFoundError,
    ConflictError,
    EmbeddingException,
    MCPException,
)
from .verification import (
    # Enums
    VerificationResult,
    VerificationStatus,
    StakeType,
    EvidenceType,
    EvidenceContribution,
    ContradictionType,
    DisputeType,
    DisputeOutcome,
    DisputeStatus,
    # Models
    Evidence,
    Verification,
    Dispute,
    Stake,
    ReputationScore,
    DiscrepancyBounty,
    # Service
    VerificationService,
    # Functions
    calculate_min_stake,
    calculate_max_stake,
    calculate_bounty,
    create_evidence,
)
from .health import (
    HealthStatus,
    run_health_check,
    require_healthy,
    startup_checks,
    validate_environment,
    validate_database,
)
from .logging import (
    configure_logging,
    get_logger,
    ToolCallLogger,
    tool_logger,
)
from .mcp_base import (
    MCPServerBase,
    ToolRouter,
    success_response,
    error_response,
    not_found_response,
)
from .external_sources import (
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
    # Models
    ExternalSourceVerification,
    L4SourceRequirements,
    # Service
    ExternalSourceVerificationService,
    # Functions
    verify_external_source,
    check_belief_l4_readiness,
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
