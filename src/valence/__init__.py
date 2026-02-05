"""Valence - Personal knowledge substrate for AI agents.

Valence provides:
- Knowledge substrate (beliefs, entities, tensions)
- Conversation tracking (sessions, exchanges, patterns)
- Claude Code integration (plugin, hooks, skills)
- Multi-platform agents (Matrix, API)
- Consensus mechanism (VRF-based validator selection)
"""

__version__ = "1.0.0"

# Core library
# Knowledge substrate (EKB)
# Conversation tracking (VKB)
# Embedding infrastructure
# Agent implementations
# Consensus mechanism
from . import (
    agents as agents,
)
from . import (
    consensus as consensus,
)
from . import (
    core as core,
)
from . import (
    embeddings as embeddings,
)
from . import (
    substrate as substrate,
)
from . import (
    vkb as vkb,
)
