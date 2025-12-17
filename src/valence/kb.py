"""Valence Knowledge Base operations."""

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


def get_db_path() -> Path:
    """Get the path to the KB database."""
    return Path(__file__).parent.parent.parent / "valence.kb.sqlite"


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_schemas() -> None:
    """Initialize all module schemas."""
    schema_dir = Path(__file__).parent.parent.parent
    schema_files = [
        "schema.sql",
        "schema_conversations.sql",
        "schema_embeddings.sql",
    ]

    conn = get_connection()
    for schema_file in schema_files:
        schema_path = schema_dir / schema_file
        if schema_path.exists():
            with open(schema_path) as f:
                conn.executescript(f.read())
    conn.commit()
    conn.close()


def generate_id() -> str:
    """Generate a new UUID."""
    return str(uuid.uuid4())


def now_ts() -> int:
    """Current Unix timestamp."""
    return int(time.time())


def create_entry(
    entry_type: str,
    content: str,
    *,
    summary: str | None = None,
    confidence: float = 1.0,
    source: str | None = None,
    source_type: str | None = None,
    parent_id: str | None = None,
    created_at: int | None = None,
) -> dict[str, Any]:
    """Create a new entry in the KB."""
    entry_id = generate_id()
    created = created_at or now_ts()

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO entries (id, type, content, summary, created_at, confidence, source, source_type, parent_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (entry_id, entry_type, content, summary, created, confidence, source, source_type, parent_id)
    )
    conn.commit()

    row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    conn.close()

    return dict(row)


def get_entry(entry_id: str) -> dict[str, Any] | None:
    """Get an entry by ID."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def search_entries(
    query: str,
    entry_type: str | None = None,
    limit: int = 20
) -> list[dict[str, Any]]:
    """Search entries by content (simple LIKE search for now)."""
    conn = get_connection()

    sql = "SELECT * FROM entries WHERE content LIKE ?"
    params: list[Any] = [f"%{query}%"]

    if entry_type:
        sql += " AND type = ?"
        params.append(entry_type)

    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    return [dict(row) for row in rows]
