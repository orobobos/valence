"""Tests for the Challenge and Reviewer System.

Tests the challenge resolution mechanism including:
- Configurable reviewer thresholds
- Random reviewer selection
- Reviewer independence verification
- Appeal mechanism
- Reviewer reputation tracking

Per THREAT-MODEL.md §1.4.3 requirements.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from valence.federation.challenges import (
    DEFAULT_REVIEWER_CONFIG,
    # Appeals
    AppealHandler,
    AppealNotAllowedError,
    # Data classes
    Challenge,
    ChallengeResolution,
    # Resolution
    ChallengeResolver,
    ChallengeReview,
    ChallengeStatus,
    # Enums
    ChallengeType,
    EligibleReviewer,
    # Exceptions
    InsufficientReviewersError,
    ReviewDecision,
    # Configuration
    ReviewerConfig,
    ReviewerReputation,
    # Selection
    ReviewerSelector,
    ReviewerStatus,
    secure_shuffle,
    # Validation
    validate_challenge,
)

# =============================================================================
# CONFIGURATION TESTS
# =============================================================================


class TestReviewerConfig:
    """Tests for ReviewerConfig."""

    def test_default_l3_l4_reviewer_count(self):
        """L3/L4 beliefs require 7 reviewers (per THREAT-MODEL.md §1.4.3)."""
        config = DEFAULT_REVIEWER_CONFIG

        assert config.get_reviewer_count("L3") == 7
        assert config.get_reviewer_count("L4") == 7

    def test_lower_layer_reviewer_count(self):
        """L1/L2 beliefs require fewer reviewers."""
        config = DEFAULT_REVIEWER_CONFIG

        assert config.get_reviewer_count("L1") == 3
        assert config.get_reviewer_count("L2") == 3

    def test_layer_case_insensitive(self):
        """Layer names should be case-insensitive."""
        config = ReviewerConfig()

        assert config.get_reviewer_count("l3") == config.get_reviewer_count("L3")
        assert config.get_reviewer_count("l4") == config.get_reviewer_count("L4")

    def test_consensus_thresholds(self):
        """Higher layers require higher consensus thresholds."""
        config = DEFAULT_REVIEWER_CONFIG

        # L1/L2: 2/3 (67%)
        assert config.get_consensus_threshold("L1") == 2 / 3
        assert config.get_consensus_threshold("L2") == 2 / 3

        # L3/L4: 3/4 (75%)
        assert config.get_consensus_threshold("L3") == 3 / 4
        assert config.get_consensus_threshold("L4") == 3 / 4

    def test_appeal_reviewer_count_increases(self):
        """Appeal rounds increase reviewer count."""
        config = ReviewerConfig(l3_reviewers=7, appeal_reviewer_multiplier=1.5)

        # First appeal: 7 * 1.5 = 10.5 -> 10
        assert config.get_appeal_reviewer_count("L3", 1) >= 10

        # Second appeal: 7 * 1.5^2 = 15.75 -> 15
        assert config.get_appeal_reviewer_count("L3", 2) >= 15

    def test_config_to_dict(self):
        """Config should serialize to dict."""
        config = ReviewerConfig()
        data = config.to_dict()

        assert "reviewer_counts" in data
        assert "consensus_thresholds" in data
        assert "appeal_settings" in data
        assert "eligibility" in data
        assert "independence" in data

    def test_custom_config(self):
        """Custom configuration should work."""
        config = ReviewerConfig(
            l3_reviewers=9,
            l4_reviewers=11,
            min_reviewer_reputation=0.5,
        )

        assert config.get_reviewer_count("L3") == 9
        assert config.get_reviewer_count("L4") == 11
        assert config.min_reviewer_reputation == 0.5


# =============================================================================
# CHALLENGE MODEL TESTS
# =============================================================================


class TestChallenge:
    """Tests for Challenge dataclass."""

    def test_challenge_creation(self):
        """Challenge should be created with required fields."""
        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L3",
            challenger_did="did:vkb:key:z6MkTest",
            challenger_stake=0.05,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="The claim is incorrect because...",
        )

        assert challenge.status == ChallengeStatus.OPEN
        assert challenge.appeal_round == 0
        assert challenge.review_deadline is not None

    def test_challenge_serialization(self):
        """Challenge should serialize to dict and back."""
        original = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L3",
            challenger_did="did:vkb:key:z6MkTest",
            challenger_stake=0.05,
            challenge_type=ChallengeType.EVIDENCE_QUALITY,
            reasoning="Evidence is weak",
            counter_evidence=[{"type": "url", "url": "https://example.com"}],
        )

        data = original.to_dict()
        restored = Challenge.from_dict(data)

        assert restored.id == original.id
        assert restored.target_layer == original.target_layer
        assert restored.challenge_type == original.challenge_type
        assert restored.counter_evidence == original.counter_evidence

    def test_challenge_types(self):
        """All challenge types should be valid."""
        types = [
            ChallengeType.FACTUAL_ERROR,
            ChallengeType.INDEPENDENCE_VIOLATION,
            ChallengeType.EVIDENCE_QUALITY,
            ChallengeType.OUTDATED,
            ChallengeType.METHODOLOGY,
            ChallengeType.SCOPE,
        ]

        for challenge_type in types:
            challenge = Challenge(
                id=uuid4(),
                target_belief_id=uuid4(),
                target_layer="L3",
                challenger_did="did:vkb:key:z6MkTest",
                challenger_stake=0.05,
                challenge_type=challenge_type,
                reasoning="Test reasoning",
            )
            assert challenge.challenge_type == challenge_type


class TestChallengeReview:
    """Tests for ChallengeReview dataclass."""

    def test_review_creation(self):
        """Review should be created with required fields."""
        review = ChallengeReview(
            id=uuid4(),
            challenge_id=uuid4(),
            reviewer_did="did:vkb:key:z6MkReviewer",
            reviewer_reputation=0.6,
        )

        assert review.status == ReviewerStatus.ASSIGNED
        assert review.decision is None

    def test_review_completion(self):
        """Review can be completed with decision."""
        review = ChallengeReview(
            id=uuid4(),
            challenge_id=uuid4(),
            reviewer_did="did:vkb:key:z6MkReviewer",
            reviewer_reputation=0.6,
            status=ReviewerStatus.COMPLETED,
            decision=ReviewDecision.UPHOLD,
            reasoning="The challenge is valid",
            confidence=0.9,
            completed_at=datetime.now(),
        )

        assert review.status == ReviewerStatus.COMPLETED
        assert review.decision == ReviewDecision.UPHOLD

    def test_review_serialization(self):
        """Review should serialize to dict and back."""
        original = ChallengeReview(
            id=uuid4(),
            challenge_id=uuid4(),
            reviewer_did="did:vkb:key:z6MkReviewer",
            reviewer_reputation=0.7,
            decision=ReviewDecision.REJECT,
            reasoning="Challenge is invalid",
        )

        data = original.to_dict()
        restored = ChallengeReview.from_dict(data)

        assert restored.id == original.id
        assert restored.decision == original.decision


# =============================================================================
# REVIEWER SELECTION TESTS
# =============================================================================


class TestReviewerSelector:
    """Tests for ReviewerSelector."""

    def create_eligible_pool(self, count: int = 20) -> list[EligibleReviewer]:
        """Create a pool of eligible reviewers with diverse federations."""
        return [
            EligibleReviewer(
                did=f"did:vkb:key:z6MkReviewer{i}",
                reputation=0.5 + (i * 0.02),
                account_age_days=60 + i,
                verification_count=20 + i,
                # Each reviewer in their own unique federation (for independence)
                federations=[f"federation_{i}"],
                domains=[f"domain_{i % 3}"],
                reviewer_accuracy=0.8,
            )
            for i in range(count)
        ]

    def test_selects_correct_count_l3(self):
        """Should select 7 reviewers for L3 beliefs."""
        selector = ReviewerSelector()
        pool = self.create_eligible_pool(20)

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L3",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.05,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
        )

        selected = selector.select_reviewers(
            challenge=challenge,
            eligible_pool=pool,
            belief_holder_did="did:vkb:key:z6MkHolder",
            belief_holder_federations=["federation_other"],
        )

        assert len(selected) == 7

    def test_selects_correct_count_l4(self):
        """Should select 7 reviewers for L4 beliefs."""
        selector = ReviewerSelector()
        pool = self.create_eligible_pool(20)

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L4",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.10,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
        )

        selected = selector.select_reviewers(
            challenge=challenge,
            eligible_pool=pool,
            belief_holder_did="did:vkb:key:z6MkHolder",
            belief_holder_federations=["federation_other"],
        )

        assert len(selected) == 7

    def test_excludes_belief_holder(self):
        """Belief holder cannot be a reviewer."""
        selector = ReviewerSelector()
        pool = self.create_eligible_pool(10)
        holder_did = pool[0].did  # First in pool is the holder

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L1",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.01,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
        )

        selected = selector.select_reviewers(
            challenge=challenge,
            eligible_pool=pool,
            belief_holder_did=holder_did,
            belief_holder_federations=[],
        )

        selected_dids = [r.did for r in selected]
        assert holder_did not in selected_dids

    def test_excludes_challenger(self):
        """Challenger cannot be a reviewer."""
        selector = ReviewerSelector()
        pool = self.create_eligible_pool(10)
        challenger_did = pool[1].did  # Second in pool is the challenger

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L1",
            challenger_did=challenger_did,
            challenger_stake=0.01,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
        )

        selected = selector.select_reviewers(
            challenge=challenge,
            eligible_pool=pool,
            belief_holder_did="did:vkb:key:z6MkHolder",
            belief_holder_federations=[],
        )

        selected_dids = [r.did for r in selected]
        assert challenger_did not in selected_dids

    def test_excludes_shared_federation_members(self):
        """Reviewers cannot share federations with belief holder."""
        selector = ReviewerSelector(ReviewerConfig(max_shared_federations=0))

        # All reviewers in federation_A
        pool = [
            EligibleReviewer(
                did=f"did:vkb:key:z6MkReviewer{i}",
                reputation=0.6,
                account_age_days=60,
                verification_count=20,
                federations=["federation_A"],
                domains=[],
            )
            for i in range(5)
        ]
        # Add some in different federation
        pool.extend(
            [
                EligibleReviewer(
                    did=f"did:vkb:key:z6MkReviewerIndep{i}",
                    reputation=0.6,
                    account_age_days=60,
                    verification_count=20,
                    federations=["federation_B"],
                    domains=[],
                )
                for i in range(5)
            ]
        )

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L1",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.01,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
        )

        selected = selector.select_reviewers(
            challenge=challenge,
            eligible_pool=pool,
            belief_holder_did="did:vkb:key:z6MkHolder",
            belief_holder_federations=["federation_A"],  # Holder in federation_A
        )

        # All selected should be from federation_B
        for reviewer in selected:
            assert "federation_A" not in reviewer.federations

    def test_insufficient_reviewers_raises(self):
        """Should raise if not enough eligible reviewers."""
        selector = ReviewerSelector()
        pool = self.create_eligible_pool(3)  # Only 3, need 7 for L3

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L3",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.05,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
        )

        with pytest.raises(InsufficientReviewersError):
            selector.select_reviewers(
                challenge=challenge,
                eligible_pool=pool,
                belief_holder_did="did:vkb:key:z6MkHolder",
                belief_holder_federations=[],
            )

    def test_random_selection(self):
        """Selection should be random (different each time)."""
        selector = ReviewerSelector()
        pool = self.create_eligible_pool(20)

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L1",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.01,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
        )

        # Run multiple selections
        selections = []
        for _ in range(5):
            selected = selector.select_reviewers(
                challenge=challenge,
                eligible_pool=pool,
                belief_holder_did="did:vkb:key:z6MkHolder",
                belief_holder_federations=[],
            )
            selections.append(tuple(r.did for r in selected))

        # At least some selections should differ (random)
        # Note: This could theoretically fail randomly, but probability is very low
        unique_selections = set(selections)
        assert len(unique_selections) > 1, "Selection should be randomized"

    def test_filters_low_reputation(self):
        """Should filter out reviewers below minimum reputation."""
        config = ReviewerConfig(min_reviewer_reputation=0.5)
        selector = ReviewerSelector(config)

        pool = [
            EligibleReviewer(
                did=f"did:vkb:key:z6MkLowRep{i}",
                reputation=0.3,  # Below threshold
                account_age_days=60,
                verification_count=20,
                federations=[],
                domains=[],
            )
            for i in range(5)
        ] + [
            EligibleReviewer(
                did=f"did:vkb:key:z6MkHighRep{i}",
                reputation=0.7,  # Above threshold
                account_age_days=60,
                verification_count=20,
                federations=[],
                domains=[],
            )
            for i in range(5)
        ]

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L1",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.01,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
        )

        selected = selector.select_reviewers(
            challenge=challenge,
            eligible_pool=pool,
            belief_holder_did="did:vkb:key:z6MkHolder",
            belief_holder_federations=[],
        )

        for reviewer in selected:
            assert reviewer.reputation >= 0.5


class TestSecureShuffle:
    """Tests for secure_shuffle function."""

    def test_shuffle_modifies_list(self):
        """Shuffle should modify the list in place."""
        items = list(range(100))
        original = items.copy()
        secure_shuffle(items)

        # Should be modified (very unlikely to be identical)
        assert items != original
        # Should contain same elements
        assert sorted(items) == sorted(original)

    def test_shuffle_empty_list(self):
        """Shuffle should handle empty list."""
        items: list = []
        secure_shuffle(items)
        assert items == []

    def test_shuffle_single_item(self):
        """Shuffle should handle single item list."""
        items = [1]
        secure_shuffle(items)
        assert items == [1]


# =============================================================================
# CHALLENGE RESOLUTION TESTS
# =============================================================================


class TestChallengeResolver:
    """Tests for ChallengeResolver."""

    def create_reviews(
        self,
        challenge_id: uuid4,
        uphold: int,
        reject: int,
        abstain: int = 0,
    ) -> list[ChallengeReview]:
        """Create a set of reviews with specified decisions."""
        reviews = []

        for i in range(uphold):
            reviews.append(
                ChallengeReview(
                    id=uuid4(),
                    challenge_id=challenge_id,
                    reviewer_did=f"did:vkb:key:z6MkUphold{i}",
                    reviewer_reputation=0.6,
                    status=ReviewerStatus.COMPLETED,
                    decision=ReviewDecision.UPHOLD,
                    stake=0.02,
                )
            )

        for i in range(reject):
            reviews.append(
                ChallengeReview(
                    id=uuid4(),
                    challenge_id=challenge_id,
                    reviewer_did=f"did:vkb:key:z6MkReject{i}",
                    reviewer_reputation=0.6,
                    status=ReviewerStatus.COMPLETED,
                    decision=ReviewDecision.REJECT,
                    stake=0.02,
                )
            )

        for i in range(abstain):
            reviews.append(
                ChallengeReview(
                    id=uuid4(),
                    challenge_id=challenge_id,
                    reviewer_did=f"did:vkb:key:z6MkAbstain{i}",
                    reviewer_reputation=0.6,
                    status=ReviewerStatus.COMPLETED,
                    decision=ReviewDecision.ABSTAIN,
                    stake=0.02,
                )
            )

        return reviews

    def test_upheld_challenge_l3(self):
        """L3 challenge should be upheld with 75% agreement (6/7)."""
        resolver = ChallengeResolver()

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L3",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.05,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
        )

        # 6 uphold, 1 reject -> 6/7 > 75%
        reviews = self.create_reviews(challenge.id, uphold=6, reject=1)

        resolution = resolver.resolve_challenge(challenge, reviews)

        assert resolution.outcome == "upheld"
        assert resolution.belief_demoted is True
        assert resolution.new_layer == "L2"
        assert resolution.challenger_reward > 0

    def test_rejected_challenge_l3(self):
        """L3 challenge should be rejected with 75% rejection (6/7)."""
        resolver = ChallengeResolver()

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L3",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.05,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
        )

        # 1 uphold, 6 reject -> 6/7 > 75%
        reviews = self.create_reviews(challenge.id, uphold=1, reject=6)

        resolution = resolver.resolve_challenge(challenge, reviews)

        assert resolution.outcome == "rejected"
        assert resolution.belief_demoted is False
        assert resolution.challenger_penalty > 0

    def test_no_consensus_l3(self):
        """L3 challenge with split vote should have no consensus."""
        resolver = ChallengeResolver()

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L3",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.05,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
        )

        # 4 uphold, 3 reject -> Neither reaches 75%
        reviews = self.create_reviews(challenge.id, uphold=4, reject=3)

        resolution = resolver.resolve_challenge(challenge, reviews)

        assert resolution.outcome == "partial"
        assert resolution.belief_demoted is False

    def test_upheld_challenge_l1(self):
        """L1 challenge should be upheld with 67% agreement (2/3)."""
        resolver = ChallengeResolver()

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L1",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.01,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
        )

        # 2 uphold, 1 reject -> 2/3 >= 67%
        reviews = self.create_reviews(challenge.id, uphold=2, reject=1)

        resolution = resolver.resolve_challenge(challenge, reviews)

        assert resolution.outcome == "upheld"

    def test_abstain_excluded_from_threshold(self):
        """Abstain votes should be excluded from consensus calculation."""
        resolver = ChallengeResolver()

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L1",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.01,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
        )

        # 2 uphold, 0 reject, 1 abstain -> 2/2 = 100% of voting reviewers
        reviews = self.create_reviews(challenge.id, uphold=2, reject=0, abstain=1)

        resolution = resolver.resolve_challenge(challenge, reviews)

        assert resolution.outcome == "upheld"

    def test_reviewer_penalties_for_minority(self):
        """Reviewers voting against majority should be penalized."""
        resolver = ChallengeResolver()

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L1",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.01,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
        )

        # 2 uphold, 1 reject -> minority (reject) should be penalized
        reviews = self.create_reviews(challenge.id, uphold=2, reject=1)

        resolution = resolver.resolve_challenge(challenge, reviews)

        # The rejecting reviewer should have a penalty
        assert len(resolution.reviewer_penalties) == 1
        assert "did:vkb:key:z6MkReject0" in resolution.reviewer_penalties

    def test_resolution_serialization(self):
        """Resolution should serialize to dict and back."""
        original = ChallengeResolution(
            outcome="upheld",
            uphold_votes=5,
            reject_votes=2,
            total_reviewers=7,
            belief_demoted=True,
            new_layer="L2",
            challenger_reward=0.025,
            reviewer_penalties={"did:test": 0.002},
            summary="Challenge upheld",
            resolved_by=["did:reviewer1", "did:reviewer2"],
        )

        data = original.to_dict()
        restored = ChallengeResolution.from_dict(data)

        assert restored.outcome == original.outcome
        assert restored.uphold_votes == original.uphold_votes
        assert restored.belief_demoted == original.belief_demoted


# =============================================================================
# APPEAL TESTS
# =============================================================================


class TestAppealHandler:
    """Tests for AppealHandler."""

    def test_can_appeal_upheld_challenge(self):
        """Upheld challenge can be appealed."""
        handler = AppealHandler()

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L3",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.05,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
            status=ChallengeStatus.UPHELD,
            resolved_at=datetime.now(),
        )

        can_appeal, reason = handler.can_appeal(challenge)

        assert can_appeal is True
        assert reason is None

    def test_can_appeal_rejected_challenge(self):
        """Rejected challenge can be appealed."""
        handler = AppealHandler()

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L3",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.05,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
            status=ChallengeStatus.REJECTED,
            resolved_at=datetime.now(),
        )

        can_appeal, reason = handler.can_appeal(challenge)

        assert can_appeal is True

    def test_cannot_appeal_open_challenge(self):
        """Open challenge cannot be appealed."""
        handler = AppealHandler()

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L3",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.05,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
            status=ChallengeStatus.OPEN,
        )

        can_appeal, reason = handler.can_appeal(challenge)

        assert can_appeal is False
        assert "resolved" in reason.lower()

    def test_cannot_exceed_max_appeals(self):
        """Cannot exceed maximum appeal rounds."""
        config = ReviewerConfig(max_appeal_rounds=2)
        handler = AppealHandler(config)

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L3",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.05,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
            status=ChallengeStatus.REJECTED,
            appeal_round=2,  # Already at max
            resolved_at=datetime.now(),
        )

        can_appeal, reason = handler.can_appeal(challenge)

        assert can_appeal is False
        assert "maximum" in reason.lower()

    def test_cannot_appeal_after_deadline(self):
        """Cannot appeal after deadline."""
        config = ReviewerConfig(appeal_deadline_days=14)
        handler = AppealHandler(config)

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L3",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.05,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
            status=ChallengeStatus.REJECTED,
            resolved_at=datetime.now() - timedelta(days=30),  # 30 days ago
        )

        can_appeal, reason = handler.can_appeal(challenge)

        assert can_appeal is False
        assert "deadline" in reason.lower()

    def test_create_appeal(self):
        """Appeal should create new challenge with incremented round."""
        handler = AppealHandler()

        original = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L3",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.05,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Original reasoning",
            status=ChallengeStatus.REJECTED,
            resolved_at=datetime.now(),
        )

        appeal = handler.create_appeal(original, "I disagree with the decision")

        assert appeal.appeal_round == 1
        assert appeal.previous_challenge_id == original.id
        assert appeal.challenger_stake > original.challenger_stake  # Higher stake
        assert "APPEAL" in appeal.reasoning

    def test_create_appeal_raises_if_not_allowed(self):
        """Creating appeal should raise if not allowed."""
        handler = AppealHandler()

        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L3",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.05,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Test",
            status=ChallengeStatus.OPEN,  # Not resolved
        )

        with pytest.raises(AppealNotAllowedError):
            handler.create_appeal(challenge, "Appeal reasoning")


# =============================================================================
# REVIEWER REPUTATION TESTS
# =============================================================================


class TestReviewerReputation:
    """Tests for ReviewerReputation tracking."""

    def test_initial_reputation(self):
        """New reviewer should have perfect accuracy."""
        rep = ReviewerReputation(reviewer_did="did:vkb:key:z6MkReviewer")

        assert rep.accuracy_rate == 1.0
        assert rep.is_eligible is True

    def test_record_upheld_review(self):
        """Recording upheld review should increase count."""
        rep = ReviewerReputation(reviewer_did="did:vkb:key:z6MkReviewer")

        rep.record_review_outcome(was_upheld=True)

        assert rep.total_reviews == 1
        assert rep.reviews_upheld == 1
        assert rep.accuracy_rate == 1.0

    def test_record_overturned_review(self):
        """Recording overturned review should decrease accuracy."""
        rep = ReviewerReputation(reviewer_did="did:vkb:key:z6MkReviewer")

        rep.record_review_outcome(was_upheld=True)
        rep.record_review_outcome(was_upheld=False)

        assert rep.total_reviews == 2
        assert rep.reviews_upheld == 1
        assert rep.reviews_overturned == 1
        assert rep.accuracy_rate == 0.5

    def test_domain_accuracy_tracking(self):
        """Domain-specific accuracy should be tracked."""
        rep = ReviewerReputation(reviewer_did="did:vkb:key:z6MkReviewer")

        rep.record_review_outcome(was_upheld=True, domain="physics")
        rep.record_review_outcome(was_upheld=True, domain="physics")
        rep.record_review_outcome(was_upheld=False, domain="chemistry")

        assert "physics" in rep.domains
        assert "chemistry" in rep.domains
        assert rep.domain_accuracy.get("physics", 0) == 1.0
        assert rep.domain_accuracy.get("chemistry", 0) == 0.0

    def test_suspension_for_low_accuracy(self):
        """Reviewer with consistently poor accuracy should be suspended."""
        rep = ReviewerReputation(reviewer_did="did:vkb:key:z6MkReviewer")

        # 3 upheld, 7 overturned -> 30% accuracy, below 50% threshold
        for _ in range(3):
            rep.record_review_outcome(was_upheld=True)
        for _ in range(7):
            rep.record_review_outcome(was_upheld=False)

        assert rep.is_eligible is False
        assert rep.ineligible_reason is not None
        assert rep.ineligible_until is not None

    def test_serialization(self):
        """Reputation should serialize to dict."""
        rep = ReviewerReputation(
            reviewer_did="did:vkb:key:z6MkReviewer",
            total_reviews=10,
            reviews_upheld=8,
            reviews_overturned=2,
        )
        rep.update_accuracy()

        data = rep.to_dict()

        assert data["reviewer_did"] == rep.reviewer_did
        assert data["stats"]["accuracy_rate"] == 0.8


# =============================================================================
# VALIDATION TESTS
# =============================================================================


class TestValidateChallenge:
    """Tests for challenge validation."""

    def test_valid_l1_challenge(self):
        """Valid L1 challenge should pass."""
        is_valid, error = validate_challenge(
            challenger_did="did:vkb:key:z6MkTest",
            challenger_reputation=0.3,
            challenger_stake=0.01,
            target_layer="L1",
        )

        assert is_valid is True
        assert error is None

    def test_insufficient_stake(self):
        """Challenge with insufficient stake should fail."""
        is_valid, error = validate_challenge(
            challenger_did="did:vkb:key:z6MkTest",
            challenger_reputation=0.5,
            challenger_stake=0.001,  # Below minimum for L3
            target_layer="L3",
        )

        assert is_valid is False
        assert "stake" in error.lower()

    def test_stake_exceeds_reputation(self):
        """Cannot stake more than current reputation."""
        is_valid, error = validate_challenge(
            challenger_did="did:vkb:key:z6MkTest",
            challenger_reputation=0.02,
            challenger_stake=0.05,  # More than reputation
            target_layer="L1",
        )

        assert is_valid is False
        assert "reputation" in error.lower()

    def test_l3_requires_minimum_reputation(self):
        """L3 challenge requires minimum reputation."""
        is_valid, error = validate_challenge(
            challenger_did="did:vkb:key:z6MkTest",
            challenger_reputation=0.2,  # Below 0.3 minimum
            challenger_stake=0.05,
            target_layer="L3",
        )

        assert is_valid is False
        assert "0.3" in error

    def test_l4_requires_minimum_reputation(self):
        """L4 challenge requires minimum reputation."""
        is_valid, error = validate_challenge(
            challenger_did="did:vkb:key:z6MkTest",
            challenger_reputation=0.2,  # Below 0.3 minimum
            challenger_stake=0.10,
            target_layer="L4",
        )

        assert is_valid is False

    def test_custom_min_stakes(self):
        """Custom minimum stakes should be respected."""
        custom_stakes = {"L1": 0.05, "L2": 0.10}

        is_valid, error = validate_challenge(
            challenger_did="did:vkb:key:z6MkTest",
            challenger_reputation=0.5,
            challenger_stake=0.03,  # Below custom minimum
            target_layer="L1",
            min_stake_by_layer=custom_stakes,
        )

        assert is_valid is False
        assert "0.05" in error


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestChallengeIntegration:
    """Integration tests for the full challenge flow."""

    def test_full_challenge_flow_upheld(self):
        """Test complete challenge flow resulting in upheld challenge."""
        config = ReviewerConfig()
        selector = ReviewerSelector(config)
        resolver = ChallengeResolver(config)

        # Create challenge
        challenge = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L3",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.05,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="The claim contradicts established evidence",
        )

        # Validate
        is_valid, _ = validate_challenge(
            challenger_did=challenge.challenger_did,
            challenger_reputation=0.5,
            challenger_stake=challenge.challenger_stake,
            target_layer=challenge.target_layer,
        )
        assert is_valid

        # Create eligible pool
        pool = [
            EligibleReviewer(
                did=f"did:vkb:key:z6MkReviewer{i}",
                reputation=0.6,
                account_age_days=60,
                verification_count=20,
                federations=[f"federation_{i}"],  # All different federations
                domains=["science"],
            )
            for i in range(15)
        ]

        # Select reviewers
        selected = selector.select_reviewers(
            challenge=challenge,
            eligible_pool=pool,
            belief_holder_did="did:vkb:key:z6MkHolder",
            belief_holder_federations=["federation_other"],
        )
        assert len(selected) == 7

        # Create reviews (6 uphold, 1 reject)
        reviews = [
            ChallengeReview(
                id=uuid4(),
                challenge_id=challenge.id,
                reviewer_did=r.did,
                reviewer_reputation=r.reputation,
                status=ReviewerStatus.COMPLETED,
                decision=ReviewDecision.UPHOLD if i < 6 else ReviewDecision.REJECT,
                stake=0.02,
            )
            for i, r in enumerate(selected)
        ]

        # Resolve
        resolution = resolver.resolve_challenge(challenge, reviews)

        assert resolution.outcome == "upheld"
        assert resolution.uphold_votes == 6
        assert resolution.reject_votes == 1
        assert resolution.belief_demoted is True
        assert resolution.new_layer == "L2"

    def test_full_appeal_flow(self):
        """Test complete appeal flow."""
        config = ReviewerConfig()
        handler = AppealHandler(config)

        # Original challenge was rejected
        original = Challenge(
            id=uuid4(),
            target_belief_id=uuid4(),
            target_layer="L3",
            challenger_did="did:vkb:key:z6MkChallenger",
            challenger_stake=0.05,
            challenge_type=ChallengeType.FACTUAL_ERROR,
            reasoning="Original challenge",
            status=ChallengeStatus.REJECTED,
            resolution=ChallengeResolution(
                outcome="rejected",
                reject_votes=5,
                uphold_votes=2,
                total_reviewers=7,
            ),
            resolved_at=datetime.now(),
        )

        # Create appeal
        appeal = handler.create_appeal(
            original, "New evidence has emerged that supports my challenge"
        )

        assert appeal.appeal_round == 1
        assert appeal.previous_challenge_id == original.id
        assert original.status == ChallengeStatus.APPEALED

        # Appeal requires more reviewers (1.5x = 10.5 -> 10)
        required = config.get_appeal_reviewer_count("L3", 1)
        assert required >= 10
