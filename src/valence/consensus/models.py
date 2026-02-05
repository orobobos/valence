"""Data models for Valence Consensus.

These models represent consensus concepts like validators, stakes,
epochs, slashing, and elevation proposals per NODE-SELECTION.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

# =============================================================================
# ENUMS
# =============================================================================


class ValidatorTier(StrEnum):
    """Validator stake tiers with different risk/reward profiles."""

    STANDARD = "standard"  # 0.10-0.30 stake, 1.0× weight
    ENHANCED = "enhanced"  # 0.30-0.50 stake, 1.5× weight
    GUARDIAN = "guardian"  # 0.50-0.80 stake, 2.0× weight

    @property
    def multiplier(self) -> float:
        """Get the selection weight multiplier for this tier."""
        return {
            ValidatorTier.STANDARD: 1.0,
            ValidatorTier.ENHANCED: 1.5,
            ValidatorTier.GUARDIAN: 2.0,
        }[self]

    @property
    def min_stake(self) -> float:
        """Get minimum stake for this tier."""
        return {
            ValidatorTier.STANDARD: 0.10,
            ValidatorTier.ENHANCED: 0.30,
            ValidatorTier.GUARDIAN: 0.50,
        }[self]

    @property
    def max_stake(self) -> float:
        """Get maximum stake for this tier."""
        return {
            ValidatorTier.STANDARD: 0.30,
            ValidatorTier.ENHANCED: 0.50,
            ValidatorTier.GUARDIAN: 0.80,
        }[self]


class ValidatorStatus(StrEnum):
    """Current status of a validator."""

    ELIGIBLE = "eligible"  # Meets criteria but not staked
    STAKED = "staked"  # In pool waiting for selection
    ACTIVE = "active"  # Currently validating
    COOLDOWN = "cooldown"  # Epoch ended, unbonding
    SUSPENDED = "suspended"  # Temporarily suspended
    SLASHED = "slashed"  # Stake slashed


class StakeStatus(StrEnum):
    """Status of a stake registration."""

    PENDING = "pending"  # Registered, not yet active
    ACTIVE = "active"  # Stake is active
    UNBONDING = "unbonding"  # Requested withdrawal
    SLASHED = "slashed"  # Slashed due to misbehavior
    WITHDRAWN = "withdrawn"  # Successfully withdrawn


class AttestationType(StrEnum):
    """Types of identity attestations for Sybil resistance."""

    SOCIAL_VALIDATOR = "social_validator"  # Existing validators vouch
    FEDERATION_MEMBER = "federation_member"  # Federation vouches
    GOVERNMENT_ID = "government_id"  # Via bridge
    BIOMETRIC_POH = "biometric_poh"  # Worldcoin, etc.
    WEB_OF_TRUST = "web_of_trust"  # Keybase-style


class SlashingOffense(StrEnum):
    """Types of slashable offenses."""

    DOUBLE_VOTING = "double_voting"  # CRITICAL: 100% slash
    EQUIVOCATION = "equivocation"  # CRITICAL: 100% slash
    COLLUSION = "collusion"  # CRITICAL: 100% slash
    UNAVAILABILITY = "unavailability"  # HIGH: 50% slash
    CENSORSHIP = "censorship"  # HIGH: 50% slash
    INVALID_VOTE = "invalid_vote"  # MEDIUM: 20% slash
    LATE_VOTING = "late_voting"  # LOW: 5% slash

    @property
    def severity(self) -> str:
        """Get severity level of this offense."""
        return {
            SlashingOffense.DOUBLE_VOTING: "CRITICAL",
            SlashingOffense.EQUIVOCATION: "CRITICAL",
            SlashingOffense.COLLUSION: "CRITICAL",
            SlashingOffense.UNAVAILABILITY: "HIGH",
            SlashingOffense.CENSORSHIP: "HIGH",
            SlashingOffense.INVALID_VOTE: "MEDIUM",
            SlashingOffense.LATE_VOTING: "LOW",
        }[self]

    @property
    def slash_percentage(self) -> float:
        """Get slash percentage for this offense."""
        return {
            SlashingOffense.DOUBLE_VOTING: 1.0,
            SlashingOffense.EQUIVOCATION: 1.0,
            SlashingOffense.COLLUSION: 1.0,
            SlashingOffense.UNAVAILABILITY: 0.5,
            SlashingOffense.CENSORSHIP: 0.5,
            SlashingOffense.INVALID_VOTE: 0.2,
            SlashingOffense.LATE_VOTING: 0.05,
        }[self]


class SlashingStatus(StrEnum):
    """Status of a slashing event."""

    PENDING = "pending"  # Reported, awaiting review
    CONFIRMED = "confirmed"  # Confirmed by validators
    APPEALED = "appealed"  # Under appeal
    EXECUTED = "executed"  # Slash applied
    REJECTED = "rejected"  # Evidence insufficient


class ElevationVoteChoice(StrEnum):
    """Vote choices for elevation proposals."""

    APPROVE = "approve"
    REJECT = "reject"
    ABSTAIN = "abstain"


class ElevationOutcome(StrEnum):
    """Outcomes of elevation proposals."""

    ELEVATED = "elevated"  # Reached quorum, elevated to L4
    REJECTED = "rejected"  # Reached quorum, rejected
    DEFERRED = "deferred"  # No quorum, deferred to next epoch
    PENDING = "pending"  # Voting in progress


# =============================================================================
# IDENTITY ATTESTATION
# =============================================================================


@dataclass
class IdentityAttestation:
    """Attestation proving unique identity for Sybil resistance."""

    id: UUID
    agent_id: str  # DID of the attested agent
    type: AttestationType

    # Attester info
    attester: str  # DID of attester or 'external_system'
    attested_at: datetime
    expires_at: datetime | None = None

    # Verification
    proof: bytes = field(default_factory=bytes)
    verifiable: bool = True

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_valid(self, as_of: datetime | None = None) -> bool:
        """Check if attestation is currently valid."""
        check_time = as_of or datetime.now()
        if self.expires_at and check_time > self.expires_at:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": str(self.id),
            "agent_id": self.agent_id,
            "type": self.type.value,
            "attester": self.attester,
            "attested_at": self.attested_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "proof": self.proof.hex() if self.proof else "",
            "verifiable": self.verifiable,
            "metadata": self.metadata,
        }


# =============================================================================
# STAKE REGISTRATION
# =============================================================================


@dataclass
class StakeRegistration:
    """Registration of reputation stake for validator eligibility."""

    id: UUID
    agent_id: str  # DID
    amount: float  # Reputation staked
    tier: ValidatorTier

    # Timing
    registered_at: datetime
    eligible_from_epoch: int  # Can't join current epoch

    # Status
    status: StakeStatus = StakeStatus.PENDING
    unbond_requested_at: datetime | None = None
    unbond_available_at: datetime | None = None

    # Slashing
    slashed_amount: float = 0.0
    slash_reason: str | None = None

    def is_eligible_for_epoch(self, epoch: int) -> bool:
        """Check if stake is eligible for given epoch."""
        if self.status not in (StakeStatus.PENDING, StakeStatus.ACTIVE):
            return False
        return epoch >= self.eligible_from_epoch

    def effective_stake(self) -> float:
        """Get stake amount minus any slashing."""
        return max(0.0, self.amount - self.slashed_amount)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": str(self.id),
            "agent_id": self.agent_id,
            "amount": self.amount,
            "tier": self.tier.value,
            "registered_at": self.registered_at.isoformat(),
            "eligible_from_epoch": self.eligible_from_epoch,
            "status": self.status.value,
            "unbond_requested_at": (self.unbond_requested_at.isoformat() if self.unbond_requested_at else None),
            "unbond_available_at": (self.unbond_available_at.isoformat() if self.unbond_available_at else None),
            "slashed_amount": self.slashed_amount,
            "slash_reason": self.slash_reason,
            "effective_stake": self.effective_stake(),
        }


# =============================================================================
# VALIDATOR
# =============================================================================


@dataclass
class ValidatorPerformance:
    """Performance metrics for a validator during an epoch."""

    participation_rate: float = 1.0  # % of rounds participated
    votes_cast: int = 0
    votes_correct: int = 0  # Aligned with consensus
    byzantine_strikes: int = 0
    average_vote_latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "participation_rate": self.participation_rate,
            "votes_cast": self.votes_cast,
            "votes_correct": self.votes_correct,
            "byzantine_strikes": self.byzantine_strikes,
            "average_vote_latency_ms": self.average_vote_latency_ms,
        }


@dataclass
class Validator:
    """A validator in the consensus system."""

    id: UUID
    agent_id: str  # DID

    # Stake
    staked_reputation: float
    tier: ValidatorTier
    stake_lock_until: datetime

    # Selection
    selection_weight: float
    selection_ticket: bytes  # VRF ticket that won selection

    # Identity
    public_key: bytes  # Ed25519 public key for VRF
    attestations: list[IdentityAttestation] = field(default_factory=list)

    # Federation membership (for diversity)
    federation_membership: list[str] = field(default_factory=list)

    # Tenure
    tenure_epochs: int = 0  # Consecutive epochs served
    first_epoch: int = 0

    # Status
    status: ValidatorStatus = ValidatorStatus.ACTIVE

    # Performance (updated throughout epoch)
    performance: ValidatorPerformance = field(default_factory=ValidatorPerformance)

    # Eligibility snapshot
    reputation_at_selection: float = 0.0

    def has_valid_attestation(self, as_of: datetime | None = None) -> bool:
        """Check if validator has at least one valid attestation."""
        return any(att.is_valid(as_of) for att in self.attestations)

    def attestation_count(self, as_of: datetime | None = None) -> int:
        """Count valid attestations."""
        return sum(1 for att in self.attestations if att.is_valid(as_of))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": str(self.id),
            "agent_id": self.agent_id,
            "staked_reputation": self.staked_reputation,
            "tier": self.tier.value,
            "stake_lock_until": self.stake_lock_until.isoformat(),
            "selection_weight": self.selection_weight,
            "selection_ticket": self.selection_ticket.hex(),
            "public_key": self.public_key.hex(),
            "attestations": [att.to_dict() for att in self.attestations],
            "federation_membership": self.federation_membership,
            "tenure_epochs": self.tenure_epochs,
            "first_epoch": self.first_epoch,
            "status": self.status.value,
            "performance": self.performance.to_dict(),
            "reputation_at_selection": self.reputation_at_selection,
        }


# =============================================================================
# VALIDATOR SET
# =============================================================================


@dataclass
class DiversityConstraints:
    """Constraints to ensure diverse validator selection."""

    # Federation diversity
    max_from_same_federation: float = 0.20  # Max 20% from any federation
    min_federation_diversity: int = 3  # At least 3 federations

    # Tenure diversity
    max_consecutive_validators: float = 0.60  # Max 60% returning
    min_new_validators: float = 0.20  # At least 20% new

    # Tier diversity
    min_standard_tier: float = 0.30  # At least 30% from standard tier

    # Geographic diversity (optional)
    max_from_same_region: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "max_from_same_federation": self.max_from_same_federation,
            "min_federation_diversity": self.min_federation_diversity,
            "max_consecutive_validators": self.max_consecutive_validators,
            "min_new_validators": self.min_new_validators,
            "min_standard_tier": self.min_standard_tier,
            "max_from_same_region": self.max_from_same_region,
        }


@dataclass
class ValidatorSet:
    """The active validator set for an epoch."""

    epoch: int
    epoch_start: datetime
    epoch_end: datetime

    validators: list[Validator] = field(default_factory=list)

    # Selection proof
    selection_seed: bytes = field(default_factory=bytes)
    selection_proof_hash: bytes = field(default_factory=bytes)  # Hash of all proofs

    # Chain of epochs
    previous_epoch_hash: bytes = field(default_factory=bytes)

    # Constraints used
    diversity_constraints: DiversityConstraints = field(default_factory=DiversityConstraints)

    @property
    def validator_count(self) -> int:
        """Number of validators in the set."""
        return len(self.validators)

    @property
    def byzantine_tolerance(self) -> int:
        """Maximum Byzantine nodes tolerated (f where n=3f+1)."""
        return (self.validator_count - 1) // 3

    @property
    def quorum_threshold(self) -> int:
        """Required votes for consensus (2f+1)."""
        f = self.byzantine_tolerance
        return 2 * f + 1

    @property
    def supermajority_threshold(self) -> int:
        """Required votes for supermajority decisions."""
        f = self.byzantine_tolerance
        return (5 * f) // 6 + 1

    def get_validator(self, agent_id: str) -> Validator | None:
        """Find validator by agent ID."""
        for v in self.validators:
            if v.agent_id == agent_id:
                return v
        return None

    def is_validator(self, agent_id: str) -> bool:
        """Check if agent is an active validator."""
        return self.get_validator(agent_id) is not None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "epoch": self.epoch,
            "epoch_start": self.epoch_start.isoformat(),
            "epoch_end": self.epoch_end.isoformat(),
            "validators": [v.to_dict() for v in self.validators],
            "validator_count": self.validator_count,
            "quorum_threshold": self.quorum_threshold,
            "selection_seed": self.selection_seed.hex(),
            "selection_proof_hash": self.selection_proof_hash.hex(),
            "previous_epoch_hash": self.previous_epoch_hash.hex(),
            "diversity_constraints": self.diversity_constraints.to_dict(),
        }


# =============================================================================
# EPOCH TRANSITION
# =============================================================================


@dataclass
class EpochTransition:
    """Record of transition between epochs."""

    id: UUID
    ending_epoch: int
    starting_epoch: int

    # Outgoing validators
    outgoing_validators: list[str] = field(default_factory=list)  # DIDs
    outgoing_performance: dict[str, ValidatorPerformance] = field(default_factory=dict)

    # Incoming validators
    incoming_validators: list[str] = field(default_factory=list)  # DIDs
    selection_seed: bytes = field(default_factory=bytes)

    # State handoff
    pending_elevations: list[UUID] = field(default_factory=list)
    pending_challenges: list[UUID] = field(default_factory=list)

    # Signatures (for verification)
    outgoing_signature_count: int = 0
    incoming_acknowledgment_count: int = 0

    # Timing
    transition_started_at: datetime = field(default_factory=datetime.now)
    transition_completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "ending_epoch": self.ending_epoch,
            "starting_epoch": self.starting_epoch,
            "outgoing_validators": self.outgoing_validators,
            "outgoing_performance": {k: v.to_dict() for k, v in self.outgoing_performance.items()},
            "incoming_validators": self.incoming_validators,
            "selection_seed": self.selection_seed.hex(),
            "pending_elevations": [str(e) for e in self.pending_elevations],
            "pending_challenges": [str(c) for c in self.pending_challenges],
            "outgoing_signature_count": self.outgoing_signature_count,
            "incoming_acknowledgment_count": self.incoming_acknowledgment_count,
            "transition_started_at": self.transition_started_at.isoformat(),
            "transition_completed_at": (self.transition_completed_at.isoformat() if self.transition_completed_at else None),
        }


# =============================================================================
# SLASHING
# =============================================================================


@dataclass
class SlashingEvidence:
    """Evidence supporting a slashing claim."""

    # Cryptographic evidence (e.g., two conflicting signed votes)
    evidence_type: str
    evidence_data: bytes
    evidence_hash: bytes

    # Metadata
    collected_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "evidence_type": self.evidence_type,
            "evidence_data": self.evidence_data.hex(),
            "evidence_hash": self.evidence_hash.hex(),
            "collected_at": self.collected_at.isoformat(),
        }


@dataclass
class SlashingEvent:
    """A slashing event for validator misbehavior."""

    id: UUID
    validator_id: str  # DID of accused validator
    offense: SlashingOffense

    # Evidence
    evidence: SlashingEvidence

    # Amounts
    stake_at_risk: float
    slash_amount: float

    # Process
    reported_by: str  # DID of reporter
    reported_at: datetime
    status: SlashingStatus = SlashingStatus.PENDING

    # Resolution
    resolution_votes: dict[str, bool] = field(default_factory=dict)  # DID -> vote
    resolution_at: datetime | None = None
    appeal_deadline: datetime | None = None

    # Distribution (if executed)
    reporter_reward: float = 0.0  # 30% to reporter
    security_fund: float = 0.0  # 20% to security fund
    burned: float = 0.0  # 50% burned

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "validator_id": self.validator_id,
            "offense": self.offense.value,
            "offense_severity": self.offense.severity,
            "evidence": self.evidence.to_dict(),
            "stake_at_risk": self.stake_at_risk,
            "slash_amount": self.slash_amount,
            "reported_by": self.reported_by,
            "reported_at": self.reported_at.isoformat(),
            "status": self.status.value,
            "resolution_votes": self.resolution_votes,
            "resolution_at": (self.resolution_at.isoformat() if self.resolution_at else None),
            "appeal_deadline": (self.appeal_deadline.isoformat() if self.appeal_deadline else None),
            "reporter_reward": self.reporter_reward,
            "security_fund": self.security_fund,
            "burned": self.burned,
        }


# =============================================================================
# ELEVATION VOTING
# =============================================================================


@dataclass
class VerificationReport:
    """Report from a validator's independent verification."""

    independence_verified: bool = False
    evidence_chains_traced: bool = False
    requirements_met: bool = False
    concerns: list[str] = field(default_factory=list)

    # Detailed checks
    independence_score: float | None = None
    domain_count: int | None = None
    verification_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "independence_verified": self.independence_verified,
            "evidence_chains_traced": self.evidence_chains_traced,
            "requirements_met": self.requirements_met,
            "concerns": self.concerns,
            "independence_score": self.independence_score,
            "domain_count": self.domain_count,
            "verification_count": self.verification_count,
        }


