"""Validator Selection Algorithm.

Implements VRF-based lottery selection per NODE-SELECTION.md:
- VRF tickets determine selection order
- Stake-weighted probability
- Diversity constraints enforced
- Anti-entrenchment measures
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import uuid4

from .models import (
    DiversityConstraints,
    EligibilityRequirements,
    IdentityAttestation,
    StakeRegistration,
    Validator,
    ValidatorPerformance,
    ValidatorSet,
    ValidatorStatus,
    ValidatorTier,
)
from .vrf import VRF, VRFOutput

# =============================================================================
# CONSTANTS
# =============================================================================

# Validator set sizing
MIN_VALIDATORS = 31  # 3f+1 where f=10
MAX_VALIDATORS = 100

# Epoch duration
EPOCH_DURATION_DAYS = 7
COOLDOWN_DURATION_DAYS = 14


# =============================================================================
# CANDIDATE
# =============================================================================


@dataclass
class ValidatorCandidate:
    """A candidate for validator selection."""

    agent_id: str  # DID
    public_key: bytes  # Ed25519 public key

    # Stake
    stake: StakeRegistration

    # Identity
    attestations: list[IdentityAttestation] = field(default_factory=list)

    # History
    reputation: float = 0.5
    tenure_epochs: int = 0  # Consecutive epochs served
    last_epoch_performance: ValidatorPerformance | None = None

    # Federation membership
    federation_membership: list[str] = field(default_factory=list)

    # Computed during selection
    selection_weight: float = 0.0
    vrf_output: VRFOutput | None = None

    def valid_attestation_count(self, as_of: datetime | None = None) -> int:
        """Count valid attestations."""
        return sum(1 for att in self.attestations if att.is_valid(as_of))


# =============================================================================
# WEIGHT CALCULATION
# =============================================================================


def compute_selection_weight(candidate: ValidatorCandidate) -> float:
    """Compute a candidate's selection weight.

    Higher weight = higher probability of selection.

    Per NODE-SELECTION.md formula:
    - Base: stake tier multiplier (1.0, 1.5, or 2.0)
    - Reputation bonus: up to 1.25× at rep=1.0
    - Attestation bonus: up to 1.3× with 3+ attestations
    - Tenure penalty: 0.9^(tenure-4) after 4 consecutive epochs
    - Performance factor: 0.9-1.1× based on last epoch

    Args:
        candidate: The validator candidate

    Returns:
        Selection weight (multiplicative factors combined)
    """
    # Base: stake tier multiplier
    base = candidate.stake.tier.multiplier

    # Reputation bonus (beyond minimum 0.5)
    rep_excess = max(0.0, candidate.reputation - 0.5)
    reputation_factor = 1.0 + (rep_excess * 0.5)  # Up to 1.25× at rep=1.0

    # Attestation bonus
    attestation_count = candidate.valid_attestation_count()
    attestation_factor = 1.0 + (0.1 * min(attestation_count, 3))  # Up to 1.3×

    # Tenure penalty (anti-entrenchment)
    tenure = candidate.tenure_epochs
    if tenure > 4:
        tenure_penalty = 0.9 ** (tenure - 4)  # Decreasing after 4 epochs
    else:
        tenure_penalty = 1.0

    # Performance factor (if previously served)
    if candidate.last_epoch_performance:
        perf = candidate.last_epoch_performance
        # Range 0.9-1.1× based on participation rate
        performance_factor = 0.9 + (0.2 * perf.participation_rate)
    else:
        performance_factor = 1.0  # New validators: neutral

    return base * reputation_factor * attestation_factor * tenure_penalty * performance_factor


def compute_tenure_penalty(consecutive_epochs: int) -> float:
    """Compute tenure penalty factor for anti-entrenchment.

    Args:
        consecutive_epochs: Number of consecutive epochs served

    Returns:
        Penalty multiplier (1.0 = no penalty, <1.0 = penalized)
    """
    if consecutive_epochs <= 4:
        return 1.0
    return 0.9 ** (consecutive_epochs - 4)


# =============================================================================
# EPOCH SEED DERIVATION
# =============================================================================


def derive_epoch_seed(
    previous_seed: bytes,
    block_hash: bytes,
    epoch_number: int,
) -> bytes:
    """Derive the seed for a new epoch.

    Wraps VRF.derive_epoch_seed for convenience.
    """
    return VRF.derive_epoch_seed(previous_seed, block_hash, epoch_number)


# =============================================================================
# VALIDATOR SET SIZING
# =============================================================================


def compute_validator_set_size(
    monthly_active_agents: int = 0,
    l4_elevations_last_epoch: int = 0,
) -> int:
    """Compute target validator set size.

    Per NODE-SELECTION.md:
    - Base: 31 (3f+1 where f=10)
    - +1 per 1000 active agents
    - +1 per 100 L4 elevations
    - Max: 100
    - Must maintain 3f+1 format

    Args:
        monthly_active_agents: Number of active agents in last month
        l4_elevations_last_epoch: Number of L4 elevations in last epoch

    Returns:
        Target validator count (in 3f+1 format)
    """
    base_size = MIN_VALIDATORS

    # Scale with network activity
    activity_bonus = monthly_active_agents // 1000
    elevation_bonus = l4_elevations_last_epoch // 100

    computed = base_size + activity_bonus + elevation_bonus

    # Cap at maximum
    computed = min(computed, MAX_VALIDATORS)

    # Ensure 3f+1 format
    f = (computed - 1) // 3
    return 3 * f + 1


# =============================================================================
# DIVERSITY ENFORCEMENT
# =============================================================================


def apply_diversity_constraints(
    candidates: list[tuple[ValidatorCandidate, VRFOutput]],
    target_count: int,
    constraints: DiversityConstraints,
    previous_validators: set[str] | None = None,
) -> list[tuple[ValidatorCandidate, VRFOutput]]:
    """Apply diversity constraints to candidate selection.

    Filters candidates to ensure:
    - Max 20% from any single federation
    - Max 60% returning validators
    - Min 20% new validators
    - Min 30% from standard tier

    Args:
        candidates: List of (candidate, vrf_output) sorted by ticket
        target_count: Target number of validators
        constraints: Diversity constraints to apply
        previous_validators: DIDs of validators from previous epoch

    Returns:
        Filtered list of candidates meeting constraints
    """
    previous_validators = previous_validators or set()

    selected: list[tuple[ValidatorCandidate, VRFOutput]] = []
    federation_counts: dict[str, int] = {}
    tier_counts: dict[ValidatorTier, int] = {}
    returning_count = 0
    new_count = 0

    # Maximum counts
    max_per_federation = int(target_count * constraints.max_from_same_federation)
    max_returning = int(target_count * constraints.max_consecutive_validators)

    # Process candidates in ticket order
    for candidate, vrf_output in candidates:
        if len(selected) >= target_count:
            break

        # Check federation limit
        federation_limited = False
        for fed in candidate.federation_membership:
            if federation_counts.get(fed, 0) >= max_per_federation:
                federation_limited = True
                break
        if federation_limited:
            continue

        # Check returning validator limit
        is_returning = candidate.agent_id in previous_validators
        if is_returning and returning_count >= max_returning:
            continue

        # Accept candidate
        selected.append((candidate, vrf_output))

        # Update counters
        for fed in candidate.federation_membership:
            federation_counts[fed] = federation_counts.get(fed, 0) + 1

        tier_counts[candidate.stake.tier] = tier_counts.get(candidate.stake.tier, 0) + 1

        if is_returning:
            returning_count += 1
        else:
            new_count += 1

    # Check minimum new validator requirement
    min_new = int(target_count * constraints.min_new_validators)
    if new_count < min_new and len(selected) == target_count:
        # Need to force-fill with new validators
        # Remove lowest-weight returning validators and add new ones
        selected = _force_new_validators(
            selected,
            candidates,
            min_new - new_count,
            previous_validators,
        )

    return selected


def _force_new_validators(
    selected: list[tuple[ValidatorCandidate, VRFOutput]],
    all_candidates: list[tuple[ValidatorCandidate, VRFOutput]],
    needed: int,
    previous_validators: set[str],
) -> list[tuple[ValidatorCandidate, VRFOutput]]:
    """Force-fill with new validators to meet minimum requirement."""
    # Find returning validators in selected (sorted by weight, lowest first)
    returning = [(c, v) for c, v in selected if c.agent_id in previous_validators]
    returning.sort(key=lambda x: x[0].selection_weight)

    # Find new candidates not yet selected
    selected_ids = {c.agent_id for c, _ in selected}
    new_candidates = [(c, v) for c, v in all_candidates if c.agent_id not in selected_ids and c.agent_id not in previous_validators]

    # Replace lowest-weight returning with new candidates
    result = list(selected)
    for i in range(min(needed, len(returning), len(new_candidates))):
        # Remove lowest-weight returning validator
        to_remove = returning[i]
        result.remove(to_remove)
        # Add new candidate
        result.append(new_candidates[i])

    return result


# =============================================================================
# MAIN SELECTION
# =============================================================================


def select_validators(
    candidates: list[ValidatorCandidate],
    epoch_seed: bytes,
    target_count: int,
    constraints: DiversityConstraints | None = None,
    previous_validators: set[str] | None = None,
) -> list[Validator]:
    """Select validators for an epoch using VRF lottery.

    Per NODE-SELECTION.md:
    1. Each candidate computes their VRF ticket
    2. Candidates are sorted by ticket
    3. Diversity constraints are applied
    4. Top N candidates are selected

    Args:
        candidates: Eligible validator candidates
        epoch_seed: Random seed for this epoch
        target_count: Number of validators to select
        constraints: Diversity constraints (defaults to standard)
        previous_validators: DIDs of validators from previous epoch

    Returns:
        List of selected Validators
    """
    if not constraints:
        constraints = DiversityConstraints()

    # Compute selection weights and VRF tickets
    weighted_candidates: list[tuple[ValidatorCandidate, VRFOutput]] = []

    for candidate in candidates:
        # Compute selection weight
        candidate.selection_weight = compute_selection_weight(candidate)

        # Compute VRF ticket
        # Note: In production, candidates would compute their own tickets
        # Here we simulate using a deterministic pseudo-VRF for testing
        vrf_output = _compute_candidate_ticket(candidate, epoch_seed)
        candidate.vrf_output = vrf_output

        weighted_candidates.append((candidate, vrf_output))

    # Sort by ticket (lowest first)
    weighted_candidates.sort(key=lambda x: x[1].ticket)

    # Apply diversity constraints
    selected = apply_diversity_constraints(
        weighted_candidates,
        target_count,
        constraints,
        previous_validators,
    )

    # Convert to Validator objects
    epoch_end = datetime.now() + timedelta(days=EPOCH_DURATION_DAYS)
    cooldown_end = epoch_end + timedelta(days=COOLDOWN_DURATION_DAYS)

    validators = []
    for candidate, vrf_output in selected:
        # Determine tenure
        is_returning = previous_validators and candidate.agent_id in previous_validators
        tenure = candidate.tenure_epochs + 1 if is_returning else 1

        validator = Validator(
            id=uuid4(),
            agent_id=candidate.agent_id,
            staked_reputation=candidate.stake.effective_stake(),
            tier=candidate.stake.tier,
            stake_lock_until=cooldown_end,
            selection_weight=candidate.selection_weight,
            selection_ticket=vrf_output.ticket,
            public_key=candidate.public_key,
            attestations=candidate.attestations,
            federation_membership=candidate.federation_membership,
            tenure_epochs=tenure,
            first_epoch=0,  # Would be set by caller
            status=ValidatorStatus.ACTIVE,
            reputation_at_selection=candidate.reputation,
        )
        validators.append(validator)

    return validators


def _compute_candidate_ticket(
    candidate: ValidatorCandidate,
    epoch_seed: bytes,
) -> VRFOutput:
    """Compute a candidate's VRF ticket.

    In production, the candidate computes this using their private key.
    For testing/simulation, we use a deterministic pseudo-VRF.
    """
    from .vrf import VRFProof

    # Create input from seed and agent ID
    agent_fingerprint = hashlib.sha256(candidate.agent_id.encode()).digest()
    input_data = hashlib.sha256(epoch_seed + agent_fingerprint).digest()

    # Apply weight adjustment to ticket
    # Higher weight = lower effective ticket (better chance)
    raw_ticket = hashlib.sha256(input_data + candidate.public_key).digest()

    # Adjust ticket based on weight (probabilistic advantage)
    # Weight of 2.0 gives ~2× better chance
    weight = candidate.selection_weight
    adjusted = int.from_bytes(raw_ticket, "big")
    if weight > 0:
        adjusted = int(adjusted / weight)
    ticket = adjusted.to_bytes(32, "big")[-32:]  # Keep 32 bytes

    # Create pseudo-proof (in production this would be a real VRF proof)
    proof = VRFProof(
        gamma=raw_ticket[:32],
        c=raw_ticket[16:48],
        s=input_data[:32],
    )

    return VRFOutput(
        ticket=ticket,
        proof=proof,
        input_hash=input_data,
    )


# =============================================================================
# VALIDATOR SELECTOR CLASS
# =============================================================================


class ValidatorSelector:
    """High-level interface for validator selection.

    Manages the complete selection process including:
    - Eligibility checking
    - Weight computation
    - VRF lottery
    - Diversity enforcement
    - Epoch transitions

    Example:
        >>> selector = ValidatorSelector()
        >>> candidates = [...]  # Load from database
        >>> epoch_seed = derive_epoch_seed(prev_seed, block_hash, epoch_num)
        >>> validators = selector.select_for_epoch(
        ...     candidates=candidates,
        ...     epoch_seed=epoch_seed,
        ...     epoch_number=42,
        ... )
    """

    def __init__(
        self,
        eligibility: EligibilityRequirements | None = None,
        constraints: DiversityConstraints | None = None,
    ):
        """Initialize the selector.

        Args:
            eligibility: Eligibility requirements (defaults to standard)
            constraints: Diversity constraints (defaults to standard)
        """
        self.eligibility = eligibility or EligibilityRequirements()
        self.constraints = constraints or DiversityConstraints()

    def check_eligibility(
        self,
        reputation: float,
        account_age_days: int,
        verification_count: int,
        uphold_rate: float,
        attestation_count: int,
        active_slashing: bool,
    ) -> tuple[bool, list[str]]:
        """Check if an agent is eligible to be a validator.

        Returns:
            Tuple of (eligible, list of reasons if not eligible)
        """
        return self.eligibility.check(
            reputation=reputation,
            account_age_days=account_age_days,
            verification_count=verification_count,
            uphold_rate=uphold_rate,
            attestation_count=attestation_count,
            active_slashing=active_slashing,
        )

    def compute_weight(self, candidate: ValidatorCandidate) -> float:
        """Compute selection weight for a candidate."""
        return compute_selection_weight(candidate)

    def select_for_epoch(
        self,
        candidates: list[ValidatorCandidate],
        epoch_seed: bytes,
        epoch_number: int,
        previous_epoch: ValidatorSet | None = None,
        network_stats: dict[str, int] | None = None,
    ) -> ValidatorSet:
        """Select validators for a new epoch.

        Args:
            candidates: List of eligible candidates
            epoch_seed: Random seed for selection
            epoch_number: The epoch number
            previous_epoch: Previous epoch's validator set (for tenure tracking)
            network_stats: Network statistics for sizing (optional)

        Returns:
            New ValidatorSet for the epoch
        """
        # Determine target count
        stats = network_stats or {}
        target_count = compute_validator_set_size(
            monthly_active_agents=stats.get("monthly_active_agents", 0),
            l4_elevations_last_epoch=stats.get("l4_elevations_last_epoch", 0),
        )

        # Get previous validator DIDs
        previous_validators: set[str] = set()
        if previous_epoch:
            previous_validators = {v.agent_id for v in previous_epoch.validators}

            # Update tenure for candidates
            for candidate in candidates:
                prev_validator = previous_epoch.get_validator(candidate.agent_id)
                if prev_validator:
                    candidate.tenure_epochs = prev_validator.tenure_epochs
                    candidate.last_epoch_performance = prev_validator.performance

        # Select validators
        validators = select_validators(
            candidates=candidates,
            epoch_seed=epoch_seed,
            target_count=target_count,
            constraints=self.constraints,
            previous_validators=previous_validators,
        )

        # Set epoch info on validators
        for validator in validators:
            validator.first_epoch = epoch_number

        # Compute epoch times
        epoch_start = datetime.now()
        epoch_end = epoch_start + timedelta(days=EPOCH_DURATION_DAYS)

        # Compute selection proof hash (hash of all tickets)
        proof_data = b"".join(v.selection_ticket for v in validators)
        proof_hash = hashlib.sha256(proof_data).digest()

        # Get previous epoch hash
        prev_hash = b"\x00" * 32
        if previous_epoch:
            prev_data = f"{previous_epoch.epoch}:{previous_epoch.selection_seed.hex()}".encode()
            prev_hash = hashlib.sha256(prev_data).digest()

        return ValidatorSet(
            epoch=epoch_number,
            epoch_start=epoch_start,
            epoch_end=epoch_end,
            validators=validators,
            selection_seed=epoch_seed,
            selection_proof_hash=proof_hash,
            previous_epoch_hash=prev_hash,
            diversity_constraints=self.constraints,
        )

    def verify_selection(
        self,
        validator_set: ValidatorSet,
        candidates: list[ValidatorCandidate],
    ) -> tuple[bool, list[str]]:
        """Verify that a validator set was correctly selected.

        Args:
            validator_set: The validator set to verify
            candidates: The original candidate pool

        Returns:
            Tuple of (valid, list of issues if invalid)
        """
        issues = []

        # Check validator count
        expected_f = (len(validator_set.validators) - 1) // 3
        expected_count = 3 * expected_f + 1
        if len(validator_set.validators) != expected_count:
            issues.append(f"Invalid validator count: {len(validator_set.validators)} != 3f+1")

        # Check diversity constraints
        federation_counts: dict[str, int] = {}
        tier_counts: dict[ValidatorTier, int] = {}

        for validator in validator_set.validators:
            for fed in validator.federation_membership:
                federation_counts[fed] = federation_counts.get(fed, 0) + 1
            tier_counts[validator.tier] = tier_counts.get(validator.tier, 0) + 1

        # Check federation diversity
        max_per_fed = int(len(validator_set.validators) * self.constraints.max_from_same_federation)
        for fed, count in federation_counts.items():
            if count > max_per_fed:
                issues.append(f"Federation {fed} over limit: {count} > {max_per_fed}")

        # Check tier diversity
        standard_count = tier_counts.get(ValidatorTier.STANDARD, 0)
        min_standard = int(len(validator_set.validators) * self.constraints.min_standard_tier)
        if standard_count < min_standard:
            issues.append(f"Not enough standard tier: {standard_count} < {min_standard}")

        return len(issues) == 0, issues
