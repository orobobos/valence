"""Valence Consensus Module - VRF-based validator selection.

This module implements the consensus node selection mechanism per NODE-SELECTION.md:
- VRF (Verifiable Random Function) for unpredictable but verifiable selection
- Stake-weighted probability with anti-gaming measures
- Diversity constraints to prevent capture
- Slashing conditions for misbehavior
"""

from .anti_gaming import (
    AntiGamingEngine,
    compute_diversity_score,
    compute_tenure_penalty,
    detect_collusion_patterns,
)
from .models import (
    AttestationType,
    DiversityConstraints,
    ElevationProposal,
    ElevationVote,
    EpochTransition,
    IdentityAttestation,
    SlashingEvent,
    SlashingOffense,
    SlashingStatus,
    StakeRegistration,
    StakeStatus,
    Validator,
    ValidatorSet,
    ValidatorStatus,
    ValidatorTier,
)
from .selection import (
    ValidatorSelector,
    compute_selection_weight,
    derive_epoch_seed,
    select_validators,
)
from .vrf import VRF, VRFOutput, VRFProof

__all__ = [
    # VRF
    "VRF",
    "VRFProof",
    "VRFOutput",
    # Models
    "Validator",
    "ValidatorSet",
    "ValidatorTier",
    "ValidatorStatus",
    "StakeRegistration",
    "StakeStatus",
    "IdentityAttestation",
    "AttestationType",
    "SlashingEvent",
    "SlashingOffense",
    "SlashingStatus",
    "EpochTransition",
    "DiversityConstraints",
    "ElevationProposal",
    "ElevationVote",
    # Selection
    "ValidatorSelector",
    "compute_selection_weight",
    "derive_epoch_seed",
    "select_validators",
    # Anti-Gaming
    "AntiGamingEngine",
    "compute_tenure_penalty",
    "compute_diversity_score",
    "detect_collusion_patterns",
]
