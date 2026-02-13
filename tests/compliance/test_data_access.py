"""Tests for GDPR data access (Article 15) and export (Article 20)."""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from valence.compliance.data_access import (
    EXPORT_FORMAT_VERSION,
    export_holder_data,
    get_holder_data,
    import_holder_data,
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
    """Mock the get_cursor context manager."""

    @contextmanager
    def _mock_get_cursor(dict_cursor: bool = True) -> Generator:
        yield mock_cursor

    with patch("valence.compliance.data_access.get_cursor", _mock_get_cursor):
        with patch("valence.compliance.audit.get_cursor", _mock_get_cursor):
            yield mock_cursor


# =============================================================================
# get_holder_data TESTS (GDPR Article 15)
# =============================================================================


class TestGetHolderData:
    """Tests for GDPR Article 15 data access."""

    def test_returns_all_categories(self, mock_get_cursor):
        """Should return data organized by category."""
        result = get_holder_data("did:valence:alice")

        assert result["holder_did"] == "did:valence:alice"
        assert "categories" in result
        categories = result["categories"]
        assert "beliefs" in categories
        assert "entities" in categories
        assert "sessions" in categories
        assert "exchanges" in categories
        assert "patterns" in categories
        assert "consents" in categories
        assert "audit_log" in categories

    def test_returns_generated_timestamp(self, mock_get_cursor):
        """Should include generation timestamp."""
        result = get_holder_data("did:valence:alice")

        assert "generated_at" in result

    def test_returns_total_records(self, mock_get_cursor):
        """Should compute total across all categories."""
        result = get_holder_data("did:valence:alice")

        assert "total_records" in result
        assert result["total_records"] == 0  # All mocked to empty

    def test_queries_beliefs(self, mock_get_cursor):
        """Should query beliefs for the holder."""
        get_holder_data("did:valence:alice")

        # Should have queried beliefs table
        calls = mock_get_cursor.execute.call_args_list
        sql_calls = [c[0][0] for c in calls]
        assert any("FROM beliefs" in sql for sql in sql_calls)

    def test_queries_consent_records(self, mock_get_cursor):
        """Should query consent records for the holder."""
        get_holder_data("did:valence:alice")

        calls = mock_get_cursor.execute.call_args_list
        sql_calls = [c[0][0] for c in calls]
        assert any("consent_records" in sql for sql in sql_calls)

    def test_logs_audit_entry(self, mock_get_cursor):
        """Should create an audit log entry for data access."""
        get_holder_data("did:valence:alice")

        # Audit log INSERT should be one of the execute calls
        calls = mock_get_cursor.execute.call_args_list
        sql_calls = [c[0][0] for c in calls]
        assert any("INSERT INTO audit_log" in sql for sql in sql_calls)

    def test_with_beliefs_data(self, mock_get_cursor):
        """Should include belief data when present."""
        belief_id = uuid4()
        mock_get_cursor.fetchall.side_effect = [
            # beliefs query
            [{"id": belief_id, "content": "test belief", "created_at": datetime.now()}],
            # entities query
            [],
            # sessions query
            [],
            # patterns query
            [],
            # consents query
            [],
            # audit_log query
            [],
        ]

        result = get_holder_data("did:valence:alice")

        assert result["categories"]["beliefs"]["count"] == 1
        assert result["total_records"] == 1


# =============================================================================
# export_holder_data TESTS (GDPR Article 20)
# =============================================================================


class TestExportHolderData:
    """Tests for GDPR Article 20 data portability."""

    def test_export_format(self, mock_get_cursor):
        """Should include format and version metadata."""
        export = export_holder_data("did:valence:alice")

        assert export["format"] == "valence-export"
        assert export["version"] == EXPORT_FORMAT_VERSION
        assert "exported_at" in export
        assert export["holder_did"] == "did:valence:alice"

    def test_export_contains_data(self, mock_get_cursor):
        """Should include all data categories."""
        export = export_holder_data("did:valence:alice")

        assert "data" in export
        assert "metadata" in export
        assert "total_records" in export["metadata"]
        assert "categories" in export["metadata"]

    def test_export_logs_audit(self, mock_get_cursor):
        """Should log export as audit entry."""
        export_holder_data("did:valence:alice")

        calls = mock_get_cursor.execute.call_args_list
        sql_calls = [c[0][0] for c in calls]
        # Should have 2 audit inserts: one for get_holder_data, one for export
        audit_inserts = [s for s in sql_calls if "INSERT INTO audit_log" in s]
        assert len(audit_inserts) == 2


# =============================================================================
# import_holder_data TESTS (GDPR Article 20 inbound)
# =============================================================================


class TestImportHolderData:
    """Tests for GDPR Article 20 data import."""

    def test_rejects_invalid_format(self, mock_get_cursor):
        """Should reject data without correct format marker."""
        result = import_holder_data({"format": "wrong", "data": {}})

        assert result["success"] is False
        assert "Invalid export format" in result["error"]

    def test_accepts_valid_format(self, mock_get_cursor):
        """Should accept valence-export format."""
        result = import_holder_data({
            "format": "valence-export",
            "version": "1.0.0",
            "holder_did": "did:valence:alice",
            "data": {},
        })

        assert result["success"] is True

    def test_imports_beliefs(self, mock_get_cursor):
        """Should import belief records."""
        result = import_holder_data({
            "format": "valence-export",
            "version": "1.0.0",
            "holder_did": "did:valence:alice",
            "data": {
                "beliefs": {
                    "records": [
                        {"content": "test belief", "confidence": {"overall": 0.8}},
                    ]
                }
            },
        })

        assert result["success"] is True
        assert result["imported"]["beliefs"] == 1

    def test_imports_consents(self, mock_get_cursor):
        """Should import consent records."""
        result = import_holder_data({
            "format": "valence-export",
            "version": "1.0.0",
            "holder_did": "did:valence:alice",
            "data": {
                "consents": {
                    "records": [
                        {
                            "holder_did": "did:valence:alice",
                            "purpose": "data_processing",
                            "scope": "all",
                        },
                    ]
                }
            },
        })

        assert result["success"] is True
        assert result["imported"]["consents"] == 1

    def test_total_imported_count(self, mock_get_cursor):
        """Should compute total imported across categories."""
        result = import_holder_data({
            "format": "valence-export",
            "version": "1.0.0",
            "holder_did": "did:valence:alice",
            "data": {
                "beliefs": {"records": [{"content": "b1"}, {"content": "b2"}]},
                "consents": {"records": [{"purpose": "analytics"}]},
            },
        })

        assert result["total_imported"] == 3
