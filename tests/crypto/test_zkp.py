"""Tests for Zero-Knowledge Proof abstraction layer.

These tests verify the ZKP interface and mock implementation work correctly
for compliance verification use cases.
"""

from datetime import datetime, timedelta

import pytest

from valence.crypto.zkp import (
    ComplianceProof,
    # Types
    ComplianceProofType,
    MockZKPBackend,
    # Mock implementations
    PublicParameters,
    VerificationResult,
    ZKPBackend,
    ZKPCircuitNotFoundError,
    # Exceptions
    ZKPInputError,
    ZKPProver,
    ZKPVerifier,
    # Utilities
    hash_public_inputs,
    verify_proof,
)

# =============================================================================
# Data Class Tests
# =============================================================================


class TestPublicParameters:
    """Tests for PublicParameters dataclass."""

    def test_create_parameters(self):
        """Test creating public parameters."""
        params = PublicParameters(
            proof_type=ComplianceProofType.HAS_CONSENT,
            circuit_hash=b"circuit" * 4,
            verification_key=b"vk" * 16,
            proving_key_hash=b"pk" * 16,
        )

        assert params.proof_type == ComplianceProofType.HAS_CONSENT
        assert len(params.circuit_hash) == 28
        assert params.version == "1.0.0"
        assert isinstance(params.created_at, datetime)

    def test_parameters_serialization(self):
        """Test parameters to_dict/from_dict roundtrip."""
        params = PublicParameters(
            proof_type=ComplianceProofType.WITHIN_POLICY,
            circuit_hash=b"0" * 32,
            verification_key=b"1" * 32,
            proving_key_hash=b"2" * 32,
            version="2.0.0",
        )

        data = params.to_dict()
        restored = PublicParameters.from_dict(data)

        assert restored.proof_type == params.proof_type
        assert restored.circuit_hash == params.circuit_hash
        assert restored.verification_key == params.verification_key
        assert restored.version == params.version


class TestComplianceProof:
    """Tests for ComplianceProof dataclass."""

    def test_create_proof(self):
        """Test creating a compliance proof."""
        proof = ComplianceProof(
            proof_type=ComplianceProofType.NOT_REVOKED,
            proof_data=b"proof" * 10,
            public_inputs_hash=b"hash" * 8,
        )

        assert proof.proof_type == ComplianceProofType.NOT_REVOKED
        assert len(proof.proof_data) == 50
        assert proof.expires_at is None
        assert not proof.is_expired

    def test_proof_expiration(self):
        """Test proof expiration checking."""
        # Non-expired proof
        future = datetime.now() + timedelta(hours=1)
        proof = ComplianceProof(
            proof_type=ComplianceProofType.HAS_CONSENT,
            proof_data=b"0" * 64,
            public_inputs_hash=b"1" * 32,
            expires_at=future,
        )
        assert not proof.is_expired

        # Expired proof
        past = datetime.now() - timedelta(hours=1)
        expired_proof = ComplianceProof(
            proof_type=ComplianceProofType.HAS_CONSENT,
            proof_data=b"0" * 64,
            public_inputs_hash=b"1" * 32,
            expires_at=past,
        )
        assert expired_proof.is_expired

    def test_proof_serialization(self):
        """Test proof to_dict/from_dict roundtrip."""
        proof = ComplianceProof(
            proof_type=ComplianceProofType.MEMBER_OF_DOMAIN,
            proof_data=b"proof123",
            public_inputs_hash=b"hash456",
            metadata={"circuit_version": "1.0.0", "mock": True},
        )

        data = proof.to_dict()
        restored = ComplianceProof.from_dict(data)

        assert restored.proof_type == proof.proof_type
        assert restored.proof_data == proof.proof_data
        assert restored.public_inputs_hash == proof.public_inputs_hash
        assert restored.metadata == proof.metadata


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""

    def test_successful_result(self):
        """Test creating a successful verification result."""
        result = VerificationResult(
            valid=True,
            proof_type=ComplianceProofType.HAS_CONSENT,
            public_inputs_hash=b"hash" * 8,
            verification_time_ms=15.5,
        )

        assert result.valid
        assert result.error_message is None
        assert result.verification_time_ms == 15.5

    def test_failed_result(self):
        """Test creating a failed verification result."""
        result = VerificationResult(
            valid=False,
            proof_type=ComplianceProofType.NOT_REVOKED,
            public_inputs_hash=b"hash" * 8,
            error_message="Public inputs hash mismatch",
        )

        assert not result.valid
        assert "mismatch" in result.error_message

    def test_result_serialization(self):
        """Test result to_dict."""
        result = VerificationResult(
            valid=True,
            proof_type=ComplianceProofType.WITHIN_POLICY,
            public_inputs_hash=b"0" * 32,
        )

        data = result.to_dict()

        assert data["valid"] is True
        assert data["proof_type"] == "WITHIN_POLICY"


