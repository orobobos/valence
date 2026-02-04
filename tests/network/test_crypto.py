"""
Tests for E2E encryption in Valence Relay Protocol.
"""

import pytest
import json
from cryptography.exceptions import InvalidSignature, InvalidTag

from valence.network.crypto import (
    KeyPair,
    generate_identity_keypair,
    generate_encryption_keypair,
    encrypt_message,
    decrypt_message,
)
from valence.network.messages import RelayMessage, DeliverPayload


class TestKeyGeneration:
    """Test key generation functions."""
    
    def test_generate_identity_keypair(self):
        """Ed25519 identity keypairs should be generated correctly."""
        private, public = generate_identity_keypair()
        
        # Keys should be valid (can sign and verify)
        message = b"test message"
        signature = private.sign(message)
        public.verify(signature, message)  # Should not raise
    
    def test_generate_encryption_keypair(self):
        """X25519 encryption keypairs should be generated correctly."""
        private, public = generate_encryption_keypair()
        
        # Keys should be valid (can perform exchange)
        other_private, other_public = generate_encryption_keypair()
        
        # ECDH should produce the same shared secret
        secret1 = private.exchange(other_public)
        secret2 = other_private.exchange(public)
        assert secret1 == secret2
    
    def test_keypairs_are_unique(self):
        """Each keypair generation should produce unique keys."""
        pairs = [generate_encryption_keypair() for _ in range(5)]
        public_keys = [p[1].public_bytes_raw() for p in pairs]
        
        # All should be unique
        assert len(set(public_keys)) == 5


class TestEncryptDecrypt:
    """Test encrypt/decrypt round trip."""
    
    @pytest.fixture
    def alice_keys(self):
        """Alice's identity and encryption keys."""
        return {
            "identity": generate_identity_keypair(),
            "encryption": generate_encryption_keypair(),
        }
    
    @pytest.fixture
    def bob_keys(self):
        """Bob's identity and encryption keys."""
        return {
            "identity": generate_identity_keypair(),
            "encryption": generate_encryption_keypair(),
        }
    
    def test_basic_encrypt_decrypt(self, alice_keys, bob_keys):
        """Basic encrypt/decrypt should work."""
        plaintext = b"Hello, Bob!"
        
        # Alice encrypts for Bob
        encrypted = encrypt_message(
            content=plaintext,
            recipient_public_key=bob_keys["encryption"][1],  # Bob's public
            sender_private_key=alice_keys["identity"][0],     # Alice's signing key
        )
        
        # Bob decrypts
        decrypted = decrypt_message(
            encrypted=encrypted,
            recipient_private_key=bob_keys["encryption"][0],  # Bob's private
            sender_public_key=alice_keys["identity"][1],      # Alice's public
        )
        
        assert decrypted == plaintext
    
    def test_encrypt_decrypt_empty_message(self, alice_keys, bob_keys):
        """Empty messages should work."""
        plaintext = b""
        
        encrypted = encrypt_message(
            content=plaintext,
            recipient_public_key=bob_keys["encryption"][1],
            sender_private_key=alice_keys["identity"][0],
        )
        
        decrypted = decrypt_message(
            encrypted=encrypted,
            recipient_private_key=bob_keys["encryption"][0],
            sender_public_key=alice_keys["identity"][1],
        )
        
        assert decrypted == plaintext
    
    def test_encrypt_decrypt_large_message(self, alice_keys, bob_keys):
        """Large messages should work."""
        plaintext = b"x" * 1_000_000  # 1MB
        
        encrypted = encrypt_message(
            content=plaintext,
            recipient_public_key=bob_keys["encryption"][1],
            sender_private_key=alice_keys["identity"][0],
        )
        
        decrypted = decrypt_message(
            encrypted=encrypted,
            recipient_private_key=bob_keys["encryption"][0],
            sender_public_key=alice_keys["identity"][1],
        )
        
        assert decrypted == plaintext
    
    def test_encrypt_decrypt_json_payload(self, alice_keys, bob_keys):
        """JSON payloads should round-trip correctly."""
        payload = DeliverPayload(
            sender_id="alice-node-001",
            message_type="belief",
            content={"belief": "The sky is blue", "confidence": 0.95},
            reply_path="encrypted-path-here"
        )
        plaintext = payload.to_bytes()
        
        encrypted = encrypt_message(
            content=plaintext,
            recipient_public_key=bob_keys["encryption"][1],
            sender_private_key=alice_keys["identity"][0],
        )
        
        decrypted = decrypt_message(
            encrypted=encrypted,
            recipient_private_key=bob_keys["encryption"][0],
            sender_public_key=alice_keys["identity"][1],
        )
        
        recovered = DeliverPayload.from_bytes(decrypted)
        assert recovered.sender_id == payload.sender_id
        assert recovered.message_type == payload.message_type
        assert recovered.content == payload.content


