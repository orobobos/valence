"""Tests for Valence Seed Node CLI (cli/seed.py).

Tests cover:
1. Argument parsing for start, status, and discover commands
2. get_config_from_env function
3. cmd_status and cmd_discover with mocked HTTP responses
4. Error handling scenarios
"""

from __future__ import annotations

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from valence.cli.seed import (
    async_main,
    cmd_discover,
    cmd_status,
    create_parser,
    get_config_from_env,
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
        assert args.host is None  # Gets from env or default
        assert args.port is None
        assert args.seed_id is None
        assert args.peer == []

    def test_start_command_custom_values(self):
        """Start command with custom values."""
        parser = create_parser()
        args = parser.parse_args(
            [
                "start",
                "--host",
                "127.0.0.1",
                "--port",
                "8470",
                "--seed-id",
                "test-seed-001",
                "--peer",
                "https://peer1.example.com",
                "--peer",
                "https://peer2.example.com",
            ]
        )

        assert args.host == "127.0.0.1"
        assert args.port == 8470
        assert args.seed_id == "test-seed-001"
        assert args.peer == ["https://peer1.example.com", "https://peer2.example.com"]

    def test_start_command_short_flags(self):
        """Start command with short flags."""
        parser = create_parser()
        args = parser.parse_args(
            [
                "start",
                "-H",
                "0.0.0.0",
                "-p",
                "9000",
            ]
        )

        assert args.host == "0.0.0.0"
        assert args.port == 9000

    def test_status_command_defaults(self):
        """Status command with default values."""
        parser = create_parser()
        args = parser.parse_args(["status"])

        assert args.command == "status"
        assert args.url is None
        assert args.port is None
        assert args.json is False

    def test_status_command_custom_values(self):
        """Status command with custom values."""
        parser = create_parser()
        args = parser.parse_args(
            [
                "status",
                "--url",
                "https://seed.example.com",
                "--json",
            ]
        )

        assert args.url == "https://seed.example.com"
        assert args.json is True

    def test_status_command_short_flags(self):
        """Status command with short flags."""
        parser = create_parser()
        args = parser.parse_args(
            [
                "status",
                "-u",
                "http://localhost:8470",
                "-p",
                "8470",
            ]
        )

        assert args.url == "http://localhost:8470"
        assert args.port == 8470

    def test_discover_command_defaults(self):
        """Discover command with default values."""
        parser = create_parser()
        args = parser.parse_args(["discover"])

        assert args.command == "discover"
        assert args.url is None
        assert args.count == 5
        assert args.region is None
        assert args.feature == []
        assert args.json is False

    def test_discover_command_custom_values(self):
        """Discover command with custom values."""
        parser = create_parser()
        args = parser.parse_args(
            [
                "discover",
                "--url",
                "https://seed.example.com",
                "--count",
                "10",
                "--region",
                "us-west",
                "--feature",
                "fast",
                "--feature",
                "reliable",
                "--json",
            ]
        )

        assert args.url == "https://seed.example.com"
        assert args.count == 10
        assert args.region == "us-west"
        assert args.feature == ["fast", "reliable"]
        assert args.json is True

    def test_discover_command_short_flags(self):
        """Discover command with short flags."""
        parser = create_parser()
        args = parser.parse_args(
            [
                "discover",
                "-n",
                "20",
                "-r",
                "eu-central",
                "-f",
                "encrypted",
            ]
        )

        assert args.count == 20
        assert args.region == "eu-central"
        assert args.feature == ["encrypted"]

    def test_global_verbose_flag(self):
        """Global verbose flag."""
        parser = create_parser()
        args = parser.parse_args(["-v", "status"])
        assert args.verbose is True


# ============================================================================
# get_config_from_env Tests
# ============================================================================


class TestGetConfigFromEnv:
    """Test environment config loading."""

    def test_get_config_empty(self, monkeypatch):
        """Get config when no env vars set."""
        # Clear env vars
        for var in [
            "VALENCE_SEED_HOST",
            "VALENCE_SEED_PORT",
            "VALENCE_SEED_ID",
            "VALENCE_SEED_PEERS",
        ]:
            monkeypatch.delenv(var, raising=False)

        # Mock get_config to return empty
        mock_core_config = MagicMock()
        mock_core_config.seed_host = None
        mock_core_config.seed_port = None
        mock_core_config.seed_id = None
        mock_core_config.seed_peers = None

        with patch("valence.core.config.get_config", return_value=mock_core_config):
            config = get_config_from_env()

        assert config == {}

    def test_get_config_with_values(self):
        """Get config with env vars set."""
        mock_core_config = MagicMock()
        mock_core_config.seed_host = "0.0.0.0"
        mock_core_config.seed_port = 8470
        mock_core_config.seed_id = "test-seed"
        mock_core_config.seed_peers = "https://peer1.com, https://peer2.com"

        with patch("valence.core.config.get_config", return_value=mock_core_config):
            config = get_config_from_env()

        assert config["host"] == "0.0.0.0"
        assert config["port"] == 8470
        assert config["seed_id"] == "test-seed"
        assert config["known_seeds"] == ["https://peer1.com", "https://peer2.com"]

    def test_get_config_empty_peers(self):
        """Get config with empty peers string."""
        mock_core_config = MagicMock()
        mock_core_config.seed_host = None
        mock_core_config.seed_port = None
        mock_core_config.seed_id = None
        mock_core_config.seed_peers = "   ,  "  # Empty after stripping

        with patch("valence.core.config.get_config", return_value=mock_core_config):
            config = get_config_from_env()

        assert "known_seeds" not in config or config.get("known_seeds") == []


# ============================================================================
# cmd_status Tests
# ============================================================================


class TestCmdStatus:
    """Test cmd_status function."""

    @pytest.mark.asyncio
    async def test_status_success_json(self):
        """Status command with JSON output."""
        args = argparse.Namespace(
            url="http://localhost:8470",
            port=None,
            json=True,
        )

        mock_response_data = {
            "seed_id": "test-seed-001",
            "status": "running",
            "routers": {"total": 10, "healthy": 8},
            "known_seeds": 2,
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
    async def test_status_success_human_readable(self, capsys):
        """Status command with human-readable output."""
        args = argparse.Namespace(
            url=None,  # Use local
            port=8470,
            json=False,
        )

        mock_response_data = {
            "seed_id": "test-seed-001",
            "status": "running",
            "routers": {"total": 10, "healthy": 8},
            "known_seeds": 2,
        }

        mock_config = MagicMock()
        mock_config.seed_port = 8470

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
            with patch("valence.core.config.get_config", return_value=mock_config):
                result = await cmd_status(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "✅" in captured.out
        assert "test-seed-001" in captured.out

    @pytest.mark.asyncio
    async def test_status_http_error(self, capsys):
        """Status command with HTTP error."""
        args = argparse.Namespace(
            url="http://localhost:8470",
            port=None,
            json=False,
        )

        mock_response = AsyncMock()
        mock_response.status = 500

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

    @pytest.mark.asyncio
    async def test_status_connection_error(self, capsys):
        """Status command when seed is unreachable."""
        import aiohttp

        args = argparse.Namespace(
            url="http://localhost:8470",
            port=None,
            json=False,
        )

        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=aiohttp.ClientError("Connection refused"))

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_ctx):
            result = await cmd_status(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "❌" in captured.err

    @pytest.mark.asyncio
    async def test_status_url_normalization(self):
        """Status normalizes URL correctly."""
        args = argparse.Namespace(
            url="seed.example.com",  # No http://
            port=None,
            json=True,
        )

        mock_response_data = {"seed_id": "test"}

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

        # Should have added http://
        call_args = mock_session.get.call_args[0][0]
        assert call_args.startswith("http://")
        assert result == 0


# ============================================================================
# cmd_discover Tests
# ============================================================================


class TestCmdDiscover:
    """Test cmd_discover function."""

    @pytest.mark.asyncio
    async def test_discover_success_json(self):
        """Discover command with JSON output."""
        args = argparse.Namespace(
            url="http://localhost:8470",
            port=None,
            count=5,
            region=None,
            feature=[],
            json=True,
        )

        mock_response_data = {
            "seed_id": "test-seed",
            "routers": [
                {
                    "router_id": "router-001",
                    "endpoints": ["ws://router1.example.com"],
                    "regions": ["us-west"],
                    "capacity": {"current_load_pct": 45},
                    "health": {"uptime_pct": 99.5},
                },
            ],
            "other_seeds": [],
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_response_data)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_ctx)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_ctx):
            result = await cmd_discover(args)

        assert result == 0

    @pytest.mark.asyncio
    async def test_discover_success_human_readable(self, capsys):
        """Discover command with human-readable output."""
        args = argparse.Namespace(
            url="http://localhost:8470",
            port=None,
            count=5,
            region="us-west",
            feature=["fast"],
            json=False,
        )

        mock_response_data = {
            "seed_id": "test-seed",
            "routers": [
                {
                    "router_id": "router-001",
                    "endpoints": ["ws://router1.example.com"],
                    "regions": ["us-west"],
                    "capacity": {"current_load_pct": 45},
                    "health": {"uptime_pct": 99.5},
                },
                {
                    "router_id": "router-002-very-long-id-that-should-be-truncated",
                    "endpoints": [
                        "ws://router2.example.com",
                        "wss://router2.secure.com",
                    ],
                    "regions": [],
                    "capacity": {"current_load_pct": 20},
                    "health": {"uptime_pct": 98.0},
                },
            ],
            "other_seeds": ["https://seed2.example.com"],
        }

        mock_config = MagicMock()
        mock_config.seed_port = 8470

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_response_data)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_ctx)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_ctx):
            with patch("valence.core.config.get_config", return_value=mock_config):
                result = await cmd_discover(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "📡" in captured.out
        assert "router-001" in captured.out
        assert "us-west" in captured.out
        assert "seed2.example.com" in captured.out

    @pytest.mark.asyncio
    async def test_discover_no_routers(self, capsys):
        """Discover command with no routers found."""
        args = argparse.Namespace(
            url="http://localhost:8470",
            port=None,
            count=5,
            region=None,
            feature=[],
            json=False,
        )

        mock_response_data = {
            "seed_id": "test-seed",
            "routers": [],
        }

        mock_config = MagicMock()
        mock_config.seed_port = 8470

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_response_data)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_ctx)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_ctx):
            with patch("valence.core.config.get_config", return_value=mock_config):
                result = await cmd_discover(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "No routers available" in captured.out

    @pytest.mark.asyncio
    async def test_discover_sends_preferences(self):
        """Discover sends region and feature preferences."""
        args = argparse.Namespace(
            url="http://localhost:8470",
            port=None,
            count=10,
            region="eu-west",
            feature=["encrypted", "low-latency"],
            json=True,
        )

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"routers": []})

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_ctx)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_ctx):
            await cmd_discover(args)

        # Check the JSON payload sent
        call_kwargs = mock_session.post.call_args[1]
        assert call_kwargs["json"]["requested_count"] == 10
        assert call_kwargs["json"]["preferences"]["region"] == "eu-west"
        assert call_kwargs["json"]["preferences"]["features"] == [
            "encrypted",
            "low-latency",
        ]