@dataclass
class ElevationVote:
    """A validator's vote on an elevation proposal."""

    id: UUID
    proposal_id: UUID
    validator_id: str  # DID

    vote: ElevationVoteChoice
    verification_report: VerificationReport

    # Cryptographic
    signature: bytes = field(default_factory=bytes)
    voted_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "proposal_id": str(self.proposal_id),
            "validator_id": self.validator_id,
            "vote": self.vote.value,
            "verification_report": self.verification_report.to_dict(),
            "signature": self.signature.hex() if self.signature else "",
            "voted_at": self.voted_at.isoformat(),
        }


@dataclass
class ElevationProposal:
    """A proposal to elevate a belief to L4 (Communal Knowledge)."""

    id: UUID
    belief_id: UUID
    proposed_at: datetime

    # Proposer
    proposer: str  # DID
    proposer_stake: float  # Stake at risk if frivolous

    # Voting
    voting_epoch: int
    voting_deadline: datetime

    votes: list[ElevationVote] = field(default_factory=list)

    # Requirements checked
    requirements: dict[str, bool] = field(default_factory=dict)

    # Outcome
    outcome: ElevationOutcome = ElevationOutcome.PENDING
    finalized_at: datetime | None = None

    def approve_count(self) -> int:
        """Count approval votes."""
        return sum(1 for v in self.votes if v.vote == ElevationVoteChoice.APPROVE)

    def reject_count(self) -> int:
        """Count rejection votes."""
        return sum(1 for v in self.votes if v.vote == ElevationVoteChoice.REJECT)

    def abstain_count(self) -> int:
        """Count abstention votes."""
        return sum(1 for v in self.votes if v.vote == ElevationVoteChoice.ABSTAIN)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "belief_id": str(self.belief_id),
            "proposed_at": self.proposed_at.isoformat(),
            "proposer": self.proposer,
            "proposer_stake": self.proposer_stake,
            "voting_epoch": self.voting_epoch,
            "voting_deadline": self.voting_deadline.isoformat(),
            "votes": [v.to_dict() for v in self.votes],
            "requirements": self.requirements,
            "outcome": self.outcome.value,
            "finalized_at": (self.finalized_at.isoformat() if self.finalized_at else None),
            "approve_count": self.approve_count(),
            "reject_count": self.reject_count(),
            "abstain_count": self.abstain_count(),
        }


