"""VKB tool definitions and implementations.

Tool implementations extracted from mcp_server.py for use in the unified HTTP server.
Descriptions include behavioral conditioning for proactive Claude usage.

This package re-exports everything for backward compatibility so that existing
imports like ``from valence.vkb.tools import session_start`` continue to work.
"""

from .definitions import VKB_TOOLS
from .exchanges import exchange_add, exchange_list
from .handlers import VKB_HANDLERS, handle_vkb_tool
from .insights import insight_extract, insight_list
from .patterns import pattern_list, pattern_record, pattern_reinforce, pattern_search
from .sessions import session_end, session_find_by_room, session_get, session_list, session_start

__all__ = [
    # Definitions
    "VKB_TOOLS",
    # Handlers
    "VKB_HANDLERS",
    "handle_vkb_tool",
    # Sessions
    "session_start",
    "session_end",
    "session_get",
    "session_list",
    "session_find_by_room",
    # Exchanges
    "exchange_add",
    "exchange_list",
    # Patterns
    "pattern_record",
    "pattern_reinforce",
    "pattern_list",
    "pattern_search",
    # Insights
    "insight_extract",
    "insight_list",
]
