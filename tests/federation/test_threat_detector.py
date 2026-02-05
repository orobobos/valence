"""Tests for Threat Detector (federation/threat_detector.py).

Tests cover:
1. ThreatDetector initialization
2. assess_threat_level with various signals
3. apply_threat_response for each threat level
4. Edge cases and signal combinations
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from valence.federation.models import NodeTrust, ThreatLevel
from valence.federation.threat_detector import (
    THREAT_THRESHOLDS,
    ThreatDetector,
)

# ============================================================================
# ThreatDetector Initialization Tests
# ============================================================================


class TestThreatDetectorInit:
    """Test ThreatDetector initialization."""

    def test_detector_creation(self):
        """Create detector with registry."""
        mock_registry = MagicMock()
        detector = ThreatDetector(registry=mock_registry)

        assert detector.registry == mock_registry


# ============================================================================
# assess_threat_level Tests
# ============================================================================


class TestAssessThreatLevel:
    """Test assess_threat_level method."""

    @pytest.fixture
    def detector(self):
        """Create a detector with mock registry."""
        mock_registry = MagicMock()
        return ThreatDetector(registry=mock_registry)

    def test_no_trust_record(self, detector):
        """No trust record returns NONE level."""
        detector.registry.get_node_trust.return_value = None
        node_id = uuid4()

        level, assessment = detector.assess_threat_level(node_id)

        assert level == ThreatLevel.NONE
        assert assessment["reason"] == "No trust record"

    def test_clean_node_no_threat(self, detector):
        """Clean node with good behavior has no threat."""
        node_id = uuid4()

        node_trust = MagicMock(spec=NodeTrust)
        node_trust.beliefs_received = 5  # Low activity, under threshold
        node_trust.beliefs_disputed = 0
        node_trust.sync_requests_served = 2
        node_trust.aggregation_participations = 3
        node_trust.overall = 0.8  # Good trust
        node_trust.beliefs_corroborated = 4
        node_trust.relationship_started_at = datetime.now() - timedelta(days=30)

        detector.registry.get_node_trust.return_value = node_trust

        level, assessment = detector.assess_threat_level(node_id)

        assert level == ThreatLevel.NONE
        assert assessment["threat_score"] == 0.0
        assert len(assessment["signals"]) == 0

    def test_high_dispute_ratio_signal(self, detector):
        """High dispute ratio triggers threat signal."""
        node_id = uuid4()

        node_trust = MagicMock(spec=NodeTrust)
        node_trust.beliefs_received = 100
        node_trust.beliefs_disputed = 50  # 50% dispute ratio
        node_trust.sync_requests_served = 5
        node_trust.aggregation_participations = 5
        node_trust.overall = 0.5
        node_trust.beliefs_corroborated = 50
        node_trust.relationship_started_at = datetime.now() - timedelta(days=30)

        detector.registry.get_node_trust.return_value = node_trust

        level, assessment = detector.assess_threat_level(node_id)

        # Should have high_dispute_ratio signal
        signal_types = [s["type"] for s in assessment["signals"]]
        assert "high_dispute_ratio" in signal_types

        # 50% dispute ratio should contribute 0.3 (capped)
        dispute_signal = next(s for s in assessment["signals"] if s["type"] == "high_dispute_ratio")
        assert dispute_signal["value"] == 0.5
        assert dispute_signal["contribution"] == 0.3

    def test_persistently_low_trust_signal(self, detector):
        """Persistently low trust triggers threat signal."""
        node_id = uuid4()

        node_trust = MagicMock(spec=NodeTrust)
        node_trust.beliefs_received = 15
        node_trust.beliefs_disputed = 2
        node_trust.sync_requests_served = 10
        node_trust.aggregation_participations = 5
        node_trust.overall = 0.15  # Very low trust
        node_trust.beliefs_corroborated = 10
        node_trust.relationship_started_at = datetime.now() - timedelta(days=30)

        detector.registry.get_node_trust.return_value = node_trust

        level, assessment = detector.assess_threat_level(node_id)

        signal_types = [s["type"] for s in assessment["signals"]]
        assert "persistently_low_trust" in signal_types

        low_trust_signal = next(s for s in assessment["signals"] if s["type"] == "persistently_low_trust")
        assert low_trust_signal["contribution"] == 0.2

    def test_low_corroboration_signal(self, detector):
        """Low corroboration ratio triggers threat signal."""
        node_id = uuid4()

        node_trust = MagicMock(spec=NodeTrust)
        node_trust.beliefs_received = 100
        node_trust.beliefs_disputed = 5
        node_trust.sync_requests_served = 10
        node_trust.aggregation_participations = 5
        node_trust.overall = 0.5
        node_trust.beliefs_corroborated = 5  # Only 5% corroborated
        node_trust.relationship_started_at = datetime.now() - timedelta(days=30)

        detector.registry.get_node_trust.return_value = node_trust

        level, assessment = detector.assess_threat_level(node_id)

        signal_types = [s["type"] for s in assessment["signals"]]
        assert "low_corroboration" in signal_types

        corr_signal = next(s for s in assessment["signals"] if s["type"] == "low_corroboration")
        assert corr_signal["contribution"] == 0.15

    def test_high_volume_signal(self, detector):
        """High volume (potential spam) triggers threat signal."""
        node_id = uuid4()

        node_trust = MagicMock(spec=NodeTrust)
        node_trust.beliefs_received = 500  # Very high
        node_trust.beliefs_disputed = 10
        node_trust.sync_requests_served = 50
        node_trust.aggregation_participations = 20
        node_trust.overall = 0.7
        node_trust.beliefs_corroborated = 400
        # Active for only 3 days = 166 beliefs/day
        node_trust.relationship_started_at = datetime.now() - timedelta(days=3)

        detector.registry.get_node_trust.return_value = node_trust

        level, assessment = detector.assess_threat_level(node_id)

        signal_types = [s["type"] for s in assessment["signals"]]
        assert "high_volume" in signal_types

        volume_signal = next(s for s in assessment["signals"] if s["type"] == "high_volume")
        assert volume_signal["value"] > 50  # Daily rate above threshold

    def test_combined_signals_medium_threat(self, detector):
        """Combined signals can reach MEDIUM threat level."""
        node_id = uuid4()

        node_trust = MagicMock(spec=NodeTrust)
        node_trust.beliefs_received = 100
        node_trust.beliefs_disputed = 35  # 35% dispute ratio
        node_trust.sync_requests_served = 20
        node_trust.aggregation_participations = 10
        node_trust.overall = 0.4  # Mediocre trust
        node_trust.beliefs_corroborated = 8  # 8% corroboration
        node_trust.relationship_started_at = datetime.now() - timedelta(days=30)

        detector.registry.get_node_trust.return_value = node_trust

        level, assessment = detector.assess_threat_level(node_id)

        # Should have multiple signals
        assert len(assessment["signals"]) >= 2
        # Should reach at least MEDIUM
        assert level.value in ("medium", "high")
        assert assessment["threat_score"] >= THREAT_THRESHOLDS[ThreatLevel.MEDIUM]

    def test_critical_threat_level(self, detector):
        """Many severe signals can reach CRITICAL threat level."""
        node_id = uuid4()

        node_trust = MagicMock(spec=NodeTrust)
        node_trust.beliefs_received = 500
        node_trust.beliefs_disputed = 250  # 50% dispute
        node_trust.sync_requests_served = 50
        node_trust.aggregation_participations = 50
        node_trust.overall = 0.1  # Very low trust
        node_trust.beliefs_corroborated = 5  # 1% corroboration
        # High volume
        node_trust.relationship_started_at = datetime.now() - timedelta(days=2)

        detector.registry.get_node_trust.return_value = node_trust

        level, assessment = detector.assess_threat_level(node_id)

        # Should reach CRITICAL
        assert level == ThreatLevel.CRITICAL
        assert assessment["threat_score"] >= 0.8

    def test_threat_level_thresholds(self, detector):
        """Verify threat level thresholds are correctly applied."""
        # Verify threshold values
        assert THREAT_THRESHOLDS[ThreatLevel.NONE] == 0.0
        assert THREAT_THRESHOLDS[ThreatLevel.LOW] == 0.2
        assert THREAT_THRESHOLDS[ThreatLevel.MEDIUM] == 0.4
        assert THREAT_THRESHOLDS[ThreatLevel.HIGH] == 0.6
        assert THREAT_THRESHOLDS[ThreatLevel.CRITICAL] == 0.8


# ============================================================================
# apply_threat_response Tests
# ============================================================================


class TestApplyThreatResponse:
    """Test apply_threat_response method."""

    @pytest.fixture
    def detector(self):
        """Create a detector with mock registry."""
        mock_registry = MagicMock()
        return ThreatDetector(registry=mock_registry)

    def test_no_node_trust_returns_false(self, detector):
        """No node trust record returns False."""
        detector.registry.get_node_trust.return_value = None
        node_id = uuid4()

        result = detector.apply_threat_response(
            node_id=node_id,
            threat_level=ThreatLevel.MEDIUM,
            assessment={"signals": []},
        )

        assert result is False

    def test_none_level_no_action(self, detector):
        """NONE threat level requires no action."""
        node_id = uuid4()
        node_trust = MagicMock(spec=NodeTrust)
        detector.registry.get_node_trust.return_value = node_trust

        result = detector.apply_threat_response(
            node_id=node_id,
            threat_level=ThreatLevel.NONE,
            assessment={"signals": []},
        )

        assert result is True
        # No modifications should have been made
        detector.registry.save_node_trust.assert_not_called()

    def test_low_level_logs_warning(self, detector, caplog):
        """LOW threat level logs warning but no penalty."""
        import logging

        node_id = uuid4()
        node_trust = MagicMock(spec=NodeTrust)
        node_trust.manual_trust_adjustment = 0.0
        detector.registry.get_node_trust.return_value = node_trust

        with caplog.at_level(logging.WARNING):
            result = detector.apply_threat_response(
                node_id=node_id,
                threat_level=ThreatLevel.LOW,
                assessment={"signals": [{"type": "test"}]},
            )

        assert result is True
        # Should not save (no changes)
        detector.registry.save_node_trust.assert_not_called()
        # Should log warning
        assert "LOW threat level" in caplog.text

    def test_medium_level_applies_penalty(self, detector):
        """MEDIUM threat level applies trust penalty."""
        node_id = uuid4()
        node_trust = MagicMock(spec=NodeTrust)
        node_trust.manual_trust_adjustment = 0.0
        detector.registry.get_node_trust.return_value = node_trust

        result = detector.apply_threat_response(
            node_id=node_id,
            threat_level=ThreatLevel.MEDIUM,
            assessment={"signals": []},
        )

        assert result is True
        # Should have applied -0.1 penalty
        assert node_trust.manual_trust_adjustment == -0.1
        assert "medium" in node_trust.adjustment_reason.lower()
        node_trust.recalculate_overall.assert_called_once()
        detector.registry.save_node_trust.assert_called_once()

    def test_high_level_quarantines(self, detector):
        """HIGH threat level quarantines node."""
        node_id = uuid4()
        node_trust = MagicMock(spec=NodeTrust)
        node_trust.manual_trust_adjustment = 0.0
        detector.registry.get_node_trust.return_value = node_trust

        with patch("valence.federation.threat_detector.get_cursor") as mock_cursor:
            mock_cur = MagicMock()
            mock_cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
            mock_cursor.return_value.__exit__ = MagicMock(return_value=False)

            result = detector.apply_threat_response(
                node_id=node_id,
                threat_level=ThreatLevel.HIGH,
                assessment={"signals": []},
            )

        assert result is True
        # Should have applied -0.3 penalty
        assert node_trust.manual_trust_adjustment == -0.3
        assert "quarantine" in node_trust.adjustment_reason.lower()
        node_trust.recalculate_overall.assert_called_once()
        # Should have updated database for quarantine
        mock_cur.execute.assert_called_once()
        assert "quarantine_until" in mock_cur.execute.call_args[0][0]

    def test_critical_level_isolates(self, detector):
        """CRITICAL threat level isolates node (read-only)."""
        node_id = uuid4()
        node_trust = MagicMock(spec=NodeTrust)
        node_trust.manual_trust_adjustment = 0.0
        detector.registry.get_node_trust.return_value = node_trust

        with patch("valence.federation.threat_detector.get_cursor") as mock_cursor:
            mock_cur = MagicMock()
            mock_cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
            mock_cursor.return_value.__exit__ = MagicMock(return_value=False)

            result = detector.apply_threat_response(
                node_id=node_id,
                threat_level=ThreatLevel.CRITICAL,
                assessment={"signals": [{"type": "multiple_flags"}]},
            )

        assert result is True
        # Should have applied -0.5 penalty (capped at -0.9)
        assert node_trust.manual_trust_adjustment == -0.5
        assert "isolation" in node_trust.adjustment_reason.lower()
        # Should have set read_only and suspended
        assert "read_only" in mock_cur.execute.call_args[0][0]
        assert "suspended" in mock_cur.execute.call_args[0][0]

    def test_critical_penalty_caps_at_minus_0_9(self, detector):
        """CRITICAL penalty is capped at -0.9 total."""
        node_id = uuid4()
        node_trust = MagicMock(spec=NodeTrust)
        node_trust.manual_trust_adjustment = -0.6  # Already has penalty
        detector.registry.get_node_trust.return_value = node_trust

        with patch("valence.federation.threat_detector.get_cursor") as mock_cursor:
            mock_cur = MagicMock()
            mock_cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
            mock_cursor.return_value.__exit__ = MagicMock(return_value=False)

            detector.apply_threat_response(
                node_id=node_id,
                threat_level=ThreatLevel.CRITICAL,
                assessment={"signals": []},
            )

        # -0.6 + -0.5 = -1.1, but should cap at -0.9
        assert node_trust.manual_trust_adjustment == -0.9

    def test_db_error_handled_gracefully(self, detector, caplog):
        """Database errors are handled gracefully."""
        import logging

        node_id = uuid4()
        node_trust = MagicMock(spec=NodeTrust)
        node_trust.manual_trust_adjustment = 0.0
        detector.registry.get_node_trust.return_value = node_trust

        with patch("valence.federation.threat_detector.get_cursor") as mock_cursor:
            mock_cursor.return_value.__enter__ = MagicMock(side_effect=Exception("DB connection failed"))
            mock_cursor.return_value.__exit__ = MagicMock(return_value=False)

            with caplog.at_level(logging.ERROR):
                result = detector.apply_threat_response(
                    node_id=node_id,
                    threat_level=ThreatLevel.HIGH,
                    assessment={"signals": []},
                )

        # Should still return True (response was applied, just DB failed)
        assert result is True
        # Should log error
        assert "quarantine" in caplog.text.lower() or "error" in caplog.text.lower()


# ============================================================================
# Edge Case Tests
# ============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.fixture
    def detector(self):
        """Create a detector with mock registry."""
        mock_registry = MagicMock()
        return ThreatDetector(registry=mock_registry)

    def test_dispute_ratio_threshold_exactly_30_percent(self, detector):
        """Dispute ratio exactly at 30% threshold."""
        node_id = uuid4()

        node_trust = MagicMock(spec=NodeTrust)
        node_trust.beliefs_received = 100
        node_trust.beliefs_disputed = 30  # Exactly 30%
        node_trust.sync_requests_served = 5
        node_trust.aggregation_participations = 5
        node_trust.overall = 0.5
        node_trust.beliefs_corroborated = 50
        node_trust.relationship_started_at = datetime.now() - timedelta(days=30)

        detector.registry.get_node_trust.return_value = node_trust

        level, assessment = detector.assess_threat_level(node_id)

        # At exactly 30%, should NOT trigger (>0.3 is the condition)
        signal_types = [s["type"] for s in assessment["signals"]]
        assert "high_dispute_ratio" not in signal_types

    def test_dispute_ratio_just_above_threshold(self, detector):
        """Dispute ratio just above 30% threshold."""
        node_id = uuid4()

        node_trust = MagicMock(spec=NodeTrust)
        node_trust.beliefs_received = 100
        node_trust.beliefs_disputed = 31  # Just above 30%
        node_trust.sync_requests_served = 5
        node_trust.aggregation_participations = 5
        node_trust.overall = 0.5
        node_trust.beliefs_corroborated = 50
        node_trust.relationship_started_at = datetime.now() - timedelta(days=30)

        detector.registry.get_node_trust.return_value = node_trust

        level, assessment = detector.assess_threat_level(node_id)

        # Just above 30% should trigger
        signal_types = [s["type"] for s in assessment["signals"]]
        assert "high_dispute_ratio" in signal_types

    def test_new_node_no_volume_signal(self, detector):
        """New node with few beliefs doesn't trigger volume signal."""
        node_id = uuid4()

        node_trust = MagicMock(spec=NodeTrust)
        node_trust.beliefs_received = 50  # Under 100 threshold
        node_trust.beliefs_disputed = 0
        node_trust.sync_requests_served = 5
        node_trust.aggregation_participations = 5
        node_trust.overall = 0.7
        node_trust.beliefs_corroborated = 40
        # Even if very recent, under 100 beliefs shouldn't trigger
        node_trust.relationship_started_at = datetime.now() - timedelta(hours=1)

        detector.registry.get_node_trust.return_value = node_trust

        level, assessment = detector.assess_threat_level(node_id)

        signal_types = [s["type"] for s in assessment["signals"]]
        assert "high_volume" not in signal_types

    def test_zero_beliefs_corroborated_division(self, detector):
        """Zero beliefs corroborated doesn't cause division error."""
        node_id = uuid4()

        node_trust = MagicMock(spec=NodeTrust)
        node_trust.beliefs_received = 10
        node_trust.beliefs_disputed = 0
        node_trust.sync_requests_served = 5
        node_trust.aggregation_participations = 5
        node_trust.overall = 0.5
        node_trust.beliefs_corroborated = 0  # Zero corroborated
        node_trust.relationship_started_at = datetime.now() - timedelta(days=30)

        detector.registry.get_node_trust.return_value = node_trust

        # Should not raise
        level, assessment = detector.assess_threat_level(node_id)

        # With 0 corroborated and >0 received, ratio is 0% - triggers if <10%
        # But beliefs_received = 10 means low_corroboration check doesn't trigger
        # (needs beliefs_corroborated > 0 per the condition)
        assert level is not None

    def test_zero_days_active(self, detector):
        """Node active for 0 days (same day) doesn't cause division error."""
        node_id = uuid4()

        node_trust = MagicMock(spec=NodeTrust)
        node_trust.beliefs_received = 200
        node_trust.beliefs_disputed = 10
        node_trust.sync_requests_served = 5
        node_trust.aggregation_participations = 5
        node_trust.overall = 0.7
        node_trust.beliefs_corroborated = 150
        # Just started today
        node_trust.relationship_started_at = datetime.now()

        detector.registry.get_node_trust.return_value = node_trust

        # Should not raise (max(1, days) protects against division by zero)
        level, assessment = detector.assess_threat_level(node_id)

        # With 200 beliefs in 1 day = 200/day, well above 50 threshold
        signal_types = [s["type"] for s in assessment["signals"]]
        assert "high_volume" in signal_types