# =============================================================================
# Utility Function Tests
# =============================================================================


class TestHashPublicInputs:
    """Tests for hash_public_inputs utility."""

    def test_deterministic_hashing(self):
        """Test that hashing is deterministic."""
        inputs = {"user_id": "alice", "action": "read", "timestamp": 12345}

        hash1 = hash_public_inputs(inputs)
        hash2 = hash_public_inputs(inputs)

        assert hash1 == hash2
        assert len(hash1) == 32  # SHA-256

    def test_order_independent(self):
        """Test that hash is independent of dict insertion order."""
        inputs1 = {"a": 1, "b": 2, "c": 3}
        inputs2 = {"c": 3, "a": 1, "b": 2}

        assert hash_public_inputs(inputs1) == hash_public_inputs(inputs2)

    def test_different_inputs_different_hash(self):
        """Test that different inputs produce different hashes."""
        hash1 = hash_public_inputs({"user": "alice"})
        hash2 = hash_public_inputs({"user": "bob"})

        assert hash1 != hash2


# =============================================================================
# Mock Backend Tests
# =============================================================================


class TestMockZKPBackend:
    """Tests for MockZKPBackend."""

    @pytest.fixture
    def backend(self):
        """Create a fresh backend for each test."""
        return MockZKPBackend()

    def test_setup_creates_parameters(self, backend):
        """Test that setup creates public parameters."""
        params = backend.setup(ComplianceProofType.HAS_CONSENT)

        assert params.proof_type == ComplianceProofType.HAS_CONSENT
        assert len(params.circuit_hash) == 32
        assert len(params.verification_key) == 32
        assert len(params.proving_key_hash) == 32

    def test_setup_is_deterministic(self, backend):
        """Test that setup produces deterministic results."""
        params1 = backend.setup(ComplianceProofType.WITHIN_POLICY)

        backend2 = MockZKPBackend()
        params2 = backend2.setup(ComplianceProofType.WITHIN_POLICY)

        assert params1.circuit_hash == params2.circuit_hash
        assert params1.verification_key == params2.verification_key

    def test_setup_all_proof_types(self, backend):
        """Test setting up all proof types."""
        all_params = backend.setup_all()

        assert len(all_params) == len(ComplianceProofType)
        for proof_type in ComplianceProofType:
            assert proof_type in all_params

    def test_get_public_parameters(self, backend):
        """Test retrieving public parameters."""
        # Before setup
        assert backend.get_public_parameters(ComplianceProofType.NOT_REVOKED) is None

        # After setup
        backend.setup(ComplianceProofType.NOT_REVOKED)
        params = backend.get_public_parameters(ComplianceProofType.NOT_REVOKED)

        assert params is not None
        assert params.proof_type == ComplianceProofType.NOT_REVOKED

    def test_create_prover_without_setup_fails(self, backend):
        """Test that creating a prover without setup raises an error."""
        with pytest.raises(ZKPCircuitNotFoundError) as exc_info:
            backend.create_prover(ComplianceProofType.HAS_CONSENT)

        assert "setup" in str(exc_info.value).lower()

    def test_create_verifier_without_setup_fails(self, backend):
        """Test that creating a verifier without setup raises an error."""
        with pytest.raises(ZKPCircuitNotFoundError):
            backend.create_verifier(ComplianceProofType.MEMBER_OF_DOMAIN)

    def test_create_prover_after_setup(self, backend):
        """Test creating a prover after setup."""
        backend.setup(ComplianceProofType.WITHIN_POLICY)
        prover = backend.create_prover(ComplianceProofType.WITHIN_POLICY)

        assert prover.proof_type == ComplianceProofType.WITHIN_POLICY

    def test_create_verifier_after_setup(self, backend):
        """Test creating a verifier after setup."""
        backend.setup(ComplianceProofType.NOT_REVOKED)
        verifier = backend.create_verifier(ComplianceProofType.NOT_REVOKED)

        assert verifier.proof_type == ComplianceProofType.NOT_REVOKED


