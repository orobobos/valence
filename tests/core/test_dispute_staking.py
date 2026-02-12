"""Tests for dispute staking with quality scoring (#350).

Tests cover:
1. get_consensus_level thresholds
2. calculate_stake_requirement L1/L2/L3
3. calculate_stake_requirement with quality penalty
4. DisputeQuality score calculation
5. DisputeQuality can_file logic
6. get_dispute_quality from DB
7. validate_dispute_filing allowed
8. validate_dispute_filing rejected (low quality)
9. validate_dispute_filing belief not found
10. StakeRequirement serialization
11. DisputeQuality serialization
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from valence.core.dispute_staking import (
    BASE_STAKE,
    QUALITY_PENALTY_MULTIPLIER,
    QUALITY_PENALTY_THRESHOLD,
    QUALITY_REJECT_THRESHOLD,
    DisputeQuality,
    StakeRequirement,
    calculate_stake_requirement,
    get_consensus_level,
    get_dispute_quality,
    validate_dispute_filing,
)


@pytest.fixture
def mock_cur():
    return MagicMock()


class TestGetConsensusLevel:
    """Test consensus level mapping."""

    def test_level_1_no_corroboration(self):
        assert get_consensus_level(0) == 1

    def test_level_1_one_corroboration(self):
        assert get_consensus_level(1) == 1

    def test_level_2_two_corroborations(self):
        assert get_consensus_level(2) == 2

    def test_level_2_four_corroborations(self):
        assert get_consensus_level(4) == 2

    def test_level_3_five_corroborations(self):
        assert get_consensus_level(5) == 3

    def test_level_3_many_corroborations(self):
        assert get_consensus_level(100) == 3


class TestCalculateStakeRequirement:
    """Test stake calculation."""

    def test_l1_no_penalty(self):
        req = calculate_stake_requirement(0, quality_score=0.5)
        assert req.consensus_multiplier == 1.0
        assert req.quality_multiplier == 1.0
        assert req.total_required == BASE_STAKE * 1.0

    def test_l2_no_penalty(self):
        req = calculate_stake_requirement(3, quality_score=0.5)
        assert req.consensus_multiplier == 2.0
        assert req.total_required == BASE_STAKE * 2.0

    def test_l3_no_penalty(self):
        req = calculate_stake_requirement(10, quality_score=0.5)
        assert req.consensus_multiplier == 5.0
        assert req.total_required == BASE_STAKE * 5.0

    def test_low_quality_penalty(self):
        req = calculate_stake_requirement(0, quality_score=0.15)
        assert req.quality_multiplier == QUALITY_PENALTY_MULTIPLIER
        assert req.total_required == BASE_STAKE * 1.0 * QUALITY_PENALTY_MULTIPLIER

    def test_l3_with_penalty(self):
        req = calculate_stake_requirement(10, quality_score=0.1)
        assert req.total_required == BASE_STAKE * 5.0 * QUALITY_PENALTY_MULTIPLIER

    def test_custom_base_stake(self):
        req = calculate_stake_requirement(0, quality_score=0.5, base_stake=10.0)
        assert req.base_amount == 10.0
        assert req.total_required == 10.0

    def test_reason_includes_level(self):
        req = calculate_stake_requirement(3, quality_score=0.5)
        assert "L2" in req.reason

    def test_reason_includes_penalty_info(self):
        req = calculate_stake_requirement(0, quality_score=0.1)
        assert "low quality penalty" in req.reason


class TestDisputeQuality:
    """Test quality score dataclass."""

    def test_new_participant_score(self):
        dq = DisputeQuality(identity_id="new")
        assert dq.score == 0.5  # Neutral

    def test_perfect_record(self):
        dq = DisputeQuality(identity_id="good", disputes_filed=10, disputes_won=10)
        # 10 / (10 + 1) = 0.909...
        assert dq.score == pytest.approx(10 / 11)

    def test_terrible_record(self):
        dq = DisputeQuality(identity_id="bad", disputes_filed=10, disputes_won=0)
        assert dq.score == 0.0

    def test_can_file_new_participant(self):
        dq = DisputeQuality(identity_id="new")
        assert dq.can_file is True

    def test_can_file_good_record(self):
        dq = DisputeQuality(identity_id="good", disputes_filed=10, disputes_won=5)
        assert dq.can_file is True

    def test_cannot_file_terrible_record(self):
        dq = DisputeQuality(identity_id="bad", disputes_filed=10, disputes_won=0)
        # score = 0.0 < 0.1, filed >= 3
        assert dq.can_file is False

    def test_can_file_few_disputes_even_if_bad(self):
        # Under 3 filed = always allowed
        dq = DisputeQuality(identity_id="new-bad", disputes_filed=2, disputes_won=0)
        assert dq.can_file is True

    def test_to_dict(self):
        dq = DisputeQuality(identity_id="test", disputes_filed=5, disputes_won=3, disputes_lost=2)
        d = dq.to_dict()
        assert d["identity_id"] == "test"
        assert d["disputes_filed"] == 5
        assert "score" in d
        assert "can_file" in d


class TestGetDisputeQuality:
    """Test DB-backed quality lookup."""

    def test_returns_quality(self, mock_cur):
        mock_cur.fetchone.return_value = {"filed": 10, "won": 7, "lost": 3}
        quality = get_dispute_quality(mock_cur, "did:valence:alice")
        assert quality.identity_id == "did:valence:alice"
        assert quality.disputes_filed == 10
        assert quality.disputes_won == 7
        assert quality.disputes_lost == 3

    def test_queries_disputes_table(self, mock_cur):
        mock_cur.fetchone.return_value = {"filed": 0, "won": 0, "lost": 0}
        get_dispute_quality(mock_cur, "did:test")
        sql = mock_cur.execute.call_args[0][0]
        assert "FROM disputes" in sql
        assert "disputer_id" in sql


class TestValidateDisputeFiling:
    """Test dispute validation."""

    def test_allowed_filing(self, mock_cur):
        # First fetchone: quality
        # Second fetchone: belief
        mock_cur.fetchone.side_effect = [
            {"filed": 5, "won": 3, "lost": 2},  # quality
            {"count": 3},  # belief corroboration
        ]
        allowed, result = validate_dispute_filing(mock_cur, "did:alice", "belief-1")
        assert allowed is True
        assert isinstance(result, StakeRequirement)
        assert result.consensus_multiplier == 2.0  # L2 (3 corroborations)

    def test_rejected_low_quality(self, mock_cur):
        mock_cur.fetchone.side_effect = [
            {"filed": 10, "won": 0, "lost": 10},  # terrible quality
        ]
        allowed, result = validate_dispute_filing(mock_cur, "did:bad", "belief-1")
        assert allowed is False
        assert isinstance(result, str)
        assert "quality too low" in result.lower()

    def test_belief_not_found(self, mock_cur):
        mock_cur.fetchone.side_effect = [
            {"filed": 5, "won": 3, "lost": 2},  # quality OK
            None,  # belief not found
        ]
        allowed, result = validate_dispute_filing(mock_cur, "did:alice", "missing")
        assert allowed is False
        assert "not found" in result.lower()


class TestStakeRequirementSerialization:
    """Test StakeRequirement.to_dict."""

    def test_to_dict(self):
        req = StakeRequirement(
            base_amount=1.0,
            consensus_multiplier=2.0,
            quality_multiplier=1.0,
            total_required=2.0,
            reason="L2 belief",
        )
        d = req.to_dict()
        assert d["base_amount"] == 1.0
        assert d["total_required"] == 2.0
        assert d["reason"] == "L2 belief"
