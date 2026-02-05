"""Fixtures for spec compliance tests.

Provides utilities for:
- Loading and parsing spec files
- Schema introspection
- Cross-referencing spec requirements with implementation
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

# ============================================================================
# Spec File Utilities
# ============================================================================

SPEC_DIR = Path(__file__).parent.parent.parent / "spec" / "components"


@pytest.fixture
def spec_dir() -> Path:
    """Return the path to spec/components/."""
    return SPEC_DIR


def load_spec(component: str) -> str:
    """Load a spec file by component name.

    Args:
        component: Component name (e.g., 'belief-schema')

    Returns:
        Full spec content as string
    """
    spec_path = SPEC_DIR / component / "SPEC.md"
    if not spec_path.exists():
        raise FileNotFoundError(f"Spec not found: {spec_path}")
    return spec_path.read_text()


@pytest.fixture
def belief_schema_spec() -> str:
    """Load the belief-schema spec."""
    return load_spec("belief-schema")


@pytest.fixture
def confidence_vectors_spec() -> str:
    """Load the confidence-vectors spec."""
    return load_spec("confidence-vectors")


# ============================================================================
# Schema Introspection
# ============================================================================

# Expected columns for beliefs table per SPEC.md Section 1.1
BELIEF_SPEC_FIELDS = {
    # Identity
    "id": {"type": "uuid", "required": True},
    "version": {"type": "integer", "required": True, "note": "Not in current schema"},
    # Content
    "content": {"type": "text", "required": True},
    "content_hash": {
        "type": "text",
        "required": False,
        "note": "Not in current schema",
    },
    # Confidence
    "confidence": {"type": "jsonb", "required": True},
    # Temporal
    "valid_from": {"type": "timestamptz", "required": False},
    "valid_until": {"type": "timestamptz", "required": False},
    # Derivation - spec says derivation object, schema uses source_id
    "source_id": {"type": "uuid", "required": False, "spec_name": "derivation"},
    # Organization - spec says domains[], schema uses domain_path[]
    "domain_path": {"type": "text[]", "required": True, "spec_name": "domains"},
    # Privacy - spec has visibility enum, not yet in schema
    "visibility": {"type": "text", "required": False, "note": "Not in current schema"},
    # Provenance - spec says holder_id, schema uses source_id
    "created_at": {"type": "timestamptz", "required": True},
    # Versioning
    "supersedes_id": {"type": "uuid", "required": False, "spec_name": "supersedes"},
    "superseded_by_id": {
        "type": "uuid",
        "required": False,
        "spec_name": "superseded_by",
    },
    # Search
    "embedding": {"type": "vector", "required": False},
    # Schema additions not in spec
    "modified_at": {
        "type": "timestamptz",
        "required": True,
        "note": "Schema extension",
    },
    "extraction_method": {
        "type": "text",
        "required": False,
        "note": "Schema extension",
    },
    "status": {"type": "text", "required": True, "note": "Schema extension"},
}

# Confidence vector dimensions per SPEC.md Section 1.2
CONFIDENCE_VECTOR_DIMENSIONS = [
    "source_reliability",
    "method_quality",
    "internal_consistency",
    "temporal_freshness",
    "corroboration",
    "domain_applicability",
]

# Default confidence values per spec
CONFIDENCE_DEFAULTS = {
    "source_reliability": 0.5,
    "method_quality": 0.5,
    "internal_consistency": 1.0,
    "temporal_freshness": 1.0,
    "corroboration": 0.1,
    "domain_applicability": 0.8,
}

# Visibility enum values per spec
VISIBILITY_VALUES = ["private", "federated", "public"]

# Derivation type enum values per spec
DERIVATION_TYPES = [
    "observation",
    "inference",
    "aggregation",
    "hearsay",
    "assumption",
    "correction",
    "synthesis",
]


@pytest.fixture
def belief_spec_fields() -> dict[str, dict[str, Any]]:
    """Return the expected belief fields from spec."""
    return BELIEF_SPEC_FIELDS


@pytest.fixture
def confidence_dimensions() -> list[str]:
    """Return the six confidence dimensions from spec."""
    return CONFIDENCE_VECTOR_DIMENSIONS


@pytest.fixture
def confidence_defaults() -> dict[str, float]:
    """Return default confidence values from spec."""
    return CONFIDENCE_DEFAULTS


# ============================================================================
# SQL Schema Parser
# ============================================================================


def parse_create_table(sql: str, table_name: str) -> dict[str, str]:
    """Extract column definitions from a CREATE TABLE statement.

    Args:
        sql: Full SQL schema text
        table_name: Name of table to extract

    Returns:
        Dict of column_name -> column_type
    """
    # Find the CREATE TABLE block
    pattern = rf"CREATE TABLE IF NOT EXISTS {table_name}\s*\((.*?)\);"
    match = re.search(pattern, sql, re.DOTALL | re.IGNORECASE)
    if not match:
        return {}

    table_body = match.group(1)

    # Parse column definitions (simplified)
    columns = {}
    for line in table_body.split("\n"):
        line = line.strip()
        if not line or line.startswith("--") or line.startswith("CONSTRAINT"):
            continue
        if line.startswith("PRIMARY KEY") or line.startswith("UNIQUE"):
            continue
        if line.startswith("FOREIGN KEY"):
            continue

        # Extract column name and type
        col_match = re.match(r"(\w+)\s+(\w+(?:\([^)]+\))?)", line)
        if col_match:
            col_name = col_match.group(1).lower()
            col_type = col_match.group(2).lower()
            columns[col_name] = col_type

    return columns


@pytest.fixture
def schema_sql() -> str:
    """Load the schema.sql file."""
    schema_path = Path(__file__).parent.parent.parent / "src" / "valence" / "substrate" / "schema.sql"
    return schema_path.read_text()


@pytest.fixture
def beliefs_table_columns(schema_sql: str) -> dict[str, str]:
    """Parse columns from the beliefs table in schema.sql."""
    return parse_create_table(schema_sql, "beliefs")
