"""Zero-Knowledge Proof Abstraction Layer for Compliance Verification.

Provides a Python interface for ZK proofs that verify compliance properties
without revealing underlying content. This module defines the abstract interface
that can be backed by different implementations:
- MockZKPBackend: For testing (simulated verification)
- Future: snarkjs FFI binding for real ZK circuits

Compliance proof types:
- HAS_CONSENT: Prove user has given consent without revealing consent details
- WITHIN_POLICY: Prove operation satisfies policy without revealing operation
- NOT_REVOKED: Prove credential is not revoked without revealing the credential
- MEMBER_OF_DOMAIN: Prove membership in a domain without revealing identity

Security properties:
- Zero-knowledge: Verifier learns nothing beyond the statement's truth
- Soundness: False statements cannot be proven
- Completeness: True statements can always be proven

Example:
    >>> backend = MockZKPBackend()
    >>> prover = backend.create_prover(ComplianceProofType.HAS_CONSENT)
    >>> proof = prover.prove(
    ...     private_inputs={"consent_record": consent_hash},
    ...     public_inputs={"user_id": user_id, "action": "read"}
    ... )
    >>> verifier = backend.create_verifier(ComplianceProofType.HAS_CONSENT)
    >>> assert verifier.verify(proof, public_inputs={"user_id": user_id, "action": "read"})
"""

from __future__ import annotations

import hashlib
import secrets as crypto_secrets
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any

# =============================================================================
# Exceptions
# =============================================================================


class ZKPError(Exception):
    """Base exception for ZKP operations."""

    pass


class ZKPInvalidProofError(ZKPError):
    """Raised when a proof fails verification."""

    pass


class ZKPCircuitNotFoundError(ZKPError):
    """Raised when a circuit for a proof type is not found."""

    pass


class ZKPProvingError(ZKPError):
    """Raised when proof generation fails."""

    pass


class ZKPVerificationError(ZKPError):
    """Raised when proof verification encounters an error."""

    pass


class ZKPInputError(ZKPError):
    """Raised when inputs are malformed or missing."""

    pass


# =============================================================================
# Enums and Types
# =============================================================================


class ComplianceProofType(Enum):
    """Types of compliance proofs supported by the system.

    Each proof type corresponds to a specific ZK circuit that proves
    a compliance property without revealing sensitive information.
    """

    HAS_CONSENT = auto()
    """Prove that valid consent exists for an operation.

    Private inputs: consent_record, consent_signature
    Public inputs: user_id, action, resource_type
    Proves: A valid consent record exists authorizing the action.
    """

    WITHIN_POLICY = auto()
    """Prove that an operation satisfies a policy.

    Private inputs: operation_details, policy_evaluation
    Public inputs: policy_hash, operation_type, timestamp
    Proves: The operation was evaluated and approved by the policy.
    """

    NOT_REVOKED = auto()
    """Prove that a credential has not been revoked.

    Private inputs: credential, revocation_proof
    Public inputs: credential_commitment, revocation_accumulator
    Proves: The credential is not in the revocation set.
    """

    MEMBER_OF_DOMAIN = auto()
    """Prove membership in a domain without revealing identity.

    Private inputs: member_credential, merkle_proof
    Public inputs: domain_id, membership_root
    Proves: The prover holds a valid credential in the domain's membership tree.
    """


