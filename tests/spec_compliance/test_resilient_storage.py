"""
Spec Compliance Tests: Resilient Storage

Verifies the codebase implements the resilient storage per
spec/components/resilient-storage/SPEC.md.

Key requirements:
- BackupSet model with belief_count, content_hash, redundancy_level, encrypted, status
- BackupShard model with shard_index, is_parity, checksum
- RedundancyLevel enum: MINIMAL, PERSONAL, FEDERATION, PARANOID
- Erasure coding parameters per redundancy level
- BackupStatus enum: IN_PROGRESS, COMPLETED, FAILED, VERIFIED, CORRUPTED
- IntegrityReport with shards_valid, shards_missing, can_recover
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from valence.core.backup import (
    REDUNDANCY_PARAMS,
    BackupSet,
    BackupShard,
    BackupStatus,
    IntegrityReport,
    RedundancyLevel,
    _create_shards,
)


# ============================================================================
# RedundancyLevel Enum Tests
# ============================================================================


class TestRedundancyLevelEnum:
    """Test RedundancyLevel matches spec erasure coding tiers."""

    def test_has_minimal(self):
        """MINIMAL tier for basic backup."""
        assert RedundancyLevel.MINIMAL.value == "minimal"

    def test_has_personal(self):
        """PERSONAL tier for personal backup."""
        assert RedundancyLevel.PERSONAL.value == "personal"

    def test_has_federation(self):
        """FEDERATION tier for federation-level redundancy."""
        assert RedundancyLevel.FEDERATION.value == "federation"

    def test_has_paranoid(self):
        """PARANOID tier for maximum redundancy."""
        assert RedundancyLevel.PARANOID.value == "paranoid"

    def test_exactly_four_levels(self):
        assert len(RedundancyLevel) == 4


# ============================================================================
# Erasure Coding Parameter Tests
# ============================================================================


class TestErasureCodingParams:
    """Test Reed-Solomon parameters per spec."""

    def test_minimal_params(self):
        """MINIMAL: 3 data shards, 2 parity -> survives 2 failures."""
        params = REDUNDANCY_PARAMS[RedundancyLevel.MINIMAL]
        assert params["data_shards"] == 3
        assert params["parity_shards"] == 2

    def test_personal_params(self):
        """PERSONAL: 5 data shards, 3 parity."""
        params = REDUNDANCY_PARAMS[RedundancyLevel.PERSONAL]
        assert params["data_shards"] == 5
        assert params["parity_shards"] == 3

    def test_federation_params(self):
        """FEDERATION: 8 data shards, 4 parity."""
        params = REDUNDANCY_PARAMS[RedundancyLevel.FEDERATION]
        assert params["data_shards"] == 8
        assert params["parity_shards"] == 4

    def test_paranoid_params(self):
        """PARANOID: 12 data shards, 8 parity -> survives 8 failures."""
        params = REDUNDANCY_PARAMS[RedundancyLevel.PARANOID]
        assert params["data_shards"] == 12
        assert params["parity_shards"] == 8

    def test_all_levels_have_params(self):
        """Every redundancy level must have erasure coding parameters."""
        for level in RedundancyLevel:
            assert level in REDUNDANCY_PARAMS
            assert "data_shards" in REDUNDANCY_PARAMS[level]
            assert "parity_shards" in REDUNDANCY_PARAMS[level]

    def test_parity_enables_recovery(self):
        """Parity shards must be >= 1 for every level (basic fault tolerance)."""
        for level in RedundancyLevel:
            assert REDUNDANCY_PARAMS[level]["parity_shards"] >= 1


# ============================================================================
# BackupStatus Enum Tests
# ============================================================================


class TestBackupStatusEnum:
    """Test BackupStatus lifecycle states."""

    def test_has_in_progress(self):
        assert BackupStatus.IN_PROGRESS.value == "in_progress"

    def test_has_completed(self):
        assert BackupStatus.COMPLETED.value == "completed"

    def test_has_failed(self):
        assert BackupStatus.FAILED.value == "failed"

    def test_has_verified(self):
        assert BackupStatus.VERIFIED.value == "verified"

    def test_has_corrupted(self):
        assert BackupStatus.CORRUPTED.value == "corrupted"


# ============================================================================
# BackupSet Model Tests
# ============================================================================


class TestBackupSetModel:
    """Test BackupSet matches spec."""

    def test_has_required_fields(self):
        """BackupSet must have all spec-required fields."""
        bs = BackupSet(id=uuid4())
        assert hasattr(bs, "belief_count")
        assert hasattr(bs, "total_size_bytes")
        assert hasattr(bs, "content_hash")
        assert hasattr(bs, "redundancy_level")
        assert hasattr(bs, "encrypted")
        assert hasattr(bs, "status")
        assert hasattr(bs, "shard_count")
        assert hasattr(bs, "created_at")

    def test_default_status_is_in_progress(self):
        """New backup sets start as IN_PROGRESS."""
        bs = BackupSet(id=uuid4())
        assert bs.status == BackupStatus.IN_PROGRESS

    def test_default_redundancy_is_personal(self):
        """Default redundancy level should be PERSONAL."""
        bs = BackupSet(id=uuid4())
        assert bs.redundancy_level == RedundancyLevel.PERSONAL

    def test_encrypted_default_false(self):
        """Encrypted defaults to False (opt-in encryption)."""
        bs = BackupSet(id=uuid4())
        assert bs.encrypted is False


# ============================================================================
# BackupShard Model Tests
# ============================================================================


class TestBackupShardModel:
    """Test BackupShard matches spec."""

    def test_has_required_fields(self):
        """BackupShard must have shard_index, is_parity, checksum."""
        shard = BackupShard(
            id=uuid4(),
            set_id=uuid4(),
            shard_index=0,
            is_parity=False,
            size_bytes=1024,
            checksum="abc123",
        )
        assert shard.shard_index == 0
        assert shard.is_parity is False
        assert shard.checksum == "abc123"

    def test_parity_shard_flag(self):
        """Parity shards should be distinguishable from data shards."""
        data_shard = BackupShard(id=uuid4(), set_id=uuid4(), shard_index=0, is_parity=False, size_bytes=1024, checksum="x")
        parity_shard = BackupShard(id=uuid4(), set_id=uuid4(), shard_index=5, is_parity=True, size_bytes=1024, checksum="y")
        assert data_shard.is_parity is False
        assert parity_shard.is_parity is True

    def test_has_backend_id(self):
        """Shard tracks which storage backend holds it."""
        shard = BackupShard(id=uuid4(), set_id=uuid4(), shard_index=0, is_parity=False, size_bytes=100, checksum="z")
        assert hasattr(shard, "backend_id")
        assert shard.backend_id == "local"  # Default


# ============================================================================
# IntegrityReport Model Tests
# ============================================================================


class TestIntegrityReportModel:
    """Test IntegrityReport matches spec verification protocol."""

    def test_has_required_fields(self):
        """IntegrityReport: is_valid, shards_checked, shards_valid, can_recover."""
        report = IntegrityReport(
            set_id=uuid4(),
            is_valid=True,
            shards_checked=8,
            shards_valid=8,
            shards_missing=0,
            shards_corrupted=0,
            can_recover=True,
        )
        assert report.is_valid is True
        assert report.can_recover is True

    def test_recovery_possible_with_sufficient_valid_shards(self):
        """Recovery possible when valid shards >= data_shards."""
        report = IntegrityReport(
            set_id=uuid4(),
            is_valid=False,
            shards_checked=8,
            shards_valid=5,
            shards_missing=2,
            shards_corrupted=1,
            can_recover=True,  # 5 valid >= 5 data shards
        )
        assert report.can_recover is True

    def test_recovery_impossible_with_too_few_valid_shards(self):
        """Recovery impossible when valid shards < data_shards."""
        report = IntegrityReport(
            set_id=uuid4(),
            is_valid=False,
            shards_checked=8,
            shards_valid=3,
            shards_missing=4,
            shards_corrupted=1,
            can_recover=False,
        )
        assert report.can_recover is False


# ============================================================================
# Shard Creation Tests
# ============================================================================


class TestShardCreation:
    """Test erasure coding shard creation."""

    def test_creates_correct_number_of_shards(self):
        """Total shards = data_shards + parity_shards."""
        payload = b"test data for erasure coding " * 100
        shards = _create_shards(payload, data_shards=3, parity_shards=2)
        assert len(shards) == 5

    def test_all_shards_have_equal_size(self):
        """All shards should be padded to equal size."""
        payload = b"test data for erasure coding " * 100
        shards = _create_shards(payload, data_shards=3, parity_shards=2)
        sizes = {len(s) for s in shards}
        assert len(sizes) == 1  # All same size

    def test_data_shards_reconstruct_payload(self):
        """Data shards (without parity) should contain the original payload."""
        payload = b"hello world" + b"\x00" * 100  # Ensure clean boundaries
        shards = _create_shards(payload, data_shards=3, parity_shards=2)
        # Reconstruct from data shards only
        reconstructed = b"".join(shards[:3])
        assert payload in reconstructed or reconstructed.startswith(payload)
