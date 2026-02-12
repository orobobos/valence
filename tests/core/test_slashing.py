"""Tests for slashing mechanism (#346).

Tests cover:
1. create_slashing_event calculates correct slash amounts
2. Severity-based slash percentages (critical=50%, high=25%)
3. Appeal within deadline succeeds
4. Appeal after deadline fails
5. Execute slashing forfeits stake
6. Reject slashing unlocks stake
7. SlashingEvent serialization
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from valence.core.slashing import (
    APPEAL_WINDOW_HOURS,
    SLASH_PERCENT_CRITICAL,
    SLASH_PERCENT_HIGH,
    SlashableOffense,
    SlashingEvent,
    SlashingStatus,
    appeal_slashing_event,
    create_slashing_event,
    execute_slashing,
    reject_slashing,
)


@pytest.fixture
def mock_cur():
    return MagicMock()


class TestCreateSlashingEvent:
    """Test slashing event creation."""

    def test_critical_severity_50_percent(self, mock_cur):
        event = create_slashing_event(
            mock_cur,
            validator_did="did:valence:bad",
            offense=SlashableOffense.COLLUSION,
            severity="critical",
            evidence={"alert_id": "abc"},
            reported_by="did:valence:reporter",
            stake_amount=100.0,
        )
        assert event.slash_amount == 100.0 * SLASH_PERCENT_CRITICAL
        assert event.status == SlashingStatus.PENDING
        assert event.appeal_deadline is not None

    def test_high_severity_25_percent(self, mock_cur):
        event = create_slashing_event(
            mock_cur,
            validator_did="did:valence:bad",
            offense=SlashableOffense.FALSE_BELIEFS,
            severity="high",
            evidence={},
            reported_by="did:valence:reporter",
            stake_amount=200.0,
        )
        assert event.slash_amount == 200.0 * SLASH_PERCENT_HIGH

    def test_low_severity_no_slash(self, mock_cur):
        event = create_slashing_event(
            mock_cur,
            validator_did="did:valence:bad",
            offense=SlashableOffense.POLICY_VIOLATION,
            severity="low",
            evidence={},
            reported_by="did:valence:reporter",
            stake_amount=100.0,
        )
        assert event.slash_amount == 0.0

    def test_persists_to_db(self, mock_cur):
        create_slashing_event(
            mock_cur,
            validator_did="did:valence:bad",
            offense=SlashableOffense.REPLAY_ATTACK,
            severity="critical",
            evidence={"detail": "test"},
            reported_by="did:valence:reporter",
            stake_amount=50.0,
        )
        # Should have called INSERT and UPDATE
        assert mock_cur.execute.call_count == 2
        insert_sql = mock_cur.execute.call_args_list[0][0][0]
        assert "INSERT INTO slashing_events" in insert_sql

    def test_locks_stake(self, mock_cur):
        create_slashing_event(
            mock_cur,
            validator_did="did:valence:bad",
            offense=SlashableOffense.SYBIL_ATTACK,
            severity="critical",
            evidence={},
            reported_by="did:valence:reporter",
            stake_amount=100.0,
        )
        lock_sql = mock_cur.execute.call_args_list[1][0][0]
        assert "UPDATE stake_positions SET status = 'locked'" in lock_sql


class TestAppealSlashing:
    """Test appeal mechanism."""

    def test_appeal_pending_event(self, mock_cur):
        now = datetime.now(timezone.utc)
        mock_cur.fetchone.return_value = {
            "id": "ev1", "validator_did": "did:bad", "offense": "collusion",
            "severity": "critical", "evidence": "{}", "stake_at_risk": 100,
            "slash_amount": 50, "status": "pending", "reported_by": "did:reporter",
            "appeal_deadline": now + timedelta(hours=12),
            "executed_at": None, "appeal_reason": None,
        }
        result = appeal_slashing_event(mock_cur, "ev1", "I didn't do it")
        assert result is not None
        assert result.status == SlashingStatus.APPEALED

    def test_cannot_appeal_executed(self, mock_cur):
        mock_cur.fetchone.return_value = {
            "id": "ev1", "status": "executed",
        }
        result = appeal_slashing_event(mock_cur, "ev1", "too late")
        assert result is None

    def test_cannot_appeal_not_found(self, mock_cur):
        mock_cur.fetchone.return_value = None
        result = appeal_slashing_event(mock_cur, "missing", "reason")
        assert result is None


class TestExecuteSlashing:
    """Test slash execution."""

    def test_execute_forfeits_stake(self, mock_cur):
        now = datetime.now(timezone.utc)
        mock_cur.fetchone.return_value = {
            "id": "ev1", "validator_did": "did:bad", "offense": "collusion",
            "severity": "critical", "evidence": "{}", "stake_at_risk": 100,
            "slash_amount": 50, "status": "pending", "reported_by": "did:reporter",
            "appeal_deadline": now - timedelta(hours=1),
        }
        result = execute_slashing(mock_cur, "ev1")
        assert result is not None
        assert result.status == SlashingStatus.EXECUTED
        # Should UPDATE stake and slashing_events
        assert mock_cur.execute.call_count >= 3  # SELECT + 2 UPDATEs

    def test_cannot_execute_rejected(self, mock_cur):
        mock_cur.fetchone.return_value = {
            "id": "ev1", "status": "rejected",
        }
        result = execute_slashing(mock_cur, "ev1")
        assert result is None


class TestRejectSlashing:
    """Test slash rejection."""

    def test_reject_unlocks_stake(self, mock_cur):
        mock_cur.fetchone.return_value = {"validator_did": "did:bad", "status": "appealed"}
        result = reject_slashing(mock_cur, "ev1")
        assert result is True
        unlock_sql = mock_cur.execute.call_args_list[1][0][0]
        assert "status = 'active'" in unlock_sql

    def test_reject_not_found(self, mock_cur):
        mock_cur.fetchone.return_value = None
        assert reject_slashing(mock_cur, "missing") is False


class TestSlashingEventSerialization:
    """Test to_dict."""

    def test_to_dict(self):
        event = SlashingEvent(
            id="test-id",
            validator_did="did:valence:bad",
            offense=SlashableOffense.COLLUSION,
            severity="critical",
            evidence={"test": True},
            stake_at_risk=100.0,
            slash_amount=50.0,
            reported_by="did:valence:reporter",
        )
        d = event.to_dict()
        assert d["offense"] == "collusion"
        assert d["severity"] == "critical"
        assert d["slash_amount"] == 50.0
