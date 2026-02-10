"""Valence - Personal knowledge substrate.

Valence provides:
- Knowledge substrate (beliefs, entities, tensions)
- Conversation tracking (sessions, exchanges, patterns)
- Claude Code integration (plugin, hooks, skills)
- HTTP MCP server with OAuth 2.1

Brick packages (our-*) provide: consensus, federation, privacy,
network, embeddings, crypto, identity, storage, compliance.
"""

__version__ = "1.0.0"

from . import (
    core as core,
)
from . import (
    substrate as substrate,
)
from . import (
    vkb as vkb,
)
