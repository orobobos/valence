"""Conversation capture and curation for Valence.

Three scales:
- Micro: Individual exchanges within a session
- Meso: Session-level summaries and themes
- Macro: Patterns emerging across sessions
"""

import json
from typing import Any

from .kb import get_connection, generate_id, now_ts, create_entry


# === Session Management (Meso) ===

def start_session(
    *,
    platform: str | None = None,
    project_context: str | None = None,
) -> dict[str, Any]:
    """Start a new conversation session."""
    session_id = generate_id()
    started_at = now_ts()

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO sessions (id, started_at, platform, project_context, status)
        VALUES (?, ?, ?, ?, 'active')
        """,
        (session_id, started_at, platform, project_context)
    )
    conn.commit()

    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()

    return dict(row)


def end_session(
    session_id: str,
    *,
    summary: str | None = None,
    themes: list[str] | None = None,
    status: str = "completed",
) -> dict[str, Any]:
    """End a session with optional summary and themes."""
    ended_at = now_ts()
    themes_json = json.dumps(themes) if themes else None

    conn = get_connection()
    conn.execute(
        """
        UPDATE sessions
        SET ended_at = ?, summary = ?, themes = ?, status = ?
        WHERE id = ?
        """,
        (ended_at, summary, themes_json, status, session_id)
    )
    conn.commit()

    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()

    return dict(row)


def get_session(session_id: str) -> dict[str, Any] | None:
    """Get a session by ID."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_sessions(
    *,
    project_context: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List sessions with optional filters."""
    conn = get_connection()

    sql = "SELECT * FROM sessions WHERE 1=1"
    params: list[Any] = []

    if project_context:
        sql += " AND project_context = ?"
        params.append(project_context)

    if status:
        sql += " AND status = ?"
        params.append(status)

    sql += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    return [dict(row) for row in rows]


def update_session_summary(
    session_id: str,
    summary: str,
    themes: list[str] | None = None,
) -> dict[str, Any]:
    """Update session summary and themes (can be done during session)."""
    conn = get_connection()

    if themes is not None:
        themes_json = json.dumps(themes)
        conn.execute(
            "UPDATE sessions SET summary = ?, themes = ? WHERE id = ?",
            (summary, themes_json, session_id)
        )
    else:
        conn.execute(
            "UPDATE sessions SET summary = ? WHERE id = ?",
            (summary, session_id)
        )

    conn.commit()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()

    return dict(row)


# === Exchange Capture (Micro) ===

def add_exchange(
    session_id: str,
    role: str,
    content: str,
    *,
    tokens_approx: int | None = None,
) -> dict[str, Any]:
    """Add an exchange to a session."""
    exchange_id = generate_id()
    timestamp = now_ts()

    conn = get_connection()

    # Get next sequence number
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 as next_seq FROM exchanges WHERE session_id = ?",
        (session_id,)
    ).fetchone()
    sequence = row["next_seq"]

    conn.execute(
        """
        INSERT INTO exchanges (id, session_id, sequence, role, content, timestamp, tokens_approx)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (exchange_id, session_id, sequence, role, content, timestamp, tokens_approx)
    )
    conn.commit()

    row = conn.execute("SELECT * FROM exchanges WHERE id = ?", (exchange_id,)).fetchone()
    conn.close()

    return dict(row)


def get_exchanges(
    session_id: str,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Get exchanges for a session in order."""
    conn = get_connection()

    sql = "SELECT * FROM exchanges WHERE session_id = ? ORDER BY sequence"
    params: list[Any] = [session_id]

    if limit:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    return [dict(row) for row in rows]


# === Insight Extraction (Meso -> Entries) ===

def extract_insight(
    session_id: str,
    entry_type: str,
    content: str,
    *,
    summary: str | None = None,
    confidence: float = 0.8,
    extraction_method: str = "manual",
) -> dict[str, Any]:
    """Extract an insight from a session and create a KB entry."""
    # Create the entry
    entry = create_entry(
        entry_type=entry_type,
        content=content,
        summary=summary,
        confidence=confidence,
        source=f"session:{session_id}",
        source_type="conversation",
    )

    # Link it to the session
    conn = get_connection()
    link_id = generate_id()
    conn.execute(
        """
        INSERT INTO session_insights (id, session_id, entry_id, extraction_method)
        VALUES (?, ?, ?, ?)
        """,
        (link_id, session_id, entry["id"], extraction_method)
    )
    conn.commit()
    conn.close()

    return {
        "insight_id": link_id,
        "entry": entry,
        "session_id": session_id,
        "extraction_method": extraction_method,
    }


def get_session_insights(session_id: str) -> list[dict[str, Any]]:
    """Get all insights extracted from a session."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT si.*, e.type, e.content, e.summary, e.confidence
        FROM session_insights si
        JOIN entries e ON si.entry_id = e.id
        WHERE si.session_id = ?
        ORDER BY si.extracted_at
        """,
        (session_id,)
    ).fetchall()
    conn.close()

    return [dict(row) for row in rows]


# === Pattern Detection (Macro) ===

def record_pattern(
    pattern_type: str,
    description: str,
    *,
    evidence: list[str] | None = None,
    confidence: float = 0.5,
) -> dict[str, Any]:
    """Record a new pattern or update an existing one."""
    pattern_id = generate_id()
    now = now_ts()
    evidence_json = json.dumps(evidence or [])

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO patterns (id, type, description, evidence, first_observed_at, last_observed_at, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (pattern_id, pattern_type, description, evidence_json, now, now, confidence)
    )
    conn.commit()

    row = conn.execute("SELECT * FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
    conn.close()

    return dict(row)


def reinforce_pattern(
    pattern_id: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Reinforce a pattern (increment count, update last observed, optionally add evidence)."""
    conn = get_connection()

    # Get current pattern
    row = conn.execute("SELECT * FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Pattern not found: {pattern_id}")

    pattern = dict(row)
    new_count = pattern["occurrence_count"] + 1
    new_confidence = min(0.95, pattern["confidence"] + 0.05)  # Gradual confidence increase

    # Update evidence if session provided
    evidence = json.loads(pattern["evidence"] or "[]")
    if session_id and session_id not in evidence:
        evidence.append(session_id)

    # Update status based on count
    status = pattern["status"]
    if new_count >= 5 and status == "emerging":
        status = "established"

    conn.execute(
        """
        UPDATE patterns
        SET occurrence_count = ?, confidence = ?, last_observed_at = ?, evidence = ?, status = ?
        WHERE id = ?
        """,
        (new_count, new_confidence, now_ts(), json.dumps(evidence), status, pattern_id)
    )
    conn.commit()

    row = conn.execute("SELECT * FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
    conn.close()

    return dict(row)


def list_patterns(
    *,
    pattern_type: str | None = None,
    status: str | None = None,
    min_confidence: float = 0.0,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List patterns with optional filters."""
    conn = get_connection()

    sql = "SELECT * FROM patterns WHERE confidence >= ?"
    params: list[Any] = [min_confidence]

    if pattern_type:
        sql += " AND type = ?"
        params.append(pattern_type)

    if status:
        sql += " AND status = ?"
        params.append(status)

    sql += " ORDER BY occurrence_count DESC, confidence DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    return [dict(row) for row in rows]


def search_patterns(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search patterns by description."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM patterns WHERE description LIKE ? ORDER BY confidence DESC LIMIT ?",
        (f"%{query}%", limit)
    ).fetchall()
    conn.close()

    return [dict(row) for row in rows]
