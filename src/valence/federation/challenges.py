"""Challenge and Reviewer System for Valence Federation.

Implements the challenge resolution mechanism for disputed beliefs,
with configurable reviewer requirements based on belief layer.

Security measures (per THREAT-MODEL.md §1.4.3):
- Increased reviewer count for L3/L4 beliefs (7 vs 3)
- Random reviewer selection (no volunteering)
- Reviewer independence verification (no shared federation membership)
- Appeal mechanism with escalation
- Reviewer reputation tracking

See: spec/components/consensus-mechanism/SPEC.md §6
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================


@dataclass
class ReviewerConfig:
    """Configuration for reviewer requirements by belief layer.

    Per THREAT-MODEL.md §1.4.3, L3/L4 beliefs require more reviewers
    to prevent collusion-based challenge suppression.
    """

    # Layer-specific reviewer counts (min reviewers required)
    l1_reviewers: int = 3  # Personal beliefs: 3 reviewers
    l2_reviewers: int = 3  # Federated beliefs: 3 reviewers
    l3_reviewers: int = 7  # Domain knowledge: 7 reviewers (increased)
    l4_reviewers: int = 7  # Communal consensus: 7 reviewers (increased)

    # Consensus thresholds (fraction of reviewers that must agree)
    l1_consensus_threshold: float = 2 / 3  # ~67%
    l2_consensus_threshold: float = 2 / 3  # ~67%
    l3_consensus_threshold: float = 3 / 4  # 75% (stricter for high-stakes)
    l4_consensus_threshold: float = 3 / 4  # 75%

    # Appeal escalation multipliers
    appeal_reviewer_multiplier: float = 1.5  # 50% more reviewers on appeal
    max_appeal_rounds: int = 2  # Maximum appeal rounds

    # Reviewer eligibility requirements
    min_reviewer_reputation: float = 0.4  # Minimum reputation to review
    min_reviewer_age_days: int = 30  # Minimum account age
    min_verifications: int = 10  # Minimum verification history

    # Independence requirements
    max_shared_federations: int = 0  # Reviewers cannot share federations with belief holder
    min_independence_score: float = 0.6  # Minimum pairwise independence between reviewers

    # Timing
    review_deadline_days: int = 7  # Days to complete review
    appeal_deadline_days: int = 14  # Days to file appeal

    def get_reviewer_count(self, layer: str) -> int:
        """Get required reviewer count for a belief layer."""
        counts = {
            "L1": self.l1_reviewers,
            "L2": self.l2_reviewers,
            "L3": self.l3_reviewers,
            "L4": self.l4_reviewers,
        }
        return counts.get(layer.upper(), self.l1_reviewers)

    def get_consensus_threshold(self, layer: str) -> float:
        """Get consensus threshold for a belief layer."""
        thresholds = {
            "L1": self.l1_consensus_threshold,
            "L2": self.l2_consensus_threshold,
            "L3": self.l3_consensus_threshold,
            "L4": self.l4_consensus_threshold,
        }
        return thresholds.get(layer.upper(), self.l1_consensus_threshold)

    def get_appeal_reviewer_count(self, layer: str, appeal_round: int) -> int:
        """Get reviewer count for an appeal round."""
        base_count = self.get_reviewer_count(layer)
        # Each appeal round increases reviewer count
        multiplier = self.appeal_reviewer_multiplier**appeal_round
        return max(base_count, int(base_count * multiplier))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "reviewer_counts": {
                "L1": self.l1_reviewers,
                "L2": self.l2_reviewers,
                "L3": self.l3_reviewers,
                "L4": self.l4_reviewers,
            },
            "consensus_thresholds": {
                "L1": self.l1_consensus_threshold,
                "L2": self.l2_consensus_threshold,
                "L3": self.l3_consensus_threshold,
                "L4": self.l4_consensus_threshold,
            },
            "appeal_settings": {
                "multiplier": self.appeal_reviewer_multiplier,
                "max_rounds": self.max_appeal_rounds,
            },
            "eligibility": {
                "min_reputation": self.min_reviewer_reputation,
                "min_age_days": self.min_reviewer_age_days,
                "min_verifications": self.min_verifications,
            },
            "independence": {
                "max_shared_federations": self.max_shared_federations,
                "min_independence_score": self.min_independence_score,
            },
            "timing": {
                "review_deadline_days": self.review_deadline_days,
                "appeal_deadline_days": self.appeal_deadline_days,
            },
        }


# Default configuration
DEFAULT_REVIEWER_CONFIG = ReviewerConfig()


# =============================================================================
# ENUMS
# =============================================================================


class ChallengeType(StrEnum):
    """Types of challenges to beliefs."""

    FACTUAL_ERROR = "factual_error"  # The claim is factually wrong
    INDEPENDENCE_VIOLATION = "independence"  # Sources aren't independent
    EVIDENCE_QUALITY = "evidence_quality"  # Evidence is weak/invalid
    OUTDATED = "outdated"  # Was true but no longer
    METHODOLOGY = "methodology"  # Derivation method is flawed
    SCOPE = "scope"  # Claim is overgeneralized


class ChallengeStatus(StrEnum):
    """Status of a challenge."""

    OPEN = "open"  # Awaiting reviewer assignment
    UNDER_REVIEW = "under_review"  # Reviewers assigned, reviewing
    UPHELD = "upheld"  # Challenge accepted, belief demoted
    REJECTED = "rejected"  # Challenge rejected, belief stands
    WITHDRAWN = "withdrawn"  # Challenger withdrew
    APPEALED = "appealed"  # Decision appealed, new review
    EXPIRED = "expired"  # Review deadline passed


class ReviewDecision(StrEnum):
    """Individual reviewer's decision."""

    UPHOLD = "uphold"  # Support the challenge
    REJECT = "reject"  # Reject the challenge
    ABSTAIN = "abstain"  # Cannot decide (rare)


