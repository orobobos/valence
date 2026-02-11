"""Tests for core.curation module."""

from __future__ import annotations

import os
from unittest.mock import patch

from valence.core.curation import (
    MAX_AUTO_BELIEFS_PER_SESSION,
    MIN_CAPTURE_CONFIDENCE,
    MIN_SUMMARY_LENGTH,
    MIN_THEME_LENGTH,
    SIGNAL_CONFIDENCE,
    get_confidence,
    should_capture,
)


class TestSignalConfidence:
    """Tests for signal confidence thresholds."""

    def test_all_signals_have_valid_confidence(self):
        """All signal types should have confidence in [0, 1]."""
        for signal, conf in SIGNAL_CONFIDENCE.items():
            assert 0.0 <= conf <= 1.0, f"{signal} has invalid confidence {conf}"

    def test_explicit_request_highest(self):
        """Explicit requests should have the highest confidence."""
        assert SIGNAL_CONFIDENCE["explicit_request"] >= max(
            v for k, v in SIGNAL_CONFIDENCE.items() if k != "explicit_request"
        )

    def test_mentioned_in_passing_lowest(self):
        """Mentioned in passing should have the lowest confidence."""
        assert SIGNAL_CONFIDENCE["mentioned_in_passing"] <= min(
            v for k, v in SIGNAL_CONFIDENCE.items() if k != "mentioned_in_passing"
        )

    def test_session_summary_above_threshold(self):
        """Session summaries should be above the default capture threshold."""
        assert SIGNAL_CONFIDENCE["session_summary"] >= 0.50

    def test_session_theme_above_threshold(self):
        """Session themes should be above the default capture threshold."""
        assert SIGNAL_CONFIDENCE["session_theme"] >= 0.50


class TestShouldCapture:
    """Tests for the should_capture function."""

    def test_high_confidence_signals_captured(self):
        assert should_capture("explicit_request") is True
        assert should_capture("decision_with_rationale") is True
        assert should_capture("session_summary") is True

    def test_low_confidence_signals_skipped(self):
        assert should_capture("mentioned_in_passing") is False

    def test_unknown_signal_not_captured(self):
        assert should_capture("nonexistent_signal") is False


class TestGetConfidence:
    """Tests for get_confidence function."""

    def test_known_signal(self):
        assert get_confidence("session_summary") == 0.65

    def test_unknown_signal_returns_default(self):
        assert get_confidence("unknown") == 0.5


class TestConstants:
    """Tests for module-level constants."""

    def test_max_auto_beliefs_reasonable(self):
        assert 1 <= MAX_AUTO_BELIEFS_PER_SESSION <= 50

    def test_min_summary_length_positive(self):
        assert MIN_SUMMARY_LENGTH > 0

    def test_min_theme_length_positive(self):
        assert MIN_THEME_LENGTH > 0

    def test_default_capture_confidence(self):
        assert MIN_CAPTURE_CONFIDENCE == 0.50
