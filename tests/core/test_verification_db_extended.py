"""Extended tests for valence.core.verification.db — covers dispute and reputation flows."""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from valence.core.verification.constants import ReputationConstants
from valence.core.verification.db import (
    _apply_reputation_update,
    _db_lock_stake,
    _process_dispute_resolution,
    _process_verification_reputation,
    _release_stake,
    get_dispute,
    get_disputes_for_verification,
    get_verification_summary,
)
from valence.core.verification.enums import (
    DisputeOutcome,
    DisputeStatus,
    DisputeType,
    StakeType,
    VerificationResult,
    VerificationStatus,
)
from valence.core.verification.evidence import Evidence
from valence.core.verification.results import ResultDetails, Stake
from valence.core.verification.verification import (
    Dispute,
    ReputationScore,
    ReputationUpdate,
    StakePosition,
    Verification,
)
from valence.core.exceptions import NotFoundError, ValidationException


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

    with patch("valence.core.verification.db.get_cursor", _mock_get_cursor):
        yield mock_cursor


def _make_reputation(identity_id: str = "alice", overall: float = 0.5) -> ReputationScore:
    return ReputationScore(
        identity_id=identity_id,
        overall=overall,
        by_domain={},
        verification_count=10,
        discrepancy_finds=1,
        stake_at_risk=0.0,
    )


def _make_verification(
    verifier_id: str = "bob",
    holder_id: str = "alice",
    result: VerificationResult = VerificationResult.CONFIRMED,
    stake_amount: float = 0.05,
) -> Verification:
    return Verification(
        id=uuid4(),
        verifier_id=verifier_id,
        belief_id=uuid4(),
        holder_id=holder_id,
        result=result,
        evidence=[],
        stake=Stake(amount=stake_amount, type=StakeType.STANDARD, locked_until=datetime.now() + timedelta(days=7), escrow_id=uuid4()),
        status=VerificationStatus.ACCEPTED,
    )


def _make_dispute(
    verification_id: UUID | None = None,
    disputer_id: str = "carol",
    outcome: DisputeOutcome | None = None,
    stake_amount: float = 0.03,
) -> Dispute:
    return Dispute(
        id=uuid4(),
        verification_id=verification_id or uuid4(),
        disputer_id=disputer_id,
        counter_evidence=[],
        stake=Stake(amount=stake_amount, type=StakeType.CHALLENGE, locked_until=datetime.now() + timedelta(days=7), escrow_id=uuid4()),
        dispute_type=DisputeType.EVIDENCE_INVALID,
        reasoning="This is wrong",
        status=DisputeStatus.RESOLVED if outcome else DisputeStatus.PENDING,
        outcome=outcome,
    )


def _rep_row(identity_id: str = "alice", overall: float = 0.5) -> dict:
    return {
        "identity_id": identity_id, "overall": overall, "by_domain": "{}",
        "verification_count": 10, "discrepancy_finds": 0, "stake_at_risk": 0.0,
        "created_at": datetime.now(), "modified_at": datetime.now(),
    }


# =============================================================================
# GET VERIFICATION SUMMARY TESTS
# =============================================================================


class TestGetVerificationSummary:
    """Tests for get_verification_summary."""

    def test_empty_summary(self):
        with patch("valence.core.verification.db.get_verifications_for_belief", return_value=[]):
            result = get_verification_summary(uuid4())
        assert result["total"] == 0
        assert result["consensus_result"] is None
        assert result["consensus_confidence"] == 0.0

    def test_summary_counts(self):
        v1 = _make_verification(result=VerificationResult.CONFIRMED)
        v2 = _make_verification(verifier_id="carol", result=VerificationResult.CONTRADICTED)
        with patch("valence.core.verification.db.get_verifications_for_belief", return_value=[v1, v2]):
            with patch("valence.core.verification.db.get_or_create_reputation", return_value=_make_reputation(overall=0.7)):
                result = get_verification_summary(uuid4())
        assert result["total"] == 2
        assert result["by_result"]["confirmed"] == 1
        assert result["by_result"]["contradicted"] == 1

    def test_consensus_calculation(self):
        v1 = _make_verification(result=VerificationResult.CONFIRMED)
        v2 = _make_verification(verifier_id="carol", result=VerificationResult.CONFIRMED)
        with patch("valence.core.verification.db.get_verifications_for_belief", return_value=[v1, v2]):
            with patch("valence.core.verification.db.get_or_create_reputation", return_value=_make_reputation(overall=0.7)):
                result = get_verification_summary(uuid4())
        assert result["consensus_result"] == "confirmed"
        assert result["consensus_confidence"] > 0


# =============================================================================
# APPLY REPUTATION UPDATE TESTS
# =============================================================================


