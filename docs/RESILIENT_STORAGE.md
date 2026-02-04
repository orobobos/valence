# Resilient Storage Module

The resilient storage module implements erasure coding for belief storage redundancy,
allowing data to survive partial hardware failures and enabling distributed storage
across multiple backends.

## Overview

Per the spec (`spec/components/resilient-storage/SPEC.md`), this module provides:

- **Reed-Solomon erasure coding** for distributed redundancy
- **Configurable redundancy levels** (minimal, personal, federation, paranoid)
- **Recovery from partial data loss** (any k of n shards)
- **Merkle tree integrity verification**
- **Pluggable storage backends** (memory, local files, extensible)

## Quick Start

```python
from valence.storage import (
    ErasureCodec,
    RedundancyLevel,
    IntegrityVerifier,
    MemoryBackend,
)

# Create a codec with personal-level redundancy (3 of 5)
codec = ErasureCodec(level=RedundancyLevel.PERSONAL)

# Encode belief data
data = b"This is my belief content"
shard_set = codec.encode(data, belief_id="belief-123")

# Verify integrity
verifier = IntegrityVerifier()
report = verifier.verify_shard_set(shard_set)
print(f"Valid: {report.is_valid}, Can recover: {report.can_recover}")

# Simulate partial failure (lose 2 shards)
shard_set.shards[0] = None
shard_set.shards[2] = None

# Recover original data
result = codec.decode(shard_set)
assert result.success
assert result.data == data  # ✓ Full recovery
```

## Redundancy Levels

| Level | Data (k) | Total (n) | Overhead | Survives |
|-------|----------|-----------|----------|----------|
| MINIMAL | 2 | 3 | 50% | 1 failure |
| PERSONAL | 3 | 5 | 67% | 2 failures |
| FEDERATION | 5 | 9 | 80% | 4 failures |
| PARANOID | 7 | 15 | 114% | 8 failures |

Choose based on your reliability needs:
- **MINIMAL**: Testing and development
- **PERSONAL**: Individual backups
- **FEDERATION**: Distributed storage across peers
- **PARANOID**: Critical data that must never be lost

## Erasure Coding

The module implements Reed-Solomon erasure coding using Galois Field GF(2^8)
arithmetic. Key properties:

- **Systematic encoding**: First k shards contain original data
- **MDS (Maximum Distance Separable)**: Any k shards can recover data
- **Pure Python**: No external dependencies

### How It Works

1. Data is split into k equal-sized chunks
2. n total shards are generated (k data + (n-k) parity)
3. Parity shards are computed via matrix multiplication in GF(2^8)
4. Any k shards can recover original data via matrix inversion

```python
# Custom redundancy parameters
codec = ErasureCodec(data_shards=4, total_shards=7)
print(codec.get_stats())
# {'data_shards': 4, 'total_shards': 7, 'parity_shards': 3,
#  'max_failures': 3, 'overhead_percent': 75.0, 'level': 'custom'}
```

## Integrity Verification

### Merkle Trees

```python
from valence.storage import MerkleTree, verify_proof

# Build tree from shard data
tree = MerkleTree.from_shards(shard_set.shards)
root_hash = tree.root_hash

# Generate proof for a specific shard
proof = tree.get_proof(shard_index=2)

# Verify proof (works without the full tree)
assert verify_proof(proof)
```

### Challenge-Response

```python
verifier = IntegrityVerifier()

# Remote verification
shard = backend.retrieve_shard(location)
expected_checksum = "abc123..."  # From metadata
valid = verifier.challenge_response_verify(shard, expected_checksum)
```

## Storage Backends

### Memory Backend (Testing)

```python
from valence.storage import MemoryBackend

backend = MemoryBackend("test")
location = await backend.store_shard(shard)
retrieved = await backend.retrieve_shard(location)
```

### Local File Backend

```python
from valence.storage import LocalFileBackend

backend = LocalFileBackend(
    base_path="/path/to/storage",
    backend_id="local-primary",
    quota_bytes=10 * 1024 * 1024 * 1024,  # 10GB quota
)

# Store entire shard set
locations = await backend.store_shard_set(shard_set)

# Get stats
stats = await backend.get_stats()
print(f"Using {stats.total_bytes} bytes across {stats.total_shards} shards")
```

### Backend Registry (Multi-Backend)

```python
from valence.storage import BackendRegistry, MemoryBackend, LocalFileBackend

registry = BackendRegistry()
registry.register(LocalFileBackend("/primary", "local-1"))
registry.register(LocalFileBackend("/backup", "local-2"))
registry.register(MemoryBackend("mem-cache"))

# Distribute shards across backends (round-robin)
locations = await registry.distribute_shard_set(shard_set)

# Retrieve distributed shards
retrieved = await registry.retrieve_distributed(locations, template)

# Health check all backends
health = await registry.health_check_all()
```

## Recovery Workflows

### Basic Recovery

```python
# Encode
shard_set = codec.encode(data)

# Store distributed
locations = await registry.distribute_shard_set(shard_set)

# Later: retrieve and decode
retrieved = await registry.retrieve_distributed(locations, template)
result = codec.decode(retrieved)

if result.success:
    original_data = result.data
else:
    print(f"Recovery failed: {result.error_message}")
```

### Repair Damaged Shard Set

```python
# Some shards are missing or corrupted
report = verifier.verify_shard_set(shard_set)
if not report.is_valid and report.can_recover:
    # Repair by re-encoding from recovered data
    repaired = codec.repair(shard_set)
    # repaired now has all n shards regenerated
```

## API Reference

### ErasureCodec

```python
class ErasureCodec:
    def __init__(
        self,
        level: RedundancyLevel | None = None,
        data_shards: int = 3,
        total_shards: int = 5,
    ): ...
    
    def encode(self, data: bytes, belief_id: str | None = None) -> ShardSet: ...
    def decode(self, shard_set: ShardSet) -> RecoveryResult: ...
    def verify_integrity(self, shard_set: ShardSet) -> bool: ...
    def repair(self, shard_set: ShardSet) -> ShardSet: ...
    def get_stats(self) -> dict: ...
```

### IntegrityVerifier

```python
class IntegrityVerifier:
    def verify_shard_set(self, shard_set: ShardSet) -> IntegrityReport: ...
    def verify_shard(self, shard: StorageShard) -> bool: ...
    def generate_merkle_root(self, shard_set: ShardSet) -> str: ...
    def generate_proof(self, shard_set: ShardSet, shard_index: int) -> MerkleProof: ...
```

### StorageBackend (ABC)

```python
class StorageBackend(ABC):
    async def store_shard(self, shard: StorageShard) -> str: ...
    async def retrieve_shard(self, location: str) -> StorageShard: ...
    async def delete_shard(self, location: str) -> bool: ...
    async def shard_exists(self, location: str) -> bool: ...
    async def list_shards(self, prefix: str = "") -> list[str]: ...
    async def get_stats(self) -> StorageStats: ...
```

## Future Extensions

Per the spec, planned features include:

- **Post-quantum encryption** (hybrid Kyber + X25519)
- **S3-compatible backends** (Backblaze B2, MinIO, AWS)
- **Decentralized backends** (IPFS, Filecoin, Sia)
- **Graph-aware backup** (preserve belief relationships)
- **Checkpoint/restore** functionality
