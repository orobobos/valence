"""Tests for the embeddings CLI commands.

Tests cover:
1. Argument parsing for `valence embeddings backfill`
2. Dry-run mode (no mutations, shows counts)
3. Content-type filtering
4. Force mode (re-embed all)
5. Normal backfill (delegates to service)
6. Error handling
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from valence.cli.main import app, cmd_embeddings

# ============================================================================
# Argument Parsing
# ============================================================================


class TestEmbeddingsArgParsing:
    """Test CLI argument parsing for embeddings commands."""

    def test_embeddings_backfill_defaults(self):
        """Parse embeddings backfill with defaults."""
        parser = app()
        args = parser.parse_args(["embeddings", "backfill"])
        assert args.command == "embeddings"
        assert args.embeddings_command == "backfill"
        assert args.batch_size == 100
        assert args.dry_run is False
        assert args.content_type is None
        assert args.force is False

    def test_embeddings_backfill_batch_size(self):
        """Parse --batch-size flag."""
        parser = app()
        args = parser.parse_args(["embeddings", "backfill", "--batch-size", "50"])
        assert args.batch_size == 50

    def test_embeddings_backfill_batch_size_short(self):
        """Parse -b short flag."""
        parser = app()
        args = parser.parse_args(["embeddings", "backfill", "-b", "200"])
        assert args.batch_size == 200

    def test_embeddings_backfill_dry_run(self):
        """Parse --dry-run flag."""
        parser = app()
        args = parser.parse_args(["embeddings", "backfill", "--dry-run"])
        assert args.dry_run is True

    def test_embeddings_backfill_content_type(self):
        """Parse --content-type flag."""
        parser = app()
        for ct in ("belief", "exchange", "pattern"):
            args = parser.parse_args(["embeddings", "backfill", "--content-type", ct])
            assert args.content_type == ct

    def test_embeddings_backfill_content_type_short(self):
        """Parse -t short flag."""
        parser = app()
        args = parser.parse_args(["embeddings", "backfill", "-t", "belief"])
        assert args.content_type == "belief"

    def test_embeddings_backfill_content_type_invalid(self):
        """Invalid content type raises error."""
        parser = app()
        with pytest.raises(SystemExit):
            parser.parse_args(["embeddings", "backfill", "--content-type", "invalid"])

    def test_embeddings_backfill_force(self):
        """Parse --force flag."""
        parser = app()
        args = parser.parse_args(["embeddings", "backfill", "--force"])
        assert args.force is True

    def test_embeddings_backfill_force_short(self):
        """Parse -f short flag."""
        parser = app()
        args = parser.parse_args(["embeddings", "backfill", "-f"])
        assert args.force is True

    def test_embeddings_backfill_all_flags(self):
        """Parse all flags together."""
        parser = app()
        args = parser.parse_args(
            [
                "embeddings",
                "backfill",
                "--batch-size",
                "25",
                "--dry-run",
                "--content-type",
                "belief",
                "--force",
            ]
        )
        assert args.batch_size == 25
        assert args.dry_run is True
        assert args.content_type == "belief"
        assert args.force is True

    def test_embeddings_requires_subcommand(self):
        """embeddings without subcommand raises error."""
        parser = app()
        with pytest.raises(SystemExit):
            parser.parse_args(["embeddings"])


# ============================================================================
# Mock Database Fixture
# ============================================================================


@pytest.fixture
def mock_db():
    """Create a mock database connection and cursor."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    return mock_conn, mock_cur


# ============================================================================
# Dry Run Tests
# ============================================================================


