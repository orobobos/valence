"""Integration tests for resilient storage.

End-to-end tests combining erasure coding, integrity verification,
and storage backends.
"""

import pytest
import tempfile
import shutil
import os
from uuid import uuid4

from valence.storage import (
    ErasureCodec,
    RedundancyLevel,
    MerkleTree,
    IntegrityVerifier,
    MemoryBackend,
    LocalFileBackend,
    BackendRegistry,
)
from valence.storage.models import ShardSet


class TestEndToEndErasureCoding:
    """End-to-end tests for erasure coding workflow."""
    
    @pytest.fixture
    def codec(self):
        """Personal level codec (3 of 5)."""
        return ErasureCodec(level=RedundancyLevel.PERSONAL)
    
    @pytest.fixture
    def verifier(self):
        """Integrity verifier."""
        return IntegrityVerifier()
    
    @pytest.fixture
    def registry(self):
        """Backend registry with 3 memory backends."""
        reg = BackendRegistry()
        for i in range(3):
            reg.register(MemoryBackend(f"mem-{i}"))
        return reg
    
    @pytest.mark.asyncio
    async def test_encode_store_retrieve_decode(self, codec, registry):
        """Complete workflow: encode -> store -> retrieve -> decode."""
        # Original belief data
        original_data = b"This is a belief that must survive failures"
        belief_id = str(uuid4())
        
        # 1. Encode
        shard_set = codec.encode(original_data, belief_id=belief_id)
        assert len(shard_set.shards) == 5
        
        # 2. Distribute across backends
        locations = await registry.distribute_shard_set(shard_set)
        assert len(locations) == 5
        
        # 3. Create template for retrieval
        template = ShardSet(
            set_id=shard_set.set_id,
            shards=[None] * 5,
            data_shards_k=3,
            total_shards_n=5,
            original_size=shard_set.original_size,
            original_checksum=shard_set.original_checksum,
        )
        
        # 4. Retrieve
        retrieved = await registry.retrieve_distributed(locations, template)
        assert len(retrieved.available_shards) == 5
        
        # 5. Decode
        result = codec.decode(retrieved)
        assert result.success
        assert result.data == original_data
    
    @pytest.mark.asyncio
    async def test_survive_backend_failure(self, codec, registry):
        """Survive loss of some backends (simulated)."""
        original_data = b"Data that must survive backend failure"
        
        # Encode and distribute
        shard_set = codec.encode(original_data)
        locations = await registry.distribute_shard_set(shard_set)
        
        # Simulate backend failure by clearing one backend
        failed_backend = registry.get("mem-0")
        failed_backend.clear()
        
        # Create template
        template = ShardSet(
            set_id=shard_set.set_id,
            shards=[None] * 5,
            data_shards_k=3,
            total_shards_n=5,
            original_size=shard_set.original_size,
            original_checksum=shard_set.original_checksum,
        )
        
        # Retrieve (some shards will be missing)
        retrieved = await registry.retrieve_distributed(locations, template)
        
        # Should still have at least k=3 shards from other backends
        available = len(retrieved.available_shards)
        assert available >= 3, f"Only {available} shards available"
        
        # Should still be able to decode
        result = codec.decode(retrieved)
        assert result.success
        assert result.data == original_data
    
    @pytest.mark.asyncio
    async def test_integrity_verification_flow(self, codec, verifier, registry):
        """Test integrity verification in workflow."""
        original_data = b"Data requiring integrity verification"
        
        # Encode
        shard_set = codec.encode(original_data)
        
        # Generate and store Merkle root
        merkle_root = verifier.generate_merkle_root(shard_set)
        shard_set.merkle_root = merkle_root
        
        # Verify initial integrity
        report = verifier.verify_shard_set(shard_set)
        assert report.is_valid
        assert report.can_recover
        
        # Distribute
        await registry.distribute_shard_set(shard_set)
        
        # Verify again after distribution
        report = verifier.verify_shard_set(shard_set)
        assert report.is_valid


class TestDisasterRecoveryScenarios:
    """Tests simulating disaster recovery scenarios from spec."""
    
    @pytest.fixture
    def codec_paranoid(self):
        """Paranoid level codec (7 of 15)."""
        return ErasureCodec(level=RedundancyLevel.PARANOID)
    
    def test_survive_max_failures(self, codec_paranoid):
        """Survive maximum allowed failures."""
        data = b"Critical belief data"
        shard_set = codec_paranoid.encode(data)
        
        # Remove up to max_failures (8) shards
        for i in range(8):
            shard_set.shards[i] = None
        
        # Should still have 7 shards = k
        assert len(shard_set.available_shards) == 7
        
        # Should recover
        result = codec_paranoid.decode(shard_set)
        assert result.success
        assert result.data == data
    
    def test_fail_beyond_max_failures(self, codec_paranoid):
        """Fail when exceeding max failures."""
        data = b"Critical belief data"
        shard_set = codec_paranoid.encode(data)
        
        # Remove more than max_failures (9) shards
        for i in range(9):
            shard_set.shards[i] = None
        
        # Only 6 shards left, need 7
        assert len(shard_set.available_shards) == 6
        
        # Should fail to recover
        result = codec_paranoid.decode(shard_set)
        assert not result.success
    
    def test_repair_after_partial_failure(self):
        """Repair shard set after partial failure."""
        codec = ErasureCodec(level=RedundancyLevel.PERSONAL)
        data = b"Data needing repair"
        
        shard_set = codec.encode(data)
        
        # Simulate partial failure
        shard_set.shards[0] = None
        shard_set.shards[2] = None
        
        # Repair
        repaired = codec.repair(shard_set)
        
        # Should have all shards back
        assert len(repaired.available_shards) == 5
        assert all(s is not None for s in repaired.shards)
        
        # Decode should work
        result = codec.decode(repaired)
        assert result.success
        assert result.data == data


