"""Utility functions for Valence CLI."""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


def get_db_connection():
    """Get database connection using config."""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    from ..core.config import get_config

    config = get_config()
    return psycopg2.connect(
        host=config.db_host,
        port=config.db_port,
        dbname=config.db_name,
        user=config.db_user,
        password=config.db_password,
        cursor_factory=RealDictCursor,
    )


def get_embedding(text: str) -> list[float] | None:
    """Generate embedding using configured provider (local or OpenAI)."""
    try:
        from our_embeddings.service import generate_embedding

        return generate_embedding(text)
    except Exception as e:
        print(f"⚠️  Embedding failed: {e}", file=sys.stderr)
        return None


def format_confidence(conf: dict) -> str:
    """Format confidence for display."""
    if not conf:
        return "?"
    overall = conf.get("overall", 0)
    if isinstance(overall, int | float):
        return f"{overall:.0%}"
    return str(overall)[:5]


def format_age(dt: datetime) -> str:
    """Format datetime as human-readable age."""
    if not dt:
        return "?"

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    now = datetime.now(UTC)
    delta = now - dt

    if delta.days > 365:
        return f"{delta.days // 365}y"
    elif delta.days > 30:
        return f"{delta.days // 30}mo"
    elif delta.days > 0:
        return f"{delta.days}d"
    elif delta.seconds > 3600:
        return f"{delta.seconds // 3600}h"
    elif delta.seconds > 60:
        return f"{delta.seconds // 60}m"
    else:
        return "now"


# ============================================================================
# Multi-Signal Ranking (Valence Query Protocol)
# Re-exported from core.ranking for backward compatibility
# ============================================================================

from ..core.ranking import compute_confidence_score, compute_recency_score, multi_signal_rank  # noqa: E402, F401
