"""Tests for valence.core.incentives — calibration, rewards, transfers, velocity.

Tests cover:
- Brier score calculation
- Calibration reward formula
- Reward creation and claiming
- Transfer recording
- Velocity limit checking
"""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from valence.core.incentives import (
    CalibrationSnapshot,
    Reward,
    Transfer,
    VelocityStatus,
    calculate_brier_score,
    calculate_calibration_reward,
    check_velocity_limit,
    claim_reward,
    create_reward,
    get_calibration_history,
    get_pending_rewards,
    get_transfers,
    get_velocity_status,
    record_transfer,
    run_calibration_snapshot,
    update_velocity,
)
from valence.core.exceptions import NotFoundError, ValidationException
from valence.core.verification.constants import ReputationConstants


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

    with patch("valence.core.incentives.get_cursor", _mock_get_cursor):
        yield mock_cursor


# =============================================================================
# CALIBRATION TESTS
# =============================================================================


class TestCalculateBrierScore:
    """Tests for calculate_brier_score."""

    def test_no_data_returns_zero(self, mock_get_cursor):
        score, n = calculate_brier_score("did:valence:alice", date(2025, 1, 1), date(2025, 2, 1))
        assert score == 0.0
        assert n == 0

    def test_perfect_calibration(self, mock_get_cursor):
        # All beliefs confirmed, all at 100% confidence
        mock_get_cursor.fetchall.return_value = [
            {"result": "confirmed", "confidence": json.dumps({"overall": 1.0})},
            {"result": "confirmed", "confidence": json.dumps({"overall": 1.0})},
        ]
        score, n = calculate_brier_score("did:valence:alice", date(2025, 1, 1), date(2025, 2, 1))
        assert score == 1.0
        assert n == 2

    def test_poor_calibration(self, mock_get_cursor):
        # Claimed 90% but contradicted
        mock_get_cursor.fetchall.return_value = [
            {"result": "contradicted", "confidence": json.dumps({"overall": 0.9})},
        ]
        score, n = calculate_brier_score("did:valence:alice", date(2025, 1, 1), date(2025, 2, 1))
        # error = (0.9 - 0.0)^2 = 0.81, score = 1 - 0.81 = 0.19
        assert abs(score - 0.19) < 0.01
        assert n == 1

    def test_mixed_results(self, mock_get_cursor):
        mock_get_cursor.fetchall.return_value = [
            {"result": "confirmed", "confidence": json.dumps({"overall": 0.8})},
            {"result": "contradicted", "confidence": json.dumps({"overall": 0.3})},
        ]
        score, n = calculate_brier_score("did:valence:alice", date(2025, 1, 1), date(2025, 2, 1))
        # error1 = (0.8 - 1.0)^2 = 0.04, error2 = (0.3 - 0.0)^2 = 0.09
        # mean = 0.065, score = 1 - 0.065 = 0.935
        assert abs(score - 0.935) < 0.01
        assert n == 2


class TestCalculateCalibrationReward:
    """Tests for calculate_calibration_reward."""

    def test_insufficient_sample_size(self):
        reward = calculate_calibration_reward(brier_score=0.8, sample_size=10, consecutive_months=0)
        assert reward == 0.0

    def test_below_penalty_threshold(self):
        reward = calculate_calibration_reward(brier_score=0.3, sample_size=100, consecutive_months=0)
        assert reward < 0  # Penalty

    def test_neutral_zone(self):
        reward = calculate_calibration_reward(brier_score=0.45, sample_size=100, consecutive_months=0)
        assert reward == 0.0

    def test_positive_reward(self):
        reward = calculate_calibration_reward(brier_score=0.8, sample_size=100, consecutive_months=0)
        assert reward > 0
        assert reward <= ReputationConstants.CALIBRATION_BONUS_BASE * 1.5

    def test_consistency_bonus(self):
        base_reward = calculate_calibration_reward(brier_score=0.8, sample_size=100, consecutive_months=0)
        bonus_reward = calculate_calibration_reward(brier_score=0.8, sample_size=100, consecutive_months=6)
        assert bonus_reward > base_reward

    def test_consistency_bonus_capped(self):
        reward_10 = calculate_calibration_reward(brier_score=0.8, sample_size=100, consecutive_months=10)
        reward_20 = calculate_calibration_reward(brier_score=0.8, sample_size=100, consecutive_months=20)
        # Both should be the same due to cap at 1.5x
        assert reward_10 == reward_20


class TestRunCalibrationSnapshot:
    """Tests for run_calibration_snapshot."""

    def test_no_data_returns_none(self, mock_get_cursor):
        result = run_calibration_snapshot("did:valence:alice", date(2025, 1, 1))
        assert result is None


# =============================================================================
# REWARD TESTS
# =============================================================================


class TestCreateReward:
    """Tests for create_reward."""

    def test_creates_reward(self, mock_get_cursor):
        reward = create_reward("did:valence:alice", 0.005, "verification", reason="Test reward")
        assert reward.identity_id == "did:valence:alice"
        assert reward.amount == 0.005
        assert reward.status == "pending"
        assert reward.reward_type == "verification"

    def test_with_expiry(self, mock_get_cursor):
        reward = create_reward("did:valence:alice", 0.005, "bounty_claimed", expires_in_days=30)
        assert reward.expires_at is not None


class TestGetPendingRewards:
    """Tests for get_pending_rewards."""

    def test_empty_rewards(self, mock_get_cursor):
        rewards = get_pending_rewards("did:valence:alice")
        assert rewards == []