class ReviewerStatus(StrEnum):
    """Status of a reviewer assignment."""

    ASSIGNED = "assigned"  # Selected, awaiting review
    COMPLETED = "completed"  # Submitted decision
    RECUSED = "recused"  # Conflict of interest found
    EXPIRED = "expired"  # Did not review in time


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class Challenge:
    """A challenge to a belief's validity.

    Challenges allow any agent to dispute a belief's accuracy,
    evidence quality, or other aspects. Successful challenges
    can result in belief demotion or revision.
    """

    id: UUID

    # Target
    target_belief_id: UUID
    target_layer: str  # L1, L2, L3, L4

    # Challenger
    challenger_did: str
    challenger_stake: float  # Reputation staked on challenge

    # Challenge details
    challenge_type: ChallengeType
    reasoning: str
    counter_evidence: list[dict[str, Any]] = field(default_factory=list)

    # Status
    status: ChallengeStatus = ChallengeStatus.OPEN

    # Appeal tracking
    appeal_round: int = 0
    previous_challenge_id: UUID | None = None  # If this is an appeal

    # Resolution
    resolution: ChallengeResolution | None = None

    # Timing
    created_at: datetime = field(default_factory=datetime.now)
    review_deadline: datetime | None = None
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        """Set review deadline if not set."""
        if self.review_deadline is None:
            config = DEFAULT_REVIEWER_CONFIG
            self.review_deadline = self.created_at + timedelta(days=config.review_deadline_days)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": str(self.id),
            "target_belief_id": str(self.target_belief_id),
            "target_layer": self.target_layer,
            "challenger_did": self.challenger_did,
            "challenger_stake": float(self.challenger_stake),
            "challenge_type": self.challenge_type.value,
            "reasoning": self.reasoning,
            "counter_evidence": self.counter_evidence,
            "status": self.status.value,
            "appeal_round": self.appeal_round,
            "previous_challenge_id": (str(self.previous_challenge_id) if self.previous_challenge_id else None),
            "resolution": self.resolution.to_dict() if self.resolution else None,
            "created_at": self.created_at.isoformat(),
            "review_deadline": (self.review_deadline.isoformat() if self.review_deadline else None),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Challenge:
        """Create from dictionary."""
        resolution = None
        if data.get("resolution"):
            resolution = ChallengeResolution.from_dict(data["resolution"])

        return cls(
            id=UUID(data["id"]) if isinstance(data["id"], str) else data["id"],
            target_belief_id=(UUID(data["target_belief_id"]) if isinstance(data["target_belief_id"], str) else data["target_belief_id"]),
            target_layer=data["target_layer"],
            challenger_did=data["challenger_did"],
            challenger_stake=float(data["challenger_stake"]),
            challenge_type=ChallengeType(data["challenge_type"]),
            reasoning=data["reasoning"],
            counter_evidence=data.get("counter_evidence", []),
            status=ChallengeStatus(data["status"]),
            appeal_round=data.get("appeal_round", 0),
            previous_challenge_id=(UUID(data["previous_challenge_id"]) if data.get("previous_challenge_id") else None),
            resolution=resolution,
            created_at=(datetime.fromisoformat(data["created_at"]) if isinstance(data["created_at"], str) else data["created_at"]),
            review_deadline=(datetime.fromisoformat(data["review_deadline"]) if data.get("review_deadline") else None),
            resolved_at=(datetime.fromisoformat(data["resolved_at"]) if data.get("resolved_at") else None),
        )


