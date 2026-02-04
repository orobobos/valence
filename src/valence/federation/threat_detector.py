"""Threat Detection - Signal analysis and threat assessment.

Part of the TrustManager refactor (Issue #31). This module handles:
- Analyzing behavioral signals from nodes
- Assessing threat levels
- Applying graduated responses
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from ..core.db import get_cursor
from .models import NodeTrust, ThreatLevel

logger = logging.getLogger(__name__)


# Threat level thresholds
THREAT_THRESHOLDS = {
    ThreatLevel.NONE: 0.0,
    ThreatLevel.LOW: 0.2,
    ThreatLevel.MEDIUM: 0.4,
    ThreatLevel.HIGH: 0.6,
    ThreatLevel.CRITICAL: 0.8,
}


class ThreatDetector:
    """Analyzes node behavior and assesses threat levels.
    
    Responsible for:
    - Processing behavioral signals
    - Computing threat scores
    - Determining threat levels
    - Applying graduated responses
    """

    def __init__(self, registry: Any) -> None:
        """Initialize ThreatDetector.
        
        Args:
            registry: TrustRegistry instance for data access
        """
        self.registry = registry

    def assess_threat_level(
        self,
        node_id: UUID,
    ) -> tuple[ThreatLevel, dict[str, Any]]:
        """Assess the threat level of a node based on behavior signals.

        Args:
            node_id: The node's UUID

        Returns:
            Tuple of (threat level, assessment details)
        """
        node_trust = self.registry.get_node_trust(node_id)
        if not node_trust:
            return ThreatLevel.NONE, {"reason": "No trust record"}

        assessment: dict[str, Any] = {
            "signals": [],
            "threat_score": 0.0,
        }

        # Signal 1: High dispute ratio
        if node_trust.beliefs_received > 10:
            dispute_ratio = node_trust.beliefs_disputed / node_trust.beliefs_received
            if dispute_ratio > 0.3:
                assessment["signals"].append({
                    "type": "high_dispute_ratio",
                    "value": dispute_ratio,
                    "contribution": min(0.3, dispute_ratio),
                })
                assessment["threat_score"] += min(0.3, dispute_ratio)

        # Signal 2: Very low trust after significant interaction
        total_interactions = (
            node_trust.beliefs_received +
            node_trust.sync_requests_served +
            node_trust.aggregation_participations
        )
        if total_interactions > 20 and node_trust.overall < 0.2:
            assessment["signals"].append({
                "type": "persistently_low_trust",
                "value": node_trust.overall,
                "contribution": 0.2,
            })
            assessment["threat_score"] += 0.2

        # Signal 3: Trust declined rapidly (low corroboration)
        if node_trust.beliefs_corroborated > 0:
            corroboration_ratio = node_trust.beliefs_corroborated / max(1, node_trust.beliefs_received)
            if corroboration_ratio < 0.1:
                assessment["signals"].append({
                    "type": "low_corroboration",
                    "value": corroboration_ratio,
                    "contribution": 0.15,
                })
                assessment["threat_score"] += 0.15

        # Signal 4: Rapid volume (potential spam/Sybil)
        if node_trust.beliefs_received > 100:
            days_active = max(1, (datetime.now() - node_trust.relationship_started_at).days)
            daily_rate = node_trust.beliefs_received / days_active
            if daily_rate > 50:  # More than 50 beliefs per day
                assessment["signals"].append({
                    "type": "high_volume",
                    "value": daily_rate,
                    "contribution": min(0.2, (daily_rate - 50) / 200),
                })
                assessment["threat_score"] += min(0.2, (daily_rate - 50) / 200)

        # Determine threat level from score
        threat_level = ThreatLevel.NONE
        for level, threshold in sorted(THREAT_THRESHOLDS.items(), key=lambda x: x[1], reverse=True):
            if assessment["threat_score"] >= threshold:
                threat_level = level
                break

        assessment["level"] = threat_level.value
        return threat_level, assessment

    def apply_threat_response(
        self,
        node_id: UUID,
        threat_level: ThreatLevel,
        assessment: dict[str, Any],
    ) -> bool:
        """Apply graduated response based on threat level.

        Per PRINCIPLES: "reduced access rather than exile"

        Args:
            node_id: The node's UUID
            threat_level: Assessed threat level
            assessment: Assessment details

        Returns:
            True if response was applied
        """
        node_trust = self.registry.get_node_trust(node_id)
        if not node_trust:
            return False

        if threat_level == ThreatLevel.NONE:
            return True  # No action needed

        # Level 1: Low - Increased scrutiny (log, no penalty)
        if threat_level == ThreatLevel.LOW:
            logger.warning(
                f"Node {node_id} at LOW threat level: {assessment['signals']}"
            )
            return True

        # Level 2: Medium - Reduce trust
        if threat_level == ThreatLevel.MEDIUM:
            penalty = -0.1
            node_trust.manual_trust_adjustment += penalty
            node_trust.adjustment_reason = f"Automated penalty: {threat_level.value}"
            node_trust.recalculate_overall()
            self.registry.save_node_trust(node_trust)
            logger.warning(
                f"Node {node_id} at MEDIUM threat level, applied trust penalty: {penalty}"
            )
            return True

        # Level 3: High - Quarantine from sensitive operations
        if threat_level == ThreatLevel.HIGH:
            penalty = -0.3
            node_trust.manual_trust_adjustment += penalty
            node_trust.adjustment_reason = f"Quarantine: {threat_level.value}"
            node_trust.recalculate_overall()
            self.registry.save_node_trust(node_trust)

            # Mark in metadata for exclusion from consensus
            try:
                with get_cursor() as cur:
                    cur.execute("""
                        UPDATE federation_nodes
                        SET metadata = jsonb_set(
                            COALESCE(metadata, '{}'),
                            '{quarantine_until}',
                            to_jsonb((NOW() + INTERVAL '7 days')::TEXT)
                        )
                        WHERE id = %s
                    """, (node_id,))
            except Exception as e:
                logger.exception(f"Error setting quarantine: {e}")

            logger.warning(
                f"Node {node_id} at HIGH threat level, quarantined for 7 days"
            )
            return True

        # Level 4: Critical - Functional isolation (read-only)
        if threat_level == ThreatLevel.CRITICAL:
            penalty = -0.5
            node_trust.manual_trust_adjustment = max(-0.9, node_trust.manual_trust_adjustment + penalty)
            node_trust.adjustment_reason = f"Isolation: {threat_level.value}"
            node_trust.recalculate_overall()
            self.registry.save_node_trust(node_trust)

            # Mark as read-only (can still receive, not contribute)
            try:
                with get_cursor() as cur:
                    cur.execute("""
                        UPDATE federation_nodes
                        SET metadata = jsonb_set(
                            jsonb_set(
                                COALESCE(metadata, '{}'),
                                '{read_only}',
                                'true'
                            ),
                            '{isolation_reason}',
                            %s::jsonb
                        ),
                        status = 'suspended'
                        WHERE id = %s
                    """, (f'"{assessment}"', node_id))
            except Exception as e:
                logger.exception(f"Error setting isolation: {e}")

            logger.error(
                f"Node {node_id} at CRITICAL threat level, isolated"
            )
            return True

        return False
