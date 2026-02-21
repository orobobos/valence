"""CLI command modules for Valence.

Each module exposes a ``register(subparsers)`` function that wires up
its argparse sub-commands and sets ``parser.set_defaults(func=handler)``.
"""

from . import (
    beliefs,
    conflicts,
    embeddings,
    io,
    maintenance,
    migration,
    qos,
    stats,
)
from .beliefs import cmd_add, cmd_init, cmd_list, cmd_query
from .conflicts import cmd_conflicts
from .embeddings import cmd_embeddings
from .io import cmd_export, cmd_import
from .maintenance import cmd_maintenance
from .migration import cmd_migrate
from .qos import cmd_qos
from .stats import cmd_stats

# All command modules with register() functions, in registration order.
COMMAND_MODULES = [
    beliefs,
    conflicts,
    stats,
    io,
    embeddings,
    migration,
    qos,
    maintenance,
]

__all__ = [
    "COMMAND_MODULES",
    "cmd_add",
    "cmd_conflicts",
    "cmd_embeddings",
    "cmd_export",
    "cmd_import",
    "cmd_init",
    "cmd_list",
    "cmd_migrate",
    "cmd_qos",
    "cmd_query",
    "cmd_stats",
    "cmd_maintenance",
]
