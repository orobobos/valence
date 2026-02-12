"""Tests for Merkle consistency proofs (#351).

Tests cover:
1. build_belief_merkle_root with beliefs
2. build_belief_merkle_root with empty set
3. compare_with_peer detects divergence
4. compare_with_peer returns None for consistent roots
5. MerkleCheckpoint serialization
6. PartitionEvent serialization
7. get_recent_checkpoints
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from valence.core.merkle_sync import (
    MerkleCheckpoint,
    PartitionEvent,
    build_belief_merkle_root,
    compare_with_peer,
    get_recent_checkpoints,
)


@pytest.fixture
def mock_cur():
    return MagicMock()


class TestBuildBeliefMerkleRoot:
    """Test Merkle tree construction."""

    def test_builds_from_beliefs(self, mock_cur):
        mock_cur.fetchall.return_value = [
            {"id": "aaaa-1111"},
            {"id": "bbbb-2222"},
            {"id": "cccc-3333"},
        ]
        checkpoint = build_belief_merkle_root(mock_cur)
        assert checkpoint.belief_count == 3
        assert len(checkpoint.root_hash) == 64  # SHA256 hex
        assert checkpoint.id is not None

    def test_empty_set(self, mock_cur):
        mock_cur.fetchall.return_value = []
        checkpoint = build_belief_merkle_root(mock_cur)
        assert checkpoint.belief_count == 0
        assert checkpoint.root_hash is not None

    def test_deterministic(self, mock_cur):
        beliefs = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        mock_cur.fetchall.return_value = beliefs
        cp1 = build_belief_merkle_root(mock_cur)

        mock_cur.fetchall.return_value = beliefs
        cp2 = build_belief_merkle_root(mock_cur)

        assert cp1.root_hash == cp2.root_hash

    def test_persists_checkpoint(self, mock_cur):
        mock_cur.fetchall.return_value = [{"id": "x"}]
        build_belief_merkle_root(mock_cur)
        insert_sql = mock_cur.execute.call_args_list[-1][0][0]
        assert "INSERT INTO merkle_checkpoints" in insert_sql


class TestCompareWithPeer:
    """Test peer comparison."""

    def test_consistent_roots(self):
        result = compare_with_peer("abc123", "did:peer", "abc123")
        assert result is None

    def test_divergent_roots(self):
        result = compare_with_peer("abc123", "did:peer", "xyz789")
        assert result is not None
        assert isinstance(result, PartitionEvent)
        assert result.peer_did == "did:peer"
        assert result.severity == "warning"

    def test_persists_partition_event(self, mock_cur):
        result = compare_with_peer("abc", "did:peer", "xyz", cur=mock_cur)
        assert result is not None
        insert_sql = mock_cur.execute.call_args[0][0]
        assert "INSERT INTO partition_events" in insert_sql


class TestSerialization:
    """Test dataclass serialization."""

    def test_checkpoint_to_dict(self):
        cp = MerkleCheckpoint(id="cp1", root_hash="abc" * 20 + "abcd", belief_count=10)
        d = cp.to_dict()
        assert d["belief_count"] == 10
        assert "root_hash" in d

    def test_partition_event_to_dict(self):
        ev = PartitionEvent(id="ev1", peer_did="did:bad", local_root="abc", peer_root="xyz", severity="warning")
        d = ev.to_dict()
        assert d["peer_did"] == "did:bad"
        assert d["severity"] == "warning"


class TestGetRecentCheckpoints:
    """Test checkpoint retrieval."""

    def test_returns_checkpoints(self, mock_cur):
        from datetime import datetime, timezone

        mock_cur.fetchall.return_value = [
            {"id": "cp1", "root_hash": "abc", "belief_count": 10, "created_at": datetime.now(timezone.utc)},
        ]
        checkpoints = get_recent_checkpoints(mock_cur, limit=5)
        assert len(checkpoints) == 1
        assert checkpoints[0].id == "cp1"