class TestApplyReputationUpdate:
    """Tests for _apply_reputation_update."""

    def test_positive_delta(self, mock_get_cursor):
        mock_get_cursor.fetchone.return_value = _rep_row("alice", 0.5)
        event = _apply_reputation_update("alice", 0.1, "test reward")
        assert event.delta == 0.1
        assert event.old_value == 0.5
        assert event.new_value == 0.6

    def test_negative_delta_floors(self, mock_get_cursor):
        mock_get_cursor.fetchone.return_value = _rep_row("alice", 0.15)
        event = _apply_reputation_update("alice", -0.5, "penalty")
        assert event.new_value == ReputationConstants.REPUTATION_FLOOR

    def test_caps_at_one(self, mock_get_cursor):
        mock_get_cursor.fetchone.return_value = _rep_row("alice", 0.95)
        event = _apply_reputation_update("alice", 0.2, "big reward")
        assert event.new_value == 1.0

    def test_domain_specific_update(self, mock_get_cursor):
        mock_get_cursor.fetchone.return_value = {
            "identity_id": "alice", "overall": 0.5, "by_domain": json.dumps({"tech": 0.6}),
            "verification_count": 10, "discrepancy_finds": 0, "stake_at_risk": 0.0,
            "created_at": datetime.now(), "modified_at": datetime.now(),
        }
        event = _apply_reputation_update("alice", 0.1, "domain reward", dimension="tech")
        assert event.dimension == "tech"

    def test_with_verification_id(self, mock_get_cursor):
        mock_get_cursor.fetchone.return_value = _rep_row()
        vid = uuid4()
        event = _apply_reputation_update("alice", 0.05, "reward", verification_id=vid)
        assert event.verification_id == vid

    def test_with_dispute_id(self, mock_get_cursor):
        mock_get_cursor.fetchone.return_value = _rep_row()
        did = uuid4()
        event = _apply_reputation_update("alice", -0.05, "penalty", dispute_id=did)
        assert event.dispute_id == did


# =============================================================================
# DB LOCK STAKE TESTS
# =============================================================================


class TestDbLockStake:
    """Tests for _db_lock_stake."""

    def test_standard_stake(self):
        cursor = MagicMock()
        rep = _make_reputation()
        vid = uuid4()
        position = _db_lock_stake(cursor, rep, 0.05, verification_id=vid)
        assert position.amount == 0.05
        assert position.type == StakeType.STANDARD
        assert position.verification_id == vid
        assert rep.stake_at_risk == 0.05

    def test_challenge_stake(self):
        cursor = MagicMock()
        rep = _make_reputation()
        did = uuid4()
        position = _db_lock_stake(cursor, rep, 0.03, dispute_id=did)
        assert position.type == StakeType.CHALLENGE
        assert position.dispute_id == did

    def test_stake_accumulates(self):
        cursor = MagicMock()
        rep = _make_reputation()
        _db_lock_stake(cursor, rep, 0.05, verification_id=uuid4())
        _db_lock_stake(cursor, rep, 0.03, verification_id=uuid4())
        assert rep.stake_at_risk == 0.08


# =============================================================================
# RELEASE STAKE TESTS
# =============================================================================


class TestReleaseStake:
    """Tests for _release_stake."""

    def test_release_returns_amount(self, mock_get_cursor):
        pid = uuid4()
        mock_get_cursor.fetchall.return_value = [{"id": pid, "amount": 0.05}]
        amount = _release_stake("alice", verification_id=uuid4())
        assert amount == 0.05

    def test_forfeit_stake(self, mock_get_cursor):
        pid = uuid4()
        mock_get_cursor.fetchall.return_value = [{"id": pid, "amount": 0.03}]
        amount = _release_stake("alice", dispute_id=uuid4(), forfeit=True)
        assert amount == 0.03

    def test_no_positions(self, mock_get_cursor):
        mock_get_cursor.fetchall.return_value = []
        amount = _release_stake("alice", verification_id=uuid4())
        assert amount == 0.0

    def test_multiple_positions(self, mock_get_cursor):
        mock_get_cursor.fetchall.return_value = [
            {"id": uuid4(), "amount": 0.03},
            {"id": uuid4(), "amount": 0.02},
        ]
        amount = _release_stake("alice", verification_id=uuid4())
        assert amount == 0.05


# =============================================================================
# GET DISPUTE TESTS
# =============================================================================


class TestGetDispute:
    """Tests for get_dispute."""

    def test_not_found(self, mock_get_cursor):
        result = get_dispute(uuid4())
        assert result is None


class TestGetDisputesForVerification:
    """Tests for get_disputes_for_verification."""

    def test_empty(self, mock_get_cursor):
        result = get_disputes_for_verification(uuid4())
        assert result == []


# =============================================================================
# PROCESS VERIFICATION REPUTATION TESTS
# =============================================================================


