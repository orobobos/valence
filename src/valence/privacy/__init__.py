"""Privacy module for Valence - share policies, encryption, and sharing service."""

from .types import ShareLevel, EnforcementType, PropagationRules, SharePolicy
from .encryption import EncryptionEnvelope
from .sharing import (
    ShareRequest,
    ShareResult,
    ConsentChainEntry,
    Share,
    SharingService,
)

__all__ = [
    # Types
    "ShareLevel",
    "EnforcementType", 
    "PropagationRules",
    "SharePolicy",
    # Encryption
    "EncryptionEnvelope",
    # Sharing
    "ShareRequest",
    "ShareResult",
    "ConsentChainEntry",
    "Share",
    "SharingService",
]
