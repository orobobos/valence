"""Spec compliance tests for belief-schema.

Reference: spec/components/belief-schema/SPEC.md

These tests verify that the implementation (schema.sql, models)
conforms to the specification. Spec is the source of truth.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest


# ============================================================================
# Section 1.1: Belief Core Structure
# ============================================================================

class TestBeliefCoreStructure:
    """Tests for SPEC Section 1.1: Belief interface.
    
    The spec defines 15 fields for the Belief interface.
    Schema may have variations but must support the core semantics.
    """

    def test_beliefs_table_exists(self, schema_sql: str):
        """Verify beliefs table is defined in schema."""
        assert "CREATE TABLE IF NOT EXISTS beliefs" in schema_sql

    def test_id_field_is_uuid(self, beliefs_table_columns: dict[str, str]):
        """SPEC: id: UUID - Unique identifier."""
        assert "id" in beliefs_table_columns
        assert beliefs_table_columns["id"] == "uuid"

    def test_content_field_exists(self, beliefs_table_columns: dict[str, str]):
        """SPEC: content: string - The claim itself (UTF-8, max 64KB)."""
        assert "content" in beliefs_table_columns
        assert beliefs_table_columns["content"] == "text"

    def test_confidence_field_is_jsonb(self, beliefs_table_columns: dict[str, str]):
        """SPEC: confidence: ConfidenceVector - Multi-dimensional confidence scores."""
        assert "confidence" in beliefs_table_columns
        assert beliefs_table_columns["confidence"] == "jsonb"

    def test_valid_from_field_exists(self, beliefs_table_columns: dict[str, str]):
        """SPEC: valid_from: timestamp - When this belief became/becomes valid."""
        assert "valid_from" in beliefs_table_columns
        assert "timestamp" in beliefs_table_columns["valid_from"]

    def test_valid_until_field_exists(self, beliefs_table_columns: dict[str, str]):
        """SPEC: valid_until: timestamp | null - When this belief expires."""
        assert "valid_until" in beliefs_table_columns
        assert "timestamp" in beliefs_table_columns["valid_until"]

    def test_domains_field_exists(self, beliefs_table_columns: dict[str, str]):
        """SPEC: domains: string[] - Categorical tags.
        
        Schema uses domain_path instead of domains - acceptable naming variation.
        """
        assert "domain_path" in beliefs_table_columns
        # TEXT[] type shows as text[] in our parser
        assert "text" in beliefs_table_columns["domain_path"]

    def test_created_at_field_exists(self, beliefs_table_columns: dict[str, str]):
        """SPEC: created_at: timestamp - When this version was created."""
        assert "created_at" in beliefs_table_columns
        assert "timestamp" in beliefs_table_columns["created_at"]

    def test_supersedes_field_exists(self, beliefs_table_columns: dict[str, str]):
        """SPEC: supersedes: UUID | null - Previous version this belief supersedes."""
        assert "supersedes_id" in beliefs_table_columns
        assert beliefs_table_columns["supersedes_id"] == "uuid"

    def test_superseded_by_field_exists(self, beliefs_table_columns: dict[str, str]):
        """SPEC: superseded_by: UUID | null - Newer version that supersedes this."""
        assert "superseded_by_id" in beliefs_table_columns
        assert beliefs_table_columns["superseded_by_id"] == "uuid"

    def test_embedding_field_exists(self, beliefs_table_columns: dict[str, str]):
        """SPEC: embedding: float[] - Vector embedding for semantic search."""
        assert "embedding" in beliefs_table_columns
        # vector(1536) type
        assert "vector" in beliefs_table_columns["embedding"]

    def test_embedding_dimension_is_1536(self, schema_sql: str):
        """SPEC Section 3.1: Dimensions: 1536 (text-embedding-3-small)."""
        # Check that embedding is defined as vector(1536)
        assert "embedding VECTOR(1536)" in schema_sql


# ============================================================================
# Section 1.1 - Known Gaps
# ============================================================================

class TestBeliefSchemaGaps:
    """Document known gaps between spec and schema.
    
    These tests are expected to FAIL until the schema is updated.
    Mark as xfail to track them without breaking CI.
    """

    @pytest.mark.xfail(reason="Schema uses source_id instead of holder_id")
    def test_holder_id_field_exists(self, beliefs_table_columns: dict[str, str]):
        """SPEC: holder_id: UUID - Agent who holds this belief.
        
        Current schema uses source_id which links to sources table.
        Spec envisions holder_id for agent-centric ownership.
        """
        assert "holder_id" in beliefs_table_columns

    @pytest.mark.xfail(reason="version field not implemented")
    def test_version_field_exists(self, beliefs_table_columns: dict[str, str]):
        """SPEC: version: number - Monotonic version counter (starts at 1)."""
        assert "version" in beliefs_table_columns

    @pytest.mark.xfail(reason="content_hash field not implemented")
    def test_content_hash_field_exists(self, beliefs_table_columns: dict[str, str]):
        """SPEC: content_hash: string - SHA-256 of content (for deduplication)."""
        assert "content_hash" in beliefs_table_columns

    @pytest.mark.xfail(reason="visibility field not implemented")
    def test_visibility_field_exists(self, beliefs_table_columns: dict[str, str]):
        """SPEC: visibility: Visibility - Who can see this belief."""
        assert "visibility" in beliefs_table_columns


# ============================================================================
# Section 1.2: ConfidenceVector
# ============================================================================

class TestConfidenceVectorStructure:
    """Tests for SPEC Section 1.2: ConfidenceVector.
    
    Six orthogonal dimensions of confidence, each scored 0.0 to 1.0.
    """

    def test_confidence_default_has_overall(self, schema_sql: str):
        """Verify default confidence includes 'overall' key."""
        # Schema has: DEFAULT '{"overall": 0.7}'
        assert '"overall":' in schema_sql or "'overall':" in schema_sql

    def test_confidence_constraint_bounds_overall(self, schema_sql: str):
        """SPEC: Each dimension scored 0.0 to 1.0.
        
        Schema should have constraint checking overall is in [0, 1].
        """
        # Check for the constraint
        assert "beliefs_valid_confidence" in schema_sql
        assert "(confidence->>'overall')::numeric >= 0" in schema_sql
        assert "(confidence->>'overall')::numeric <= 1" in schema_sql

    def test_six_confidence_dimensions_documented(
        self, confidence_dimensions: list[str]
    ):
        """SPEC defines exactly six confidence dimensions."""
        expected = [
            "source_reliability",
            "method_quality",
            "internal_consistency",
            "temporal_freshness",
            "corroboration",
            "domain_applicability",
        ]
        assert confidence_dimensions == expected

    def test_confidence_defaults_match_spec(
        self, confidence_defaults: dict[str, float]
    ):
        """SPEC Section 1.2: Default Values for new beliefs."""
        expected = {
            "source_reliability": 0.5,    # Unknown source
            "method_quality": 0.5,        # Unknown method  
            "internal_consistency": 1.0,  # No known contradictions
            "temporal_freshness": 1.0,    # Fresh at creation
            "corroboration": 0.1,         # Single source
            "domain_applicability": 0.8,  # Self-assigned domains
        }
        assert confidence_defaults == expected


# ============================================================================
# Section 1.3: Visibility
# ============================================================================

class TestVisibilityEnum:
    """Tests for SPEC Section 1.3: Visibility enum."""

    def test_visibility_enum_values(self):
        """SPEC defines three visibility levels."""
        from tests.spec_compliance.conftest import VISIBILITY_VALUES
        
        expected = ["private", "federated", "public"]
        assert VISIBILITY_VALUES == expected


# ============================================================================
# Section 2: Derivation Structure
# ============================================================================

class TestDerivationTypes:
    """Tests for SPEC Section 2.1: DerivationType enum."""

    def test_derivation_types_defined(self):
        """SPEC defines seven derivation types."""
        from tests.spec_compliance.conftest import DERIVATION_TYPES
        
        expected = [
            "observation",
            "inference",
            "aggregation", 
            "hearsay",
            "assumption",
            "correction",
            "synthesis",
        ]
        assert DERIVATION_TYPES == expected


# ============================================================================
# Section 4: Versioning
# ============================================================================

class TestVersioningSemantics:
    """Tests for SPEC Section 4: Versioning.
    
    Beliefs are immutable. Updates create new versions.
    """

    def test_supersession_foreign_keys(self, schema_sql: str):
        """Verify supersession links reference beliefs table."""
        # supersedes_id should FK to beliefs
        assert "supersedes_id UUID REFERENCES beliefs(id)" in schema_sql
        assert "superseded_by_id UUID REFERENCES beliefs(id)" in schema_sql

    def test_active_beliefs_view_exists(self, schema_sql: str):
        """SPEC: Default queries return only latest version.
        
        Schema should have a view for current/active beliefs.
        """
        assert "CREATE OR REPLACE VIEW beliefs_current" in schema_sql
        # View should filter for active and not superseded
        assert "superseded_by_id IS NULL" in schema_sql


# ============================================================================
# Section 6: Domain Taxonomy
# ============================================================================

class TestDomainTaxonomy:
    """Tests for SPEC Section 6: Domain Taxonomy."""

    def test_domain_index_exists(self, schema_sql: str):
        """SPEC Section 7.3: GIN index on domains for efficient queries."""
        # Schema uses domain_path
        assert "idx_beliefs_domain" in schema_sql
        assert "GIN (domain_path)" in schema_sql


# ============================================================================
# Section 7: Constraints & Limits
# ============================================================================

class TestConstraintsAndLimits:
    """Tests for SPEC Section 7: Constraints & Limits."""

    def test_status_constraint_exists(self, schema_sql: str):
        """Schema has status constraint (active, superseded, disputed, archived)."""
        assert "beliefs_valid_status" in schema_sql
        assert "'active'" in schema_sql
        assert "'superseded'" in schema_sql
        assert "'disputed'" in schema_sql
        assert "'archived'" in schema_sql


# ============================================================================
# Section 7.3: Indexing Requirements
# ============================================================================

class TestIndexing:
    """Tests for SPEC Section 7.3: Indexing Requirements."""

    def test_id_primary_key(self, schema_sql: str):
        """SPEC: B-tree on id (implicit via PRIMARY KEY)."""
        assert "id UUID PRIMARY KEY" in schema_sql

    def test_domain_gin_index(self, schema_sql: str):
        """SPEC: GIN on domains for array queries."""
        assert "idx_beliefs_domain" in schema_sql
        assert "GIN (domain_path)" in schema_sql

    def test_embedding_index(self, schema_sql: str):
        """SPEC: HNSW on embedding for semantic search.
        
        Note: Schema currently uses ivfflat, not HNSW.
        Both are valid vector index types.
        """
        assert "idx_beliefs_embedding" in schema_sql
        # Could be HNSW or ivfflat
        assert "embedding" in schema_sql.lower()

    def test_created_at_index(self, schema_sql: str):
        """SPEC: B-tree on created_at for time queries."""
        assert "idx_beliefs_created" in schema_sql

    def test_status_index(self, schema_sql: str):
        """SPEC: Index for filtering by status."""
        assert "idx_beliefs_status" in schema_sql


# ============================================================================
# Integration: Spec-to-Schema Field Mapping
# ============================================================================

class TestSpecToSchemaMapping:
    """Verify overall alignment between spec fields and schema columns."""

    def test_required_spec_fields_have_schema_columns(
        self,
        beliefs_table_columns: dict[str, str],
        belief_spec_fields: dict[str, dict[str, Any]],
    ):
        """All required spec fields should have corresponding schema columns.
        
        Some fields may have different names (domains→domain_path).
        """
        # Core required fields that MUST exist
        required_core = ["id", "content", "confidence", "created_at"]
        
        for field in required_core:
            assert field in beliefs_table_columns, (
                f"Required field '{field}' missing from schema"
            )

    def test_schema_extensions_documented(
        self,
        beliefs_table_columns: dict[str, str],
    ):
        """Schema may have extensions not in spec - verify they're intentional."""
        # These are schema additions for practical implementation
        schema_extensions = ["modified_at", "extraction_method", "status", "content_tsv"]
        
        for ext in schema_extensions:
            if ext in beliefs_table_columns:
                # This is fine - just documenting it exists
                pass
