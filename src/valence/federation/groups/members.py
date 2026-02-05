"""Group member and epoch secrets for MLS-style group encryption."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .constants import (
    AES_KEY_SIZE,
    KDF_INFO_ENCRYPTION_KEY,
    KDF_INFO_EPOCH_SECRET,
    KDF_INFO_MEMBER_SECRET,
)
from .types import GroupRole, MemberStatus


@dataclass
class GroupMember:
    """A member of a federated group."""

    did: str
    role: GroupRole = GroupRole.MEMBER
    status: MemberStatus = MemberStatus.ACTIVE

    # Key material (for active members)
    init_public_key: bytes = b""
    signature_public_key: bytes = b""

    # Epoch when member joined
    joined_at_epoch: int = 0

    # Timestamps
    joined_at: datetime = field(default_factory=datetime.now)
    removed_at: datetime | None = None

    # Leaf index in the ratchet tree (for key derivation)
    leaf_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "did": self.did,
            "role": self.role.value,
            "status": self.status.value,
            "init_public_key": (base64.b64encode(self.init_public_key).decode() if self.init_public_key else ""),
            "signature_public_key": (base64.b64encode(self.signature_public_key).decode() if self.signature_public_key else ""),
            "joined_at_epoch": self.joined_at_epoch,
            "joined_at": self.joined_at.isoformat(),
            "removed_at": self.removed_at.isoformat() if self.removed_at else None,
            "leaf_index": self.leaf_index,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GroupMember:
        """Create from dictionary."""
        return cls(
            did=data["did"],
            role=GroupRole(data.get("role", "member")),
            status=MemberStatus(data.get("status", "active")),
            init_public_key=(base64.b64decode(data["init_public_key"]) if data.get("init_public_key") else b""),
            signature_public_key=(base64.b64decode(data["signature_public_key"]) if data.get("signature_public_key") else b""),
            joined_at_epoch=data.get("joined_at_epoch", 0),
            joined_at=(datetime.fromisoformat(data["joined_at"]) if data.get("joined_at") else datetime.now()),
            removed_at=(datetime.fromisoformat(data["removed_at"]) if data.get("removed_at") else None),
            leaf_index=data.get("leaf_index", 0),
        )


@dataclass
class EpochSecrets:
    """Cryptographic secrets for a specific epoch.

    Each epoch has its own set of derived keys to provide
    forward secrecy and post-compromise security.
    """

    epoch: int

    # Core secret for this epoch
    epoch_secret: bytes = b""

    # Derived keys
    encryption_key: bytes = b""  # For encrypting group content

    # Tree secret for deriving member-specific secrets
    tree_secret: bytes = b""

    # Confirmation key for verifying commits
    confirmation_key: bytes = b""

    @classmethod
    def derive(cls, epoch: int, init_secret: bytes, commit_secret: bytes | None = None) -> EpochSecrets:
        """Derive epoch secrets from init secret and optional commit secret.

        Args:
            epoch: The epoch number
            init_secret: Random secret (for first epoch) or previous epoch's tree secret
            commit_secret: Fresh randomness from the commit (if any)
        """
        # Combine secrets if commit_secret provided
        if commit_secret:
            combined = init_secret + commit_secret
        else:
            combined = init_secret

        # Derive epoch secret
        epoch_secret = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=epoch.to_bytes(8, "big"),
            info=KDF_INFO_EPOCH_SECRET,
        ).derive(combined)

        # Derive encryption key
        encryption_key = HKDF(
            algorithm=hashes.SHA256(),
            length=AES_KEY_SIZE,
            salt=None,
            info=KDF_INFO_ENCRYPTION_KEY,
        ).derive(epoch_secret)

        # Derive tree secret (for member secrets and next epoch)
        tree_secret = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"valence-mls-tree-secret",
        ).derive(epoch_secret)

        # Derive confirmation key
        confirmation_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"valence-mls-confirmation-key",
        ).derive(epoch_secret)

        return cls(
            epoch=epoch,
            epoch_secret=epoch_secret,
            encryption_key=encryption_key,
            tree_secret=tree_secret,
            confirmation_key=confirmation_key,
        )

    def derive_member_secret(self, leaf_index: int) -> bytes:
        """Derive a member-specific secret from the tree secret."""
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=leaf_index.to_bytes(4, "big"),
            info=KDF_INFO_MEMBER_SECRET,
        ).derive(self.tree_secret)
