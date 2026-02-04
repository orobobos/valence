"""Sharing service for Valence belief sharing.

Implements basic share() API with DIRECT level support, consent chains,
and cryptographic enforcement.
"""

from dataclasses import dataclass
from typing import Optional, Protocol, Any
import uuid
import time
import hashlib
import json
import logging

from .types import SharePolicy, ShareLevel, EnforcementType
from .encryption import EncryptionEnvelope

logger = logging.getLogger(__name__)


@dataclass
class ShareRequest:
    """Request to share a belief with a specific recipient."""
    
    belief_id: str
    recipient_did: str
    policy: Optional[SharePolicy] = None  # Defaults to DIRECT


@dataclass
class ShareResult:
    """Result of a successful share operation."""
    
    share_id: str
    consent_chain_id: str
    encrypted_for: str
    created_at: float


@dataclass
class ConsentChainEntry:
    """A consent chain tracking the origin and path of a share."""
    
    id: str
    belief_id: str
    origin_sharer: str  # DID
    origin_timestamp: float
    origin_policy: dict
    origin_signature: bytes
    hops: list
    chain_hash: bytes
    revoked: bool = False


@dataclass
class Share:
    """A share record linking encrypted content to a consent chain."""
    
    id: str
    consent_chain_id: str
    encrypted_envelope: dict
    recipient_did: str
    created_at: float
    accessed_at: Optional[float] = None


class DatabaseProtocol(Protocol):
    """Protocol for database operations required by SharingService."""
    
    async def get_belief(self, belief_id: str) -> Optional[Any]:
        """Get a belief by ID."""
        ...
    
    async def create_consent_chain(
        self,
        id: str,
        belief_id: str,
        origin_sharer: str,
        origin_timestamp: float,
        origin_policy: dict,
        origin_signature: bytes,
        chain_hash: bytes,
    ) -> None:
        """Create a consent chain record."""
        ...
    
    async def create_share(
        self,
        id: str,
        consent_chain_id: str,
        encrypted_envelope: dict,
        recipient_did: str,
    ) -> None:
        """Create a share record."""
        ...
    
    async def get_share(self, share_id: str) -> Optional[Share]:
        """Get a share by ID."""
        ...
    
    async def list_shares(
        self,
        sharer_did: Optional[str] = None,
        recipient_did: Optional[str] = None,
        limit: int = 100,
    ) -> list[Share]:
        """List shares, optionally filtered by sharer or recipient."""
        ...
    
    async def get_consent_chain(self, chain_id: str) -> Optional[ConsentChainEntry]:
        """Get a consent chain by ID."""
        ...


class IdentityProtocol(Protocol):
    """Protocol for identity operations required by SharingService."""
    
    async def get_public_key(self, did: str) -> Optional[bytes]:
        """Get the X25519 public key for a DID."""
        ...
    
    def sign(self, data: dict) -> bytes:
        """Sign data with the local identity's Ed25519 key."""
        ...
    
    def get_did(self) -> str:
        """Get the local node's DID."""
        ...