class TestSignatureVerification:
    """Test signature verification."""
    
    @pytest.fixture
    def alice_keys(self):
        return {
            "identity": generate_identity_keypair(),
            "encryption": generate_encryption_keypair(),
        }
    
    @pytest.fixture
    def bob_keys(self):
        return {
            "identity": generate_identity_keypair(),
            "encryption": generate_encryption_keypair(),
        }
    
    @pytest.fixture
    def eve_keys(self):
        """Eve is an attacker."""
        return {
            "identity": generate_identity_keypair(),
            "encryption": generate_encryption_keypair(),
        }
    
    def test_wrong_sender_key_fails(self, alice_keys, bob_keys, eve_keys):
        """Decryption with wrong sender public key should fail."""
        plaintext = b"Hello, Bob!"
        
        # Alice encrypts for Bob
        encrypted = encrypt_message(
            content=plaintext,
            recipient_public_key=bob_keys["encryption"][1],
            sender_private_key=alice_keys["identity"][0],
        )
        
        # Bob tries to decrypt but uses Eve's public key for verification
        with pytest.raises(InvalidSignature):
            decrypt_message(
                encrypted=encrypted,
                recipient_private_key=bob_keys["encryption"][0],
                sender_public_key=eve_keys["identity"][1],  # Wrong key!
            )
    
    def test_forged_signature_fails(self, alice_keys, bob_keys, eve_keys):
        """Messages with forged signatures should fail."""
        plaintext = b"Hello, Bob!"
        
        # Alice encrypts for Bob
        encrypted = encrypt_message(
            content=plaintext,
            recipient_public_key=bob_keys["encryption"][1],
            sender_private_key=alice_keys["identity"][0],
        )
        
        # Eve forges a signature
        forged_payload_bytes = json.dumps(encrypted["payload"], sort_keys=True).encode()
        forged_signature = eve_keys["identity"][0].sign(forged_payload_bytes)
        encrypted["signature"] = forged_signature.hex()
        encrypted["sender_public"] = eve_keys["identity"][1].public_bytes_raw().hex()
        
        # Bob tries to decrypt with Alice's key (original sender)
        with pytest.raises(InvalidSignature):
            decrypt_message(
                encrypted=encrypted,
                recipient_private_key=bob_keys["encryption"][0],
                sender_public_key=alice_keys["identity"][1],  # Alice's key
            )


class TestTamperingDetection:
    """Test that tampered messages are detected."""
    
    @pytest.fixture
    def alice_keys(self):
        return {
            "identity": generate_identity_keypair(),
            "encryption": generate_encryption_keypair(),
        }
    
    @pytest.fixture
    def bob_keys(self):
        return {
            "identity": generate_identity_keypair(),
            "encryption": generate_encryption_keypair(),
        }
    
    def test_tampered_ciphertext_fails(self, alice_keys, bob_keys):
        """Tampered ciphertext should fail decryption."""
        plaintext = b"Hello, Bob!"
        
        encrypted = encrypt_message(
            content=plaintext,
            recipient_public_key=bob_keys["encryption"][1],
            sender_private_key=alice_keys["identity"][0],
        )
        
        # Tamper with ciphertext (flip some bits)
        original = bytes.fromhex(encrypted["payload"]["ciphertext"])
        tampered = bytes([b ^ 0xFF for b in original[:16]]) + original[16:]
        encrypted["payload"]["ciphertext"] = tampered.hex()
        
        # Signature check will fail because payload changed
        with pytest.raises(InvalidSignature):
            decrypt_message(
                encrypted=encrypted,
                recipient_private_key=bob_keys["encryption"][0],
                sender_public_key=alice_keys["identity"][1],
            )
    
    def test_tampered_nonce_fails(self, alice_keys, bob_keys):
        """Tampered nonce should fail decryption."""
        plaintext = b"Hello, Bob!"
        
        encrypted = encrypt_message(
            content=plaintext,
            recipient_public_key=bob_keys["encryption"][1],
            sender_private_key=alice_keys["identity"][0],
        )
        
        # Tamper with nonce
        original = bytes.fromhex(encrypted["payload"]["nonce"])
        tampered = bytes([b ^ 0xFF for b in original])
        encrypted["payload"]["nonce"] = tampered.hex()
        
        # Signature check will fail because payload changed
        with pytest.raises(InvalidSignature):
            decrypt_message(
                encrypted=encrypted,
                recipient_private_key=bob_keys["encryption"][0],
                sender_public_key=alice_keys["identity"][1],
            )
    
    def test_tampered_ephemeral_key_fails(self, alice_keys, bob_keys):
        """Tampered ephemeral public key should fail."""
        plaintext = b"Hello, Bob!"
        
        encrypted = encrypt_message(
            content=plaintext,
            recipient_public_key=bob_keys["encryption"][1],
            sender_private_key=alice_keys["identity"][0],
        )
        
        # Replace ephemeral key with a different one
        fake_private, fake_public = generate_encryption_keypair()
        encrypted["payload"]["ephemeral_public"] = fake_public.public_bytes_raw().hex()
        
        # Signature check will fail because payload changed
        with pytest.raises(InvalidSignature):
            decrypt_message(
                encrypted=encrypted,
                recipient_private_key=bob_keys["encryption"][0],
                sender_public_key=alice_keys["identity"][1],
            )


