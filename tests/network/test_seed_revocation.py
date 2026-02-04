"""Tests for seed revocation functionality."""

import json
import tempfile
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from valence.network.messages import (
    SeedAnnouncement,
    SeedRevocation,
    PeerExchange,
    MessageType,
    parse_message,
)
from valence.network.seed import (
    Seed,
    SeedManager,
    RevocationEntry,
    RevocationList,
)
from valence.network.discovery import (
    DiscoveryService,
    SeedValidator,
    ValidationResult,
)


# Fixtures
@pytest.fixture
def operator_keypair():
    """Generate an operator key pair."""
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture
def seed_keypair():
    """Generate a seed key pair."""
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture
def revocation_list(operator_keypair):
    """Create a revocation list with operator key."""
    _, public_key = operator_keypair
    rev_list = RevocationList()
    rev_list.add_operator_key("operator-1", public_key)
    return rev_list


@pytest.fixture
def seed_manager(revocation_list):
    """Create a seed manager."""
    return SeedManager(
        node_id="test-node",
        revocation_list=revocation_list,
    )


@pytest.fixture
def discovery_service(seed_manager):
    """Create a discovery service."""
    return DiscoveryService(
        node_id="test-node",
        seed_manager=seed_manager,
    )


# Message Tests
class TestSeedRevocationMessage:
    """Test SeedRevocation message type."""
    
    def test_create_revocation(self, operator_keypair):
        """Test creating a revocation message."""
        private_key, _ = operator_keypair
        
        revocation = SeedRevocation(
            sender_id="test-node",
            revoked_seed_id="bad-seed-123",
            reason="Compromised private key",
            operator_key_id="operator-1",
        )
        
        assert revocation.msg_type == MessageType.SEED_REVOCATION
        assert revocation.revoked_seed_id == "bad-seed-123"
        assert revocation.reason == "Compromised private key"
        assert revocation.operator_key_id == "operator-1"
    
    def test_sign_and_verify_revocation(self, operator_keypair):
        """Test signing and verifying a revocation."""
        private_key, public_key = operator_keypair
        
        revocation = SeedRevocation(
            sender_id="test-node",
            revoked_seed_id="bad-seed-123",
            reason="Malicious behavior",
            operator_key_id="operator-1",
        )
        
        # Sign
        revocation.sign(private_key)
        assert revocation.signature is not None
        
        # Verify
        assert revocation.verify(public_key) is True
        
        # Tamper and verify fails
        revocation.reason = "Modified reason"
        assert revocation.verify(public_key) is False
    
    def test_revocation_serialization(self, operator_keypair):
        """Test revocation serialization/deserialization."""
        private_key, _ = operator_keypair
        
        revocation = SeedRevocation(
            sender_id="test-node",
            revoked_seed_id="bad-seed-456",
            reason="Key exposure",
            operator_key_id="operator-1",
        )
        revocation.sign(private_key)
        
        # Serialize
        data = revocation.to_dict()
        assert data["revoked_seed_id"] == "bad-seed-456"
        assert data["reason"] == "Key exposure"
        
        # Deserialize
        restored = SeedRevocation.from_dict(data)
        assert restored.revoked_seed_id == revocation.revoked_seed_id
        assert restored.reason == revocation.reason
        assert restored.signature == revocation.signature
    
    def test_revocation_id_generation(self):
        """Test unique revocation ID generation."""
        rev1 = SeedRevocation(
            sender_id="node-1",
            revoked_seed_id="seed-1",
            revocation_timestamp=1000.0,
            operator_key_id="op-1",
        )
        
        rev2 = SeedRevocation(
            sender_id="node-1",
            revoked_seed_id="seed-1",
            revocation_timestamp=1001.0,  # Different timestamp
            operator_key_id="op-1",
        )
        
        # Different timestamps = different IDs
        assert rev1.revocation_id() != rev2.revocation_id()
    
    def test_parse_revocation_message(self, operator_keypair):
        """Test parsing a revocation message."""
        private_key, _ = operator_keypair
        
        revocation = SeedRevocation(
            sender_id="test-node",
            revoked_seed_id="bad-seed",
            reason="Test",
            operator_key_id="operator-1",
        )
        revocation.sign(private_key)
        
        data = revocation.to_dict()
        parsed = parse_message(data)
        
        assert isinstance(parsed, SeedRevocation)
        assert parsed.revoked_seed_id == "bad-seed"


