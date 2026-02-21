"""Substrate tool dispatch and handler mapping.

Provides:
    SUBSTRATE_HANDLERS -- tool name to handler function mapping
    handle_substrate_tool -- dispatch function
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .beliefs import (
    belief_create,
    belief_get,
    belief_query,
    belief_search,
    belief_supersede,
)
from .entities import entity_get, entity_search
from .tensions import tension_list, tension_resolve

# Tool name to handler mapping
SUBSTRATE_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "belief_query": belief_query,
    "belief_create": belief_create,
    "belief_supersede": belief_supersede,
    "belief_get": belief_get,
    "entity_get": entity_get,
    "entity_search": entity_search,
    "tension_list": tension_list,
    "tension_resolve": tension_resolve,
    "belief_search": belief_search,
}


def handle_substrate_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Handle a substrate tool call.

    Args:
        name: Tool name
        arguments: Tool arguments

    Returns:
        Tool result dictionary
    """
    handler = SUBSTRATE_HANDLERS.get(name)
    if handler is None:
        return {"success": False, "error": f"Unknown substrate tool: {name}"}

    return handler(**arguments)
