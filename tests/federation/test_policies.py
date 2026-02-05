"""Tests for federation admin threshold policies.

Tests cover:
- ThresholdPolicy creation and validation
- PendingApproval state management
- PolicyManager workflows (request, approve, reject)
- Automatic execution when threshold met
- Timeout/expiration handling
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from valence.federation.policies import (
    ApprovalStatus,
    Operation,
    PendingApproval,
    PolicyManager,
    ThresholdPolicy,
    get_policy_manager,
    reset_policy_manager,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def admin_dids():
    """Sample admin DIDs for testing."""
    return {
        "did:key:admin1",
        "did:key:admin2",
        "did:key:admin3",
    }


@pytest.fixture
def two_of_three_policy(admin_dids):
    """Policy requiring 2 of 3 admin approvals."""
    return ThresholdPolicy(
        operation=Operation.ADD_MEMBER,
        required_approvals=2,
        admin_dids=admin_dids,
        timeout=timedelta(hours=24),
    )


@pytest.fixture
def manager():
    """Fresh PolicyManager instance."""
    return PolicyManager()


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the singleton between tests."""
    reset_policy_manager()
    yield
    reset_policy_manager()


# =============================================================================
# THRESHOLD POLICY TESTS
# =============================================================================


class TestThresholdPolicy:
    """Tests for ThresholdPolicy dataclass."""

    def test_create_valid_policy(self, admin_dids):
        """Can create a valid threshold policy."""
        policy = ThresholdPolicy(
            operation=Operation.ADD_MEMBER,
            required_approvals=2,
            admin_dids=admin_dids,
        )

        assert policy.operation == Operation.ADD_MEMBER
        assert policy.required_approvals == 2
        assert policy.admin_dids == admin_dids
        assert policy.timeout == timedelta(hours=24)  # default

    def test_custom_timeout(self, admin_dids):
        """Can set custom timeout."""
        policy = ThresholdPolicy(
            operation=Operation.DISSOLVE,
            required_approvals=3,
            admin_dids=admin_dids,
            timeout=timedelta(days=7),
        )

        assert policy.timeout == timedelta(days=7)

    def test_converts_list_to_set(self):
        """admin_dids list is converted to set."""
        policy = ThresholdPolicy(
            operation=Operation.ADD_MEMBER,
            required_approvals=1,
            admin_dids=["did:key:a", "did:key:b"],
        )

        assert isinstance(policy.admin_dids, set)
        assert policy.admin_dids == {"did:key:a", "did:key:b"}

    def test_rejects_zero_required(self, admin_dids):
        """Rejects required_approvals < 1."""
        with pytest.raises(ValueError, match="at least 1"):
            ThresholdPolicy(
                operation=Operation.ADD_MEMBER,
                required_approvals=0,
                admin_dids=admin_dids,
            )

    def test_rejects_negative_required(self, admin_dids):
        """Rejects negative required_approvals."""
        with pytest.raises(ValueError, match="at least 1"):
            ThresholdPolicy(
                operation=Operation.ADD_MEMBER,
                required_approvals=-1,
                admin_dids=admin_dids,
            )

    def test_rejects_required_exceeds_admins(self, admin_dids):
        """Rejects required > number of admins."""
        with pytest.raises(ValueError, match="cannot exceed"):
            ThresholdPolicy(
                operation=Operation.ADD_MEMBER,
                required_approvals=5,
                admin_dids=admin_dids,  # only 3 admins
            )

    def test_rejects_empty_admins(self):
        """Rejects empty admin_dids."""
        with pytest.raises(ValueError, match="cannot be empty"):
            ThresholdPolicy(
                operation=Operation.ADD_MEMBER,
                required_approvals=1,
                admin_dids=set(),
            )

    def test_is_admin(self, two_of_three_policy):
        """is_admin correctly identifies admins."""
        assert two_of_three_policy.is_admin("did:key:admin1")
        assert two_of_three_policy.is_admin("did:key:admin2")
        assert not two_of_three_policy.is_admin("did:key:stranger")

    def test_can_approve(self, two_of_three_policy):
        """can_approve validates approval eligibility."""
        approval = PendingApproval(
            operation=Operation.ADD_MEMBER,
            payload={"did": "did:key:newmember"},
            approved_by={"did:key:admin1"},
        )

        # admin2 can approve (hasn't approved yet)
        assert two_of_three_policy.can_approve(approval, "did:key:admin2")

        # admin1 cannot approve (already approved)
        assert not two_of_three_policy.can_approve(approval, "did:key:admin1")

        # stranger cannot approve
        assert not two_of_three_policy.can_approve(approval, "did:key:stranger")

    def test_can_approve_rejects_non_pending(self, two_of_three_policy):
        """can_approve rejects non-pending approvals."""
        approval = PendingApproval(
            operation=Operation.ADD_MEMBER,
            payload={},
            status=ApprovalStatus.APPROVED,
        )

        assert not two_of_three_policy.can_approve(approval, "did:key:admin2")


