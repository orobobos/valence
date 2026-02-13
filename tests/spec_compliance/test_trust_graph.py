"""
Spec Compliance Tests: Trust Graph

Verifies the codebase implements trust graph functionality per
spec/components/trust-graph/SPEC.md.

Key requirements:
- trust_check interface exists and accepts topic, entity_name, min_trust, limit
- Returns structured results with trusted_entities and trusted_nodes
- Entity trust scoring based on belief count and average confidence
- Trust is continuous [0.0, 1.0]
- Domain-specific trust support
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

from valence.substrate.tools.trust import trust_check


# ============================================================================
# Trust Check Interface Tests
# ============================================================================


class TestTrustCheckInterface:
    """Test trust_check tool matches spec query interface."""

    def test_trust_check_function_exists(self):
        """trust_check function must be importable."""
        assert callable(trust_check)

    def test_accepts_topic_parameter(self):
        """Spec: topic is required parameter."""
        sig = inspect.signature(trust_check)
        assert "topic" in sig.parameters

    def test_accepts_entity_name_parameter(self):
        """Spec: optional entity_name for filtering."""
        sig = inspect.signature(trust_check)
        assert "entity_name" in sig.parameters
        assert sig.parameters["entity_name"].default is None

    def test_accepts_min_trust_parameter(self):
        """Spec: min_trust threshold for filtering results."""
        sig = inspect.signature(trust_check)
        assert "min_trust" in sig.parameters
        assert sig.parameters["min_trust"].default == 0.3

    def test_accepts_limit_parameter(self):
        """Spec: limit for number of results."""
        sig = inspect.signature(trust_check)
        assert "limit" in sig.parameters
        assert sig.parameters["limit"].default == 10

    def test_accepts_include_federated_parameter(self):
        """Spec: include_federated flag for cross-federation trust."""
        sig = inspect.signature(trust_check)
        assert "include_federated" in sig.parameters
        assert sig.parameters["include_federated"].default is True


# ============================================================================
# Trust Check Return Structure Tests
# ============================================================================


class TestTrustCheckReturnStructure:
    """Test trust_check returns properly structured results."""

    @patch("valence.substrate.tools.trust._common.get_cursor")
    def test_returns_success_flag(self, mock_cursor):
        """Result must include success flag."""
        mock_ctx = MagicMock()
        mock_cursor.return_value.__enter__ = lambda s: mock_ctx
        mock_cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_ctx.execute = MagicMock()
        mock_ctx.fetchall = MagicMock(return_value=[])

        result = trust_check(topic="python")
        assert "success" in result
        assert result["success"] is True

    @patch("valence.substrate.tools.trust._common.get_cursor")
    def test_returns_trusted_entities_list(self, mock_cursor):
        """Result must include trusted_entities list."""
        mock_ctx = MagicMock()
        mock_cursor.return_value.__enter__ = lambda s: mock_ctx
        mock_cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_ctx.execute = MagicMock()
        mock_ctx.fetchall = MagicMock(return_value=[])

        result = trust_check(topic="python")
        assert "trusted_entities" in result
        assert isinstance(result["trusted_entities"], list)

    @patch("valence.substrate.tools.trust._common.get_cursor")
    def test_returns_trusted_nodes_list(self, mock_cursor):
        """Result must include trusted_nodes for federation trust."""
        mock_ctx = MagicMock()
        mock_cursor.return_value.__enter__ = lambda s: mock_ctx
        mock_cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_ctx.execute = MagicMock()
        mock_ctx.fetchall = MagicMock(return_value=[])

        result = trust_check(topic="python")
        assert "trusted_nodes" in result
        assert isinstance(result["trusted_nodes"], list)

    @patch("valence.substrate.tools.trust._common.get_cursor")
    def test_returns_topic_in_result(self, mock_cursor):
        """Result echoes the queried topic."""
        mock_ctx = MagicMock()
        mock_cursor.return_value.__enter__ = lambda s: mock_ctx
        mock_cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_ctx.execute = MagicMock()
        mock_ctx.fetchall = MagicMock(return_value=[])

        result = trust_check(topic="quantum computing")
        assert result["topic"] == "quantum computing"


# ============================================================================
# Trust Entity Result Shape Tests
# ============================================================================


class TestTrustEntityResultShape:
    """Test the structure of trusted entity results."""

    @patch("valence.substrate.tools.trust._common.get_cursor")
    def test_entity_result_has_expected_fields(self, mock_cursor):
        """Each trusted entity should have id, name, type, belief_count, avg_confidence."""
        mock_ctx = MagicMock()
        mock_cursor.return_value.__enter__ = lambda s: mock_ctx
        mock_cursor.return_value.__exit__ = MagicMock(return_value=False)

        # First call is entity query, second is node query
        mock_ctx.execute = MagicMock()
        mock_ctx.fetchall = MagicMock(side_effect=[
            [
                {
                    "id": "entity-uuid-1",
                    "name": "Test Entity",
                    "type": "concept",
                    "belief_count": 5,
                    "avg_confidence": 0.85,
                    "max_confidence": 0.95,
                }
            ],
            [],  # No federation nodes
        ])

        result = trust_check(topic="testing")
        assert len(result["trusted_entities"]) == 1
        entity = result["trusted_entities"][0]
        assert "id" in entity
        assert "name" in entity
        assert "type" in entity
        assert "belief_count" in entity
        assert "avg_confidence" in entity
        assert "trust_reason" in entity


# ============================================================================
# Trust Model Property Tests
# ============================================================================


class TestTrustModelProperties:
    """Test trust model properties per spec."""

    def test_trust_is_continuous_range(self):
        """Spec: trust is continuous float in [0.0, 1.0]."""
        # The min_trust parameter validates this is float-based
        sig = inspect.signature(trust_check)
        assert isinstance(sig.parameters["min_trust"].default, float)

    def test_default_min_trust_is_reasonable(self):
        """Spec: default_trust for unknown agents is 0.1, threshold > that."""
        sig = inspect.signature(trust_check)
        min_trust = sig.parameters["min_trust"].default
        assert 0.0 < min_trust < 1.0
