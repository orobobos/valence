"""Tests for ConsentManager — full lifecycle coverage.

Tests: grant, check, revoke, expiry, retention, list.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from valence.compliance.consent import ConsentManager, ConsentRecord, RETENTION_YEARS


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

    with patch("valence.compliance.consent.get_cursor", _mock_get_cursor):
        yield mock_cursor


def _make_consent_row(
    holder_did: str = "did:valence:test",
    purpose: str = "data_processing",
    scope: str = "all",
    revoked_at=None,
    expires_at=None,
    **kwargs,
) -> dict:
    """Create a mock consent record row."""
    now = datetime.now()
    return {
        "id": kwargs.get("id", uuid4()),
        "holder_did": holder_did,
        "purpose": purpose,
        "scope": scope,
        "granted_at": kwargs.get("granted_at", now),
        "expires_at": expires_at,
        "revoked_at": revoked_at,
        "retention_until": kwargs.get("retention_until", now + timedelta(days=RETENTION_YEARS * 365)),
        "metadata": kwargs.get("metadata", {}),
    }


# =============================================================================
# ConsentRecord TESTS
# =============================================================================


class TestConsentRecord:
    """Tests for ConsentRecord dataclass."""

    def test_active_consent(self):
        """Active consent is not revoked and not expired."""
        record = ConsentRecord(
            id=uuid4(),
            holder_did="did:valence:test",
            purpose="data_processing",
            scope="all",
            granted_at=datetime.now(),
        )
        assert record.is_active() is True

    def test_revoked_consent_is_inactive(self):
        """Revoked consent should not be active."""
        record = ConsentRecord(
            id=uuid4(),
            holder_did="did:valence:test",
            purpose="data_processing",
            scope="all",
            granted_at=datetime.now(),
            revoked_at=datetime.now(),
        )
        assert record.is_active() is False

    def test_expired_consent_is_inactive(self):
        """Expired consent should not be active."""
        record = ConsentRecord(
            id=uuid4(),
            holder_did="did:valence:test",
            purpose="data_processing",
            scope="all",
            granted_at=datetime.now() - timedelta(days=365),
            expires_at=datetime.now() - timedelta(days=1),
        )
        assert record.is_active() is False

    def test_future_expiry_is_active(self):
        """Consent with future expiry should be active."""
        record = ConsentRecord(
            id=uuid4(),
            holder_did="did:valence:test",
            purpose="data_processing",
            scope="all",
            granted_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=365),
        )
        assert record.is_active() is True

    def test_to_dict_roundtrip(self):
        """to_dict should include all fields."""
        record = ConsentRecord(
            id=uuid4(),
            holder_did="did:valence:test",
            purpose="analytics",
            scope="sessions",
            granted_at=datetime.now(),
            retention_until=datetime.now() + timedelta(days=2555),
        )
        d = record.to_dict()
        assert d["holder_did"] == "did:valence:test"
        assert d["purpose"] == "analytics"
        assert d["scope"] == "sessions"
        assert d["is_active"] is True

    def test_from_row(self):
        """from_row should construct from database row."""
        row = _make_consent_row(purpose="backup", scope="beliefs")
        record = ConsentRecord.from_row(row)
        assert record.purpose == "backup"
        assert record.scope == "beliefs"


# =============================================================================
# ConsentManager TESTS
# =============================================================================


class TestConsentManagerRecordConsent:
    """Tests for ConsentManager.record_consent."""

    def test_record_consent_basic(self, mock_get_cursor):
        """Should insert consent record and return ConsentRecord."""
        mock_get_cursor.fetchone.return_value = _make_consent_row()

        record = ConsentManager.record_consent(
            holder_did="did:valence:alice",
            purpose="data_processing",
        )

        assert isinstance(record, ConsentRecord)
        mock_get_cursor.execute.assert_called_once()
        sql = mock_get_cursor.execute.call_args[0][0]
        assert "INSERT INTO consent_records" in sql

    def test_record_consent_with_expiry(self, mock_get_cursor):
        """Should pass expiry to the database."""
        expiry = datetime.now() + timedelta(days=90)
        mock_get_cursor.fetchone.return_value = _make_consent_row(expires_at=expiry)

        record = ConsentManager.record_consent(
            holder_did="did:valence:alice",
            purpose="federation_sharing",
            expiry=expiry,
        )

        params = mock_get_cursor.execute.call_args[0][1]
        assert expiry in params

    def test_record_consent_sets_retention(self, mock_get_cursor):
        """Should set retention_until to 7 years from now."""
        mock_get_cursor.fetchone.return_value = _make_consent_row()

        ConsentManager.record_consent(
            holder_did="did:valence:alice",
            purpose="data_processing",
        )

        params = mock_get_cursor.execute.call_args[0][1]
        # retention_until is the 5th parameter
        retention = params[4]
        assert isinstance(retention, datetime)
        # Should be roughly 7 years from now
        days_diff = (retention - datetime.now()).days
        assert 2550 <= days_diff <= 2560


class TestConsentManagerCheckConsent:
    """Tests for ConsentManager.check_consent."""

    def test_check_consent_exists(self, mock_get_cursor):
        """Should return True when active consent exists."""
        mock_get_cursor.fetchone.return_value = {"id": uuid4()}

        result = ConsentManager.check_consent("did:valence:alice", "data_processing")

        assert result is True

    def test_check_consent_not_found(self, mock_get_cursor):
        """Should return False when no consent exists."""
        mock_get_cursor.fetchone.return_value = None

        result = ConsentManager.check_consent("did:valence:alice", "data_processing")

        assert result is False

    def test_check_consent_filters_revoked(self, mock_get_cursor):
        """Should filter out revoked consents in SQL."""
        mock_get_cursor.fetchone.return_value = None

        ConsentManager.check_consent("did:valence:alice", "data_processing")

        sql = mock_get_cursor.execute.call_args[0][0]
        assert "revoked_at IS NULL" in sql

    def test_check_consent_filters_expired(self, mock_get_cursor):
        """Should filter out expired consents in SQL."""
        mock_get_cursor.fetchone.return_value = None

        ConsentManager.check_consent("did:valence:alice", "data_processing")

        sql = mock_get_cursor.execute.call_args[0][0]
        assert "expires_at" in sql


class TestConsentManagerRevokeConsent:
    """Tests for ConsentManager.revoke_consent."""

    def test_revoke_consent_success(self, mock_get_cursor):
        """Should mark consent as revoked."""
        consent_id = uuid4()
        mock_get_cursor.fetchone.return_value = {"id": consent_id}

        result = ConsentManager.revoke_consent(consent_id, reason="User requested")

        assert result is True
        sql = mock_get_cursor.execute.call_args[0][0]
        assert "revoked_at = NOW()" in sql

    def test_revoke_consent_not_found(self, mock_get_cursor):
        """Should return False when consent not found."""
        mock_get_cursor.fetchone.return_value = None

        result = ConsentManager.revoke_consent(uuid4())

        assert result is False

    def test_revoke_consent_already_revoked(self, mock_get_cursor):
        """Should not double-revoke (SQL has WHERE revoked_at IS NULL)."""
        mock_get_cursor.fetchone.return_value = None  # No rows updated

        result = ConsentManager.revoke_consent(uuid4())

        assert result is False
        sql = mock_get_cursor.execute.call_args[0][0]
        assert "revoked_at IS NULL" in sql


class TestConsentManagerListConsents:
    """Tests for ConsentManager.list_consents."""

    def test_list_consents_basic(self, mock_get_cursor):
        """Should return list of ConsentRecord objects."""
        mock_get_cursor.fetchall.return_value = [
            _make_consent_row(purpose="data_processing"),
            _make_consent_row(purpose="analytics"),
        ]

        results = ConsentManager.list_consents("did:valence:alice")

        assert len(results) == 2
        assert all(isinstance(r, ConsentRecord) for r in results)

    def test_list_consents_excludes_revoked_by_default(self, mock_get_cursor):
        """Should exclude revoked consents by default."""
        mock_get_cursor.fetchall.return_value = []

        ConsentManager.list_consents("did:valence:alice")

        sql = mock_get_cursor.execute.call_args[0][0]
        assert "revoked_at IS NULL" in sql

    def test_list_consents_include_revoked(self, mock_get_cursor):
        """Should include revoked when requested."""
        mock_get_cursor.fetchall.return_value = []

        ConsentManager.list_consents("did:valence:alice", include_revoked=True)

        sql = mock_get_cursor.execute.call_args[0][0]
        assert "revoked_at IS NULL" not in sql
