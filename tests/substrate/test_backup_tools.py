"""Tests for backup MCP tool handlers."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from valence.core.backup import BackupSet, BackupStatus, IntegrityReport, RedundancyLevel
from valence.core.exceptions import NotFoundError
from valence.substrate.tools.backup import (
    backup_create,
    backup_get,
    backup_list,
    backup_verify,
)


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
# BACKUP CREATE TESTS
# =============================================================================


class TestBackupCreate:
    """Tests for backup_create tool handler."""

    def test_default_params(self, mock_get_cursor):
        mock_get_cursor.fetchall.return_value = []
        result = backup_create()
        assert result["success"] is True
        assert "backup" in result
        assert result["backup"]["status"] == "completed"

    def test_with_domain_filter(self, mock_get_cursor):
        mock_get_cursor.fetchall.return_value = []
        result = backup_create(domain_filter=["tech"])
        assert result["success"] is True

    def test_with_min_confidence(self, mock_get_cursor):
        mock_get_cursor.fetchall.return_value = []
        result = backup_create(min_confidence=0.8)
        assert result["success"] is True

    def test_with_encrypt(self, mock_get_cursor):
        mock_get_cursor.fetchall.return_value = []
        result = backup_create(encrypt=True)
        assert result["success"] is True

    def test_invalid_redundancy(self):
        result = backup_create(redundancy="invalid")
        assert result["success"] is False
        assert "redundancy" in result["error"].lower()

    def test_paranoid_redundancy(self, mock_get_cursor):
        mock_get_cursor.fetchall.return_value = []
        result = backup_create(redundancy="paranoid")
        assert result["success"] is True

    def test_backup_response_fields(self, mock_get_cursor):
        mock_get_cursor.fetchall.return_value = []
        result = backup_create()
        backup = result["backup"]
        assert "id" in backup
        assert "belief_count" in backup
        assert "total_size_bytes" in backup
        assert "shard_count" in backup
        assert "redundancy_level" in backup
        assert "encrypted" in backup
        assert "status" in backup
        assert "content_hash" in backup
        assert "created_at" in backup

    def test_with_beliefs(self, mock_get_cursor):
        mock_get_cursor.fetchall.side_effect = [
            [{"id": uuid4(), "content": "Test", "confidence": {"overall": 0.8}, "domain_path": ["tech"], "source_id": "alice", "created_at": datetime.now()}],
        ]
        with patch("valence.core.backup._save_shard"):
            result = backup_create()
        assert result["success"] is True
        assert result["backup"]["belief_count"] == 1
        assert result["backup"]["shard_count"] > 0


# =============================================================================
# BACKUP VERIFY TESTS
# =============================================================================


class TestBackupVerify:
    """Tests for backup_verify tool handler."""

    def test_invalid_uuid(self):
        result = backup_verify(backup_set_id="not-a-uuid")
        assert result["success"] is False
        assert "Invalid UUID" in result["error"]

    def test_not_found(self, mock_get_cursor):
        with patch("valence.core.backup.get_cursor") as mock_gc:
            @contextmanager
            def _gc(dict_cursor=True):
                yield mock_get_cursor
            mock_gc.side_effect = _gc
            result = backup_verify(backup_set_id=str(uuid4()))
        assert result["success"] is False
        assert "not found" in result["error"].lower() or "BackupSet" in result["error"]

    def test_valid_report(self):
        bid = uuid4()
        report = IntegrityReport(
            set_id=bid, is_valid=True,
            shards_checked=8, shards_valid=8,
            shards_missing=0, shards_corrupted=0,
            can_recover=True,
        )
        with patch("valence.substrate.tools.backup.db_verify_backup", return_value=report):
            result = backup_verify(backup_set_id=str(bid))
        assert result["success"] is True
        assert result["report"]["is_valid"] is True
        assert result["report"]["can_recover"] is True
        assert result["report"]["shards_checked"] == 8

    def test_corrupted_report(self):
        bid = uuid4()
        report = IntegrityReport(
            set_id=bid, is_valid=False,
            shards_checked=8, shards_valid=5,
            shards_missing=1, shards_corrupted=2,
            can_recover=True,
        )
        with patch("valence.substrate.tools.backup.db_verify_backup", return_value=report):
            result = backup_verify(backup_set_id=str(bid))
        assert result["success"] is True
        assert result["report"]["is_valid"] is False
        assert result["report"]["shards_missing"] == 1
        assert result["report"]["shards_corrupted"] == 2


# =============================================================================
# BACKUP LIST TESTS
# =============================================================================


class TestBackupList:
    """Tests for backup_list tool handler."""

    def test_empty_list(self):
        with patch("valence.substrate.tools.backup.db_list_backups", return_value=[]):
            result = backup_list()
        assert result["success"] is True
        assert result["backups"] == []
        assert result["total"] == 0

    def test_with_backups(self):
        bs = BackupSet(id=uuid4(), belief_count=10, shard_count=8, status=BackupStatus.COMPLETED)
        with patch("valence.substrate.tools.backup.db_list_backups", return_value=[bs]):
            result = backup_list()
        assert result["success"] is True
        assert result["total"] == 1
        assert result["backups"][0]["belief_count"] == 10
        assert result["backups"][0]["shard_count"] == 8

    def test_custom_limit(self):
        with patch("valence.substrate.tools.backup.db_list_backups", return_value=[]) as mock:
            backup_list(limit=5)
        mock.assert_called_once_with(limit=5)

    def test_backup_list_fields(self):
        bs = BackupSet(id=uuid4(), belief_count=5, shard_count=8, status=BackupStatus.VERIFIED, redundancy_level=RedundancyLevel.PARANOID)
        with patch("valence.substrate.tools.backup.db_list_backups", return_value=[bs]):
            result = backup_list()
        b = result["backups"][0]
        assert "id" in b
        assert "belief_count" in b
        assert "shard_count" in b
        assert "status" in b
        assert "redundancy_level" in b
        assert "created_at" in b


# =============================================================================
# BACKUP GET TESTS
# =============================================================================


class TestBackupGet:
    """Tests for backup_get tool handler."""

    def test_invalid_uuid(self):
        result = backup_get(backup_set_id="bad")
        assert result["success"] is False
        assert "Invalid UUID" in result["error"]

    def test_not_found(self):
        with patch("valence.substrate.tools.backup.db_get_backup", return_value=None):
            result = backup_get(backup_set_id=str(uuid4()))
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_found(self):
        bid = uuid4()
        bs = BackupSet(
            id=bid, belief_count=50, total_size_bytes=25000,
            shard_count=8, content_hash="abc123",
            redundancy_level=RedundancyLevel.FEDERATION,
            encrypted=True, status=BackupStatus.VERIFIED,
        )
        with patch("valence.substrate.tools.backup.db_get_backup", return_value=bs):
            result = backup_get(backup_set_id=str(bid))
        assert result["success"] is True
        backup = result["backup"]
        assert backup["id"] == str(bid)
        assert backup["belief_count"] == 50
        assert backup["total_size_bytes"] == 25000
        assert backup["encrypted"] is True
        assert backup["redundancy_level"] == "federation"
        assert backup["status"] == "verified"

    def test_response_includes_timestamps(self):
        bid = uuid4()
        now = datetime.now()
        bs = BackupSet(id=bid, status=BackupStatus.VERIFIED, created_at=now, verified_at=now)
        with patch("valence.substrate.tools.backup.db_get_backup", return_value=bs):
            result = backup_get(backup_set_id=str(bid))
        assert result["backup"]["created_at"] == now.isoformat()
        assert result["backup"]["verified_at"] == now.isoformat()

    def test_null_timestamps(self):
        bid = uuid4()
        bs = BackupSet(id=bid, verified_at=None, error_message=None)
        with patch("valence.substrate.tools.backup.db_get_backup", return_value=bs):
            result = backup_get(backup_set_id=str(bid))
        assert result["backup"]["verified_at"] is None
        assert result["backup"]["error_message"] is None
