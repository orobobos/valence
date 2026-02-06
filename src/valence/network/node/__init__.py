"""
Valence Node Client - User nodes connect to routers for message relay.

This package provides the NodeClient and related classes for connecting
to the Valence relay network.

Refactored from a single large file into submodules for maintainability:
- state.py: ConnectionState for persistence
- errors.py: Exception classes
- pending.py: PendingAck, PendingMessage
- router_connection.py: RouterConnection
- failover.py: FailoverState
- cover_traffic.py: CoverTrafficConfig
- client.py: NodeClient, create_node_client
"""

from .client import NodeClient, create_node_client
from .cover_traffic import CoverTrafficConfig
from .errors import (
    ConnectionError,
    NodeError,
    NoRoutersAvailableError,
    StaleStateError,
    StateConflictError,
)
from .failover import FailoverState
from .pending import PendingAck, PendingMessage
from .router_connection import RouterConnection
from .state import STATE_VERSION, ConnectionState

__all__ = [
    # Main client
    "NodeClient",
    "create_node_client",
    # State persistence
    "ConnectionState",
    "STATE_VERSION",
    # Errors
    "StateConflictError",
    "StaleStateError",
    "NodeError",
    "ConnectionError",
    "NoRoutersAvailableError",
    # Data models
    "RouterConnection",
    "PendingAck",
    "PendingMessage",
    "FailoverState",
    "CoverTrafficConfig",
]
