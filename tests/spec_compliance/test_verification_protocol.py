"""
Spec Compliance Tests: Verification Protocol

Verifies the codebase implements the verification protocol per
spec/components/verification-protocol/SPEC.md.

Key requirements:
- Verification model with result, evidence, stake
- VerificationResult enum: CONFIRMED, CONTRADICTED, UNCERTAIN, PARTIAL
- VerificationStatus enum: PENDING, ACCEPTED, DISPUTED, OVERTURNED, REJECTED, EXPIRED
- Evidence types: BELIEF, EXTERNAL, OBSERVATION, DERIVATION, TESTIMONY
- EvidenceContribution: SUPPORTS, CONTRADICTS, CONTEXT, QUALIFIES
- ResultDetails with per-result fields
- ContradictionType and UncertaintyReason enums
- Dispute lifecycle: DisputeType, DisputeOutcome, DisputeStatus, ResolutionMethod
- Stake model and minimum stake calculation
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from valence.core.verification.enums import (
    ContradictionType,
    DisputeOutcome,
    DisputeStatus,
    DisputeType,
    EvidenceContribution,
    EvidenceType,
    ResolutionMethod,
    StakeType,
    UncertaintyReason,
    VerificationResult,
    VerificationStatus,
)
from valence.core.verification.evidence import Evidence, create_evidence
from valence.core.verification.models import (
    BeliefReference,
    DerivationProof,
    ExternalSource,
    Observation,
)
from valence.core.verification.results import ResultDetails, Stake
from valence.core.verification.verification import (
    Dispute,
    Verification,
    VerificationService,
    calculate_bounty,
    calculate_confirmation_reward,
    calculate_contradiction_reward,
    calculate_min_stake,
    validate_evidence_requirements,
)


# ============================================================================
# Verification Result Enum Tests
# ============================================================================


class TestVerificationResultEnum:
    """Test VerificationResult matches spec Section 1.2."""

    def test_has_confirmed(self):
        assert VerificationResult.CONFIRMED.value == "confirmed"

    def test_has_contradicted(self):
        assert VerificationResult.CONTRADICTED.value == "contradicted"

    def test_has_uncertain(self):
        assert VerificationResult.UNCERTAIN.value == "uncertain"

    def test_has_partial(self):
        assert VerificationResult.PARTIAL.value == "partial"

    def test_exactly_four_results(self):
        assert len(VerificationResult) == 4


# ============================================================================
# Verification Status Enum Tests
# ============================================================================


class TestVerificationStatusEnum:
    """Test VerificationStatus matches spec Section 4.1 state machine."""

    def test_has_pending(self):
        assert VerificationStatus.PENDING.value == "pending"

    def test_has_accepted(self):
        assert VerificationStatus.ACCEPTED.value == "accepted"

    def test_has_disputed(self):
        assert VerificationStatus.DISPUTED.value == "disputed"

    def test_has_overturned(self):
        assert VerificationStatus.OVERTURNED.value == "overturned"

    def test_has_rejected(self):
        assert VerificationStatus.REJECTED.value == "rejected"

    def test_has_expired(self):
        assert VerificationStatus.EXPIRED.value == "expired"


# ============================================================================
# Evidence Type Enum Tests
# ============================================================================


class TestEvidenceTypeEnum:
    """Test EvidenceType matches spec Section 2.1."""

    def test_has_belief(self):
        assert EvidenceType.BELIEF.value == "belief"

    def test_has_external(self):
        assert EvidenceType.EXTERNAL.value == "external"

    def test_has_observation(self):
        assert EvidenceType.OBSERVATION.value == "observation"

    def test_has_derivation(self):
        assert EvidenceType.DERIVATION.value == "derivation"

    def test_has_testimony(self):
        assert EvidenceType.TESTIMONY.value == "testimony"

    def test_exactly_five_types(self):
        assert len(EvidenceType) == 5


class TestEvidenceContributionEnum:
    """Test EvidenceContribution matches spec Section 2.1."""

    def test_has_supports(self):
        assert EvidenceContribution.SUPPORTS.value == "supports"

    def test_has_contradicts(self):
        assert EvidenceContribution.CONTRADICTS.value == "contradicts"

    def test_has_context(self):
        assert EvidenceContribution.CONTEXT.value == "context"

    def test_has_qualifies(self):
        assert EvidenceContribution.QUALIFIES.value == "qualifies"


# ============================================================================
# ContradictionType and UncertaintyReason Tests
# ============================================================================


class TestContradictionTypeEnum:
    """Test ContradictionType matches spec Section 1.3."""

    def test_has_factually_false(self):
        assert ContradictionType.FACTUALLY_FALSE.value == "factually_false"

    def test_has_outdated(self):
        assert ContradictionType.OUTDATED.value == "outdated"

    def test_has_misattributed(self):
        assert ContradictionType.MISATTRIBUTED.value == "misattributed"

    def test_has_overstated(self):
        assert ContradictionType.OVERSTATED.value == "overstated"

    def test_has_missing_context(self):
        assert ContradictionType.MISSING_CONTEXT.value == "missing_context"

    def test_has_logical_error(self):
        assert ContradictionType.LOGICAL_ERROR.value == "logical_error"

    def test_exactly_six_types(self):
        assert len(ContradictionType) == 6


class TestUncertaintyReasonEnum:
    """Test UncertaintyReason matches spec Section 1.3."""

    def test_has_insufficient_evidence(self):
        assert UncertaintyReason.INSUFFICIENT_EVIDENCE.value == "insufficient_evidence"

    def test_has_conflicting_sources(self):
        assert UncertaintyReason.CONFLICTING_SOURCES.value == "conflicting_sources"

    def test_has_outside_expertise(self):
        assert UncertaintyReason.OUTSIDE_EXPERTISE.value == "outside_expertise"

    def test_has_unfalsifiable(self):
        assert UncertaintyReason.UNFALSIFIABLE.value == "unfalsifiable"

    def test_has_requires_experiment(self):
        assert UncertaintyReason.REQUIRES_EXPERIMENT.value == "requires_experiment"


# ============================================================================
# Dispute Lifecycle Enum Tests
# ============================================================================


class TestDisputeEnums:
    """Test dispute lifecycle enums match spec Section 4."""

    def test_dispute_type_values(self):
        expected = {
            "evidence_invalid", "evidence_fabricated", "evidence_insufficient",
            "reasoning_flawed", "conflict_of_interest", "new_evidence",
        }
        actual = {dt.value for dt in DisputeType}
        assert actual == expected

    def test_dispute_outcome_values(self):
        expected = {"upheld", "overturned", "modified", "dismissed"}
        actual = {do.value for do in DisputeOutcome}
        assert actual == expected

    def test_dispute_status_values(self):
        expected = {"pending", "resolved", "expired"}
        actual = {ds.value for ds in DisputeStatus}
        assert actual == expected

    def test_resolution_method_values(self):
        expected = {"automatic", "jury", "expert", "appeal"}
        actual = {rm.value for rm in ResolutionMethod}
        assert actual == expected


# ============================================================================
# ResultDetails Model Tests
# ============================================================================


class TestResultDetails:
    """Test ResultDetails matches spec Section 1.3."""

    def test_confirmation_fields(self):
        """CONFIRMED has confirmation_strength and confirmed_aspects."""
        rd = ResultDetails(confirmation_strength="strong", confirmed_aspects=["fact A"])
        assert rd.confirmation_strength == "strong"
        assert rd.confirmed_aspects == ["fact A"]

    def test_contradiction_fields(self):
        """CONTRADICTED has contradiction_type, corrected_belief, severity."""
        rd = ResultDetails(
            contradiction_type=ContradictionType.FACTUALLY_FALSE,
            corrected_belief="The correct statement is...",
            severity="major",
        )
        assert rd.contradiction_type == ContradictionType.FACTUALLY_FALSE
        assert rd.corrected_belief is not None
        assert rd.severity == "major"

    def test_partial_fields(self):
        """PARTIAL has accurate_portions, inaccurate_portions, accuracy_estimate."""
        rd = ResultDetails(
            accurate_portions=["Part A"],
            inaccurate_portions=["Part B"],
            accuracy_estimate=0.7,
        )
        assert rd.accuracy_estimate == 0.7
        assert len(rd.accurate_portions) == 1
        assert len(rd.inaccurate_portions) == 1

    def test_uncertain_fields(self):
        """UNCERTAIN has uncertainty_reason and additional_evidence_needed."""
        rd = ResultDetails(
            uncertainty_reason=UncertaintyReason.INSUFFICIENT_EVIDENCE,
            additional_evidence_needed=["Primary source needed"],
        )
        assert rd.uncertainty_reason == UncertaintyReason.INSUFFICIENT_EVIDENCE
        assert len(rd.additional_evidence_needed) == 1

    def test_roundtrip_serialization(self):
        """to_dict/from_dict roundtrip preserves data."""
        rd = ResultDetails(
            contradiction_type=ContradictionType.OUTDATED,
            severity="minor",
        )
        restored = ResultDetails.from_dict(rd.to_dict())
        assert restored.contradiction_type == ContradictionType.OUTDATED
        assert restored.severity == "minor"


# ============================================================================
# Evidence Model Tests
# ============================================================================


class TestEvidenceModel:
    """Test Evidence model matches spec Section 2.1."""

    def test_evidence_has_required_fields(self):
        """Evidence must have id, type, relevance, contribution."""
        e = Evidence(
            id=uuid4(),
            type=EvidenceType.EXTERNAL,
            relevance=0.8,
            contribution=EvidenceContribution.SUPPORTS,
        )
        assert e.id is not None
        assert e.type == EvidenceType.EXTERNAL
        assert e.relevance == 0.8
        assert e.contribution == EvidenceContribution.SUPPORTS

    def test_evidence_relevance_validation(self):
        """Relevance must be in [0.0, 1.0]."""
        with pytest.raises(Exception):
            Evidence(id=uuid4(), type=EvidenceType.EXTERNAL, relevance=1.5, contribution=EvidenceContribution.SUPPORTS)

    def test_external_source_model(self):
        """ExternalSource has url, doi, isbn, citation fields per spec."""
        es = ExternalSource(url="https://example.com", doi="10.1234/test", source_reputation=0.9)
        assert es.url == "https://example.com"
        assert es.doi == "10.1234/test"
        assert es.source_reputation == 0.9

    def test_belief_reference_model(self):
        """BeliefReference has belief_id, holder_id, content_hash."""
        br = BeliefReference(belief_id=uuid4(), holder_id="did:example:123", content_hash="abc123")
        assert br.holder_id == "did:example:123"

    def test_observation_model(self):
        """Observation has description, timestamp, method, reproducible."""
        obs = Observation(description="Saw X", timestamp=datetime.now(), method="visual", reproducible=True)
        assert obs.reproducible is True

    def test_derivation_proof_model(self):
        """DerivationProof has premises, logic_type, proof_steps."""
        dp = DerivationProof(premises=[uuid4()], logic_type="deductive", proof_steps=["Step 1"])
        assert dp.logic_type == "deductive"

    def test_create_evidence_helper(self):
        """create_evidence convenience function works."""
        e = create_evidence(EvidenceType.EXTERNAL, EvidenceContribution.SUPPORTS, url="https://example.com")
        assert e.type == EvidenceType.EXTERNAL
        assert e.external_source is not None


# ============================================================================
# Evidence Requirements Validation Tests
# ============================================================================


class TestEvidenceRequirements:
    """Test evidence requirements per spec Section 2.3."""

    def test_confirmed_requires_supporting_evidence(self):
        """CONFIRMED: minimum 1 supporting evidence."""
        errors = validate_evidence_requirements(VerificationResult.CONFIRMED, [])
        assert any("supporting" in e.lower() for e in errors)

    def test_contradicted_requires_contradicting_evidence(self):
        """CONTRADICTED: minimum 1 contradicting evidence."""
        errors = validate_evidence_requirements(VerificationResult.CONTRADICTED, [])
        assert any("contradicting" in e.lower() for e in errors)

    def test_partial_requires_both(self):
        """PARTIAL: 1 supporting + 1 contradicting."""
        errors = validate_evidence_requirements(VerificationResult.PARTIAL, [])
        assert len(errors) >= 2

    def test_uncertain_no_minimum(self):
        """UNCERTAIN: no minimum evidence (but must explain why)."""
        errors = validate_evidence_requirements(VerificationResult.UNCERTAIN, [])
        assert len(errors) == 0


# ============================================================================
# Stake Model Tests
# ============================================================================


class TestStakeModel:
    """Test Stake matches spec Section 3."""

    def test_stake_has_required_fields(self):
        """Stake has amount, type, locked_until, escrow_id."""
        s = Stake(amount=0.05, type=StakeType.STANDARD, locked_until=datetime.now(), escrow_id=uuid4())
        assert s.amount == 0.05
        assert s.type == StakeType.STANDARD

    def test_stake_type_enum(self):
        """StakeType: STANDARD, BOUNTY, CHALLENGE."""
        assert StakeType.STANDARD.value == "standard"
        assert StakeType.BOUNTY.value == "bounty"
        assert StakeType.CHALLENGE.value == "challenge"

    def test_negative_stake_rejected(self):
        """Stake amount cannot be negative."""
        with pytest.raises(Exception):
            Stake(amount=-0.01, type=StakeType.STANDARD, locked_until=datetime.now(), escrow_id=uuid4())

    def test_min_stake_calculation(self):
        """Min stake = base_stake * confidence_multiplier * domain_multiplier."""
        result = calculate_min_stake(belief_confidence=0.8, verifier_domain_reputation=0.5)
        expected = 0.01 * 0.8 * (1.0 + 0.5 * 0.5)
        assert abs(result - expected) < 0.0001
