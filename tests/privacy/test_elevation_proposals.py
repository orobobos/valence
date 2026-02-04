# Tests for Elevation Proposal Workflow
"""
Test suite for content elevation proposal and approval workflow.

Tests the explicit proposal-approval workflow for transitioning content
between ShareLevel privacy levels (PRIVATE -> DIRECT -> BOUNDED -> etc).
"""

import pytest
import time
from dataclasses import dataclass
from typing import Optional, List, Any

from valence.privacy.elevation_proposals import (
    ProposalStatus,
    TransformType,
    ContentTransform,
    ElevationProposal,
    ElevationHistoryEntry,
    ElevationProposalService,
    ProposeRequest,
    ApproveRequest,
    RejectRequest,
    is_valid_elevation,
    SHARE_LEVEL_ORDER,
)


@dataclass
class MockBelief:
    """Mock belief for testing."""
    id: str
    content: str
    owner_did: str
    share_level: str = "private"


class MockProposalDatabase:
    """Mock database for testing elevation proposal workflow."""
    
    def __init__(self):
        self.beliefs: dict[str, MockBelief] = {}
        self.proposals: dict[str, ElevationProposal] = {}
        self.history: list[ElevationHistoryEntry] = []
        self._next_belief_id = 1
    
    async def get_belief(self, belief_id: str) -> Optional[MockBelief]:
        return self.beliefs.get(belief_id)
    
    async def get_belief_owner(self, belief_id: str) -> Optional[str]:
        belief = self.beliefs.get(belief_id)
        return belief.owner_did if belief else None
    
    async def get_belief_share_level(self, belief_id: str) -> Optional[str]:
        belief = self.beliefs.get(belief_id)
        return belief.share_level if belief else None
    
    async def create_elevation_proposal(self, proposal: ElevationProposal) -> None:
        self.proposals[proposal.id] = proposal
    
    async def get_elevation_proposal(self, proposal_id: str) -> Optional[ElevationProposal]:
        return self.proposals.get(proposal_id)
    
    async def update_elevation_proposal(self, proposal: ElevationProposal) -> None:
        self.proposals[proposal.id] = proposal
    
    async def list_proposals_for_owner(
        self, owner_did: str, status: Optional[ProposalStatus] = None
    ) -> List[ElevationProposal]:
        results = []
        for p in self.proposals.values():
            if p.owner_did != owner_did:
                continue
            if status and p.status != status:
                continue
            results.append(p)
        return results
    
    async def list_proposals_by_proposer(
        self, proposer_did: str, status: Optional[ProposalStatus] = None
    ) -> List[ElevationProposal]:
        results = []
        for p in self.proposals.values():
            if p.proposer_did != proposer_did:
                continue
            if status and p.status != status:
                continue
            results.append(p)
        return results
    
    async def list_proposals_for_belief(
        self, belief_id: str, status: Optional[ProposalStatus] = None
    ) -> List[ElevationProposal]:
        results = []
        for p in self.proposals.values():
            if p.belief_id != belief_id:
                continue
            if status and p.status != status:
                continue
            results.append(p)
        return results
    
    async def create_elevated_belief(
        self,
        original_belief_id: str,
        new_level: str,
        content: str,
        owner_did: str,
    ) -> str:
        new_id = f"elevated-{self._next_belief_id}"
        self._next_belief_id += 1
        self.beliefs[new_id] = MockBelief(
            id=new_id,
            content=content,
            owner_did=owner_did,
            share_level=new_level,
        )
        return new_id
    
    async def create_elevation_history(self, entry: ElevationHistoryEntry) -> None:
        self.history.append(entry)
    
    async def get_elevation_history(self, belief_id: str) -> List[ElevationHistoryEntry]:
        return [h for h in self.history if h.belief_id == belief_id]


