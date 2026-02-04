# Valence Privacy Elevation
"""
Auto-elevation system for beliefs based on corroboration and other signals.

Elevation increases a belief's visibility/trust level when certain criteria are met.
This module handles:
- Corroboration-based auto-elevation (multiple independent sources)
- Elevation proposals and approval workflow
- Owner opt-out controls
- Audit trail for elevation decisions
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

from .corroboration import (
    CorroborationDetector,
    CorroborationEvidence,
    CorroborationStatus,
    get_detector,
)


class ElevationLevel(Enum):
    """Levels of belief visibility/trust."""
    
    PRIVATE = "private"  # Owner only
    TRUSTED = "trusted"  # Shared with trusted network
    COMMUNITY = "community"  # Shared with community
    PUBLIC = "public"  # Publicly visible


class ElevationTrigger(Enum):
    """What triggered an elevation."""
    
    MANUAL = "manual"  # Human decided to elevate
    CORROBORATION = "corroboration"  # Met corroboration threshold
    AGE = "age"  # Belief has aged without contradiction
    VERIFICATION = "verification"  # External verification passed
    COMMUNITY_VOTE = "community_vote"  # Community approval


class ProposalStatus(Enum):
    """Status of an elevation proposal."""
    
    PENDING = "pending"  # Awaiting decision
    APPROVED = "approved"  # Owner/system approved
    REJECTED = "rejected"  # Owner rejected
    EXPIRED = "expired"  # Proposal timed out
    AUTO_APPROVED = "auto_approved"  # Auto-approved (owner opted in)


@dataclass
class ElevationProposal:
    """A proposal to elevate a belief's visibility level."""
    
    proposal_id: str
    belief_id: str
    from_level: ElevationLevel
    to_level: ElevationLevel
    trigger: ElevationTrigger
    evidence: dict = field(default_factory=dict)  # Supporting evidence
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    decided_at: Optional[datetime] = None
    decision_reason: Optional[str] = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "proposal_id": self.proposal_id,
            "belief_id": self.belief_id,
            "from_level": self.from_level.value,
            "to_level": self.to_level.value,
            "trigger": self.trigger.value,
            "evidence": self.evidence,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "decision_reason": self.decision_reason,
        }


@dataclass
class BeliefElevationState:
    """Current elevation state for a belief."""
    
    belief_id: str
    current_level: ElevationLevel = ElevationLevel.PRIVATE
    auto_elevate_enabled: bool = True  # Owner can opt out
    elevation_history: list[dict] = field(default_factory=list)
    opt_out_reason: Optional[str] = None
    
    def record_elevation(
        self,
        from_level: ElevationLevel,
        to_level: ElevationLevel,
        trigger: ElevationTrigger,
        reason: Optional[str] = None,
    ) -> None:
        """Record an elevation in history."""
        self.elevation_history.append({
            "from_level": from_level.value,
            "to_level": to_level.value,
            "trigger": trigger.value,
            "reason": reason,
            "elevated_at": datetime.now(timezone.utc).isoformat(),
        })
        self.current_level = to_level
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "belief_id": self.belief_id,
            "current_level": self.current_level.value,
            "auto_elevate_enabled": self.auto_elevate_enabled,
            "elevation_history": self.elevation_history,
            "opt_out_reason": self.opt_out_reason,
        }


@dataclass
class AutoElevationConfig:
    """Configuration for automatic elevation."""
    
    # Enable/disable auto-elevation globally
    enabled: bool = True
    
    # Corroboration thresholds for each level
    # e.g., 3 sources -> TRUSTED, 5 sources -> COMMUNITY
    corroboration_levels: dict[int, ElevationLevel] = field(default_factory=lambda: {
        3: ElevationLevel.TRUSTED,
        5: ElevationLevel.COMMUNITY,
        10: ElevationLevel.PUBLIC,
    })
    
    # Minimum similarity for corroboration to count
    min_similarity: float = 0.85
    
    # Whether to auto-approve or create proposals
    auto_approve: bool = False
    
    # Proposal expiry in hours (0 = never expire)
    proposal_expiry_hours: int = 168  # 1 week
    
    # Require source diversity
    require_source_diversity: bool = True
    min_unique_source_types: int = 2


