"""Cryptographic primitives for Valence.

This module provides cryptographic abstractions including:
- MLS (Messaging Layer Security) for group encryption
- ZKP (Zero-Knowledge Proofs) for compliance verification
- PRE (Proxy Re-Encryption) for federation aggregation
"""

from valence.crypto.mls import (
    MLSBackend,
    MLSEpochMismatchError,
    MLSError,
    MLSGroup,
    MLSGroupNotFoundError,
    MLSKeySchedule,
    MLSMember,
    MLSMemberNotFoundError,
    MockMLSBackend,
)
from valence.crypto.pre import (
    # Mock implementation
    MockPREBackend,
    # Abstract interface
    PREBackend,
    PRECiphertext,
    PREDecryptionError,
    PREEncryptionError,
    # Exceptions
    PREError,
    PREInvalidCiphertextError,
    PREKeyError,
    PREKeyPair,
    PREPrivateKey,
    # Data classes
    PREPublicKey,
    PREReEncryptionError,
    ReEncryptionKey,
    # Utilities
    create_mock_backend,
)
from valence.crypto.zkp import (
    ComplianceProof,
    # Types
    ComplianceProofType,
    MockZKPBackend,
    # Mock implementations
    MockZKPProver,
    MockZKPVerifier,
    PublicParameters,
    VerificationResult,
    ZKPBackend,
    ZKPCircuitNotFoundError,
    # Exceptions
    ZKPError,
    ZKPInputError,
    ZKPInvalidProofError,
    # Abstract interfaces
    ZKPProver,
    ZKPProvingError,
    ZKPVerificationError,
    ZKPVerifier,
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
    # PRE Exceptions
    "PREError",
    "PREKeyError",
    "PREEncryptionError",
    "PREDecryptionError",
    "PREReEncryptionError",
    "PREInvalidCiphertextError",
    # PRE Data Classes
    "PREPublicKey",
    "PREPrivateKey",
    "PREKeyPair",
    "ReEncryptionKey",
    "PRECiphertext",
    # PRE Interfaces
    "PREBackend",
    # PRE Mock Implementation
    "MockPREBackend",
    # PRE Utilities
    "create_mock_backend",
]