# Revocation List Tests
class TestRevocationList:
    """Test RevocationList functionality."""
    
    def test_add_revocation(self, operator_keypair):
        """Test adding a revocation."""
        private_key, public_key = operator_keypair
        rev_list = RevocationList()
        rev_list.add_operator_key("operator-1", public_key)
        
        # Create signed revocation message
        revocation = SeedRevocation(
            sender_id="test-node",
            revoked_seed_id="bad-seed",
            reason="Compromised",
            operator_key_id="operator-1",
        )
        revocation.sign(private_key)
        
        # Add from message
        result = rev_list.add_from_message(revocation)
        assert result is True
        assert rev_list.is_revoked("bad-seed") is True
    
    def test_reject_invalid_signature(self, operator_keypair):
        """Test rejecting revocation with invalid signature."""
        _, public_key = operator_keypair
        other_private = ed25519.Ed25519PrivateKey.generate()
        
        rev_list = RevocationList()
        rev_list.add_operator_key("operator-1", public_key)
        
        # Create revocation signed by wrong key
        revocation = SeedRevocation(
            sender_id="test-node",
            revoked_seed_id="bad-seed",
            reason="Test",
            operator_key_id="operator-1",
        )
        revocation.sign(other_private)
        
        result = rev_list.add_from_message(revocation)
        assert result is False
        assert rev_list.is_revoked("bad-seed") is False
    
    def test_reject_unknown_operator(self, operator_keypair):
        """Test rejecting revocation from unknown operator."""
        private_key, _ = operator_keypair
        rev_list = RevocationList()
        # Don't add operator key
        
        revocation = SeedRevocation(
            sender_id="test-node",
            revoked_seed_id="bad-seed",
            reason="Test",
            operator_key_id="unknown-operator",
        )
        revocation.sign(private_key)
        
        result = rev_list.add_from_message(revocation)
        assert result is False
    
    def test_duplicate_revocation(self, operator_keypair):
        """Test that duplicate revocations are ignored."""
        private_key, public_key = operator_keypair
        rev_list = RevocationList()
        rev_list.add_operator_key("operator-1", public_key)
        
        revocation = SeedRevocation(
            sender_id="test-node",
            revoked_seed_id="bad-seed",
            reason="Test",
            operator_key_id="operator-1",
        )
        revocation.sign(private_key)
        
        # First add succeeds
        assert rev_list.add_from_message(revocation) is True
        # Second add returns False (duplicate)
        assert rev_list.add_from_message(revocation) is False
    
    def test_file_persistence(self, operator_keypair):
        """Test saving and loading revocation list."""
        private_key, public_key = operator_keypair
        
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "revocations.json"
            
            # Create and populate list
            rev_list = RevocationList(path=path)
            rev_list.add_operator_key("operator-1", public_key)
            
            revocation = SeedRevocation(
                sender_id="test-node",
                revoked_seed_id="bad-seed",
                reason="Persistence test",
                operator_key_id="operator-1",
            )
            revocation.sign(private_key)
            rev_list.add_from_message(revocation)
            
            # Save
            assert rev_list.save_to_file() is True
            assert path.exists()
            
            # Load into new list
            rev_list2 = RevocationList()
            count = rev_list2.load_from_file(path)
            assert count == 1
            assert rev_list2.is_revoked("bad-seed") is True
    
    def test_signed_file(self, operator_keypair):
        """Test creating and loading signed revocation file."""
        private_key, public_key = operator_keypair
        
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "revocations-signed.json"
            
            # Create list
            rev_list = RevocationList()
            rev_list.add_operator_key("operator-1", public_key)
            
            revocation = SeedRevocation(
                sender_id="test-node",
                revoked_seed_id="bad-seed",
                reason="Signed file test",
                operator_key_id="operator-1",
            )
            revocation.sign(private_key)
            rev_list.add_from_message(revocation)
            
            # Create signed file
            assert rev_list.create_signed_file(path, private_key, "operator-1") is True
            
            # Load and verify
            rev_list2 = RevocationList()
            rev_list2.add_operator_key("operator-1", public_key)
            count = rev_list2.load_signed_file(path)
            
            assert count == 1
            assert rev_list2.is_revoked("bad-seed") is True
    
    def test_reject_tampered_signed_file(self, operator_keypair):
        """Test rejecting tampered signed file."""
        private_key, public_key = operator_keypair
        
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "revocations-tampered.json"
            
            rev_list = RevocationList()
            rev_list.add_operator_key("operator-1", public_key)
            
            revocation = SeedRevocation(
                sender_id="test-node",
                revoked_seed_id="bad-seed",
                reason="Original reason",
                operator_key_id="operator-1",
            )
            revocation.sign(private_key)
            rev_list.add_from_message(revocation)
            rev_list.create_signed_file(path, private_key, "operator-1")
            
            # Tamper with file
            with open(path, "r") as f:
                data = json.load(f)
            data["data"]["revocations"][0]["reason"] = "Tampered!"
            with open(path, "w") as f:
                json.dump(data, f)
            
            # Load should fail verification
            rev_list2 = RevocationList()
            rev_list2.add_operator_key("operator-1", public_key)
            count = rev_list2.load_signed_file(path)
            
            assert count == -1  # Verification failed


