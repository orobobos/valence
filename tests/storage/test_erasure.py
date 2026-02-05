"""Tests for Reed-Solomon erasure coding.

Comprehensive tests for the erasure coding implementation including:
- Basic encode/decode cycles
- Recovery from partial data loss
- Various redundancy levels
- Edge cases and error handling
"""

import hashlib
import os
from uuid import uuid4

import pytest

from valence.storage.erasure import (
    ErasureCodec,
    InsufficientShardsError,
    _gf_div,
    _gf_inverse,
    _gf_mul,
    _gf_pow,
    _init_galois_tables,
)
from valence.storage.models import (
    RedundancyLevel,
    ShardSet,
    StorageShard,
)


class TestGaloisField:
    """Tests for Galois Field arithmetic."""

    def setup_method(self):
        """Ensure GF tables are initialized."""
        _init_galois_tables()

    def test_gf_multiply_identity(self):
        """Multiplying by 1 returns the same value."""
        for x in [0, 1, 127, 255]:
            assert _gf_mul(x, 1) == x
            assert _gf_mul(1, x) == x

    def test_gf_multiply_zero(self):
        """Multiplying by 0 returns 0."""
        for x in [0, 1, 127, 255]:
            assert _gf_mul(x, 0) == 0
            assert _gf_mul(0, x) == 0

    def test_gf_multiply_commutative(self):
        """Multiplication is commutative."""
        pairs = [(3, 7), (15, 100), (200, 255)]
        for a, b in pairs:
            assert _gf_mul(a, b) == _gf_mul(b, a)

    def test_gf_divide_identity(self):
        """Dividing by 1 returns the same value."""
        for x in [1, 50, 127, 255]:
            assert _gf_div(x, 1) == x

    def test_gf_divide_self(self):
        """Dividing a number by itself returns 1."""
        for x in [1, 50, 127, 255]:
            assert _gf_div(x, x) == 1

    def test_gf_divide_zero(self):
        """Dividing zero returns zero."""
        assert _gf_div(0, 1) == 0
        assert _gf_div(0, 255) == 0

    def test_gf_divide_by_zero_raises(self):
        """Dividing by zero raises error."""
        with pytest.raises(ZeroDivisionError):
            _gf_div(1, 0)

    def test_gf_pow_zero(self):
        """Any number to power 0 is 1."""
        for x in [0, 1, 127, 255]:
            assert _gf_pow(x, 0) == 1

    def test_gf_pow_one(self):
        """Any number to power 1 is itself."""
        for x in [1, 50, 127, 255]:
            assert _gf_pow(x, 1) == x

    def test_gf_inverse_property(self):
        """x * x^-1 = 1 for all x != 0."""
        for x in [1, 50, 127, 255]:
            inv = _gf_inverse(x)
            assert _gf_mul(x, inv) == 1

    def test_gf_inverse_zero_raises(self):
        """Zero has no inverse."""
        with pytest.raises(ZeroDivisionError):
            _gf_inverse(0)


class TestRedundancyLevel:
    """Tests for RedundancyLevel enum."""

    def test_predefined_levels(self):
        """Test predefined redundancy levels."""
        assert RedundancyLevel.MINIMAL.data_shards == 2
        assert RedundancyLevel.MINIMAL.total_shards == 3

        assert RedundancyLevel.PERSONAL.data_shards == 3
        assert RedundancyLevel.PERSONAL.total_shards == 5

        assert RedundancyLevel.FEDERATION.data_shards == 5
        assert RedundancyLevel.FEDERATION.total_shards == 9

        assert RedundancyLevel.PARANOID.data_shards == 7
        assert RedundancyLevel.PARANOID.total_shards == 15

    def test_parity_shards(self):
        """Test parity shard calculation."""
        assert RedundancyLevel.MINIMAL.parity_shards == 1
        assert RedundancyLevel.PERSONAL.parity_shards == 2
        assert RedundancyLevel.FEDERATION.parity_shards == 4
        assert RedundancyLevel.PARANOID.parity_shards == 8

    def test_max_failures(self):
        """Test max failures equals parity shards."""
        for level in RedundancyLevel:
            assert level.max_failures == level.parity_shards

    def test_overhead_percent(self):
        """Test overhead calculation."""
        # MINIMAL: 1/2 = 50%
        assert RedundancyLevel.MINIMAL.overhead_percent == 50.0
        # PERSONAL: 2/3 ≈ 66.67%
        assert abs(RedundancyLevel.PERSONAL.overhead_percent - 66.67) < 0.1

    def test_from_string(self):
        """Test creating from string."""
        assert RedundancyLevel.from_string("minimal") == RedundancyLevel.MINIMAL
        assert RedundancyLevel.from_string("PERSONAL") == RedundancyLevel.PERSONAL
        assert RedundancyLevel.from_string("Federation") == RedundancyLevel.FEDERATION

    def test_from_string_invalid(self):
        """Test invalid string raises error."""
        with pytest.raises(ValueError) as exc_info:
            RedundancyLevel.from_string("invalid")
        assert "Unknown redundancy level" in str(exc_info.value)

    def test_custom_validation(self):
        """Test custom parameter validation."""
        # Valid custom
        k, n = RedundancyLevel.custom(4, 7)
        assert k == 4
        assert n == 7

        # Invalid: k < 1
        with pytest.raises(ValueError):
            RedundancyLevel.custom(0, 5)

        # Invalid: n <= k
        with pytest.raises(ValueError):
            RedundancyLevel.custom(5, 5)

        # Invalid: n > 255
        with pytest.raises(ValueError):
            RedundancyLevel.custom(10, 256)