@dataclass
class ChallengeReview:
    """Individual reviewer's assessment of a challenge."""

    id: UUID
    challenge_id: UUID

    # Reviewer
    reviewer_did: str
    reviewer_reputation: float  # At time of assignment

    # Assignment
    status: ReviewerStatus = ReviewerStatus.ASSIGNED
    assigned_at: datetime = field(default_factory=datetime.now)

    # Decision
    decision: ReviewDecision | None = None
    reasoning: str | None = None
    confidence: float | None = None  # 0-1, reviewer's confidence in decision

    # Stake
    stake: float = 0.0  # Reputation at risk

    # Completion
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "challenge_id": str(self.challenge_id),
            "reviewer_did": self.reviewer_did,
            "reviewer_reputation": float(self.reviewer_reputation),
            "status": self.status.value,
            "assigned_at": self.assigned_at.isoformat(),
            "decision": self.decision.value if self.decision else None,
            "reasoning": self.reasoning,
            "confidence": (float(self.confidence) if self.confidence is not None else None),
            "stake": float(self.stake),
            "completed_at": (self.completed_at.isoformat() if self.completed_at else None),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChallengeReview:
        """Create from dictionary."""
        return cls(
            id=UUID(data["id"]) if isinstance(data["id"], str) else data["id"],
            challenge_id=(UUID(data["challenge_id"]) if isinstance(data["challenge_id"], str) else data["challenge_id"]),
            reviewer_did=data["reviewer_did"],
            reviewer_reputation=float(data["reviewer_reputation"]),
            status=ReviewerStatus(data["status"]),
            assigned_at=(datetime.fromisoformat(data["assigned_at"]) if isinstance(data["assigned_at"], str) else data["assigned_at"]),
            decision=ReviewDecision(data["decision"]) if data.get("decision") else None,
            reasoning=data.get("reasoning"),
            confidence=(float(data["confidence"]) if data.get("confidence") is not None else None),
            stake=float(data.get("stake", 0)),
            completed_at=(datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None),
        )


@dataclass
class ChallengeResolution:
    """Final resolution of a challenge."""

    outcome: str  # "upheld", "rejected", "partial"

    # Voting summary
    uphold_votes: int = 0
    reject_votes: int = 0
    abstain_votes: int = 0
    total_reviewers: int = 0

    # Effects
    belief_demoted: bool = False
    belief_revised: bool = False
    new_layer: str | None = None  # If demoted

    # Reputation effects
    challenger_reward: float = 0.0
    challenger_penalty: float = 0.0
    belief_holder_penalty: float = 0.0

    # Reviewer penalties (DIDs of reviewers who voted against majority)
    reviewer_penalties: dict[str, float] = field(default_factory=dict)

    # Reasoning
    summary: str = ""
    resolved_by: list[str] = field(default_factory=list)  # Reviewer DIDs

    resolved_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "outcome": self.outcome,
            "votes": {
                "uphold": self.uphold_votes,
                "reject": self.reject_votes,
                "abstain": self.abstain_votes,
                "total": self.total_reviewers,
            },
            "effects": {
                "belief_demoted": self.belief_demoted,
                "belief_revised": self.belief_revised,
                "new_layer": self.new_layer,
            },
            "reputation": {
                "challenger_reward": float(self.challenger_reward),
                "challenger_penalty": float(self.challenger_penalty),
                "belief_holder_penalty": float(self.belief_holder_penalty),
                "reviewer_penalties": {k: float(v) for k, v in self.reviewer_penalties.items()},
            },
            "summary": self.summary,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChallengeResolution:
        """Create from dictionary."""
        votes = data.get("votes", {})
        effects = data.get("effects", {})
        reputation = data.get("reputation", {})

        return cls(
            outcome=data["outcome"],
            uphold_votes=votes.get("uphold", 0),
            reject_votes=votes.get("reject", 0),
            abstain_votes=votes.get("abstain", 0),
            total_reviewers=votes.get("total", 0),
            belief_demoted=effects.get("belief_demoted", False),
            belief_revised=effects.get("belief_revised", False),
            new_layer=effects.get("new_layer"),
            challenger_reward=float(reputation.get("challenger_reward", 0)),
            challenger_penalty=float(reputation.get("challenger_penalty", 0)),
            belief_holder_penalty=float(reputation.get("belief_holder_penalty", 0)),
            reviewer_penalties=reputation.get("reviewer_penalties", {}),
            summary=data.get("summary", ""),
            resolved_by=data.get("resolved_by", []),
            resolved_at=(datetime.fromisoformat(data["resolved_at"]) if data.get("resolved_at") else datetime.now()),
        )