class TestClaimReward:
    """Tests for claim_reward."""

    def test_not_found(self, mock_get_cursor):
        with pytest.raises(NotFoundError):
            claim_reward(uuid4())

    def test_not_pending(self, mock_get_cursor):
        mock_get_cursor.fetchone.return_value = {
            "id": uuid4(),
            "identity_id": "did:valence:alice",
            "amount": 0.005,
            "reward_type": "verification",
            "source_id": None,
            "reason": "Test",
            "status": "claimed",
            "created_at": datetime.now(),
            "claimed_at": datetime.now(),
            "expires_at": None,
        }
        with pytest.raises(ValidationException, match="not pending"):
            claim_reward(uuid4())

    def test_expired_reward(self, mock_get_cursor):
        mock_get_cursor.fetchone.return_value = {
            "id": uuid4(),
            "identity_id": "did:valence:alice",
            "amount": 0.005,
            "reward_type": "verification",
            "source_id": None,
            "reason": "Test",
            "status": "pending",
            "created_at": datetime.now() - timedelta(days=60),
            "claimed_at": None,
            "expires_at": datetime.now() - timedelta(days=1),
        }
        with pytest.raises(ValidationException, match="expired"):
            claim_reward(uuid4())


# =============================================================================
# TRANSFER TESTS
# =============================================================================


class TestRecordTransfer:
    """Tests for record_transfer."""

    def test_creates_transfer(self, mock_get_cursor):
        transfer = record_transfer(
            "did:valence:alice", "did:valence:bob",
            0.01, "bounty_payout", reason="Bounty earned",
        )
        assert transfer.from_identity_id == "did:valence:alice"
        assert transfer.to_identity_id == "did:valence:bob"
        assert transfer.amount == 0.01


class TestGetTransfers:
    """Tests for get_transfers."""

    def test_empty_transfers(self, mock_get_cursor):
        transfers = get_transfers("did:valence:alice")
        assert transfers == []


# =============================================================================
# VELOCITY TESTS
# =============================================================================


class TestCheckVelocityLimit:
    """Tests for check_velocity_limit."""

    def test_within_limits(self, mock_get_cursor):
        mock_get_cursor.fetchone.side_effect = [
            {"total_gain": 0.0},  # daily
            {"total_gain": 0.0},  # weekly
        ]
        assert check_velocity_limit("did:valence:alice", 0.005) is True

    def test_exceeds_daily_limit(self, mock_get_cursor):
        mock_get_cursor.fetchone.return_value = {"total_gain": ReputationConstants.MAX_DAILY_GAIN - 0.001}
        assert check_velocity_limit("did:valence:alice", 0.005) is False

    def test_exceeds_weekly_limit(self, mock_get_cursor):
        mock_get_cursor.fetchone.side_effect = [
            {"total_gain": 0.001},  # daily — OK
            {"total_gain": ReputationConstants.MAX_WEEKLY_GAIN - 0.001},  # weekly — exceeds
        ]
        assert check_velocity_limit("did:valence:alice", 0.005) is False


class TestUpdateVelocity:
    """Tests for update_velocity."""

    def test_inserts_tracking(self, mock_get_cursor):
        update_velocity("did:valence:alice", 0.005)
        calls = mock_get_cursor.execute.call_args_list
        sql_calls = [c[0][0] for c in calls]
        assert any("INSERT INTO velocity_tracking" in sql for sql in sql_calls)


class TestGetVelocityStatus:
    """Tests for get_velocity_status."""

    def test_no_tracking(self, mock_get_cursor):
        status = get_velocity_status("did:valence:alice")
        assert status.daily_gain == 0.0
        assert status.weekly_gain == 0.0
        assert status.daily_remaining == ReputationConstants.MAX_DAILY_GAIN
        assert status.weekly_remaining == ReputationConstants.MAX_WEEKLY_GAIN

    def test_with_existing_tracking(self, mock_get_cursor):
        mock_get_cursor.fetchone.side_effect = [
            {"total_gain": 0.01, "verification_count": 5},  # daily
            {"total_gain": 0.03},  # weekly
        ]
        status = get_velocity_status("did:valence:alice")
        assert status.daily_gain == 0.01
        assert status.daily_verifications == 5
        assert status.weekly_gain == 0.03


# =============================================================================
# MCP TOOL TESTS
# =============================================================================


class TestIncentiveTools:
    """Tests for incentive MCP tool handlers."""

    def test_calibration_run_no_data(self, mock_get_cursor):
        from valence.substrate.tools.incentives import calibration_run
        result = calibration_run(identity_id="did:valence:alice")
        assert result["success"] is True
        assert result["snapshot"] is None

    def test_calibration_history_empty(self, mock_get_cursor):
        from valence.substrate.tools.incentives import calibration_history
        result = calibration_history(identity_id="did:valence:alice")
        assert result["success"] is True
        assert result["total"] == 0

    def test_rewards_pending_empty(self, mock_get_cursor):
        from valence.substrate.tools.incentives import rewards_pending
        result = rewards_pending(identity_id="did:valence:alice")
        assert result["success"] is True
        assert result["count"] == 0

    def test_reward_claim_bad_uuid(self):
        from valence.substrate.tools.incentives import reward_claim
        result = reward_claim(reward_id="bad-uuid")
        assert result["success"] is False

    def test_transfer_history_invalid_direction(self):
        from valence.substrate.tools.incentives import transfer_history
        result = transfer_history(identity_id="did:valence:alice", direction="sideways")
        assert result["success"] is False

    def test_velocity_status_no_data(self, mock_get_cursor):
        from valence.substrate.tools.incentives import velocity_status
        result = velocity_status(identity_id="did:valence:alice")
        assert result["success"] is True
        assert result["velocity"]["daily_remaining"] == ReputationConstants.MAX_DAILY_GAIN