class TestErasureCodecBasic:
    """Basic tests for ErasureCodec."""

    def test_create_with_level(self):
        """Test creating codec with RedundancyLevel."""
        codec = ErasureCodec(level=RedundancyLevel.PERSONAL)
        assert codec.data_shards == 3
        assert codec.total_shards == 5

    def test_create_with_custom_params(self):
        """Test creating codec with custom parameters."""
        codec = ErasureCodec(data_shards=4, total_shards=6)
        assert codec.data_shards == 4
        assert codec.total_shards == 6

    def test_invalid_params_raises(self):
        """Test invalid parameters raise errors."""
        # k < 1
        with pytest.raises(ValueError):
            ErasureCodec(data_shards=0, total_shards=5)

        # n <= k
        with pytest.raises(ValueError):
            ErasureCodec(data_shards=5, total_shards=5)

        # n > 255
        with pytest.raises(ValueError):
            ErasureCodec(data_shards=10, total_shards=256)

    def test_get_stats(self):
        """Test getting codec statistics."""
        codec = ErasureCodec(level=RedundancyLevel.PERSONAL)
        stats = codec.get_stats()

        assert stats["data_shards"] == 3
        assert stats["total_shards"] == 5
        assert stats["parity_shards"] == 2
        assert stats["max_failures"] == 2
        assert stats["level"] == "PERSONAL"


class TestErasureCodecEncodeDecode:
    """Tests for encode/decode operations."""

    @pytest.fixture
    def codec_minimal(self):
        """Minimal codec (2 of 3)."""
        return ErasureCodec(level=RedundancyLevel.MINIMAL)

    @pytest.fixture
    def codec_personal(self):
        """Personal codec (3 of 5)."""
        return ErasureCodec(level=RedundancyLevel.PERSONAL)

    @pytest.fixture
    def sample_data(self):
        """Sample data for encoding."""
        return b"Hello, Valence! This is test data for erasure coding."

    def test_encode_creates_correct_shard_count(self, codec_minimal, sample_data):
        """Encoding creates correct number of shards."""
        shard_set = codec_minimal.encode(sample_data)
        assert len(shard_set.shards) == 3
        assert shard_set.data_shards_k == 2
        assert shard_set.total_shards_n == 3

    def test_encode_stores_original_metadata(self, codec_minimal, sample_data):
        """Encoding stores original data metadata."""
        shard_set = codec_minimal.encode(sample_data)

        assert shard_set.original_size == len(sample_data)
        assert shard_set.original_checksum == hashlib.sha256(sample_data).hexdigest()

    def test_encode_marks_parity_shards(self, codec_minimal, sample_data):
        """Parity shards are marked correctly."""
        shard_set = codec_minimal.encode(sample_data)

        # First k shards are data
        assert not shard_set.shards[0].metadata.is_parity
        assert not shard_set.shards[1].metadata.is_parity
        # Remaining are parity
        assert shard_set.shards[2].metadata.is_parity

    def test_encode_decode_roundtrip(self, codec_personal, sample_data):
        """Data survives encode/decode roundtrip."""
        shard_set = codec_personal.encode(sample_data)
        result = codec_personal.decode(shard_set)

        assert result.success
        assert result.data == sample_data

    def test_encode_decode_with_belief_id(self, codec_minimal, sample_data):
        """Belief ID is preserved through encode/decode."""
        belief_id = str(uuid4())
        shard_set = codec_minimal.encode(sample_data, belief_id=belief_id)

        assert str(shard_set.belief_id) == belief_id

    def test_decode_with_all_data_shards(self, codec_personal, sample_data):
        """Decode works with all data shards present."""
        shard_set = codec_personal.encode(sample_data)

        # Keep only data shards (indices 0, 1, 2)
        shard_set.shards = shard_set.shards[:3]

        result = codec_personal.decode(shard_set)
        assert result.success
        assert result.data == sample_data

    def test_decode_with_one_data_shard_missing(self, codec_personal, sample_data):
        """Decode works with one data shard missing."""
        shard_set = codec_personal.encode(sample_data)

        # Remove first data shard
        shard_set.shards[0] = None

        result = codec_personal.decode(shard_set)
        assert result.success
        assert result.data == sample_data

    def test_decode_with_multiple_data_shards_missing(self, codec_personal, sample_data):
        """Decode works with multiple data shards missing."""
        shard_set = codec_personal.encode(sample_data)

        # Remove two data shards (we have 2 parity, so this should work)
        shard_set.shards[0] = None
        shard_set.shards[1] = None

        result = codec_personal.decode(shard_set)
        assert result.success
        assert result.data == sample_data

    def test_decode_fails_with_too_many_missing(self, codec_personal, sample_data):
        """Decode fails when too many shards are missing."""
        shard_set = codec_personal.encode(sample_data)

        # Remove 3 shards (need 3, have only 2 left)
        shard_set.shards[0] = None
        shard_set.shards[1] = None
        shard_set.shards[2] = None

        result = codec_personal.decode(shard_set)
        assert not result.success
        assert "Need 3 shards" in result.error_message