# ============================================================================
# async_main Tests
# ============================================================================


class TestAsyncMain:
    """Test async_main dispatcher."""

    @pytest.mark.asyncio
    async def test_dispatch_to_start(self):
        """Dispatch to start command."""
        args = argparse.Namespace(
            command="start",
            host=None,
            port=None,
            seed_id=None,
            peer=[],
            verbose=False,
        )

        with patch("valence.cli.seed.cmd_start", new_callable=AsyncMock) as mock_start:
            mock_start.return_value = 0
            result = await async_main(args)

        assert result == 0
        mock_start.assert_called_once_with(args)

    @pytest.mark.asyncio
    async def test_dispatch_to_status(self):
        """Dispatch to status command."""
        args = argparse.Namespace(
            command="status",
            url=None,
            port=None,
            json=False,
            verbose=False,
        )

        with patch("valence.cli.seed.cmd_status", new_callable=AsyncMock) as mock_status:
            mock_status.return_value = 0
            result = await async_main(args)

        assert result == 0
        mock_status.assert_called_once_with(args)

    @pytest.mark.asyncio
    async def test_dispatch_to_discover(self):
        """Dispatch to discover command."""
        args = argparse.Namespace(
            command="discover",
            url=None,
            port=None,
            count=5,
            region=None,
            feature=[],
            json=False,
            verbose=False,
        )

        with patch("valence.cli.seed.cmd_discover", new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = 0
            result = await async_main(args)

        assert result == 0
        mock_discover.assert_called_once_with(args)

    @pytest.mark.asyncio
    async def test_dispatch_no_command(self):
        """No command shows help."""
        args = argparse.Namespace(
            command=None,
            verbose=False,
        )

        result = await async_main(args)

        assert result == 0


# ============================================================================
# main() Entry Point Tests
# ============================================================================


class TestMain:
    """Test main entry point."""

    def test_main_no_command_returns_0(self):
        """Main with no command returns 0."""
        with patch("sys.argv", ["valence-seed"]):
            result = main()
        assert result == 0

    def test_main_help_exits_0(self):
        """Main with --help exits with 0."""
        with patch("sys.argv", ["valence-seed", "--help"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 0
