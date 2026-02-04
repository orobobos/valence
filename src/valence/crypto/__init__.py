"""Cryptographic primitives for Valence.

This module provides cryptographic abstractions including:
- MLS (Messaging Layer Security) for group encryption
- ZKP (Zero-Knowledge Proofs) for compliance verification
"""

from valence.crypto.mls import (
    MLSGroup,
    MLSMember,
    MLSKeySchedule,
    MLSBackend,
    MockMLSBackend,
    MLSError,
    MLSGroupNotFoundError,
    MLSMemberNotFoundError,
    MLSEpochMismatchError,
)

from valence.crypto.zkp import (
    # Exceptions
    ZKPError,
    ZKPInvalidProofError,
    ZKPCircuitNotFoundError,
    ZKPProvingError,
    ZKPVerificationError,
    ZKPInputError,
    # Types
    ComplianceProofType,
    PublicParameters,
    ComplianceProof,
    VerificationResult,
    # Abstract interfaces
    ZKPProver,
    ZKPVerifier,
    ZKPBackend,
    # Mock implementations
    MockZKPProver,
    MockZKPVerifier,
    MockZKPBackend,
    # Utilities
    hash_public_inputs,
    verify_proof,
)

__all__ = [
    # MLS
    "MLSGroup",
    "MLSMember",
    "MLSKeySchedule",
    "MLSBackend",
    "MockMLSBackend",
    "MLSError",
    "MLSGroupNotFoundError",
    "MLSMemberNotFoundError",
    "MLSEpochMismatchError",
    # ZKP Exceptions
    "ZKPError",
    "ZKPInvalidProofError",
    "ZKPCircuitNotFoundError",
    "ZKPProvingError",
    "ZKPVerificationError",
    "ZKPInputError",
    # ZKP Types
    "ComplianceProofType",
    "PublicParameters",
    "ComplianceProof",
    "VerificationResult",
    # ZKP Interfaces
    "ZKPProver",
    "ZKPVerifier",
    "ZKPBackend",
    # ZKP Mock Implementations
    "MockZKPProver",
    "MockZKPVerifier",
    "MockZKPBackend",
    # ZKP Utilities
    "hash_public_inputs",
    "verify_proof",
]
