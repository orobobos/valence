"""Tests for unified MCP server.

Tests cover:
- create_server() - server creation
- Tool definitions and descriptions
- Resource content
- Prompt content
- Helper functions
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from valence.server.unified_server import (
    SERVER_NAME,
    SERVER_VERSION,
    _get_context_prompt,
    _get_tool_reference,
    _get_usage_instructions,
    create_server,
)
from valence.substrate.tools import SUBSTRATE_TOOLS, handle_substrate_tool
from valence.vkb.tools import VKB_TOOLS, handle_vkb_tool

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_cursor():
    """Mock database cursor."""
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    return cursor


@pytest.fixture
def mock_get_cursor(mock_cursor):
    """Mock the get_cursor context manager."""

    @contextmanager
    def _mock_get_cursor(dict_cursor: bool = True) -> Generator:
        yield mock_cursor

    with patch("valence.substrate.tools.get_cursor", _mock_get_cursor):
        with patch("valence.vkb.tools.get_cursor", _mock_get_cursor):
            yield mock_cursor


# =============================================================================
# SERVER CREATION TESTS
# =============================================================================


class TestCreateServer:
    """Tests for create_server function."""

    def test_create_server_returns_server(self):
        """Test that create_server returns a Server instance."""
        from mcp.server import Server

        server = create_server()

        assert server is not None
        assert isinstance(server, Server)
        assert server.name == SERVER_NAME

    def test_create_server_idempotent(self):
        """Test that create_server can be called multiple times."""
        server1 = create_server()
        server2 = create_server()

        # Should both work (independent instances)
        assert server1 is not server2
        assert server1.name == server2.name

    def test_server_has_request_handlers(self):
        """Test that server has handlers registered."""
        server = create_server()

        # The server should have request handlers registered
        assert hasattr(server, "request_handlers")
        assert len(server.request_handlers) > 0


# =============================================================================
# TOOL DEFINITIONS TESTS
# =============================================================================


class TestToolDefinitions:
    """Tests for tool definitions in unified server."""

    def test_all_substrate_tools_defined(self):
        """Test that all substrate tools are defined."""
        expected_tools = [
            "belief_query",
            "belief_create",
            "belief_supersede",
            "belief_get",
            "entity_get",
            "entity_search",
            "tension_list",
            "tension_resolve",
            "belief_corroboration",
        ]

        tool_names = [t.name for t in SUBSTRATE_TOOLS]
        for expected in expected_tools:
            assert expected in tool_names

    def test_all_vkb_tools_defined(self):
        """Test that all VKB tools are defined."""
        expected_tools = [
            "session_start",
            "session_end",
            "session_get",
            "session_list",
            "session_find_by_room",
            "exchange_add",
            "exchange_list",
            "pattern_record",
            "pattern_reinforce",
            "pattern_list",
            "pattern_search",
            "insight_extract",
            "insight_list",
        ]

        tool_names = [t.name for t in VKB_TOOLS]
        for expected in expected_tools:
            assert expected in tool_names

    def test_tool_descriptions_have_behavioral_conditioning(self):
        """Test that key tools have behavioral hints."""
        belief_query = next(t for t in SUBSTRATE_TOOLS if t.name == "belief_query")
        assert "MUST" in belief_query.description or "CRITICAL" in belief_query.description

        belief_create = next(t for t in SUBSTRATE_TOOLS if t.name == "belief_create")
        assert "PROACTIVELY" in belief_create.description

        insight_extract = next(t for t in VKB_TOOLS if t.name == "insight_extract")
        assert "PROACTIVELY" in insight_extract.description


# =============================================================================
# TOOL ROUTING TESTS
# =============================================================================


class TestToolRouting:
    """Tests for tool call routing."""

    def test_substrate_tool_routing(self, mock_get_cursor):
        """Test that substrate tools are routed correctly."""
        mock_get_cursor.fetchall.return_value = []

        result = handle_substrate_tool("belief_query", {"query": "test"})

        assert result["success"] is True

    def test_vkb_tool_routing(self, mock_get_cursor):
        """Test that VKB tools are routed correctly."""
        from datetime import datetime

        mock_get_cursor.fetchone.return_value = {
            "id": uuid4(),
            "platform": "claude-code",
            "status": "active",
            "project_context": None,
            "summary": None,
            "themes": [],
            "started_at": datetime.now(),
            "ended_at": None,
            "claude_session_id": None,
            "external_room_id": None,
            "metadata": {},
            "exchange_count": None,
            "insight_count": None,
        }

        result = handle_vkb_tool("session_start", {"platform": "claude-code"})

        assert result["success"] is True

    def test_unknown_substrate_tool_error(self):
        """Test that unknown substrate tool returns error."""
        result = handle_substrate_tool("nonexistent_tool", {})

        assert result["success"] is False
        assert "Unknown" in result["error"]

    def test_unknown_vkb_tool_error(self):
        """Test that unknown VKB tool returns error."""
        result = handle_vkb_tool("nonexistent_tool", {})

        assert result["success"] is False
        assert "Unknown" in result["error"]


# =============================================================================
# RESOURCE CONTENT TESTS
# =============================================================================


class TestResourceContent:
    """Tests for resource content."""

    def test_get_usage_instructions_content(self):
        """Test usage instructions has required content."""
        instructions = _get_usage_instructions()

        # Should have title
        assert "Valence Knowledge Substrate" in instructions

        # Should have behavioral guidelines (case-insensitive check)
        assert "query first" in instructions.lower()
        assert "PROACTIVELY" in instructions

        # Should list tool categories
        assert "Knowledge Substrate" in instructions
        assert "Conversation Tracking" in instructions

        # Should mention key tools
        assert "belief_query" in instructions
        assert "belief_create" in instructions
        assert "session_start" in instructions
        assert "session_end" in instructions

    def test_get_tool_reference_content(self):
        """Test tool reference has all tools listed."""
        reference = _get_tool_reference()

        # Should have headers
        assert "Tool Reference" in reference
        assert "Knowledge Substrate Tools" in reference
        assert "Conversation Tracking Tools" in reference

        # Should list all substrate tools
        for tool in SUBSTRATE_TOOLS:
            assert tool.name in reference

        # Should list all VKB tools
        for tool in VKB_TOOLS:
            assert tool.name in reference


# =============================================================================
# PROMPT CONTENT TESTS
# =============================================================================


class TestPromptContent:
    """Tests for prompt content."""

    def test_get_context_prompt_content(self):
        """Test context prompt has required content."""
        prompt = _get_context_prompt()

        # Should mention Valence
        assert "Valence" in prompt

        # Should have core behaviors
        assert "Query First" in prompt
        assert "Capture Proactively" in prompt
        assert "Track Sessions" in prompt

        # Should mention key tools
        assert "belief_query" in prompt
        assert "belief_create" in prompt or "insight_extract" in prompt
        assert "session_start" in prompt
        assert "session_end" in prompt


# =============================================================================
# CONSTANTS TESTS
# =============================================================================


class TestConstants:
    """Tests for module constants."""

    def test_server_name(self):
        """Test server name is correct."""
        assert SERVER_NAME == "valence"

    def test_server_version(self):
        """Test server version is set."""
        assert SERVER_VERSION is not None
        assert len(SERVER_VERSION) > 0
        # Should be a version string like "1.0.0"
        assert "." in SERVER_VERSION or SERVER_VERSION.isdigit()


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestIntegration:
    """Integration-style tests for unified server."""

    def test_server_can_be_created_and_configured(self):
        """Test that server can be created and is properly configured."""
        server = create_server()

        # Server should have name
        assert server.name == SERVER_NAME

        # Server should be ready for use
        assert server is not None

    def test_all_tool_names_are_unique(self):
        """Test that there are no duplicate tool names."""
        all_tools = SUBSTRATE_TOOLS + VKB_TOOLS
        tool_names = [t.name for t in all_tools]

        # Should have no duplicates
        assert len(tool_names) == len(set(tool_names))

    def test_all_tools_have_input_schema(self):
        """Test that all tools have input schemas defined."""
        all_tools = SUBSTRATE_TOOLS + VKB_TOOLS

        for tool in all_tools:
            assert tool.inputSchema is not None, f"Tool {tool.name} missing inputSchema"
            assert "type" in tool.inputSchema, f"Tool {tool.name} inputSchema missing type"
            assert tool.inputSchema["type"] == "object", f"Tool {tool.name} inputSchema type should be object"

    def test_all_tools_have_descriptions(self):
        """Test that all tools have descriptions."""
        all_tools = SUBSTRATE_TOOLS + VKB_TOOLS

        for tool in all_tools:
            assert tool.description is not None, f"Tool {tool.name} missing description"
            assert len(tool.description) > 10, f"Tool {tool.name} description too short"
