"""Centralized configurable defaults for Valence.

All tunable parameters in one place. Hooks duplicate these values
(standalone constraint — they can't import from the package).
"""

from __future__ import annotations

import os

# Ranking weights (sum to 1.0)
RANKING_SEMANTIC_WEIGHT = 0.50
RANKING_CONFIDENCE_WEIGHT = 0.35
RANKING_RECENCY_WEIGHT = 0.15
RANKING_DECAY_RATE = 0.01  # ~69 day half-life

# Auto-capture thresholds
MIN_CAPTURE_CONFIDENCE = float(os.environ.get("VALENCE_MIN_CAPTURE_CONFIDENCE", "0.50"))
MAX_AUTO_BELIEFS_PER_SESSION = 10
MIN_SUMMARY_LENGTH = 20
MIN_THEME_LENGTH = 10

# Query defaults
DEFAULT_QUERY_LIMIT = 20
DEFAULT_SEARCH_LIMIT = 10
DEFAULT_MIN_SIMILARITY = 0.5

# Session context injection
CONTEXT_BELIEF_LIMIT = 5
CONTEXT_PATTERN_LIMIT = 5
