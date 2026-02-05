"""Tests for Merkle tree integrity verification.

Comprehensive tests for:
- Merkle tree construction
- Proof generation and verification
- Integrity checking of shard sets
"""

import hashlib
from uuid import uuid4

import pytest

from valence.storage.integrity import (
    IntegrityVerifier,
    MerkleProof,
    MerkleTree,
    compute_hash,
    verify_proof,
)
from valence.storage.models import (
    ShardMetadata,
    ShardSet,
    StorageShard,
)


class TestComputeHash:
    """Tests for hash computation."""

    def test_sha256_default(self):
        """Default hash is SHA-256."""
        data = b"test data"
        expected = hashlib.sha256(data).hexdigest()
        assert compute_hash(data) == expected

    def test_sha256_explicit(self):
        """Explicit SHA-256 hash."""
        data = b"test data"
        expected = hashlib.sha256(data).hexdigest()
        assert compute_hash(data, "sha256") == expected

    def test_sha3_256(self):
        """SHA3-256 hash."""
        data = b"test data"
        expected = hashlib.sha3_256(data).hexdigest()
        assert compute_hash(data, "sha3_256") == expected

    def test_blake2b(self):
        """BLAKE2b hash."""
        data = b"test data"
        expected = hashlib.blake2b(data, digest_size=32).hexdigest()
        assert compute_hash(data, "blake2b") == expected

    def test_invalid_algorithm(self):
        """Invalid algorithm raises error."""
        with pytest.raises(ValueError) as exc_info:
            compute_hash(b"data", "md5")
        assert "Unsupported hash algorithm" in str(exc_info.value)

    def test_empty_data(self):
        """Hash of empty data."""
        expected = hashlib.sha256(b"").hexdigest()
        assert compute_hash(b"") == expected

    def test_deterministic(self):
        """Same data produces same hash."""
        data = b"consistent data"
        h1 = compute_hash(data)
        h2 = compute_hash(data)
        assert h1 == h2


class TestMerkleTree:
    """Tests for Merkle tree construction."""

    def test_empty_tree(self):
        """Empty tree has empty root."""
        tree = MerkleTree.from_data([])
        assert tree.root_hash == ""
        assert tree.height == 1
        assert tree.leaf_count == 0

    def test_single_leaf(self):
        """Single leaf tree."""
        data = b"single leaf"
        tree = MerkleTree.from_data([data])

        assert tree.leaf_count == 1
        assert tree.root_hash == compute_hash(data)

    def test_two_leaves(self):
        """Two leaf tree."""
        data1, data2 = b"leaf1", b"leaf2"
        tree = MerkleTree.from_data([data1, data2])

        h1 = compute_hash(data1)
        h2 = compute_hash(data2)
        expected_root = compute_hash(bytes.fromhex(h1) + bytes.fromhex(h2))

        assert tree.leaf_count == 2
        assert tree.root_hash == expected_root

    def test_power_of_two_leaves(self):
        """Tree with power-of-two leaves."""
        data = [f"leaf{i}".encode() for i in range(4)]
        tree = MerkleTree.from_data(data)

        assert tree.leaf_count == 4
        assert tree.height == 3  # 4 leaves -> 2 nodes -> 1 root

    def test_non_power_of_two_leaves(self):
        """Tree with non-power-of-two leaves handles padding."""
        data = [f"leaf{i}".encode() for i in range(5)]
        tree = MerkleTree.from_data(data)

        assert tree.leaf_count == 5
        # Should still produce a valid root
        assert tree.root_hash != ""

    def test_from_hashes(self):
        """Build tree from pre-computed hashes."""
        hashes = [
            compute_hash(b"data1"),
            compute_hash(b"data2"),
            compute_hash(b"data3"),
        ]
        tree = MerkleTree.from_hashes(hashes)

        assert tree.leaf_count == 3
        assert tree.leaves == hashes

    def test_from_shards(self):
        """Build tree from storage shards."""
        shards = []
        for i in range(3):
            data = f"shard{i}".encode()
            checksum = compute_hash(data)
            metadata = ShardMetadata(
                shard_id=uuid4(),
                index=i,
                checksum=checksum,
            )
            shards.append(StorageShard(data=data, metadata=metadata))

        tree = MerkleTree.from_shards(shards)

        assert tree.leaf_count == 3
        assert tree.leaves[0] == shards[0].metadata.checksum

    def test_to_dict(self):
        """Convert tree to dictionary."""
        data = [b"a", b"b"]
        tree = MerkleTree.from_data(data)

        d = tree.to_dict()
        assert "leaves" in d
        assert "root_hash" in d
        assert "height" in d
        assert "algorithm" in d


