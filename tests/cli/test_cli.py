"""Tests for Valence CLI.

Tests cover:
1. CLI argument parsing
2. Command dispatch
3. Derivation chain visibility
4. Conflict detection
5. Init/add/query/list happy paths
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from io import StringIO
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from valence.cli.main import (
    app,
    cmd_add,
    cmd_init,
    cmd_list,
    cmd_query,
    cmd_conflicts,
    cmd_stats,
    format_confidence,
    format_age,
    get_embedding,
)


# ============================================================================
# Unit Tests - Pure Functions
# ============================================================================

class TestFormatConfidence:
    """Test confidence formatting."""
    
    def test_format_overall(self):
        """Format overall confidence."""
        assert format_confidence({"overall": 0.8}) == "80%"
        assert format_confidence({"overall": 0.95}) == "95%"
        assert format_confidence({"overall": 0.123}) == "12%"
    
    def test_format_empty(self):
        """Format empty confidence."""
        assert format_confidence({}) == "?"
        assert format_confidence(None) == "?"
    
    def test_format_non_numeric(self):
        """Format non-numeric overall."""
        # Should truncate to 5 chars
        result = format_confidence({"overall": "high"})
        assert len(result) <= 5


class TestFormatAge:
    """Test age formatting."""
    
    def test_format_recent(self):
        """Format very recent time."""
        now = datetime.now(timezone.utc)
        assert format_age(now) == "now"
        assert format_age(now - timedelta(seconds=30)) == "now"
    
    def test_format_minutes(self):
        """Format minutes ago."""
        now = datetime.now(timezone.utc)
        assert format_age(now - timedelta(minutes=5)) == "5m"
        assert format_age(now - timedelta(minutes=59)) == "59m"
    
    def test_format_hours(self):
        """Format hours ago."""
        now = datetime.now(timezone.utc)
        assert format_age(now - timedelta(hours=3)) == "3h"
        assert format_age(now - timedelta(hours=23)) == "23h"
    
    def test_format_days(self):
        """Format days ago."""
        now = datetime.now(timezone.utc)
        assert format_age(now - timedelta(days=5)) == "5d"
        assert format_age(now - timedelta(days=29)) == "29d"
    
    def test_format_months(self):
        """Format months ago."""
        now = datetime.now(timezone.utc)
        assert format_age(now - timedelta(days=45)) == "1mo"
        assert format_age(now - timedelta(days=180)) == "6mo"
    
    def test_format_years(self):
        """Format years ago."""
        now = datetime.now(timezone.utc)
        assert format_age(now - timedelta(days=400)) == "1y"
        assert format_age(now - timedelta(days=800)) == "2y"
    
    def test_format_none(self):
        """Format None datetime."""
        assert format_age(None) == "?"
    
    def test_format_naive_datetime(self):
        """Format naive datetime (no timezone) - gets treated as UTC."""
        # Note: naive datetime gets treated as UTC, so the result depends on local TZ
        now = datetime.now()
        result = format_age(now - timedelta(hours=2))
        # Just verify it returns something reasonable (not "?")
        assert result != "?"
        assert any(c in result for c in ['h', 'm', 'd', 'y', 'now', 'mo'])


class TestArgumentParser:
    """Test CLI argument parsing."""
    
    def test_init_command(self):
        """Parse init command."""
        parser = app()
        args = parser.parse_args(['init'])
        assert args.command == 'init'
        assert args.force is False
    
    def test_init_force(self):
        """Parse init with force flag."""
        parser = app()
        args = parser.parse_args(['init', '--force'])
        assert args.force is True
    
    def test_add_command(self):
        """Parse add command."""
        parser = app()
        args = parser.parse_args(['add', 'Test belief content'])
        assert args.command == 'add'
        assert args.content == 'Test belief content'
    
    def test_add_with_options(self):
        """Parse add with all options."""
        parser = app()
        args = parser.parse_args([
            'add', 'Test belief',
            '--confidence', '0.9',
            '--domain', 'tech',
            '--domain', 'python',
            '--derivation-type', 'inference',
            '--derived-from', '12345678-1234-1234-1234-123456789abc',
            '--method', 'Derived from observation'
        ])
        assert args.content == 'Test belief'
        assert args.confidence == '0.9'
        assert args.domain == ['tech', 'python']
        assert args.derivation_type == 'inference'
        assert args.derived_from == '12345678-1234-1234-1234-123456789abc'
        assert args.method == 'Derived from observation'
    
    def test_query_command(self):
        """Parse query command."""
        parser = app()
        args = parser.parse_args(['query', 'search terms'])
        assert args.command == 'query'
        assert args.query == 'search terms'
        assert args.limit == 10  # default
        assert args.threshold == 0.3  # default
    
    def test_query_with_options(self):
        """Parse query with all options."""
        parser = app()
        args = parser.parse_args([
            'query', 'search terms',
            '--limit', '20',
            '--threshold', '0.5',
            '--domain', 'tech',
            '--chain'
        ])
        assert args.limit == 20
        assert args.threshold == 0.5
        assert args.domain == 'tech'
        assert args.chain is True
    
    def test_list_command(self):
        """Parse list command."""
        parser = app()
        args = parser.parse_args(['list'])
        assert args.command == 'list'
        assert args.limit == 10  # default
    
    def test_list_with_options(self):
        """Parse list with options."""
        parser = app()
        args = parser.parse_args(['list', '--limit', '50', '--domain', 'tech'])
        assert args.limit == 50
        assert args.domain == 'tech'
    
    def test_conflicts_command(self):
        """Parse conflicts command."""
        parser = app()
        args = parser.parse_args(['conflicts'])
        assert args.command == 'conflicts'
        assert args.threshold == 0.85  # default
        assert args.auto_record is False
    
    def test_conflicts_with_options(self):
        """Parse conflicts with options."""
        parser = app()
        args = parser.parse_args(['conflicts', '--threshold', '0.9', '--auto-record'])
        assert args.threshold == 0.9
        assert args.auto_record is True
    
    def test_stats_command(self):
        """Parse stats command."""
        parser = app()
        args = parser.parse_args(['stats'])
        assert args.command == 'stats'


# ============================================================================
# Integration Tests with Mocked Database
# ============================================================================

@pytest.fixture
def mock_db():
    """Create a mock database connection."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cur


