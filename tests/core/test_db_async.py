"""Tests for async database functionality in valence.core.db module."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest

from valence.core.exceptions import DatabaseException


# ============================================================================
# Async Mock Fixture
# ============================================================================


@pytest.fixture
def mock_asyncpg_pool():
    """Mock the asyncpg module for async database operations with proper async support."""
    mock_pool = MagicMock()
    mock_connection = AsyncMock()
    mock_transaction = MagicMock()

    # Configure the mock pool
    mock_pool.acquire = AsyncMock(return_value=mock_connection)
    mock_pool.release = AsyncMock()
    mock_pool.close = AsyncMock()
    mock_pool.get_size = MagicMock(return_value=5)
    mock_pool.get_idle_size = MagicMock(return_value=3)

    # Configure the mock connection
    mock_connection.fetch = AsyncMock(return_value=[])
    mock_connection.fetchrow = AsyncMock(return_value=None)
    mock_connection.fetchval = AsyncMock(return_value=None)
    mock_connection.execute = AsyncMock(return_value="")
    mock_connection.close = AsyncMock()

    # Configure transaction context manager
    mock_transaction.__aenter__ = AsyncMock(return_value=mock_transaction)
    mock_transaction.__aexit__ = AsyncMock(return_value=None)
    mock_connection.transaction = MagicMock(return_value=mock_transaction)

    # Mock create_pool as an async function that returns the pool
    async def mock_create_pool(*args, **kwargs):
        return mock_pool

    with patch("asyncpg.create_pool", side_effect=mock_create_pool) as mock_create:
        yield {
            "create_pool": mock_create,
            "pool": mock_pool,
            "connection": mock_connection,
            "transaction": mock_transaction,
        }


# ============================================================================
# AsyncConnectionPool Tests
# ============================================================================


class TestAsyncConnectionPool:
    """Tests for AsyncConnectionPool class."""

    @pytest.fixture(autouse=True)
    def reset_async_pool(self):
        """Reset the async connection pool singleton before each test."""
        from valence.core import db

        # Reset the async pool singleton
        db.AsyncConnectionPool._instance = None
        db._async_pool = None
        yield
        # Cleanup after test
        db.AsyncConnectionPool._instance = None
        db._async_pool = None

    def test_get_instance_sync_creates_instance(self, env_with_db_vars):
        """get_instance_sync should create a new instance if none exists."""
        from valence.core.db import AsyncConnectionPool

        pool = AsyncConnectionPool.get_instance_sync()
        assert pool is not None
        assert isinstance(pool, AsyncConnectionPool)

    def test_get_instance_sync_returns_same_instance(self, env_with_db_vars):
        """get_instance_sync should return the same instance on subsequent calls."""
        from valence.core.db import AsyncConnectionPool

        pool1 = AsyncConnectionPool.get_instance_sync()
        pool2 = AsyncConnectionPool.get_instance_sync()
        assert pool1 is pool2

    @pytest.mark.asyncio
    async def test_get_instance_async_creates_instance(self, env_with_db_vars):
        """get_instance should create a new instance if none exists."""
        from valence.core.db import AsyncConnectionPool

        pool = await AsyncConnectionPool.get_instance()
        assert pool is not None
        assert isinstance(pool, AsyncConnectionPool)

    @pytest.mark.asyncio
    async def test_get_instance_async_returns_same_instance(self, env_with_db_vars):
        """get_instance should return the same instance on subsequent calls."""
        from valence.core.db import AsyncConnectionPool

        pool1 = await AsyncConnectionPool.get_instance()
        pool2 = await AsyncConnectionPool.get_instance()
        assert pool1 is pool2

    @pytest.mark.asyncio
    async def test_ensure_pool_creates_pool(self, env_with_db_vars, mock_asyncpg_pool):
        """_ensure_pool should create a new asyncpg pool."""
        from valence.core.db import AsyncConnectionPool

        pool = AsyncConnectionPool.get_instance_sync()
        await pool._ensure_pool()

        mock_asyncpg_pool["create_pool"].assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_pool_uses_correct_params(self, env_with_db_vars, mock_asyncpg_pool, monkeypatch):
        """_ensure_pool should use connection and pool params from config."""
        from valence.core.db import AsyncConnectionPool
        from valence.core.config import clear_config_cache

        # Set custom pool config via env vars
        monkeypatch.setenv("VALENCE_DB_POOL_MIN", "3")
        monkeypatch.setenv("VALENCE_DB_POOL_MAX", "15")

        # Clear config cache so new env vars are read
        clear_config_cache()

        pool = AsyncConnectionPool.get_instance_sync()
        await pool._ensure_pool()

        call_kwargs = mock_asyncpg_pool["create_pool"].call_args[1]
        assert call_kwargs["min_size"] == 3
        assert call_kwargs["max_size"] == 15
        assert call_kwargs["database"] == "valence_test"  # From env_with_db_vars

    @pytest.mark.asyncio
    async def test_ensure_pool_raises_when_asyncpg_unavailable(self, env_with_db_vars):
        """_ensure_pool should raise DatabaseException if asyncpg not available."""
        from valence.core import db
        from valence.core.db import AsyncConnectionPool

        original_value = db.ASYNCPG_AVAILABLE
        try:
            db.ASYNCPG_AVAILABLE = False
            pool = AsyncConnectionPool.get_instance_sync()
            with pytest.raises(DatabaseException, match="asyncpg not installed"):
                await pool._ensure_pool()
        finally:
            db.ASYNCPG_AVAILABLE = original_value

    @pytest.mark.asyncio
    async def test_ensure_pool_handles_postgres_error(self, env_with_db_vars):
        """_ensure_pool should raise DatabaseException on PostgresError."""
        import asyncpg
        from valence.core.db import AsyncConnectionPool

        with patch("asyncpg.create_pool", side_effect=asyncpg.PostgresError("Connection failed")):
            pool = AsyncConnectionPool.get_instance_sync()
            with pytest.raises(DatabaseException, match="Failed to create async connection pool"):
                await pool._ensure_pool()

    @pytest.mark.asyncio
    async def test_ensure_pool_handles_os_error(self, env_with_db_vars):
        """_ensure_pool should raise DatabaseException on OSError."""
        from valence.core.db import AsyncConnectionPool

        with patch("asyncpg.create_pool", side_effect=OSError("Network unreachable")):
            pool = AsyncConnectionPool.get_instance_sync()
            with pytest.raises(DatabaseException, match="Failed to connect to database"):
                await pool._ensure_pool()

    @pytest.mark.asyncio
    async def test_get_connection_from_pool(self, env_with_db_vars, mock_asyncpg_pool):
        """get_connection should acquire a connection from the pool."""
        from valence.core.db import AsyncConnectionPool

        pool = AsyncConnectionPool.get_instance_sync()
        conn = await pool.get_connection()

        assert conn is mock_asyncpg_pool["connection"]
        mock_asyncpg_pool["pool"].acquire.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_connection_raises_on_error(self, env_with_db_vars, mock_asyncpg_pool):
        """get_connection should raise DatabaseException on PostgresError."""
        import asyncpg
        from valence.core.db import AsyncConnectionPool

        mock_asyncpg_pool["pool"].acquire.side_effect = asyncpg.PostgresError("Pool exhausted")

        pool = AsyncConnectionPool.get_instance_sync()
        await pool._ensure_pool()
        with pytest.raises(DatabaseException, match="Database error"):
            await pool.get_connection()

    @pytest.mark.asyncio
    async def test_put_connection_releases_to_pool(self, env_with_db_vars, mock_asyncpg_pool):
        """put_connection should release the connection back to the pool."""
        from valence.core.db import AsyncConnectionPool

        pool = AsyncConnectionPool.get_instance_sync()
        conn = await pool.get_connection()
        await pool.put_connection(conn)

        mock_asyncpg_pool["pool"].release.assert_called_once_with(conn)

    @pytest.mark.asyncio
    async def test_put_connection_handles_error(self, env_with_db_vars, mock_asyncpg_pool):
        """put_connection should close connection if release fails."""
        from valence.core.db import AsyncConnectionPool

        mock_asyncpg_pool["pool"].release.side_effect = Exception("Release failed")

        pool = AsyncConnectionPool.get_instance_sync()
        conn = await pool.get_connection()
        await pool.put_connection(conn)

        conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_put_connection_with_none_pool(self, env_with_db_vars):
        """put_connection should handle None pool gracefully."""
        from valence.core.db import AsyncConnectionPool

        pool = AsyncConnectionPool.get_instance_sync()
        # Pool is None, should not raise
        await pool.put_connection(MagicMock())

    @pytest.mark.asyncio
    async def test_close_all_closes_pool(self, env_with_db_vars, mock_asyncpg_pool):
        """close_all should close the pool and reset it to None."""
        from valence.core.db import AsyncConnectionPool

        pool = AsyncConnectionPool.get_instance_sync()
        await pool._ensure_pool()
        await pool.close_all()

        mock_asyncpg_pool["pool"].close.assert_called_once()
        assert pool._pool is None

    def test_get_stats_uninitialized(self, env_with_db_vars):
        """get_stats should return uninitialized stats when pool not created."""
        from valence.core.db import AsyncConnectionPool

        pool = AsyncConnectionPool.get_instance_sync()
        stats = pool.get_stats()

        assert stats["initialized"] is False
        assert stats["type"] == "async"
        assert "min_connections" in stats
        assert "max_connections" in stats

    @pytest.mark.asyncio
    async def test_get_stats_initialized(self, env_with_db_vars, mock_asyncpg_pool):
        """get_stats should return pool statistics when initialized."""
        from valence.core.db import AsyncConnectionPool

        mock_asyncpg_pool["pool"].get_size.return_value = 5
        mock_asyncpg_pool["pool"].get_idle_size.return_value = 3

        pool = AsyncConnectionPool.get_instance_sync()
        await pool._ensure_pool()
        stats = pool.get_stats()

        assert stats["initialized"] is True
        assert stats["size"] == 5
        assert stats["free_size"] == 3
        assert stats["type"] == "async"


# ============================================================================
# Module-Level Async Functions Tests
# ============================================================================


class TestAsyncModuleFunctions:
    """Tests for module-level async functions."""

    @pytest.fixture(autouse=True)
    def reset_async_pool(self):
        """Reset the async connection pool singleton before each test."""
        from valence.core import db

        db.AsyncConnectionPool._instance = None
        db._async_pool = None
        yield
        db.AsyncConnectionPool._instance = None
        db._async_pool = None

    @pytest.mark.asyncio
    async def test_async_get_connection(self, env_with_db_vars, mock_asyncpg_pool):
        """async_get_connection should get a connection from the pool."""
        from valence.core.db import async_get_connection

        conn = await async_get_connection()
        assert conn is mock_asyncpg_pool["connection"]

    @pytest.mark.asyncio
    async def test_async_put_connection(self, env_with_db_vars, mock_asyncpg_pool):
        """async_put_connection should release connection to the pool."""
        from valence.core.db import async_get_connection, async_put_connection

        conn = await async_get_connection()
        await async_put_connection(conn)

        mock_asyncpg_pool["pool"].release.assert_called_once_with(conn)

    @pytest.mark.asyncio
    async def test_async_close_pool(self, env_with_db_vars, mock_asyncpg_pool):
        """async_close_pool should close the async connection pool."""
        from valence.core.db import async_get_connection, async_close_pool, _get_async_pool

        # Initialize pool
        await async_get_connection()
        pool = _get_async_pool()
        
        await async_close_pool()
        mock_asyncpg_pool["pool"].close.assert_called_once()

    def test_get_async_pool_stats(self, env_with_db_vars):
        """get_async_pool_stats should return pool statistics."""
        from valence.core.db import get_async_pool_stats

        stats = get_async_pool_stats()
        assert "initialized" in stats
        assert "type" in stats


# ============================================================================
# async_cursor Context Manager Tests
# ============================================================================


class TestAsyncCursor:
    """Tests for async_cursor context manager."""

    @pytest.fixture(autouse=True)
    def reset_async_pool(self):
        """Reset the async connection pool singleton before each test."""
        from valence.core import db

        db.AsyncConnectionPool._instance = None
        db._async_pool = None
        yield
        db.AsyncConnectionPool._instance = None
        db._async_pool = None

    @pytest.mark.asyncio
    async def test_async_cursor_yields_connection(self, env_with_db_vars, mock_asyncpg_pool):
        """async_cursor should yield a connection within a transaction."""
        from valence.core.db import async_cursor

        async with async_cursor() as conn:
            assert conn is mock_asyncpg_pool["connection"]

    @pytest.mark.asyncio
    async def test_async_cursor_starts_transaction(self, env_with_db_vars, mock_asyncpg_pool):
        """async_cursor should start a transaction."""
        from valence.core.db import async_cursor

        async with async_cursor() as conn:
            pass

        mock_asyncpg_pool["connection"].transaction.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_cursor_releases_connection(self, env_with_db_vars, mock_asyncpg_pool):
        """async_cursor should release connection after use."""
        from valence.core.db import async_cursor

        async with async_cursor() as conn:
            pass

        mock_asyncpg_pool["pool"].release.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_cursor_handles_unique_violation(self, env_with_db_vars, mock_asyncpg_pool):
        """async_cursor should convert UniqueViolationError to DatabaseException."""
        import asyncpg
        from valence.core.db import async_cursor

        mock_asyncpg_pool["transaction"].__aenter__.side_effect = asyncpg.UniqueViolationError("Duplicate key")

        with pytest.raises(DatabaseException, match="Integrity constraint violation"):
            async with async_cursor() as conn:
                pass

    @pytest.mark.asyncio
    async def test_async_cursor_handles_syntax_error(self, env_with_db_vars, mock_asyncpg_pool):
        """async_cursor should convert PostgresSyntaxError to DatabaseException."""
        import asyncpg
        from valence.core.db import async_cursor

        mock_asyncpg_pool["transaction"].__aenter__.side_effect = asyncpg.PostgresSyntaxError("Syntax error")

        with pytest.raises(DatabaseException, match="SQL error"):
            async with async_cursor() as conn:
                pass

    @pytest.mark.asyncio
    async def test_async_cursor_handles_postgres_error(self, env_with_db_vars, mock_asyncpg_pool):
        """async_cursor should convert PostgresError to DatabaseException."""
        import asyncpg
        from valence.core.db import async_cursor

        mock_asyncpg_pool["transaction"].__aenter__.side_effect = asyncpg.PostgresError("Some error")

        with pytest.raises(DatabaseException, match="Database error"):
            async with async_cursor() as conn:
                pass


# ============================================================================
# async_connection_context Tests
# ============================================================================


class TestAsyncConnectionContext:
    """Tests for async_connection_context context manager."""

    @pytest.fixture(autouse=True)
    def reset_async_pool(self):
        """Reset the async connection pool singleton before each test."""
        from valence.core import db

        db.AsyncConnectionPool._instance = None
        db._async_pool = None
        yield
        db.AsyncConnectionPool._instance = None
        db._async_pool = None

    @pytest.mark.asyncio
    async def test_async_connection_context_yields_connection(self, env_with_db_vars, mock_asyncpg_pool):
        """async_connection_context should yield a connection."""
        from valence.core.db import async_connection_context

        async with async_connection_context() as conn:
            assert conn is mock_asyncpg_pool["connection"]

    @pytest.mark.asyncio
    async def test_async_connection_context_no_auto_transaction(self, env_with_db_vars, mock_asyncpg_pool):
        """async_connection_context should not start automatic transaction."""
        from valence.core.db import async_connection_context

        async with async_connection_context() as conn:
            pass

        # Transaction is NOT automatically started
        mock_asyncpg_pool["connection"].transaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_connection_context_releases_connection(self, env_with_db_vars, mock_asyncpg_pool):
        """async_connection_context should release connection after use."""
        from valence.core.db import async_connection_context

        async with async_connection_context() as conn:
            pass

        mock_asyncpg_pool["pool"].release.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_connection_context_handles_unique_violation(self, env_with_db_vars, mock_asyncpg_pool):
        """async_connection_context should convert UniqueViolationError to DatabaseException."""
        import asyncpg
        from valence.core.db import async_connection_context

        with pytest.raises(DatabaseException, match="Integrity constraint violation"):
            async with async_connection_context() as conn:
                raise asyncpg.UniqueViolationError("Duplicate key")

    @pytest.mark.asyncio
    async def test_async_connection_context_handles_syntax_error(self, env_with_db_vars, mock_asyncpg_pool):
        """async_connection_context should convert PostgresSyntaxError to DatabaseException."""
        import asyncpg
        from valence.core.db import async_connection_context

        with pytest.raises(DatabaseException, match="SQL error"):
            async with async_connection_context() as conn:
                raise asyncpg.PostgresSyntaxError("Syntax error")

    @pytest.mark.asyncio
    async def test_async_connection_context_handles_postgres_error(self, env_with_db_vars, mock_asyncpg_pool):
        """async_connection_context should convert PostgresError to DatabaseException."""
        import asyncpg
        from valence.core.db import async_connection_context

        with pytest.raises(DatabaseException, match="Database error"):
            async with async_connection_context() as conn:
                raise asyncpg.PostgresError("Some error")


# ============================================================================
# async_check_connection Tests
# ============================================================================


class TestAsyncCheckConnection:
    """Tests for async_check_connection function."""

    @pytest.fixture(autouse=True)
    def reset_async_pool(self):
        """Reset the async connection pool singleton before each test."""
        from valence.core import db

        db.AsyncConnectionPool._instance = None
        db._async_pool = None
        yield
        db.AsyncConnectionPool._instance = None
        db._async_pool = None

    @pytest.mark.asyncio
    async def test_async_check_connection_returns_true_on_success(self, env_with_db_vars, mock_asyncpg_pool):
        """async_check_connection should return True when connection works."""
        from valence.core.db import async_check_connection

        mock_asyncpg_pool["connection"].fetchval.return_value = 1

        result = await async_check_connection()
        assert result is True

    @pytest.mark.asyncio
    async def test_async_check_connection_returns_false_on_error(self, env_with_db_vars, mock_asyncpg_pool):
        """async_check_connection should return False on database error."""
        import asyncpg
        from valence.core.db import async_check_connection

        mock_asyncpg_pool["transaction"].__aenter__.side_effect = asyncpg.PostgresError("Connection failed")

        result = await async_check_connection()
        assert result is False

    @pytest.mark.asyncio
    async def test_async_check_connection_returns_false_on_exception(self, env_with_db_vars, mock_asyncpg_pool):
        """async_check_connection should return False on any exception."""
        from valence.core.db import async_check_connection

        mock_asyncpg_pool["transaction"].__aenter__.side_effect = Exception("Unexpected error")

        result = await async_check_connection()
        assert result is False


# ============================================================================
# async_init_schema Tests
# ============================================================================


class TestAsyncInitSchema:
    """Tests for async_init_schema function."""

    @pytest.fixture(autouse=True)
    def reset_async_pool(self):
        """Reset the async connection pool singleton before each test."""
        from valence.core import db

        db.AsyncConnectionPool._instance = None
        db._async_pool = None
        yield
        db.AsyncConnectionPool._instance = None
        db._async_pool = None

    @pytest.mark.asyncio
    async def test_async_init_schema_executes_sql_files(self, env_with_db_vars, mock_asyncpg_pool, tmp_path):
        """async_init_schema should execute schema SQL files."""
        from valence.core.db import async_init_schema

        # Create temporary schema files
        schema_sql = "CREATE TABLE test_table (id INT);"

        # Mock the schema directory path
        with patch("valence.core.db.Path") as mock_path:
            mock_schema_dir = MagicMock()
            mock_path.return_value.parent.parent.__truediv__.return_value = mock_schema_dir

            mock_schema_file = MagicMock()
            mock_schema_file.exists.return_value = True
            mock_procedures_file = MagicMock()
            mock_procedures_file.exists.return_value = True

            def mock_truediv(self_or_filename, filename=None):
                # Handle being called as a method (self, filename) or directly (filename)
                if filename is None:
                    filename = self_or_filename
                if filename == "schema.sql":
                    return mock_schema_file
                elif filename == "procedures.sql":
                    return mock_procedures_file
                return MagicMock()

            mock_schema_dir.__truediv__ = mock_truediv

            # Mock file reading
            with patch("builtins.open", mock_open(read_data=schema_sql)):
                await async_init_schema()

        # Check that execute was called
        assert mock_asyncpg_pool["connection"].execute.called

    @pytest.mark.asyncio
    async def test_async_init_schema_handles_missing_files(self, env_with_db_vars, mock_asyncpg_pool):
        """async_init_schema should skip non-existent schema files."""
        from valence.core.db import async_init_schema

        with patch("valence.core.db.Path") as mock_path:
            mock_schema_dir = MagicMock()
            mock_path.return_value.parent.parent.__truediv__.return_value = mock_schema_dir

            mock_schema_file = MagicMock()
            mock_schema_file.exists.return_value = False  # File doesn't exist

            mock_schema_dir.__truediv__.return_value = mock_schema_file

            await async_init_schema()

        # Execute should not be called for missing files
        mock_asyncpg_pool["connection"].execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_init_schema_raises_on_postgres_error(self, env_with_db_vars, mock_asyncpg_pool):
        """async_init_schema should raise DatabaseException on PostgresError."""
        import asyncpg
        from valence.core.db import async_init_schema

        with patch("valence.core.db.Path") as mock_path:
            mock_schema_dir = MagicMock()
            mock_path.return_value.parent.parent.__truediv__.return_value = mock_schema_dir

            mock_schema_file = MagicMock()
            mock_schema_file.exists.return_value = True
            mock_schema_dir.__truediv__.return_value = mock_schema_file

            mock_asyncpg_pool["connection"].execute.side_effect = asyncpg.PostgresError("SQL error")

            with patch("builtins.open", mock_open(read_data="INVALID SQL")):
                with pytest.raises(DatabaseException, match="Failed to initialize schema"):
                    await async_init_schema()


# ============================================================================
# async_get_schema_version Tests
# ============================================================================


class TestAsyncGetSchemaVersion:
    """Tests for async_get_schema_version function."""

    @pytest.fixture(autouse=True)
    def reset_async_pool(self):
        """Reset the async connection pool singleton before each test."""
        from valence.core import db

        db.AsyncConnectionPool._instance = None
        db._async_pool = None
        yield
        db.AsyncConnectionPool._instance = None
        db._async_pool = None

    @pytest.mark.asyncio
    async def test_async_get_schema_version_returns_version(self, env_with_db_vars, mock_asyncpg_pool):
        """async_get_schema_version should return the schema version."""
        from valence.core.db import async_get_schema_version

        mock_asyncpg_pool["connection"].fetchval.side_effect = [True, None]  # EXISTS, then version query
        mock_asyncpg_pool["connection"].fetchrow.return_value = {"version": "1.0.0"}

        version = await async_get_schema_version()
        assert version == "1.0.0"

    @pytest.mark.asyncio
    async def test_async_get_schema_version_returns_none_when_table_missing(self, env_with_db_vars, mock_asyncpg_pool):
        """async_get_schema_version should return None if schema_version table doesn't exist."""
        from valence.core.db import async_get_schema_version

        mock_asyncpg_pool["connection"].fetchval.return_value = False  # Table doesn't exist

        version = await async_get_schema_version()
        assert version is None

    @pytest.mark.asyncio
    async def test_async_get_schema_version_returns_none_on_error(self, env_with_db_vars, mock_asyncpg_pool):
        """async_get_schema_version should return None on error."""
        from valence.core.db import async_get_schema_version

        mock_asyncpg_pool["transaction"].__aenter__.side_effect = Exception("Query failed")

        version = await async_get_schema_version()
        assert version is None