# Seed Manager Tests
class TestSeedManager:
    """Test SeedManager with revocation support."""
    
    def test_add_seed(self, seed_manager):
        """Test adding a seed."""
        seed = Seed(
            seed_id="good-seed",
            address="192.168.1.1",
            port=8080,
        )
        
        result = seed_manager.add_seed(seed)
        assert result is True
        assert seed_manager.get_seed("good-seed") is not None
    
    def test_reject_revoked_seed(self, seed_manager, operator_keypair):
        """Test that revoked seeds are rejected."""
        private_key, public_key = operator_keypair
        
        # Revoke a seed
        revocation = seed_manager.revoke_seed(
            seed_id="bad-seed",
            reason="Compromised",
            operator_key=private_key,
            operator_key_id="operator-1",
            propagate=False,
        )
        assert revocation is not None
        
        # Try to add the revoked seed
        seed = Seed(
            seed_id="bad-seed",
            address="10.0.0.1",
            port=8080,
        )
        
        result = seed_manager.add_seed(seed)
        assert result is False
        assert seed_manager.get_seed("bad-seed") is None
    
    def test_revoke_existing_seed(self, seed_manager, operator_keypair):
        """Test revoking an existing seed."""
        private_key, _ = operator_keypair
        
        # Add seed first
        seed = Seed(
            seed_id="to-revoke",
            address="192.168.1.2",
            port=8080,
        )
        seed_manager.add_seed(seed)
        assert seed_manager.get_seed("to-revoke") is not None
        
        # Revoke
        revocation = seed_manager.revoke_seed(
            seed_id="to-revoke",
            reason="Misbehaving",
            operator_key=private_key,
            operator_key_id="operator-1",
            propagate=False,
        )
        assert revocation is not None
        
        # Seed should no longer be accessible
        assert seed_manager.get_seed("to-revoke") is None
        assert seed_manager.is_seed_trusted("to-revoke") is False
    
    def test_handle_revocation_message(self, seed_manager, operator_keypair):
        """Test handling incoming revocation message."""
        private_key, _ = operator_keypair
        
        # Add seed
        seed = Seed(
            seed_id="remote-revoke",
            address="192.168.1.3",
            port=8080,
        )
        seed_manager.add_seed(seed)
        
        # Create revocation message
        revocation = SeedRevocation(
            sender_id="other-node",
            revoked_seed_id="remote-revoke",
            reason="Remote revocation",
            operator_key_id="operator-1",
        )
        revocation.sign(private_key)
        
        # Handle it
        result = seed_manager.handle_revocation(revocation)
        assert result is True
        assert seed_manager.is_seed_trusted("remote-revoke") is False
    
    def test_gossip_propagation(self, seed_manager, operator_keypair):
        """Test revocation gossip propagation."""
        private_key, _ = operator_keypair
        
        received_revocations = []
        
        def gossip_handler(rev):
            received_revocations.append(rev)
        
        seed_manager.add_gossip_handler(gossip_handler)
        
        # Revoke with propagation
        seed_manager.revoke_seed(
            seed_id="propagate-test",
            reason="Test propagation",
            operator_key=private_key,
            operator_key_id="operator-1",
            propagate=True,
        )
        
        assert len(received_revocations) == 1
        assert received_revocations[0].revoked_seed_id == "propagate-test"
    
    def test_peer_exchange_with_revocations(self, seed_manager, operator_keypair):
        """Test peer exchange includes revocations."""
        private_key, _ = operator_keypair
        
        # Add seed and revoke another
        seed = Seed(seed_id="good-seed", address="1.1.1.1", port=8080)
        seed_manager.add_seed(seed)
        
        seed_manager.revoke_seed(
            seed_id="revoked-seed",
            reason="Test",
            operator_key=private_key,
            operator_key_id="operator-1",
            propagate=False,
        )
        
        # Create peer exchange
        exchange = seed_manager.create_peer_exchange(include_revocations=True)
        
        assert len(exchange.peers) == 1
        assert len(exchange.revocations) == 1
        assert exchange.revocations[0]["seed_id"] == "revoked-seed"
    
    def test_handle_peer_exchange(self, operator_keypair):
        """Test handling incoming peer exchange."""
        private_key, public_key = operator_keypair
        
        # Create two seed managers
        rev_list1 = RevocationList()
        rev_list1.add_operator_key("operator-1", public_key)
        manager1 = SeedManager("node-1", revocation_list=rev_list1)
        
        rev_list2 = RevocationList()
        rev_list2.add_operator_key("operator-1", public_key)
        manager2 = SeedManager("node-2", revocation_list=rev_list2)
        
        # Manager1 has a seed and revocation
        seed = Seed(seed_id="shared-seed", address="2.2.2.2", port=8080)
        manager1.add_seed(seed)
        manager1.revoke_seed(
            seed_id="bad-shared",
            reason="Shared revocation",
            operator_key=private_key,
            operator_key_id="operator-1",
            propagate=False,
        )
        
        # Create and send peer exchange
        exchange = manager1.create_peer_exchange()
        manager2.handle_peer_exchange(exchange)
        
        # Manager2 should now know about both
        assert manager2.get_seed("shared-seed") is not None
        assert manager2.is_seed_trusted("bad-shared") is False


