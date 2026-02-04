"""Trust Policy - Phase transitions and trust decay.

Part of the TrustManager refactor (Issue #31). This module handles:
- Trust phase transitions (observer → contributor → participant → anchor)
- Trust decay over time
- Effective trust calculation with user overrides
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from ..core.db import get_cursor
from .models import (
    NodeTrust,
    TrustPhase,
    TrustPreference,
)

logger = logging.getLogger(__name__)


# Trust decay parameters
DECAY_HALF_LIFE_DAYS = 30  # Trust decays by half over this period without interaction
DECAY_MIN_THRESHOLD = 0.1  # Minimum trust after decay

# Phase transition thresholds
PHASE_TRANSITION = {
    TrustPhase.OBSERVER: {
        "min_days": 7,
        "min_trust": 0.0,  # Observer is the starting phase
        "min_interactions": 0,
    },
    TrustPhase.CONTRIBUTOR: {
        "min_days": 7,
        "min_trust": 0.15,
        "min_interactions": 5,
    },
    TrustPhase.PARTICIPANT: {
        "min_days": 30,
        "min_trust": 0.4,
        "min_interactions": 20,
    },
    TrustPhase.ANCHOR: {
        "min_days": 90,
        "min_trust": 0.8,
        "min_interactions": 100,
        "min_endorsements": 3,
    },
}

# User preference multipliers
PREFERENCE_MULTIPLIERS = {
    TrustPreference.BLOCKED: 0.0,
    TrustPreference.REDUCED: 0.5,
    TrustPreference.AUTOMATIC: 1.0,
    TrustPreference.ELEVATED: 1.2,
    TrustPreference.ANCHOR: 1.5,
}


class TrustPolicy:
    """Manages trust phase transitions and decay.
    
    Responsible for:
    - Computing effective trust with user overrides
    - Applying time-based trust decay
    - Evaluating phase transition eligibility
    - Executing phase transitions
    """

    def __init__(
        self,
        registry: Any,
        decay_half_life_days: int = DECAY_HALF_LIFE_DAYS,
        decay_min_threshold: float = DECAY_MIN_THRESHOLD,
    ) -> None:
        """Initialize TrustPolicy.
        
        Args:
            registry: TrustRegistry instance for data access
            decay_half_life_days: Days for trust to decay by half
            decay_min_threshold: Minimum trust after decay
        """
        self.registry = registry
        self.decay_half_life_days = decay_half_life_days
        self.decay_min_threshold = decay_min_threshold

    # -------------------------------------------------------------------------
    # EFFECTIVE TRUST
    # -------------------------------------------------------------------------

    def get_effective_trust(
        self,
        node_id: UUID,
        domain: str | None = None,
        apply_decay: bool = True,
    ) -> float:
        """Get effective trust score for a node.

        Combines computed trust with user overrides and decay.

        Args:
            node_id: The node's UUID
            domain: Optional domain for domain-specific trust
            apply_decay: Whether to apply time-based decay

        Returns:
            Effective trust score (0.0 to 1.0)
        """
        node_trust = self.registry.get_node_trust(node_id)
        if not node_trust:
            return 0.1  # Default for unknown nodes

        # Get base trust (domain-specific if applicable)
        base_trust = node_trust.get_domain_trust(domain) if domain else node_trust.overall

        # Apply decay based on last interaction
        if apply_decay and node_trust.last_interaction_at:
            base_trust = self._apply_decay(base_trust, node_trust.last_interaction_at)

        # Get user preference
        user_pref = self.registry.get_user_trust_preference(node_id)
        if user_pref:
            # Get preference (possibly domain-specific)
            pref = user_pref.get_effective_preference(domain)

            # Check for manual trust score override
            if user_pref.manual_trust_score is not None:
                return user_pref.manual_trust_score

            # Apply preference multiplier
            multiplier = PREFERENCE_MULTIPLIERS.get(pref, 1.0)
            base_trust *= multiplier

        return max(0.0, min(1.0, base_trust))

    # -------------------------------------------------------------------------
    # TRUST DECAY
    # -------------------------------------------------------------------------

    def _apply_decay(
        self,
        trust: float,
        last_interaction: datetime,
    ) -> float:
        """Apply time-based decay to trust.

        Uses exponential decay with configurable half-life.

        Args:
            trust: Current trust value
            last_interaction: Timestamp of last interaction

        Returns:
            Decayed trust value
        """
        days_since_interaction = (datetime.now() - last_interaction).days
        if days_since_interaction <= 0:
            return trust

        # Exponential decay: trust * 0.5^(days / half_life)
        decay_factor = 0.5 ** (days_since_interaction / self.decay_half_life_days)
        decayed = trust * decay_factor

        # Don't decay below minimum threshold
        return max(self.decay_min_threshold, decayed)

    def apply_decay_to_all_nodes(self) -> int:
        """Apply trust decay to all nodes that haven't interacted recently.

        Returns:
            Number of nodes updated
        """
        count = 0
        try:
            with get_cursor() as cur:
                # Find nodes that haven't interacted recently
                threshold = datetime.now() - timedelta(days=7)
                cur.execute("""
                    SELECT nt.* FROM node_trust nt
                    WHERE nt.last_interaction_at < %s
                    OR nt.last_interaction_at IS NULL
                """, (threshold,))
                rows = cur.fetchall()

                for row in rows:
                    node_trust = NodeTrust.from_row(row)
                    if node_trust.last_interaction_at:
                        old_trust = node_trust.overall
                        decayed = self._apply_decay(old_trust, node_trust.last_interaction_at)
                        if decayed != old_trust:
                            node_trust.overall = decayed
                            self.registry.save_node_trust(node_trust)
                            count += 1

        except Exception as e:
            logger.exception(f"Error applying trust decay: {e}")

        return count

    # -------------------------------------------------------------------------
    # PHASE TRANSITIONS
    # -------------------------------------------------------------------------

    def check_phase_transition(self, node_id: UUID) -> TrustPhase | None:
        """Check if a node qualifies for a phase transition.

        Args:
            node_id: The node's UUID

        Returns:
            New phase if transition is warranted, None otherwise
        """
        # Get node and trust
        node = self.registry.get_node(node_id)
        if not node:
            return None

        node_trust = self.registry.get_node_trust(node_id)
        if not node_trust:
            return None

        current_phase = node.trust_phase
        days_in_phase = (datetime.now() - node.phase_started_at).days

        # Determine total interactions
        total_interactions = (
            node_trust.beliefs_received +
            node_trust.sync_requests_served +
            node_trust.aggregation_participations
        )

        # Check for demotion first (trust fell too low)
        if current_phase != TrustPhase.OBSERVER:
            prev_phases = [TrustPhase.OBSERVER, TrustPhase.CONTRIBUTOR, TrustPhase.PARTICIPANT]
            current_idx = prev_phases.index(current_phase) if current_phase in prev_phases else len(prev_phases)

            for i in range(current_idx - 1, -1, -1):
                phase = prev_phases[i]
                req = PHASE_TRANSITION[prev_phases[i + 1] if i + 1 < len(prev_phases) else TrustPhase.ANCHOR]
                if node_trust.overall < req["min_trust"] * 0.8:  # 20% below threshold
                    return phase

        # Check for promotion
        next_phase_map = {
            TrustPhase.OBSERVER: TrustPhase.CONTRIBUTOR,
            TrustPhase.CONTRIBUTOR: TrustPhase.PARTICIPANT,
            TrustPhase.PARTICIPANT: TrustPhase.ANCHOR,
        }

        next_phase = next_phase_map.get(current_phase)
        if not next_phase:
            return None  # Already at ANCHOR

        req = PHASE_TRANSITION[next_phase]

        # Check requirements
        if days_in_phase < req["min_days"]:
            return None
        if node_trust.overall < req["min_trust"]:
            return None
        if total_interactions < req["min_interactions"]:
            return None
        if "min_endorsements" in req and node_trust.endorsements_received < req["min_endorsements"]:
            return None

        return next_phase

    def transition_phase(
        self,
        node_id: UUID,
        new_phase: TrustPhase,
        reason: str | None = None,
    ) -> bool:
        """Transition a node to a new trust phase.

        Args:
            node_id: The node's UUID
            new_phase: The new trust phase
            reason: Optional reason for transition

        Returns:
            True if successful
        """
        try:
            with get_cursor() as cur:
                cur.execute("""
                    UPDATE federation_nodes
                    SET trust_phase = %s,
                        phase_started_at = NOW(),
                        metadata = jsonb_set(
                            COALESCE(metadata, '{}'),
                            '{phase_transition_reason}',
                            %s::jsonb
                        )
                    WHERE id = %s
                """, (new_phase.value, f'"{reason}"' if reason else 'null', node_id))

                logger.info(f"Node {node_id} transitioned to phase {new_phase.value}: {reason}")
                return True

        except Exception as e:
            logger.exception(f"Error transitioning node {node_id} to phase {new_phase.value}")
            return False

    def check_and_apply_transitions(self) -> list[tuple[UUID, TrustPhase, TrustPhase]]:
        """Check all nodes for phase transitions and apply them.

        Returns:
            List of (node_id, old_phase, new_phase) for transitions that occurred
        """
        transitions: list[tuple[UUID, TrustPhase, TrustPhase]] = []

        try:
            with get_cursor() as cur:
                cur.execute("SELECT id, trust_phase FROM federation_nodes WHERE status != 'unreachable'")
                rows = cur.fetchall()

            for row in rows:
                node_id = row["id"]
                old_phase = TrustPhase(row["trust_phase"])

                new_phase = self.check_phase_transition(node_id)
                if new_phase and new_phase != old_phase:
                    direction = "promoted" if new_phase.value > old_phase.value else "demoted"
                    reason = f"Automatically {direction} based on trust metrics"

                    if self.transition_phase(node_id, new_phase, reason):
                        transitions.append((node_id, old_phase, new_phase))

        except Exception as e:
            logger.exception(f"Error checking phase transitions: {e}")

        return transitions