class TestInitCommand:
    """Test init command."""
    
    @patch('valence.cli.main.get_db_connection')
    def test_init_already_exists(self, mock_get_conn, mock_db):
        """Init when schema already exists."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn
        
        # Schema exists
        mock_cur.fetchone.side_effect = [
            {'exists': True},  # beliefs table exists
            {'count': 42},     # belief count
        ]
        
        parser = app()
        args = parser.parse_args(['init'])
        result = cmd_init(args)
        
        assert result == 0
    
    @patch('valence.cli.main.get_db_connection')
    def test_init_creates_schema(self, mock_get_conn, mock_db):
        """Init creates schema when not exists."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn
        
        # Schema doesn't exist, then creation succeeds
        mock_cur.fetchone.side_effect = [
            {'exists': False},  # beliefs table doesn't exist
        ]
        
        parser = app()
        args = parser.parse_args(['init'])
        result = cmd_init(args)
        
        # Should have executed CREATE TABLE statements
        assert mock_cur.execute.called
        assert result == 0


class TestAddCommand:
    """Test add command."""
    
    @patch('valence.cli.main.get_db_connection')
    @patch('valence.cli.main.get_embedding')
    def test_add_basic(self, mock_embed, mock_get_conn, mock_db):
        """Add basic belief."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn
        mock_embed.return_value = None  # No embedding
        
        belief_id = uuid4()
        mock_cur.fetchone.return_value = {
            'id': belief_id,
            'created_at': datetime.now(timezone.utc)
        }
        
        parser = app()
        args = parser.parse_args(['add', 'Test belief content'])
        result = cmd_add(args)
        
        assert result == 0
        # Verify INSERT was called
        insert_calls = [c for c in mock_cur.execute.call_args_list 
                       if 'INSERT INTO beliefs' in str(c)]
        assert len(insert_calls) >= 1
    
    @patch('valence.cli.main.get_db_connection')
    @patch('valence.cli.main.get_embedding')
    def test_add_with_derivation(self, mock_embed, mock_get_conn, mock_db):
        """Add belief with derivation info."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn
        mock_embed.return_value = [0.1] * 1536  # Mock embedding
        
        belief_id = uuid4()
        mock_cur.fetchone.return_value = {
            'id': belief_id,
            'created_at': datetime.now(timezone.utc)
        }
        
        parser = app()
        args = parser.parse_args([
            'add', 'Derived belief',
            '--derivation-type', 'inference',
            '--method', 'Derived from logic'
        ])
        result = cmd_add(args)
        
        assert result == 0
        # Check derivation insert
        insert_calls = [c for c in mock_cur.execute.call_args_list 
                       if 'INSERT INTO belief_derivations' in str(c)]
        assert len(insert_calls) == 1