class TestShareLevelOrder:
    """Tests for share level ordering and validation."""
    
    def test_share_level_order_defined(self):
        """Verify all levels are in order."""
        assert SHARE_LEVEL_ORDER == ["private", "direct", "bounded", "cascading", "public"]
    
    def test_valid_elevation_private_to_direct(self):
        """Can elevate from private to direct."""
        assert is_valid_elevation("private", "direct") is True
    
    def test_valid_elevation_private_to_public(self):
        """Can elevate from private to public (skip levels)."""
        assert is_valid_elevation("private", "public") is True
    
    def test_valid_elevation_direct_to_bounded(self):
        """Can elevate from direct to bounded."""
        assert is_valid_elevation("direct", "bounded") is True
    
    def test_invalid_elevation_same_level(self):
        """Cannot elevate to same level."""
        assert is_valid_elevation("direct", "direct") is False
    
    def test_invalid_elevation_downgrade(self):
        """Cannot downgrade (public to private)."""
        assert is_valid_elevation("public", "private") is False
        assert is_valid_elevation("bounded", "direct") is False
    
    def test_invalid_elevation_unknown_level(self):
        """Invalid levels return False."""
        assert is_valid_elevation("unknown", "public") is False
        assert is_valid_elevation("private", "unknown") is False


class TestContentTransform:
    """Tests for ContentTransform."""
    
    def test_identity_transform(self):
        """Identity transform doesn't modify content."""
        transform = ContentTransform.identity()
        assert transform.transform_type == TransformType.NONE
        assert transform.transformed_content is None
    
    def test_redact_transform(self):
        """Redaction transform applies correctly."""
        content = "My SSN is 123-45-6789 and my name is John"
        redactions = [
            {"start": 10, "end": 21, "replacement": "[SSN]"},
        ]
        
        transform = ContentTransform.redact(content, redactions)
        
        assert transform.transform_type == TransformType.REDACTED
        assert transform.transformed_content == "My SSN is [SSN] and my name is John"
        assert transform.redactions == redactions
    
    def test_redact_multiple(self):
        """Multiple redactions apply correctly."""
        content = "Name: Alice, Phone: 555-1234, Email: alice@example.com"
        redactions = [
            {"start": 6, "end": 11, "replacement": "[NAME]"},
            {"start": 20, "end": 28, "replacement": "[PHONE]"},
            {"start": 37, "end": 54, "replacement": "[EMAIL]"},
        ]
        
        transform = ContentTransform.redact(content, redactions)
        
        assert "[NAME]" in transform.transformed_content
        assert "[PHONE]" in transform.transformed_content
        assert "[EMAIL]" in transform.transformed_content
        assert "Alice" not in transform.transformed_content
    
    def test_transform_to_dict_roundtrip(self):
        """Transform serialization roundtrip."""
        original = ContentTransform(
            transform_type=TransformType.REDACTED,
            transformed_content="redacted content",
            redactions=[{"start": 0, "end": 5}],
            transform_metadata={"reason": "privacy"},
        )
        
        data = original.to_dict()
        restored = ContentTransform.from_dict(data)
        
        assert restored.transform_type == original.transform_type
        assert restored.transformed_content == original.transformed_content
        assert restored.redactions == original.redactions
        assert restored.transform_metadata == original.transform_metadata


class TestElevationProposal:
    """Tests for ElevationProposal."""
    
    def test_proposal_to_dict_roundtrip(self):
        """Proposal serialization roundtrip."""
        original = ElevationProposal(
            id="proposal-1",
            belief_id="belief-1",
            owner_did="did:key:owner",
            proposer_did="did:key:proposer",
            from_level="private",
            to_level="direct",
            justification="Need to share for review",
            transform=ContentTransform.identity(),
        )
        
        data = original.to_dict()
        restored = ElevationProposal.from_dict(data)
        
        assert restored.id == original.id
        assert restored.belief_id == original.belief_id
        assert restored.owner_did == original.owner_did
        assert restored.proposer_did == original.proposer_did
        assert restored.from_level == original.from_level
        assert restored.to_level == original.to_level
        assert restored.justification == original.justification
    
    def test_is_pending(self):
        """Test is_pending property."""
        proposal = ElevationProposal(
            id="p1", belief_id="b1", owner_did="o", proposer_did="p",
            from_level="private", to_level="direct",
            status=ProposalStatus.PENDING,
        )
        assert proposal.is_pending is True
        
        proposal.status = ProposalStatus.APPROVED
        assert proposal.is_pending is False
    
    def test_is_expired(self):
        """Test is_expired property."""
        # Not expired - no expiry set
        proposal = ElevationProposal(
            id="p1", belief_id="b1", owner_did="o", proposer_did="p",
            from_level="private", to_level="direct",
        )
        assert proposal.is_expired is False
        
        # Not expired - future expiry
        proposal.expires_at = time.time() + 3600
        assert proposal.is_expired is False
        
        # Expired - past expiry
        proposal.expires_at = time.time() - 1
        assert proposal.is_expired is True