class TestErasureCodecRecovery:
    """Tests for recovery scenarios."""

    def test_recover_any_k_of_n_minimal(self):
        """Can recover from any k shards (minimal: 2 of 3)."""
        codec = ErasureCodec(level=RedundancyLevel.MINIMAL)
        data = b"Recovery test data for minimal redundancy"
        shard_set = codec.encode(data)

        # Try all combinations of k shards
        import itertools

        for indices in itertools.combinations(range(3), 2):
            test_set = ShardSet(
                shards=[shard_set.shards[i] if i in indices else None for i in range(3)],
                data_shards_k=2,
                total_shards_n=3,
                original_size=shard_set.original_size,
                original_checksum=shard_set.original_checksum,
            )
            result = codec.decode(test_set)
            assert result.success, f"Failed with shards {indices}"
            assert result.data == data

    def test_recover_any_k_of_n_personal(self):
        """Can recover from any k shards (personal: 3 of 5)."""
        codec = ErasureCodec(level=RedundancyLevel.PERSONAL)
        data = b"Recovery test data for personal redundancy"
        shard_set = codec.encode(data)

        import itertools

        for indices in itertools.combinations(range(5), 3):
            test_set = ShardSet(
                shards=[shard_set.shards[i] if i in indices else None for i in range(5)],
                data_shards_k=3,
                total_shards_n=5,
                original_size=shard_set.original_size,
                original_checksum=shard_set.original_checksum,
            )
            result = codec.decode(test_set)
            assert result.success, f"Failed with shards {indices}"
            assert result.data == data

    def test_corrupted_shard_detection(self):
        """Corrupted shards are detected and excluded."""
        codec = ErasureCodec(level=RedundancyLevel.PERSONAL)
        data = b"Corruption test data"
        shard_set = codec.encode(data)

        # Corrupt one data shard
        corrupt_data = b"CORRUPTED" + shard_set.shards[0].data[9:]
        shard_set.shards[0] = StorageShard(
            data=corrupt_data,
            metadata=shard_set.shards[0].metadata,  # Checksum won't match
        )

        # Should still recover using remaining valid shards
        result = codec.decode(shard_set)
        assert result.success
        assert result.data == data

    def test_large_data_recovery(self):
        """Recovery works with larger data."""
        codec = ErasureCodec(level=RedundancyLevel.PERSONAL)
        # 1MB of random data
        data = os.urandom(1024 * 1024)

        shard_set = codec.encode(data)

        # Remove 2 shards
        shard_set.shards[0] = None
        shard_set.shards[3] = None

        result = codec.decode(shard_set)
        assert result.success
        assert result.data == data


