"""Tests for Valence Router CLI (cli/router.py).

Tests cover:
1. Argument parsing for start and status commands
2. _print_status helper function
3. cmd_status with mocked HTTP responses
4. Signal handling in cmd_start (partial - hard to test fully)
"""

from __future__ import annotations

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from valence.cli.router import (
    _print_status,
    async_main,
    cmd_status,
    create_parser,
    main,
)

# ============================================================================
# Argument Parser Tests
# ============================================================================


class TestCreateParser:
    """Test CLI argument parsing."""

    def test_no_command_shows_help(self):
        """No command prints help."""
        parser = create_parser()
        args = parser.parse_args([])
        assert args.command is None

    def test_start_command_defaults(self):
        """Start command with default values."""
        parser = create_parser()
        args = parser.parse_args(["start"])

        assert args.command == "start"
        assert args.host == "0.0.0.0"
        assert args.port == 8471
        assert args.seed is None
        assert args.max_connections == 100
        assert args.heartbeat_interval == 300

    def test_start_command_custom_values(self):
        """Start command with custom values."""
        parser = create_parser()
        args = parser.parse_args(
            [
                "start",
                "--host",
                "127.0.0.1",
                "--port",
                "9000",
                "--seed",
                "https://seed.example.com:8470",
                "--max-connections",
                "200",
                "--heartbeat-interval",
                "600",
            ]
        )

        assert args.host == "127.0.0.1"
        assert args.port == 9000
        assert args.seed == "https://seed.example.com:8470"
        assert args.max_connections == 200
        assert args.heartbeat_interval == 600

    def test_start_command_short_flags(self):
        """Start command with short flags."""
        parser = create_parser()
        args = parser.parse_args(
            [
                "start",
                "-p",
                "8500",
                "-s",
                "https://seed.valence.network",
                "-m",
                "50",
            ]
        )

        assert args.port == 8500
        assert args.seed == "https://seed.valence.network"
        assert args.max_connections == 50

    def test_start_command_json_flag(self):
        """Start command with JSON output flag."""
        parser = create_parser()
        args = parser.parse_args(["--json", "start"])
        assert args.json is True

    def test_status_command_defaults(self):
        """Status command with default values."""
        parser = create_parser()
        args = parser.parse_args(["status"])

        assert args.command == "status"
        assert args.host == "localhost"
        assert args.port == 8471

    def test_status_command_custom_values(self):
        """Status command with custom values."""
        parser = create_parser()
        args = parser.parse_args(
            [
                "--json",
                "status",
                "--host",
                "192.168.1.100",
                "--port",
                "8500",
            ]
        )

        assert args.host == "192.168.1.100"
        assert args.port == 8500
        assert args.json is True

    def test_global_verbose_flag(self):
        """Global verbose flag."""
        parser = create_parser()
        args = parser.parse_args(["-v", "status"])
        assert args.verbose is True

    def test_global_json_flag(self):
        """Global JSON flag."""
        parser = create_parser()
        args = parser.parse_args(["--json", "status"])
        assert args.json is True


# ============================================================================
# _print_status Helper Tests
# ============================================================================


class TestPrintStatus:
    """Test _print_status helper function."""

    def test_print_running_status(self, capsys):
        """Print status when router is running."""
        data = {
            "running": True,
            "host": "localhost",
            "port": 8471,
            "seed_url": "https://seed.example.com",
            "connections": {
                "current": 5,
                "max": 100,
                "total": 150,
            },
            "queues": {
                "nodes": 3,
                "total_messages": 42,
            },
            "metrics": {
                "messages_relayed": 1000,
                "messages_queued": 50,
                "messages_delivered": 950,
            },
        }

        _print_status(data)
        captured = capsys.readouterr()

        assert "🟢" in captured.out
        assert "Running" in captured.out
        assert "localhost:8471" in captured.out
        assert "seed.example.com" in captured.out
        assert "5/100" in captured.out
        assert "1000" in captured.out

    def test_print_stopped_status(self, capsys):
        """Print status when router is stopped."""
        data = {
            "running": False,
            "host": "0.0.0.0",
            "port": 8471,
        }

        _print_status(data)
        captured = capsys.readouterr()

        assert "🔴" in captured.out
        assert "Stopped" in captured.out

    def test_print_status_no_seed(self, capsys):
        """Print status without seed URL."""
        data = {
            "running": True,
            "host": "localhost",
            "port": 8471,
            "connections": {},
            "queues": {},
            "metrics": {},
        }

        _print_status(data)
        captured = capsys.readouterr()

        # Should not crash, seed line should not appear
        assert "VALENCE ROUTER STATUS" in captured.out
        assert "🌱" not in captured.out


