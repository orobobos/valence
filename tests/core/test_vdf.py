"""Tests for VDF module (#345).

Tests cover:
1. VDFProof serialization round-trip
2. generate_vdf_proof produces valid proof
3. verify_vdf_proof accepts valid proof
4. verify_vdf_proof rejects tampered proof
5. build_vdf_challenge is deterministic
6. Low difficulty proof (fast for tests)
"""

from __future__ import annotations

import pytest

from valence.core.vdf import (
    VDFProof,
    build_vdf_challenge,
    generate_vdf_proof,
    verify_vdf_proof,
)

# Use very low difficulty for tests (fast)
TEST_DIFFICULTY = 100


class TestVDFProof:
    """Test VDFProof dataclass."""

    def test_to_dict_from_dict_round_trip(self):
        proof = VDFProof(
            output=b"\x01" * 32,
            proof=b"\x02" * 32,
            input_data=b"\x03" * 32,
            difficulty=1000,
            duration_seconds=1.5,
            backend="simulated",
        )
        d = proof.to_dict()
        restored = VDFProof.from_dict(d)
        assert restored.output == proof.output
        assert restored.proof == proof.proof
        assert restored.difficulty == proof.difficulty
        assert restored.backend == "simulated"


class TestGenerateAndVerify:
    """Test VDF proof generation and verification."""

    def test_generates_valid_proof(self):
        challenge = build_vdf_challenge("did:valence:test", "nonce123")
        proof = generate_vdf_proof(challenge, difficulty=TEST_DIFFICULTY)

        assert proof.output != proof.input_data
        assert proof.difficulty == TEST_DIFFICULTY
        assert proof.duration_seconds >= 0
        assert proof.backend == "simulated"

    def test_verification_accepts_valid(self):
        challenge = build_vdf_challenge("did:valence:test", "nonce456")
        proof = generate_vdf_proof(challenge, difficulty=TEST_DIFFICULTY)

        assert verify_vdf_proof(proof) is True

    def test_verification_rejects_tampered_output(self):
        challenge = build_vdf_challenge("did:valence:test", "nonce789")
        proof = generate_vdf_proof(challenge, difficulty=TEST_DIFFICULTY)
        proof.output = b"\xff" * 32  # Tamper with output

        assert verify_vdf_proof(proof) is False

    def test_verification_rejects_tampered_proof(self):
        challenge = build_vdf_challenge("did:valence:test", "nonce000")
        proof = generate_vdf_proof(challenge, difficulty=TEST_DIFFICULTY)
        proof.proof = b"\xff" * 32  # Tamper with midpoint proof

        assert verify_vdf_proof(proof) is False

    def test_verification_rejects_wrong_input(self):
        challenge = build_vdf_challenge("did:valence:test", "nonce111")
        proof = generate_vdf_proof(challenge, difficulty=TEST_DIFFICULTY)
        proof.input_data = b"\x00" * 32  # Wrong input

        assert verify_vdf_proof(proof) is False

    def test_different_inputs_different_outputs(self):
        c1 = build_vdf_challenge("did:valence:alice", "n1")
        c2 = build_vdf_challenge("did:valence:bob", "n2")
        p1 = generate_vdf_proof(c1, difficulty=TEST_DIFFICULTY)
        p2 = generate_vdf_proof(c2, difficulty=TEST_DIFFICULTY)

        assert p1.output != p2.output


class TestBuildVDFChallenge:
    """Test challenge construction."""

    def test_deterministic(self):
        c1 = build_vdf_challenge("did:valence:test", "nonce")
        c2 = build_vdf_challenge("did:valence:test", "nonce")
        assert c1 == c2

    def test_different_inputs(self):
        c1 = build_vdf_challenge("did:valence:a", "n")
        c2 = build_vdf_challenge("did:valence:b", "n")
        assert c1 != c2

    def test_returns_32_bytes(self):
        c = build_vdf_challenge("did", "nonce")
        assert len(c) == 32
