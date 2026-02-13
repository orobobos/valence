"""Tests for valence.core.consensus — layer elevation, corroboration, challenges.

Tests cover:
- Independence score calculation
- Corroboration submission and validation
- Elevation logic
- Challenge submission and resolution
- Finality computation
"""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from valence.core.consensus import (
    BeliefConsensusStatus,
    Challenge,
    ChallengeStatus,
    Corroboration,
    FinalityLevel,
    IndependenceScore,
    TrustLayer,
    _compute_finality,
    _next_layer,
    _prev_layer,
    calculate_independence,
    get_challenge,
    get_challenges_for_belief,
    get_consensus_status,
    get_corroborations,
    get_or_create_consensus_status,
    resolve_challenge,
    submit_challenge,
    submit_corroboration,
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

    with patch("valence.core.consensus._core.get_cursor", _mock_get_cursor):
        yield mock_cursor


# =============================================================================
# INDEPENDENCE TESTS
# =============================================================================


class TestCalculateIndependence:
    """Tests for calculate_independence."""

    def test_identical_sources(self):
        score = calculate_independence(["src1", "src2"], ["src1", "src2"])
        assert score.evidential == 0.0
        assert score.overall < 0.5

    def test_completely_different_sources(self):
        score = calculate_independence(["src1", "src2"], ["src3", "src4"])
        assert score.evidential == 1.0
        assert score.overall > 0.5

    def test_partial_overlap(self):
        score = calculate_independence(["src1", "src2", "src3"], ["src2", "src4"])
        assert 0.0 < score.evidential < 1.0

    def test_different_methods(self):
        score = calculate_independence(["src1"], ["src2"], "observation", "derivation")
        assert score.method == 1.0

    def test_same_methods(self):
        score = calculate_independence(["src1"], ["src2"], "observation", "observation")
        assert score.method == 0.0

    def test_temporal_distance(self):
        score_near = calculate_independence(["src1"], ["src2"], time_gap_days=1)
        score_far = calculate_independence(["src1"], ["src2"], time_gap_days=14)
        assert score_far.temporal > score_near.temporal
        assert score_far.temporal == 1.0

    def test_empty_sources(self):
        score = calculate_independence([], [])
        assert score.evidential == 0.5  # No evidence to compare


# =============================================================================
# LAYER NAVIGATION TESTS
# =============================================================================


class TestLayerNavigation:
    """Tests for _next_layer and _prev_layer."""

    def test_next_from_l1(self):
        assert _next_layer(TrustLayer.L1_PERSONAL) == TrustLayer.L2_FEDERATED

    def test_next_from_l3(self):
        assert _next_layer(TrustLayer.L3_DOMAIN) == TrustLayer.L4_COMMUNAL

    def test_next_from_l4(self):
        assert _next_layer(TrustLayer.L4_COMMUNAL) is None

    def test_prev_from_l4(self):
        assert _prev_layer(TrustLayer.L4_COMMUNAL) == TrustLayer.L3_DOMAIN

    def test_prev_from_l1(self):
        assert _prev_layer(TrustLayer.L1_PERSONAL) is None


# =============================================================================
# FINALITY TESTS
# =============================================================================


class TestComputeFinality:
    """Tests for _compute_finality."""

    def test_l1_is_tentative(self):
        assert _compute_finality(TrustLayer.L1_PERSONAL, None) == FinalityLevel.TENTATIVE

    def test_l2_is_provisional(self):
        assert _compute_finality(TrustLayer.L2_FEDERATED, None) == FinalityLevel.PROVISIONAL

    def test_l3_established_without_recent_challenge(self):
        assert _compute_finality(TrustLayer.L3_DOMAIN, None) == FinalityLevel.ESTABLISHED

    def test_l3_provisional_with_recent_challenge(self):
        recent = datetime.now() - timedelta(days=15)
        assert _compute_finality(TrustLayer.L3_DOMAIN, recent) == FinalityLevel.PROVISIONAL

    def test_l4_settled_without_recent_challenge(self):
        assert _compute_finality(TrustLayer.L4_COMMUNAL, None) == FinalityLevel.SETTLED

    def test_l4_established_with_recent_challenge(self):
        recent = datetime.now() - timedelta(days=30)
        assert _compute_finality(TrustLayer.L4_COMMUNAL, recent) == FinalityLevel.ESTABLISHED


# =============================================================================
# CONSENSUS STATUS TESTS
# =============================================================================


class TestConsensusStatus:
    """Tests for consensus status operations."""

    def test_get_returns_none_when_missing(self, mock_get_cursor):
        result = get_consensus_status(uuid4())
        assert result is None

    def test_get_returns_status(self, mock_get_cursor):
        bid = uuid4()
        mock_get_cursor.fetchone.return_value = {
            "belief_id": bid,
            "current_layer": "l2_federated",
            "corroboration_count": 5,
            "total_corroboration_weight": 2.5,
            "finality": "provisional",
            "last_challenge_at": None,
            "elevated_at": datetime.now(),
            "created_at": datetime.now(),
        }
        result = get_consensus_status(bid)
        assert result is not None
        assert result.current_layer == TrustLayer.L2_FEDERATED
        assert result.corroboration_count == 5

    def test_get_or_create_creates_when_missing(self, mock_get_cursor):
        result = get_or_create_consensus_status(uuid4())
        assert result.current_layer == TrustLayer.L1_PERSONAL
        calls = mock_get_cursor.execute.call_args_list
        sql_calls = [c[0][0] for c in calls]
        assert any("INSERT INTO belief_consensus_status" in sql for sql in sql_calls)


# =============================================================================
# CORROBORATION TESTS
# =============================================================================


class TestSubmitCorroboration:
    """Tests for submit_corroboration."""

    def test_rejects_low_similarity(self, mock_get_cursor):
        with pytest.raises(ValidationException, match="Semantic similarity too low"):
            submit_corroboration(
                primary_belief_id=uuid4(),
                corroborating_belief_id=uuid4(),
                primary_holder="did:valence:alice",
                corroborator="did:valence:bob",
                semantic_similarity=0.5,
                independence=IndependenceScore(overall=0.8),
            )

    def test_rejects_self_corroboration(self, mock_get_cursor):
        with pytest.raises(ValidationException, match="self-corroborate"):
            submit_corroboration(
                primary_belief_id=uuid4(),
                corroborating_belief_id=uuid4(),
                primary_holder="did:valence:alice",
                corroborator="did:valence:alice",
                semantic_similarity=0.9,
                independence=IndependenceScore(overall=0.8),
            )

    def test_rejects_same_belief(self, mock_get_cursor):
        bid = uuid4()
        with pytest.raises(ValidationException, match="itself"):
            submit_corroboration(
                primary_belief_id=bid,
                corroborating_belief_id=bid,
                primary_holder="did:valence:alice",
                corroborator="did:valence:bob",
                semantic_similarity=0.9,
                independence=IndependenceScore(overall=0.8),
            )

    def test_successful_submission(self, mock_get_cursor):
        # Setup: consensus status exists and won't elevate
        mock_get_cursor.fetchone.side_effect = [
            None,  # get_consensus_status for _check_elevation
            None,  # get_or_create_consensus_status inner select
        ]
        mock_get_cursor.fetchall.return_value = []  # get_corroborations

        corr = submit_corroboration(
            primary_belief_id=uuid4(),
            corroborating_belief_id=uuid4(),
            primary_holder="did:valence:alice",
            corroborator="did:valence:bob",
            semantic_similarity=0.9,
            independence=IndependenceScore(overall=0.7),
            corroborator_reputation=0.8,
        )
        assert corr.effective_weight == 0.7 * 0.8
        calls = mock_get_cursor.execute.call_args_list
        sql_calls = [c[0][0] for c in calls]
        assert any("INSERT INTO corroborations" in sql for sql in sql_calls)


class TestGetCorroborations:
    """Tests for get_corroborations."""

    def test_empty_list(self, mock_get_cursor):
        result = get_corroborations(uuid4())
        assert result == []


# =============================================================================
# CHALLENGE TESTS
# =============================================================================


class TestSubmitChallenge:
    """Tests for submit_challenge."""

    def test_raises_not_found(self, mock_get_cursor):
        with pytest.raises(NotFoundError):
            submit_challenge(uuid4(), "did:valence:carol", "Evidence contradicts this")

    def test_rejects_l1_challenge(self, mock_get_cursor):
        bid = uuid4()
        mock_get_cursor.fetchone.return_value = {
            "belief_id": bid,
            "current_layer": "l1_personal",
            "corroboration_count": 0,
            "total_corroboration_weight": 0.0,
            "finality": "tentative",
            "last_challenge_at": None,
            "elevated_at": None,
            "created_at": datetime.now(),
        }
        with pytest.raises(ValidationException, match="L1"):
            submit_challenge(bid, "did:valence:carol", "Challenge reason")

    def test_successful_submission(self, mock_get_cursor):
        bid = uuid4()
        mock_get_cursor.fetchone.return_value = {
            "belief_id": bid,
            "current_layer": "l2_federated",
            "corroboration_count": 5,
            "total_corroboration_weight": 2.5,
            "finality": "provisional",
            "last_challenge_at": None,
            "elevated_at": datetime.now(),
            "created_at": datetime.now(),
        }
        challenge = submit_challenge(bid, "did:valence:carol", "New evidence found")
        assert challenge.status == ChallengeStatus.PENDING
        assert challenge.target_layer == TrustLayer.L2_FEDERATED


class TestResolveChallenge:
    """Tests for resolve_challenge."""

    def test_not_found(self, mock_get_cursor):
        with pytest.raises(NotFoundError):
            resolve_challenge(uuid4(), upheld=True, resolution_reasoning="Valid")

    def test_not_pending(self, mock_get_cursor):
        mock_get_cursor.fetchone.return_value = {
            "id": uuid4(),
            "belief_id": uuid4(),
            "challenger_id": "did:valence:carol",
            "target_layer": "l2_federated",
            "reasoning": "Test",
            "evidence": "[]",
            "stake_amount": 0.0,
            "status": "upheld",
            "resolution_reasoning": "Already resolved",
            "created_at": datetime.now(),
            "resolved_at": datetime.now(),
        }
        with pytest.raises(ValidationException, match="not pending"):
            resolve_challenge(uuid4(), upheld=True, resolution_reasoning="Valid")

    def test_upheld_challenge(self, mock_get_cursor):
        cid = uuid4()
        bid = uuid4()
        mock_get_cursor.fetchone.return_value = {
            "id": cid,
            "belief_id": bid,
            "challenger_id": "did:valence:carol",
            "target_layer": "l2_federated",
            "reasoning": "Counter evidence",
            "evidence": "[]",
            "stake_amount": 0.05,
            "status": "pending",
            "resolution_reasoning": None,
            "created_at": datetime.now(),
            "resolved_at": None,
        }
        result = resolve_challenge(cid, upheld=True, resolution_reasoning="Challenge is valid")
        assert result.status == ChallengeStatus.UPHELD
        # Should demote — check for UPDATE on belief_consensus_status
        calls = mock_get_cursor.execute.call_args_list
        sql_calls = [c[0][0] for c in calls]
        assert any("UPDATE belief_consensus_status" in sql for sql in sql_calls)

    def test_rejected_challenge(self, mock_get_cursor):
        cid = uuid4()
        mock_get_cursor.fetchone.return_value = {
            "id": cid,
            "belief_id": uuid4(),
            "challenger_id": "did:valence:carol",
            "target_layer": "l3_domain",
            "reasoning": "Weak evidence",
            "evidence": "[]",
            "stake_amount": 0.05,
            "status": "pending",
            "resolution_reasoning": None,
            "created_at": datetime.now(),
            "resolved_at": None,
        }
        result = resolve_challenge(cid, upheld=False, resolution_reasoning="Evidence insufficient")
        assert result.status == ChallengeStatus.REJECTED


class TestGetChallenge:
    """Tests for get_challenge."""

    def test_not_found(self, mock_get_cursor):
        result = get_challenge(uuid4())
        assert result is None


class TestGetChallengesForBelief:
    """Tests for get_challenges_for_belief."""

    def test_empty_list(self, mock_get_cursor):
        result = get_challenges_for_belief(uuid4())
        assert result == []