class TestElevationProposalService:
    """Tests for ElevationProposalService."""
    
    @pytest.fixture
    def db(self):
        """Create mock database with test data."""
        db = MockProposalDatabase()
        # Add a test belief
        db.beliefs["belief-1"] = MockBelief(
            id="belief-1",
            content="This is private content with SSN 123-45-6789",
            owner_did="did:key:alice",
            share_level="private",
        )
        return db
    
    @pytest.fixture
    def service(self, db):
        """Create elevation proposal service."""
        return ElevationProposalService(db)
    
    @pytest.mark.asyncio
    async def test_propose_success(self, service, db):
        """Successfully propose an elevation."""
        request = ProposeRequest(
            belief_id="belief-1",
            to_level="direct",
            justification="Need to share for review",
        )
        
        result = await service.propose(request, proposer_did="did:key:bob")
        
        assert result.proposal_id is not None
        assert result.belief_id == "belief-1"
        assert result.from_level == "private"
        assert result.to_level == "direct"
        assert result.status == ProposalStatus.PENDING
        assert result.expires_at is not None
        
        # Verify stored
        proposal = await db.get_elevation_proposal(result.proposal_id)
        assert proposal is not None
        assert proposal.proposer_did == "did:key:bob"
    
    @pytest.mark.asyncio
    async def test_propose_not_found(self, service):
        """Proposing elevation for non-existent belief fails."""
        request = ProposeRequest(
            belief_id="nonexistent",
            to_level="direct",
        )
        
        with pytest.raises(ValueError, match="Belief not found"):
            await service.propose(request, "did:key:bob")
    
    @pytest.mark.asyncio
    async def test_propose_invalid_path(self, service, db):
        """Proposing invalid elevation path fails."""
        # Try to "elevate" to same level
        request = ProposeRequest(
            belief_id="belief-1",
            to_level="private",  # Same as current
        )
        
        with pytest.raises(ValueError, match="Invalid elevation"):
            await service.propose(request, "did:key:bob")
    
    @pytest.mark.asyncio
    async def test_propose_duplicate_pending(self, service, db):
        """Cannot create duplicate pending proposals."""
        request = ProposeRequest(
            belief_id="belief-1",
            to_level="direct",
        )
        
        # First proposal succeeds
        await service.propose(request, "did:key:bob")
        
        # Second proposal fails
        with pytest.raises(ValueError, match="pending proposal already exists"):
            await service.propose(request, "did:key:charlie")
    
    @pytest.mark.asyncio
    async def test_approve_success(self, service, db):
        """Owner can approve elevation."""
        # First create a proposal
        request = ProposeRequest(
            belief_id="belief-1",
            to_level="direct",
        )
        propose_result = await service.propose(request, "did:key:bob")
        
        # Owner approves
        approve_request = ApproveRequest(
            proposal_id=propose_result.proposal_id,
            reason="Approved for sharing",
        )
        result = await service.approve(approve_request, "did:key:alice")
        
        assert result.proposal_id == propose_result.proposal_id
        assert result.original_belief_id == "belief-1"
        assert result.elevated_belief_id is not None
        assert result.from_level == "private"
        assert result.to_level == "direct"
        
        # Verify elevated belief created
        elevated = await db.get_belief(result.elevated_belief_id)
        assert elevated is not None
        assert elevated.share_level == "direct"
        
        # Verify history recorded
        history = await db.get_elevation_history("belief-1")
        assert len(history) == 1
        assert history[0].proposer_did == "did:key:bob"
        assert history[0].approver_did == "did:key:alice"
    
    @pytest.mark.asyncio
    async def test_approve_not_owner(self, service, db):
        """Non-owner cannot approve."""
        request = ProposeRequest(
            belief_id="belief-1",
            to_level="direct",
        )
        propose_result = await service.propose(request, "did:key:bob")
        
        approve_request = ApproveRequest(proposal_id=propose_result.proposal_id)
        
        with pytest.raises(PermissionError, match="Only the content owner"):
            await service.approve(approve_request, "did:key:eve")
    
    @pytest.mark.asyncio
    async def test_approve_with_modified_transform(self, service, db):
        """Owner can modify transform on approval."""
        request = ProposeRequest(
            belief_id="belief-1",
            to_level="direct",
        )
        propose_result = await service.propose(request, "did:key:bob")
        
        # Owner approves with redaction
        modified_transform = ContentTransform.redact(
            "This is private content with SSN 123-45-6789",
            [{"start": 32, "end": 43, "replacement": "[REDACTED]"}],
        )
        
        approve_request = ApproveRequest(
            proposal_id=propose_result.proposal_id,
            modified_transform=modified_transform,
        )
        result = await service.approve(approve_request, "did:key:alice")
        
        # Verify elevated content is redacted
        elevated = await db.get_belief(result.elevated_belief_id)
        assert "123-45-6789" not in elevated.content
        assert "[REDACTED]" in elevated.content
    
    @pytest.mark.asyncio
    async def test_reject(self, service, db):
        """Owner can reject elevation."""
        request = ProposeRequest(
            belief_id="belief-1",
            to_level="public",
            justification="Want to make public",
        )
        propose_result = await service.propose(request, "did:key:bob")
        
        reject_request = RejectRequest(
            proposal_id=propose_result.proposal_id,
            reason="Content too sensitive for public",
        )
        result = await service.reject(reject_request, "did:key:alice")
        
        assert result.proposal_id == propose_result.proposal_id
        assert result.reason == "Content too sensitive for public"
        
        # Verify status updated
        proposal = await service.get_proposal(propose_result.proposal_id)
        assert proposal.status == ProposalStatus.REJECTED
    
    @pytest.mark.asyncio
    async def test_reject_not_owner(self, service, db):
        """Non-owner cannot reject."""
        request = ProposeRequest(
            belief_id="belief-1",
            to_level="direct",
        )
        propose_result = await service.propose(request, "did:key:bob")
        
        reject_request = RejectRequest(proposal_id=propose_result.proposal_id)
        
        with pytest.raises(PermissionError, match="Only the content owner"):
            await service.reject(reject_request, "did:key:eve")
    
    @pytest.mark.asyncio
    async def test_withdraw(self, service, db):
        """Proposer can withdraw proposal."""
        request = ProposeRequest(
            belief_id="belief-1",
            to_level="direct",
        )
        propose_result = await service.propose(request, "did:key:bob")
        
        result = await service.withdraw(
            propose_result.proposal_id,
            "did:key:bob",
        )
        
        assert result.status == ProposalStatus.WITHDRAWN
    
    @pytest.mark.asyncio
    async def test_withdraw_not_proposer(self, service, db):
        """Non-proposer cannot withdraw."""
        request = ProposeRequest(
            belief_id="belief-1",
            to_level="direct",
        )
        propose_result = await service.propose(request, "did:key:bob")
        
        with pytest.raises(PermissionError, match="Only the proposer"):
            await service.withdraw(propose_result.proposal_id, "did:key:eve")
    
    @pytest.mark.asyncio
    async def test_list_pending_for_owner(self, service, db):
        """List pending proposals for owner."""
        # Create proposals for alice's content
        request = ProposeRequest(
            belief_id="belief-1",
            to_level="direct",
        )
        await service.propose(request, "did:key:bob")
        
        # Add another belief owned by alice
        db.beliefs["belief-2"] = MockBelief(
            id="belief-2",
            content="Another belief",
            owner_did="did:key:alice",
            share_level="direct",
        )
        request2 = ProposeRequest(
            belief_id="belief-2",
            to_level="bounded",
        )
        await service.propose(request2, "did:key:charlie")
        
        # List for alice
        pending = await service.list_pending_for_owner("did:key:alice")
        assert len(pending) == 2
    
    @pytest.mark.asyncio
    async def test_expired_cannot_approve(self, service, db):
        """Cannot approve expired proposal."""
        # Create proposal with very short expiry
        request = ProposeRequest(
            belief_id="belief-1",
            to_level="direct",
            expires_in_seconds=0.001,  # Expires immediately
        )
        propose_result = await service.propose(request, "did:key:bob")
        
        # Wait for expiry
        time.sleep(0.01)
        
        approve_request = ApproveRequest(proposal_id=propose_result.proposal_id)
        
        with pytest.raises(ValueError, match="expired"):
            await service.approve(approve_request, "did:key:alice")
    
    @pytest.mark.asyncio
    async def test_callbacks_fired(self, db):
        """Callbacks fire on proposal events."""
        created_proposals = []
        decided_proposals = []
        
        service = ElevationProposalService(
            db,
            on_proposal_created=lambda p: created_proposals.append(p),
            on_proposal_decided=lambda p: decided_proposals.append(p),
        )
        
        # Create proposal
        request = ProposeRequest(
            belief_id="belief-1",
            to_level="direct",
        )
        result = await service.propose(request, "did:key:bob")
        assert len(created_proposals) == 1
        
        # Approve
        approve_request = ApproveRequest(proposal_id=result.proposal_id)
        await service.approve(approve_request, "did:key:alice")
        assert len(decided_proposals) == 1
        assert decided_proposals[0].status == ProposalStatus.APPROVED