class TestRelayMessage:
    """Test RelayMessage class."""
    
    def test_create_relay_message(self):
        """RelayMessage.create should work."""
        msg = RelayMessage.create(
            next_hop="node-123",
            payload="deadbeef",
            ttl=5
        )
        
        assert msg.next_hop == "node-123"
        assert msg.payload == "deadbeef"
        assert msg.ttl == 5
        assert msg.message_id  # Should be auto-generated
        assert msg.timestamp > 0
    
    def test_relay_message_serialization(self):
        """RelayMessage should serialize/deserialize correctly."""
        msg = RelayMessage.create(
            next_hop="node-456",
            payload="cafebabe",
            ttl=10
        )
        
        # to_dict / from_dict
        d = msg.to_dict()
        assert d["type"] == "relay"
        recovered = RelayMessage.from_dict(d)
        assert recovered.next_hop == msg.next_hop
        assert recovered.payload == msg.payload
        
        # to_json / from_json
        j = msg.to_json()
        recovered2 = RelayMessage.from_json(j)
        assert recovered2.message_id == msg.message_id


class TestDeliverPayload:
    """Test DeliverPayload class."""
    
    def test_deliver_payload_creation(self):
        """DeliverPayload should be created correctly."""
        payload = DeliverPayload(
            sender_id="alice",
            message_type="query",
            content={"query": "What is 2+2?"},
        )
        
        assert payload.sender_id == "alice"
        assert payload.message_type == "query"
        assert payload.timestamp > 0
    
    def test_deliver_payload_serialization(self):
        """DeliverPayload should serialize/deserialize correctly."""
        payload = DeliverPayload(
            sender_id="bob",
            message_type="response",
            content={"answer": 4},
            reply_path="encrypted-path"
        )
        
        # to_bytes / from_bytes
        b = payload.to_bytes()
        recovered = DeliverPayload.from_bytes(b)
        
        assert recovered.sender_id == payload.sender_id
        assert recovered.content == payload.content
        assert recovered.reply_path == payload.reply_path


class TestRouterCantRead:
    """Test that routers cannot read message content."""
    
    def test_router_only_sees_encrypted_blob(self):
        """Router should only see routing info, not content."""
        alice_identity = generate_identity_keypair()
        bob_encryption = generate_encryption_keypair()
        
        # The actual sensitive content
        secret_content = DeliverPayload(
            sender_id="alice",
            message_type="belief",
            content={"secret": "The password is 12345"}
        )
        
        # Encrypt for Bob
        encrypted = encrypt_message(
            content=secret_content.to_bytes(),
            recipient_public_key=bob_encryption[1],
            sender_private_key=alice_identity[0],
        )
        
        # Create relay message (what router sees)
        relay_msg = RelayMessage.create(
            next_hop="bob-node",
            payload=json.dumps(encrypted),
            ttl=10
        )
        
        # Router can see routing info
        assert relay_msg.next_hop == "bob-node"
        assert relay_msg.ttl == 10
        
        # But router CANNOT see the secret content
        # The payload is just an encrypted blob
        router_view = relay_msg.to_dict()
        assert "The password is 12345" not in json.dumps(router_view)
        assert "secret" not in router_view["payload"]  # payload is encrypted JSON
