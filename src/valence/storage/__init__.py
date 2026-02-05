"""Valence Resilient Storage - Erasure coding and integrity verification.

This module implements the resilient storage layer per SPEC.md, providing:
- Reed-Solomon erasure coding for distributed redundancy
- Merkle tree integrity verification
- Configurable redundancy levels
- Recovery from partial data loss

Example usage:
    from valence.storage import (
        ErasureCodec,
        RedundancyLevel,
        MerkleTree,
        StorageShard,
        ShardSet,
    )

    # Create codec with federation-level redundancy (5 of 9)
    codec = ErasureCodec(RedundancyLevel.FEDERATION)

    # Encode data into shards
    shards = codec.encode(belief_bytes)

    # Verify integrity
    assert codec.verify_integrity(shards)

    # Recover from partial data (any k shards)
    recovered = codec.decode(partial_shards)
"""

from .backend import (
    BackendRegistry,
    LocalFileBackend,
    MemoryBackend,
    StorageBackend,
)
from .erasure import ErasureCodec, ErasureCodingError
from .integrity import (
    IntegrityVerifier,
    MerkleProof,
    MerkleTree,
    compute_hash,
    verify_proof,
)
from .models import (
    IntegrityReport,
    RecoveryResult,
    RedundancyLevel,
    ShardMetadata,
    ShardSet,
    StorageShard,
)

__all__ = [
    # Models
    "RedundancyLevel",
    "StorageShard",
    "ShardSet",
    "ShardMetadata",
    "RecoveryResult",
    "IntegrityReport",
    # Erasure coding
    "ErasureCodec",
    "ErasureCodingError",
    # Integrity
    "MerkleTree",
    "MerkleProof",
    "compute_hash",
    "verify_proof",
    "IntegrityVerifier",
    # Backends
    "StorageBackend",
    "LocalFileBackend",
    "MemoryBackend",
    "BackendRegistry",
]
