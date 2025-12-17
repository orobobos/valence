"""MCP Server for Valence conversation tracking.

Provides tools for:
- Session management (start, end, list)
- Exchange capture (add, get)
- Insight extraction (extract, list)
- Pattern tracking (record, reinforce, list)
"""

import asyncio
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from . import conversations as conv
from . import kb

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the MCP server
server = Server("valence")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        # Session tools
        Tool(
            name="session_start",
            description="Start a new conversation session. Returns session ID for tracking.",
            inputSchema={
                "type": "object",
                "properties": {
                    "platform": {"type": "string", "description": "Platform (e.g., claude-code, api)"},
                    "project_context": {"type": "string", "description": "Which project this is about"},
                },
            },
        ),
        Tool(
            name="session_end",
            description="End a conversation session with summary and themes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID to end"},
                    "summary": {"type": "string", "description": "Summary of the session"},
                    "themes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Key themes from the session",
                    },
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="session_update",
            description="Update session summary/themes during the session.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID"},
                    "summary": {"type": "string", "description": "Updated summary"},
                    "themes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Updated themes",
                    },
                },
                "required": ["session_id", "summary"],
            },
        ),
        Tool(
            name="session_get",
            description="Get details of a specific session.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID"},
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="session_list",
            description="List recent sessions with optional filters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_context": {"type": "string", "description": "Filter by project"},
                    "status": {"type": "string", "description": "Filter by status (active, completed, abandoned)"},
                    "limit": {"type": "integer", "description": "Max results (default 20)"},
                },
            },
        ),
        # Exchange tools
        Tool(
            name="exchange_add",
            description="Add an exchange (message) to a session.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID"},
                    "role": {"type": "string", "enum": ["user", "assistant", "system"], "description": "Who sent this"},
                    "content": {"type": "string", "description": "Message content"},
                    "tokens_approx": {"type": "integer", "description": "Approximate token count"},
                },
                "required": ["session_id", "role", "content"],
            },
        ),
        Tool(
            name="exchange_list",
            description="Get exchanges from a session.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID"},
                    "limit": {"type": "integer", "description": "Max results"},
                    "offset": {"type": "integer", "description": "Skip first N results"},
                },
                "required": ["session_id"],
            },
        ),
        # Insight tools
        Tool(
            name="insight_extract",
            description="Extract an insight from a session and create a KB entry.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Source session ID"},
                    "entry_type": {"type": "string", "description": "Type (belief, decision, preference, etc.)"},
                    "content": {"type": "string", "description": "The insight content"},
                    "summary": {"type": "string", "description": "Short summary"},
                    "confidence": {"type": "number", "description": "Confidence 0-1 (default 0.8)"},
                },
                "required": ["session_id", "entry_type", "content"],
            },
        ),
        Tool(
            name="insight_list",
            description="List insights extracted from a session.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID"},
                },
                "required": ["session_id"],
            },
        ),
        # Pattern tools
        Tool(
            name="pattern_record",
            description="Record a new pattern observed across sessions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern_type": {
                        "type": "string",
                        "description": "Type (topic_recurrence, preference, working_style, etc.)",
                    },
                    "description": {"type": "string", "description": "What the pattern is"},
                    "evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Session IDs as evidence",
                    },
                    "confidence": {"type": "number", "description": "Initial confidence 0-1"},
                },
                "required": ["pattern_type", "description"],
            },
        ),
        Tool(
            name="pattern_reinforce",
            description="Reinforce an existing pattern (seen again).",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern_id": {"type": "string", "description": "Pattern ID"},
                    "session_id": {"type": "string", "description": "Session that supports this pattern"},
                },
                "required": ["pattern_id"],
            },
        ),
        Tool(
            name="pattern_list",
            description="List patterns with optional filters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern_type": {"type": "string", "description": "Filter by type"},
                    "status": {"type": "string", "description": "Filter by status (emerging, established, fading)"},
                    "min_confidence": {"type": "number", "description": "Minimum confidence"},
                    "limit": {"type": "integer", "description": "Max results"},
                },
            },
        ),
        Tool(
            name="pattern_search",
            description="Search patterns by description.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results"},
                },
                "required": ["query"],
            },
        ),
        # KB tools
        Tool(
            name="entry_search",
            description="Search KB entries by content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "entry_type": {"type": "string", "description": "Filter by type"},
                    "limit": {"type": "integer", "description": "Max results"},
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    import json

    try:
        result: Any = None

        # Session tools
        if name == "session_start":
            result = conv.start_session(
                platform=arguments.get("platform"),
                project_context=arguments.get("project_context"),
            )
        elif name == "session_end":
            result = conv.end_session(
                arguments["session_id"],
                summary=arguments.get("summary"),
                themes=arguments.get("themes"),
            )
        elif name == "session_update":
            result = conv.update_session_summary(
                arguments["session_id"],
                arguments["summary"],
                themes=arguments.get("themes"),
            )
        elif name == "session_get":
            result = conv.get_session(arguments["session_id"])
        elif name == "session_list":
            result = conv.list_sessions(
                project_context=arguments.get("project_context"),
                status=arguments.get("status"),
                limit=arguments.get("limit", 20),
            )

        # Exchange tools
        elif name == "exchange_add":
            result = conv.add_exchange(
                arguments["session_id"],
                arguments["role"],
                arguments["content"],
                tokens_approx=arguments.get("tokens_approx"),
            )
        elif name == "exchange_list":
            result = conv.get_exchanges(
                arguments["session_id"],
                limit=arguments.get("limit"),
                offset=arguments.get("offset", 0),
            )

        # Insight tools
        elif name == "insight_extract":
            result = conv.extract_insight(
                arguments["session_id"],
                arguments["entry_type"],
                arguments["content"],
                summary=arguments.get("summary"),
                confidence=arguments.get("confidence", 0.8),
            )
        elif name == "insight_list":
            result = conv.get_session_insights(arguments["session_id"])

        # Pattern tools
        elif name == "pattern_record":
            result = conv.record_pattern(
                arguments["pattern_type"],
                arguments["description"],
                evidence=arguments.get("evidence"),
                confidence=arguments.get("confidence", 0.5),
            )
        elif name == "pattern_reinforce":
            result = conv.reinforce_pattern(
                arguments["pattern_id"],
                session_id=arguments.get("session_id"),
            )
        elif name == "pattern_list":
            result = conv.list_patterns(
                pattern_type=arguments.get("pattern_type"),
                status=arguments.get("status"),
                min_confidence=arguments.get("min_confidence", 0.0),
                limit=arguments.get("limit", 20),
            )
        elif name == "pattern_search":
            result = conv.search_patterns(
                arguments["query"],
                limit=arguments.get("limit", 10),
            )

        # KB tools
        elif name == "entry_search":
            result = kb.search_entries(
                arguments["query"],
                entry_type=arguments.get("entry_type"),
                limit=arguments.get("limit", 20),
            )

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return [TextContent(type="text", text=f"Error: {e}")]


def run() -> None:
    """Run the MCP server."""
    # Initialize all schemas
    kb.init_schemas()
    logger.info("Valence MCP server starting...")

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(main())


if __name__ == "__main__":
    run()