class TestMerkleProof:
    """Tests for Merkle proof generation and verification."""

    def test_proof_single_leaf(self):
        """Proof for single-leaf tree."""
        data = b"only leaf"
        tree = MerkleTree.from_data([data])
        proof = tree.get_proof(0)

        assert proof.leaf_hash == compute_hash(data)
        assert proof.leaf_index == 0
        assert proof.proof_hashes == []  # No siblings
        assert proof.root_hash == tree.root_hash

    def test_proof_two_leaves(self):
        """Proof for two-leaf tree."""
        data = [b"left", b"right"]
        tree = MerkleTree.from_data(data)

        # Proof for left leaf
        proof = tree.get_proof(0)
        assert proof.leaf_index == 0
        assert len(proof.proof_hashes) == 1
        assert proof.proof_hashes[0] == compute_hash(b"right")
        assert proof.proof_directions[0]  # Sibling is on right

        # Proof for right leaf
        proof = tree.get_proof(1)
        assert proof.leaf_index == 1
        assert len(proof.proof_hashes) == 1
        assert proof.proof_hashes[0] == compute_hash(b"left")
        assert not proof.proof_directions[0]  # Sibling is on left

    def test_proof_larger_tree(self):
        """Proof for larger tree."""
        data = [f"leaf{i}".encode() for i in range(8)]
        tree = MerkleTree.from_data(data)

        # Each proof should have log2(8) = 3 siblings
        for i in range(8):
            proof = tree.get_proof(i)
            assert proof.leaf_index == i
            assert len(proof.proof_hashes) == 3

    def test_proof_out_of_range(self):
        """Proof for invalid index raises error."""
        tree = MerkleTree.from_data([b"a", b"b"])

        with pytest.raises(IndexError):
            tree.get_proof(-1)
        with pytest.raises(IndexError):
            tree.get_proof(2)

    def test_verify_proof_valid(self):
        """Valid proof verifies correctly."""
        data = [f"data{i}".encode() for i in range(7)]
        tree = MerkleTree.from_data(data)

        for i in range(7):
            proof = tree.get_proof(i)
            assert verify_proof(proof)

    def test_verify_proof_invalid_leaf(self):
        """Proof with wrong leaf hash fails."""
        data = [b"a", b"b", b"c", b"d"]
        tree = MerkleTree.from_data(data)
        proof = tree.get_proof(0)

        # Tamper with leaf hash
        proof.leaf_hash = compute_hash(b"tampered")
        assert not verify_proof(proof)

    def test_verify_proof_invalid_root(self):
        """Proof with wrong root hash fails."""
        data = [b"a", b"b", b"c", b"d"]
        tree = MerkleTree.from_data(data)
        proof = tree.get_proof(0)

        # Tamper with root hash
        proof.root_hash = compute_hash(b"wrong root")
        assert not verify_proof(proof)

    def test_verify_proof_tampered_sibling(self):
        """Proof with tampered sibling fails."""
        data = [b"a", b"b", b"c", b"d"]
        tree = MerkleTree.from_data(data)
        proof = tree.get_proof(0)

        # Tamper with a sibling hash
        proof.proof_hashes[0] = compute_hash(b"wrong sibling")
        assert not verify_proof(proof)

    def test_proof_to_dict(self):
        """Proof serialization."""
        tree = MerkleTree.from_data([b"a", b"b"])
        proof = tree.get_proof(0)

        d = proof.to_dict()
        assert "leaf_hash" in d
        assert "leaf_index" in d
        assert "proof_hashes" in d
        assert "proof_directions" in d
        assert "root_hash" in d

    def test_proof_from_dict(self):
        """Proof deserialization."""
        tree = MerkleTree.from_data([b"a", b"b"])
        original = tree.get_proof(0)

        d = original.to_dict()
        restored = MerkleProof.from_dict(d)

        assert restored.leaf_hash == original.leaf_hash
        assert restored.leaf_index == original.leaf_index
        assert verify_proof(restored)


class TestMerkleTreeVerifyLeaf:
    """Tests for leaf verification."""

    def test_verify_leaf_valid(self):
        """Valid leaf data verifies."""
        data = [b"a", b"b", b"c"]
        tree = MerkleTree.from_data(data)

        for i, d in enumerate(data):
            assert tree.verify_leaf(i, d)

    def test_verify_leaf_invalid(self):
        """Invalid leaf data fails."""
        data = [b"a", b"b", b"c"]
        tree = MerkleTree.from_data(data)

        assert not tree.verify_leaf(0, b"wrong")

    def test_verify_leaf_out_of_range(self):
        """Out of range index returns False."""
        tree = MerkleTree.from_data([b"a", b"b"])

        assert not tree.verify_leaf(-1, b"a")
        assert not tree.verify_leaf(2, b"a")


