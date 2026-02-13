"""Tests for consensus MCP tool handlers."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from valence.core.consensus import (
    BeliefConsensusStatus,
    Challenge,
    ChallengeStatus,
    Corroboration,
    FinalityLevel,
    IndependenceScore,
    TrustLayer,
)
from valence.core.exceptions import NotFoundError, ValidationException
from valence.substrate.tools.consensus import (
    challenge_get,
    challenge_resolve,
    challenge_submit,
    challenges_list,
    consensus_status,
    corroboration_list,
    corroboration_submit,
)


# =============================================================================
# UUID VALIDATION TESTS
# =============================================================================


class TestUUIDValidation:
    """Tests for UUID parsing in all handlers."""

    def test_consensus_status_invalid_uuid(self):
        result = consensus_status(belief_id="not-valid")
        assert result["success"] is False
        assert "Invalid UUID" in result["error"]

    def test_corroboration_submit_invalid_primary(self):
        result = corroboration_submit(
            primary_belief_id="bad", corroborating_belief_id=str(uuid4()),
            primary_holder="a", corroborator="b", semantic_similarity=0.9,
        )
        assert result["success"] is False

    def test_corroboration_submit_invalid_corroborating(self):
        result = corroboration_submit(
            primary_belief_id=str(uuid4()), corroborating_belief_id="bad",
            primary_holder="a", corroborator="b", semantic_similarity=0.9,
        )
        assert result["success"] is False

    def test_corroboration_list_invalid_uuid(self):
        result = corroboration_list(belief_id="bad")
        assert result["success"] is False

    def test_challenge_submit_invalid_uuid(self):
        result = challenge_submit(belief_id="bad", challenger_id="x", reasoning="test")
        assert result["success"] is False

    def test_challenge_resolve_invalid_uuid(self):
        result = challenge_resolve(challenge_id="bad", upheld=True, resolution_reasoning="test")
        assert result["success"] is False

    def test_challenge_get_invalid_uuid(self):
        result = challenge_get(challenge_id="bad")
        assert result["success"] is False

    def test_challenges_list_invalid_uuid(self):
        result = challenges_list(belief_id="bad")
        assert result["success"] is False


# =============================================================================
# CONSENSUS STATUS TESTS
# =============================================================================


class TestConsensusStatus:
    """Tests for consensus_status tool handler."""

    def test_no_status(self):
        with patch("valence.substrate.tools.consensus.db_get_consensus_status", return_value=None):
            result = consensus_status(belief_id=str(uuid4()))
        assert result["success"] is True
        assert result["status"] is None
        assert "L1" in result["message"]

    def test_with_status(self):
        bid = uuid4()
        now = datetime.now()
        status = BeliefConsensusStatus(
            belief_id=bid, current_layer=TrustLayer.L2_FEDERATED,
            corroboration_count=3, total_corroboration_weight=2.5,
            finality=FinalityLevel.PROVISIONAL, elevated_at=now,
        )
        with patch("valence.substrate.tools.consensus.db_get_consensus_status", return_value=status):
            result = consensus_status(belief_id=str(bid))
        assert result["success"] is True
        assert result["status"]["current_layer"] == "l2_federated"
        assert result["status"]["corroboration_count"] == 3
        assert result["status"]["finality"] == "provisional"
        assert result["status"]["elevated_at"] == now.isoformat()


# =============================================================================
# CORROBORATION SUBMIT TESTS
# =============================================================================


class TestCorroborationSubmit:
    """Tests for corroboration_submit tool handler."""

    def test_successful_submit(self):
        corr = Corroboration(
            id=uuid4(), primary_belief_id=uuid4(), corroborating_belief_id=uuid4(),
            primary_holder="alice", corroborator="bob", semantic_similarity=0.9,
            independence=IndependenceScore(source=1.0, evidential=1.0, method=1.0, temporal=1.0),
            effective_weight=0.85,
        )
        with patch("valence.substrate.tools.consensus.db_submit_corroboration", return_value=corr):
            result = corroboration_submit(
                primary_belief_id=str(uuid4()), corroborating_belief_id=str(uuid4()),
                primary_holder="alice", corroborator="bob", semantic_similarity=0.9,
            )
        assert result["success"] is True
        assert "corroboration" in result
        assert result["corroboration"]["effective_weight"] == 0.85

    def test_validation_error(self):
        with patch("valence.substrate.tools.consensus.db_submit_corroboration", side_effect=ValidationException("Similarity too low")):
            result = corroboration_submit(
                primary_belief_id=str(uuid4()), corroborating_belief_id=str(uuid4()),
                primary_holder="alice", corroborator="bob", semantic_similarity=0.5,
            )
        assert result["success"] is False
        assert "Similarity" in result["error"]

    def test_with_evidence_sources(self):
        corr = Corroboration(
            id=uuid4(), primary_belief_id=uuid4(), corroborating_belief_id=uuid4(),
            primary_holder="a", corroborator="b", semantic_similarity=0.95,
            independence=IndependenceScore(source=0.5, evidential=0.5, method=1.0, temporal=1.0),
            effective_weight=0.7,
        )
        with patch("valence.substrate.tools.consensus.db_submit_corroboration", return_value=corr):
            result = corroboration_submit(
                primary_belief_id=str(uuid4()), corroborating_belief_id=str(uuid4()),
                primary_holder="a", corroborator="b", semantic_similarity=0.95,
                evidence_sources_a=["wiki"], evidence_sources_b=["wiki", "paper"],
                method_a="observation", method_b="experiment",
            )
        assert result["success"] is True


# =============================================================================
# CORROBORATION LIST TESTS
# =============================================================================


class TestCorroborationList:
    """Tests for corroboration_list tool handler."""

    def test_empty_list(self):
        with patch("valence.substrate.tools.consensus.db_get_corroborations", return_value=[]):
            result = corroboration_list(belief_id=str(uuid4()))
        assert result["success"] is True
        assert result["corroborations"] == []
        assert result["total"] == 0

    def test_with_corroborations(self):
        now = datetime.now()
        corrs = [
            Corroboration(
                id=uuid4(), primary_belief_id=uuid4(), corroborating_belief_id=uuid4(),
                primary_holder="a", corroborator="b", semantic_similarity=0.9,
                independence=IndependenceScore(source=1.0, evidential=1.0, method=1.0, temporal=1.0),
                effective_weight=0.85, created_at=now,
            ),
        ]
        with patch("valence.substrate.tools.consensus.db_get_corroborations", return_value=corrs):
            result = corroboration_list(belief_id=str(uuid4()))
        assert result["total"] == 1
        c = result["corroborations"][0]
        assert c["semantic_similarity"] == 0.9
        assert c["effective_weight"] == 0.85


# =============================================================================
# CHALLENGE SUBMIT TESTS
# =============================================================================


class TestChallengeSubmit:
    """Tests for challenge_submit tool handler."""

    def test_successful_submit(self):
        now = datetime.now()
        challenge = Challenge(
            id=uuid4(), belief_id=uuid4(), challenger_id="bob",
            target_layer=TrustLayer.L2_FEDERATED, reasoning="Incorrect claim",
            status=ChallengeStatus.PENDING, created_at=now,
        )
        with patch("valence.substrate.tools.consensus.db_submit_challenge", return_value=challenge):
            result = challenge_submit(
                belief_id=str(uuid4()), challenger_id="bob", reasoning="Incorrect claim",
            )
        assert result["success"] is True
        assert result["challenge"]["status"] == "pending"

    def test_not_found_error(self):
        with patch("valence.substrate.tools.consensus.db_submit_challenge", side_effect=NotFoundError("BeliefConsensus", "x")):
            result = challenge_submit(
                belief_id=str(uuid4()), challenger_id="bob", reasoning="test",
            )
        assert result["success"] is False

    def test_validation_error(self):
        with patch("valence.substrate.tools.consensus.db_submit_challenge", side_effect=ValidationException("Cannot challenge")):
            result = challenge_submit(
                belief_id=str(uuid4()), challenger_id="bob", reasoning="test",
            )
        assert result["success"] is False


# =============================================================================
# CHALLENGE RESOLVE TESTS
# =============================================================================


class TestChallengeResolve:
    """Tests for challenge_resolve tool handler."""

    def test_upheld(self):
        now = datetime.now()
        challenge = Challenge(
            id=uuid4(), belief_id=uuid4(), challenger_id="bob",
            target_layer=TrustLayer.L2_FEDERATED, reasoning="bad",
            status=ChallengeStatus.UPHELD, resolved_at=now,
        )
        with patch("valence.substrate.tools.consensus.db_resolve_challenge", return_value=challenge):
            result = challenge_resolve(
                challenge_id=str(uuid4()), upheld=True, resolution_reasoning="Evidence supports",
            )
        assert result["success"] is True
        assert result["challenge"]["status"] == "upheld"

    def test_rejected(self):
        now = datetime.now()
        challenge = Challenge(
            id=uuid4(), belief_id=uuid4(), challenger_id="bob",
            target_layer=TrustLayer.L2_FEDERATED, reasoning="bad",
            status=ChallengeStatus.REJECTED, resolved_at=now,
        )
        with patch("valence.substrate.tools.consensus.db_resolve_challenge", return_value=challenge):
            result = challenge_resolve(
                challenge_id=str(uuid4()), upheld=False, resolution_reasoning="No evidence",
            )
        assert result["success"] is True
        assert result["challenge"]["status"] == "rejected"

    def test_not_found(self):
        with patch("valence.substrate.tools.consensus.db_resolve_challenge", side_effect=NotFoundError("Challenge", "x")):
            result = challenge_resolve(challenge_id=str(uuid4()), upheld=True, resolution_reasoning="test")
        assert result["success"] is False


# =============================================================================
# CHALLENGE GET TESTS
# =============================================================================


class TestChallengeGet:
    """Tests for challenge_get tool handler."""

    def test_not_found(self):
        with patch("valence.substrate.tools.consensus.db_get_challenge", return_value=None):
            result = challenge_get(challenge_id=str(uuid4()))
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_found(self):
        now = datetime.now()
        ch = Challenge(
            id=uuid4(), belief_id=uuid4(), challenger_id="bob",
            target_layer=TrustLayer.L3_DOMAIN, reasoning="Bad data",
            status=ChallengeStatus.PENDING, stake_amount=0.05,
            created_at=now,
        )
        with patch("valence.substrate.tools.consensus.db_get_challenge", return_value=ch):
            result = challenge_get(challenge_id=str(ch.id))
        assert result["success"] is True
        assert result["challenge"]["challenger_id"] == "bob"
        assert result["challenge"]["target_layer"] == "l3_domain"
        assert result["challenge"]["stake_amount"] == 0.05


# =============================================================================
# CHALLENGES LIST TESTS
# =============================================================================


class TestChallengesList:
    """Tests for challenges_list tool handler."""

    def test_empty_list(self):
        with patch("valence.substrate.tools.consensus.db_get_challenges", return_value=[]):
            result = challenges_list(belief_id=str(uuid4()))
        assert result["success"] is True
        assert result["challenges"] == []
        assert result["total"] == 0

    def test_with_challenges(self):
        now = datetime.now()
        chs = [
            Challenge(
                id=uuid4(), belief_id=uuid4(), challenger_id="bob",
                target_layer=TrustLayer.L2_FEDERATED, reasoning="wrong",
                status=ChallengeStatus.PENDING, stake_amount=0.1, created_at=now,
            ),
            Challenge(
                id=uuid4(), belief_id=uuid4(), challenger_id="carol",
                target_layer=TrustLayer.L2_FEDERATED, reasoning="outdated",
                status=ChallengeStatus.UPHELD, stake_amount=0.0, created_at=now,
            ),
        ]
        with patch("valence.substrate.tools.consensus.db_get_challenges", return_value=chs):
            result = challenges_list(belief_id=str(uuid4()))
        assert result["total"] == 2
        assert result["challenges"][0]["challenger_id"] == "bob"
        assert result["challenges"][1]["status"] == "upheld"
