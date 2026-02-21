"""Substrate tool definitions and implementations.

Tool implementations extracted from mcp_server.py for use in the unified HTTP server.
Descriptions include behavioral conditioning for proactive Claude usage.

This package re-exports all public names so that existing imports like
``from valence.substrate.tools import belief_query`` continue to work.
"""

from __future__ import annotations

# Re-export shared utilities (also ensures patch target backward compat)
from ._common import _validate_enum, get_cursor  # noqa: F401

# Re-export all tool implementations
from .beliefs import (  # noqa: F401
    _content_hash,
    _log_retrievals,
    _reinforce_belief,
    belief_create,
    belief_get,
    belief_query,
    belief_search,
    belief_supersede,
)

# Re-export tool definitions
from .definitions import SUBSTRATE_TOOLS  # noqa: F401
from .entities import entity_get, entity_search  # noqa: F401

# Re-export handler dispatch
from .handlers import SUBSTRATE_HANDLERS, handle_substrate_tool  # noqa: F401
from .tensions import tension_list, tension_resolve  # noqa: F401

__all__ = [
    # Definitions
    "SUBSTRATE_TOOLS",
    # Handlers
    "SUBSTRATE_HANDLERS",
    "handle_substrate_tool",
    # Beliefs
    "belief_query",
    "belief_create",
    "belief_supersede",
    "belief_get",
    "belief_search",
    "_content_hash",
    "_reinforce_belief",
    "_log_retrievals",
    # Entities
    "entity_get",
    "entity_search",
    # Tensions
    "tension_list",
    "tension_resolve",
    # Shared (for patching)
    "_validate_enum",
    "get_cursor",
]
