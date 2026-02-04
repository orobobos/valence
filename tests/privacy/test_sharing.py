"""Tests for sharing service - consent chains, encryption, and policy validation."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass
from typing import Optional, Any
import json
import hashlib

from valence.privacy.sharing import (
    ShareRequest,
    ShareResult,
    SharingService,
    Share,
    ConsentChainEntry,
)
from valence.privacy.types import SharePolicy, ShareLevel, EnforcementType
from valence.privacy.encryption import generate_keypair, EncryptionEnvelope


@dataclass
class MockBelief:
    """Mock belief for testing."""
    id: str
    content: str


class MockDatabase:
    """Mock database for testing."""
    
    def __init__(self):
        self.beliefs: dict[str, MockBelief] = {}
        self.consent_chains: dict[str, dict] = {}
        self.shares: dict[str, dict] = {}
    
    async def get_belief(self, belief_id: str) -> Optional[MockBelief]:
        return self.beliefs.get(belief_id)
    
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
        self.consent_chains[id] = {
            "id": id,
            "belief_id": belief_id,
            "origin_sharer": origin_sharer,
            "origin_timestamp": origin_timestamp,
            "origin_policy": origin_policy,
            "origin_signature": origin_signature,
            "chain_hash": chain_hash,
            "hops": [],
            "revoked": False,
        }
    
    async def create_share(
        self,
        id: str,
        consent_chain_id: str,
        encrypted_envelope: dict,
        recipient_did: str,
    ) -> None:
        import time
        self.shares[id] = {
            "id": id,
            "consent_chain_id": consent_chain_id,
            "encrypted_envelope": encrypted_envelope,
            "recipient_did": recipient_did,
            "created_at": time.time(),
            "accessed_at": None,
        }
    
    async def get_share(self, share_id: str) -> Optional[Share]:
        data = self.shares.get(share_id)
        if not data:
            return None
        return Share(
            id=data["id"],
            consent_chain_id=data["consent_chain_id"],
            encrypted_envelope=data["encrypted_envelope"],
            recipient_did=data["recipient_did"],
            created_at=data["created_at"],
            accessed_at=data["accessed_at"],
        )
    
    async def list_shares(
        self,
        sharer_did: Optional[str] = None,
        recipient_did: Optional[str] = None,
        limit: int = 100,
    ) -> list[Share]:
        results = []
        for data in self.shares.values():
            if recipient_did and data["recipient_did"] != recipient_did:
                continue
            # Note: sharer_did filtering would need consent_chain lookup
            results.append(Share(
                id=data["id"],
                consent_chain_id=data["consent_chain_id"],
                encrypted_envelope=data["encrypted_envelope"],
                recipient_did=data["recipient_did"],
                created_at=data["created_at"],
                accessed_at=data["accessed_at"],
            ))
            if len(results) >= limit:
                break
        return results
    
    async def get_consent_chain(self, chain_id: str) -> Optional[ConsentChainEntry]:
        data = self.consent_chains.get(chain_id)
        if not data:
            return None
        return ConsentChainEntry(
            id=data["id"],
            belief_id=data["belief_id"],
            origin_sharer=data["origin_sharer"],
            origin_timestamp=data["origin_timestamp"],
            origin_policy=data["origin_policy"],
            origin_signature=data["origin_signature"],
            hops=data["hops"],
            chain_hash=data["chain_hash"],
            revoked=data["revoked"],
        )


class MockIdentityService:
    """Mock identity service for testing."""
    
    def __init__(self, did: str = "did:key:test-sharer"):
        self.did = did
        # Generate real X25519 keypairs for encryption testing
        self.keypairs: dict[str, tuple[bytes, bytes]] = {}
        # Ed25519-like signing (simplified for testing)
        self._sign_key = b"test-signing-key-32-bytes-long!!"
    
    def add_identity(self, did: str) -> bytes:
        """Add an identity and return its public key."""
        private, public = generate_keypair()
        self.keypairs[did] = (private, public)
        return public
    
    async def get_public_key(self, did: str) -> Optional[bytes]:
        if did in self.keypairs:
            return self.keypairs[did][1]
        return None
    
    def sign(self, data: dict) -> bytes:
        """Sign data (simplified for testing)."""
        data_json = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(self._sign_key + data_json).digest()
    
    def get_did(self) -> str:
        return self.did


class TestSharingService:
    """Tests for SharingService."""
    
    @pytest.fixture
    def db(self):
        """Create a mock database."""
        return MockDatabase()
    
    @pytest.fixture
    def identity(self):
        """Create a mock identity service."""
        return MockIdentityService()
    
    @pytest.fixture
    def service(self, db, identity):
        """Create a sharing service."""
        return SharingService(db, identity)
    
    @pytest.mark.asyncio
    async def test_share_basic(self, service, db, identity):
        """Test basic share operation."""
        # Setup: add belief and recipient identity
        belief_id = "belief-123"
        db.beliefs[belief_id] = MockBelief(id=belief_id, content="Test belief content")
        
        recipient_did = "did:key:recipient"
        identity.add_identity(recipient_did)
        
        # Share
        request = ShareRequest(
            belief_id=belief_id,
            recipient_did=recipient_did,
        )
        
        result = await service.share(request, identity.get_did())
        
        # Verify result
        assert result.share_id is not None
        assert result.consent_chain_id is not None
        assert result.encrypted_for == recipient_did
        assert result.created_at > 0
        
        # Verify consent chain was created
        assert result.consent_chain_id in db.consent_chains
        chain = db.consent_chains[result.consent_chain_id]
        assert chain["belief_id"] == belief_id
        assert chain["origin_sharer"] == identity.get_did()
        
        # Verify share was created
        assert result.share_id in db.shares
        share = db.shares[result.share_id]
        assert share["recipient_did"] == recipient_did
        assert "encrypted_content" in share["encrypted_envelope"]
    
    @pytest.mark.asyncio
    async def test_share_with_explicit_policy(self, service, db, identity):
        """Test share with explicit DIRECT policy."""
        belief_id = "belief-456"
        db.beliefs[belief_id] = MockBelief(id=belief_id, content="Another test belief")
        
        recipient_did = "did:key:bob"
        identity.add_identity(recipient_did)
        
        policy = SharePolicy.direct([recipient_did])
        
        request = ShareRequest(
            belief_id=belief_id,
            recipient_did=recipient_did,
            policy=policy,
        )
        
        result = await service.share(request, identity.get_did())
        
        # Verify policy was stored in consent chain
        chain = db.consent_chains[result.consent_chain_id]
        assert chain["origin_policy"]["level"] == "direct"
        assert chain["origin_policy"]["enforcement"] == "cryptographic"
    
    @pytest.mark.asyncio
    async def test_share_belief_not_found(self, service, db, identity):
        """Test share with non-existent belief."""
        identity.add_identity("did:key:recipient")
        
        request = ShareRequest(
            belief_id="nonexistent",
            recipient_did="did:key:recipient",
        )
        
        with pytest.raises(ValueError, match="Belief not found"):
            await service.share(request, identity.get_did())
    
    @pytest.mark.asyncio
    async def test_share_recipient_not_found(self, service, db, identity):
        """Test share with non-existent recipient."""
        belief_id = "belief-789"
        db.beliefs[belief_id] = MockBelief(id=belief_id, content="Content")
        
        request = ShareRequest(
            belief_id=belief_id,
            recipient_did="did:key:unknown",
        )
        
        with pytest.raises(ValueError, match="Recipient not found"):
            await service.share(request, identity.get_did())
    
    @pytest.mark.asyncio
    async def test_share_non_direct_level_rejected(self, service, db, identity):
        """Test that non-DIRECT levels are rejected in v1."""
        belief_id = "belief-001"
        db.beliefs[belief_id] = MockBelief(id=belief_id, content="Content")
        
        recipient_did = "did:key:recipient"
        identity.add_identity(recipient_did)
        
        # Try BOUNDED level
        policy = SharePolicy.bounded(max_hops=3)
        
        request = ShareRequest(
            belief_id=belief_id,
            recipient_did=recipient_did,
            policy=policy,
        )
        
        with pytest.raises(ValueError, match="Only DIRECT sharing supported"):
            await service.share(request, identity.get_did())
    
    @pytest.mark.asyncio
    async def test_share_recipient_not_in_policy(self, service, db, identity):
        """Test that recipient must be in policy recipients list."""
        belief_id = "belief-002"
        db.beliefs[belief_id] = MockBelief(id=belief_id, content="Content")
        
        recipient_did = "did:key:bob"
        other_did = "did:key:alice"
        identity.add_identity(recipient_did)
        
        # Policy with different recipient
        policy = SharePolicy.direct([other_did])
        
        request = ShareRequest(
            belief_id=belief_id,
            recipient_did=recipient_did,
            policy=policy,
        )
        
        with pytest.raises(ValueError, match="Recipient not in policy"):
            await service.share(request, identity.get_did())


class TestEncryptionVerification:
    """Tests verifying encryption works end-to-end."""
    
    @pytest.fixture
    def db(self):
        return MockDatabase()
    
    @pytest.fixture
    def identity(self):
        return MockIdentityService()
    
    @pytest.fixture
    def service(self, db, identity):
        return SharingService(db, identity)
    
    @pytest.mark.asyncio
    async def test_encrypted_content_decryptable(self, service, db, identity):
        """Test that shared content can be decrypted by recipient."""
        belief_id = "belief-enc-001"
        original_content = "This is secret content that should be encrypted."
        db.beliefs[belief_id] = MockBelief(id=belief_id, content=original_content)
        
        recipient_did = "did:key:decryptor"
        recipient_public = identity.add_identity(recipient_did)
        recipient_private = identity.keypairs[recipient_did][0]
        
        request = ShareRequest(
            belief_id=belief_id,
            recipient_did=recipient_did,
        )
        
        result = await service.share(request, identity.get_did())
        
        # Get the encrypted envelope
        share = db.shares[result.share_id]
        envelope = EncryptionEnvelope.from_dict(share["encrypted_envelope"])
        
        # Decrypt as recipient
        decrypted = EncryptionEnvelope.decrypt(envelope, recipient_private)
        
        assert decrypted.decode("utf-8") == original_content
    
    @pytest.mark.asyncio
    async def test_encrypted_content_different_per_recipient(self, service, db, identity):
        """Test that encryption produces different ciphertext for same content."""
        belief_id = "belief-enc-002"
        db.beliefs[belief_id] = MockBelief(id=belief_id, content="Same content")
        
        # Two different recipients
        identity.add_identity("did:key:alice")
        identity.add_identity("did:key:bob")
        
        request1 = ShareRequest(belief_id=belief_id, recipient_did="did:key:alice")
        request2 = ShareRequest(belief_id=belief_id, recipient_did="did:key:bob")
        
        result1 = await service.share(request1, identity.get_did())
        result2 = await service.share(request2, identity.get_did())
        
        share1 = db.shares[result1.share_id]
        share2 = db.shares[result2.share_id]
        
        # Different encrypted content (due to different ephemeral keys and recipients)
        assert share1["encrypted_envelope"]["encrypted_content"] != share2["encrypted_envelope"]["encrypted_content"]


class TestConsentChain:
    """Tests for consent chain creation and integrity."""
    
    @pytest.fixture
    def db(self):
        return MockDatabase()
    
    @pytest.fixture
    def identity(self):
        return MockIdentityService()
    
    @pytest.fixture
    def service(self, db, identity):
        return SharingService(db, identity)
    
    @pytest.mark.asyncio
    async def test_consent_chain_has_signature(self, service, db, identity):
        """Test that consent chain includes a signature."""
        belief_id = "belief-cc-001"
        db.beliefs[belief_id] = MockBelief(id=belief_id, content="Content")
        
        recipient_did = "did:key:recipient"
        identity.add_identity(recipient_did)
        
        request = ShareRequest(belief_id=belief_id, recipient_did=recipient_did)
        result = await service.share(request, identity.get_did())
        
        chain = db.consent_chains[result.consent_chain_id]
        
        assert chain["origin_signature"] is not None
        assert len(chain["origin_signature"]) == 32  # SHA256 digest
    
    @pytest.mark.asyncio
    async def test_consent_chain_has_hash(self, service, db, identity):
        """Test that consent chain has integrity hash."""
        belief_id = "belief-cc-002"
        db.beliefs[belief_id] = MockBelief(id=belief_id, content="Content")
        
        recipient_did = "did:key:recipient"
        identity.add_identity(recipient_did)
        
        request = ShareRequest(belief_id=belief_id, recipient_did=recipient_did)
        result = await service.share(request, identity.get_did())
        
        chain = db.consent_chains[result.consent_chain_id]
        
        assert chain["chain_hash"] is not None
        assert len(chain["chain_hash"]) == 32  # SHA256 digest
    
    @pytest.mark.asyncio
    async def test_consent_chain_includes_policy(self, service, db, identity):
        """Test that consent chain stores the policy."""
        belief_id = "belief-cc-003"
        db.beliefs[belief_id] = MockBelief(id=belief_id, content="Content")
        
        recipient_did = "did:key:recipient"
        identity.add_identity(recipient_did)
        
        request = ShareRequest(belief_id=belief_id, recipient_did=recipient_did)
        result = await service.share(request, identity.get_did())
        
        chain = db.consent_chains[result.consent_chain_id]
        
        assert chain["origin_policy"]["level"] == "direct"
        assert chain["origin_policy"]["enforcement"] == "cryptographic"
        assert recipient_did in chain["origin_policy"]["recipients"]


class TestShareRetrieval:
    """Tests for share retrieval operations."""
    
    @pytest.fixture
    def db(self):
        return MockDatabase()
    
    @pytest.fixture
    def identity(self):
        return MockIdentityService()
    
    @pytest.fixture
    def service(self, db, identity):
        return SharingService(db, identity)
    
    @pytest.mark.asyncio
    async def test_get_share(self, service, db, identity):
        """Test getting a share by ID."""
        # Create a share
        belief_id = "belief-get-001"
        db.beliefs[belief_id] = MockBelief(id=belief_id, content="Content")
        identity.add_identity("did:key:recipient")
        
        request = ShareRequest(belief_id=belief_id, recipient_did="did:key:recipient")
        result = await service.share(request, identity.get_did())
        
        # Retrieve it
        share = await service.get_share(result.share_id)
        
        assert share is not None
        assert share.id == result.share_id
        assert share.recipient_did == "did:key:recipient"
    
    @pytest.mark.asyncio
    async def test_get_share_not_found(self, service, db, identity):
        """Test getting a non-existent share."""
        share = await service.get_share("nonexistent-id")
        assert share is None
    
    @pytest.mark.asyncio
    async def test_list_shares(self, service, db, identity):
        """Test listing shares."""
        # Create multiple shares
        for i in range(3):
            belief_id = f"belief-list-{i}"
            db.beliefs[belief_id] = MockBelief(id=belief_id, content=f"Content {i}")
            identity.add_identity(f"did:key:recipient-{i}")
            
            request = ShareRequest(
                belief_id=belief_id,
                recipient_did=f"did:key:recipient-{i}",
            )
            await service.share(request, identity.get_did())
        
        # List all
        shares = await service.list_shares()
        assert len(shares) == 3
    
    @pytest.mark.asyncio
    async def test_list_shares_by_recipient(self, service, db, identity):
        """Test listing shares filtered by recipient."""
        # Create shares to different recipients
        for i in range(3):
            belief_id = f"belief-filter-{i}"
            db.beliefs[belief_id] = MockBelief(id=belief_id, content=f"Content {i}")
            identity.add_identity(f"did:key:r-{i}")
            
            request = ShareRequest(
                belief_id=belief_id,
                recipient_did=f"did:key:r-{i}",
            )
            await service.share(request, identity.get_did())
        
        # Filter by recipient
        shares = await service.list_shares(recipient_did="did:key:r-1")
        assert len(shares) == 1
        assert shares[0].recipient_did == "did:key:r-1"