class ElevationManager:
    """
    Manages belief elevation based on corroboration and other signals.
    
    This service:
    1. Monitors corroboration levels
    2. Creates elevation proposals when thresholds are met
    3. Handles owner approval/rejection
    4. Supports owner opt-out of auto-elevation
    5. Maintains audit trail of all elevation decisions
    """
    
    def __init__(
        self,
        corroboration_detector: Optional[CorroborationDetector] = None,
        config: Optional[AutoElevationConfig] = None,
    ):
        """
        Initialize the elevation manager.
        
        Args:
            corroboration_detector: Detector for corroboration (defaults to global)
            config: Auto-elevation configuration
        """
        self._detector = corroboration_detector or get_detector()
        self.config = config or AutoElevationConfig()
        
        # Storage (in production, use database)
        self._proposals: dict[str, ElevationProposal] = {}
        self._states: dict[str, BeliefElevationState] = {}
        self._proposals_by_belief: dict[str, list[str]] = {}  # belief_id -> proposal_ids
        
        # Callbacks
        self._on_proposal: list[Callable[[ElevationProposal], None]] = []
        self._on_elevation: list[Callable[[str, ElevationLevel, ElevationLevel], None]] = []
    
    def get_or_create_state(self, belief_id: str) -> BeliefElevationState:
        """Get or create elevation state for a belief."""
        if belief_id not in self._states:
            self._states[belief_id] = BeliefElevationState(belief_id=belief_id)
        return self._states[belief_id]
    
    def opt_out(self, belief_id: str, reason: Optional[str] = None) -> bool:
        """
        Opt out of auto-elevation for a belief.
        
        Args:
            belief_id: The belief to opt out
            reason: Optional reason for opting out
        
        Returns:
            True if opt-out was recorded
        """
        state = self.get_or_create_state(belief_id)
        state.auto_elevate_enabled = False
        state.opt_out_reason = reason
        return True
    
    def opt_in(self, belief_id: str) -> bool:
        """
        Opt back into auto-elevation for a belief.
        
        Args:
            belief_id: The belief to opt in
        
        Returns:
            True if opt-in was recorded
        """
        state = self.get_or_create_state(belief_id)
        state.auto_elevate_enabled = True
        state.opt_out_reason = None
        return True
    
    def is_opted_out(self, belief_id: str) -> bool:
        """Check if a belief has opted out of auto-elevation."""
        state = self._states.get(belief_id)
        if state is None:
            return False
        return not state.auto_elevate_enabled
    
    def _determine_target_level(
        self,
        evidence: CorroborationEvidence,
        current_level: ElevationLevel,
    ) -> Optional[ElevationLevel]:
        """
        Determine target elevation level based on corroboration.
        
        Returns None if no elevation is warranted.
        """
        source_count = evidence.source_count
        
        # Check source diversity if required
        if self.config.require_source_diversity:
            unique_types = len(evidence.unique_source_types)
            if unique_types < self.config.min_unique_source_types:
                # Not diverse enough - cap effective count
                source_count = min(source_count, unique_types)
        
        # Find highest applicable level
        target_level = None
        for threshold, level in sorted(self.config.corroboration_levels.items()):
            if source_count >= threshold:
                # Only elevate up, never down
                if self._level_value(level) > self._level_value(current_level):
                    target_level = level
        
        return target_level
    
    def _level_value(self, level: ElevationLevel) -> int:
        """Get numeric value for level comparison."""
        return {
            ElevationLevel.PRIVATE: 0,
            ElevationLevel.TRUSTED: 1,
            ElevationLevel.COMMUNITY: 2,
            ElevationLevel.PUBLIC: 3,
        }.get(level, 0)
    
    def check_and_propose_elevation(
        self,
        belief_id: str,
        evidence: Optional[CorroborationEvidence] = None,
    ) -> Optional[ElevationProposal]:
        """
        Check if a belief should be elevated and create a proposal if so.
        
        Args:
            belief_id: The belief to check
            evidence: Corroboration evidence (fetched if not provided)
        
        Returns:
            ElevationProposal if elevation is warranted, None otherwise
        """
        if not self.config.enabled:
            return None
        
        # Check opt-out
        if self.is_opted_out(belief_id):
            return None
        
        # Get evidence
        if evidence is None:
            evidence = self._detector.get_evidence(belief_id)
        
        if evidence is None:
            return None
        
        # Get current state
        state = self.get_or_create_state(belief_id)
        current_level = state.current_level
        
        # Determine target level
        target_level = self._determine_target_level(evidence, current_level)
        
        if target_level is None:
            return None
        
        # Check for existing pending proposal
        existing = self.get_pending_proposals(belief_id)
        for prop in existing:
            if prop.to_level == target_level:
                return prop  # Already proposed
        
        # Create proposal
        proposal = ElevationProposal(
            proposal_id=str(uuid.uuid4()),
            belief_id=belief_id,
            from_level=current_level,
            to_level=target_level,
            trigger=ElevationTrigger.CORROBORATION,
            evidence=evidence.to_dict(),
        )
        
        # Store proposal
        self._proposals[proposal.proposal_id] = proposal
        if belief_id not in self._proposals_by_belief:
            self._proposals_by_belief[belief_id] = []
        self._proposals_by_belief[belief_id].append(proposal.proposal_id)
        
        # Auto-approve if configured
        if self.config.auto_approve:
            self._approve_proposal(proposal, auto=True)
        
        # Fire callbacks
        for callback in self._on_proposal:
            try:
                callback(proposal)
            except Exception:
                pass
        
        return proposal
    
    def _approve_proposal(
        self,
        proposal: ElevationProposal,
        reason: Optional[str] = None,
        auto: bool = False,
    ) -> None:
        """Internal method to approve a proposal."""
        proposal.status = ProposalStatus.AUTO_APPROVED if auto else ProposalStatus.APPROVED
        proposal.decided_at = datetime.now(timezone.utc)
        proposal.decision_reason = reason or ("Auto-approved" if auto else "Approved by owner")
        
        # Update state
        state = self.get_or_create_state(proposal.belief_id)
        state.record_elevation(
            from_level=proposal.from_level,
            to_level=proposal.to_level,
            trigger=proposal.trigger,
            reason=proposal.decision_reason,
        )
        
        # Fire callbacks
        for callback in self._on_elevation:
            try:
                callback(proposal.belief_id, proposal.from_level, proposal.to_level)
            except Exception:
                pass
    
    def approve_proposal(
        self,
        proposal_id: str,
        reason: Optional[str] = None,
    ) -> Optional[ElevationProposal]:
        """
        Approve an elevation proposal.
        
        Args:
            proposal_id: ID of the proposal
            reason: Optional reason for approval
        
        Returns:
            Updated proposal, or None if not found
        """
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return None
        
        if proposal.status != ProposalStatus.PENDING:
            return proposal  # Already decided
        
        self._approve_proposal(proposal, reason)
        return proposal
    
    def reject_proposal(
        self,
        proposal_id: str,
        reason: Optional[str] = None,
    ) -> Optional[ElevationProposal]:
        """
        Reject an elevation proposal.
        
        Args:
            proposal_id: ID of the proposal
            reason: Optional reason for rejection
        
        Returns:
            Updated proposal, or None if not found
        """
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return None
        
        if proposal.status != ProposalStatus.PENDING:
            return proposal  # Already decided
        
        proposal.status = ProposalStatus.REJECTED
        proposal.decided_at = datetime.now(timezone.utc)
        proposal.decision_reason = reason or "Rejected by owner"
        
        return proposal
    
    def get_proposal(self, proposal_id: str) -> Optional[ElevationProposal]:
        """Get a proposal by ID."""
        return self._proposals.get(proposal_id)
    
    def get_pending_proposals(
        self,
        belief_id: Optional[str] = None,
    ) -> list[ElevationProposal]:
        """
        Get all pending proposals.
        
        Args:
            belief_id: Optional filter by belief
        
        Returns:
            List of pending proposals
        """
        proposals = list(self._proposals.values())
        proposals = [p for p in proposals if p.status == ProposalStatus.PENDING]
        
        if belief_id is not None:
            proposals = [p for p in proposals if p.belief_id == belief_id]
        
        return proposals
    
    def get_elevation_state(self, belief_id: str) -> Optional[BeliefElevationState]:
        """Get the elevation state for a belief."""
        return self._states.get(belief_id)
    
    def elevate_manually(
        self,
        belief_id: str,
        to_level: ElevationLevel,
        reason: Optional[str] = None,
    ) -> BeliefElevationState:
        """
        Manually elevate a belief (bypasses corroboration check).
        
        Args:
            belief_id: The belief to elevate
            to_level: Target level
            reason: Optional reason
        
        Returns:
            Updated elevation state
        """
        state = self.get_or_create_state(belief_id)
        from_level = state.current_level
        
        state.record_elevation(
            from_level=from_level,
            to_level=to_level,
            trigger=ElevationTrigger.MANUAL,
            reason=reason,
        )
        
        # Fire callbacks
        for callback in self._on_elevation:
            try:
                callback(belief_id, from_level, to_level)
            except Exception:
                pass
        
        return state
    
    def on_proposal_created(
        self,
        callback: Callable[[ElevationProposal], None],
    ) -> None:
        """Register callback for when proposals are created."""
        self._on_proposal.append(callback)
    
    def on_elevation(
        self,
        callback: Callable[[str, ElevationLevel, ElevationLevel], None],
    ) -> None:
        """Register callback for when beliefs are elevated."""
        self._on_elevation.append(callback)
    
    def process_corroboration_update(
        self,
        belief_id: str,
        evidence: CorroborationEvidence,
    ) -> Optional[ElevationProposal]:
        """
        Process a corroboration update and check for elevation.
        
        This is the main entry point for the corroboration detector
        to notify the elevation manager of changes.
        
        Args:
            belief_id: The belief that was corroborated
            evidence: Updated corroboration evidence
        
        Returns:
            ElevationProposal if one was created
        """
        return self.check_and_propose_elevation(belief_id, evidence)
    
    def clear(self) -> None:
        """Clear all state (for testing)."""
        self._proposals.clear()
        self._states.clear()
        self._proposals_by_belief.clear()