# ============================================================================
# async_table_exists Tests
# ============================================================================


class TestAsyncTableExists:
    """Tests for async_table_exists function."""

    @pytest.fixture(autouse=True)
    def reset_async_pool(self):
        """Reset the async connection pool singleton before each test."""
        from valence.core import db

        db.AsyncConnectionPool._instance = None
        db._async_pool = None
        yield
        db.AsyncConnectionPool._instance = None
        db._async_pool = None

    @pytest.mark.asyncio
    async def test_async_table_exists_returns_true(self, env_with_db_vars, mock_asyncpg_pool):
        """async_table_exists should return True for existing tables."""
        from valence.core.db import async_table_exists

        mock_asyncpg_pool["connection"].fetchval.return_value = True

        exists = await async_table_exists("beliefs")
        assert exists is True

    @pytest.mark.asyncio
    async def test_async_table_exists_returns_false(self, env_with_db_vars, mock_asyncpg_pool):
        """async_table_exists should return False for non-existing tables."""
        from valence.core.db import async_table_exists

        mock_asyncpg_pool["connection"].fetchval.return_value = False

        exists = await async_table_exists("nonexistent_table")
        assert exists is False

    @pytest.mark.asyncio
    async def test_async_table_exists_returns_false_on_none(self, env_with_db_vars, mock_asyncpg_pool):
        """async_table_exists should return False when fetchval returns None."""
        from valence.core.db import async_table_exists

        mock_asyncpg_pool["connection"].fetchval.return_value = None

        exists = await async_table_exists("some_table")
        assert exists is False