# ============================================================================
# cmd_status Tests
# ============================================================================


class TestCmdStatus:
    """Test cmd_status function."""

    @pytest.mark.asyncio
    async def test_status_success_json(self):
        """Status command with JSON output."""
        args = argparse.Namespace(
            host="localhost",
            port=8471,
            json=True,
        )

        mock_response_data = {
            "running": True,
            "host": "localhost",
            "port": 8471,
        }

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_response_data)

        # Create async context manager for response
        mock_get_cm = MagicMock()
        mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_get_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_get_cm)

        # Create async context manager for session
        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_cm):
            result = await cmd_status(args)

        assert result == 0

    @pytest.mark.asyncio
    async def test_status_success_human_readable(self, capsys):
        """Status command with human-readable output."""
        args = argparse.Namespace(
            host="localhost",
            port=8471,
            json=False,
        )

        mock_response_data = {
            "running": True,
            "host": "localhost",
            "port": 8471,
            "connections": {"current": 5, "max": 100, "total": 50},
            "queues": {"nodes": 2, "total_messages": 10},
            "metrics": {
                "messages_relayed": 100,
                "messages_queued": 5,
                "messages_delivered": 95,
            },
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_response_data)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_ctx)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_ctx):
            result = await cmd_status(args)

        assert result == 0

    @pytest.mark.asyncio
    async def test_status_http_error(self, capsys):
        """Status command with HTTP error."""
        args = argparse.Namespace(
            host="localhost",
            port=8471,
            json=False,
        )

        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_ctx)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_ctx):
            result = await cmd_status(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "❌" in captured.err
        assert "500" in captured.err

    @pytest.mark.asyncio
    async def test_status_connection_error(self, capsys):
        """Status command when router is unreachable."""
        import aiohttp

        args = argparse.Namespace(
            host="localhost",
            port=8471,
            json=False,
        )

        mock_session_ctx = AsyncMock()
        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=aiohttp.ClientConnectorError(connection_key=MagicMock(), os_error=OSError("Connection refused")))
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_ctx):
            result = await cmd_status(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "❌" in captured.err
        assert "Cannot connect" in captured.err


# ============================================================================
# async_main Tests
# ============================================================================


class TestAsyncMain:
    """Test async_main dispatcher."""

    @pytest.mark.asyncio
    async def test_dispatch_to_status(self):
        """Dispatch to status command."""
        args = argparse.Namespace(
            command="status",
            host="localhost",
            port=8471,
            json=True,
            verbose=False,
        )

        with patch("valence.cli.router.cmd_status", new_callable=AsyncMock) as mock_status:
            mock_status.return_value = 0
            result = await async_main(args)

        assert result == 0
        mock_status.assert_called_once_with(args)

    @pytest.mark.asyncio
    async def test_dispatch_no_command(self, capsys):
        """No command shows help."""
        args = argparse.Namespace(
            command=None,
            verbose=False,
        )

        result = await async_main(args)

        assert result == 0

    @pytest.mark.asyncio
    async def test_verbose_logging(self):
        """Verbose flag enables debug logging."""
        args = argparse.Namespace(
            command=None,
            verbose=True,
        )

        with patch("logging.basicConfig") as mock_logging:
            await async_main(args)

            # Should configure DEBUG level
            mock_logging.assert_called()
            call_kwargs = mock_logging.call_args[1]
            assert call_kwargs.get("level") == 10  # DEBUG


# ============================================================================
# main() Entry Point Tests
# ============================================================================


class TestMain:
    """Test main entry point."""

    def test_main_no_command_returns_0(self):
        """Main with no command returns 0."""
        with patch("sys.argv", ["valence-router"]):
            result = main()
        assert result == 0

    def test_main_help_exits_0(self):
        """Main with --help exits with 0."""
        with patch("sys.argv", ["valence-router", "--help"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 0
