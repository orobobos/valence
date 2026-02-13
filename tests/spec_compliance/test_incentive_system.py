"""
Spec Compliance Tests: Incentive System

Verifies the codebase implements the incentive system per
spec/components/incentive-system/SPEC.md.

Key requirements:
- Confirmation reward formula with diminishing returns
- Contradiction reward formula (5x base, higher multiplier cap)
- Calibration scoring via Brier score
- Velocity limits: daily gain 0.02, weekly gain 0.08
- Reputation floor 0.1, max stake ratio 0.20
- CalibrationSnapshot, Reward, Transfer models
- Calibration reward requires min 50 verified beliefs, score > 0.5
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from valence.core.incentives import (
    CalibrationSnapshot,
    Reward,
    Transfer,
    VelocityStatus,
    calculate_brier_score,
    calculate_calibration_reward,
)
from valence.core.verification.constants import ReputationConstants
from valence.core.verification.verification import (
    calculate_bounty,
    calculate_confirmation_reward,
    calculate_contradiction_reward,
    calculate_holder_contradiction_penalty,
    calculate_partial_reward,
)


# ============================================================================
# Reward Formula Tests
# ============================================================================


class TestConfirmationReward:
    """Test confirmation reward per spec Section 2.1."""

    def test_base_confirmation_reward(self):
        """BASE_CONFIRMATION = 0.001 (0.1% of neutral reputation)."""
        assert ReputationConstants.CONFIRMATION_BASE == 0.001

    def test_confirmation_reward_increases_with_stake(self):
        """Higher stake = higher reward (stake_factor capped at 2.0)."""
        low_stake = calculate_confirmation_reward(stake=0.01, min_stake=0.01, belief_confidence=0.8, existing_confirmations=0)
        high_stake = calculate_confirmation_reward(stake=0.02, min_stake=0.01, belief_confidence=0.8, existing_confirmations=0)
        assert high_stake > low_stake

    def test_confirmation_reward_diminishes_with_prior_confirmations(self):
        """Novelty factor: 1/sqrt(prior_confirmations + 1) - first confirmations worth more."""
        first = calculate_confirmation_reward(stake=0.01, min_stake=0.01, belief_confidence=0.8, existing_confirmations=0)
        tenth = calculate_confirmation_reward(stake=0.01, min_stake=0.01, belief_confidence=0.8, existing_confirmations=9)
        assert first > tenth

    def test_confirmation_reward_stake_multiplier_capped_at_two(self):
        """Stake multiplier capped at 2.0."""
        at_cap = calculate_confirmation_reward(stake=0.02, min_stake=0.01, belief_confidence=0.8, existing_confirmations=0)
        above_cap = calculate_confirmation_reward(stake=0.10, min_stake=0.01, belief_confidence=0.8, existing_confirmations=0)
        assert abs(at_cap - above_cap) < 0.0001


class TestContradictionReward:
    """Test contradiction reward per spec Section 2.1."""

    def test_base_contradiction_reward(self):
        """BASE_CONTRADICTION = 0.005 (0.5% of neutral reputation)."""
        assert ReputationConstants.CONTRADICTION_BASE == 0.005

    def test_contradiction_reward_higher_than_confirmation(self):
        """Spec: contradiction reward is 5x base vs confirmation (asymmetric)."""
        conf_reward = calculate_confirmation_reward(stake=0.01, min_stake=0.01, belief_confidence=0.8, existing_confirmations=0)
        contra_reward = calculate_contradiction_reward(
            stake=0.01, min_stake=0.01, belief_confidence=0.8, is_first_contradiction=True,
        )
        assert contra_reward > conf_reward

    def test_first_finder_bonus(self):
        """First contradiction gets 2x novelty bonus."""
        first = calculate_contradiction_reward(stake=0.01, min_stake=0.01, belief_confidence=0.8, is_first_contradiction=True)
        second = calculate_contradiction_reward(
            stake=0.01, min_stake=0.01, belief_confidence=0.8, is_first_contradiction=False, existing_contradictions=1,
        )
        assert first > second

    def test_confidence_premium_is_squared(self):
        """Confidence premium = belief_confidence^2."""
        high_conf = calculate_contradiction_reward(stake=0.01, min_stake=0.01, belief_confidence=0.9, is_first_contradiction=True)
        low_conf = calculate_contradiction_reward(stake=0.01, min_stake=0.01, belief_confidence=0.5, is_first_contradiction=True)
        # Ratio should be approximately (0.9^2)/(0.5^2) = 3.24
        assert high_conf / low_conf == pytest.approx(0.81 / 0.25, rel=0.01)

    def test_stake_multiplier_capped_at_three(self):
        """Contradiction stake multiplier capped at 3.0 (higher than confirmation)."""
        at_cap = calculate_contradiction_reward(stake=0.03, min_stake=0.01, belief_confidence=0.8, is_first_contradiction=True)
        above_cap = calculate_contradiction_reward(stake=0.10, min_stake=0.01, belief_confidence=0.8, is_first_contradiction=True)
        assert abs(at_cap - above_cap) < 0.0001


class TestPartialReward:
    """Test partial verification reward per spec Section 2.1."""

    def test_partial_reward_is_proportional_blend(self):
        """partial_reward = accuracy * confirmation + (1-accuracy) * contradiction."""
        result = calculate_partial_reward(
            accuracy_estimate=0.5,
            stake=0.01,
            min_stake=0.01,
            belief_confidence=0.8,
            existing_confirmations=0,
            existing_contradictions=0,
        )
        assert result > 0


class TestHolderPenalty:
    """Test holder penalty for contradictions per spec Section 2.1."""

    def test_holder_penalty_increases_with_confidence(self):
        """Overconfidence multiplier = belief_confidence^2."""
        high = calculate_holder_contradiction_penalty(belief_confidence=0.9, verifier_reputation=0.5)
        low = calculate_holder_contradiction_penalty(belief_confidence=0.5, verifier_reputation=0.5)
        assert high > low


# ============================================================================
# Calibration Tests
# ============================================================================


class TestCalibrationScoring:
    """Test calibration scoring per spec Section 2.3."""

    def test_calibration_reward_formula(self):
        """calibration_reward = BASE * score * volume_factor * consistency_bonus."""
        reward = calculate_calibration_reward(brier_score=0.8, sample_size=100, consecutive_months=3)
        expected = 0.01 * 0.8 * 1.0 * (1.0 + 3 * 0.05)
        assert abs(reward - expected) < 0.001

    def test_calibration_requires_min_50_samples(self):
        """Spec: minimum 50 verified beliefs in period."""
        reward = calculate_calibration_reward(brier_score=0.8, sample_size=20, consecutive_months=0)
        assert reward == 0.0

    def test_calibration_score_above_half_to_earn(self):
        """Spec: score > 0.5 to earn reward."""
        reward = calculate_calibration_reward(brier_score=0.45, sample_size=100, consecutive_months=0)
        assert reward == 0.0

    def test_calibration_penalty_below_threshold(self):
        """Spec: score < 0.4 triggers penalty."""
        reward = calculate_calibration_reward(brier_score=0.3, sample_size=100, consecutive_months=0)
        assert reward < 0

    def test_calibration_penalty_threshold_value(self):
        """Penalty threshold should be 0.4."""
        assert ReputationConstants.CALIBRATION_PENALTY_THRESHOLD == 0.4

    def test_consistency_bonus_capped_at_1_5(self):
        """Consistency bonus = min(1.5, 1 + months * 0.05)."""
        # 10 months * 0.05 = 0.50, so bonus = 1.5 (capped)
        reward_capped = calculate_calibration_reward(brier_score=0.8, sample_size=100, consecutive_months=10)
        reward_more = calculate_calibration_reward(brier_score=0.8, sample_size=100, consecutive_months=20)
        assert abs(reward_capped - reward_more) < 0.0001


# ============================================================================
# Velocity Limit Tests
# ============================================================================


class TestVelocityLimits:
    """Test velocity limits per spec Section 5.2."""

    def test_max_daily_gain(self):
        """Max daily gain = 0.02 (2%)."""
        assert ReputationConstants.MAX_DAILY_GAIN == 0.02

    def test_max_weekly_gain(self):
        """Max weekly gain = 0.08 (8%)."""
        assert ReputationConstants.MAX_WEEKLY_GAIN == 0.08

    def test_reputation_floor(self):
        """Minimum reputation = 0.1."""
        assert ReputationConstants.REPUTATION_FLOOR == 0.1

    def test_max_stake_ratio(self):
        """Max stake ratio = 0.20 (can't bet more than 20%)."""
        assert ReputationConstants.MAX_STAKE_RATIO == 0.20

    def test_max_verifications_per_day(self):
        """Spec rate limit: 50 verifications per day."""
        assert ReputationConstants.MAX_VERIFICATIONS_PER_DAY == 50


# ============================================================================
# Data Model Tests
# ============================================================================


class TestIncentiveDataModels:
    """Test incentive system data models exist with expected fields."""

    def test_reward_model_fields(self):
        """Reward has id, identity_id, amount, reward_type, status."""
        from uuid import uuid4

        r = Reward(
            id=uuid4(),
            identity_id="did:test:123",
            amount=0.01,
            reward_type="confirmation",
        )
        assert r.status == "pending"
        assert r.identity_id == "did:test:123"

    def test_transfer_model_fields(self):
        """Transfer has from_identity_id, to_identity_id, amount, transfer_type."""
        from uuid import uuid4

        t = Transfer(
            id=uuid4(),
            from_identity_id="did:test:alice",
            to_identity_id="did:test:bob",
            amount=0.005,
            transfer_type="verification_stake_forfeit",
        )
        assert t.from_identity_id == "did:test:alice"

    def test_calibration_snapshot_fields(self):
        """CalibrationSnapshot has brier_score, sample_size, reward_earned."""
        from uuid import uuid4

        cs = CalibrationSnapshot(
            id=uuid4(),
            identity_id="did:test:123",
            period_start=date.today(),
            period_end=date.today() + timedelta(days=30),
            brier_score=0.75,
            sample_size=100,
            reward_earned=0.008,
        )
        assert cs.brier_score == 0.75
        assert cs.sample_size == 100

    def test_velocity_status_fields(self):
        """VelocityStatus has daily_gain, weekly_gain, remaining values."""
        vs = VelocityStatus(
            identity_id="did:test:123",
            daily_gain=0.005,
            weekly_gain=0.02,
            daily_remaining=0.015,
            weekly_remaining=0.06,
        )
        assert vs.daily_remaining == 0.015


# ============================================================================
# Bounty Tests
# ============================================================================


class TestBountyFormula:
    """Test discrepancy bounty formula per spec Section 3.4."""

    def test_bounty_increases_with_confidence(self):
        """Higher confidence beliefs have higher bounties (confidence_premium = conf^2)."""
        high = calculate_bounty(holder_stake=0.01, belief_confidence=0.9, days_since_creation=30)
        low = calculate_bounty(holder_stake=0.01, belief_confidence=0.5, days_since_creation=30)
        assert high > low

    def test_bounty_increases_with_age(self):
        """Age factor increases bounty up to a cap."""
        young = calculate_bounty(holder_stake=0.01, belief_confidence=0.8, days_since_creation=1)
        old = calculate_bounty(holder_stake=0.01, belief_confidence=0.8, days_since_creation=30)
        assert old > young

    def test_bounty_multiplier_constant(self):
        """Bounty multiplier = 0.5."""
        assert ReputationConstants.BOUNTY_MULTIPLIER == 0.5
