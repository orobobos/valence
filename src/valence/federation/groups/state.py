"""Group state for MLS-style group encryption."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from .key_package import KeyPackage
from .members import EpochSecrets, GroupMember
from .types import GroupRole, GroupStatus, MemberStatus


@dataclass
class GroupState:
    """Complete state of a federated group.

    Maintains membership roster, epoch secrets, and group configuration.
    """

    id: UUID
    name: str

    # Current state
    epoch: int = 0
    status: GroupStatus = GroupStatus.ACTIVE

    # Membership
    members: dict[str, GroupMember] = field(default_factory=dict)  # DID -> GroupMember
    pending_members: dict[str, KeyPackage] = field(default_factory=dict)  # DID -> KeyPackage

    # Secrets (only populated locally for this member)
    current_secrets: EpochSecrets | None = None

    # Init secret for first epoch (random)
    init_secret: bytes = b""

    # Configuration
    config: dict[str, Any] = field(default_factory=dict)

    # Audit
    created_at: datetime = field(default_factory=datetime.now)
    created_by: str = ""
    updated_at: datetime = field(default_factory=datetime.now)

    # Next available leaf index
    next_leaf_index: int = 0

    def get_active_members(self) -> list[GroupMember]:
        """Get all active members."""
        return [m for m in self.members.values() if m.status == MemberStatus.ACTIVE]

    def get_member(self, did: str) -> GroupMember | None:
        """Get a member by DID."""
        return self.members.get(did)

    def is_admin(self, did: str) -> bool:
        """Check if a DID has admin rights."""
        member = self.members.get(did)
        return member is not None and member.role == GroupRole.ADMIN

    def member_count(self) -> int:
        """Get count of active members."""
        return len(self.get_active_members())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary (without secrets)."""
        return {
            "id": str(self.id),
            "name": self.name,
            "epoch": self.epoch,
            "status": self.status.value,
            "members": {did: m.to_dict() for did, m in self.members.items()},
            "config": self.config,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GroupState:
        """Restore from dictionary."""
        from datetime import datetime

        return cls(
            id=UUID(data["id"]),
            name=data["name"],
            epoch=data.get("epoch", 0),
            status=GroupStatus(data.get("status", "active")),
            members={did: GroupMember.from_dict(m) for did, m in data.get("members", {}).items()},
            config=data.get("config", {}),
            created_at=(datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now()),
            created_by=data.get("created_by", ""),
            updated_at=(datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now()),
        )

    def get_group_info(self) -> dict:
        """Get group info for welcome messages."""
        return {
            "id": str(self.id),
            "name": self.name,
            "epoch": self.epoch,
            "config": self.config,
            "created_by": self.created_by,
        }

    def get_roster(self) -> list[dict]:
        """Get current roster for welcome messages."""
        return [m.to_dict() for m in self.get_active_members()]
