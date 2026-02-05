"""Tests for migration 009: 384-dimensional embeddings."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


class TestMigration009LocalEmbeddings:
    """Tests for the 384-dimensional embedding migration."""

    @pytest.fixture
    def migration_sql(self) -> str:
        """Load the migration SQL file."""
        migration_path = (
            Path(__file__).parent.parent.parent
            / "migrations"
            / "009-local-embeddings.sql"
        )
        return migration_path.read_text()

    @pytest.fixture
    def rollback_sql(self) -> str:
        """Load the rollback SQL file."""
        rollback_path = (
            Path(__file__).parent.parent.parent
            / "migrations"
            / "009-local-embeddings-rollback.sql"
        )
        return rollback_path.read_text()

    def test_migration_file_exists(self):
        """Migration file should exist."""
        migration_path = (
            Path(__file__).parent.parent.parent
            / "migrations"
            / "009-local-embeddings.sql"
        )
        assert migration_path.exists(), "Migration 009 file not found"

    def test_rollback_file_exists(self):
        """Rollback file should exist."""
        rollback_path = (
            Path(__file__).parent.parent.parent
            / "migrations"
            / "009-local-embeddings-rollback.sql"
        )
        assert rollback_path.exists(), "Rollback 009 file not found"

    def test_migration_adds_embedding_384_columns(self, migration_sql: str):
        """Migration should add embedding_384 columns to all tables."""
        # Check for ALTER TABLE statements adding embedding_384
        assert "ADD COLUMN IF NOT EXISTS embedding_384 VECTOR(384)" in migration_sql
        assert "beliefs ADD COLUMN IF NOT EXISTS embedding_384" in migration_sql
        assert "vkb_exchanges ADD COLUMN IF NOT EXISTS embedding_384" in migration_sql
        assert "vkb_patterns ADD COLUMN IF NOT EXISTS embedding_384" in migration_sql

    def test_migration_creates_hnsw_indexes(self, migration_sql: str):
        """Migration should create HNSW indexes (not IVFFlat)."""
        # Check for HNSW index creation
        assert "USING hnsw" in migration_sql
        assert "idx_beliefs_embedding_384" in migration_sql
        assert "idx_vkb_exchanges_embedding_384" in migration_sql
        assert "idx_vkb_patterns_embedding_384" in migration_sql

        # Check for vector_cosine_ops
        assert "vector_cosine_ops" in migration_sql

        # HNSW parameters
        assert "m = 16" in migration_sql
        assert "ef_construction = 64" in migration_sql

    def test_migration_drops_old_indexes(self, migration_sql: str):
        """Migration should drop old IVFFlat indexes."""
        assert "DROP INDEX IF EXISTS idx_beliefs_embedding" in migration_sql
        assert "DROP INDEX IF EXISTS idx_vkb_exchanges_embedding" in migration_sql
        assert "DROP INDEX IF EXISTS idx_vkb_patterns_embedding" in migration_sql

    def test_migration_registers_new_embedding_type(self, migration_sql: str):
        """Migration should register bge-small-en-v1.5 as default."""
        assert "bge_small_en_v15" in migration_sql
        assert "'local'" in migration_sql
        assert "'BAAI/bge-small-en-v1.5'" in migration_sql
        assert "384" in migration_sql
        assert (
            "is_default = TRUE" in migration_sql
            or "is_default, TRUE" in migration_sql.replace(" ", "")
        )

    def test_migration_preserves_old_columns(self, migration_sql: str):
        """Migration should preserve old embedding columns for rollback."""
        # Should NOT drop the old embedding column
        assert "DROP COLUMN embedding" not in migration_sql
        assert "DROP COLUMN IF EXISTS embedding" not in migration_sql
        # Comments should indicate preservation
        assert "Old columns" in migration_sql or "keep old" in migration_sql.lower()

    def test_rollback_restores_ivfflat_indexes(self, rollback_sql: str):
        """Rollback should restore IVFFlat indexes."""
        assert "USING ivfflat" in rollback_sql
        assert "idx_beliefs_embedding" in rollback_sql
        assert "idx_vkb_exchanges_embedding" in rollback_sql
        assert "idx_vkb_patterns_embedding" in rollback_sql

    def test_rollback_drops_hnsw_indexes(self, rollback_sql: str):
        """Rollback should drop HNSW indexes."""
        assert "DROP INDEX IF EXISTS idx_beliefs_embedding_384" in rollback_sql
        assert "DROP INDEX IF EXISTS idx_vkb_exchanges_embedding_384" in rollback_sql
        assert "DROP INDEX IF EXISTS idx_vkb_patterns_embedding_384" in rollback_sql

    def test_rollback_drops_384_columns(self, rollback_sql: str):
        """Rollback should drop embedding_384 columns."""
        assert "DROP COLUMN IF EXISTS embedding_384" in rollback_sql

    def test_rollback_restores_openai_default(self, rollback_sql: str):
        """Rollback should restore OpenAI as default embedding type."""
        assert "openai_text3_small" in rollback_sql
        assert "is_default = TRUE" in rollback_sql

    def test_migration_has_verification(self, migration_sql: str):
        """Migration should include verification checks."""
        assert "RAISE EXCEPTION" in migration_sql or "RAISE NOTICE" in migration_sql
        # Should verify column and index counts
        assert (
            "new_cols" in migration_sql.lower()
            or "new columns" in migration_sql.lower()
        )

    def test_rollback_has_verification(self, rollback_sql: str):
        """Rollback should include verification checks."""
        assert "RAISE" in rollback_sql


class TestMigration009Stats:
    """Tests for updated stats function."""

    @pytest.fixture
    def migration_sql(self) -> str:
        """Load the migration SQL file."""
        migration_path = (
            Path(__file__).parent.parent.parent
            / "migrations"
            / "009-local-embeddings.sql"
        )
        return migration_path.read_text()

    def test_stats_function_tracks_384_embeddings(self, migration_sql: str):
        """Stats function should track 384-dim embedding coverage."""
        assert "beliefs_with_embeddings_384" in migration_sql
        assert "embedding_384 IS NOT NULL" in migration_sql


class TestMigration009Integration:
    """Integration tests for migration 009 (requires database)."""

    @pytest.fixture
    def mock_cursor(self):
        """Create a mock database cursor."""
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        return cursor

    def test_migration_sql_is_valid_postgres(self, mock_cursor):
        """Migration SQL should be valid PostgreSQL syntax (basic check)."""
        migration_path = (
            Path(__file__).parent.parent.parent
            / "migrations"
            / "009-local-embeddings.sql"
        )
        sql = migration_path.read_text()

        # Basic syntax checks
        assert sql.count("(") == sql.count(")"), "Mismatched parentheses"
        assert "--" in sql, "Should have comments"
        assert ";" in sql, "Should have statement terminators"

        # Check for common SQL errors
        assert (
            "ALTER TABLES" not in sql
        ), "Invalid: ALTER TABLES (should be ALTER TABLE)"
        assert "CREAT INDEX" not in sql, "Typo: CREAT INDEX"
        assert "DROB" not in sql, "Typo: DROB"

    def test_rollback_sql_is_valid_postgres(self, mock_cursor):
        """Rollback SQL should be valid PostgreSQL syntax (basic check)."""
        rollback_path = (
            Path(__file__).parent.parent.parent
            / "migrations"
            / "009-local-embeddings-rollback.sql"
        )
        sql = rollback_path.read_text()

        # Basic syntax checks
        assert sql.count("(") == sql.count(")"), "Mismatched parentheses"
        assert "--" in sql, "Should have comments"
        assert ";" in sql, "Should have statement terminators"