# =============================================================================
# ELIGIBILITY REQUIREMENTS
# =============================================================================


@dataclass
class EligibilityRequirements:
    """Requirements for validator eligibility per NODE-SELECTION.md."""

    min_reputation: float = 0.5
    min_account_age_days: int = 180
    min_verification_history: int = 50
    min_uphold_rate: float = 0.70
    requires_attestation: bool = True
    no_active_slashing: bool = True

    def check(
        self,
        reputation: float,
        account_age_days: int,
        verification_count: int,
        uphold_rate: float,
        attestation_count: int,
        active_slashing: bool,
    ) -> tuple[bool, list[str]]:
        """Check if an agent meets eligibility requirements.

        Returns:
            Tuple of (eligible, list of reasons if not eligible)
        """
        reasons = []

        if reputation < self.min_reputation:
            reasons.append(f"Reputation {reputation:.2f} < {self.min_reputation:.2f}")

        if account_age_days < self.min_account_age_days:
            reasons.append(f"Account age {account_age_days} days < {self.min_account_age_days} days")

        if verification_count < self.min_verification_history:
            reasons.append(f"Verification count {verification_count} < {self.min_verification_history}")

        if uphold_rate < self.min_uphold_rate:
            reasons.append(f"Uphold rate {uphold_rate:.2%} < {self.min_uphold_rate:.2%}")

        if self.requires_attestation and attestation_count < 1:
            reasons.append("No valid identity attestation")

        if self.no_active_slashing and active_slashing:
            reasons.append("Active slashing event pending")

        return len(reasons) == 0, reasons

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "min_reputation": self.min_reputation,
            "min_account_age_days": self.min_account_age_days,
            "min_verification_history": self.min_verification_history,
            "min_uphold_rate": self.min_uphold_rate,
            "requires_attestation": self.requires_attestation,
            "no_active_slashing": self.no_active_slashing,
        }