class TestMerkleTreeIntegration:
    """Integration tests for Merkle trees with erasure coding."""
    
    def test_merkle_proof_for_shards(self):
        """Generate and verify proofs for each shard."""
        from valence.storage.integrity import verify_proof
        
        codec = ErasureCodec(level=RedundancyLevel.MINIMAL)
        data = b"Data for Merkle proof testing"
        
        shard_set = codec.encode(data)
        
        # Build Merkle tree
        tree = MerkleTree.from_shards(shard_set.shards)
        
        # Generate and verify proof for each shard
        for i, shard in enumerate(shard_set.shards):
            proof = tree.get_proof(i)
            assert verify_proof(proof), f"Proof failed for shard {i}"
            
            # Verify leaf matches shard
            assert tree.verify_leaf(i, shard.data)
    
    def test_detect_shard_tampering_via_merkle(self):
        """Detect tampered shard via Merkle proof."""
        from valence.storage.integrity import verify_proof
        
        codec = ErasureCodec(level=RedundancyLevel.MINIMAL)
        data = b"Tamper detection test"
        
        shard_set = codec.encode(data)
        tree = MerkleTree.from_shards(shard_set.shards)
        
        # Get proof for shard 0
        original_proof = tree.get_proof(0)
        assert verify_proof(original_proof)
        
        # "Tamper" with shard (change its hash in the proof)
        tampered_proof = tree.get_proof(0)
        tampered_proof.leaf_hash = "deadbeef" * 8  # Wrong hash
        
        # Verification should fail
        assert not verify_proof(tampered_proof)


class TestLocalFileBackendIntegration:
    """Integration tests with local file storage."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory."""
        d = tempfile.mkdtemp()
        yield d
        shutil.rmtree(d)
    
    @pytest.mark.asyncio
    async def test_file_persistence(self, temp_dir):
        """Shards persist to disk and can be retrieved."""
        codec = ErasureCodec(level=RedundancyLevel.MINIMAL)
        backend = LocalFileBackend(temp_dir, "persist-test")
        
        data = b"Persistent belief data"
        shard_set = codec.encode(data)
        
        # Store
        locations = await backend.store_shard_set(shard_set)
        
        # Create new backend instance pointing to same directory
        backend2 = LocalFileBackend(temp_dir, "persist-test")
        
        # Retrieve
        template = ShardSet(
            shards=[None] * 3,
            data_shards_k=2,
            total_shards_n=3,
            original_size=shard_set.original_size,
            original_checksum=shard_set.original_checksum,
        )
        
        retrieved = await backend2.retrieve_shard_set(locations, template)
        
        # Decode
        result = codec.decode(retrieved)
        assert result.success
        assert result.data == data
    
    @pytest.mark.asyncio
    async def test_large_file_handling(self, temp_dir):
        """Handle large files efficiently."""
        codec = ErasureCodec(level=RedundancyLevel.PERSONAL)
        backend = LocalFileBackend(temp_dir, "large-test")
        
        # 10MB of data
        data = os.urandom(10 * 1024 * 1024)
        
        shard_set = codec.encode(data)
        
        # Store
        await backend.store_shard_set(shard_set)
        
        stats = await backend.get_stats()
        assert stats.total_shards == 5
        # With overhead, total bytes should be > original
        assert stats.total_bytes > len(data)


class TestRedundancyLevelSelection:
    """Tests for choosing appropriate redundancy levels."""
    
    def test_minimal_for_testing(self):
        """Minimal level suitable for testing."""
        codec = ErasureCodec(level=RedundancyLevel.MINIMAL)
        data = b"Test data"
        
        shard_set = codec.encode(data)
        assert len(shard_set.shards) == 3
        assert shard_set.can_recover  # Need 2, have 3
    
    def test_personal_for_individual_use(self):
        """Personal level for individual backups."""
        codec = ErasureCodec(level=RedundancyLevel.PERSONAL)
        stats = codec.get_stats()
        
        assert stats["max_failures"] == 2
        assert stats["overhead_percent"] < 70
    
    def test_federation_for_distributed(self):
        """Federation level for distributed storage."""
        codec = ErasureCodec(level=RedundancyLevel.FEDERATION)
        stats = codec.get_stats()
        
        assert stats["max_failures"] == 4
        assert stats["data_shards"] == 5
        assert stats["total_shards"] == 9
    
    def test_paranoid_for_critical_data(self):
        """Paranoid level for critical data."""
        codec = ErasureCodec(level=RedundancyLevel.PARANOID)
        stats = codec.get_stats()
        
        assert stats["max_failures"] == 8
        assert stats["data_shards"] == 7
        assert stats["total_shards"] == 15


class TestRecoveryTimingAndMetrics:
    """Tests for recovery timing and metrics."""
    
    def test_recovery_metrics_recorded(self):
        """Recovery operation records timing metrics."""
        codec = ErasureCodec(level=RedundancyLevel.PERSONAL)
        data = b"Metrics test data" * 1000  # Some reasonable size
        
        shard_set = codec.encode(data)
        
        # Remove some shards to force recovery computation
        shard_set.shards[0] = None
        shard_set.shards[1] = None
        
        result = codec.decode(shard_set)
        
        assert result.success
        assert result.recovery_time_ms > 0
        assert result.shards_used == 3
        assert result.shards_available == 3
        assert result.shards_required == 3