# ============================================================================
# async_count_rows Tests
# ============================================================================


class TestAsyncCountRows:
    """Tests for async_count_rows function."""

    @pytest.fixture(autouse=True)
    def reset_async_pool(self):
        """Reset the async connection pool singleton before each test."""
        from valence.core import db

        db.AsyncConnectionPool._instance = None
        db._async_pool = None
        yield
        db.AsyncConnectionPool._instance = None
        db._async_pool = None

    @pytest.mark.asyncio
    async def test_async_count_rows_returns_count(self, env_with_db_vars, mock_asyncpg_pool):
        """async_count_rows should return the row count for a valid table."""
        from valence.core.db import async_count_rows

        mock_asyncpg_pool["connection"].fetchval.side_effect = ["beliefs", 42]  # table exists, then count

        count = await async_count_rows("beliefs")
        assert count == 42

    @pytest.mark.asyncio
    async def test_async_count_rows_rejects_invalid_table(self, env_with_db_vars, mock_asyncpg_pool):
        """async_count_rows should raise ValueError for tables not in allowlist."""
        from valence.core.db import async_count_rows

        with pytest.raises(ValueError, match="Table not in allowlist"):
            await async_count_rows("dangerous_table; DROP TABLE beliefs;")

    @pytest.mark.asyncio
    async def test_async_count_rows_rejects_nonexistent_table(self, env_with_db_vars, mock_asyncpg_pool):
        """async_count_rows should raise ValueError if table doesn't exist."""
        from valence.core.db import async_count_rows

        mock_asyncpg_pool["connection"].fetchval.return_value = None  # Table doesn't exist

        with pytest.raises(ValueError, match="Table does not exist"):
            await async_count_rows("beliefs")

    @pytest.mark.asyncio
    async def test_async_count_rows_returns_zero_on_none(self, env_with_db_vars, mock_asyncpg_pool):
        """async_count_rows should return 0 when count returns None."""
        from valence.core.db import async_count_rows

        mock_asyncpg_pool["connection"].fetchval.side_effect = ["beliefs", None]  # table exists, count is None

        count = await async_count_rows("beliefs")
        assert count == 0


