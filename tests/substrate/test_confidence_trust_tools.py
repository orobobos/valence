"""Tests for confidence and trust MCP tool handlers."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from valence.substrate.tools.confidence import (
    _corroboration_label,
    belief_corroboration,
    confidence_explain,
)
from valence.substrate.tools.trust import trust_check


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

    with patch("valence.substrate.tools._common.get_cursor", _mock_get_cursor):
        yield mock_cursor


# =============================================================================
# CORROBORATION LABEL TESTS
# =============================================================================


class TestCorroborationLabel:
    """Tests for _corroboration_label helper."""

    def test_uncorroborated(self):
        assert _corroboration_label(0) == "uncorroborated"

    def test_single(self):
        assert _corroboration_label(1) == "single corroboration"

    def test_moderate(self):
        assert _corroboration_label(2) == "moderately corroborated"
        assert _corroboration_label(3) == "moderately corroborated"

    def test_well(self):
        assert _corroboration_label(4) == "well corroborated"
        assert _corroboration_label(6) == "well corroborated"

    def test_highly(self):
        assert _corroboration_label(7) == "highly corroborated"
        assert _corroboration_label(100) == "highly corroborated"


# =============================================================================
# BELIEF CORROBORATION TESTS
# =============================================================================


class TestBeliefCorroboration:
    """Tests for belief_corroboration tool handler."""

    def test_invalid_uuid(self):
        result = belief_corroboration(belief_id="not-valid")
        assert result["success"] is False
        assert "Invalid belief ID" in result["error"]

    def test_not_found(self):
        with patch("our_federation.corroboration.get_corroboration", return_value=None):
            result = belief_corroboration(belief_id=str(uuid4()))
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_successful(self):
        bid = uuid4()
        mock_corr = MagicMock()
        mock_corr.belief_id = bid
        mock_corr.corroboration_count = 3
        mock_corr.confidence_corroboration = 0.75
        mock_corr.sources = ["alice", "bob", "carol"]

        with patch("our_federation.corroboration.get_corroboration", return_value=mock_corr):
            result = belief_corroboration(belief_id=str(bid))

        assert result["success"] is True
        assert result["corroboration_count"] == 3
        assert result["confidence_corroboration"] == 0.75
        assert result["corroborating_sources"] == ["alice", "bob", "carol"]
        assert result["confidence_label"] == "moderately corroborated"


# =============================================================================
# CONFIDENCE EXPLAIN TESTS
# =============================================================================


class TestConfidenceExplain:
    """Tests for confidence_explain tool handler."""

    def test_not_found(self, mock_get_cursor):
        mock_get_cursor.fetchone.return_value = None
        result = confidence_explain(belief_id=str(uuid4()))
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_successful_explain(self, mock_get_cursor):
        bid = str(uuid4())
        mock_get_cursor.fetchone.return_value = {
            "id": bid,
            "content": "Python is a great language for data science",
            "confidence": {
                "overall": 0.8,
                "source_reliability": 0.9,
                "method_quality": 0.7,
                "corroboration": 0.6,
                "temporal_freshness": 0.85,
                "internal_consistency": 0.8,
            },
            "domain_path": ["tech", "python"],
            "source_id": "alice",
            "status": "active",
            "created_at": "2025-01-01T00:00:00",
            "modified_at": "2025-01-01T00:00:00",
            "valid_from": None,
            "valid_until": None,
            "superseded_by": None,
            "supersedes": None,
            "visibility": "private",
        }
        mock_get_cursor.fetchall.return_value = []  # No trust annotations

        result = confidence_explain(belief_id=bid)

        assert result["success"] is True
        assert result["belief_id"] == bid
        assert result["overall_confidence"] == 0.8
        assert "dimensions" in result
        assert "source_reliability" in result["dimensions"]
        assert "computation_method" in result
        assert "recommendations" in result

    def test_low_confidence_recommendations(self, mock_get_cursor):
        bid = str(uuid4())
        mock_get_cursor.fetchone.return_value = {
            "id": bid,
            "content": "Some uncertain claim",
            "confidence": {
                "overall": 0.3,
                "source_reliability": 0.2,
                "corroboration": 0.1,
                "temporal_freshness": 0.3,
                "internal_consistency": 0.4,
            },
            "domain_path": ["general"],
            "source_id": "unknown",
            "status": "active",
            "created_at": "2025-01-01T00:00:00",
            "modified_at": "2025-01-01T00:00:00",
            "valid_from": None,
            "valid_until": None,
            "superseded_by": None,
            "supersedes": None,
            "visibility": "private",
        }
        mock_get_cursor.fetchall.return_value = []

        result = confidence_explain(belief_id=bid)

        assert result["success"] is True
        recs = result["recommendations"]
        assert len(recs) > 0
        # Should have recommendations for low source_reliability, low corroboration, low freshness
        rec_text = " ".join(recs)
        assert "source" in rec_text.lower() or "corroboration" in rec_text.lower()

    def test_with_trust_annotations(self, mock_get_cursor):
        from datetime import datetime

        bid = str(uuid4())
        mock_get_cursor.fetchone.return_value = {
            "id": bid,
            "content": "Annotated belief",
            "confidence": {"overall": 0.8},
            "domain_path": [],
            "source_id": "alice",
            "status": "active",
            "created_at": "2025-01-01T00:00:00",
            "modified_at": "2025-01-01T00:00:00",
            "valid_from": None,
            "valid_until": None,
            "superseded_by": None,
            "supersedes": None,
            "visibility": "private",
        }
        mock_get_cursor.fetchall.return_value = [
            {"type": "verification", "confidence_delta": 0.1, "created_at": datetime(2025, 1, 1)},
        ]

        result = confidence_explain(belief_id=bid)
        assert result["success"] is True
        assert "trust_annotations" in result
        assert len(result["trust_annotations"]) == 1
        assert result["trust_annotations"][0]["type"] == "verification"


# =============================================================================
# TRUST CHECK TESTS
# =============================================================================


class TestTrustCheck:
    """Tests for trust_check tool handler."""

    def test_basic_query(self, mock_get_cursor):
        mock_get_cursor.fetchall.return_value = []
        result = trust_check(topic="python")
        assert result["success"] is True
        assert result["topic"] == "python"
        assert result["trusted_entities"] == []

    def test_with_entity_filter(self, mock_get_cursor):
        mock_get_cursor.fetchall.return_value = []
        result = trust_check(topic="python", entity_name="alice")
        assert result["success"] is True

    def test_without_federated(self, mock_get_cursor):
        mock_get_cursor.fetchall.return_value = []
        result = trust_check(topic="python", include_federated=False)
        assert result["success"] is True
        assert result["trusted_nodes"] == []

    def test_with_trusted_entities(self, mock_get_cursor):
        eid = uuid4()
        mock_get_cursor.fetchall.side_effect = [
            [{"id": eid, "name": "Alice", "type": "person", "belief_count": 5, "avg_confidence": 0.85, "max_confidence": 0.95}],
            [],  # No federated nodes
        ]
        result = trust_check(topic="python")
        assert result["success"] is True
        assert len(result["trusted_entities"]) == 1
        assert result["trusted_entities"][0]["name"] == "Alice"
        assert result["trusted_entities"][0]["belief_count"] == 5

    def test_federated_table_missing(self, mock_get_cursor):
        """Test graceful handling when federation tables don't exist."""
        mock_get_cursor.fetchall.side_effect = [
            [],  # entities
            Exception("relation 'federation_nodes' does not exist"),
        ]
        # Should not raise — the federation query error is caught
        result = trust_check(topic="python")
        assert result["success"] is True

    def test_custom_min_trust_and_limit(self, mock_get_cursor):
        mock_get_cursor.fetchall.return_value = []
        result = trust_check(topic="python", min_trust=0.8, limit=5)
        assert result["success"] is True

    def test_domain_scoped_trust_returned_in_result(self, mock_get_cursor):
        """When domain is provided, it appears in result."""
        mock_get_cursor.fetchall.return_value = []
        result = trust_check(topic="python", domain="tech")
        assert result["domain"] == "tech"

    def test_domain_scoped_trust_query_uses_domain(self, mock_get_cursor):
        """When domain is provided, federated query uses domain_expertise JSONB path."""
        nid = uuid4()
        mock_get_cursor.fetchall.side_effect = [
            [],  # entities
            [
                {
                    "id": nid,
                    "name": "PeerNode",
                    "instance_url": "https://peer.example.com",
                    "trust": {"overall": 0.6, "domain_expertise": {"tech": 0.9}},
                    "beliefs_corroborated": 10,
                    "beliefs_disputed": 1,
                    "effective_trust": 0.9,
                }
            ],
        ]
        result = trust_check(topic="python", domain="tech")
        assert len(result["trusted_nodes"]) == 1
        node = result["trusted_nodes"][0]
        assert node["trust_score"] == 0.9
        assert node["domain_trust"] == 0.9
        assert node["domain"] == "tech"

    def test_domain_scoped_trust_fallback_to_overall(self, mock_get_cursor):
        """When domain_expertise key missing, falls back to overall trust."""
        nid = uuid4()
        mock_get_cursor.fetchall.side_effect = [
            [],
            [
                {
                    "id": nid,
                    "name": "GenericNode",
                    "instance_url": "https://generic.example.com",
                    "trust": {"overall": 0.7},
                    "beliefs_corroborated": 5,
                    "beliefs_disputed": 0,
                    "effective_trust": 0.7,
                }
            ],
        ]
        result = trust_check(topic="python", domain="science")
        assert len(result["trusted_nodes"]) == 1
        node = result["trusted_nodes"][0]
        assert node["trust_score"] == 0.7
        assert node["domain_trust"] is None

    def test_without_domain_no_domain_fields(self, mock_get_cursor):
        """When domain is not provided, nodes don't have domain-specific fields."""
        nid = uuid4()
        mock_get_cursor.fetchall.side_effect = [
            [],
            [
                {
                    "id": nid,
                    "name": "Node",
                    "instance_url": "https://example.com",
                    "trust": {"overall": 0.5},
                    "beliefs_corroborated": 3,
                    "beliefs_disputed": 0,
                    "effective_trust": 0.5,
                }
            ],
        ]
        result = trust_check(topic="python")
        node = result["trusted_nodes"][0]
        assert "domain_trust" not in node
        assert "domain" not in node