class TestErasureCodecRepair:
    """Tests for shard repair functionality."""

    def test_repair_restores_all_shards(self):
        """Repair regenerates all missing shards."""
        codec = ErasureCodec(level=RedundancyLevel.PERSONAL)
        data = b"Repair test data"
        shard_set = codec.encode(data)

        # Remove some shards
        shard_set.shards[0] = None
        shard_set.shards[2] = None

        # Repair
        repaired = codec.repair(shard_set)

        # Should have all shards
        assert len(repaired.available_shards) == 5
        assert all(s is not None for s in repaired.shards)

    def test_repair_preserves_metadata(self):
        """Repair preserves shard set metadata."""
        codec = ErasureCodec(level=RedundancyLevel.PERSONAL)
        data = b"Metadata preservation test"
        shard_set = codec.encode(data)
        original_id = shard_set.set_id
        original_created = shard_set.created_at

        shard_set.shards[0] = None
        repaired = codec.repair(shard_set)

        assert repaired.set_id == original_id
        assert repaired.created_at == original_created

    def test_repair_fails_with_insufficient_shards(self):
        """Repair fails when not enough shards available."""
        codec = ErasureCodec(level=RedundancyLevel.PERSONAL)
        data = b"Insufficient shards test"
        shard_set = codec.encode(data)

        # Remove too many shards
        shard_set.shards[0] = None
        shard_set.shards[1] = None
        shard_set.shards[2] = None

        with pytest.raises(InsufficientShardsError):
            codec.repair(shard_set)


class TestErasureCodecIntegrity:
    """Tests for integrity verification."""

    def test_verify_integrity_valid(self):
        """Verify integrity returns True for valid shards."""
        codec = ErasureCodec(level=RedundancyLevel.PERSONAL)
        data = b"Integrity test data"
        shard_set = codec.encode(data)

        assert codec.verify_integrity(shard_set)

    def test_verify_integrity_with_missing(self):
        """Verify integrity with some missing shards."""
        codec = ErasureCodec(level=RedundancyLevel.PERSONAL)
        data = b"Missing shards test"
        shard_set = codec.encode(data)

        # Remove up to parity_shards
        shard_set.shards[0] = None
        shard_set.shards[1] = None

        # Still valid - can recover
        assert codec.verify_integrity(shard_set)

    def test_verify_integrity_fails_insufficient(self):
        """Verify integrity fails with insufficient shards."""
        codec = ErasureCodec(level=RedundancyLevel.PERSONAL)
        data = b"Insufficient test"
        shard_set = codec.encode(data)

        # Remove too many
        shard_set.shards[0] = None
        shard_set.shards[1] = None
        shard_set.shards[2] = None

        assert not codec.verify_integrity(shard_set)


class TestErasureCodecEdgeCases:
    """Edge case tests."""

    def test_empty_data(self):
        """Handle empty data gracefully."""
        codec = ErasureCodec(level=RedundancyLevel.MINIMAL)
        data = b""

        shard_set = codec.encode(data)
        result = codec.decode(shard_set)

        assert result.success
        assert result.data == data

    def test_single_byte_data(self):
        """Handle single byte data."""
        codec = ErasureCodec(level=RedundancyLevel.MINIMAL)
        data = b"X"

        shard_set = codec.encode(data)
        result = codec.decode(shard_set)

        assert result.success
        assert result.data == data

    def test_data_size_not_multiple_of_k(self):
        """Handle data size not evenly divisible by k."""
        codec = ErasureCodec(level=RedundancyLevel.PERSONAL)  # k=3
        data = b"12345678901"  # 11 bytes, not divisible by 3

        shard_set = codec.encode(data)
        result = codec.decode(shard_set)

        assert result.success
        assert result.data == data

    def test_binary_data_with_nulls(self):
        """Handle binary data with null bytes."""
        codec = ErasureCodec(level=RedundancyLevel.MINIMAL)
        data = b"\x00\x01\x00\x02\x00\x03"

        shard_set = codec.encode(data)
        result = codec.decode(shard_set)

        assert result.success
        assert result.data == data

    def test_high_entropy_random_data(self):
        """Handle high-entropy random data."""
        codec = ErasureCodec(level=RedundancyLevel.PERSONAL)
        data = os.urandom(1000)

        shard_set = codec.encode(data)

        # Remove some shards
        shard_set.shards[1] = None

        result = codec.decode(shard_set)

        assert result.success
        assert result.data == data
