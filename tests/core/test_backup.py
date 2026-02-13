"""Tests for valence.core.backup — backup orchestration, shards, integrity.

Tests cover:
- Backup creation with belief selection
- Shard creation (erasure coding)
- Integrity verification
- Backup listing and retrieval
"""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from valence.core.backup import (
    BackupSet,
    BackupShard,
    BackupStatus,
    IntegrityReport,
    RedundancyLevel,
    REDUNDANCY_PARAMS,
    _create_shards,
    _encrypt_payload,
    create_backup,
    get_backup,
    list_backups,
    verify_backup,
)
from valence.core.exceptions import NotFoundError


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_cursor():
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    return cursor


@pytest.fixture
def mock_get_cursor(mock_cursor):
    @contextmanager
    def _mock_get_cursor(dict_cursor: bool = True) -> Generator:
        yield mock_cursor

    with patch("valence.core.backup.get_cursor", _mock_get_cursor):
        yield mock_cursor


# =============================================================================
# SHARD CREATION TESTS
# =============================================================================


class TestCreateShards:
    """Tests for _create_shards."""

    def test_creates_correct_number_of_shards(self):
        payload = b"Hello, World! This is test data for erasure coding."
        shards = _create_shards(payload, data_shards=3, parity_shards=2)
        assert len(shards) == 5

    def test_data_shards_contain_payload(self):
        payload = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        shards = _create_shards(payload, data_shards=2, parity_shards=1)
        # Reassembling data shards should contain original payload
        reassembled = b"".join(shards[:2])
        assert payload in reassembled

    def test_shards_same_size(self):
        payload = b"Test data of variable length for sharding"
        shards = _create_shards(payload, data_shards=4, parity_shards=2)
        sizes = [len(s) for s in shards]
        assert len(set(sizes)) == 1  # All same size

    def test_empty_payload(self):
        shards = _create_shards(b"", data_shards=3, parity_shards=2)
        assert len(shards) == 5


class TestEncryptPayload:
    """Tests for _encrypt_payload."""

    def test_encrypted_differs_from_original(self):
        payload = b"Secret data that needs encryption"
        encrypted = _encrypt_payload(payload)
        assert encrypted != payload
        assert len(encrypted) > len(payload)  # Key prefix added

    def test_key_prefix(self):
        payload = b"Test"
        encrypted = _encrypt_payload(payload)
        assert len(encrypted) == 32 + len(payload)  # 32-byte key + payload


# =============================================================================
# REDUNDANCY PARAMS TESTS
# =============================================================================


class TestRedundancyParams:
    """Tests for redundancy level configuration."""

    def test_minimal_params(self):
        params = REDUNDANCY_PARAMS[RedundancyLevel.MINIMAL]
        assert params["data_shards"] == 3
        assert params["parity_shards"] == 2

    def test_paranoid_params(self):
        params = REDUNDANCY_PARAMS[RedundancyLevel.PARANOID]
        assert params["data_shards"] == 12
        assert params["parity_shards"] == 8

    def test_all_levels_defined(self):
        for level in RedundancyLevel:
            assert level in REDUNDANCY_PARAMS


# =============================================================================
# CREATE BACKUP TESTS
# =============================================================================


class TestCreateBackup:
    """Tests for create_backup."""

    def test_empty_backup(self, mock_get_cursor):
        mock_get_cursor.fetchall.return_value = []

        backup = create_backup()
        assert backup.belief_count == 0
        assert backup.status == BackupStatus.COMPLETED

    def test_backup_with_beliefs(self, mock_get_cursor):
        mock_get_cursor.fetchall.side_effect = [
            [  # beliefs
                {"id": uuid4(), "content": "Test belief", "confidence": {"overall": 0.8}, "domain_path": ["tech"], "source_id": "alice", "created_at": datetime.now()},
            ],
        ]

        with patch("valence.core.backup._save_shard"):
            backup = create_backup()

        assert backup.belief_count == 1
        assert backup.status == BackupStatus.COMPLETED
        assert backup.shard_count > 0


# =============================================================================
# VERIFY BACKUP TESTS
# =============================================================================


class TestVerifyBackup:
    """Tests for verify_backup."""

    def test_not_found(self, mock_get_cursor):
        with pytest.raises(NotFoundError):
            verify_backup(uuid4())


# =============================================================================
# LIST/GET BACKUP TESTS
# =============================================================================


class TestListBackups:
    """Tests for list_backups."""

    def test_empty_list(self, mock_get_cursor):
        result = list_backups()
        assert result == []


class TestGetBackup:
    """Tests for get_backup."""

    def test_not_found(self, mock_get_cursor):
        result = get_backup(uuid4())
        assert result is None

    def test_returns_backup(self, mock_get_cursor):
        bid = uuid4()
        mock_get_cursor.fetchone.return_value = {
            "id": bid,
            "belief_count": 100,
            "total_size_bytes": 50000,
            "content_hash": "abc123",
            "redundancy_level": "personal",
            "encrypted": False,
            "status": "completed",
            "shard_count": 8,
            "created_at": datetime.now(),
            "verified_at": None,
            "error_message": None,
        }
        result = get_backup(bid)
        assert result is not None
        assert result.belief_count == 100
        assert result.status == BackupStatus.COMPLETED


# =============================================================================
# DATA MODEL TESTS
# =============================================================================


class TestBackupModels:
    """Tests for backup data models."""

    def test_backup_set_defaults(self):
        bs = BackupSet(id=uuid4())
        assert bs.status == BackupStatus.IN_PROGRESS
        assert bs.redundancy_level == RedundancyLevel.PERSONAL
        assert bs.encrypted is False

    def test_backup_shard_defaults(self):
        shard = BackupShard(
            id=uuid4(), set_id=uuid4(), shard_index=0,
            is_parity=False, size_bytes=1024, checksum="abc",
        )
        assert shard.backend_id == "local"

    def test_integrity_report(self):
        report = IntegrityReport(
            set_id=uuid4(), is_valid=True,
            shards_checked=8, shards_valid=8,
            shards_missing=0, shards_corrupted=0,
            can_recover=True,
        )
        assert report.is_valid
        assert report.can_recover