class TestProcessVerificationReputation:
    """Tests for _process_verification_reputation."""

    def test_confirmed_rewards_verifier(self, mock_get_cursor):
        v = _make_verification(result=VerificationResult.CONFIRMED)
        mock_get_cursor.fetchone.side_effect = [
            _rep_row("bob", 0.6),  # get_or_create_reputation (verifier)
            {"confidence": json.dumps({"overall": 0.7})},  # belief confidence
            _rep_row("bob", 0.6),  # _apply_reputation_update (verifier)
            _rep_row("alice", 0.5),  # _apply_reputation_update (holder)
        ]
        mock_get_cursor.fetchall.return_value = []
        _process_verification_reputation(v)

    def test_contradicted_penalizes_holder(self, mock_get_cursor):
        v = _make_verification(result=VerificationResult.CONTRADICTED)
        mock_get_cursor.fetchone.side_effect = [
            _rep_row("bob", 0.7),  # verifier rep
            {"confidence": json.dumps({"overall": 0.8})},  # belief confidence
            _rep_row("bob", 0.7),  # _apply_reputation_update (verifier)
            _rep_row("alice", 0.5),  # _apply_reputation_update (holder)
        ]
        mock_get_cursor.fetchall.return_value = []
        _process_verification_reputation(v)

    def test_uncertain_small_reward(self, mock_get_cursor):
        v = _make_verification(result=VerificationResult.UNCERTAIN)
        mock_get_cursor.fetchone.side_effect = [
            _rep_row("bob", 0.5),
            {"confidence": json.dumps({"overall": 0.5})},
            _rep_row("bob", 0.5),  # _apply_reputation_update
        ]
        mock_get_cursor.fetchall.return_value = []
        _process_verification_reputation(v)

    def test_belief_confidence_string_parsing(self, mock_get_cursor):
        """Test that string confidence JSON is parsed correctly."""
        v = _make_verification(result=VerificationResult.CONFIRMED)
        mock_get_cursor.fetchone.side_effect = [
            _rep_row("bob", 0.6),
            {"confidence": '{"overall": 0.9}'},  # string, not dict
            _rep_row("bob", 0.6),
            _rep_row("alice", 0.5),
        ]
        mock_get_cursor.fetchall.return_value = []
        _process_verification_reputation(v)


# =============================================================================
# PROCESS DISPUTE RESOLUTION TESTS
# =============================================================================


class TestProcessDisputeResolution:
    """Tests for _process_dispute_resolution."""

    def test_upheld_dispute(self, mock_get_cursor):
        v = _make_verification()
        d = _make_dispute(verification_id=v.id, outcome=DisputeOutcome.UPHELD)

        with patch("valence.core.verification.db._apply_reputation_update") as mock_rep:
            with patch("valence.core.verification.db._release_stake"):
                _process_dispute_resolution(d, v)
            assert mock_rep.call_count == 2

    def test_overturned_dispute(self, mock_get_cursor):
        v = _make_verification(result=VerificationResult.CONTRADICTED)
        d = _make_dispute(verification_id=v.id, outcome=DisputeOutcome.OVERTURNED)

        with patch("valence.core.verification.db._apply_reputation_update") as mock_rep:
            with patch("valence.core.verification.db._release_stake"):
                with patch("valence.core.verification.db.get_or_create_reputation", return_value=_make_reputation("bob", 0.6)):
                    _process_dispute_resolution(d, v)
            assert mock_rep.call_count >= 3

    def test_overturned_non_contradiction(self, mock_get_cursor):
        """Overturned dispute on non-contradicted verification doesn't restore holder."""
        v = _make_verification(result=VerificationResult.CONFIRMED)
        d = _make_dispute(verification_id=v.id, outcome=DisputeOutcome.OVERTURNED)

        with patch("valence.core.verification.db._apply_reputation_update") as mock_rep:
            with patch("valence.core.verification.db._release_stake"):
                _process_dispute_resolution(d, v)
            # Only verifier penalty + disputer reward, no holder restoration
            assert mock_rep.call_count == 2

    def test_modified_dispute(self, mock_get_cursor):
        v = _make_verification()
        d = _make_dispute(verification_id=v.id, outcome=DisputeOutcome.MODIFIED)

        with patch("valence.core.verification.db._release_stake") as mock_release:
            _process_dispute_resolution(d, v)
            assert mock_release.call_count == 2

    def test_dismissed_dispute(self, mock_get_cursor):
        v = _make_verification()
        d = _make_dispute(verification_id=v.id, outcome=DisputeOutcome.DISMISSED)

        with patch("valence.core.verification.db._apply_reputation_update") as mock_rep:
            with patch("valence.core.verification.db._release_stake"):
                _process_dispute_resolution(d, v)
            assert mock_rep.call_count == 2
