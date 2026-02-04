"""
E2E Encryption for Valence Relay Protocol.

Provides:
- X25519 key exchange for encryption
- Ed25519 signing for authentication
- AES-256-GCM for content encryption
- HKDF for key derivation

Routers only see encrypted blobs - they cannot read message content.
"""

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from dataclasses import dataclass
from typing import Tuple
import os
import json


@dataclass
class KeyPair:
    """Generic keypair container for raw bytes."""
    private_key: bytes
    public_key: bytes


def generate_identity_keypair() -> Tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Generate Ed25519 keypair for signing."""
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def generate_encryption_keypair() -> Tuple[X25519PrivateKey, X25519PublicKey]:
    """Generate X25519 keypair for encryption."""
    private_key = X25519PrivateKey.generate()
    return private_key, private_key.public_key()


def encrypt_message(
    content: bytes,
    recipient_public_key: X25519PublicKey,
    sender_private_key: Ed25519PrivateKey
) -> dict:
    """
    Encrypt a message for a recipient.
    
    Process:
    1. Generate ephemeral X25519 keypair
    2. Derive shared secret via ECDH
    3. Derive DEK from shared secret using HKDF
    4. Encrypt content with DEK (AES-256-GCM)
    5. Sign the encrypted payload with sender's Ed25519 key
    
    Args:
        content: Raw bytes to encrypt
        recipient_public_key: Recipient's X25519 public key
        sender_private_key: Sender's Ed25519 private key for signing
        
    Returns:
        dict with 'payload' (encrypted data), 'signature', and 'sender_public'
    """
    # Generate ephemeral keypair for this message
    ephemeral_private = X25519PrivateKey.generate()
    ephemeral_public = ephemeral_private.public_key()
    
    # Derive shared secret via ECDH
    shared_secret = ephemeral_private.exchange(recipient_public_key)
    
    # Derive DEK using HKDF
    dek = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"valence-relay-v1"
    ).derive(shared_secret)
    
    # Encrypt content with AES-256-GCM
    nonce = os.urandom(12)
    aesgcm = AESGCM(dek)
    ciphertext = aesgcm.encrypt(nonce, content, None)
    
    # Build payload
    payload = {
        "ephemeral_public": ephemeral_public.public_bytes_raw().hex(),
        "nonce": nonce.hex(),
        "ciphertext": ciphertext.hex(),
    }
    
    # Sign the payload
    payload_bytes = json.dumps(payload, sort_keys=True).encode()
    signature = sender_private_key.sign(payload_bytes)
    
    return {
        "payload": payload,
        "signature": signature.hex(),
        "sender_public": sender_private_key.public_key().public_bytes_raw().hex()
    }


def decrypt_message(
    encrypted: dict,
    recipient_private_key: X25519PrivateKey,
    sender_public_key: Ed25519PublicKey
) -> bytes:
    """
    Decrypt a message.
    
    Process:
    1. Verify signature using sender's Ed25519 public key
    2. Extract ephemeral public key from payload
    3. Derive shared secret via ECDH
    4. Derive DEK from shared secret using HKDF
    5. Decrypt content with DEK
    
    Args:
        encrypted: The encrypted message dict from encrypt_message()
        recipient_private_key: Recipient's X25519 private key
        sender_public_key: Sender's Ed25519 public key for verification
        
    Returns:
        Decrypted plaintext bytes
        
    Raises:
        cryptography.exceptions.InvalidSignature: If signature verification fails
        cryptography.exceptions.InvalidTag: If decryption fails (tampered data)
    """
    # Verify signature
    payload_bytes = json.dumps(encrypted["payload"], sort_keys=True).encode()
    signature = bytes.fromhex(encrypted["signature"])
    sender_public_key.verify(signature, payload_bytes)  # Raises InvalidSignature on failure
    
    # Extract ephemeral public key
    ephemeral_public = X25519PublicKey.from_public_bytes(
        bytes.fromhex(encrypted["payload"]["ephemeral_public"])
    )
    
    # Derive shared secret via ECDH
    shared_secret = recipient_private_key.exchange(ephemeral_public)
    
    # Derive DEK using HKDF
    dek = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"valence-relay-v1"
    ).derive(shared_secret)
    
    # Decrypt
    nonce = bytes.fromhex(encrypted["payload"]["nonce"])
    ciphertext = bytes.fromhex(encrypted["payload"]["ciphertext"])
    aesgcm = AESGCM(dek)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    
    return plaintext