class TestIntegrityVerifier:
    """Tests for IntegrityVerifier."""

    @pytest.fixture
    def verifier(self):
        """Create a verifier instance."""
        return IntegrityVerifier()

    @pytest.fixture
    def complete_shard_set(self):
        """Create a complete shard set."""
        shards = []
        for i in range(5):
            data = f"shard{i}".encode()
            checksum = compute_hash(data)
            metadata = ShardMetadata(
                shard_id=uuid4(),
                index=i,
                is_parity=(i >= 3),
                size_bytes=len(data),
                checksum=checksum,
            )
            shards.append(StorageShard(data=data, metadata=metadata))

        return ShardSet(
            shards=shards,
            data_shards_k=3,
            total_shards_n=5,
            original_size=100,
            original_checksum=compute_hash(b"original"),
        )

    def test_verify_complete_set(self, verifier, complete_shard_set):
        """Complete valid shard set passes verification."""
        report = verifier.verify_shard_set(complete_shard_set)

        assert report.is_valid
        assert report.valid_shards == 5
        assert report.corrupted_shards == []
        assert report.missing_shards == []
        assert report.can_recover

    def test_verify_with_missing_shards(self, verifier, complete_shard_set):
        """Verification reports missing shards."""
        complete_shard_set.shards[0] = None
        complete_shard_set.shards[2] = None

        report = verifier.verify_shard_set(complete_shard_set)

        assert not report.is_valid  # Not complete
        assert report.valid_shards == 3
        assert report.missing_shards == [0, 2]
        assert report.can_recover  # Still have k=3 valid shards

    def test_verify_with_corrupted_shards(self, verifier, complete_shard_set):
        """Verification detects corrupted shards."""
        # Corrupt a shard (data doesn't match checksum)
        complete_shard_set.shards[1] = StorageShard(
            data=b"corrupted data",
            metadata=complete_shard_set.shards[1].metadata,
        )

        report = verifier.verify_shard_set(complete_shard_set)

        assert not report.is_valid
        assert 1 in report.corrupted_shards

    def test_verify_unrecoverable(self, verifier, complete_shard_set):
        """Verification reports when recovery impossible."""
        # Remove too many shards (need 3, have only 2)
        complete_shard_set.shards[0] = None
        complete_shard_set.shards[1] = None
        complete_shard_set.shards[2] = None

        report = verifier.verify_shard_set(complete_shard_set)

        assert not report.is_valid
        assert not report.can_recover
        assert "Cannot recover" in report.details

    def test_verify_single_shard(self, verifier, complete_shard_set):
        """Verify individual shard integrity."""
        shard = complete_shard_set.shards[0]
        assert verifier.verify_shard(shard)

        # Corrupt it
        corrupted = StorageShard(
            data=b"wrong",
            metadata=shard.metadata,
        )
        assert not verifier.verify_shard(corrupted)

    def test_generate_merkle_root(self, verifier, complete_shard_set):
        """Generate Merkle root for shard set."""
        root = verifier.generate_merkle_root(complete_shard_set)

        assert root != ""
        assert len(root) == 64  # SHA-256 hex

    def test_generate_proof(self, verifier, complete_shard_set):
        """Generate proof for specific shard."""
        proof = verifier.generate_proof(complete_shard_set, 0)

        assert proof.leaf_index == 0
        assert proof.root_hash != ""
        assert verify_proof(proof)

    def test_generate_proof_invalid_index(self, verifier, complete_shard_set):
        """Generate proof for missing shard raises error."""
        complete_shard_set.shards[0] = None

        with pytest.raises(ValueError):
            verifier.generate_proof(complete_shard_set, 0)

    def test_challenge_response_verify(self, verifier, complete_shard_set):
        """Challenge-response verification."""
        shard = complete_shard_set.shards[0]
        expected = shard.metadata.checksum

        assert verifier.challenge_response_verify(shard, expected)
        assert not verifier.challenge_response_verify(shard, "wrong")


class TestIntegrityReport:
    """Tests for IntegrityReport model."""

    def test_report_to_dict(self):
        """Report serializes to dict."""
        from valence.storage.models import IntegrityReport

        report = IntegrityReport(
            is_valid=True,
            total_shards=5,
            valid_shards=5,
            corrupted_shards=[],
            missing_shards=[],
            can_recover=True,
            details="All good",
        )

        d = report.to_dict()
        assert d["is_valid"]
        assert d["total_shards"] == 5
        assert d["details"] == "All good"
