"""Tests for storage backend implementations.

Tests for:
- MemoryBackend
- LocalFileBackend
- BackendRegistry
"""

import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from valence.storage.backend import (
    BackendRegistry,
    LocalFileBackend,
    MemoryBackend,
    ShardNotFoundError,
    StorageQuotaExceededError,
    StorageStats,
)
from valence.storage.integrity import compute_hash
from valence.storage.models import (
    ShardMetadata,
    ShardSet,
    StorageShard,
)


class TestStorageStats:
    """Tests for StorageStats model."""

    def test_to_dict(self):
        """Stats serialize to dictionary."""
        stats = StorageStats(
            backend_id="test-backend",
            backend_type="memory",
            total_shards=10,
            total_bytes=1000,
            quota_bytes=5000,
            healthy=True,
        )

        d = stats.to_dict()
        assert d["backend_id"] == "test-backend"
        assert d["total_shards"] == 10
        assert d["total_bytes"] == 1000


class TestMemoryBackend:
    """Tests for in-memory storage backend."""

    @pytest.fixture
    def backend(self):
        """Create a memory backend."""
        return MemoryBackend("test-memory")

    @pytest.fixture
    def sample_shard(self):
        """Create a sample shard."""
        data = b"test shard data"
        return StorageShard(
            data=data,
            metadata=ShardMetadata(
                shard_id=uuid4(),
                index=0,
                size_bytes=len(data),
                checksum=compute_hash(data),
            ),
        )

    @pytest.mark.asyncio
    async def test_store_and_retrieve(self, backend, sample_shard):
        """Store and retrieve a shard."""
        location = await backend.store_shard(sample_shard)

        retrieved = await backend.retrieve_shard(location)

        assert retrieved.data == sample_shard.data
        assert retrieved.metadata.index == sample_shard.metadata.index

    @pytest.mark.asyncio
    async def test_retrieve_not_found(self, backend):
        """Retrieve non-existent shard raises error."""
        with pytest.raises(ShardNotFoundError):
            await backend.retrieve_shard("nonexistent")

    @pytest.mark.asyncio
    async def test_delete_shard(self, backend, sample_shard):
        """Delete a shard."""
        location = await backend.store_shard(sample_shard)

        assert await backend.shard_exists(location)
        deleted = await backend.delete_shard(location)

        assert deleted
        assert not await backend.shard_exists(location)

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, backend):
        """Delete non-existent shard returns False."""
        assert not await backend.delete_shard("nonexistent")

    @pytest.mark.asyncio
    async def test_list_shards(self, backend, sample_shard):
        """List stored shards."""
        # Store multiple
        locations = []
        for i in range(3):
            shard = StorageShard(
                data=f"shard{i}".encode(),
                metadata=ShardMetadata(shard_id=uuid4(), index=i),
            )
            locations.append(await backend.store_shard(shard))

        listed = await backend.list_shards()
        assert len(listed) == 3
        for loc in locations:
            assert loc in listed

    @pytest.mark.asyncio
    async def test_get_stats(self, backend, sample_shard):
        """Get backend statistics."""
        await backend.store_shard(sample_shard)

        stats = await backend.get_stats()

        assert stats.backend_id == "test-memory"
        assert stats.backend_type == "memory"
        assert stats.total_shards == 1
        assert stats.total_bytes == len(sample_shard.data)
        assert stats.healthy

    @pytest.mark.asyncio
    async def test_health_check(self, backend):
        """Health check returns True."""
        assert await backend.health_check()

    def test_clear(self, backend):
        """Clear all shards."""
        backend._storage["test"] = b"data"
        backend._metadata["test"] = {}

        backend.clear()

        assert len(backend._storage) == 0
        assert len(backend._metadata) == 0


