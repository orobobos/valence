"""
Node-related exceptions.
"""


class StateConflictError(Exception):
    """Raised when there's a conflict between saved and current state."""

    pass


class StaleStateError(Exception):
    """Raised when saved state is too old to be useful."""

    pass


class NodeError(Exception):
    """Base exception for node errors."""

    pass


class ConnectionError(NodeError):
    """Raised when connection to router fails."""

    pass


class NoRoutersAvailableError(NodeError):
    """Raised when no routers are available."""

    pass