# ============================================================================
# DatabaseStats.async_collect Tests
# ============================================================================


class TestDatabaseStatsAsyncCollect:
    """Tests for DatabaseStats.async_collect method."""

    @pytest.fixture(autouse=True)
    def reset_async_pool(self):
        """Reset the async connection pool singleton before each test."""
        from valence.core import db

        db.AsyncConnectionPool._instance = None
        db._async_pool = None
        yield
        db.AsyncConnectionPool._instance = None
        db._async_pool = None

    @pytest.mark.asyncio
    async def test_async_collect_returns_stats(self, env_with_db_vars, mock_asyncpg_pool):
        """async_collect should return DatabaseStats with counts."""
        from valence.core.db import DatabaseStats

        # Mock fetchval to return table exists then count for each table
        mock_asyncpg_pool["connection"].fetchval.side_effect = [
            "beliefs", 10,      # beliefs exists, count 10
            "entities", 20,    # entities exists, count 20
            "vkb_sessions", 5, # sessions exists, count 5
            "vkb_exchanges", 50,  # exchanges exists, count 50
            "vkb_patterns", 3,    # patterns exists, count 3
            "tensions", 2,        # tensions exists, count 2
        ]

        stats = await DatabaseStats.async_collect()

        assert stats.beliefs_count == 10
        assert stats.entities_count == 20
        assert stats.sessions_count == 5
        assert stats.exchanges_count == 50
        assert stats.patterns_count == 3
        assert stats.tensions_count == 2

    @pytest.mark.asyncio
    async def test_async_collect_handles_errors_gracefully(self, env_with_db_vars, mock_asyncpg_pool):
        """async_collect should handle errors and continue with other tables."""
        from valence.core.db import DatabaseStats

        # First table check fails, rest succeed
        mock_asyncpg_pool["connection"].fetchval.side_effect = [
            None,  # beliefs doesn't exist (raises ValueError)
            "entities", 20,    # entities exists, count 20
            "vkb_sessions", 5, # sessions exists, count 5
            None,  # exchanges doesn't exist
            "vkb_patterns", 3, # patterns exists, count 3
            "tensions", 2,     # tensions exists, count 2
        ]

        stats = await DatabaseStats.async_collect()

        # Failed tables should have 0 count
        assert stats.beliefs_count == 0
        assert stats.entities_count == 20
        assert stats.sessions_count == 5
        assert stats.exchanges_count == 0
        assert stats.patterns_count == 3
        assert stats.tensions_count == 2

    @pytest.mark.asyncio
    async def test_async_collect_to_dict(self, env_with_db_vars, mock_asyncpg_pool):
        """async_collect stats should convert to dict correctly."""
        from valence.core.db import DatabaseStats

        mock_asyncpg_pool["connection"].fetchval.side_effect = [
            "beliefs", 100,
            "entities", 50,
            "vkb_sessions", 25,
            "vkb_exchanges", 200,
            "vkb_patterns", 10,
            "tensions", 5,
        ]

        stats = await DatabaseStats.async_collect()
        stats_dict = stats.to_dict()

        assert stats_dict == {
            "beliefs": 100,
            "entities": 50,
            "sessions": 25,
            "exchanges": 200,
            "patterns": 10,
            "tensions": 5,
        }


