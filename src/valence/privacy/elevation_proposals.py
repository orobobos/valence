# Valence Elevation Proposal Workflow
"""
Elevation proposal workflow for promoting content from more private to more public levels.

This module extends the core elevation system with explicit proposal-approval workflows.
Content owners must approve proposals before elevation occurs.

Key features:
- Explicit proposal workflow requiring owner approval
- Full history tracking (who proposed, when approved)
- Support for transformed/redacted versions on elevation
- Original content preserved at original level
"""

from __future__ import annotations

import uuid
import time
import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Protocol, Any, List, Callable

from .types import ShareLevel


class ProposalStatus(Enum):
    """Status of an elevation proposal."""
    
    PENDING = "pending"      # Awaiting owner approval
    APPROVED = "approved"    # Owner approved
    REJECTED = "rejected"    # Owner rejected
    WITHDRAWN = "withdrawn"  # Proposer withdrew
    EXPIRED = "expired"      # Proposal expired without decision


class TransformType(Enum):
    """Types of transformations that can be applied during elevation."""
    
    NONE = "none"            # Elevate content as-is
    REDACTED = "redacted"    # Content with redactions applied
    SUMMARIZED = "summarized"  # Summarized/abstracted version
    ANONYMIZED = "anonymized"  # Identifying info removed
    CUSTOM = "custom"        # Custom transformation


@dataclass
class ContentTransform:
    """A transformation applied to content during elevation."""
    
    transform_type: TransformType = TransformType.NONE
    transformed_content: Optional[str] = None  # If None, use original
    redactions: Optional[List[dict]] = None    # List of {start, end, replacement}
    transform_metadata: Optional[dict] = None  # Additional transform info
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "transform_type": self.transform_type.value,
            "transformed_content": self.transformed_content,
            "redactions": self.redactions,
            "transform_metadata": self.transform_metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ContentTransform":
        """Deserialize from dictionary."""
        return cls(
            transform_type=TransformType(data.get("transform_type", "none")),
            transformed_content=data.get("transformed_content"),
            redactions=data.get("redactions"),
            transform_metadata=data.get("transform_metadata"),
        )
    
    @classmethod
    def identity(cls) -> "ContentTransform":
        """Create an identity transform (no changes)."""
        return cls(transform_type=TransformType.NONE)
    
    @classmethod
    def redact(cls, content: str, redactions: List[dict]) -> "ContentTransform":
        """Create a redaction transform.
        
        Args:
            content: Original content
            redactions: List of {start, end, replacement} dicts
        
        Returns:
            ContentTransform with redacted content
        """
        # Apply redactions in reverse order to preserve positions
        transformed = content
        sorted_redactions = sorted(redactions, key=lambda r: r["start"], reverse=True)
        for r in sorted_redactions:
            replacement = r.get("replacement", "[REDACTED]")
            transformed = transformed[:r["start"]] + replacement + transformed[r["end"]:]
        
        return cls(
            transform_type=TransformType.REDACTED,
            transformed_content=transformed,
            redactions=redactions,
        )