# =============================================================================
# Mock Prover Tests
# =============================================================================


class TestMockZKPProver:
    """Tests for MockZKPProver."""

    @pytest.fixture
    def backend(self):
        """Create a backend with all circuits set up."""
        backend = MockZKPBackend()
        backend.setup_all()
        return backend

    def test_prove_has_consent(self, backend):
        """Test generating HAS_CONSENT proof."""
        prover = backend.create_prover(ComplianceProofType.HAS_CONSENT)

        proof = prover.prove(
            private_inputs={"consent_record": b"consent-data-hash"},
            public_inputs={"user_id": "alice", "action": "read"},
        )

        assert proof.proof_type == ComplianceProofType.HAS_CONSENT
        assert len(proof.proof_data) == 64
        assert proof.metadata.get("mock") is True

    def test_prove_within_policy(self, backend):
        """Test generating WITHIN_POLICY proof."""
        prover = backend.create_prover(ComplianceProofType.WITHIN_POLICY)

        proof = prover.prove(
            private_inputs={
                "operation_details": {"type": "data_access", "scope": "limited"},
                "policy_evaluation": {"result": "allow", "rules_checked": 5},
            },
            public_inputs={
                "policy_hash": "abc123",
                "operation_type": "data_access",
            },
        )

        assert proof.proof_type == ComplianceProofType.WITHIN_POLICY

    def test_prove_not_revoked(self, backend):
        """Test generating NOT_REVOKED proof."""
        prover = backend.create_prover(ComplianceProofType.NOT_REVOKED)

        proof = prover.prove(
            private_inputs={
                "credential": b"my-credential",
                "revocation_proof": b"non-membership-proof",
            },
            public_inputs={
                "credential_commitment": "commitment-hash",
                "revocation_accumulator": "accumulator-value",
            },
        )

        assert proof.proof_type == ComplianceProofType.NOT_REVOKED

    def test_prove_member_of_domain(self, backend):
        """Test generating MEMBER_OF_DOMAIN proof."""
        prover = backend.create_prover(ComplianceProofType.MEMBER_OF_DOMAIN)

        proof = prover.prove(
            private_inputs={
                "member_credential": b"domain-credential",
                "merkle_proof": [b"sibling1", b"sibling2"],
            },
            public_inputs={
                "domain_id": "acme-corp",
                "membership_root": "merkle-root-hash",
            },
        )

        assert proof.proof_type == ComplianceProofType.MEMBER_OF_DOMAIN

    def test_missing_private_inputs_raises_error(self, backend):
        """Test that missing private inputs raises ZKPInputError."""
        prover = backend.create_prover(ComplianceProofType.HAS_CONSENT)

        with pytest.raises(ZKPInputError) as exc_info:
            prover.prove(
                private_inputs={},  # Missing consent_record
                public_inputs={"user_id": "alice", "action": "read"},
            )

        assert "consent_record" in str(exc_info.value)

    def test_missing_public_inputs_raises_error(self, backend):
        """Test that missing public inputs raises ZKPInputError."""
        prover = backend.create_prover(ComplianceProofType.HAS_CONSENT)

        with pytest.raises(ZKPInputError) as exc_info:
            prover.prove(
                private_inputs={"consent_record": b"data"},
                public_inputs={"user_id": "alice"},  # Missing action
            )

        assert "action" in str(exc_info.value)

    def test_validate_inputs_returns_true(self, backend):
        """Test that validate_inputs returns True for valid inputs."""
        prover = backend.create_prover(ComplianceProofType.HAS_CONSENT)

        result = prover.validate_inputs(
            private_inputs={"consent_record": b"data"},
            public_inputs={"user_id": "alice", "action": "read"},
        )

        assert result is True

    def test_proof_deterministic_for_same_public_inputs(self, backend):
        """Test that the public inputs hash is deterministic."""
        prover = backend.create_prover(ComplianceProofType.HAS_CONSENT)

        public_inputs = {"user_id": "alice", "action": "read"}

        proof1 = prover.prove(
            private_inputs={"consent_record": b"data1"},
            public_inputs=public_inputs,
        )
        proof2 = prover.prove(
            private_inputs={"consent_record": b"data2"},
            public_inputs=public_inputs,
        )

        # Same public inputs should produce same hash
        assert proof1.public_inputs_hash == proof2.public_inputs_hash
        # But different proof data (due to random component)
        assert proof1.proof_data != proof2.proof_data


