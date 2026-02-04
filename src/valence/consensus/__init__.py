"""Valence Consensus Module - VRF-based validator selection.

This module implements the consensus node selection mechanism per NODE-SELECTION.md:
- VRF (Verifiable Random Function) for unpredictable but verifiable selection
- Stake-weighted probability with anti-gaming measures
- Diversity constraints to prevent capture
- Slashing conditions for misbehavior
"""

from .vrf import VRF, VRFProof, VRFOutput
from .models import (
    Validator,
    ValidatorSet,
    ValidatorTier,
    ValidatorStatus,
    StakeRegistration,
    StakeStatus,
    IdentityAttestation,
    AttestationType,
    SlashingEvent,
    SlashingOffense,
    SlashingStatus,
    EpochTransition,
    DiversityConstraints,
    ElevationProposal,
    ElevationVote,
)
from .selection import (
    ValidatorSelector,
    compute_selection_weight,
    derive_epoch_seed,
    select_validators,
)
from .anti_gaming import (
    AntiGamingEngine,
    compute_tenure_penalty,
    compute_diversity_score,
    detect_collusion_patterns,
)

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
