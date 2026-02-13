"""Tests for valence.core.verification.db — database persistence layer.

Tests cover:
- Reputation CRUD operations
- Verification submission and acceptance with DB persistence
- Dispute submission and resolution with DB persistence
- Stake locking and release
- Reputation event logging
- Bounty operations
"""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from valence.core.exceptions import NotFoundError, ValidationException
from valence.core.verification.constants import ReputationConstants
from valence.core.verification.db import (
    _apply_reputation_update,
    _release_stake,
    accept_verification,
    get_bounty,
    get_dispute,
    get_or_create_reputation,
    get_reputation,
    get_reputation_events,
    get_verification,
    get_verification_summary,
    get_verifications_for_belief,
    list_bounties,
    resolve_dispute,
    submit_dispute,
    submit_verification,
)
from valence.core.verification.enums import (
    DisputeOutcome,
    DisputeStatus,
    DisputeType,
    EvidenceContribution,
    EvidenceType,
    ResolutionMethod,
    StakeType,
    VerificationResult,
    VerificationStatus,
)
from valence.core.verification.evidence import Evidence
from valence.core.verification.results import ResultDetails, Stake
from valence.core.verification.verification import ReputationScore


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_cursor():
    """Mock database cursor."""
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    return cursor


@pytest.fixture
def mock_get_cursor(mock_cursor):
    """Mock the get_cursor context manager."""

    @contextmanager
    def _mock_get_cursor(dict_cursor: bool = True) -> Generator:
        yield mock_cursor

    with patch("valence.core.verification.db.get_cursor", _mock_get_cursor):
        yield mock_cursor


@pytest.fixture
def sample_reputation_row():
    """Return a sample reputation DB row."""
    return {
        "identity_id": "did:valence:alice",
        "overall": 0.5,
        "by_domain": "{}",
        "verification_count": 0,
        "discrepancy_finds": 0,
        "stake_at_risk": 0.0,
        "created_at": datetime.now(),
        "modified_at": datetime.now(),
    }


@pytest.fixture
def sample_verification_row():
    """Return a sample verification DB row."""
    verification_id = uuid4()
    return {
        "id": verification_id,
        "verifier_id": "did:valence:bob",
        "belief_id": uuid4(),
        "holder_id": "did:valence:alice",
        "result": "confirmed",
        "evidence": json.dumps([{
            "id": str(uuid4()),
            "type": "external",
            "relevance": 0.9,
            "contribution": "supports",
        }]),
        "stake": json.dumps({
            "amount": 0.02,
            "type": "standard",
            "locked_until": (datetime.now() + timedelta(days=7)).isoformat(),
            "escrow_id": str(uuid4()),
        }),
        "reasoning": "Verified via external source",
        "result_details": None,
        "status": "pending",
        "dispute_id": None,
        "signature": None,
        "created_at": datetime.now(),
        "accepted_at": None,
    }


@pytest.fixture
def sample_evidence():
    """Supporting evidence for tests."""
    return [
        Evidence(
            id=uuid4(),
            type=EvidenceType.EXTERNAL,
            relevance=0.9,
            contribution=EvidenceContribution.SUPPORTS,
        )
    ]


@pytest.fixture
def sample_contradicting_evidence():
    """Contradicting evidence for tests."""
    return [
        Evidence(
            id=uuid4(),
            type=EvidenceType.EXTERNAL,
            relevance=0.9,
            contribution=EvidenceContribution.CONTRADICTS,
        )
    ]


@pytest.fixture
def sample_belief_info():
    """Sample belief info dict."""
    return {
        "holder_id": "did:valence:alice",
        "confidence": {"overall": 0.7},
        "domain_path": ["tech"],
    }


# =============================================================================
# REPUTATION TESTS
# =============================================================================


