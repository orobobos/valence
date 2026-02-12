"""Tests for commit-reveal protocol (#353).

Tests cover:
1. compute_commitment_hash deterministic
2. compute_commitment_hash different inputs differ
3. generate_nonce randomness
4. submit_commitment creates record
5. submit_commitment persists to DB
6. submit_reveal valid hash
7. submit_reveal invalid hash
8. submit_reveal late but valid = penalty
9. submit_reveal not found raises
10. expire_unrevealed marks no_reveal
11. Commitment serialization
12. Reveal serialization
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from valence.core.consensus.commit_reveal import (
    DELAY_SECONDS,
    REVEAL_WINDOW_MINUTES,
    Commitment,
    Reveal,
    compute_commitment_hash,
    expire_unrevealed,
    generate_nonce,
    submit_commitment,
    submit_reveal,
)


@pytest.fixture
def mock_cur():
    return MagicMock()


class TestComputeCommitmentHash:
    """Test commitment hashing."""

    def test_deterministic(self):
        h1 = compute_commitment_hash("corroborate", "nonce123")
        h2 = compute_commitment_hash("corroborate", "nonce123")
        assert h1 == h2

    def test_different_votes_differ(self):
        h1 = compute_commitment_hash("corroborate", "nonce123")
        h2 = compute_commitment_hash("dispute", "nonce123")
        assert h1 != h2

    def test_different_nonces_differ(self):
        h1 = compute_commitment_hash("corroborate", "nonce1")
        h2 = compute_commitment_hash("corroborate", "nonce2")
        assert h1 != h2

    def test_returns_hex_string(self):
        h = compute_commitment_hash("vote", "nonce")
        assert len(h) == 64  # SHA256 hex
        int(h, 16)  # Should be valid hex


class TestGenerateNonce:
    """Test nonce generation."""

    def test_returns_hex_string(self):
        nonce = generate_nonce()
        assert len(nonce) == 32  # 16 bytes = 32 hex chars
        int(nonce, 16)

    def test_unique(self):
        nonces = {generate_nonce() for _ in range(10)}
        assert len(nonces) == 10


class TestSubmitCommitment:
    """Test commitment submission."""

    def test_creates_commitment(self, mock_cur):
        commitment = submit_commitment(
            mock_cur,
            belief_id="belief-1",
            committer_did="did:valence:alice",
            commitment_hash="abc123" * 10 + "abcd",
        )
        assert commitment.belief_id == "belief-1"
        assert commitment.committer_did == "did:valence:alice"
        assert commitment.status == "committed"
        assert commitment.id is not None

    def test_reveal_window_timing(self, mock_cur):
        commitment = submit_commitment(
            mock_cur,
            belief_id="belief-1",
            committer_did="did:valence:alice",
            commitment_hash="abc",
            delay_seconds=300,
            reveal_window_minutes=60,
        )
        # Reveal opens after delay
        assert commitment.reveal_window_opens > commitment.committed_at
        delta_open = (commitment.reveal_window_opens - commitment.committed_at).total_seconds()
        assert abs(delta_open - 300) < 2  # ~5 minutes

        # Reveal closes after window
        delta_close = (commitment.reveal_window_closes - commitment.reveal_window_opens).total_seconds()
        assert abs(delta_close - 3600) < 2  # ~60 minutes

    def test_persists_to_db(self, mock_cur):
        submit_commitment(mock_cur, "b1", "did:alice", "hash123")
        insert_sql = mock_cur.execute.call_args[0][0]
        assert "INSERT INTO corroboration_commitments" in insert_sql


class TestSubmitReveal:
    """Test reveal submission."""

    def test_valid_reveal(self, mock_cur):
        vote = "corroborate"
        nonce = "secret_nonce"
        expected_hash = compute_commitment_hash(vote, nonce)
        now = datetime.now(timezone.utc)

        mock_cur.fetchone.return_value = {
            "id": "commit-1",
            "commitment_hash": expected_hash,
            "reveal_window_opens": now - timedelta(minutes=5),
            "reveal_window_closes": now + timedelta(minutes=55),
            "status": "committed",
        }

        reveal = submit_reveal(mock_cur, "commit-1", vote, nonce)
        assert reveal.is_valid is True
        assert reveal.is_late is False

    def test_invalid_hash(self, mock_cur):
        now = datetime.now(timezone.utc)
        mock_cur.fetchone.return_value = {
            "id": "commit-1",
            "commitment_hash": "wrong_hash" * 6 + "wxyz",
            "reveal_window_opens": now - timedelta(minutes=5),
            "reveal_window_closes": now + timedelta(minutes=55),
            "status": "committed",
        }

        reveal = submit_reveal(mock_cur, "commit-1", "vote", "bad_nonce")
        assert reveal.is_valid is False

    def test_late_reveal_is_penalty(self, mock_cur):
        vote = "corroborate"
        nonce = "nonce"
        expected_hash = compute_commitment_hash(vote, nonce)
        now = datetime.now(timezone.utc)

        mock_cur.fetchone.return_value = {
            "id": "commit-1",
            "commitment_hash": expected_hash,
            "reveal_window_opens": now - timedelta(hours=2),
            "reveal_window_closes": now - timedelta(hours=1),  # Already closed
            "status": "committed",
        }

        reveal = submit_reveal(mock_cur, "commit-1", vote, nonce)
        assert reveal.is_valid is True
        assert reveal.is_late is True
        # Verify status written as penalty
        update_sql = mock_cur.execute.call_args_list[-1][0][0]
        update_args = mock_cur.execute.call_args_list[-1][0][1]
        assert "UPDATE corroboration_commitments" in update_sql
        assert update_args[0] == "penalty"

    def test_not_found_raises(self, mock_cur):
        mock_cur.fetchone.return_value = None
        with pytest.raises(ValueError, match="Commitment not found"):
            submit_reveal(mock_cur, "missing-id", "vote", "nonce")


class TestExpireUnrevealed:
    """Test expiration of unrevealed commitments."""

    def test_returns_count(self, mock_cur):
        mock_cur.rowcount = 3
        count = expire_unrevealed(mock_cur)
        assert count == 3

    def test_updates_status(self, mock_cur):
        mock_cur.rowcount = 0
        expire_unrevealed(mock_cur)
        sql = mock_cur.execute.call_args[0][0]
        assert "SET status = 'no_reveal'" in sql
        assert "status = 'committed'" in sql


class TestSerialization:
    """Test dataclass serialization."""

    def test_commitment_to_dict(self):
        now = datetime.now(timezone.utc)
        c = Commitment(
            id="c1", belief_id="b1", committer_did="did:alice",
            commitment_hash="abc", committed_at=now,
            reveal_window_opens=now + timedelta(minutes=5),
            reveal_window_closes=now + timedelta(minutes=65),
        )
        d = c.to_dict()
        assert d["belief_id"] == "b1"
        assert d["status"] == "committed"
        assert "reveal_window_opens" in d

    def test_reveal_to_dict(self):
        now = datetime.now(timezone.utc)
        r = Reveal(
            commitment_id="c1", vote_value="corroborate",
            nonce="secret", revealed_at=now,
            is_valid=True, is_late=False,
        )
        d = r.to_dict()
        assert d["vote_value"] == "corroborate"
        assert d["is_valid"] is True
        assert d["is_late"] is False
