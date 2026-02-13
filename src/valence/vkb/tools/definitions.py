"""VKB tool definitions with behavioral conditioning.

Tool() objects that describe each VKB tool's schema and descriptions.
These are served by MCP servers so Claude knows what tools are available.
"""

from __future__ import annotations

from mcp.types import Tool

VKB_TOOLS = [
    Tool(
        name="session_start",
        description=(
            "Begin a new conversation session.\n\n"
            "Call this at the START of a conversation to enable session tracking. "
            "Sessions provide context for future conversations and enable insight extraction."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": [
                        "claude-code",
                        "api",
                        "slack",
                        "claude-web",
                        "claude-desktop",
                        "claude-mobile",
                    ],
                    "description": "Platform this session is on",
                },
                "project_context": {
                    "type": "string",
                    "description": "Project or topic context",
                },
                "external_room_id": {
                    "type": "string",
                    "description": "Room/channel ID for chat platforms",
                },
                "claude_session_id": {
                    "type": "string",
                    "description": "Claude Code session ID for resume",
                },
                "metadata": {
                    "type": "object",
                    "description": "Additional session metadata",
                },
            },
            "required": ["platform"],
        },
    ),
    Tool(
        name="session_end",
        description=(
            "Close a session with summary and themes.\n\n"
            "Call this when a conversation is concluding to:\n"
            "- Capture a summary of what was discussed\n"
            "- Record key themes for future reference\n"
            "- Enable session-based insight extraction"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "UUID of the session",
                },
                "summary": {
                    "type": "string",
                    "description": "Session summary - key accomplishments and outcomes",
                },
                "themes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key themes from session",
                },
                "status": {
                    "type": "string",
                    "enum": ["completed", "abandoned"],
                    "default": "completed",
                },
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="session_get",
        description="Get session details including optional recent exchanges.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "UUID of the session",
                },
                "include_exchanges": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include recent exchanges",
                },
                "exchange_limit": {
                    "type": "integer",
                    "default": 10,
                },
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="session_list",
        description="List sessions with filters. Useful for reviewing past conversations.",
        inputSchema={
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "description": "Filter by platform",
                },
                "project_context": {
                    "type": "string",
                    "description": "Filter by project",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "completed", "abandoned"],
                    "description": "Filter by status",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                },
            },
        },
    ),
    Tool(
        name="session_find_by_room",
        description="Find active session by external room ID. Use to resume existing sessions.",
        inputSchema={
            "type": "object",
            "properties": {
                "external_room_id": {
                    "type": "string",
                    "description": "Room/channel ID",
                },
            },
            "required": ["external_room_id"],
        },
    ),
    Tool(
        name="exchange_add",
        description="Record a conversation turn. Used for detailed conversation tracking.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "UUID of the session",
                },
                "role": {
                    "type": "string",
                    "enum": ["user", "assistant", "system"],
                },
                "content": {
                    "type": "string",
                    "description": "Message content",
                },
                "tokens_approx": {
                    "type": "integer",
                    "description": "Approximate token count",
                },
                "tool_uses": {
                    "type": "array",
                    "description": "Tools used in this turn",
                },
            },
            "required": ["session_id", "role", "content"],
        },
    ),
    Tool(
        name="exchange_list",
        description="Get exchanges from a session. Useful for reviewing conversation history.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "UUID of the session",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max exchanges to return",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                },
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="pattern_record",
        description=(
            "Record a new behavioral pattern.\n\n"
            "Use when you notice:\n"
            "- Recurring topics or themes across sessions\n"
            "- Consistent user preferences\n"
            "- Working style patterns\n"
            "- Common problem-solving approaches"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": "Pattern type (topic_recurrence, preference, working_style, etc.)",
                },
                "description": {
                    "type": "string",
                    "description": "What the pattern is",
                },
                "evidence": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Session IDs as evidence",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "default": 0.5,
                },
            },
            "required": ["type", "description"],
        },
    ),
    Tool(
        name="pattern_reinforce",
        description=("Strengthen an existing pattern with new evidence.\n\nCall when you observe a pattern that matches one already recorded."),
        inputSchema={
            "type": "object",
            "properties": {
                "pattern_id": {
                    "type": "string",
                    "description": "UUID of the pattern",
                },
                "session_id": {
                    "type": "string",
                    "description": "Session that supports this pattern",
                },
            },
            "required": ["pattern_id"],
        },
    ),
    Tool(
        name="pattern_list",
        description="List patterns with filters. Review to understand user preferences and behaviors.",
        inputSchema={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": "Filter by pattern type",
                },
                "status": {
                    "type": "string",
                    "enum": ["emerging", "established", "fading", "archived"],
                    "description": "Filter by status",
                },
                "min_confidence": {
                    "type": "number",
                    "default": 0,
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                },
            },
        },
    ),
    Tool(
        name="pattern_search",
        description="Search patterns by description.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="insight_extract",
        description=(
            "Extract an insight from a session and create a belief in the knowledge base.\n\n"
            "Use PROACTIVELY when:\n"
            "- A decision is made with clear rationale\n"
            "- User expresses a preference or value\n"
            "- A problem is solved with a novel approach\n"
            "- Important factual information is shared\n\n"
            "This bridges conversation tracking to the knowledge substrate."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Source session",
                },
                "content": {
                    "type": "string",
                    "description": "The insight/belief content",
                },
                "domain_path": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Domain classification",
                },
                "confidence": {
                    "type": "object",
                    "description": "Confidence dimensions",
                    "default": {"overall": 0.8},
                },
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {"type": "string"},
                            "role": {"type": "string"},
                        },
                    },
                    "description": "Entities to link",
                },
            },
            "required": ["session_id", "content"],
        },
    ),
    Tool(
        name="insight_list",
        description="List insights extracted from a session.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session to get insights from",
                },
            },
            "required": ["session_id"],
        },
    ),
]
