"""KeyPackage for MLS-style group encryption."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey


@dataclass
class KeyPackage:
    """Pre-key bundle for adding a member to a group.

    Contains public keys needed to establish shared secrets with
    the new member. Must be uploaded by the member beforehand.

    In MLS terms, this is a LeafNode with init keys.
    """

    id: UUID
    member_did: str

    # HPKE keys for encryption to this member
    init_public_key: bytes  # X25519 public key for key exchange

    # Signing key for authenticating the member
    signature_public_key: bytes  # Ed25519 public key

    # Credentials
    credential_type: str = "basic"

    # Validity
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime | None = None

    # Signature over the package
    signature: bytes = b""

    def is_valid(self) -> bool:
        """Check if the KeyPackage is still valid."""
        if self.expires_at and datetime.now() > self.expires_at:
            return False
        return True

    @classmethod
    def generate(
        cls,
        member_did: str,
        signing_private_key: bytes,
        expires_in: timedelta | None = None,
    ) -> tuple[KeyPackage, bytes]:
        """Generate a new KeyPackage for a member.

        Args:
            member_did: The member's DID
            signing_private_key: Ed25519 private key for signing
            expires_in: How long the package is valid

        Returns:
            Tuple of (KeyPackage, init_private_key)
        """
        # Generate X25519 keypair for init key
        init_private = X25519PrivateKey.generate()
        init_public = init_private.public_key()

        init_private_bytes = init_private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        init_public_bytes = init_public.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

        # Get signing public key
        signing_private = Ed25519PrivateKey.from_private_bytes(signing_private_key)
        signature_public_bytes = signing_private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

        now = datetime.now()
        expires_at = now + expires_in if expires_in else None

        package = cls(
            id=uuid4(),
            member_did=member_did,
            init_public_key=init_public_bytes,
            signature_public_key=signature_public_bytes,
            created_at=now,
            expires_at=expires_at,
        )

        # Sign the package
        package.signature = package._sign(signing_private_key)

        return package, init_private_bytes

    def _sign(self, private_key: bytes) -> bytes:
        """Sign the KeyPackage content."""
        content = self._signable_content()
        signing_key = Ed25519PrivateKey.from_private_bytes(private_key)
        return signing_key.sign(content)

    def verify_signature(self) -> bool:
        """Verify the KeyPackage signature."""
        try:
            content = self._signable_content()
            public_key = Ed25519PublicKey.from_public_bytes(self.signature_public_key)
            public_key.verify(self.signature, content)
            return True
        except Exception:
            return False

    def _signable_content(self) -> bytes:
        """Get the content to be signed."""
        return json.dumps(
            {
                "id": str(self.id),
                "member_did": self.member_did,
                "init_public_key": base64.b64encode(self.init_public_key).decode(),
                "signature_public_key": base64.b64encode(self.signature_public_key).decode(),
                "credential_type": self.credential_type,
                "created_at": self.created_at.isoformat(),
                "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            },
            sort_keys=True,
        ).encode()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": str(self.id),
            "member_did": self.member_did,
            "init_public_key": base64.b64encode(self.init_public_key).decode(),
            "signature_public_key": base64.b64encode(self.signature_public_key).decode(),
            "credential_type": self.credential_type,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "signature": base64.b64encode(self.signature).decode(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KeyPackage:
        """Create from dictionary."""
        return cls(
            id=UUID(data["id"]),
            member_did=data["member_did"],
            init_public_key=base64.b64decode(data["init_public_key"]),
            signature_public_key=base64.b64decode(data["signature_public_key"]),
            credential_type=data.get("credential_type", "basic"),
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=(datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None),
            signature=base64.b64decode(data["signature"]),
        )