@dataclass
class ElevationProposal:
    """A proposal to elevate content to a higher visibility level."""
    
    id: str
    belief_id: str
    owner_did: str           # Who owns the content
    proposer_did: str        # Who proposed the elevation
    
    # Levels (using ShareLevel values as strings)
    from_level: str          # Current ShareLevel value
    to_level: str            # Proposed ShareLevel value
    
    # Status tracking
    status: ProposalStatus = ProposalStatus.PENDING
    
    # Timestamps
    proposed_at: float = field(default_factory=time.time)
    decided_at: Optional[float] = None
    expires_at: Optional[float] = None
    
    # Decision metadata
    decision_reason: Optional[str] = None
    decided_by: Optional[str] = None
    
    # Transformation for elevation
    transform: ContentTransform = field(default_factory=ContentTransform.identity)
    
    # The elevated content ID (created on approval)
    elevated_belief_id: Optional[str] = None
    
    # Proposal metadata
    justification: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "belief_id": self.belief_id,
            "owner_did": self.owner_did,
            "proposer_did": self.proposer_did,
            "from_level": self.from_level,
            "to_level": self.to_level,
            "status": self.status.value,
            "proposed_at": self.proposed_at,
            "decided_at": self.decided_at,
            "expires_at": self.expires_at,
            "decision_reason": self.decision_reason,
            "decided_by": self.decided_by,
            "transform": self.transform.to_dict(),
            "elevated_belief_id": self.elevated_belief_id,
            "justification": self.justification,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ElevationProposal":
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            belief_id=data["belief_id"],
            owner_did=data["owner_did"],
            proposer_did=data["proposer_did"],
            from_level=data["from_level"],
            to_level=data["to_level"],
            status=ProposalStatus(data.get("status", "pending")),
            proposed_at=data.get("proposed_at", time.time()),
            decided_at=data.get("decided_at"),
            expires_at=data.get("expires_at"),
            decision_reason=data.get("decision_reason"),
            decided_by=data.get("decided_by"),
            transform=ContentTransform.from_dict(data["transform"]) if data.get("transform") else ContentTransform.identity(),
            elevated_belief_id=data.get("elevated_belief_id"),
            justification=data.get("justification"),
            metadata=data.get("metadata", {}),
        )
    
    @property
    def is_pending(self) -> bool:
        """Check if proposal is still pending."""
        return self.status == ProposalStatus.PENDING
    
    @property
    def is_expired(self) -> bool:
        """Check if proposal has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


@dataclass
class ElevationHistoryEntry:
    """An entry in the elevation history for a piece of content."""
    
    id: str
    belief_id: str
    proposal_id: str
    
    # The elevation that occurred
    from_level: str
    to_level: str
    
    # Who was involved
    proposer_did: str
    approver_did: str
    
    # When it happened
    proposed_at: float
    approved_at: float
    
    # Transform applied
    transform: ContentTransform
    
    # Links
    original_belief_id: str
    elevated_belief_id: str
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "belief_id": self.belief_id,
            "proposal_id": self.proposal_id,
            "from_level": self.from_level,
            "to_level": self.to_level,
            "proposer_did": self.proposer_did,
            "approver_did": self.approver_did,
            "proposed_at": self.proposed_at,
            "approved_at": self.approved_at,
            "transform": self.transform.to_dict(),
            "original_belief_id": self.original_belief_id,
            "elevated_belief_id": self.elevated_belief_id,
        }


# Valid elevation paths - must go from more private to more public
SHARE_LEVEL_ORDER = ["private", "direct", "bounded", "cascading", "public"]


def is_valid_elevation(from_level: str, to_level: str) -> bool:
    """Check if elevation from one level to another is valid.
    
    Elevation must go from more private to more public.
    """
    try:
        from_idx = SHARE_LEVEL_ORDER.index(from_level)
        to_idx = SHARE_LEVEL_ORDER.index(to_level)
        return to_idx > from_idx
    except ValueError:
        return False


class ProposalDatabaseProtocol(Protocol):
    """Protocol for database operations required by ElevationProposalService."""
    
    async def get_belief(self, belief_id: str) -> Optional[Any]:
        """Get a belief by ID."""
        ...
    
    async def get_belief_owner(self, belief_id: str) -> Optional[str]:
        """Get the owner DID of a belief."""
        ...
    
    async def get_belief_share_level(self, belief_id: str) -> Optional[str]:
        """Get the current share level of a belief."""
        ...
    
    async def create_elevation_proposal(self, proposal: ElevationProposal) -> None:
        """Create an elevation proposal."""
        ...
    
    async def get_elevation_proposal(self, proposal_id: str) -> Optional[ElevationProposal]:
        """Get an elevation proposal by ID."""
        ...
    
    async def update_elevation_proposal(self, proposal: ElevationProposal) -> None:
        """Update an elevation proposal."""
        ...
    
    async def list_proposals_for_owner(
        self, owner_did: str, status: Optional[ProposalStatus] = None
    ) -> List[ElevationProposal]:
        """List proposals for content owned by a DID."""
        ...
    
    async def list_proposals_by_proposer(
        self, proposer_did: str, status: Optional[ProposalStatus] = None
    ) -> List[ElevationProposal]:
        """List proposals made by a DID."""
        ...
    
    async def list_proposals_for_belief(
        self, belief_id: str, status: Optional[ProposalStatus] = None
    ) -> List[ElevationProposal]:
        """List proposals for a specific belief."""
        ...
    
    async def create_elevated_belief(
        self,
        original_belief_id: str,
        new_level: str,
        content: str,
        owner_did: str,
    ) -> str:
        """Create a new belief at the elevated level.
        
        Returns the new belief ID.
        """
        ...
    
    async def create_elevation_history(self, entry: ElevationHistoryEntry) -> None:
        """Record an elevation in history."""
        ...
    
    async def get_elevation_history(self, belief_id: str) -> List[ElevationHistoryEntry]:
        """Get elevation history for a belief."""
        ...


@dataclass
class ProposeRequest:
    """Request to propose elevating content."""
    
    belief_id: str
    to_level: str
    justification: Optional[str] = None
    transform: Optional[ContentTransform] = None
    expires_in_seconds: Optional[float] = None  # Default: 7 days


@dataclass
class ProposeResult:
    """Result of proposing an elevation."""
    
    proposal_id: str
    belief_id: str
    from_level: str
    to_level: str
    status: ProposalStatus
    expires_at: Optional[float] = None


@dataclass
class ApproveRequest:
    """Request to approve an elevation proposal."""
    
    proposal_id: str
    modified_transform: Optional[ContentTransform] = None  # Owner can modify transform
    reason: Optional[str] = None


@dataclass
class ApproveResult:
    """Result of approving an elevation."""
    
    proposal_id: str
    original_belief_id: str
    elevated_belief_id: str
    from_level: str
    to_level: str
    approved_at: float


@dataclass
class RejectRequest:
    """Request to reject an elevation proposal."""
    
    proposal_id: str
    reason: Optional[str] = None


@dataclass
class RejectResult:
    """Result of rejecting an elevation."""
    
    proposal_id: str
    belief_id: str
    rejected_at: float
    reason: Optional[str] = None


class ElevationProposalService:
    """Service for managing content elevation proposal workflows.
    
    This service implements the proposal-approval pattern for elevation:
    1. Anyone can propose elevating content to a higher level
    2. The content owner must approve the proposal
    3. On approval, elevated content is created at the new level
    4. Original content remains at original level
    5. Full history is tracked
    """
    
    DEFAULT_EXPIRY_SECONDS = 7 * 24 * 60 * 60  # 7 days
    
    def __init__(
        self,
        db: ProposalDatabaseProtocol,
        on_proposal_created: Optional[Callable[[ElevationProposal], None]] = None,
        on_proposal_decided: Optional[Callable[[ElevationProposal], None]] = None,
    ):
        self.db = db
        self._on_proposal_created = on_proposal_created
        self._on_proposal_decided = on_proposal_decided
    
    async def propose(
        self,
        request: ProposeRequest,
        proposer_did: str,
    ) -> ProposeResult:
        """Propose elevating content to a higher visibility level.
        
        Args:
            request: The elevation request
            proposer_did: DID of the entity proposing elevation
            
        Returns:
            ProposeResult with proposal details
            
        Raises:
            ValueError: If belief not found or invalid elevation
        """
        # Get belief and validate
        belief = await self.db.get_belief(request.belief_id)
        if not belief:
            raise ValueError("Belief not found")
        
        owner_did = await self.db.get_belief_owner(request.belief_id)
        if not owner_did:
            raise ValueError("Could not determine belief owner")
        
        current_level = await self.db.get_belief_share_level(request.belief_id)
        if not current_level:
            current_level = "private"  # Default assumption
        
        # Validate elevation path
        if not is_valid_elevation(current_level, request.to_level):
            raise ValueError(
                f"Invalid elevation: cannot elevate from {current_level} to {request.to_level}"
            )
        
        # Check for existing pending proposal
        existing = await self.db.list_proposals_for_belief(
            request.belief_id, 
            status=ProposalStatus.PENDING
        )
        if existing:
            raise ValueError("A pending proposal already exists for this belief")
        
        # Create proposal
        proposal_id = str(uuid.uuid4())
        now = time.time()
        expires_in = request.expires_in_seconds or self.DEFAULT_EXPIRY_SECONDS
        
        proposal = ElevationProposal(
            id=proposal_id,
            belief_id=request.belief_id,
            owner_did=owner_did,
            proposer_did=proposer_did,
            from_level=current_level,
            to_level=request.to_level,
            status=ProposalStatus.PENDING,
            proposed_at=now,
            expires_at=now + expires_in,
            transform=request.transform or ContentTransform.identity(),
            justification=request.justification,
        )
        
        await self.db.create_elevation_proposal(proposal)
        
        # Notify
        if self._on_proposal_created:
            self._on_proposal_created(proposal)
        
        return ProposeResult(
            proposal_id=proposal_id,
            belief_id=request.belief_id,
            from_level=current_level,
            to_level=request.to_level,
            status=ProposalStatus.PENDING,
            expires_at=proposal.expires_at,
        )
    
    async def approve(
        self,
        request: ApproveRequest,
        approver_did: str,
    ) -> ApproveResult:
        """Approve an elevation proposal.
        
        Only the content owner can approve.
        
        Args:
            request: The approval request
            approver_did: DID of the entity approving
            
        Returns:
            ApproveResult with elevated content details
            
        Raises:
            ValueError: If proposal not found or not pending
            PermissionError: If approver is not the owner
        """
        proposal = await self.db.get_elevation_proposal(request.proposal_id)
        if not proposal:
            raise ValueError("Proposal not found")
        
        if proposal.status != ProposalStatus.PENDING:
            raise ValueError(f"Proposal is not pending (status: {proposal.status.value})")
        
        if proposal.is_expired:
            # Mark as expired
            proposal.status = ProposalStatus.EXPIRED
            proposal.decided_at = time.time()
            await self.db.update_elevation_proposal(proposal)
            raise ValueError("Proposal has expired")
        
        if proposal.owner_did != approver_did:
            raise PermissionError("Only the content owner can approve elevation")
        
        # Get original content
        belief = await self.db.get_belief(proposal.belief_id)
        if not belief:
            raise ValueError("Original belief no longer exists")
        
        # Get content - handle both dict and object
        original_content = (
            belief.get("content") if isinstance(belief, dict)
            else getattr(belief, "content", None)
        )
        if not original_content:
            raise ValueError("Belief has no content")
        
        # Apply transform (owner can modify)
        transform = request.modified_transform or proposal.transform
        if transform.transformed_content:
            elevated_content = transform.transformed_content
        else:
            elevated_content = original_content
        
        # Create elevated belief
        elevated_belief_id = await self.db.create_elevated_belief(
            original_belief_id=proposal.belief_id,
            new_level=proposal.to_level,
            content=elevated_content,
            owner_did=proposal.owner_did,
        )
        
        # Update proposal
        now = time.time()
        proposal.status = ProposalStatus.APPROVED
        proposal.decided_at = now
        proposal.decided_by = approver_did
        proposal.decision_reason = request.reason
        proposal.elevated_belief_id = elevated_belief_id
        proposal.transform = transform
        
        await self.db.update_elevation_proposal(proposal)
        
        # Record history
        history_entry = ElevationHistoryEntry(
            id=str(uuid.uuid4()),
            belief_id=proposal.belief_id,
            proposal_id=proposal.id,
            from_level=proposal.from_level,
            to_level=proposal.to_level,
            proposer_did=proposal.proposer_did,
            approver_did=approver_did,
            proposed_at=proposal.proposed_at,
            approved_at=now,
            transform=transform,
            original_belief_id=proposal.belief_id,
            elevated_belief_id=elevated_belief_id,
        )
        await self.db.create_elevation_history(history_entry)
        
        # Notify
        if self._on_proposal_decided:
            self._on_proposal_decided(proposal)
        
        return ApproveResult(
            proposal_id=proposal.id,
            original_belief_id=proposal.belief_id,
            elevated_belief_id=elevated_belief_id,
            from_level=proposal.from_level,
            to_level=proposal.to_level,
            approved_at=now,
        )
    
    async def reject(
        self,
        request: RejectRequest,
        rejector_did: str,
    ) -> RejectResult:
        """Reject an elevation proposal.
        
        Only the content owner can reject.
        
        Args:
            request: The rejection request
            rejector_did: DID of the entity rejecting
            
        Returns:
            RejectResult with rejection details
            
        Raises:
            ValueError: If proposal not found or not pending
            PermissionError: If rejector is not the owner
        """
        proposal = await self.db.get_elevation_proposal(request.proposal_id)
        if not proposal:
            raise ValueError("Proposal not found")
        
        if proposal.status != ProposalStatus.PENDING:
            raise ValueError(f"Proposal is not pending (status: {proposal.status.value})")
        
        if proposal.owner_did != rejector_did:
            raise PermissionError("Only the content owner can reject elevation")
        
        # Update proposal
        now = time.time()
        proposal.status = ProposalStatus.REJECTED
        proposal.decided_at = now
        proposal.decided_by = rejector_did
        proposal.decision_reason = request.reason
        
        await self.db.update_elevation_proposal(proposal)
        
        # Notify
        if self._on_proposal_decided:
            self._on_proposal_decided(proposal)
        
        return RejectResult(
            proposal_id=proposal.id,
            belief_id=proposal.belief_id,
            rejected_at=now,
            reason=request.reason,
        )
    
    async def withdraw(
        self,
        proposal_id: str,
        withdrawer_did: str,
    ) -> ElevationProposal:
        """Withdraw an elevation proposal.
        
        Only the proposer can withdraw.
        
        Args:
            proposal_id: ID of the proposal to withdraw
            withdrawer_did: DID of the entity withdrawing
            
        Returns:
            The updated proposal
            
        Raises:
            ValueError: If proposal not found or not pending
            PermissionError: If withdrawer is not the proposer
        """
        proposal = await self.db.get_elevation_proposal(proposal_id)
        if not proposal:
            raise ValueError("Proposal not found")
        
        if proposal.status != ProposalStatus.PENDING:
            raise ValueError(f"Proposal is not pending (status: {proposal.status.value})")
        
        if proposal.proposer_did != withdrawer_did:
            raise PermissionError("Only the proposer can withdraw")
        
        # Update proposal
        now = time.time()
        proposal.status = ProposalStatus.WITHDRAWN
        proposal.decided_at = now
        proposal.decided_by = withdrawer_did
        
        await self.db.update_elevation_proposal(proposal)
        
        # Notify
        if self._on_proposal_decided:
            self._on_proposal_decided(proposal)
        
        return proposal
    
    async def get_proposal(self, proposal_id: str) -> Optional[ElevationProposal]:
        """Get an elevation proposal by ID."""
        return await self.db.get_elevation_proposal(proposal_id)
    
    async def list_pending_for_owner(
        self, owner_did: str
    ) -> List[ElevationProposal]:
        """List pending proposals for content owned by a DID."""
        proposals = await self.db.list_proposals_for_owner(
            owner_did, status=ProposalStatus.PENDING
        )
        # Filter out expired
        return [p for p in proposals if not p.is_expired]
    
    async def list_by_proposer(
        self,
        proposer_did: str,
        status: Optional[ProposalStatus] = None,
    ) -> List[ElevationProposal]:
        """List proposals made by a DID."""
        return await self.db.list_proposals_by_proposer(proposer_did, status)
    
    async def get_history(
        self, belief_id: str
    ) -> List[ElevationHistoryEntry]:
        """Get the elevation history for a belief."""
        return await self.db.get_elevation_history(belief_id)
    
    async def expire_stale(self) -> int:
        """Expire proposals that have passed their expiry time.
        
        Returns the number of proposals expired.
        """
        # This would be called periodically by a background task
        # For now, expiry is checked on access
        return 0
