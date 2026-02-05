"""
E2E Encryption for Valence Relay Protocol.

Provides:
- X25519 key exchange for encryption
- Ed25519 signing for authentication
- AES-256-GCM for content encryption
- HKDF for key derivation

Circuit/Onion Encryption (Issue #115):
- Layered encryption for multi-hop routing
- Each router peels one layer without seeing full path
- Forward secrecy via ephemeral keys per circuit

Routers only see encrypted blobs - they cannot read message content.
"""

import json
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
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


@dataclass
class KeyPair:
    """Generic keypair container for raw bytes."""

    private_key: bytes
    public_key: bytes


def generate_identity_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Generate Ed25519 keypair for signing."""
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def generate_encryption_keypair() -> tuple[X25519PrivateKey, X25519PublicKey]:
    """Generate X25519 keypair for encryption."""
    private_key = X25519PrivateKey.generate()
    return private_key, private_key.public_key()


def encrypt_message(
    content: bytes,
    recipient_public_key: X25519PublicKey,
    sender_private_key: Ed25519PrivateKey,
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
    dek = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"valence-relay-v1").derive(shared_secret)

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
        "sender_public": sender_private_key.public_key().public_bytes_raw().hex(),
    }


def decrypt_message(
    encrypted: dict,
    recipient_private_key: X25519PrivateKey,
    sender_public_key: Ed25519PublicKey,
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
    ephemeral_public = X25519PublicKey.from_public_bytes(bytes.fromhex(encrypted["payload"]["ephemeral_public"]))

    # Derive shared secret via ECDH
    shared_secret = recipient_private_key.exchange(ephemeral_public)

    # Derive DEK using HKDF
    dek = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"valence-relay-v1").derive(shared_secret)

    # Decrypt
    nonce = bytes.fromhex(encrypted["payload"]["nonce"])
    ciphertext = bytes.fromhex(encrypted["payload"]["ciphertext"])
    aesgcm = AESGCM(dek)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)

    return plaintext


# =============================================================================
# CIRCUIT/ONION ENCRYPTION (Issue #115)
# =============================================================================


@dataclass
class OnionLayer:
    """
    A single layer of onion encryption.

    Each layer contains:
    - The encrypted payload for this hop
    - Routing info (next hop, or final delivery)
    """

    encrypted_payload: bytes
    next_hop: str | None  # Router ID or None for exit


@dataclass
class CircuitKeyMaterial:
    """
    Key material for a circuit hop.

    Generated during circuit creation via DH key exchange.
    """

    ephemeral_private: X25519PrivateKey
    ephemeral_public: X25519PublicKey
    shared_key: bytes  # 32-byte AES key


def derive_circuit_key(
    private_key: X25519PrivateKey,
    peer_public_key: X25519PublicKey,
    circuit_id: str,
) -> bytes:
    """
    Derive a circuit hop key via ECDH + HKDF.

    Args:
        private_key: Our ephemeral X25519 private key
        peer_public_key: Peer's ephemeral X25519 public key
        circuit_id: Circuit identifier (used as HKDF info)

    Returns:
        32-byte AES key for this circuit hop
    """
    # Perform ECDH
    shared_secret = private_key.exchange(peer_public_key)

    # Derive key using HKDF
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=f"valence-circuit-v1:{circuit_id}".encode(),
    ).derive(shared_secret)

    return key


def generate_circuit_keypair() -> tuple[X25519PrivateKey, X25519PublicKey]:
    """
    Generate an ephemeral X25519 keypair for circuit establishment.

    Returns:
        Tuple of (private_key, public_key)
    """
    private_key = X25519PrivateKey.generate()
    return private_key, private_key.public_key()


def encrypt_onion_layer(
    content: bytes,
    key: bytes,
    next_hop: str | None = None,
) -> bytes:
    """
    Encrypt one layer of an onion.

    The layer format is:
    - 12 bytes: nonce
    - 1 byte: has_next_hop flag (0 or 1)
    - 64 bytes: next_hop (padded, if has_next_hop)
    - remaining: AES-GCM ciphertext

    Args:
        content: Plaintext bytes (inner onion or final payload)
        key: 32-byte AES key for this layer
        next_hop: Router ID of next hop (None for exit/final delivery)

    Returns:
        Encrypted layer bytes
    """
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)

    # Build routing header
    if next_hop:
        has_next = b"\x01"
        # Pad next_hop to fixed 64 bytes for uniform layer size
        next_hop_bytes = next_hop.encode()[:64].ljust(64, b"\x00")
    else:
        has_next = b"\x00"
        next_hop_bytes = b"\x00" * 64

    # Prepend routing header to content before encryption
    plaintext = has_next + next_hop_bytes + content

    # Encrypt
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)

    return nonce + ciphertext


def decrypt_onion_layer(
    layer: bytes,
    key: bytes,
) -> tuple[bytes, str | None]:
    """
    Decrypt (peel) one layer of an onion.

    Args:
        layer: Encrypted layer bytes
        key: 32-byte AES key for this layer

    Returns:
        Tuple of (inner_content, next_hop_or_none)

    Raises:
        cryptography.exceptions.InvalidTag: If decryption fails
    """
    # Extract nonce (first 12 bytes)
    nonce = layer[:12]
    ciphertext = layer[12:]

    # Decrypt
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)

    # Parse routing header
    has_next = plaintext[0] == 1
    next_hop_bytes = plaintext[1:65]
    content = plaintext[65:]

    if has_next:
        # Strip null padding from next_hop
        next_hop = next_hop_bytes.rstrip(b"\x00").decode()
    else:
        next_hop = None

    return content, next_hop


def create_onion(
    content: bytes,
    hop_keys: list[bytes],
    hop_ids: list[str],
) -> bytes:
    """
    Create a complete onion by layering encryption for each hop.

    Encrypts in reverse order so that each router peels from the outside in.

    Args:
        content: Final payload to deliver
        hop_keys: List of 32-byte AES keys for each hop (in path order)
        hop_ids: List of router IDs for each hop (in path order)

    Returns:
        Onion-encrypted payload

    Example:
        If path is [R1, R2, R3] and recipient is R_final:
        - First encrypt for R3 with next_hop=None (exit to R_final)
        - Then encrypt for R2 with next_hop=R3
        - Finally encrypt for R1 with next_hop=R2

        R1 peels to find next_hop=R2
        R2 peels to find next_hop=R3
        R3 peels to find next_hop=None, delivers to recipient
    """
    if len(hop_keys) != len(hop_ids):
        raise ValueError("hop_keys and hop_ids must have same length")

    if not hop_keys:
        return content

    # Start with innermost layer (last hop, no next)
    onion = encrypt_onion_layer(content, hop_keys[-1], next_hop=None)

    # Wrap with outer layers in reverse order
    for i in range(len(hop_keys) - 2, -1, -1):
        next_hop = hop_ids[i + 1]
        onion = encrypt_onion_layer(onion, hop_keys[i], next_hop=next_hop)

    return onion


def peel_onion(
    onion: bytes,
    key: bytes,
) -> tuple[bytes, str | None]:
    """
    Peel one layer from an onion and get routing info.

    This is what each router does when it receives a circuit relay message.

    Args:
        onion: The onion-encrypted payload
        key: This hop's shared key

    Returns:
        Tuple of (inner_onion_or_payload, next_hop_or_none)

        If next_hop is None, this is the exit node and the content
        should be delivered to the final recipient.
    """
    return decrypt_onion_layer(onion, key)


def encrypt_circuit_payload(
    content: bytes,
    circuit_keys: list[bytes],
) -> bytes:
    """
    Encrypt a payload for transmission through a circuit.

    Unlike create_onion, this doesn't include routing info - the circuit
    is already established and routers know where to forward.

    Each layer is just AES-GCM encryption.

    Args:
        content: Payload to encrypt
        circuit_keys: List of hop keys (in path order)

    Returns:
        Layered-encrypted payload
    """
    # Encrypt in reverse order (innermost first)
    payload = content
    for key in reversed(circuit_keys):
        nonce = os.urandom(12)
        aesgcm = AESGCM(key)
        payload = nonce + aesgcm.encrypt(nonce, payload, None)

    return payload


def decrypt_circuit_layer(
    payload: bytes,
    key: bytes,
) -> bytes:
    """
    Decrypt one layer of a circuit payload.

    Args:
        payload: Layered-encrypted payload
        key: This hop's key

    Returns:
        Payload with this layer removed
    """
    nonce = payload[:12]
    ciphertext = payload[12:]

    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def encrypt_backward_payload(
    content: bytes,
    key: bytes,
) -> bytes:
    """
    Encrypt a backward-direction payload (response going back through circuit).

    In backward direction, each router adds a layer as the message travels
    back toward the originator.

    Args:
        content: Payload to encrypt
        key: This hop's key

    Returns:
        Encrypted payload with one layer added
    """
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    return nonce + aesgcm.encrypt(nonce, content, None)


def decrypt_backward_layers(
    payload: bytes,
    circuit_keys: list[bytes],
) -> bytes:
    """
    Decrypt all layers of a backward-direction payload.

    The originator decrypts layers in order (first hop's layer first).

    Args:
        payload: Layered payload from backward direction
        circuit_keys: List of hop keys (in path order)

    Returns:
        Decrypted content
    """
    result = payload
    for key in circuit_keys:
        result = decrypt_circuit_layer(result, key)

    return result
