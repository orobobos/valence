"""Valence Transport — pluggable P2P networking layer.

This package defines the abstract :class:`TransportAdapter` protocol and
ships the ``"legacy"`` backend that wraps the existing federation stack.

Quick start::

    from valence.transport import get_transport, TransportConfig

    config = TransportConfig(backend="legacy")
    transport = get_transport(config)
    await transport.start()

    peers = await transport.discover_peers()
    resp  = await transport.send(peer_id, "sync_request", payload)

    await transport.stop()

Adding a new backend
--------------------
1. Create ``valence/transport/<name>.py`` that contains a class satisfying
   :class:`TransportAdapter`.
2. Register it in :data:`BACKEND_REGISTRY` below.
3. Users select it via ``TransportConfig(backend="<name>")``.
"""

from __future__ import annotations

from typing import Any

from .adapter import (
    Connection,
    PeerInfo,
    TransportAdapter,
    TransportConfig,
    TransportState,
)

# ---------------------------------------------------------------------------
# Backend registry
# ---------------------------------------------------------------------------

# Mapping from backend name → factory callable.
# Each factory takes a TransportConfig and returns a TransportAdapter instance.
# We use strings for lazy imports so that heavy deps aren't pulled in at
# import time.
BACKEND_REGISTRY: dict[str, str] = {
    "legacy": "valence.transport.legacy:LegacyTransportAdapter",
}


def register_backend(name: str, factory_path: str) -> None:
    """Register an additional transport backend.

    Parameters
    ----------
    name:
        Short name used in ``TransportConfig.backend``.
    factory_path:
        Dotted import path in ``"module.path:ClassName"`` form.
        The class must accept a single ``TransportConfig`` argument.
    """
    BACKEND_REGISTRY[name] = factory_path


def _import_factory(path: str) -> Any:
    """Dynamically import ``'some.module:ClassName'``."""
    module_path, _, attr = path.rpartition(":")
    if not module_path:
        raise ValueError(f"Invalid factory path: {path!r} (expected 'module:Class')")
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, attr)


def get_transport(config: TransportConfig | None = None) -> TransportAdapter:
    """Create a transport adapter from *config*.

    If *config* is ``None`` the ``"legacy"`` backend is used with default
    settings.

    Raises
    ------
    ValueError
        If the requested backend is not in :data:`BACKEND_REGISTRY`.
    """
    if config is None:
        config = TransportConfig()

    factory_path = BACKEND_REGISTRY.get(config.backend)
    if factory_path is None:
        available = ", ".join(sorted(BACKEND_REGISTRY))
        raise ValueError(f"Unknown transport backend {config.backend!r}. Available: {available}")

    factory = _import_factory(factory_path)
    return factory(config)


__all__ = [
    # Core types
    "Connection",
    "PeerInfo",
    "TransportAdapter",
    "TransportConfig",
    "TransportState",
    # Factory
    "get_transport",
    "register_backend",
    "BACKEND_REGISTRY",
]