class TestBackfillDryRun:
    """Test dry-run mode shows counts without mutating."""

    @patch("valence.cli.commands.embeddings.get_db_connection")
    def test_dry_run_shows_counts(self, mock_get_conn, mock_db, capsys):
        """Dry run shows missing counts per type."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn

        # Return counts for belief, exchange, pattern
        mock_cur.fetchone.side_effect = [
            {"count": 10},  # beliefs missing
            {"count": 5},  # exchanges missing
            {"count": 3},  # patterns missing
        ]

        parser = app()
        args = parser.parse_args(["embeddings", "backfill", "--dry-run"])
        result = cmd_embeddings(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Dry run" in captured.out
        assert "10" in captured.out
        assert "5" in captured.out
        assert "3" in captured.out
        assert "18" in captured.out  # total

    @patch("valence.cli.commands.embeddings.get_db_connection")
    def test_dry_run_single_type(self, mock_get_conn, mock_db, capsys):
        """Dry run with --content-type shows only that type."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn

        mock_cur.fetchone.side_effect = [
            {"count": 15},  # beliefs missing
        ]

        parser = app()
        args = parser.parse_args(["embeddings", "backfill", "--dry-run", "-t", "belief"])
        result = cmd_embeddings(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Dry run" in captured.out
        assert "15" in captured.out

    @patch("valence.cli.commands.embeddings.get_db_connection")
    def test_dry_run_nothing_to_backfill(self, mock_get_conn, mock_db, capsys):
        """Dry run when nothing needs backfilling."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn

        mock_cur.fetchone.side_effect = [
            {"count": 0},
            {"count": 0},
            {"count": 0},
        ]

        parser = app()
        args = parser.parse_args(["embeddings", "backfill", "--dry-run"])
        result = cmd_embeddings(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Nothing to backfill" in captured.out

    @patch("valence.cli.commands.embeddings.get_db_connection")
    def test_dry_run_force_counts_all(self, mock_get_conn, mock_db, capsys):
        """Dry run with --force counts all records, not just missing."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn

        # Force mode counts all active records
        mock_cur.fetchone.side_effect = [
            {"count": 100},  # all beliefs
            {"count": 50},  # all exchanges
            {"count": 25},  # all patterns
        ]

        parser = app()
        args = parser.parse_args(["embeddings", "backfill", "--dry-run", "--force"])
        result = cmd_embeddings(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Dry run" in captured.out
        assert "Force mode" in captured.out
        assert "175" in captured.out  # total


# ============================================================================
# Normal Backfill Tests
# ============================================================================


class TestBackfillNormal:
    """Test normal backfill delegates to service layer."""

    @patch("our_embeddings.service.backfill_embeddings", return_value=5)
    @patch("valence.cli.commands.embeddings.get_db_connection")
    def test_backfill_calls_service(self, mock_get_conn, mock_backfill, mock_db, capsys):
        """Backfill delegates to backfill_embeddings service."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn

        # Counts
        mock_cur.fetchone.side_effect = [
            {"count": 5},  # beliefs missing
        ]

        parser = app()
        args = parser.parse_args(["embeddings", "backfill", "-t", "belief"])
        result = cmd_embeddings(args)

        assert result == 0
        mock_backfill.assert_called_once_with("belief", batch_size=100)

    @patch("our_embeddings.service.backfill_embeddings", side_effect=[3, 2, 1])
    @patch("valence.cli.commands.embeddings.get_db_connection")
    def test_backfill_all_types(self, mock_get_conn, mock_backfill, mock_db, capsys):
        """Backfill processes all types when no filter."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn

        mock_cur.fetchone.side_effect = [
            {"count": 3},
            {"count": 2},
            {"count": 1},
        ]

        parser = app()
        args = parser.parse_args(["embeddings", "backfill"])
        result = cmd_embeddings(args)

        assert result == 0
        assert mock_backfill.call_count == 3
        captured = capsys.readouterr()
        assert "complete" in captured.out.lower()

    @patch("our_embeddings.service.backfill_embeddings", return_value=10)
    @patch("valence.cli.commands.embeddings.get_db_connection")
    def test_backfill_custom_batch_size(self, mock_get_conn, mock_backfill, mock_db, capsys):
        """Batch size is passed through to service."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn

        mock_cur.fetchone.side_effect = [{"count": 10}]

        parser = app()
        args = parser.parse_args(["embeddings", "backfill", "-t", "belief", "-b", "25"])
        result = cmd_embeddings(args)

        assert result == 0
        mock_backfill.assert_called_once_with("belief", batch_size=25)

    @patch("valence.cli.commands.embeddings.get_db_connection")
    def test_backfill_nothing_to_do(self, mock_get_conn, mock_db, capsys):
        """Backfill exits cleanly when nothing needs embedding."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn

        mock_cur.fetchone.side_effect = [
            {"count": 0},
            {"count": 0},
            {"count": 0},
        ]

        parser = app()
        args = parser.parse_args(["embeddings", "backfill"])
        result = cmd_embeddings(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Nothing to backfill" in captured.out


# ============================================================================
# Force Mode Tests
# ============================================================================


class TestBackfillForce:
    """Test --force mode re-embeds existing records."""

    @patch("our_embeddings.service.embed_content", return_value={})
    @patch("valence.cli.commands.embeddings.get_db_connection")
    def test_force_reembeds_all(self, mock_get_conn, mock_embed, mock_db, capsys):
        """Force mode fetches and re-embeds all records."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn

        belief_id = uuid4()

        # Count query returns total active beliefs
        mock_cur.fetchone.side_effect = [{"count": 1}]
        # Fetch records for force re-embed
        mock_cur.fetchall.return_value = [
            {"id": belief_id, "content": "Test belief"},
        ]

        parser = app()
        args = parser.parse_args(
            [
                "embeddings",
                "backfill",
                "--force",
                "-t",
                "belief",
            ]
        )
        result = cmd_embeddings(args)

        assert result == 0
        mock_embed.assert_called_once_with("belief", str(belief_id), "Test belief")
        captured = capsys.readouterr()
        assert "Force mode" in captured.out


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestBackfillErrors:
    """Test error handling in backfill."""

    @patch("valence.cli.commands.embeddings.get_db_connection")
    def test_db_error_returns_nonzero(self, mock_get_conn, capsys):
        """Database connection failure returns non-zero exit code."""
        mock_get_conn.side_effect = Exception("Connection refused")

        parser = app()
        args = parser.parse_args(["embeddings", "backfill"])
        result = cmd_embeddings(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "failed" in captured.err.lower()


# ============================================================================
# Command Routing
# ============================================================================


class TestEmbeddingsRouting:
    """Test embeddings command routing."""

    def test_main_dispatches_to_embeddings(self):
        """main() dispatches 'embeddings' to cmd_embeddings via args.func."""
        parser = app()
        args = parser.parse_args(["embeddings", "backfill", "--dry-run"])

        # With modular registration, args.func is set by set_defaults()
        assert hasattr(args, "func")
        assert args.func is cmd_embeddings


# ============================================================================
# Migrate Argument Parsing (#364)
# ============================================================================


class TestMigrateArgParsing:
    """Test CLI argument parsing for embeddings migrate command."""

    def test_migrate_requires_model(self):
        """embeddings migrate requires --model."""
        parser = app()
        with pytest.raises(SystemExit):
            parser.parse_args(["embeddings", "migrate"])

    def test_migrate_known_model(self):
        """Parse known model with defaults auto-resolved."""
        parser = app()
        args = parser.parse_args(["embeddings", "migrate", "--model", "text-embedding-3-small"])
        assert args.model == "text-embedding-3-small"
        assert args.dims is None  # resolved at runtime
        assert args.dry_run is False

    def test_migrate_custom_model_with_dims(self):
        """Parse custom model with explicit dimensions."""
        parser = app()
        args = parser.parse_args(["embeddings", "migrate", "--model", "my-model", "--dims", "768"])
        assert args.model == "my-model"
        assert args.dims == 768

    def test_migrate_dry_run(self):
        """Parse --dry-run flag."""
        parser = app()
        args = parser.parse_args(["embeddings", "migrate", "--model", "text-embedding-3-small", "--dry-run"])
        assert args.dry_run is True

    def test_migrate_all_flags(self):
        """Parse all migrate flags together."""
        parser = app()
        args = parser.parse_args([
            "embeddings", "migrate",
            "--model", "custom/model",
            "--dims", "512",
            "--provider", "custom_provider",
            "--type-id", "custom_512",
            "--dry-run",
        ])
        assert args.model == "custom/model"
        assert args.dims == 512
        assert args.provider == "custom_provider"
        assert args.type_id == "custom_512"
        assert args.dry_run is True


# ============================================================================
# Migrate Command Tests (#364)
# ============================================================================


class TestMigrateCommand:
    """Test embeddings migrate command logic."""

    @patch("valence.cli.commands.embeddings.get_db_connection")
    def test_migrate_dry_run_known_model(self, mock_get_conn, capsys):
        """Dry run shows migration plan without making changes."""
        parser = app()
        args = parser.parse_args(["embeddings", "migrate", "--model", "text-embedding-3-small", "--dry-run"])
        result = cmd_embeddings(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Dry run" in captured.out
        assert "1536" in captured.out
        assert "text-embedding-3-small" in captured.out
        mock_get_conn.assert_not_called()

    def test_migrate_custom_model_missing_dims(self, capsys):
        """Custom model without --dims returns error."""
        parser = app()
        args = parser.parse_args(["embeddings", "migrate", "--model", "unknown-model"])
        result = cmd_embeddings(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Unknown model" in captured.err
        assert "--dims" in captured.err

    @patch("valence.cli.commands.embeddings.get_db_connection")
    def test_migrate_already_configured(self, mock_get_conn, mock_db, capsys):
        """Skip migration if already on the target model."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn

        mock_cur.fetchone.return_value = {
            "id": "local_bge_small",
            "dimensions": 384,
            "is_default": True,
        }

        parser = app()
        args = parser.parse_args(["embeddings", "migrate", "--model", "BAAI/bge-small-en-v1.5"])
        result = cmd_embeddings(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Already configured" in captured.out

    @patch("valence.cli.commands.embeddings.get_db_connection")
    def test_migrate_executes_steps(self, mock_get_conn, mock_db, capsys):
        """Migration executes all steps via migrate_embedding_dimensions function."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn
        mock_conn.autocommit = True  # will be set to False

        # First fetchone: current embedding type
        # Second fetchall: migration steps
        mock_cur.fetchone.return_value = {
            "id": "local_bge_small",
            "dimensions": 384,
            "is_default": True,
        }
        mock_cur.fetchall.return_value = [
            {"step": "register_type", "detail": "Registered openai_text3_small"},
            {"step": "complete", "detail": "Migration complete"},
        ]

        parser = app()
        args = parser.parse_args(["embeddings", "migrate", "--model", "text-embedding-3-small"])
        result = cmd_embeddings(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Migration to" in captured.out
        assert "1536" in captured.out
        mock_conn.commit.assert_called_once()

    @patch("valence.cli.commands.embeddings.get_db_connection")
    def test_migrate_error_rolls_back(self, mock_get_conn, mock_db, capsys):
        """Migration error triggers rollback."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn

        mock_cur.fetchone.side_effect = Exception("DB error")

        parser = app()
        args = parser.parse_args(["embeddings", "migrate", "--model", "text-embedding-3-small"])
        result = cmd_embeddings(args)

        assert result == 1
        mock_conn.rollback.assert_called_once()


# ============================================================================
# Status Argument Parsing (#364)
# ============================================================================


class TestStatusArgParsing:
    """Test CLI argument parsing for embeddings status command."""

    def test_status_parses(self):
        """embeddings status parses with no extra args."""
        parser = app()
        args = parser.parse_args(["embeddings", "status"])
        assert args.embeddings_command == "status"


# ============================================================================
# Status Command Tests (#364)
# ============================================================================


class TestStatusCommand:
    """Test embeddings status command logic."""

    @patch("valence.cli.commands.embeddings.get_db_connection")
    def test_status_shows_info(self, mock_get_conn, mock_db, capsys):
        """Status shows embedding types, columns, and coverage."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn

        # Calls: embedding_types, vector columns, coverage, total beliefs, embedded beliefs
        mock_cur.fetchall.side_effect = [
            [{"id": "local_bge_small", "provider": "local", "model": "BAAI/bge-small-en-v1.5", "dimensions": 384, "is_default": True, "status": "active"}],
            [{"table_name": "beliefs", "column_name": "embedding", "udt_name": "vector", "dims": 384}],
            [{"embedding_type_id": "local_bge_small", "content_type": "belief", "count": 42}],
        ]
        mock_cur.fetchone.side_effect = [
            {"count": 100},  # total beliefs
            {"count": 42},   # embedded beliefs
        ]

        parser = app()
        args = parser.parse_args(["embeddings", "status"])
        result = cmd_embeddings(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "local_bge_small" in captured.out
        assert "384" in captured.out
        assert "42/100" in captured.out

    @patch("valence.cli.commands.embeddings.get_db_connection")
    def test_status_error_handling(self, mock_get_conn, capsys):
        """Status handles connection errors gracefully."""
        mock_get_conn.side_effect = Exception("Cannot connect")

        parser = app()
        args = parser.parse_args(["embeddings", "status"])
        result = cmd_embeddings(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "failed" in captured.err.lower()