class TestQueryCommand:
    """Test query command with derivation chains."""
    
    @patch('valence.cli.main.get_db_connection')
    @patch('valence.cli.main.get_embedding')
    def test_query_shows_derivation(self, mock_embed, mock_get_conn, mock_db, capsys):
        """Query results show derivation chains."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn
        mock_embed.return_value = [0.1] * 1536
        
        source_id = uuid4()
        belief_id = uuid4()
        
        # Query result with derivation info
        mock_cur.fetchall.return_value = [{
            'id': belief_id,
            'content': 'Test belief content that was derived',
            'confidence': {'overall': 0.8},
            'domain_path': ['tech'],
            'created_at': datetime.now(timezone.utc),
            'extraction_method': 'inference',
            'supersedes_id': None,
            'similarity': 0.95,
            'derivation_type': 'inference',
            'method_description': 'Derived via logical deduction',
            'confidence_rationale': 'Strong evidence',
            'derivation_sources': [
                {'source_belief_id': str(source_id), 'contribution_type': 'primary', 'external_ref': None}
            ]
        }]
        
        # Source belief lookup
        mock_cur.fetchone.return_value = {'content': 'Original observation source'}
        
        parser = app()
        args = parser.parse_args(['query', 'test'])
        result = cmd_query(args)
        
        assert result == 0
        
        captured = capsys.readouterr()
        # Verify derivation info is shown
        assert 'Derivation: inference' in captured.out
        assert 'Method: Derived via logical deduction' in captured.out
        assert 'Derived from' in captured.out or 'primary' in captured.out
    
    @patch('valence.cli.main.get_db_connection')
    @patch('valence.cli.main.get_embedding')
    def test_query_no_results(self, mock_embed, mock_get_conn, mock_db, capsys):
        """Query with no results."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn
        mock_embed.return_value = None
        
        mock_cur.fetchall.return_value = []
        
        parser = app()
        args = parser.parse_args(['query', 'nonexistent'])
        result = cmd_query(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert 'No beliefs found' in captured.out


class TestConflictsCommand:
    """Test conflict detection."""
    
    @patch('valence.cli.main.get_db_connection')
    def test_conflicts_detects_negation(self, mock_get_conn, mock_db, capsys):
        """Detect conflicts with negation asymmetry."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn
        
        # Similar beliefs with opposite conclusions
        mock_cur.fetchall.return_value = [{
            'id_a': uuid4(),
            'content_a': 'Python is good for data science',
            'confidence_a': {'overall': 0.8},
            'created_a': datetime.now(timezone.utc),
            'id_b': uuid4(),
            'content_b': 'Python is not good for data science',
            'confidence_b': {'overall': 0.7},
            'created_b': datetime.now(timezone.utc),
            'similarity': 0.92,
        }]
        
        parser = app()
        args = parser.parse_args(['conflicts'])
        result = cmd_conflicts(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert 'potential conflict' in captured.out.lower() or 'Conflict' in captured.out
    
    @patch('valence.cli.main.get_db_connection')
    def test_conflicts_no_conflicts(self, mock_get_conn, mock_db, capsys):
        """No conflicts found."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn
        
        mock_cur.fetchall.return_value = []
        
        parser = app()
        args = parser.parse_args(['conflicts'])
        result = cmd_conflicts(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert 'No potential conflicts' in captured.out or 'no' in captured.out.lower()
    
    @patch('valence.cli.main.get_db_connection')
    def test_conflicts_auto_record(self, mock_get_conn, mock_db):
        """Auto-record detected conflicts as tensions."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn
        
        conflict_pair = {
            'id_a': uuid4(),
            'content_a': 'X is always true',
            'confidence_a': {'overall': 0.8},
            'created_a': datetime.now(timezone.utc),
            'id_b': uuid4(),
            'content_b': 'X is never true',
            'confidence_b': {'overall': 0.7},
            'created_b': datetime.now(timezone.utc),
            'similarity': 0.90,
        }
        
        mock_cur.fetchall.return_value = [conflict_pair]
        mock_cur.fetchone.return_value = {'id': uuid4()}
        
        parser = app()
        args = parser.parse_args(['conflicts', '--auto-record'])
        result = cmd_conflicts(args)
        
        assert result == 0
        # Verify tension was inserted
        insert_calls = [c for c in mock_cur.execute.call_args_list 
                       if 'INSERT INTO tensions' in str(c)]
        assert len(insert_calls) >= 1


class TestListCommand:
    """Test list command."""
    
    @patch('valence.cli.main.get_db_connection')
    def test_list_basic(self, mock_get_conn, mock_db, capsys):
        """List beliefs."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn
        
        mock_cur.fetchall.return_value = [
            {
                'id': uuid4(),
                'content': 'First belief',
                'confidence': {'overall': 0.9},
                'domain_path': ['tech'],
                'created_at': datetime.now(timezone.utc),
                'derivation_type': 'observation',
            },
            {
                'id': uuid4(),
                'content': 'Second belief',
                'confidence': {'overall': 0.7},
                'domain_path': [],
                'created_at': datetime.now(timezone.utc) - timedelta(hours=2),
                'derivation_type': 'inference',
            },
        ]
        
        parser = app()
        args = parser.parse_args(['list'])
        result = cmd_list(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert 'First belief' in captured.out
        assert 'Second belief' in captured.out


class TestStatsCommand:
    """Test stats command."""
    
    @patch('valence.cli.main.get_db_connection')
    def test_stats_basic(self, mock_get_conn, mock_db, capsys):
        """Show stats."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn
        
        mock_cur.fetchone.side_effect = [
            {'total': 100},
            {'active': 95},
            {'with_emb': 80},
            {'tensions': 3},
            {'count': 5},
            {'derivations': 50},
        ]
        
        parser = app()
        args = parser.parse_args(['stats'])
        result = cmd_stats(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert '100' in captured.out  # total beliefs
        assert 'Statistics' in captured.out


# ============================================================================
# Derivation Chain Tests
# ============================================================================

class TestDerivationChains:
    """Test derivation chain visibility."""
    
    @patch('valence.cli.main.get_db_connection')
    @patch('valence.cli.main.get_embedding')
    def test_shows_external_ref(self, mock_embed, mock_get_conn, mock_db, capsys):
        """Show external references in derivation."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn
        mock_embed.return_value = [0.1] * 1536
        
        mock_cur.fetchall.return_value = [{
            'id': uuid4(),
            'content': 'Belief from external source',
            'confidence': {'overall': 0.8},
            'domain_path': [],
            'created_at': datetime.now(timezone.utc),
            'extraction_method': 'hearsay',
            'supersedes_id': None,
            'similarity': 0.9,
            'derivation_type': 'hearsay',
            'method_description': 'Reported by trusted source',
            'confidence_rationale': None,
            'derivation_sources': [
                {'source_belief_id': None, 'contribution_type': 'primary', 'external_ref': 'https://example.com/doc'}
            ]
        }]
        
        parser = app()
        args = parser.parse_args(['query', 'external'])
        result = cmd_query(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert 'External' in captured.out
        assert 'example.com' in captured.out
    
    @patch('valence.cli.main.get_db_connection')
    @patch('valence.cli.main.get_embedding')
    def test_shows_supersession_chain(self, mock_embed, mock_get_conn, mock_db, capsys):
        """Show supersession chain when --chain flag used."""
        mock_conn, mock_cur = mock_db
        mock_get_conn.return_value = mock_conn
        mock_embed.return_value = [0.1] * 1536
        
        old_id = uuid4()
        
        mock_cur.fetchall.return_value = [{
            'id': uuid4(),
            'content': 'Updated belief',
            'confidence': {'overall': 0.9},
            'domain_path': [],
            'created_at': datetime.now(timezone.utc),
            'extraction_method': 'correction',
            'supersedes_id': old_id,
            'similarity': 0.95,
            'derivation_type': 'correction',
            'method_description': 'Corrected previous error',
            'confidence_rationale': None,
            'derivation_sources': []
        }]
        
        # Chain lookup
        mock_cur.fetchone.side_effect = [
            {'id': old_id, 'content': 'Original incorrect belief', 'supersedes_id': None},
        ]
        
        parser = app()
        args = parser.parse_args(['query', 'updated', '--chain'])
        result = cmd_query(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert 'Supersedes' in captured.out


# ============================================================================
# End-to-End Happy Path Test
# ============================================================================

class TestHappyPath:
    """Test the full happy path: pip install && valence init works."""
    
    def test_cli_module_imports(self):
        """Verify CLI module can be imported."""
        from valence.cli import main, app
        assert callable(main)
        assert callable(app)
    
    def test_help_output(self, capsys):
        """Verify help output works."""
        parser = app()
        
        # This should not raise
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(['--help'])
        
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert 'valence' in captured.out
        assert 'init' in captured.out
        assert 'add' in captured.out
        assert 'query' in captured.out