# =============================================================================
# Mock Verifier Tests
# =============================================================================


class TestMockZKPVerifier:
    """Tests for MockZKPVerifier."""

    @pytest.fixture
    def backend(self):
        """Create a backend with all circuits set up."""
        backend = MockZKPBackend()
        backend.setup_all()
        return backend

    def test_verify_valid_proof(self, backend):
        """Test verifying a valid proof."""
        public_inputs = {"user_id": "alice", "action": "read"}

        prover = backend.create_prover(ComplianceProofType.HAS_CONSENT)
        proof = prover.prove(
            private_inputs={"consent_record": b"consent"},
            public_inputs=public_inputs,
        )

        verifier = backend.create_verifier(ComplianceProofType.HAS_CONSENT)
        result = verifier.verify(proof, public_inputs)

        assert result.valid
        assert result.error_message is None
        assert result.verification_time_ms >= 0

    def test_verify_wrong_public_inputs(self, backend):
        """Test that wrong public inputs fail verification."""
        prover = backend.create_prover(ComplianceProofType.HAS_CONSENT)
        proof = prover.prove(
            private_inputs={"consent_record": b"consent"},
            public_inputs={"user_id": "alice", "action": "read"},
        )

        verifier = backend.create_verifier(ComplianceProofType.HAS_CONSENT)

        # Verify with different public inputs
        result = verifier.verify(proof, {"user_id": "bob", "action": "read"})

        assert not result.valid
        assert "hash mismatch" in result.error_message.lower()

    def test_verify_wrong_proof_type(self, backend):
        """Test that wrong proof type fails verification."""
        prover = backend.create_prover(ComplianceProofType.HAS_CONSENT)
        proof = prover.prove(
            private_inputs={"consent_record": b"consent"},
            public_inputs={"user_id": "alice", "action": "read"},
        )

        # Try to verify with wrong verifier
        verifier = backend.create_verifier(ComplianceProofType.NOT_REVOKED)
        result = verifier.verify(proof, {"user_id": "alice", "action": "read"})

        assert not result.valid
        assert "type mismatch" in result.error_message.lower()

    def test_verify_expired_proof(self, backend):
        """Test that expired proofs fail verification."""
        prover = backend.create_prover(ComplianceProofType.HAS_CONSENT)
        public_inputs = {"user_id": "alice", "action": "read"}

        proof = prover.prove(
            private_inputs={"consent_record": b"consent"},
            public_inputs=public_inputs,
        )

        # Manually expire the proof
        proof.expires_at = datetime.now() - timedelta(hours=1)

        verifier = backend.create_verifier(ComplianceProofType.HAS_CONSENT)
        result = verifier.verify(proof, public_inputs)

        assert not result.valid
        assert "expired" in result.error_message.lower()

    def test_verify_invalid_proof_length(self, backend):
        """Test that proofs with wrong length fail verification."""
        public_inputs = {"user_id": "alice", "action": "read"}

        # Create a malformed proof
        proof = ComplianceProof(
            proof_type=ComplianceProofType.HAS_CONSENT,
            proof_data=b"too-short",  # Wrong length
            public_inputs_hash=hash_public_inputs(public_inputs),
        )

        verifier = backend.create_verifier(ComplianceProofType.HAS_CONSENT)
        result = verifier.verify(proof, public_inputs)

        assert not result.valid
        assert "length" in result.error_message.lower()


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestVerifyProofFunction:
    """Tests for the verify_proof convenience function."""

    def test_verify_proof_with_backend(self):
        """Test verify_proof with explicit backend."""
        backend = MockZKPBackend()
        backend.setup(ComplianceProofType.WITHIN_POLICY)

        public_inputs = {"policy_hash": "abc", "operation_type": "read"}

        prover = backend.create_prover(ComplianceProofType.WITHIN_POLICY)
        proof = prover.prove(
            private_inputs={
                "operation_details": {},
                "policy_evaluation": {},
            },
            public_inputs=public_inputs,
        )

        assert verify_proof(proof, public_inputs, backend) is True

    def test_verify_proof_creates_backend(self):
        """Test verify_proof creates backend if none provided."""
        # Create proof with one backend
        backend = MockZKPBackend()
        backend.setup(ComplianceProofType.HAS_CONSENT)

        public_inputs = {"user_id": "test", "action": "write"}

        prover = backend.create_prover(ComplianceProofType.HAS_CONSENT)
        proof = prover.prove(
            private_inputs={"consent_record": b"data"},
            public_inputs=public_inputs,
        )

        # Verify without providing backend
        assert verify_proof(proof, public_inputs) is True

    def test_verify_proof_returns_false_on_failure(self):
        """Test verify_proof returns False on verification failure."""
        backend = MockZKPBackend()
        backend.setup(ComplianceProofType.HAS_CONSENT)

        prover = backend.create_prover(ComplianceProofType.HAS_CONSENT)
        proof = prover.prove(
            private_inputs={"consent_record": b"data"},
            public_inputs={"user_id": "alice", "action": "read"},
        )

        # Different public inputs should fail
        assert (
            verify_proof(
                proof,
                {"user_id": "bob", "action": "read"},
                backend,
            )
            is False
        )

    def test_verify_proof_expired(self):
        """Test verify_proof returns False for expired proofs."""
        backend = MockZKPBackend()
        backend.setup(ComplianceProofType.HAS_CONSENT)

        public_inputs = {"user_id": "alice", "action": "read"}

        prover = backend.create_prover(ComplianceProofType.HAS_CONSENT)
        proof = prover.prove(
            private_inputs={"consent_record": b"data"},
            public_inputs=public_inputs,
        )

        # Expire the proof
        proof.expires_at = datetime.now() - timedelta(seconds=1)

        assert verify_proof(proof, public_inputs, backend) is False