@dataclass
class ReviewerReputation:
    """Tracks a reviewer's performance over time.

    Reviewers who consistently make decisions that are later
    overturned on appeal lose credibility and may be excluded
    from future review pools.
    """

    reviewer_did: str

    # Review history
    total_reviews: int = 0
    reviews_upheld: int = 0  # Reviewer's decision matched final outcome
    reviews_overturned: int = 0  # Reviewer's decision was overturned on appeal

    # Calculated metrics
    accuracy_rate: float = 1.0  # reviews_upheld / (total - abstains)

    # Domains reviewed
    domains: list[str] = field(default_factory=list)
    domain_accuracy: dict[str, float] = field(default_factory=dict)

    # Status
    is_eligible: bool = True
    ineligible_reason: str | None = None
    ineligible_until: datetime | None = None

    # Timestamps
    first_review_at: datetime | None = None
    last_review_at: datetime | None = None
    updated_at: datetime = field(default_factory=datetime.now)

    def update_accuracy(self) -> None:
        """Recalculate accuracy rate."""
        if self.total_reviews > 0:
            self.accuracy_rate = self.reviews_upheld / self.total_reviews
        else:
            self.accuracy_rate = 1.0
        self.updated_at = datetime.now()

    def record_review_outcome(self, was_upheld: bool, domain: str | None = None) -> None:
        """Record the outcome of a review."""
        self.total_reviews += 1
        if was_upheld:
            self.reviews_upheld += 1
        else:
            self.reviews_overturned += 1

        if domain:
            if domain not in self.domains:
                self.domains.append(domain)
            # Update domain accuracy
            domain_total = self.domain_accuracy.get(f"{domain}_total", 0) + 1
            domain_upheld = self.domain_accuracy.get(f"{domain}_upheld", 0) + (1 if was_upheld else 0)
            self.domain_accuracy[f"{domain}_total"] = domain_total
            self.domain_accuracy[f"{domain}_upheld"] = domain_upheld
            self.domain_accuracy[domain] = domain_upheld / domain_total

        self.last_review_at = datetime.now()
        self.update_accuracy()

        # Check if reviewer should be suspended
        if self.total_reviews >= 10 and self.accuracy_rate < 0.5:
            self.is_eligible = False
            self.ineligible_reason = "Accuracy rate below threshold"
            self.ineligible_until = datetime.now() + timedelta(days=90)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "reviewer_did": self.reviewer_did,
            "stats": {
                "total_reviews": self.total_reviews,
                "reviews_upheld": self.reviews_upheld,
                "reviews_overturned": self.reviews_overturned,
                "accuracy_rate": float(self.accuracy_rate),
            },
            "domains": self.domains,
            "domain_accuracy": {k: float(v) for k, v in self.domain_accuracy.items()},
            "eligibility": {
                "is_eligible": self.is_eligible,
                "ineligible_reason": self.ineligible_reason,
                "ineligible_until": (self.ineligible_until.isoformat() if self.ineligible_until else None),
            },
            "first_review_at": (self.first_review_at.isoformat() if self.first_review_at else None),
            "last_review_at": (self.last_review_at.isoformat() if self.last_review_at else None),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class EligibleReviewer:
    """A candidate for reviewer selection."""

    did: str
    reputation: float
    account_age_days: int
    verification_count: int
    federations: list[str]  # Federation memberships
    domains: list[str]  # Domain expertise
    reviewer_accuracy: float = 1.0  # Historical accuracy