class TestGetOrCreateReputation:
    """Tests for get_or_create_reputation."""

    def test_returns_existing_reputation(self, mock_get_cursor, sample_reputation_row):
        mock_get_cursor.fetchone.return_value = sample_reputation_row

        rep = get_or_create_reputation("did:valence:alice")

        assert rep.identity_id == "did:valence:alice"
        assert rep.overall == 0.5

    def test_creates_new_reputation(self, mock_get_cursor, sample_reputation_row):
        mock_get_cursor.fetchone.side_effect = [None, sample_reputation_row]

        rep = get_or_create_reputation("did:valence:alice")

        assert rep.identity_id == "did:valence:alice"
        calls = mock_get_cursor.execute.call_args_list
        sql_calls = [c[0][0] for c in calls]
        assert any("INSERT INTO reputations" in sql for sql in sql_calls)

    def test_queries_by_identity_id(self, mock_get_cursor, sample_reputation_row):
        mock_get_cursor.fetchone.return_value = sample_reputation_row

        get_or_create_reputation("did:valence:bob")

        calls = mock_get_cursor.execute.call_args_list
        assert any("did:valence:bob" in str(c) for c in calls)


class TestGetReputation:
    """Tests for get_reputation."""

    def test_returns_none_for_missing(self, mock_get_cursor):
        result = get_reputation("did:valence:nonexistent")
        assert result is None

    def test_returns_reputation_when_found(self, mock_get_cursor, sample_reputation_row):
        mock_get_cursor.fetchone.return_value = sample_reputation_row

        result = get_reputation("did:valence:alice")

        assert result is not None
        assert result.identity_id == "did:valence:alice"


# =============================================================================
# VERIFICATION TESTS
# =============================================================================


class TestSubmitVerification:
    """Tests for submit_verification."""

    def test_rejects_self_verification(self, mock_get_cursor, sample_reputation_row, sample_evidence):
        mock_get_cursor.fetchone.return_value = sample_reputation_row
        mock_get_cursor.fetchall.return_value = []

        with pytest.raises(ValidationException, match="own belief"):
            submit_verification(
                belief_id=uuid4(),
                belief_info={"holder_id": "did:valence:alice", "confidence": {"overall": 0.7}},
                verifier_id="did:valence:alice",  # Same as holder
                result=VerificationResult.CONFIRMED,
                evidence=sample_evidence,
                stake_amount=0.02,
            )

    def test_successful_submission_inserts_row(self, mock_get_cursor, sample_reputation_row, sample_evidence):
        mock_get_cursor.fetchone.return_value = sample_reputation_row
        mock_get_cursor.fetchall.return_value = []

        verification = submit_verification(
            belief_id=uuid4(),
            belief_info={"holder_id": "did:valence:alice", "confidence": {"overall": 0.7}},
            verifier_id="did:valence:bob",
            result=VerificationResult.CONFIRMED,
            evidence=sample_evidence,
            stake_amount=0.02,
        )

        assert verification.status == VerificationStatus.PENDING
        assert verification.result == VerificationResult.CONFIRMED
        calls = mock_get_cursor.execute.call_args_list
        sql_calls = [c[0][0] for c in calls]
        assert any("INSERT INTO verifications" in sql for sql in sql_calls)

    def test_locks_stake_on_submission(self, mock_get_cursor, sample_reputation_row, sample_evidence):
        mock_get_cursor.fetchone.return_value = sample_reputation_row
        mock_get_cursor.fetchall.return_value = []

        submit_verification(
            belief_id=uuid4(),
            belief_info={"holder_id": "did:valence:alice", "confidence": {"overall": 0.7}},
            verifier_id="did:valence:bob",
            result=VerificationResult.CONFIRMED,
            evidence=sample_evidence,
            stake_amount=0.02,
        )

        calls = mock_get_cursor.execute.call_args_list
        sql_calls = [c[0][0] for c in calls]
        assert any("INSERT INTO stake_positions" in sql for sql in sql_calls)
        assert any("UPDATE reputations SET stake_at_risk" in sql for sql in sql_calls)


class TestGetVerification:
    """Tests for get_verification."""

    def test_returns_none_when_not_found(self, mock_get_cursor):
        result = get_verification(uuid4())
        assert result is None

    def test_returns_verification_from_row(self, mock_get_cursor, sample_verification_row):
        mock_get_cursor.fetchone.return_value = sample_verification_row

        result = get_verification(sample_verification_row["id"])

        assert result is not None
        assert result.verifier_id == "did:valence:bob"
        assert result.status == VerificationStatus.PENDING


