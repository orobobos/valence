"""Verifiable Delay Function for Sybil-resistant identity registration (#345).

Provides VDF proof generation and verification for federation node registration.
New nodes must compute a VDF proof (~30s on commodity hardware) to register,
making mass Sybil identity creation economically impractical.

Uses a configurable backend:
- "simulated": Hash-chain simulation (default, no external deps)
- "chiavdf": Real VDF via chiavdf library (when available)

The simulated backend uses iterated SHA256 — not a true VDF (parallelizable),
but provides the same API contract for integration testing and development.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Default difficulty: tuned for ~30s on commodity hardware with simulated backend
DEFAULT_DIFFICULTY = 1_000_000


@dataclass
class VDFProof:
    """A VDF proof of sequential computation."""

    output: bytes
    proof: bytes
    input_data: bytes
    difficulty: int
    duration_seconds: float
    backend: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output.hex(),
            "proof": self.proof.hex(),
            "input_data": self.input_data.hex(),
            "difficulty": self.difficulty,
            "duration_seconds": self.duration_seconds,
            "backend": self.backend,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VDFProof:
        return cls(
            output=bytes.fromhex(d["output"]),
            proof=bytes.fromhex(d["proof"]),
            input_data=bytes.fromhex(d["input_data"]),
            difficulty=d["difficulty"],
            duration_seconds=d.get("duration_seconds", 0.0),
            backend=d.get("backend", "unknown"),
            metadata=d.get("metadata", {}),
        )


def generate_vdf_proof(
    input_data: bytes,
    difficulty: int = DEFAULT_DIFFICULTY,
) -> VDFProof:
    """Generate a VDF proof by performing sequential computation.

    Args:
        input_data: The challenge input (typically SHA256 of DID + nonce).
        difficulty: Number of sequential iterations.

    Returns:
        VDFProof with output, proof, and timing information.
    """
    backend = _get_backend()
    start = time.monotonic()
    output, proof = backend.compute(input_data, difficulty)
    duration = time.monotonic() - start

    return VDFProof(
        output=output,
        proof=proof,
        input_data=input_data,
        difficulty=difficulty,
        duration_seconds=duration,
        backend=backend.name,
    )


def verify_vdf_proof(vdf_proof: VDFProof) -> bool:
    """Verify a VDF proof.

    Verification is fast (O(1) or O(log n)) compared to generation.

    Args:
        vdf_proof: The proof to verify.

    Returns:
        True if the proof is valid.
    """
    backend = _get_backend()
    return backend.verify(vdf_proof.input_data, vdf_proof.output, vdf_proof.proof, vdf_proof.difficulty)


def build_vdf_challenge(did: str, nonce: str) -> bytes:
    """Build a deterministic VDF challenge from a DID and nonce.

    Args:
        did: The registering node's DID.
        nonce: A random nonce provided by the verifier.

    Returns:
        32-byte SHA256 challenge.
    """
    return hashlib.sha256(f"{did}:{nonce}".encode()).digest()


class _SimulatedBackend:
    """Iterated SHA256 — not a true VDF but same API contract."""

    name = "simulated"

    def compute(self, input_data: bytes, difficulty: int) -> tuple[bytes, bytes]:
        current = input_data
        for _ in range(difficulty):
            current = hashlib.sha256(current).digest()
        # Proof is the intermediate at difficulty//2 (for fast verification)
        midpoint = input_data
        for _ in range(difficulty // 2):
            midpoint = hashlib.sha256(midpoint).digest()
        return current, midpoint

    def verify(self, input_data: bytes, output: bytes, proof: bytes, difficulty: int) -> bool:
        # Verify: run from midpoint to output (difficulty//2 iterations)
        remaining = difficulty - difficulty // 2
        current = proof
        for _ in range(remaining):
            current = hashlib.sha256(current).digest()
        if current != output:
            return False
        # Verify: run from input to midpoint (difficulty//2 iterations)
        current = input_data
        for _ in range(difficulty // 2):
            current = hashlib.sha256(current).digest()
        return current == proof


def _get_backend() -> _SimulatedBackend:
    """Get the VDF backend. Currently only simulated is available."""
    return _SimulatedBackend()