# Module-level default manager
_default_manager: Optional[ElevationManager] = None


def get_elevation_manager() -> ElevationManager:
    """Get the default elevation manager."""
    global _default_manager
    if _default_manager is None:
        _default_manager = ElevationManager()
    return _default_manager


def check_and_propose_elevation(
    belief_id: str,
    evidence: Optional[CorroborationEvidence] = None,
) -> Optional[ElevationProposal]:
    """
    High-level function to check and propose elevation for a belief.
    
    Args:
        belief_id: The belief to check
        evidence: Corroboration evidence (fetched if not provided)
    
    Returns:
        ElevationProposal if elevation is warranted
    
    Example:
        >>> from valence.privacy.corroboration import get_detector
        >>> evidence = get_detector().get_evidence("belief-123")
        >>> proposal = check_and_propose_elevation("belief-123", evidence)
        >>> if proposal:
        ...     print(f"Proposed elevation to {proposal.to_level.value}")
    """
    return get_elevation_manager().check_and_propose_elevation(belief_id, evidence)


def approve_elevation(
    proposal_id: str,
    reason: Optional[str] = None,
) -> Optional[ElevationProposal]:
    """Approve an elevation proposal."""
    return get_elevation_manager().approve_proposal(proposal_id, reason)


def reject_elevation(
    proposal_id: str,
    reason: Optional[str] = None,
) -> Optional[ElevationProposal]:
    """Reject an elevation proposal."""
    return get_elevation_manager().reject_proposal(proposal_id, reason)


def opt_out_auto_elevation(
    belief_id: str,
    reason: Optional[str] = None,
) -> bool:
    """Opt out of auto-elevation for a belief."""
    return get_elevation_manager().opt_out(belief_id, reason)


def opt_in_auto_elevation(belief_id: str) -> bool:
    """Opt back into auto-elevation for a belief."""
    return get_elevation_manager().opt_in(belief_id)