class TestGetVerificationsForBelief:
    """Tests for get_verifications_for_belief."""

    def test_returns_empty_for_no_verifications(self, mock_get_cursor):
        result = get_verifications_for_belief(uuid4())
        assert result == []

    def test_returns_list_of_verifications(self, mock_get_cursor, sample_verification_row):
        mock_get_cursor.fetchall.return_value = [sample_verification_row]

        result = get_verifications_for_belief(sample_verification_row["belief_id"])

        assert len(result) == 1
        assert result[0].verifier_id == "did:valence:bob"


class TestAcceptVerification:
    """Tests for accept_verification."""

    def test_raises_not_found_for_missing(self, mock_get_cursor):
        with pytest.raises(NotFoundError):
            accept_verification(uuid4())

    def test_raises_if_not_pending(self, mock_get_cursor, sample_verification_row):
        sample_verification_row["status"] = "accepted"
        mock_get_cursor.fetchone.return_value = sample_verification_row

        with pytest.raises(ValidationException, match="not pending"):
            accept_verification(sample_verification_row["id"])

    def test_updates_status_to_accepted(self, mock_get_cursor, sample_verification_row, sample_reputation_row):
        # First call: get_verification, second: get_or_create_reputation, etc.
        mock_get_cursor.fetchone.side_effect = [
            sample_verification_row,  # get_verification
            sample_reputation_row,  # get_or_create_reputation (verifier)
            {"confidence": json.dumps({"overall": 0.7})},  # belief confidence
            sample_reputation_row,  # get_or_create_reputation (various)
            sample_reputation_row,  # get_or_create_reputation
            sample_reputation_row,  # _apply_reputation_update
            sample_reputation_row,  # get_or_create_reputation
        ]
        mock_get_cursor.fetchall.return_value = []

        result = accept_verification(sample_verification_row["id"])

        assert result.status == VerificationStatus.ACCEPTED
        assert result.accepted_at is not None


# =============================================================================
# DISPUTE TESTS
# =============================================================================


class TestGetDispute:
    """Tests for get_dispute."""

    def test_returns_none_when_not_found(self, mock_get_cursor):
        result = get_dispute(uuid4())
        assert result is None


class TestSubmitDispute:
    """Tests for submit_dispute."""

    def test_raises_not_found_for_missing_verification(self, mock_get_cursor, sample_contradicting_evidence):
        with pytest.raises(NotFoundError):
            submit_dispute(
                verification_id=uuid4(),
                disputer_id="did:valence:carol",
                counter_evidence=sample_contradicting_evidence,
                stake_amount=0.05,
                dispute_type=DisputeType.NEW_EVIDENCE,
                reasoning="New evidence found",
            )


# =============================================================================
# REPUTATION UPDATE TESTS
# =============================================================================


class TestApplyReputationUpdate:
    """Tests for _apply_reputation_update."""

    def test_logs_reputation_event(self, mock_get_cursor, sample_reputation_row):
        mock_get_cursor.fetchone.return_value = sample_reputation_row

        event = _apply_reputation_update(
            "did:valence:alice",
            delta=0.005,
            reason="Test reward",
        )

        assert event.delta == 0.005
        assert event.reason == "Test reward"
        calls = mock_get_cursor.execute.call_args_list
        sql_calls = [c[0][0] for c in calls]
        assert any("INSERT INTO reputation_events" in sql for sql in sql_calls)

    def test_respects_reputation_floor(self, mock_get_cursor, sample_reputation_row):
        sample_reputation_row["overall"] = 0.15
        mock_get_cursor.fetchone.return_value = sample_reputation_row

        event = _apply_reputation_update(
            "did:valence:alice",
            delta=-0.10,
            reason="Large penalty",
        )

        assert event.new_value == ReputationConstants.REPUTATION_FLOOR

    def test_respects_reputation_ceiling(self, mock_get_cursor, sample_reputation_row):
        sample_reputation_row["overall"] = 0.95
        mock_get_cursor.fetchone.return_value = sample_reputation_row

        event = _apply_reputation_update(
            "did:valence:alice",
            delta=0.10,
            reason="Large bonus",
        )

        assert event.new_value == 1.0


