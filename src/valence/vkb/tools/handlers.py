"""VKB tool dispatch and handler registry.

Provides handle_vkb_tool() and VKB_HANDLERS mapping.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .exchanges import exchange_add, exchange_list
from .insights import insight_extract, insight_list
from .patterns import pattern_list, pattern_record, pattern_reinforce, pattern_search
from .sessions import session_end, session_find_by_room, session_get, session_list, session_start

logger = logging.getLogger(__name__)

# Tool name to handler mapping
VKB_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "session_start": session_start,
    "session_end": session_end,
    "session_get": session_get,
    "session_list": session_list,
    "session_find_by_room": session_find_by_room,
    "exchange_add": exchange_add,
    "exchange_list": exchange_list,
    "pattern_record": pattern_record,
    "pattern_reinforce": pattern_reinforce,
    "pattern_list": pattern_list,
    "pattern_search": pattern_search,
    "insight_extract": insight_extract,
    "insight_list": insight_list,
}


def handle_vkb_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Handle a VKB tool call.

    Args:
        name: Tool name
        arguments: Tool arguments

    Returns:
        Tool result dictionary
    """
    handler = VKB_HANDLERS.get(name)
    if handler is None:
        return {"success": False, "error": f"Unknown VKB tool: {name}"}

    return handler(**arguments)