# =============================================================================
# End-to-End Tests
# =============================================================================


class TestEndToEnd:
    """End-to-end tests for the ZKP workflow."""

    def test_full_consent_workflow(self):
        """Test complete consent proof workflow."""
        # 1. Setup
        backend = MockZKPBackend()
        backend.setup(ComplianceProofType.HAS_CONSENT)

        # 2. Prover generates proof
        prover = backend.create_prover(ComplianceProofType.HAS_CONSENT)

        public_inputs = {
            "user_id": "user-123",
            "action": "process_data",
            "resource_type": "personal_data",
        }

        proof = prover.prove(
            private_inputs={
                "consent_record": b"signed-consent-hash",
                "consent_signature": b"signature",
            },
            public_inputs=public_inputs,
        )

        # 3. Proof can be serialized and sent
        proof_dict = proof.to_dict()

        # 4. Verifier receives and deserializes
        received_proof = ComplianceProof.from_dict(proof_dict)

        # 5. Verifier verifies
        verifier = backend.create_verifier(ComplianceProofType.HAS_CONSENT)
        result = verifier.verify(received_proof, public_inputs)

        assert result.valid

    def test_full_domain_membership_workflow(self):
        """Test complete domain membership proof workflow."""
        backend = MockZKPBackend()
        backend.setup(ComplianceProofType.MEMBER_OF_DOMAIN)

        # Organization creates merkle tree of members
        domain_id = "acme-corporation"
        membership_root = "merkle-root-abc123"

        public_inputs = {
            "domain_id": domain_id,
            "membership_root": membership_root,
        }

        # Member proves they belong without revealing identity
        prover = backend.create_prover(ComplianceProofType.MEMBER_OF_DOMAIN)
        proof = prover.prove(
            private_inputs={
                "member_credential": b"my-employee-credential",
                "merkle_proof": [b"path", b"to", b"root"],
            },
            public_inputs=public_inputs,
        )

        # Verifier checks membership
        assert verify_proof(proof, public_inputs, backend)

    def test_multiple_proof_types(self):
        """Test using multiple proof types together."""
        backend = MockZKPBackend()
        backend.setup_all()

        # Generate different proofs
        proofs = {}

        # 1. Consent proof
        prover1 = backend.create_prover(ComplianceProofType.HAS_CONSENT)
        proofs["consent"] = prover1.prove(
            private_inputs={"consent_record": b"consent"},
            public_inputs={"user_id": "alice", "action": "read"},
        )

        # 2. Policy proof
        prover2 = backend.create_prover(ComplianceProofType.WITHIN_POLICY)
        proofs["policy"] = prover2.prove(
            private_inputs={"operation_details": {}, "policy_evaluation": {}},
            public_inputs={"policy_hash": "hash", "operation_type": "read"},
        )

        # 3. Non-revocation proof
        prover3 = backend.create_prover(ComplianceProofType.NOT_REVOKED)
        proofs["revocation"] = prover3.prove(
            private_inputs={"credential": b"cred", "revocation_proof": b"proof"},
            public_inputs={
                "credential_commitment": "commit",
                "revocation_accumulator": "acc",
            },
        )

        # Verify each with appropriate verifier
        v1 = backend.create_verifier(ComplianceProofType.HAS_CONSENT)
        v2 = backend.create_verifier(ComplianceProofType.WITHIN_POLICY)
        v3 = backend.create_verifier(ComplianceProofType.NOT_REVOKED)

        assert v1.verify(
            proofs["consent"], {"user_id": "alice", "action": "read"}
        ).valid
        assert v2.verify(
            proofs["policy"], {"policy_hash": "hash", "operation_type": "read"}
        ).valid
        assert v3.verify(
            proofs["revocation"],
            {"credential_commitment": "commit", "revocation_accumulator": "acc"},
        ).valid