# Seed Validator Tests
class TestSeedValidator:
    """Test SeedValidator functionality."""
    
    def test_validate_good_seed(self, revocation_list):
        """Test validating a good seed."""
        validator = SeedValidator(revocation_list)
        
        seed = Seed(
            seed_id="good-seed",
            address="1.1.1.1",
            port=8080,
            trust_score=0.9,
            last_seen=time.time(),
        )
        
        result = validator.validate_seed(seed)
        assert result.is_valid is True
    
    def test_validate_revoked_seed(self, revocation_list, operator_keypair):
        """Test validating a revoked seed."""
        private_key, _ = operator_keypair
        validator = SeedValidator(revocation_list)
        
        # Add revocation
        revocation = SeedRevocation(
            sender_id="test",
            revoked_seed_id="revoked-seed",
            reason="Compromised",
            operator_key_id="operator-1",
        )
        revocation.sign(private_key)
        revocation_list.add_from_message(revocation)
        
        seed = Seed(
            seed_id="revoked-seed",
            address="1.1.1.1",
            port=8080,
        )
        
        result = validator.validate_seed(seed)
        assert result.is_valid is False
        assert "revoked" in result.reason.lower()
        assert result.revocation is not None
    
    def test_validate_low_trust_seed(self, revocation_list):
        """Test rejecting low trust seed."""
        validator = SeedValidator(revocation_list, min_trust_score=0.5)
        
        seed = Seed(
            seed_id="untrusted-seed",
            address="1.1.1.1",
            port=8080,
            trust_score=0.2,
        )
        
        result = validator.validate_seed(seed)
        assert result.is_valid is False
        assert "trust" in result.reason.lower()
    
    def test_validate_stale_seed(self, revocation_list):
        """Test rejecting stale seed."""
        validator = SeedValidator(revocation_list, max_age_seconds=60)
        
        seed = Seed(
            seed_id="stale-seed",
            address="1.1.1.1",
            port=8080,
            last_seen=time.time() - 3600,  # 1 hour ago
        )
        
        result = validator.validate_seed(seed)
        assert result.is_valid is False
        assert "ago" in result.reason.lower()
    
    def test_filter_valid_seeds(self, revocation_list, operator_keypair):
        """Test filtering a list of seeds."""
        private_key, _ = operator_keypair
        validator = SeedValidator(revocation_list)
        
        # Revoke one seed
        revocation = SeedRevocation(
            sender_id="test",
            revoked_seed_id="bad-seed",
            reason="Test",
            operator_key_id="operator-1",
        )
        revocation.sign(private_key)
        revocation_list.add_from_message(revocation)
        
        seeds = [
            Seed(seed_id="good-1", address="1.1.1.1", port=8080),
            Seed(seed_id="bad-seed", address="2.2.2.2", port=8080),
            Seed(seed_id="good-2", address="3.3.3.3", port=8080),
        ]
        
        valid = validator.filter_valid_seeds(seeds)
        assert len(valid) == 2
        assert all(s.seed_id.startswith("good") for s in valid)


