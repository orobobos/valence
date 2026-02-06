"""
Router connection data model.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import aiohttp

from ..discovery import RouterInfo


@dataclass
class RouterConnection:
    """Represents an active connection to a router."""

    router: RouterInfo
    websocket: aiohttp.ClientWebSocketResponse
    session: aiohttp.ClientSession
    connected_at: float
    last_seen: float
    messages_sent: int = 0
    messages_received: int = 0
    ack_pending: int = 0
    ack_success: int = 0
    ack_failure: int = 0
    ping_latency_ms: float = 0.0
    back_pressure_active: bool = False
    back_pressure_until: float = 0.0
    back_pressure_retry_ms: int = 1000

    @property
    def is_under_back_pressure(self) -> bool:
        if not self.back_pressure_active:
            return False
        return time.time() < self.back_pressure_until

    @property
    def ack_success_rate(self) -> float:
        total = self.ack_success + self.ack_failure
        if total == 0:
            return 1.0
        return self.ack_success / total

    @property
    def health_score(self) -> float:
        ack_score = self.ack_success_rate
        latency_score = max(0, 1.0 - (self.ping_latency_ms / 500))
        load_pct = self.router.capacity.get("current_load_pct", 0)
        load_score = 1.0 - (load_pct / 100)
        return (ack_score * 0.5) + (latency_score * 0.3) + (load_score * 0.2)