# =============================================================================
# Interface Compliance Tests
# =============================================================================


class TestInterfaceCompliance:
    """Tests to ensure mock implementation follows the abstract interface."""

    def test_backend_is_zkp_backend(self):
        """Test MockZKPBackend is instance of ZKPBackend."""
        backend = MockZKPBackend()
        assert isinstance(backend, ZKPBackend)

    def test_prover_is_zkp_prover(self):
        """Test MockZKPProver is instance of ZKPProver."""
        backend = MockZKPBackend()
        backend.setup(ComplianceProofType.HAS_CONSENT)
        prover = backend.create_prover(ComplianceProofType.HAS_CONSENT)
        assert isinstance(prover, ZKPProver)

    def test_verifier_is_zkp_verifier(self):
        """Test MockZKPVerifier is instance of ZKPVerifier."""
        backend = MockZKPBackend()
        backend.setup(ComplianceProofType.HAS_CONSENT)
        verifier = backend.create_verifier(ComplianceProofType.HAS_CONSENT)
        assert isinstance(verifier, ZKPVerifier)


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_public_inputs(self):
        """Test handling of empty public inputs."""
        # Empty dict should hash consistently
        hash1 = hash_public_inputs({})
        hash2 = hash_public_inputs({})
        assert hash1 == hash2

    def test_complex_public_inputs(self):
        """Test hashing of complex public input values."""
        inputs = {
            "nested": {"a": 1, "b": [1, 2, 3]},
            "list": [{"x": 1}, {"y": 2}],
            "unicode": "héllo wörld 🌍",
        }

        hash1 = hash_public_inputs(inputs)
        hash2 = hash_public_inputs(inputs)
        assert hash1 == hash2

    def test_proof_type_enum_values(self):
        """Test all proof types have unique values."""
        values = [pt.value for pt in ComplianceProofType]
        assert len(values) == len(set(values))  # All unique
        assert len(values) == 4  # Expected count

    def test_extra_inputs_allowed(self):
        """Test that extra inputs beyond required are allowed."""
        backend = MockZKPBackend()
        backend.setup(ComplianceProofType.HAS_CONSENT)
        prover = backend.create_prover(ComplianceProofType.HAS_CONSENT)

        # Extra inputs should not raise
        proof = prover.prove(
            private_inputs={
                "consent_record": b"data",
                "extra_private": "value",  # Extra
            },
            public_inputs={
                "user_id": "alice",
                "action": "read",
                "extra_public": 123,  # Extra
            },
        )

        assert proof is not None
