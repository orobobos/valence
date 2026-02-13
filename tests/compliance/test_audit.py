"""Tests for AuditLogger — log and query operations.

Tests: log entry creation, query filtering, error resilience.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from valence.compliance.audit import AuditAction, AuditEntry, AuditLogger, get_audit_logger


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

    with patch("valence.compliance.audit.get_cursor", _mock_get_cursor):
        yield mock_cursor


@pytest.fixture
def audit_logger():
    """Fresh AuditLogger instance."""
    return AuditLogger()


# =============================================================================
# AuditEntry TESTS
# =============================================================================


class TestAuditEntry:
    """Tests for AuditEntry dataclass."""

    def test_to_dict(self):
        """to_dict should include all fields."""
        entry_id = uuid4()
        now = datetime.now()
        entry = AuditEntry(
            id=entry_id,
            timestamp=now,
            actor_did="did:valence:alice",
            action=AuditAction.BELIEF_CREATE,
            resource_type="belief",
            resource_id="some-id",
            details={"content_preview": "test belief"},
            ip_address="127.0.0.1",
        )
        d = entry.to_dict()
        assert d["id"] == str(entry_id)
        assert d["timestamp"] == now.isoformat()
        assert d["actor_did"] == "did:valence:alice"
        assert d["action"] == "belief_create"
        assert d["resource_type"] == "belief"
        assert d["resource_id"] == "some-id"
        assert d["details"]["content_preview"] == "test belief"
        assert d["ip_address"] == "127.0.0.1"

    def test_to_dict_nullable_fields(self):
        """to_dict should handle None values."""
        entry = AuditEntry(
            id=uuid4(),
            timestamp=datetime.now(),
            actor_did=None,
            action=AuditAction.DATA_ACCESS,
            resource_type="belief",
            resource_id=None,
            details={},
        )
        d = entry.to_dict()
        assert d["actor_did"] is None
        assert d["resource_id"] is None
        assert d["ip_address"] is None


class TestAuditAction:
    """Tests for AuditAction enum."""

    def test_all_actions_have_string_values(self):
        """Every AuditAction should have a snake_case string value."""
        for action in AuditAction:
            assert isinstance(action.value, str)
            assert "_" in action.value or action.value.isalpha()

    def test_expected_actions_exist(self):
        """Core actions should be defined."""
        expected = [
            "belief_create", "belief_supersede", "belief_archive",
            "belief_share", "share_revoke",
            "tension_resolve",
            "consent_grant", "consent_revoke",
            "data_access", "data_export", "data_delete",
            "session_start", "session_end",
        ]
        actual_values = {a.value for a in AuditAction}
        for action_value in expected:
            assert action_value in actual_values, f"Missing action: {action_value}"


# =============================================================================
# AuditLogger.log TESTS
# =============================================================================


class TestAuditLoggerLog:
    """Tests for AuditLogger.log method."""

    def test_log_basic(self, mock_get_cursor, audit_logger):
        """Should insert an audit log entry."""
        audit_logger.log(
            action=AuditAction.BELIEF_CREATE,
            resource_type="belief",
            resource_id="test-id",
        )

        mock_get_cursor.execute.assert_called_once()
        sql = mock_get_cursor.execute.call_args[0][0]
        assert "INSERT INTO audit_log" in sql

    def test_log_with_all_params(self, mock_get_cursor, audit_logger):
        """Should pass all parameters to SQL."""
        audit_logger.log(
            action=AuditAction.CONSENT_GRANT,
            resource_type="consent",
            resource_id="consent-123",
            details={"purpose": "data_processing"},
            actor_did="did:valence:alice",
            ip_address="192.168.1.1",
        )

        params = mock_get_cursor.execute.call_args[0][1]
        assert "did:valence:alice" in params
        assert "consent_grant" in params
        assert "consent" in params
        assert "consent-123" in params
        assert "192.168.1.1" in params

    def test_log_serializes_details(self, mock_get_cursor, audit_logger):
        """Should JSON-serialize the details dict."""
        audit_logger.log(
            action=AuditAction.BELIEF_CREATE,
            resource_type="belief",
            details={"key": "value"},
        )

        params = mock_get_cursor.execute.call_args[0][1]
        # Details should be JSON string
        details_param = params[4]  # 5th param is details
        parsed = json.loads(details_param)
        assert parsed["key"] == "value"

    def test_log_empty_details_defaults(self, mock_get_cursor, audit_logger):
        """Should default details to empty dict."""
        audit_logger.log(
            action=AuditAction.SESSION_START,
            resource_type="session",
        )

        params = mock_get_cursor.execute.call_args[0][1]
        details_param = params[4]
        assert json.loads(details_param) == {}

    def test_log_never_raises(self, audit_logger):
        """Log should swallow exceptions — non-fatal."""
        with patch("valence.compliance.audit.get_cursor", side_effect=Exception("DB down")):
            # Should NOT raise
            audit_logger.log(
                action=AuditAction.BELIEF_CREATE,
                resource_type="belief",
            )

    def test_log_logs_warning_on_error(self, audit_logger):
        """Should log a warning when write fails."""
        with patch("valence.compliance.audit.get_cursor", side_effect=Exception("DB down")):
            with patch("valence.compliance.audit.logger") as mock_logger:
                audit_logger.log(
                    action=AuditAction.BELIEF_CREATE,
                    resource_type="belief",
                )
                mock_logger.warning.assert_called_once()


# =============================================================================
# AuditLogger.query TESTS
# =============================================================================


class TestAuditLoggerQuery:
    """Tests for AuditLogger.query method."""

    def test_query_basic(self, mock_get_cursor, audit_logger):
        """Should query audit_log table."""
        audit_logger.query()

        sql = mock_get_cursor.execute.call_args[0][0]
        assert "SELECT * FROM audit_log" in sql
        assert "ORDER BY timestamp DESC" in sql

    def test_query_with_action_filter(self, mock_get_cursor, audit_logger):
        """Should filter by action."""
        audit_logger.query(action=AuditAction.BELIEF_CREATE)

        sql = mock_get_cursor.execute.call_args[0][0]
        assert "AND action = %s" in sql
        params = mock_get_cursor.execute.call_args[0][1]
        assert "belief_create" in params

    def test_query_with_resource_type(self, mock_get_cursor, audit_logger):
        """Should filter by resource_type."""
        audit_logger.query(resource_type="belief")

        sql = mock_get_cursor.execute.call_args[0][0]
        assert "AND resource_type = %s" in sql

    def test_query_with_resource_id(self, mock_get_cursor, audit_logger):
        """Should filter by resource_id."""
        audit_logger.query(resource_id="some-id")

        sql = mock_get_cursor.execute.call_args[0][0]
        assert "AND resource_id = %s" in sql

    def test_query_with_actor_did(self, mock_get_cursor, audit_logger):
        """Should filter by actor_did."""
        audit_logger.query(actor_did="did:valence:alice")

        sql = mock_get_cursor.execute.call_args[0][0]
        assert "AND actor_did = %s" in sql

    def test_query_with_since(self, mock_get_cursor, audit_logger):
        """Should filter by timestamp."""
        since = datetime.now() - timedelta(hours=1)
        audit_logger.query(since=since)

        sql = mock_get_cursor.execute.call_args[0][0]
        assert "AND timestamp >= %s" in sql

    def test_query_with_limit(self, mock_get_cursor, audit_logger):
        """Should pass limit to SQL."""
        audit_logger.query(limit=50)

        sql = mock_get_cursor.execute.call_args[0][0]
        assert "LIMIT %s" in sql
        params = mock_get_cursor.execute.call_args[0][1]
        assert 50 in params

    def test_query_returns_entries(self, mock_get_cursor, audit_logger):
        """Should return list of AuditEntry objects."""
        entry_id = uuid4()
        now = datetime.now()
        mock_get_cursor.fetchall.return_value = [
            {
                "id": entry_id,
                "timestamp": now,
                "actor_did": "did:valence:alice",
                "action": "belief_create",
                "resource_type": "belief",
                "resource_id": "b-123",
                "details": {"preview": "test"},
                "ip_address": None,
            }
        ]

        results = audit_logger.query()

        assert len(results) == 1
        assert isinstance(results[0], AuditEntry)
        assert results[0].id == entry_id
        assert results[0].action == AuditAction.BELIEF_CREATE

    def test_query_handles_string_details(self, mock_get_cursor, audit_logger):
        """Should parse details when stored as JSON string."""
        mock_get_cursor.fetchall.return_value = [
            {
                "id": uuid4(),
                "timestamp": datetime.now(),
                "actor_did": None,
                "action": "data_access",
                "resource_type": "belief",
                "resource_id": None,
                "details": '{"key": "value"}',
                "ip_address": None,
            }
        ]

        results = audit_logger.query()

        assert results[0].details == {"key": "value"}

    def test_query_combined_filters(self, mock_get_cursor, audit_logger):
        """Should support multiple filters simultaneously."""
        since = datetime.now() - timedelta(days=7)
        audit_logger.query(
            action=AuditAction.CONSENT_GRANT,
            resource_type="consent",
            actor_did="did:valence:alice",
            since=since,
            limit=10,
        )

        sql = mock_get_cursor.execute.call_args[0][0]
        assert "AND action = %s" in sql
        assert "AND resource_type = %s" in sql
        assert "AND actor_did = %s" in sql
        assert "AND timestamp >= %s" in sql
        assert "LIMIT %s" in sql


# =============================================================================
# Singleton TESTS
# =============================================================================


class TestGetAuditLogger:
    """Tests for get_audit_logger singleton."""

    def test_returns_audit_logger(self):
        """Should return an AuditLogger instance."""
        logger = get_audit_logger()
        assert isinstance(logger, AuditLogger)

    def test_returns_same_instance(self):
        """Should return the same instance on repeated calls."""
        logger1 = get_audit_logger()
        logger2 = get_audit_logger()
        assert logger1 is logger2