# =============================================================================
# STAKE RELEASE TESTS
# =============================================================================


class TestReleaseStake:
    """Tests for _release_stake."""

    def test_releases_matching_positions(self, mock_get_cursor):
        pos_id = uuid4()
        mock_get_cursor.fetchall.return_value = [{"id": pos_id, "amount": 0.02}]

        amount = _release_stake("did:valence:alice", verification_id=uuid4())

        assert amount == 0.02
        calls = mock_get_cursor.execute.call_args_list
        sql_calls = [c[0][0] for c in calls]
        assert any("UPDATE stake_positions SET status" in sql for sql in sql_calls)
        assert any("UPDATE reputations SET stake_at_risk" in sql for sql in sql_calls)

    def test_returns_zero_for_no_matching(self, mock_get_cursor):
        mock_get_cursor.fetchall.return_value = []

        amount = _release_stake("did:valence:alice", verification_id=uuid4())

        assert amount == 0.0

    def test_forfeit_sets_forfeited_status(self, mock_get_cursor):
        pos_id = uuid4()
        mock_get_cursor.fetchall.return_value = [{"id": pos_id, "amount": 0.03}]

        _release_stake("did:valence:alice", verification_id=uuid4(), forfeit=True)

        calls = mock_get_cursor.execute.call_args_list
        # Find the UPDATE call for stake_positions
        update_calls = [c for c in calls if "UPDATE stake_positions" in c[0][0]]
        assert len(update_calls) > 0
        assert "forfeited" in str(update_calls[0])


# =============================================================================
# BOUNTY TESTS
# =============================================================================


class TestGetBounty:
    """Tests for get_bounty."""

    def test_returns_none_when_not_found(self, mock_get_cursor):
        result = get_bounty(uuid4())
        assert result is None

    def test_returns_bounty_from_row(self, mock_get_cursor):
        belief_id = uuid4()
        mock_get_cursor.fetchone.return_value = {
            "belief_id": belief_id,
            "holder_id": "did:valence:alice",
            "base_amount": 0.005,
            "confidence_premium": 0.64,
            "age_factor": 1.5,
            "total_bounty": 0.0024,
            "created_at": datetime.now(),
            "expires_at": None,
            "claimed": False,
            "claimed_by": None,
            "claimed_at": None,
        }

        result = get_bounty(belief_id)

        assert result is not None
        assert result.belief_id == belief_id
        assert result.total_bounty == 0.0024
        assert result.claimed is False


class TestListBounties:
    """Tests for list_bounties."""

    def test_returns_empty_list(self, mock_get_cursor):
        result = list_bounties()
        assert result == []

    def test_filters_unclaimed_by_default(self, mock_get_cursor):
        list_bounties(unclaimed_only=True)

        calls = mock_get_cursor.execute.call_args_list
        sql = calls[0][0][0]
        assert "WHERE NOT claimed" in sql


# =============================================================================
# REPUTATION EVENTS TESTS
# =============================================================================


class TestGetReputationEvents:
    """Tests for get_reputation_events."""

    def test_returns_empty_for_no_events(self, mock_get_cursor):
        result = get_reputation_events("did:valence:alice")
        assert result == []

    def test_queries_with_identity_and_limit(self, mock_get_cursor):
        get_reputation_events("did:valence:alice", limit=10)

        calls = mock_get_cursor.execute.call_args_list
        sql = calls[0][0][0]
        assert "reputation_events" in sql
        assert "LIMIT" in sql


# =============================================================================
# VERIFICATION SUMMARY TESTS
# =============================================================================


class TestGetVerificationSummary:
    """Tests for get_verification_summary."""

    def test_empty_summary(self, mock_get_cursor):
        summary = get_verification_summary(uuid4())

        assert summary["total"] == 0
        assert summary["total_stake"] == 0
        assert summary["consensus_result"] is None