# =============================================================================
# REVIEWER SELECTION
# =============================================================================


class ReviewerSelector:
    """Selects reviewers for challenges using random selection with independence checks.

    Per THREAT-MODEL.md §1.4.3:
    - Random selection (no volunteering)
    - No shared federation membership with belief holder
    - Reviewers must be independent of each other
    """

    def __init__(self, config: ReviewerConfig | None = None):
        self.config = config or DEFAULT_REVIEWER_CONFIG

    def select_reviewers(
        self,
        challenge: Challenge,
        eligible_pool: list[EligibleReviewer],
        belief_holder_did: str,
        belief_holder_federations: list[str],
        exclude_dids: list[str] | None = None,
    ) -> list[EligibleReviewer]:
        """Select reviewers for a challenge.

        Args:
            challenge: The challenge being reviewed
            eligible_pool: All potentially eligible reviewers
            belief_holder_did: DID of the belief holder
            belief_holder_federations: Federations the belief holder belongs to
            exclude_dids: Additional DIDs to exclude (e.g., challenger)

        Returns:
            List of selected reviewers

        Raises:
            InsufficientReviewersError: If not enough eligible reviewers
        """
        exclude_dids = exclude_dids or []
        exclude_dids.append(belief_holder_did)
        exclude_dids.append(challenge.challenger_did)

        # Determine required reviewer count
        required_count = self.config.get_appeal_reviewer_count(challenge.target_layer, challenge.appeal_round)

        # Filter for eligibility
        eligible = self._filter_eligible(
            eligible_pool,
            belief_holder_federations,
            exclude_dids,
        )

        if len(eligible) < required_count:
            raise InsufficientReviewersError(f"Need {required_count} reviewers but only {len(eligible)} eligible")

        # Select reviewers ensuring pairwise independence
        selected = self._select_independent_reviewers(
            eligible,
            required_count,
        )

        logger.info(
            f"Selected {len(selected)} reviewers for challenge {challenge.id} (layer={challenge.target_layer}, appeal_round={challenge.appeal_round})"
        )

        return selected

    def _filter_eligible(
        self,
        pool: list[EligibleReviewer],
        holder_federations: list[str],
        exclude_dids: list[str],
    ) -> list[EligibleReviewer]:
        """Filter pool to eligible reviewers."""
        eligible = []

        for candidate in pool:
            # Skip excluded DIDs
            if candidate.did in exclude_dids:
                continue

            # Check minimum reputation
            if candidate.reputation < self.config.min_reviewer_reputation:
                continue

            # Check account age
            if candidate.account_age_days < self.config.min_reviewer_age_days:
                continue

            # Check verification history
            if candidate.verification_count < self.config.min_verifications:
                continue

            # Check federation independence
            shared_federations = set(candidate.federations) & set(holder_federations)
            if len(shared_federations) > self.config.max_shared_federations:
                continue

            # Check reviewer accuracy (historical performance)
            if candidate.reviewer_accuracy < 0.5:
                continue

            eligible.append(candidate)

        return eligible

    def _select_independent_reviewers(
        self,
        eligible: list[EligibleReviewer],
        count: int,
    ) -> list[EligibleReviewer]:
        """Select reviewers ensuring pairwise independence."""
        selected: list[EligibleReviewer] = []

        # Shuffle to randomize (use cryptographically secure random)
        candidates = eligible.copy()
        secure_shuffle(candidates)

        for candidate in candidates:
            if len(selected) >= count:
                break

            # Check independence with already selected reviewers
            is_independent = True
            for existing in selected:
                independence = self._calculate_pairwise_independence(candidate, existing)
                if independence < self.config.min_independence_score:
                    is_independent = False
                    break

            if is_independent:
                selected.append(candidate)

        return selected

    def _calculate_pairwise_independence(
        self,
        a: EligibleReviewer,
        b: EligibleReviewer,
    ) -> float:
        """Calculate independence score between two reviewers.

        Returns a score from 0 (completely dependent) to 1 (fully independent).
        """
        # Federation overlap
        shared_federations = set(a.federations) & set(b.federations)
        total_federations = set(a.federations) | set(b.federations)
        if total_federations:
            federation_independence = 1.0 - len(shared_federations) / len(total_federations)
        else:
            federation_independence = 1.0

        # Domain overlap (some overlap is OK, even expected)
        shared_domains = set(a.domains) & set(b.domains)
        total_domains = set(a.domains) | set(b.domains)
        if total_domains:
            # Allow domain overlap, just weight it less
            domain_factor = 1.0 - 0.3 * (len(shared_domains) / len(total_domains))
        else:
            domain_factor = 1.0

        # Combined score (federation independence is more important)
        return 0.7 * federation_independence + 0.3 * domain_factor