class SharingService:
    """Service for sharing beliefs with specific recipients.
    
    Implements DIRECT sharing level with:
    - Cryptographic enforcement (encryption for recipient)
    - Consent chain creation and signing
    - Policy validation
    """
    
    def __init__(self, db: DatabaseProtocol, identity_service: IdentityProtocol):
        self.db = db
        self.identity = identity_service
    
    async def share(self, request: ShareRequest, sharer_did: str) -> ShareResult:
        """Share a belief with a specific recipient.
        
        Args:
            request: The share request containing belief_id, recipient, and optional policy
            sharer_did: The DID of the entity sharing the belief
            
        Returns:
            ShareResult with share_id, consent_chain_id, and metadata
            
        Raises:
            ValueError: If validation fails (belief not found, recipient not found, etc.)
        """
        # Default to DIRECT policy
        policy = request.policy or SharePolicy(
            level=ShareLevel.DIRECT,
            enforcement=EnforcementType.CRYPTOGRAPHIC,
            recipients=[request.recipient_did],
        )
        
        # Validate: DIRECT level only for now
        if policy.level != ShareLevel.DIRECT:
            raise ValueError("Only DIRECT sharing supported in v1")
        
        # Validate: must be cryptographic enforcement for DIRECT
        if policy.enforcement != EnforcementType.CRYPTOGRAPHIC:
            raise ValueError("DIRECT sharing requires CRYPTOGRAPHIC enforcement")
        
        # Validate: recipient must be in policy recipients
        if policy.recipients is None or request.recipient_did not in policy.recipients:
            raise ValueError("Recipient not in policy recipients list")
        
        # Get the belief
        belief = await self.db.get_belief(request.belief_id)
        if not belief:
            raise ValueError("Belief not found")
        
        # Get belief content - handle both dict and object
        belief_content = (
            belief.get("content") if isinstance(belief, dict)
            else getattr(belief, "content", None)
        )
        if not belief_content:
            raise ValueError("Belief has no content")
        
        # Get recipient's public key
        recipient_key = await self.identity.get_public_key(request.recipient_did)
        if not recipient_key:
            raise ValueError("Recipient not found or has no public key")
        
        # Encrypt for recipient
        envelope = EncryptionEnvelope.encrypt(
            content=belief_content.encode("utf-8"),
            recipient_public_key=recipient_key,
        )
        
        # Create consent chain origin
        timestamp = time.time()
        consent_origin = {
            "sharer": sharer_did,
            "recipient": request.recipient_did,
            "belief_id": request.belief_id,
            "policy": policy.to_dict(),
            "timestamp": timestamp,
        }
        
        # Sign the consent
        signature = self.identity.sign(consent_origin)
        
        # Compute chain hash
        consent_json = json.dumps(consent_origin, sort_keys=True).encode("utf-8")
        chain_hash = hashlib.sha256(consent_json + signature).digest()
        
        # Store consent chain
        consent_chain_id = str(uuid.uuid4())
        await self.db.create_consent_chain(
            id=consent_chain_id,
            belief_id=request.belief_id,
            origin_sharer=sharer_did,
            origin_timestamp=timestamp,
            origin_policy=policy.to_dict(),
            origin_signature=signature,
            chain_hash=chain_hash,
        )
        
        # Store encrypted share
        share_id = str(uuid.uuid4())
        await self.db.create_share(
            id=share_id,
            consent_chain_id=consent_chain_id,
            encrypted_envelope=envelope.to_dict(),
            recipient_did=request.recipient_did,
        )
        
        logger.info(
            f"Shared belief {request.belief_id} with {request.recipient_did} "
            f"(share_id={share_id}, consent_chain_id={consent_chain_id})"
        )
        
        return ShareResult(
            share_id=share_id,
            consent_chain_id=consent_chain_id,
            encrypted_for=request.recipient_did,
            created_at=timestamp,
        )
    
    async def get_share(self, share_id: str) -> Optional[Share]:
        """Get share details by ID.
        
        Args:
            share_id: The share UUID
            
        Returns:
            Share details or None if not found
        """
        return await self.db.get_share(share_id)
    
    async def list_shares(
        self,
        sharer_did: Optional[str] = None,
        recipient_did: Optional[str] = None,
        limit: int = 100,
    ) -> list[Share]:
        """List shares, optionally filtered.
        
        Args:
            sharer_did: Filter by sharer DID
            recipient_did: Filter by recipient DID
            limit: Maximum number of results
            
        Returns:
            List of Share objects
        """
        return await self.db.list_shares(
            sharer_did=sharer_did,
            recipient_did=recipient_did,
            limit=limit,
        )
    
    async def get_consent_chain(self, chain_id: str) -> Optional[ConsentChainEntry]:
        """Get consent chain details.
        
        Args:
            chain_id: The consent chain UUID
            
        Returns:
            ConsentChainEntry or None if not found
        """
        return await self.db.get_consent_chain(chain_id)
