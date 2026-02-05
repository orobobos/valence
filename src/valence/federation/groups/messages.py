"""MLS message types for group encryption."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .constants import AES_KEY_SIZE, KDF_INFO_WELCOME_KEY, NONCE_SIZE


@dataclass
class WelcomeMessage:
    """Welcome message for a new group member.

    Contains encrypted group secrets and state, allowing the
    new member to decrypt group content from their join point.
    """

    id: UUID
    group_id: UUID

    # Who is being welcomed
    new_member_did: str

    # Encrypted group secrets (encrypted to new member's init key)
    encrypted_group_secrets: bytes = b""
    encrypted_group_secrets_nonce: bytes = b""

    # Ephemeral public key used for encryption
    ephemeral_public_key: bytes = b""

    # Current epoch info
    epoch: int = 0

    # Group info (encrypted)
    encrypted_group_info: bytes = b""
    encrypted_group_info_nonce: bytes = b""

    # Member roster at join time (encrypted)
    encrypted_roster: bytes = b""
    encrypted_roster_nonce: bytes = b""

    # Signature from adder
    adder_did: str = ""
    signature: bytes = b""

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime | None = None

    def encrypt_secrets(
        self,
        group_secrets: bytes,
        group_info: dict,
        roster: list[dict],
        recipient_init_key: bytes,
    ) -> None:
        """Encrypt group secrets for the new member.

        Uses X25519 key exchange + AES-GCM.
        """
        # Generate ephemeral keypair
        ephemeral_private = X25519PrivateKey.generate()
        ephemeral_public = ephemeral_private.public_key()

        self.ephemeral_public_key = ephemeral_public.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

        # Derive shared secret
        recipient_key = X25519PublicKey.from_public_bytes(recipient_init_key)
        shared_secret = ephemeral_private.exchange(recipient_key)

        # Derive welcome key
        welcome_key = HKDF(
            algorithm=hashes.SHA256(),
            length=AES_KEY_SIZE,
            salt=None,
            info=KDF_INFO_WELCOME_KEY,
        ).derive(shared_secret)

        aesgcm = AESGCM(welcome_key)

        # Encrypt group secrets
        nonce1 = os.urandom(NONCE_SIZE)
        self.encrypted_group_secrets = aesgcm.encrypt(nonce1, group_secrets, None)
        self.encrypted_group_secrets_nonce = nonce1

        # Encrypt group info
        nonce2 = os.urandom(NONCE_SIZE)
        group_info_bytes = json.dumps(group_info, sort_keys=True).encode()
        self.encrypted_group_info = aesgcm.encrypt(nonce2, group_info_bytes, None)
        self.encrypted_group_info_nonce = nonce2

        # Encrypt roster
        nonce3 = os.urandom(NONCE_SIZE)
        roster_bytes = json.dumps(roster, sort_keys=True).encode()
        self.encrypted_roster = aesgcm.encrypt(nonce3, roster_bytes, None)
        self.encrypted_roster_nonce = nonce3

    def decrypt_secrets(self, init_private_key: bytes) -> tuple[bytes, dict, list]:
        """Decrypt the welcome message using the member's init private key.

        Returns:
            Tuple of (group_secrets, group_info, roster)
        """
        # Load keys
        private_key = X25519PrivateKey.from_private_bytes(init_private_key)
        ephemeral_public = X25519PublicKey.from_public_bytes(self.ephemeral_public_key)

        # Derive shared secret
        shared_secret = private_key.exchange(ephemeral_public)

        # Derive welcome key
        welcome_key = HKDF(
            algorithm=hashes.SHA256(),
            length=AES_KEY_SIZE,
            salt=None,
            info=KDF_INFO_WELCOME_KEY,
        ).derive(shared_secret)

        aesgcm = AESGCM(welcome_key)

        # Decrypt secrets
        group_secrets = aesgcm.decrypt(
            self.encrypted_group_secrets_nonce,
            self.encrypted_group_secrets,
            None,
        )

        group_info_bytes = aesgcm.decrypt(
            self.encrypted_group_info_nonce,
            self.encrypted_group_info,
            None,
        )
        group_info = json.loads(group_info_bytes.decode())

        roster_bytes = aesgcm.decrypt(
            self.encrypted_roster_nonce,
            self.encrypted_roster,
            None,
        )
        roster = json.loads(roster_bytes.decode())

        return group_secrets, group_info, roster

    def sign(self, adder_private_key: bytes) -> None:
        """Sign the welcome message."""
        content = self._signable_content()
        signing_key = Ed25519PrivateKey.from_private_bytes(adder_private_key)
        self.signature = signing_key.sign(content)

    def verify_signature(self, adder_public_key: bytes) -> bool:
        """Verify the adder's signature."""
        try:
            content = self._signable_content()
            public_key = Ed25519PublicKey.from_public_bytes(adder_public_key)
            public_key.verify(self.signature, content)
            return True
        except Exception:
            return False

    def _signable_content(self) -> bytes:
        """Get content to sign."""
        return json.dumps(
            {
                "id": str(self.id),
                "group_id": str(self.group_id),
                "new_member_did": self.new_member_did,
                "epoch": self.epoch,
                "adder_did": self.adder_did,
                "created_at": self.created_at.isoformat(),
            },
            sort_keys=True,
        ).encode()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": str(self.id),
            "group_id": str(self.group_id),
            "new_member_did": self.new_member_did,
            "encrypted_group_secrets": base64.b64encode(self.encrypted_group_secrets).decode(),
            "encrypted_group_secrets_nonce": base64.b64encode(self.encrypted_group_secrets_nonce).decode(),
            "ephemeral_public_key": base64.b64encode(self.ephemeral_public_key).decode(),
            "epoch": self.epoch,
            "encrypted_group_info": base64.b64encode(self.encrypted_group_info).decode(),
            "encrypted_group_info_nonce": base64.b64encode(self.encrypted_group_info_nonce).decode(),
            "encrypted_roster": base64.b64encode(self.encrypted_roster).decode(),
            "encrypted_roster_nonce": base64.b64encode(self.encrypted_roster_nonce).decode(),
            "adder_did": self.adder_did,
            "signature": base64.b64encode(self.signature).decode(),
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WelcomeMessage:
        """Create from dictionary."""
        return cls(
            id=UUID(data["id"]),
            group_id=UUID(data["group_id"]),
            new_member_did=data["new_member_did"],
            encrypted_group_secrets=base64.b64decode(data["encrypted_group_secrets"]),
            encrypted_group_secrets_nonce=base64.b64decode(data["encrypted_group_secrets_nonce"]),
            ephemeral_public_key=base64.b64decode(data["ephemeral_public_key"]),
            epoch=data["epoch"],
            encrypted_group_info=base64.b64decode(data["encrypted_group_info"]),
            encrypted_group_info_nonce=base64.b64decode(data["encrypted_group_info_nonce"]),
            encrypted_roster=base64.b64decode(data["encrypted_roster"]),
            encrypted_roster_nonce=base64.b64decode(data["encrypted_roster_nonce"]),
            adder_did=data["adder_did"],
            signature=base64.b64decode(data["signature"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=(datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None),
        )


@dataclass
class CommitMessage:
    """A commit that changes group state (epoch transition).

    Commits are sent to existing members to notify them of
    membership changes and provide new epoch secrets.
    """

    id: UUID
    group_id: UUID

    # Epoch transition
    from_epoch: int
    to_epoch: int

    # What changed
    proposals: list[dict] = field(default_factory=list)

    # Commit secret (encrypted per member)
    # Maps member DID -> encrypted commit secret
    encrypted_commit_secrets: dict[str, dict] = field(default_factory=dict)

    # Committer info
    committer_did: str = ""
    signature: bytes = b""

    # Confirmation MAC
    confirmation_tag: bytes = b""

    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "group_id": str(self.group_id),
            "from_epoch": self.from_epoch,
            "to_epoch": self.to_epoch,
            "proposals": self.proposals,
            "encrypted_commit_secrets": self.encrypted_commit_secrets,
            "committer_did": self.committer_did,
            "signature": base64.b64encode(self.signature).decode(),
            "confirmation_tag": base64.b64encode(self.confirmation_tag).decode(),
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class RemovalAuditEntry:
    """Audit log entry for member removal.

    Provides accountability for offboarding decisions.
    """

    id: UUID
    group_id: UUID
    removed_did: str
    remover_did: str
    reason: str | None
    epoch_before: int
    epoch_after: int
    timestamp: datetime = field(default_factory=datetime.now)
    signature: bytes = b""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "group_id": str(self.group_id),
            "removed_did": self.removed_did,
            "remover_did": self.remover_did,
            "reason": self.reason,
            "epoch_before": self.epoch_before,
            "epoch_after": self.epoch_after,
            "timestamp": self.timestamp.isoformat(),
            "signature": (base64.b64encode(self.signature).decode() if self.signature else ""),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RemovalAuditEntry:
        """Create from dictionary."""
        return cls(
            id=UUID(data["id"]),
            group_id=UUID(data["group_id"]),
            removed_did=data["removed_did"],
            remover_did=data["remover_did"],
            reason=data.get("reason"),
            epoch_before=data["epoch_before"],
            epoch_after=data["epoch_after"],
            timestamp=(datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now()),
            signature=(base64.b64decode(data["signature"]) if data.get("signature") else b""),
        )