def secure_shuffle(items: list) -> None:
    """Cryptographically secure shuffle in place."""
    for i in range(len(items) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        items[i], items[j] = items[j], items[i]


# =============================================================================
# CHALLENGE RESOLUTION
# =============================================================================


class ChallengeResolver:
    """Resolves challenges based on reviewer decisions."""

    def __init__(self, config: ReviewerConfig | None = None):
        self.config = config or DEFAULT_REVIEWER_CONFIG

    def resolve_challenge(
        self,
        challenge: Challenge,
        reviews: list[ChallengeReview],
    ) -> ChallengeResolution:
        """Resolve a challenge based on completed reviews.

        Args:
            challenge: The challenge to resolve
            reviews: All completed reviews

        Returns:
            ChallengeResolution with outcome and effects
        """
        # Count votes
        uphold_votes = sum(1 for r in reviews if r.decision == ReviewDecision.UPHOLD)
        reject_votes = sum(1 for r in reviews if r.decision == ReviewDecision.REJECT)
        abstain_votes = sum(1 for r in reviews if r.decision == ReviewDecision.ABSTAIN)
        total_reviewers = len(reviews)

        # Calculate threshold
        threshold = self.config.get_consensus_threshold(challenge.target_layer)
        voting_reviewers = total_reviewers - abstain_votes
        required_for_consensus = int(voting_reviewers * threshold)

        # Determine outcome
        if uphold_votes >= required_for_consensus:
            outcome = "upheld"
        elif reject_votes >= required_for_consensus:
            outcome = "rejected"
        else:
            outcome = "partial"  # No clear consensus

        # Calculate effects
        resolution = ChallengeResolution(
            outcome=outcome,
            uphold_votes=uphold_votes,
            reject_votes=reject_votes,
            abstain_votes=abstain_votes,
            total_reviewers=total_reviewers,
            resolved_by=[r.reviewer_did for r in reviews if r.decision],
        )

        if outcome == "upheld":
            resolution.belief_demoted = True
            resolution.challenger_reward = challenge.challenger_stake * 0.5
            resolution.belief_holder_penalty = challenge.challenger_stake * 0.25
            resolution.new_layer = self._demote_layer(challenge.target_layer)
            resolution.summary = f"Challenge upheld by {uphold_votes}/{voting_reviewers} reviewers"
        elif outcome == "rejected":
            resolution.challenger_penalty = challenge.challenger_stake * 0.5
            resolution.summary = f"Challenge rejected by {reject_votes}/{voting_reviewers} reviewers"
        else:
            resolution.summary = f"No consensus reached ({uphold_votes} uphold, {reject_votes} reject)"

        # Calculate reviewer penalties (those who voted against majority)
        majority_decision = ReviewDecision.UPHOLD if uphold_votes > reject_votes else ReviewDecision.REJECT
        for review in reviews:
            if review.decision and review.decision != majority_decision and review.decision != ReviewDecision.ABSTAIN:
                # Penalty proportional to stake
                resolution.reviewer_penalties[review.reviewer_did] = review.stake * 0.1

        return resolution

    def _demote_layer(self, layer: str) -> str:
        """Get the next lower layer."""
        layers = {"L4": "L3", "L3": "L2", "L2": "L1", "L1": "L1"}
        return layers.get(layer.upper(), "L1")


# =============================================================================
# APPEAL HANDLING
# =============================================================================


class AppealHandler:
    """Handles appeals of challenge resolutions."""

    def __init__(self, config: ReviewerConfig | None = None):
        self.config = config or DEFAULT_REVIEWER_CONFIG

    def can_appeal(self, challenge: Challenge) -> tuple[bool, str | None]:
        """Check if a challenge can be appealed.

        Args:
            challenge: The resolved challenge

        Returns:
            Tuple of (can_appeal, reason_if_not)
        """
        if challenge.status not in (ChallengeStatus.UPHELD, ChallengeStatus.REJECTED):
            return False, "Challenge must be resolved before appeal"

        if challenge.appeal_round >= self.config.max_appeal_rounds:
            return (
                False,
                f"Maximum appeal rounds ({self.config.max_appeal_rounds}) reached",
            )

        if challenge.resolved_at:
            deadline = challenge.resolved_at + timedelta(days=self.config.appeal_deadline_days)
            if datetime.now() > deadline:
                return False, "Appeal deadline has passed"

        return True, None

    def create_appeal(
        self,
        original_challenge: Challenge,
        appeal_reasoning: str,
    ) -> Challenge:
        """Create an appeal challenge.

        Args:
            original_challenge: The challenge being appealed
            appeal_reasoning: Reason for the appeal

        Returns:
            New challenge representing the appeal
        """
        can_appeal, reason = self.can_appeal(original_challenge)
        if not can_appeal:
            raise AppealNotAllowedError(reason or "Appeal not allowed")

        appeal = Challenge(
            id=uuid4(),
            target_belief_id=original_challenge.target_belief_id,
            target_layer=original_challenge.target_layer,
            challenger_did=original_challenge.challenger_did,
            challenger_stake=original_challenge.challenger_stake * 1.5,  # Higher stake for appeal
            challenge_type=original_challenge.challenge_type,
            reasoning=f"APPEAL: {appeal_reasoning}\n\nOriginal: {original_challenge.reasoning}",
            counter_evidence=original_challenge.counter_evidence,
            status=ChallengeStatus.APPEALED,
            appeal_round=original_challenge.appeal_round + 1,
            previous_challenge_id=original_challenge.id,
        )

        # Update original challenge status
        original_challenge.status = ChallengeStatus.APPEALED

        logger.info(f"Appeal created: {appeal.id} (round {appeal.appeal_round}) for challenge {original_challenge.id}")

        return appeal


# =============================================================================
# EXCEPTIONS
# =============================================================================


class ChallengeError(Exception):
    """Base exception for challenge errors."""

    pass


class InsufficientReviewersError(ChallengeError):
    """Not enough eligible reviewers available."""

    pass


class AppealNotAllowedError(ChallengeError):
    """Appeal is not allowed for this challenge."""

    pass


class InvalidChallengeError(ChallengeError):
    """The challenge is invalid."""

    pass


# =============================================================================
# VALIDATION
# =============================================================================


def validate_challenge(
    challenger_did: str,
    challenger_reputation: float,
    challenger_stake: float,
    target_layer: str,
    min_stake_by_layer: dict[str, float] | None = None,
) -> tuple[bool, str | None]:
    """Validate a challenge before creation.

    Args:
        challenger_did: The challenger's DID
        challenger_reputation: Challenger's current reputation
        challenger_stake: Amount of reputation staked
        target_layer: Layer of the target belief
        min_stake_by_layer: Minimum stake required by layer

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Default minimum stakes by layer
    if min_stake_by_layer is None:
        min_stake_by_layer = {
            "L1": 0.01,
            "L2": 0.02,
            "L3": 0.05,
            "L4": 0.10,
        }

    # Check minimum stake
    min_stake = min_stake_by_layer.get(target_layer.upper(), 0.01)
    if challenger_stake < min_stake:
        return False, f"Minimum stake for {target_layer} is {min_stake}"

    # Check challenger has enough reputation to stake
    if challenger_stake > challenger_reputation:
        return False, "Cannot stake more than current reputation"

    # Check minimum reputation to challenge high-level beliefs
    if target_layer.upper() in ("L3", "L4") and challenger_reputation < 0.3:
        return False, "Minimum 0.3 reputation required to challenge L3/L4 beliefs"

    return True, None
