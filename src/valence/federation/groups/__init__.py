"""MLS-style Group Encryption for Valence Federation.

Implements a simplified MLS (Messaging Layer Security) protocol for
group key management in federated knowledge sharing.

Key concepts:
- KeyPackage: Pre-key bundle for adding members without online interaction
- Welcome: Message allowing new members to join with group secrets
- Epoch: Group state version, incremented on membership changes
- Tree-based key derivation: Scalable group secret management

Security properties:
- Forward secrecy: Past messages protected when members leave
- Post-compromise security: Group recovers from key compromise
- Epoch isolation: Each epoch has independent encryption keys
"""

# Constants
from .constants import (
    AES_KEY_SIZE,
    DEFAULT_CIPHER_SUITE,
    ENCRYPTION_KEY_SIZE,
    EPOCH_SECRET_SIZE,
    KDF_INFO_ENCRYPTION_KEY,
    KDF_INFO_EPOCH_SECRET,
    KDF_INFO_MEMBER_SECRET,
    KDF_INFO_WELCOME_KEY,
    MAX_EPOCH_HISTORY,
    MAX_GROUP_SIZE,
    MLS_PROTOCOL_VERSION,
    NONCE_SIZE,
)

# Exceptions
from .exceptions import (
    EpochMismatchError,
    GroupFullError,
    GroupNotFoundError,
    InvalidKeyPackageError,
    MemberExistsError,
    MemberNotFoundError,
    MLSError,
    PermissionDeniedError,
)

# Federation group (Issue #73)
from .federation import (
    FederationGroup,
    create_federation_group,
    get_federation_group_info,
    get_federation_member_role,
    list_federation_group_members,
    verify_federation_membership,
)

# Data classes
from .key_package import KeyPackage
from .members import EpochSecrets, GroupMember
from .messages import CommitMessage, RemovalAuditEntry, WelcomeMessage

# Core operations
from .operations import (
    add_member,
    can_decrypt_at_epoch,
    create_group,
    decrypt_group_content,
    encrypt_group_content,
    get_removal_history,
    process_commit,
    process_welcome,
    remove_member,
    rotate_keys,
)
from .state import GroupState

# Storage
from .storage import (
    clear_federation_store,
    delete_federation_group,
    get_federation_group,
    get_group_by_federation_id,
    list_federation_groups,
    store_federation_group,
)

# Types (enums)
from .types import (
    GroupRole,
    GroupStatus,
    MemberRole,  # Backward compatibility alias
    MemberStatus,
    ProposalType,
)

__all__ = [
    # Constants
    "MLS_PROTOCOL_VERSION",
    "DEFAULT_CIPHER_SUITE",
    "MAX_GROUP_SIZE",
    "EPOCH_SECRET_SIZE",
    "ENCRYPTION_KEY_SIZE",
    "KDF_INFO_EPOCH_SECRET",
    "KDF_INFO_ENCRYPTION_KEY",
    "KDF_INFO_WELCOME_KEY",
    "KDF_INFO_MEMBER_SECRET",
    "AES_KEY_SIZE",
    "NONCE_SIZE",
    "MAX_EPOCH_HISTORY",
    # Exceptions
    "MLSError",
    "GroupNotFoundError",
    "MemberExistsError",
    "MemberNotFoundError",
    "InvalidKeyPackageError",
    "GroupFullError",
    "PermissionDeniedError",
    "EpochMismatchError",
    # Types
    "GroupRole",
    "MemberRole",
    "ProposalType",
    "MemberStatus",
    "GroupStatus",
    # Data classes
    "KeyPackage",
    "GroupMember",
    "EpochSecrets",
    "WelcomeMessage",
    "CommitMessage",
    "RemovalAuditEntry",
    "GroupState",
    # Core operations
    "create_group",
    "add_member",
    "process_welcome",
    "process_commit",
    "encrypt_group_content",
    "decrypt_group_content",
    "remove_member",
    "can_decrypt_at_epoch",
    "get_removal_history",
    "rotate_keys",
    # Federation group
    "FederationGroup",
    "create_federation_group",
    "get_federation_group_info",
    "list_federation_group_members",
    "verify_federation_membership",
    "get_federation_member_role",
    # Storage
    "store_federation_group",
    "get_federation_group",
    "get_group_by_federation_id",
    "delete_federation_group",
    "list_federation_groups",
    "clear_federation_store",
]
