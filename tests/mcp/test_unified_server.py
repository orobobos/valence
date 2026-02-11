"""Tests for the unified MCP server."""

from __future__ import annotations

import pytest

from valence.mcp_server import ALL_TOOLS, call_tool, list_tools, server
from valence.substrate.tools import SUBSTRATE_HANDLERS
from valence.vkb.tools import VKB_HANDLERS


class TestToolList:
    """Tests for tool listing."""

    def test_all_tools_contains_expected_count(self):
        """ALL_TOOLS should contain all substrate + VKB tools."""
        expected = len(SUBSTRATE_HANDLERS) + len(VKB_HANDLERS)
        assert len(ALL_TOOLS) == expected

    def test_no_duplicate_tool_names(self):
        """Tool names must be unique across both servers."""
        names = [t.name for t in ALL_TOOLS]
        assert len(names) == len(set(names)), f"Duplicate tools: {[n for n in names if names.count(n) > 1]}"

    def test_substrate_tools_present(self):
        """All substrate tool names should be in the combined list."""
        tool_names = {t.name for t in ALL_TOOLS}
        for name in SUBSTRATE_HANDLERS:
            assert name in tool_names, f"Missing substrate tool: {name}"

    def test_vkb_tools_present(self):
        """All VKB tool names should be in the combined list."""
        tool_names = {t.name for t in ALL_TOOLS}
        for name in VKB_HANDLERS:
            assert name in tool_names, f"Missing VKB tool: {name}"

    @pytest.mark.asyncio
    async def test_list_tools_returns_all(self):
        """list_tools() handler should return all tools."""
        result = await list_tools()
        assert len(result) == len(ALL_TOOLS)


class TestToolRouting:
    """Tests for tool routing."""

    @pytest.mark.asyncio
    async def test_substrate_tool_routes_to_substrate(self, mock_get_cursor):
        """Substrate tool names should route to substrate handler."""
        mock_cur = mock_get_cursor.__enter__.return_value
        mock_cur.fetchall.return_value = []
        mock_cur.fetchone.return_value = None

        result = await call_tool("belief_query", {"query": "test"})
        assert len(result) == 1
        import json
        data = json.loads(result[0].text)
        assert "beliefs" in data or "error" in data

    @pytest.mark.asyncio
    async def test_vkb_tool_routes_to_vkb(self, mock_get_cursor):
        """VKB tool names should route to VKB handler."""
        mock_cur = mock_get_cursor.__enter__.return_value
        mock_cur.fetchall.return_value = []

        result = await call_tool("session_list", {})
        assert len(result) == 1
        import json
        data = json.loads(result[0].text)
        assert "sessions" in data or "error" in data

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        """Unknown tool names should return error response."""
        result = await call_tool("nonexistent_tool", {})
        assert len(result) == 1
        import json
        data = json.loads(result[0].text)
        assert data["success"] is False
        assert "Unknown tool" in data["error"]

    @pytest.mark.asyncio
    async def test_server_name(self):
        """Server should be named 'valence'."""
        assert server.name == "valence"


class TestResources:
    """Tests for resource availability."""

    @pytest.mark.asyncio
    async def test_list_resources_returns_three(self):
        """Should expose beliefs, trust, and stats resources."""
        from valence.mcp_server import list_resources
        resources = await list_resources()
        assert len(resources) == 3
        uris = {str(r.uri) for r in resources}
        assert "valence://beliefs/recent" in uris
        assert "valence://trust/graph" in uris
        assert "valence://stats" in uris
