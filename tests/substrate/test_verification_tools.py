"""Tests for verification protocol MCP tools.

Tests cover the MCP tool handler layer in valence.substrate.tools.verification,
which translates MCP calls into valence.core.verification.db operations.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from valence.substrate.tools.verification import (
    bounty_get,
    bounty_list,
    dispute_get,
    dispute_resolve,
    dispute_submit,
    reputation_events,
    reputation_get,
    verification_accept,
    verification_get,
    verification_list,
    verification_submit,
    verification_summary,
)


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
    """Mock the get_cursor context manager used by verification tools.

    Patches both the db layer and the substrate tools _common module
    since verification_submit does a direct belief lookup.
    """

    @contextmanager
    def _mock_get_cursor(dict_cursor: bool = True) -> Generator:
        yield mock_cursor

    with patch("valence.core.verification.db.get_cursor", _mock_get_cursor):
        with patch("valence.substrate.tools._common.get_cursor", _mock_get_cursor):
            yield mock_cursor


@pytest.fixture
def sample_belief_row():
    """A belief row as returned by the DB."""
    return {
        "source_id": "did:valence:alice",
        "confidence": json.dumps({"overall": 0.7}),
        "domain_path": ["tech"],
    }


@pytest.fixture
def sample_reputation_row():
    """A reputation row as returned by the DB."""
    return {
        "identity_id": "did:valence:bob",
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
    """A verification row as returned by the DB."""
    vid = uuid4()
    return {
        "id": vid,
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
def sample_dispute_row():
    """A dispute row as returned by the DB."""
    return {
        "id": uuid4(),
        "verification_id": uuid4(),
        "disputer_id": "did:valence:carol",
        "counter_evidence": json.dumps([{
            "id": str(uuid4()),
            "type": "external",
            "relevance": 0.8,
            "contribution": "contradicts",
        }]),
        "stake": json.dumps({
            "amount": 0.05,
            "type": "challenge",
            "locked_until": (datetime.now() + timedelta(days=14)).isoformat(),
            "escrow_id": str(uuid4()),
        }),
        "dispute_type": "new_evidence",
        "reasoning": "Found conflicting source",
        "proposed_result": "contradicted",
        "status": "pending",
        "outcome": None,
        "resolution_reasoning": None,
        "resolution_method": None,
        "resolved_at": None,
        "created_at": datetime.now(),
    }


# =============================================================================
# VERIFICATION SUBMIT TESTS
# =============================================================================


class TestVerificationSubmit:
    """Tests for verification_submit tool."""

    def test_invalid_belief_id(self):
        result = verification_submit(
            belief_id="not-a-uuid",
            verifier_id="did:valence:bob",
            result="confirmed",
            evidence=[{"type": "external", "relevance": 0.9, "contribution": "supports"}],
            stake_amount=0.02,
        )
        assert result["success"] is False
        assert "Invalid UUID" in result["error"]

    def test_invalid_result_enum(self):
        result = verification_submit(
            belief_id=str(uuid4()),
            verifier_id="did:valence:bob",
            result="maybe",
            evidence=[{"type": "external", "relevance": 0.9, "contribution": "supports"}],
            stake_amount=0.02,
        )
        assert result["success"] is False
        assert "Invalid result" in result["error"]

    def test_belief_not_found(self, mock_get_cursor):
        mock_get_cursor.fetchone.return_value = None

        result = verification_submit(
            belief_id=str(uuid4()),
            verifier_id="did:valence:bob",
            result="confirmed",
            evidence=[{"type": "external", "relevance": 0.9, "contribution": "supports"}],
            stake_amount=0.02,
        )
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_successful_submission(self, mock_get_cursor, sample_belief_row, sample_reputation_row):
        # fetchone calls: belief lookup, get_or_create_reputation
        mock_get_cursor.fetchone.side_effect = [sample_belief_row, sample_reputation_row]
        mock_get_cursor.fetchall.return_value = []

        result = verification_submit(
            belief_id=str(uuid4()),
            verifier_id="did:valence:bob",
            result="confirmed",
            evidence=[{"type": "external", "relevance": 0.9, "contribution": "supports"}],
            stake_amount=0.02,
        )
        assert result["success"] is True
        assert "verification" in result
        assert result["verification"]["result"] == "confirmed"
        assert result["verification"]["status"] == "pending"

    def test_self_verification_rejected(self, mock_get_cursor, sample_reputation_row):
        belief_row = {
            "source_id": "did:valence:bob",
            "confidence": json.dumps({"overall": 0.7}),
            "domain_path": ["tech"],
        }
        mock_get_cursor.fetchone.side_effect = [belief_row, sample_reputation_row]
        mock_get_cursor.fetchall.return_value = []

        result = verification_submit(
            belief_id=str(uuid4()),
            verifier_id="did:valence:bob",
            result="confirmed",
            evidence=[{"type": "external", "relevance": 0.9, "contribution": "supports"}],
            stake_amount=0.02,
        )
        assert result["success"] is False
        assert "own belief" in result["error"]


# =============================================================================
# VERIFICATION ACCEPT TESTS
# =============================================================================


class TestVerificationAccept:
    """Tests for verification_accept tool."""

    def test_invalid_uuid(self):
        result = verification_accept(verification_id="bad")
        assert result["success"] is False

    def test_not_found(self, mock_get_cursor):
        result = verification_accept(verification_id=str(uuid4()))
        assert result["success"] is False
        assert "not found" in result["error"].lower() or "Verification" in result["error"]

    def test_not_pending(self, mock_get_cursor, sample_verification_row):
        sample_verification_row["status"] = "accepted"
        mock_get_cursor.fetchone.return_value = sample_verification_row

        result = verification_accept(verification_id=str(sample_verification_row["id"]))
        assert result["success"] is False
        assert "not pending" in result["error"]


# =============================================================================
# VERIFICATION GET TESTS
# =============================================================================


class TestVerificationGet:
    """Tests for verification_get tool."""

    def test_invalid_uuid(self):
        result = verification_get(verification_id="xyz")
        assert result["success"] is False

    def test_not_found(self, mock_get_cursor):
        result = verification_get(verification_id=str(uuid4()))
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_returns_verification(self, mock_get_cursor, sample_verification_row):
        mock_get_cursor.fetchone.return_value = sample_verification_row

        result = verification_get(verification_id=str(sample_verification_row["id"]))
        assert result["success"] is True
        assert result["verification"]["verifier_id"] == "did:valence:bob"
        assert result["verification"]["result"] == "confirmed"


# =============================================================================
# VERIFICATION LIST TESTS
# =============================================================================


class TestVerificationList:
    """Tests for verification_list tool."""

    def test_invalid_belief_id(self):
        result = verification_list(belief_id="nope")
        assert result["success"] is False

    def test_empty_list(self, mock_get_cursor):
        result = verification_list(belief_id=str(uuid4()))
        assert result["success"] is True
        assert result["total"] == 0

    def test_returns_verifications(self, mock_get_cursor, sample_verification_row):
        mock_get_cursor.fetchall.return_value = [sample_verification_row]

        result = verification_list(belief_id=str(sample_verification_row["belief_id"]))
        assert result["success"] is True
        assert result["total"] == 1
        assert result["verifications"][0]["result"] == "confirmed"


# =============================================================================
# VERIFICATION SUMMARY TESTS
# =============================================================================


class TestVerificationSummary:
    """Tests for verification_summary tool."""

    def test_invalid_uuid(self):
        result = verification_summary(belief_id="bad-uuid")
        assert result["success"] is False

    def test_empty_summary(self, mock_get_cursor):
        result = verification_summary(belief_id=str(uuid4()))
        assert result["success"] is True
        assert result["total"] == 0
        assert result["consensus_result"] is None


# =============================================================================
# DISPUTE SUBMIT TESTS
# =============================================================================


class TestDisputeSubmit:
    """Tests for dispute_submit tool."""

    def test_invalid_verification_id(self):
        result = dispute_submit(
            verification_id="bad",
            disputer_id="did:valence:carol",
            counter_evidence=[{"type": "external", "relevance": 0.8, "contribution": "contradicts"}],
            stake_amount=0.05,
            dispute_type="new_evidence",
            reasoning="Found conflicting source",
        )
        assert result["success"] is False

    def test_invalid_dispute_type(self):
        result = dispute_submit(
            verification_id=str(uuid4()),
            disputer_id="did:valence:carol",
            counter_evidence=[{"type": "external", "relevance": 0.8, "contribution": "contradicts"}],
            stake_amount=0.05,
            dispute_type="invalid_type",
            reasoning="Found conflicting source",
        )
        assert result["success"] is False
        assert "Invalid dispute_type" in result["error"]

    def test_verification_not_found(self, mock_get_cursor):
        result = dispute_submit(
            verification_id=str(uuid4()),
            disputer_id="did:valence:carol",
            counter_evidence=[{"type": "external", "relevance": 0.8, "contribution": "contradicts"}],
            stake_amount=0.05,
            dispute_type="new_evidence",
            reasoning="Found conflicting source",
        )
        assert result["success"] is False


# =============================================================================
# DISPUTE RESOLVE TESTS
# =============================================================================


class TestDisputeResolve:
    """Tests for dispute_resolve tool."""

    def test_invalid_uuid(self):
        result = dispute_resolve(dispute_id="bad", outcome="upheld", resolution_reasoning="Fair")
        assert result["success"] is False

    def test_invalid_outcome(self):
        result = dispute_resolve(dispute_id=str(uuid4()), outcome="invalid", resolution_reasoning="Fair")
        assert result["success"] is False
        assert "Invalid outcome" in result["error"]

    def test_dispute_not_found(self, mock_get_cursor):
        result = dispute_resolve(dispute_id=str(uuid4()), outcome="upheld", resolution_reasoning="Fair")
        assert result["success"] is False


# =============================================================================
# DISPUTE GET TESTS
# =============================================================================


class TestDisputeGet:
    """Tests for dispute_get tool."""

    def test_invalid_uuid(self):
        result = dispute_get(dispute_id="nope")
        assert result["success"] is False

    def test_not_found(self, mock_get_cursor):
        result = dispute_get(dispute_id=str(uuid4()))
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_returns_dispute(self, mock_get_cursor, sample_dispute_row):
        mock_get_cursor.fetchone.return_value = sample_dispute_row

        result = dispute_get(dispute_id=str(sample_dispute_row["id"]))
        assert result["success"] is True
        assert result["dispute"]["disputer_id"] == "did:valence:carol"
        assert result["dispute"]["dispute_type"] == "new_evidence"


# =============================================================================
# REPUTATION GET TESTS
# =============================================================================


class TestReputationGet:
    """Tests for reputation_get tool."""

    def test_not_found(self, mock_get_cursor):
        result = reputation_get(identity_id="did:valence:unknown")
        assert result["success"] is False
        assert "No reputation found" in result["error"]

    def test_returns_reputation(self, mock_get_cursor, sample_reputation_row):
        mock_get_cursor.fetchone.return_value = sample_reputation_row

        result = reputation_get(identity_id="did:valence:bob")
        assert result["success"] is True
        assert result["reputation"]["identity_id"] == "did:valence:bob"
        assert result["reputation"]["overall"] == 0.5


# =============================================================================
# REPUTATION EVENTS TESTS
# =============================================================================


class TestReputationEvents:
    """Tests for reputation_events tool."""

    def test_empty_events(self, mock_get_cursor):
        result = reputation_events(identity_id="did:valence:bob")
        assert result["success"] is True
        assert result["total"] == 0

    def test_with_limit(self, mock_get_cursor):
        result = reputation_events(identity_id="did:valence:bob", limit=10)
        assert result["success"] is True


# =============================================================================
# BOUNTY GET TESTS
# =============================================================================


class TestBountyGet:
    """Tests for bounty_get tool."""

    def test_invalid_uuid(self):
        result = bounty_get(belief_id="bad")
        assert result["success"] is False

    def test_not_found(self, mock_get_cursor):
        result = bounty_get(belief_id=str(uuid4()))
        assert result["success"] is False
        assert "No bounty found" in result["error"]

    def test_returns_bounty(self, mock_get_cursor):
        bid = uuid4()
        mock_get_cursor.fetchone.return_value = {
            "belief_id": bid,
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

        result = bounty_get(belief_id=str(bid))
        assert result["success"] is True
        assert result["bounty"]["total_bounty"] == 0.0024
        assert result["bounty"]["claimed"] is False


# =============================================================================
# BOUNTY LIST TESTS
# =============================================================================


class TestBountyList:
    """Tests for bounty_list tool."""

    def test_empty_list(self, mock_get_cursor):
        result = bounty_list()
        assert result["success"] is True
        assert result["total"] == 0

    def test_with_params(self, mock_get_cursor):
        result = bounty_list(unclaimed_only=False, limit=5)
        assert result["success"] is True