# Discovery Service Tests
class TestDiscoveryService:
    """Test DiscoveryService functionality."""
    
    def test_handle_announcement(self, discovery_service, seed_keypair):
        """Test handling seed announcement."""
        private_key, public_key = seed_keypair
        
        announcement = SeedAnnouncement(
            sender_id="new-seed",
            seed_id="new-seed",
            address="5.5.5.5",
            port=9000,
            public_key=public_key.public_bytes_raw(),
        )
        announcement.sign(private_key)
        
        # Need to disable signature requirement for this test
        discovery_service._validator._require_signature = False
        
        result = discovery_service.handle_announcement(announcement)
        assert result is True
        assert discovery_service.is_seed_trusted("new-seed") is True
    
    def test_reject_revoked_announcement(self, discovery_service, operator_keypair, seed_keypair):
        """Test rejecting announcement for revoked seed."""
        op_private, _ = operator_keypair
        seed_private, seed_public = seed_keypair
        
        # Revoke seed first
        discovery_service.revoke_seed(
            seed_id="revoked-new",
            reason="Pre-revoked",
            operator_key=op_private,
            operator_key_id="operator-1",
            propagate=False,
        )
        
        # Try to announce
        announcement = SeedAnnouncement(
            sender_id="revoked-new",
            seed_id="revoked-new",
            address="6.6.6.6",
            port=9001,
        )
        
        discovery_service._validator._require_signature = False
        result = discovery_service.handle_announcement(announcement)
        assert result is False
    
    def test_revocation_callback(self, discovery_service, operator_keypair):
        """Test revocation event callback."""
        private_key, _ = operator_keypair
        
        revoked_seeds = []
        
        def on_revoke(seed_id, entry):
            revoked_seeds.append((seed_id, entry))
        
        discovery_service.on_revocation(on_revoke)
        
        discovery_service.revoke_seed(
            seed_id="callback-test",
            reason="Test callback",
            operator_key=private_key,
            operator_key_id="operator-1",
            propagate=False,
        )
        
        assert len(revoked_seeds) == 1
        assert revoked_seeds[0][0] == "callback-test"
    
    def test_get_trusted_seeds(self, discovery_service, operator_keypair):
        """Test getting trusted seeds."""
        private_key, _ = operator_keypair
        
        # Add some seeds
        discovery_service._validator._require_signature = False
        
        for i in range(5):
            announcement = SeedAnnouncement(
                sender_id=f"seed-{i}",
                seed_id=f"seed-{i}",
                address=f"10.0.0.{i}",
                port=8000 + i,
            )
            discovery_service.handle_announcement(announcement)
        
        # Revoke one
        discovery_service.revoke_seed(
            seed_id="seed-2",
            reason="Test",
            operator_key=private_key,
            operator_key_id="operator-1",
            propagate=False,
        )
        
        trusted = discovery_service.get_trusted_seeds()
        assert len(trusted) == 4
        assert all(s.seed_id != "seed-2" for s in trusted)


