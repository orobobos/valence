"""Curation decision framework for auto-capture.

Defines vocabulary and confidence thresholds for different types of
automatically captured knowledge. Used by session-end hooks and
insight extraction.
"""

from __future__ import annotations

import os

# Signal types mapped to base confidence scores.
# Higher confidence = stronger signal that this should be captured.
SIGNAL_CONFIDENCE: dict[str, float] = {
    "explicit_request": 0.90,       # "remember X"
    "decision_with_rationale": 0.80,
    "stated_preference": 0.75,
    "correction": 0.70,
    "project_fact": 0.65,
    "session_summary": 0.65,
    "session_theme": 0.55,
    "mentioned_in_passing": 0.35,
}

# Minimum confidence for auto-capture (configurable via env)
MIN_CAPTURE_CONFIDENCE = float(os.environ.get("VALENCE_MIN_CAPTURE_CONFIDENCE", "0.50"))

# Maximum beliefs auto-created per session to prevent spam
MAX_AUTO_BELIEFS_PER_SESSION = 10

# Minimum content length for capture
MIN_SUMMARY_LENGTH = 20
MIN_THEME_LENGTH = 10


def should_capture(signal_type: str) -> bool:
    """Check if a signal type meets the minimum capture threshold."""
    confidence = SIGNAL_CONFIDENCE.get(signal_type, 0.0)
    return confidence >= MIN_CAPTURE_CONFIDENCE


def get_confidence(signal_type: str) -> float:
    """Get the confidence score for a signal type."""
    return SIGNAL_CONFIDENCE.get(signal_type, 0.5)