class TestElevationHistoryEntry:
    """Tests for ElevationHistoryEntry."""
    
    def test_history_entry_to_dict(self):
        """History entry serialization."""
        entry = ElevationHistoryEntry(
            id="history-1",
            belief_id="belief-1",
            proposal_id="proposal-1",
            from_level="private",
            to_level="direct",
            proposer_did="did:key:bob",
            approver_did="did:key:alice",
            proposed_at=1000.0,
            approved_at=2000.0,
            transform=ContentTransform.identity(),
            original_belief_id="belief-1",
            elevated_belief_id="elevated-1",
        )
        
        data = entry.to_dict()
        
        assert data["id"] == "history-1"
        assert data["from_level"] == "private"
        assert data["to_level"] == "direct"
        assert data["proposer_did"] == "did:key:bob"
        assert data["approver_did"] == "did:key:alice"


class TestOwnerSelfElevation:
    """Tests for owner elevating their own content."""
    
    @pytest.fixture
    def db(self):
        db = MockProposalDatabase()
        db.beliefs["belief-1"] = MockBelief(
            id="belief-1",
            content="My private content",
            owner_did="did:key:alice",
            share_level="private",
        )
        return db
    
    @pytest.fixture
    def service(self, db):
        return ElevationProposalService(db)
    
    @pytest.mark.asyncio
    async def test_owner_can_propose_own_content(self, service, db):
        """Owner can propose elevation of their own content."""
        request = ProposeRequest(
            belief_id="belief-1",
            to_level="public",
        )
        result = await service.propose(request, "did:key:alice")
        
        assert result.status == ProposalStatus.PENDING
    
    @pytest.mark.asyncio
    async def test_owner_self_approval(self, service, db):
        """Owner can approve their own proposal."""
        # Propose
        request = ProposeRequest(
            belief_id="belief-1",
            to_level="direct",
        )
        propose_result = await service.propose(request, "did:key:alice")
        
        # Approve (same person)
        approve_request = ApproveRequest(proposal_id=propose_result.proposal_id)
        result = await service.approve(approve_request, "did:key:alice")
        
        assert result.elevated_belief_id is not None
        
        # History shows alice as both proposer and approver
        history = await db.get_elevation_history("belief-1")
        assert history[0].proposer_did == "did:key:alice"
        assert history[0].approver_did == "did:key:alice"