# =============================================================================
# PENDING APPROVAL TESTS
# =============================================================================


class TestPendingApproval:
    """Tests for PendingApproval dataclass."""

    def test_create_approval(self):
        """Can create a pending approval."""
        approval = PendingApproval(
            operation=Operation.REMOVE_MEMBER,
            payload={"target_did": "did:key:member"},
        )

        assert approval.operation == Operation.REMOVE_MEMBER
        assert approval.payload == {"target_did": "did:key:member"}
        assert approval.approved_by == set()
        assert approval.status == ApprovalStatus.PENDING
        assert approval.id is not None

    def test_approval_count(self):
        """approval_count returns correct value."""
        approval = PendingApproval(
            operation=Operation.ADD_MEMBER,
            payload={},
            approved_by={"a", "b", "c"},
        )

        assert approval.approval_count == 3

    def test_is_expired_no_expiry(self):
        """is_expired returns False when no expiry set."""
        approval = PendingApproval(
            operation=Operation.ADD_MEMBER,
            payload={},
        )

        assert not approval.is_expired()

    def test_is_expired_not_yet(self):
        """is_expired returns False before expiry."""
        approval = PendingApproval(
            operation=Operation.ADD_MEMBER,
            payload={},
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

        assert not approval.is_expired()

    def test_is_expired_past(self):
        """is_expired returns True after expiry."""
        approval = PendingApproval(
            operation=Operation.ADD_MEMBER,
            payload={},
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )

        assert approval.is_expired()

    def test_converts_list_to_set(self):
        """approved_by list is converted to set."""
        approval = PendingApproval(
            operation=Operation.ADD_MEMBER,
            payload={},
            approved_by=["a", "b"],
        )

        assert isinstance(approval.approved_by, set)


# =============================================================================
# POLICY MANAGER TESTS
# =============================================================================


class TestPolicyManager:
    """Tests for PolicyManager class."""

    # -------------------------------------------------------------------------
    # Policy Registration
    # -------------------------------------------------------------------------

    def test_register_policy(self, manager, two_of_three_policy):
        """Can register a policy."""
        manager.register_policy(two_of_three_policy)

        retrieved = manager.get_policy(Operation.ADD_MEMBER)
        assert retrieved == two_of_three_policy

    def test_register_duplicate_raises(self, manager, two_of_three_policy):
        """Registering duplicate operation raises."""
        manager.register_policy(two_of_three_policy)

        with pytest.raises(ValueError, match="already registered"):
            manager.register_policy(two_of_three_policy)

    def test_update_policy(self, manager, admin_dids):
        """Can update an existing policy."""
        original = ThresholdPolicy(
            operation=Operation.ADD_MEMBER,
            required_approvals=2,
            admin_dids=admin_dids,
        )
        manager.register_policy(original)

        updated = ThresholdPolicy(
            operation=Operation.ADD_MEMBER,
            required_approvals=3,
            admin_dids=admin_dids,
        )
        manager.update_policy(updated)

        assert manager.get_policy(Operation.ADD_MEMBER).required_approvals == 3

    def test_get_policy_not_found(self, manager):
        """get_policy returns None for unknown operation."""
        assert manager.get_policy(Operation.DISSOLVE) is None

    # -------------------------------------------------------------------------
    # Handler Registration
    # -------------------------------------------------------------------------

    def test_register_handler(self, manager):
        """Can register an execution handler."""
        handler = MagicMock(return_value="executed")
        manager.register_handler(Operation.ADD_MEMBER, handler)

        assert Operation.ADD_MEMBER in manager._handlers

    # -------------------------------------------------------------------------
    # Approval Workflow
    # -------------------------------------------------------------------------

    def test_request_approval(self, manager, two_of_three_policy):
        """Can request an approval."""
        manager.register_policy(two_of_three_policy)

        approval = manager.request_approval(
            operation=Operation.ADD_MEMBER,
            payload={"did": "did:key:newmember"},
            requestor_did="did:key:admin1",
        )

        assert approval.operation == Operation.ADD_MEMBER
        assert approval.status == ApprovalStatus.PENDING
        assert "did:key:admin1" in approval.approved_by  # auto-approves
        assert approval.expires_at is not None

    def test_request_approval_no_policy(self, manager):
        """Requesting approval without policy raises."""
        with pytest.raises(ValueError, match="No policy"):
            manager.request_approval(
                operation=Operation.ADD_MEMBER,
                payload={},
                requestor_did="did:key:admin1",
            )

    def test_request_approval_non_admin(self, manager, two_of_three_policy):
        """Non-admin cannot request approval."""
        manager.register_policy(two_of_three_policy)

        with pytest.raises(ValueError, match="not an authorized admin"):
            manager.request_approval(
                operation=Operation.ADD_MEMBER,
                payload={},
                requestor_did="did:key:stranger",
            )

    def test_approve(self, manager, two_of_three_policy):
        """Admin can approve a pending request."""
        manager.register_policy(two_of_three_policy)

        approval = manager.request_approval(
            operation=Operation.ADD_MEMBER,
            payload={},
            requestor_did="did:key:admin1",
        )

        updated = manager.approve(approval.id, "did:key:admin2")

        assert "did:key:admin2" in updated.approved_by
        assert updated.approval_count == 2

    def test_approve_not_found(self, manager):
        """Approving unknown ID raises."""
        with pytest.raises(KeyError):
            manager.approve(uuid4(), "did:key:admin1")

    def test_approve_non_admin(self, manager, two_of_three_policy):
        """Non-admin cannot approve."""
        manager.register_policy(two_of_three_policy)

        approval = manager.request_approval(
            operation=Operation.ADD_MEMBER,
            payload={},
            requestor_did="did:key:admin1",
        )

        with pytest.raises(ValueError, match="not an authorized admin"):
            manager.approve(approval.id, "did:key:stranger")

    def test_approve_already_approved(self, manager, two_of_three_policy):
        """Cannot approve twice."""
        manager.register_policy(two_of_three_policy)

        approval = manager.request_approval(
            operation=Operation.ADD_MEMBER,
            payload={},
            requestor_did="did:key:admin1",
        )

        with pytest.raises(ValueError, match="already approved"):
            manager.approve(approval.id, "did:key:admin1")

    def test_approve_expired(self, manager, admin_dids):
        """Cannot approve expired request."""
        policy = ThresholdPolicy(
            operation=Operation.ADD_MEMBER,
            required_approvals=2,
            admin_dids=admin_dids,
            timeout=timedelta(seconds=0),  # expires immediately
        )
        manager.register_policy(policy)

        approval = manager.request_approval(
            operation=Operation.ADD_MEMBER,
            payload={},
            requestor_did="did:key:admin1",
        )

        with pytest.raises(ValueError, match="expired"):
            manager.approve(approval.id, "did:key:admin2")

    def test_reject(self, manager, two_of_three_policy):
        """Admin can reject a pending request."""
        manager.register_policy(two_of_three_policy)

        approval = manager.request_approval(
            operation=Operation.ADD_MEMBER,
            payload={},
            requestor_did="did:key:admin1",
        )

        rejected = manager.reject(approval.id, "did:key:admin2")

        assert rejected.status == ApprovalStatus.REJECTED

    def test_reject_non_admin(self, manager, two_of_three_policy):
        """Non-admin cannot reject."""
        manager.register_policy(two_of_three_policy)

        approval = manager.request_approval(
            operation=Operation.ADD_MEMBER,
            payload={},
            requestor_did="did:key:admin1",
        )

        with pytest.raises(ValueError, match="not an authorized admin"):
            manager.reject(approval.id, "did:key:stranger")

    def test_reject_not_pending(self, manager, two_of_three_policy):
        """Cannot reject non-pending approval."""
        manager.register_policy(two_of_three_policy)
        handler = MagicMock()
        manager.register_handler(Operation.ADD_MEMBER, handler)

        approval = manager.request_approval(
            operation=Operation.ADD_MEMBER,
            payload={},
            requestor_did="did:key:admin1",
        )
        manager.approve(approval.id, "did:key:admin2")

        # Now approved/executed
        with pytest.raises(ValueError, match="Cannot reject"):
            manager.reject(approval.id, "did:key:admin3")

    # -------------------------------------------------------------------------
    # Threshold Execution
    # -------------------------------------------------------------------------

    def test_executes_when_threshold_met(self, manager, two_of_three_policy):
        """Executes operation when threshold is met."""
        manager.register_policy(two_of_three_policy)

        handler = MagicMock(return_value={"success": True})
        manager.register_handler(Operation.ADD_MEMBER, handler)

        approval = manager.request_approval(
            operation=Operation.ADD_MEMBER,
            payload={"did": "did:key:new"},
            requestor_did="did:key:admin1",
        )

        # Not yet executed (1 of 2)
        assert approval.status == ApprovalStatus.PENDING
        handler.assert_not_called()

        # Second approval triggers execution
        manager.approve(approval.id, "did:key:admin2")

        assert approval.status == ApprovalStatus.APPROVED
        assert approval.executed_at is not None
        assert approval.result == {"success": True}
        handler.assert_called_once_with({"did": "did:key:new"})

    def test_single_approval_threshold(self, manager, admin_dids):
        """Single approval threshold executes immediately."""
        policy = ThresholdPolicy(
            operation=Operation.ADD_MEMBER,
            required_approvals=1,
            admin_dids=admin_dids,
        )
        manager.register_policy(policy)

        handler = MagicMock(return_value="done")
        manager.register_handler(Operation.ADD_MEMBER, handler)

        approval = manager.request_approval(
            operation=Operation.ADD_MEMBER,
            payload={"x": 1},
            requestor_did="did:key:admin1",
        )

        # Immediately executed
        assert approval.status == ApprovalStatus.APPROVED
        handler.assert_called_once()

    def test_handler_exception_captured(self, manager, admin_dids):
        """Handler exceptions are captured in result."""
        policy = ThresholdPolicy(
            operation=Operation.ADD_MEMBER,
            required_approvals=1,
            admin_dids=admin_dids,
        )
        manager.register_policy(policy)

        handler = MagicMock(side_effect=RuntimeError("boom"))
        manager.register_handler(Operation.ADD_MEMBER, handler)

        approval = manager.request_approval(
            operation=Operation.ADD_MEMBER,
            payload={},
            requestor_did="did:key:admin1",
        )

        assert approval.status == ApprovalStatus.APPROVED
        assert "error" in approval.result
        assert "boom" in approval.result["error"]

    def test_executes_without_handler(self, manager, admin_dids):
        """Execution succeeds even without handler."""
        policy = ThresholdPolicy(
            operation=Operation.ADD_MEMBER,
            required_approvals=1,
            admin_dids=admin_dids,
        )
        manager.register_policy(policy)
        # No handler registered

        approval = manager.request_approval(
            operation=Operation.ADD_MEMBER,
            payload={"data": "test"},
            requestor_did="did:key:admin1",
        )

        assert approval.status == ApprovalStatus.APPROVED
        assert approval.result is None

    # -------------------------------------------------------------------------
    # Listing and Cleanup
    # -------------------------------------------------------------------------

    def test_list_pending(self, manager, admin_dids):
        """list_pending returns pending approvals."""
        for op in [Operation.ADD_MEMBER, Operation.REMOVE_MEMBER]:
            policy = ThresholdPolicy(
                operation=op,
                required_approvals=2,
                admin_dids=admin_dids,
            )
            manager.register_policy(policy)

        manager.request_approval(
            operation=Operation.ADD_MEMBER,
            payload={},
            requestor_did="did:key:admin1",
        )
        manager.request_approval(
            operation=Operation.REMOVE_MEMBER,
            payload={},
            requestor_did="did:key:admin1",
        )

        all_pending = manager.list_pending()
        assert len(all_pending) == 2

        add_only = manager.list_pending(operation=Operation.ADD_MEMBER)
        assert len(add_only) == 1
        assert add_only[0].operation == Operation.ADD_MEMBER

    def test_list_pending_excludes_expired(self, manager, admin_dids):
        """list_pending excludes expired by default."""
        policy = ThresholdPolicy(
            operation=Operation.ADD_MEMBER,
            required_approvals=2,
            admin_dids=admin_dids,
            timeout=timedelta(seconds=0),
        )
        manager.register_policy(policy)

        manager.request_approval(
            operation=Operation.ADD_MEMBER,
            payload={},
            requestor_did="did:key:admin1",
        )

        # Expired, should not appear
        pending = manager.list_pending()
        assert len(pending) == 0

        # Include expired
        pending_all = manager.list_pending(include_expired=True)
        # Still 0 because list_pending marks them expired
        assert len(pending_all) == 0

    def test_cleanup_expired(self, manager, admin_dids):
        """cleanup_expired marks expired approvals."""
        policy = ThresholdPolicy(
            operation=Operation.ADD_MEMBER,
            required_approvals=2,
            admin_dids=admin_dids,
            timeout=timedelta(seconds=0),
        )
        manager.register_policy(policy)

        approval = manager.request_approval(
            operation=Operation.ADD_MEMBER,
            payload={},
            requestor_did="did:key:admin1",
        )

        count = manager.cleanup_expired()
        assert count == 1
        assert approval.status == ApprovalStatus.EXPIRED

    def test_get_pending(self, manager, two_of_three_policy):
        """get_pending retrieves by ID."""
        manager.register_policy(two_of_three_policy)

        approval = manager.request_approval(
            operation=Operation.ADD_MEMBER,
            payload={},
            requestor_did="did:key:admin1",
        )

        retrieved = manager.get_pending(approval.id)
        assert retrieved == approval

        assert manager.get_pending(uuid4()) is None


# =============================================================================
# SINGLETON TESTS
# =============================================================================


class TestSingleton:
    """Tests for module-level singleton."""

    def test_get_policy_manager_returns_singleton(self):
        """get_policy_manager returns the same instance."""
        m1 = get_policy_manager()
        m2 = get_policy_manager()

        assert m1 is m2

    def test_reset_clears_singleton(self):
        """reset_policy_manager clears the singleton."""
        m1 = get_policy_manager()
        reset_policy_manager()
        m2 = get_policy_manager()

        assert m1 is not m2


# =============================================================================
# OPERATION ENUM TESTS
# =============================================================================


class TestOperation:
    """Tests for Operation enum."""

    def test_all_operations_defined(self):
        """All required operations are defined."""
        assert Operation.ADD_MEMBER.value == "add_member"
        assert Operation.REMOVE_MEMBER.value == "remove_member"
        assert Operation.UPDATE_POLICY.value == "update_policy"
        assert Operation.DISSOLVE.value == "dissolve"

    def test_operation_count(self):
        """Exactly 4 operations defined."""
        assert len(Operation) == 4