@dataclass
class PublicParameters:
    """Public parameters for a ZKP circuit.

    These parameters are generated during trusted setup (for SNARKs)
    or are deterministic (for STARKs/Bulletproofs).

    Attributes:
        proof_type: The type of compliance proof
        circuit_hash: Hash of the circuit definition
        verification_key: Key used by verifiers (public)
        proving_key_hash: Hash of the proving key (for integrity)
        created_at: When these parameters were generated
        version: Version of the circuit/parameters
    """

    proof_type: ComplianceProofType
    circuit_hash: bytes
    verification_key: bytes
    proving_key_hash: bytes
    created_at: datetime = field(default_factory=datetime.now)
    version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "proof_type": self.proof_type.name,
            "circuit_hash": self.circuit_hash.hex(),
            "verification_key": self.verification_key.hex(),
            "proving_key_hash": self.proving_key_hash.hex(),
            "created_at": self.created_at.isoformat(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PublicParameters:
        """Create from dictionary."""
        return cls(
            proof_type=ComplianceProofType[data["proof_type"]],
            circuit_hash=bytes.fromhex(data["circuit_hash"]),
            verification_key=bytes.fromhex(data["verification_key"]),
            proving_key_hash=bytes.fromhex(data["proving_key_hash"]),
            created_at=(
                datetime.fromisoformat(data["created_at"])
                if data.get("created_at")
                else datetime.now()
            ),
            version=data.get("version", "1.0.0"),
        )


@dataclass
class ComplianceProof:
    """A zero-knowledge proof of compliance.

    This is the output of the prover that can be verified without
    revealing the private inputs used to generate it.

    Attributes:
        proof_type: Type of compliance being proven
        proof_data: The actual proof bytes (format depends on backend)
        public_inputs_hash: Hash of the public inputs used
        created_at: When the proof was generated
        expires_at: When the proof expires (optional)
        metadata: Additional metadata (e.g., circuit version)
    """

    proof_type: ComplianceProofType
    proof_data: bytes
    public_inputs_hash: bytes
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if the proof has expired."""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "proof_type": self.proof_type.name,
            "proof_data": self.proof_data.hex(),
            "public_inputs_hash": self.public_inputs_hash.hex(),
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComplianceProof:
        """Create from dictionary."""
        return cls(
            proof_type=ComplianceProofType[data["proof_type"]],
            proof_data=bytes.fromhex(data["proof_data"]),
            public_inputs_hash=bytes.fromhex(data["public_inputs_hash"]),
            created_at=(
                datetime.fromisoformat(data["created_at"])
                if data.get("created_at")
                else datetime.now()
            ),
            expires_at=(
                datetime.fromisoformat(data["expires_at"])
                if data.get("expires_at")
                else None
            ),
            metadata=data.get("metadata", {}),
        )


@dataclass
class VerificationResult:
    """Result of proof verification.

    Attributes:
        valid: Whether the proof is valid
        proof_type: Type of proof that was verified
        public_inputs_hash: Hash of the public inputs used
        verified_at: When verification was performed
        error_message: Error message if verification failed
        verification_time_ms: Time taken to verify in milliseconds
    """

    valid: bool
    proof_type: ComplianceProofType
    public_inputs_hash: bytes
    verified_at: datetime = field(default_factory=datetime.now)
    error_message: str | None = None
    verification_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "valid": self.valid,
            "proof_type": self.proof_type.name,
            "public_inputs_hash": self.public_inputs_hash.hex(),
            "verified_at": self.verified_at.isoformat(),
            "error_message": self.error_message,
            "verification_time_ms": self.verification_time_ms,
        }


# =============================================================================
# Abstract Interfaces
# =============================================================================


class ZKPProver(ABC):
    """Abstract prover interface for generating compliance proofs.

    Provers take private inputs (witnesses) and public inputs to generate
    a zero-knowledge proof that a statement is true.
    """

    @property
    @abstractmethod
    def proof_type(self) -> ComplianceProofType:
        """The type of proof this prover generates."""
        pass

    @abstractmethod
    def prove(
        self,
        private_inputs: dict[str, Any],
        public_inputs: dict[str, Any],
    ) -> ComplianceProof:
        """Generate a compliance proof.

        Args:
            private_inputs: Secret witness data (not revealed in proof)
            public_inputs: Public data that verifier will also have

        Returns:
            A ComplianceProof that can be verified

        Raises:
            ZKPProvingError: If proof generation fails
            ZKPInputError: If inputs are malformed
        """
        pass

    @abstractmethod
    def validate_inputs(
        self,
        private_inputs: dict[str, Any],
        public_inputs: dict[str, Any],
    ) -> bool:
        """Validate that inputs are well-formed for this proof type.

        Args:
            private_inputs: Secret witness data
            public_inputs: Public data

        Returns:
            True if inputs are valid

        Raises:
            ZKPInputError: If inputs are malformed (with details)
        """
        pass


class ZKPVerifier(ABC):
    """Abstract verifier interface for checking compliance proofs.

    Verifiers check that a proof is valid given the public inputs,
    without needing access to the private inputs.
    """

    @property
    @abstractmethod
    def proof_type(self) -> ComplianceProofType:
        """The type of proof this verifier checks."""
        pass

    @abstractmethod
    def verify(
        self,
        proof: ComplianceProof,
        public_inputs: dict[str, Any],
    ) -> VerificationResult:
        """Verify a compliance proof.

        Args:
            proof: The proof to verify
            public_inputs: Public data (must match what was used in proving)

        Returns:
            VerificationResult indicating success/failure

        Raises:
            ZKPVerificationError: If verification encounters an error
        """
        pass


class ZKPBackend(ABC):
    """Abstract backend for ZKP operations.

    The backend manages circuits, proving keys, and verification keys,
    and creates provers and verifiers for specific proof types.
    """

    @abstractmethod
    def setup(self, proof_type: ComplianceProofType) -> PublicParameters:
        """Perform trusted setup for a proof type.

        For SNARKs, this generates the proving and verification keys.
        For STARKs/Bulletproofs, this generates deterministic parameters.

        Args:
            proof_type: The type of compliance proof to set up

        Returns:
            Public parameters that can be shared

        Raises:
            ZKPError: If setup fails
        """
        pass

    @abstractmethod
    def create_prover(self, proof_type: ComplianceProofType) -> ZKPProver:
        """Create a prover for generating proofs.

        Args:
            proof_type: The type of compliance proof

        Returns:
            A prover instance

        Raises:
            ZKPCircuitNotFoundError: If circuit not found/setup not done
        """
        pass

    @abstractmethod
    def create_verifier(self, proof_type: ComplianceProofType) -> ZKPVerifier:
        """Create a verifier for checking proofs.

        Args:
            proof_type: The type of compliance proof

        Returns:
            A verifier instance

        Raises:
            ZKPCircuitNotFoundError: If circuit not found/setup not done
        """
        pass

    @abstractmethod
    def get_public_parameters(
        self, proof_type: ComplianceProofType
    ) -> PublicParameters | None:
        """Get public parameters for a proof type.

        Args:
            proof_type: The type of compliance proof

        Returns:
            Public parameters or None if not set up
        """
        pass


# =============================================================================
# Utility Functions
# =============================================================================


def hash_public_inputs(public_inputs: dict[str, Any]) -> bytes:
    """Hash public inputs deterministically.

    Args:
        public_inputs: Dictionary of public inputs

    Returns:
        32-byte hash of the inputs
    """
    # Sort keys for deterministic ordering
    sorted_items = sorted(public_inputs.items())
    data = str(sorted_items).encode("utf-8")
    return hashlib.sha256(data).digest()


def verify_proof(
    proof: ComplianceProof,
    public_inputs: dict[str, Any],
    backend: ZKPBackend | None = None,
) -> bool:
    """Convenience function to verify a compliance proof.

    This is the main entry point for proof verification. It handles
    creating the appropriate verifier and checking the proof.

    Args:
        proof: The compliance proof to verify
        public_inputs: Public inputs that were used in proving
        backend: ZKP backend to use (creates MockZKPBackend if None)

    Returns:
        True if the proof is valid, False otherwise

    Example:
        >>> proof = prover.prove(private, public)
        >>> assert verify_proof(proof, public)
    """
    if backend is None:
        backend = MockZKPBackend()
        # Ensure setup for the proof type
        backend.setup(proof.proof_type)

    # Check expiration
    if proof.is_expired:
        return False

    verifier = backend.create_verifier(proof.proof_type)
    result = verifier.verify(proof, public_inputs)
    return result.valid


# =============================================================================
# Mock Implementation
# =============================================================================


class MockZKPProver(ZKPProver):
    """Mock prover for testing.

    This prover simulates ZK proof generation by creating deterministic
    "proofs" based on the inputs. It does NOT provide real zero-knowledge
    properties - use only for testing.

    In a real implementation, this would call snarkjs or similar.
    """

    def __init__(self, proof_type: ComplianceProofType, params: PublicParameters):
        """Initialize mock prover.

        Args:
            proof_type: Type of proof to generate
            params: Public parameters from setup
        """
        self._proof_type = proof_type
        self._params = params

        # Define required inputs for each proof type
        self._required_private: dict[ComplianceProofType, set[str]] = {
            ComplianceProofType.HAS_CONSENT: {"consent_record"},
            ComplianceProofType.WITHIN_POLICY: {
                "operation_details",
                "policy_evaluation",
            },
            ComplianceProofType.NOT_REVOKED: {"credential", "revocation_proof"},
            ComplianceProofType.MEMBER_OF_DOMAIN: {"member_credential", "merkle_proof"},
        }

        self._required_public: dict[ComplianceProofType, set[str]] = {
            ComplianceProofType.HAS_CONSENT: {"user_id", "action"},
            ComplianceProofType.WITHIN_POLICY: {"policy_hash", "operation_type"},
            ComplianceProofType.NOT_REVOKED: {
                "credential_commitment",
                "revocation_accumulator",
            },
            ComplianceProofType.MEMBER_OF_DOMAIN: {"domain_id", "membership_root"},
        }

    @property
    def proof_type(self) -> ComplianceProofType:
        """The type of proof this prover generates."""
        return self._proof_type

    def validate_inputs(
        self,
        private_inputs: dict[str, Any],
        public_inputs: dict[str, Any],
    ) -> bool:
        """Validate that inputs are well-formed for this proof type."""
        required_private = self._required_private.get(self._proof_type, set())
        required_public = self._required_public.get(self._proof_type, set())

        missing_private = required_private - set(private_inputs.keys())
        if missing_private:
            raise ZKPInputError(f"Missing private inputs: {missing_private}")

        missing_public = required_public - set(public_inputs.keys())
        if missing_public:
            raise ZKPInputError(f"Missing public inputs: {missing_public}")

        return True

    def prove(
        self,
        private_inputs: dict[str, Any],
        public_inputs: dict[str, Any],
    ) -> ComplianceProof:
        """Generate a mock compliance proof.

        The mock proof is deterministic based on the inputs, allowing
        for reproducible testing.
        """
        self.validate_inputs(private_inputs, public_inputs)

        # Create deterministic "proof" by hashing all inputs
        public_hash = hash_public_inputs(public_inputs)
        private_hash = hash_public_inputs(private_inputs)

        # Combine with circuit hash for the proof
        combined = public_hash + private_hash + self._params.circuit_hash
        proof_data = hashlib.sha256(combined).digest()

        # Add some "randomness" to make it look more like a real proof
        proof_data = proof_data + crypto_secrets.token_bytes(32)

        return ComplianceProof(
            proof_type=self._proof_type,
            proof_data=proof_data,
            public_inputs_hash=public_hash,
            metadata={
                "circuit_version": self._params.version,
                "mock": True,
            },
        )


class MockZKPVerifier(ZKPVerifier):
    """Mock verifier for testing.

    This verifier simulates ZK proof verification. It checks that the
    proof was generated with matching public inputs but does NOT verify
    any actual ZK properties.

    In a real implementation, this would call snarkjs or similar.
    """

    def __init__(self, proof_type: ComplianceProofType, params: PublicParameters):
        """Initialize mock verifier.

        Args:
            proof_type: Type of proof to verify
            params: Public parameters from setup
        """
        self._proof_type = proof_type
        self._params = params

    @property
    def proof_type(self) -> ComplianceProofType:
        """The type of proof this verifier checks."""
        return self._proof_type

    def verify(
        self,
        proof: ComplianceProof,
        public_inputs: dict[str, Any],
    ) -> VerificationResult:
        """Verify a mock compliance proof.

        For mock verification, we check:
        1. Proof type matches
        2. Public inputs hash matches
        3. Proof is not expired
        4. Proof data has expected length
        """
        start_time = time.time()

        # Check proof type
        if proof.proof_type != self._proof_type:
            return VerificationResult(
                valid=False,
                proof_type=proof.proof_type,
                public_inputs_hash=proof.public_inputs_hash,
                error_message=f"Proof type mismatch: expected {self._proof_type.name}, got {proof.proof_type.name}",
                verification_time_ms=(time.time() - start_time) * 1000,
            )

        # Check public inputs hash
        expected_hash = hash_public_inputs(public_inputs)
        if proof.public_inputs_hash != expected_hash:
            return VerificationResult(
                valid=False,
                proof_type=proof.proof_type,
                public_inputs_hash=proof.public_inputs_hash,
                error_message="Public inputs hash mismatch",
                verification_time_ms=(time.time() - start_time) * 1000,
            )

        # Check expiration
        if proof.is_expired:
            return VerificationResult(
                valid=False,
                proof_type=proof.proof_type,
                public_inputs_hash=proof.public_inputs_hash,
                error_message="Proof has expired",
                verification_time_ms=(time.time() - start_time) * 1000,
            )

        # Check proof data length (mock proofs are 64 bytes)
        if len(proof.proof_data) != 64:
            return VerificationResult(
                valid=False,
                proof_type=proof.proof_type,
                public_inputs_hash=proof.public_inputs_hash,
                error_message=f"Invalid proof data length: expected 64, got {len(proof.proof_data)}",
                verification_time_ms=(time.time() - start_time) * 1000,
            )

        # Simulate some verification time
        verification_time = (time.time() - start_time) * 1000

        return VerificationResult(
            valid=True,
            proof_type=proof.proof_type,
            public_inputs_hash=proof.public_inputs_hash,
            verification_time_ms=verification_time,
        )


class MockZKPBackend(ZKPBackend):
    """Mock ZKP backend for testing.

    This backend provides mock provers and verifiers for testing
    the ZKP interface without requiring real ZK circuits.

    In production, this would be replaced with a backend that uses:
    - snarkjs for Groth16/PLONK proofs
    - arkworks for Rust-based ZK
    - Halo2 for recursive proofs

    Example:
        >>> backend = MockZKPBackend()
        >>> params = backend.setup(ComplianceProofType.HAS_CONSENT)
        >>> prover = backend.create_prover(ComplianceProofType.HAS_CONSENT)
        >>> proof = prover.prove(
        ...     private_inputs={"consent_record": b"..."},
        ...     public_inputs={"user_id": "alice", "action": "read"}
        ... )
        >>> verifier = backend.create_verifier(ComplianceProofType.HAS_CONSENT)
        >>> result = verifier.verify(proof, {"user_id": "alice", "action": "read"})
        >>> assert result.valid
    """

    def __init__(self):
        """Initialize mock backend."""
        self._parameters: dict[ComplianceProofType, PublicParameters] = {}
        self._proving_keys: dict[ComplianceProofType, bytes] = {}

    def setup(self, proof_type: ComplianceProofType) -> PublicParameters:
        """Perform mock trusted setup.

        Generates deterministic mock keys for the proof type.
        """
        # Generate mock circuit hash
        circuit_hash = hashlib.sha256(f"circuit:{proof_type.name}".encode()).digest()

        # Generate mock keys
        verification_key = hashlib.sha256(f"vk:{proof_type.name}".encode()).digest()
        proving_key = hashlib.sha256(f"pk:{proof_type.name}".encode()).digest()
        proving_key_hash = hashlib.sha256(proving_key).digest()

        params = PublicParameters(
            proof_type=proof_type,
            circuit_hash=circuit_hash,
            verification_key=verification_key,
            proving_key_hash=proving_key_hash,
        )

        self._parameters[proof_type] = params
        self._proving_keys[proof_type] = proving_key

        return params

    def create_prover(self, proof_type: ComplianceProofType) -> ZKPProver:
        """Create a mock prover."""
        params = self._parameters.get(proof_type)
        if params is None:
            raise ZKPCircuitNotFoundError(
                f"No setup found for {proof_type.name}. Call setup() first."
            )

        return MockZKPProver(proof_type, params)

    def create_verifier(self, proof_type: ComplianceProofType) -> ZKPVerifier:
        """Create a mock verifier."""
        params = self._parameters.get(proof_type)
        if params is None:
            raise ZKPCircuitNotFoundError(
                f"No setup found for {proof_type.name}. Call setup() first."
            )

        return MockZKPVerifier(proof_type, params)

    def get_public_parameters(
        self, proof_type: ComplianceProofType
    ) -> PublicParameters | None:
        """Get public parameters for a proof type."""
        return self._parameters.get(proof_type)

    def setup_all(self) -> dict[ComplianceProofType, PublicParameters]:
        """Convenience method to set up all proof types.

        Returns:
            Dictionary mapping proof types to their parameters
        """
        for proof_type in ComplianceProofType:
            self.setup(proof_type)
        return dict(self._parameters)
