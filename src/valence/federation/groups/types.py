"""Type definitions and enums for MLS-style group encryption."""

from enum import StrEnum


class GroupRole(StrEnum):
    """Role of a member in a group."""

    ADMIN = "admin"  # Can add/remove members, change settings
    MEMBER = "member"  # Can read/write content
    OBSERVER = "observer"  # Read-only access


# Alias for backward compatibility
MemberRole = GroupRole


class ProposalType(StrEnum):
    """Type of group change proposal."""

    ADD = "add"
    REMOVE = "remove"
    UPDATE = "update"
    REINIT = "reinit"


class MemberStatus(StrEnum):
    """Status of a group member."""

    PENDING = "pending"  # Invited but not yet joined
    ACTIVE = "active"  # Fully joined and active
    REMOVED = "removed"  # Removed from group
    LEFT = "left"  # Voluntarily left


class GroupStatus(StrEnum):
    """Status of a group."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    DISSOLVED = "dissolved"