# ============================================================================
# Connection Parameter Tests
# ============================================================================


class TestAsyncConnectionParams:
    """Tests for async connection parameter handling."""

    def test_get_async_connection_params_converts_dbname(self, env_with_db_vars):
        """get_async_connection_params should convert 'dbname' to 'database'."""
        from valence.core.db import get_async_connection_params

        params = get_async_connection_params()

        assert "database" in params
        assert "dbname" not in params
        assert params["database"] == "valence_test"  # From env_with_db_vars


# ============================================================================
# Concurrency Tests
# ============================================================================


class TestAsyncConcurrency:
    """Tests for async concurrency behavior."""

    @pytest.fixture(autouse=True)
    def reset_async_pool(self):
        """Reset the async connection pool singleton before each test."""
        from valence.core import db

        db.AsyncConnectionPool._instance = None
        db._async_pool = None
        yield
        db.AsyncConnectionPool._instance = None
        db._async_pool = None

    @pytest.mark.asyncio
    async def test_concurrent_get_instance_returns_same_pool(self, env_with_db_vars):
        """Concurrent get_instance calls should return the same instance."""
        from valence.core.db import AsyncConnectionPool

        # Get instance concurrently
        results = await asyncio.gather(
            AsyncConnectionPool.get_instance(),
            AsyncConnectionPool.get_instance(),
            AsyncConnectionPool.get_instance(),
        )

        # All should be the same instance
        assert results[0] is results[1]
        assert results[1] is results[2]

    @pytest.mark.asyncio
    async def test_concurrent_connections(self, env_with_db_vars, mock_asyncpg_pool):
        """Multiple concurrent connections should work."""
        from valence.core.db import async_cursor

        async def use_connection(n: int):
            async with async_cursor() as conn:
                await conn.fetchval(f"SELECT {n}")
                return n

        results = await asyncio.gather(
            use_connection(1),
            use_connection(2),
            use_connection(3),
        )

        assert results == [1, 2, 3]
