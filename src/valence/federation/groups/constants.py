"""Constants for MLS-style group encryption."""

# Protocol version
MLS_PROTOCOL_VERSION = "1.0"
DEFAULT_CIPHER_SUITE = "X25519-AES256GCM-SHA256"
MAX_GROUP_SIZE = 1000
EPOCH_SECRET_SIZE = 32
ENCRYPTION_KEY_SIZE = 32

# Key derivation contexts
KDF_INFO_EPOCH_SECRET = b"valence-mls-epoch-secret"
KDF_INFO_ENCRYPTION_KEY = b"valence-mls-encryption-key"
KDF_INFO_WELCOME_KEY = b"valence-mls-welcome-key"
KDF_INFO_MEMBER_SECRET = b"valence-mls-member-secret"

# Key sizes
AES_KEY_SIZE = 32  # 256 bits
NONCE_SIZE = 12  # 96 bits for GCM

# Epoch history limits
MAX_EPOCH_HISTORY = 100  # Maximum number of epochs to retain for recovery
