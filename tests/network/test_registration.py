"""
Tests for Router Registration Protocol (Issue #100).

Tests cover:
- Ed25519 signature verification
- Proof-of-work generation and verification
- Endpoint reachability probing
- Registration flow (router -> seed)
- Heartbeat protocol
- Anti-Sybil difficulty scaling
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from valence.network.router import RouterNode, RegistrationError
from valence.network.seed import SeedNode, SeedConfig, RouterRecord


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def seed_config():
    """Create a test seed config with verification enabled."""
    return SeedConfig(
        host="127.0.0.1",
        port=18470,
        seed_id="test-seed-001",
        verify_signatures=True,
        verify_pow=True,
        probe_endpoints=False,  # Disable for unit tests
        pow_difficulty_base=4,  # Low difficulty for fast tests
        pow_difficulty_second=6,
        pow_difficulty_third_plus=8,
    )


@pytest.fixture
def seed_node(seed_config):
    """Create a test seed node."""
    return SeedNode(config=seed_config)


@pytest.fixture
def router_node():
    """Create a test router node."""
    return RouterNode(
        host="127.0.0.1",
        port=18471,
        regions=["us-west", "us-central"],
        features=["ipv6", "quic"],
    )


@pytest.fixture
def private_key():
    """Generate an Ed25519 private key for testing."""
    return Ed25519PrivateKey.generate()


# =============================================================================
# SIGNATURE VERIFICATION TESTS
# =============================================================================


class TestSignatureVerification:
    """Tests for Ed25519 signature verification."""
    
    def test_verify_valid_signature(self, seed_node, private_key):
        """Valid signature should pass verification."""
        # Create router_id from public key
        public_key = private_key.public_key()
        router_id = public_key.public_bytes_raw().hex()
        
        # Create and sign data
        data = {
            "router_id": router_id,
            "endpoints": ["127.0.0.1:8471"],
            "timestamp": time.time(),
        }
        message = json.dumps(data, sort_keys=True, separators=(',', ':')).encode()
        signature = private_key.sign(message).hex()
        
        # Verify
        assert seed_node._verify_signature(router_id, data, signature) is True
    
    def test_verify_invalid_signature(self, seed_node, private_key):
        """Invalid signature should fail verification."""
        public_key = private_key.public_key()
        router_id = public_key.public_bytes_raw().hex()
        
        data = {
            "router_id": router_id,
            "endpoints": ["127.0.0.1:8471"],
        }
        
        # Use wrong signature
        invalid_signature = "00" * 64  # Invalid signature
        
        assert seed_node._verify_signature(router_id, data, invalid_signature) is False
    
    def test_verify_tampered_data(self, seed_node, private_key):
        """Signature verification should fail if data is tampered."""
        public_key = private_key.public_key()
        router_id = public_key.public_bytes_raw().hex()
        
        # Sign original data
        original_data = {
            "router_id": router_id,
            "endpoints": ["127.0.0.1:8471"],
        }
        message = json.dumps(original_data, sort_keys=True, separators=(',', ':')).encode()
        signature = private_key.sign(message).hex()
        
        # Tamper with data
        tampered_data = {
            "router_id": router_id,
            "endpoints": ["192.168.1.1:8471"],  # Different endpoint
        }
        
        assert seed_node._verify_signature(router_id, tampered_data, signature) is False
    
    def test_verify_disabled(self, seed_node):
        """Verification should pass when disabled in config."""
        seed_node.config.verify_signatures = False
        
        # Invalid signature should pass when verification is disabled
        assert seed_node._verify_signature("invalid", {}, "invalid") is True


# =============================================================================
# PROOF-OF-WORK TESTS
# =============================================================================


class TestProofOfWork:
    """Tests for proof-of-work generation and verification."""
    
    def test_generate_pow(self, router_node):
        """Router should generate valid PoW."""
        router_node.POW_DIFFICULTY = 4  # Low for fast test
        
        pow = router_node._generate_pow()
        
        assert "challenge" in pow
        assert "nonce" in pow
        assert "difficulty" in pow
        assert pow["difficulty"] == 4
        
        # Verify the PoW is valid
        hash_input = f"{pow['challenge']}{pow['nonce']}{router_node.router_id}".encode()
        hash_result = hashlib.sha256(hash_input).digest()
        
        # Check leading zeros
        leading_zeros = 0
        for byte in hash_result:
            if byte == 0:
                leading_zeros += 8
            else:
                for i in range(7, -1, -1):
                    if byte & (1 << i):
                        break
                    leading_zeros += 1
                break
        
        assert leading_zeros >= 4
    
    def test_verify_valid_pow(self, seed_node, router_node):
        """Valid PoW should pass verification."""
        router_node.POW_DIFFICULTY = 4
        pow = router_node._generate_pow()
        
        assert seed_node._verify_pow(router_node.router_id, pow, 4) is True
    
    def test_verify_insufficient_pow(self, seed_node, router_node):
        """PoW with insufficient difficulty should fail."""
        router_node.POW_DIFFICULTY = 4
        pow = router_node._generate_pow()
        
        # Require higher difficulty than what was generated
        assert seed_node._verify_pow(router_node.router_id, pow, 20) is False
    
    def test_verify_missing_pow(self, seed_node, router_node):
        """Missing PoW should fail verification."""
        assert seed_node._verify_pow(router_node.router_id, None, 4) is False
        assert seed_node._verify_pow(router_node.router_id, {}, 4) is False
    
    def test_verify_pow_disabled(self, seed_node, router_node):
        """PoW verification should pass when disabled."""
        seed_node.config.verify_pow = False
        
        assert seed_node._verify_pow("any", None, 100) is True
    
    def test_pow_difficulty_scaling(self, seed_node):
        """PoW difficulty should scale with routers per IP."""
        ip = "192.168.1.1"
        
        # First router
        assert seed_node._get_pow_difficulty(ip) == 4
        
        # Register one router
        seed_node._ip_router_count[ip] = 1
        assert seed_node._get_pow_difficulty(ip) == 6
        
        # Register second router
        seed_node._ip_router_count[ip] = 2
        assert seed_node._get_pow_difficulty(ip) == 8
        
        # Third+ should stay at max
        seed_node._ip_router_count[ip] = 5
        assert seed_node._get_pow_difficulty(ip) == 8


# =============================================================================
# ENDPOINT PROBING TESTS
# =============================================================================


class TestEndpointProbing:
    """Tests for endpoint reachability probing."""
    
    @pytest.mark.asyncio
    async def test_probe_disabled(self, seed_node):
        """Probing should pass when disabled."""
        seed_node.config.probe_endpoints = False
        
        result = await seed_node._probe_endpoint("192.168.1.1:8471")
        assert result is True
    
    @pytest.mark.asyncio
    async def test_probe_unreachable(self, seed_node):
        """Unreachable endpoint should fail."""
        seed_node.config.probe_endpoints = True
        seed_node.config.probe_timeout_seconds = 1.0
        
        # This should fail (no server running)
        result = await seed_node._probe_endpoint("127.0.0.1:59999")
        assert result is False


# =============================================================================
# REGISTRATION FLOW TESTS
# =============================================================================


class TestRegistrationFlow:
    """Tests for the complete registration flow."""
    
    @pytest.mark.asyncio
    async def test_register_success(self, seed_node, router_node):
        """Successful registration should add router to registry."""
        # Disable endpoint probing for unit test
        seed_node.config.probe_endpoints = False
        router_node.POW_DIFFICULTY = 4
        
        # Build registration payload
        pow = router_node._generate_pow()
        registration = {
            "router_id": router_node.router_id,
            "endpoints": router_node.endpoints,
            "capacity": router_node.get_capacity(),
            "regions": router_node.regions,
            "features": router_node.features,
            "proof_of_work": pow,
            "timestamp": time.time(),
        }
        registration["signature"] = router_node._sign(registration)
        
        # Create mock request
        request = MagicMock()
        request.json = AsyncMock(return_value=registration)
        request.remote = "127.0.0.1"
        
        response = await seed_node.handle_register(request)
        
        assert response.status == 200
        data = json.loads(response.text)
        
        assert data["status"] == "accepted"
        assert data["action"] == "registered"
        assert router_node.router_id in seed_node.router_registry
    
    @pytest.mark.asyncio
    async def test_register_invalid_signature(self, seed_node, router_node):
        """Registration with invalid signature should be rejected."""
        seed_node.config.probe_endpoints = False
        
        registration = {
            "router_id": router_node.router_id,
            "endpoints": router_node.endpoints,
            "timestamp": time.time(),
            "signature": "00" * 64,  # Invalid signature
        }
        
        request = MagicMock()
        request.json = AsyncMock(return_value=registration)
        request.remote = "127.0.0.1"
        
        response = await seed_node.handle_register(request)
        
        assert response.status == 400
        data = json.loads(response.text)
        assert data["status"] == "rejected"
        assert data["reason"] == "invalid_signature"
    
    @pytest.mark.asyncio
    async def test_register_insufficient_pow(self, seed_node, router_node):
        """Registration with insufficient PoW should be rejected."""
        seed_node.config.probe_endpoints = False
        seed_node.config.verify_signatures = False  # Skip signature check
        seed_node.config.pow_difficulty_base = 20  # High difficulty
        
        # Generate weak PoW
        router_node.POW_DIFFICULTY = 4
        pow = router_node._generate_pow()
        
        registration = {
            "router_id": router_node.router_id,
            "endpoints": router_node.endpoints,
            "proof_of_work": pow,
            "timestamp": time.time(),
        }
        
        request = MagicMock()
        request.json = AsyncMock(return_value=registration)
        request.remote = "127.0.0.1"
        
        response = await seed_node.handle_register(request)
        
        assert response.status == 400
        data = json.loads(response.text)
        assert data["status"] == "rejected"
        assert data["reason"] == "insufficient_pow"
    
    @pytest.mark.asyncio
    async def test_register_missing_fields(self, seed_node):
        """Registration with missing fields should be rejected."""
        request = MagicMock()
        request.json = AsyncMock(return_value={})
        request.remote = "127.0.0.1"
        
        response = await seed_node.handle_register(request)
        
        assert response.status == 400
        data = json.loads(response.text)
        assert data["reason"] == "missing_router_id"
    
    @pytest.mark.asyncio
    async def test_register_update_existing(self, seed_node, router_node):
        """Updating existing registration should skip PoW check."""
        seed_node.config.probe_endpoints = False
        router_node.POW_DIFFICULTY = 4
        
        # First registration
        pow = router_node._generate_pow()
        registration = {
            "router_id": router_node.router_id,
            "endpoints": router_node.endpoints,
            "capacity": router_node.get_capacity(),
            "proof_of_work": pow,
            "timestamp": time.time(),
        }
        registration["signature"] = router_node._sign(registration)
        
        request = MagicMock()
        request.json = AsyncMock(return_value=registration)
        request.remote = "127.0.0.1"
        
        await seed_node.handle_register(request)
        
        # Update registration (no PoW needed)
        update = {
            "router_id": router_node.router_id,
            "endpoints": ["127.0.0.1:9999"],  # New endpoint
            "timestamp": time.time(),
        }
        update["signature"] = router_node._sign(update)
        
        request.json = AsyncMock(return_value=update)
        response = await seed_node.handle_register(request)
        
        data = json.loads(response.text)
        assert data["status"] == "accepted"
        assert data["action"] == "updated"


# =============================================================================
# HEARTBEAT PROTOCOL TESTS
# =============================================================================


class TestHeartbeatProtocol:
    """Tests for the heartbeat protocol."""
    
    @pytest.mark.asyncio
    async def test_heartbeat_updates_health(self, seed_node, router_node):
        """Heartbeat should update router health metrics."""
        seed_node.config.verify_signatures = False
        
        # Pre-register the router
        seed_node.router_registry[router_node.router_id] = RouterRecord(
            router_id=router_node.router_id,
            endpoints=router_node.endpoints,
            capacity={},
            health={"last_seen": 0, "uptime_pct": 100},
            regions=[],
            features=[],
            registered_at=time.time(),
            router_signature="",
        )
        
        heartbeat = {
            "router_id": router_node.router_id,
            "current_connections": 50,
            "load_pct": 35.5,
            "messages_relayed": 12500,
            "uptime_pct": 99.8,
            "timestamp": time.time(),
        }
        
        request = MagicMock()
        request.json = AsyncMock(return_value=heartbeat)
        
        response = await seed_node.handle_heartbeat(request)
        
        assert response.status == 200
        data = json.loads(response.text)
        
        assert data["status"] == "ok"
        assert data["health_status"] == "healthy"
        assert "next_heartbeat_in" in data
        
        # Verify metrics were updated
        record = seed_node.router_registry[router_node.router_id]
        assert record.capacity["current_load_pct"] == 35.5
        assert record.capacity["active_connections"] == 50
        assert record.health["uptime_pct"] == 99.8
    
    @pytest.mark.asyncio
    async def test_heartbeat_health_status_degraded(self, seed_node, router_node):
        """High load should result in degraded status."""
        seed_node.config.verify_signatures = False
        
        seed_node.router_registry[router_node.router_id] = RouterRecord(
            router_id=router_node.router_id,
            endpoints=router_node.endpoints,
            capacity={},
            health={"last_seen": 0},
            regions=[],
            features=[],
            registered_at=time.time(),
            router_signature="",
        )
        
        heartbeat = {
            "router_id": router_node.router_id,
            "load_pct": 95.0,  # High load
            "uptime_pct": 99.0,
            "timestamp": time.time(),
        }
        
        request = MagicMock()
        request.json = AsyncMock(return_value=heartbeat)
        
        response = await seed_node.handle_heartbeat(request)
        data = json.loads(response.text)
        
        assert data["health_status"] == "degraded"
    
    @pytest.mark.asyncio
    async def test_heartbeat_unregistered_router(self, seed_node, router_node):
        """Heartbeat from unregistered router should fail."""
        heartbeat = {
            "router_id": router_node.router_id,
            "load_pct": 50.0,
            "timestamp": time.time(),
        }
        
        request = MagicMock()
        request.json = AsyncMock(return_value=heartbeat)
        
        response = await seed_node.handle_heartbeat(request)
        
        assert response.status == 404
        data = json.loads(response.text)
        assert data["reason"] == "not_registered"
    
    @pytest.mark.asyncio
    async def test_heartbeat_with_signature(self, seed_node, router_node):
        """Heartbeat with valid signature should be accepted."""
        seed_node.config.verify_signatures = True
        
        seed_node.router_registry[router_node.router_id] = RouterRecord(
            router_id=router_node.router_id,
            endpoints=router_node.endpoints,
            capacity={},
            health={"last_seen": 0},
            regions=[],
            features=[],
            registered_at=time.time(),
            router_signature="",
        )
        
        heartbeat = {
            "router_id": router_node.router_id,
            "load_pct": 50.0,
            "timestamp": time.time(),
        }
        heartbeat["signature"] = router_node._sign(heartbeat)
        
        request = MagicMock()
        request.json = AsyncMock(return_value=heartbeat)
        
        response = await seed_node.handle_heartbeat(request)
        
        assert response.status == 200


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestRegistrationIntegration:
    """Integration tests for registration flow."""
    
    @pytest.mark.asyncio
    async def test_router_generates_valid_identity(self):
        """Router should generate valid Ed25519 identity on creation."""
        router = RouterNode()
        
        # Router ID should be 32 bytes (64 hex chars)
        assert len(router.router_id) == 64
        
        # Should be valid hex
        bytes.fromhex(router.router_id)
        
        # Should be able to sign and verify
        data = {"test": "data"}
        signature = router._sign(data)
        
        assert len(signature) == 128  # 64-byte signature as hex
    
    @pytest.mark.asyncio
    async def test_full_registration_cycle(self):
        """Test complete registration and heartbeat cycle."""
        # Create seed with lenient settings
        seed_config = SeedConfig(
            host="127.0.0.1",
            port=0,
            verify_signatures=True,
            verify_pow=True,
            probe_endpoints=False,
            pow_difficulty_base=4,
        )
        seed = SeedNode(config=seed_config)
        
        # Create router
        router = RouterNode(
            host="127.0.0.1",
            port=8471,
            regions=["test-region"],
        )
        router.POW_DIFFICULTY = 4
        
        # Step 1: Register
        pow = router._generate_pow()
        registration = {
            "router_id": router.router_id,
            "endpoints": router.endpoints,
            "capacity": router.get_capacity(),
            "regions": router.regions,
            "features": router.features,
            "proof_of_work": pow,
            "timestamp": time.time(),
        }
        registration["signature"] = router._sign(registration)
        
        request = MagicMock()
        request.json = AsyncMock(return_value=registration)
        request.remote = "127.0.0.1"
        
        response = await seed.handle_register(request)
        assert response.status == 200
        
        # Step 2: Send heartbeat
        heartbeat = {
            "router_id": router.router_id,
            "current_connections": 10,
            "load_pct": 10.0,
            "messages_relayed": 100,
            "uptime_pct": 99.9,
            "timestamp": time.time(),
        }
        heartbeat["signature"] = router._sign(heartbeat)
        
        request.json = AsyncMock(return_value=heartbeat)
        response = await seed.handle_heartbeat(request)
        
        assert response.status == 200
        data = json.loads(response.text)
        assert data["health_status"] == "healthy"
        
        # Step 3: Verify router appears in discovery
        request.json = AsyncMock(return_value={"requested_count": 5})
        response = await seed.handle_discover(request)
        
        data = json.loads(response.text)
        assert len(data["routers"]) == 1
        assert data["routers"][0]["router_id"] == router.router_id