# Integration Tests
class TestIntegration:
    """Integration tests for the full revocation flow."""
    
    def test_full_revocation_flow(self, operator_keypair):
        """Test complete revocation flow across multiple nodes."""
        private_key, public_key = operator_keypair
        
        # Create three nodes
        nodes = []
        for i in range(3):
            rev_list = RevocationList()
            rev_list.add_operator_key("operator-1", public_key)
            manager = SeedManager(f"node-{i}", revocation_list=rev_list)
            nodes.append(manager)
        
        # Wire up gossip between nodes
        def make_handler(target_manager):
            def handler(rev):
                target_manager.handle_revocation(rev)
            return handler
        
        for i, manager in enumerate(nodes):
            for j, other in enumerate(nodes):
                if i != j:
                    manager.add_gossip_handler(make_handler(other))
        
        # Add a seed to all nodes
        for manager in nodes:
            seed = Seed(seed_id="shared-seed", address="1.2.3.4", port=8080)
            manager.add_seed(seed)
        
        # Revoke from node 0 with propagation
        nodes[0].revoke_seed(
            seed_id="shared-seed",
            reason="Network-wide revocation",
            operator_key=private_key,
            operator_key_id="operator-1",
            propagate=True,
        )
        
        # All nodes should now have the revocation
        for manager in nodes:
            assert manager.is_seed_trusted("shared-seed") is False
    
    def test_out_of_band_revocation(self, operator_keypair):
        """Test out-of-band revocation file distribution."""
        private_key, public_key = operator_keypair
        
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "revocations.json"
            
            # Create revocation list and sign
            rev_list = RevocationList()
            rev_list.add_operator_key("operator-1", public_key)
            
            revocation = SeedRevocation(
                sender_id="operator",
                revoked_seed_id="oob-revoked",
                reason="Out-of-band revocation",
                operator_key_id="operator-1",
            )
            revocation.sign(private_key)
            rev_list.add_from_message(revocation)
            rev_list.create_signed_file(path, private_key, "operator-1")
            
            # New node loads file
            new_rev_list = RevocationList()
            new_rev_list.add_operator_key("operator-1", public_key)
            
            manager = SeedManager("new-node", revocation_list=new_rev_list)
            
            # Load the out-of-band file
            count = new_rev_list.load_signed_file(path)
            assert count == 1
            
            # Seed should be rejected
            seed = Seed(seed_id="oob-revoked", address="1.1.1.1", port=8080)
            result = manager.add_seed(seed)
            assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