class TestLocalFileBackend:
    """Tests for local file storage backend."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        d = tempfile.mkdtemp()
        yield d
        shutil.rmtree(d)

    @pytest.fixture
    def backend(self, temp_dir):
        """Create a local file backend."""
        return LocalFileBackend(temp_dir, "test-local")

    @pytest.fixture
    def sample_shard(self):
        """Create a sample shard."""
        data = b"test shard data for file backend"
        return StorageShard(
            data=data,
            metadata=ShardMetadata(
                shard_id=uuid4(),
                index=0,
                size_bytes=len(data),
                checksum=compute_hash(data),
            ),
        )

    @pytest.mark.asyncio
    async def test_creates_directories(self, temp_dir):
        """Backend creates necessary directories."""
        LocalFileBackend(temp_dir, "test")

        assert Path(temp_dir, "shards").exists()
        assert Path(temp_dir, "metadata").exists()

    @pytest.mark.asyncio
    async def test_store_and_retrieve(self, backend, sample_shard):
        """Store and retrieve a shard."""
        location = await backend.store_shard(sample_shard)

        retrieved = await backend.retrieve_shard(location)

        assert retrieved.data == sample_shard.data
        assert retrieved.metadata.checksum == sample_shard.metadata.checksum

    @pytest.mark.asyncio
    async def test_retrieve_not_found(self, backend):
        """Retrieve non-existent shard raises error."""
        with pytest.raises(ShardNotFoundError):
            await backend.retrieve_shard("00000000-0000-0000-0000-000000000000")

    @pytest.mark.asyncio
    async def test_delete_shard(self, backend, sample_shard):
        """Delete a shard from file system."""
        location = await backend.store_shard(sample_shard)

        assert await backend.shard_exists(location)
        deleted = await backend.delete_shard(location)

        assert deleted
        assert not await backend.shard_exists(location)

    @pytest.mark.asyncio
    async def test_list_shards(self, backend):
        """List stored shards."""
        locations = []
        for i in range(3):
            shard = StorageShard(
                data=f"file-shard{i}".encode(),
                metadata=ShardMetadata(shard_id=uuid4(), index=i),
            )
            locations.append(await backend.store_shard(shard))

        listed = await backend.list_shards()
        assert len(listed) == 3

    @pytest.mark.asyncio
    async def test_get_stats(self, backend, sample_shard):
        """Get backend statistics."""
        await backend.store_shard(sample_shard)

        stats = await backend.get_stats()

        assert stats.backend_id == "test-local"
        assert stats.backend_type == "local"
        assert stats.total_shards == 1
        assert stats.total_bytes > 0
        assert stats.healthy

    @pytest.mark.asyncio
    async def test_quota_enforcement(self, temp_dir):
        """Quota is enforced on storage."""
        backend = LocalFileBackend(temp_dir, "quota-test", quota_bytes=100)

        small_shard = StorageShard(
            data=b"small", metadata=ShardMetadata(shard_id=uuid4(), index=0)
        )
        await backend.store_shard(small_shard)

        # Try to store a large shard
        large_shard = StorageShard(
            data=b"x" * 200, metadata=ShardMetadata(shard_id=uuid4(), index=1)
        )
        with pytest.raises(StorageQuotaExceededError):
            await backend.store_shard(large_shard)

    @pytest.mark.asyncio
    async def test_clear(self, backend, sample_shard):
        """Clear all stored shards."""
        await backend.store_shard(sample_shard)
        assert (await backend.get_stats()).total_shards == 1

        await backend.clear()

        assert (await backend.get_stats()).total_shards == 0


class TestBackendRegistry:
    """Tests for backend registry."""

    @pytest.fixture
    def registry(self):
        """Create a registry."""
        return BackendRegistry()

    @pytest.fixture
    def memory_backends(self):
        """Create multiple memory backends."""
        return [
            MemoryBackend("mem-1"),
            MemoryBackend("mem-2"),
            MemoryBackend("mem-3"),
        ]

    def test_register_backend(self, registry, memory_backends):
        """Register backends."""
        for backend in memory_backends:
            registry.register(backend)

        assert len(registry.list_backends()) == 3
        assert "mem-1" in registry.list_backends()

    def test_unregister_backend(self, registry, memory_backends):
        """Unregister a backend."""
        registry.register(memory_backends[0])

        assert registry.unregister("mem-1")
        assert "mem-1" not in registry.list_backends()
        assert not registry.unregister("nonexistent")

    def test_get_backend(self, registry, memory_backends):
        """Get a backend by ID."""
        registry.register(memory_backends[0])

        backend = registry.get("mem-1")
        assert backend is memory_backends[0]
        assert registry.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_all_stats(self, registry, memory_backends):
        """Get stats from all backends."""
        for backend in memory_backends:
            registry.register(backend)

        stats = await registry.get_all_stats()

        assert len(stats) == 3
        assert "mem-1" in stats
        assert stats["mem-1"].backend_type == "memory"

    @pytest.mark.asyncio
    async def test_health_check_all(self, registry, memory_backends):
        """Check health of all backends."""
        for backend in memory_backends:
            registry.register(backend)

        health = await registry.health_check_all()

        assert len(health) == 3
        assert all(h for h in health.values())

    @pytest.mark.asyncio
    async def test_distribute_shard_set(self, registry, memory_backends):
        """Distribute shards across backends."""
        for backend in memory_backends:
            registry.register(backend)

        # Create a shard set
        shards = []
        for i in range(6):
            shard = StorageShard(
                data=f"dist-shard{i}".encode(),
                metadata=ShardMetadata(shard_id=uuid4(), index=i),
            )
            shards.append(shard)

        shard_set = ShardSet(
            shards=shards,
            data_shards_k=3,
            total_shards_n=6,
        )

        # Distribute
        locations = await registry.distribute_shard_set(shard_set)

        assert len(locations) == 6
        # Should round-robin across backends
        backend_ids = [loc[0] for loc in locations.values()]
        assert "mem-1" in backend_ids
        assert "mem-2" in backend_ids
        assert "mem-3" in backend_ids

    @pytest.mark.asyncio
    async def test_retrieve_distributed(self, registry, memory_backends):
        """Retrieve distributed shards."""
        for backend in memory_backends:
            registry.register(backend)

        # Create and distribute
        shards = []
        for i in range(3):
            shard = StorageShard(
                data=f"retrieve-shard{i}".encode(),
                metadata=ShardMetadata(shard_id=uuid4(), index=i),
            )
            shards.append(shard)

        shard_set = ShardSet(
            shards=shards,
            data_shards_k=2,
            total_shards_n=3,
            original_size=50,
        )

        locations = await registry.distribute_shard_set(shard_set)

        # Clear local references and retrieve
        template = ShardSet(
            set_id=shard_set.set_id,
            shards=[None] * 3,
            data_shards_k=2,
            total_shards_n=3,
            original_size=50,
        )

        retrieved = await registry.retrieve_distributed(locations, template)

        assert len(retrieved.available_shards) == 3
        assert retrieved.shards[0].data == b"retrieve-shard0"


class TestStorageBackendInterface:
    """Tests for storage backend base methods."""

    @pytest.fixture
    def backend(self):
        """Create a memory backend."""
        return MemoryBackend("interface-test")

    @pytest.fixture
    def sample_shard_set(self):
        """Create a sample shard set."""
        shards = []
        for i in range(3):
            shard = StorageShard(
                data=f"interface-shard{i}".encode(),
                metadata=ShardMetadata(shard_id=uuid4(), index=i),
            )
            shards.append(shard)

        return ShardSet(
            shards=shards,
            data_shards_k=2,
            total_shards_n=3,
            original_size=50,
        )

    @pytest.mark.asyncio
    async def test_store_shard_set(self, backend, sample_shard_set):
        """Store entire shard set."""
        locations = await backend.store_shard_set(sample_shard_set)

        assert len(locations) == 3
        assert 0 in locations
        assert 1 in locations
        assert 2 in locations

    @pytest.mark.asyncio
    async def test_store_shard_set_specific_indices(self, backend, sample_shard_set):
        """Store specific shard indices."""
        locations = await backend.store_shard_set(sample_shard_set, indices=[0, 2])

        assert len(locations) == 2
        assert 0 in locations
        assert 2 in locations
        assert 1 not in locations

    @pytest.mark.asyncio
    async def test_retrieve_shard_set(self, backend, sample_shard_set):
        """Retrieve shard set from stored locations."""
        locations = await backend.store_shard_set(sample_shard_set)

        template = ShardSet(
            set_id=sample_shard_set.set_id,
            shards=[None] * 3,
            data_shards_k=2,
            total_shards_n=3,
        )

        retrieved = await backend.retrieve_shard_set(locations, template)

        assert len(retrieved.available_shards) == 3
        assert retrieved.shards[0].data == sample_shard_set.shards[0].data
