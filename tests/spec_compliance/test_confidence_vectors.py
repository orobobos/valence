"""
Spec Compliance Tests: Confidence Vectors

Verifies the codebase implements the confidence vector system per
spec/components/confidence-vectors/SPEC.md.

Key requirements:
- Six orthogonal dimensions, each scored 0.0-1.0
- Weighted geometric mean for aggregation (per MATH.md)
- Default values for new beliefs
- DimensionalConfidence class with all dimensions
- ConfidenceDimension enum with all six dimensions
- Values clamped to [0.0, 1.0]
"""

from __future__ import annotations

import math

import pytest

from our_confidence import (
    DEFAULT_WEIGHTS,
    ConfidenceDimension,
    DimensionalConfidence,
    aggregate_confidence,
    confidence_label,
)
from our_confidence.confidence import CORE_DIMENSIONS, EPSILON, _compute_overall


# ============================================================================
# Dimension Enum Tests
# ============================================================================


class TestConfidenceDimensionEnum:
    """Test ConfidenceDimension enum matches spec Section 1.2."""

    SPEC_DIMENSIONS = [
        "source_reliability",
        "method_quality",
        "internal_consistency",
        "temporal_freshness",
        "corroboration",
        "domain_applicability",
    ]

    def test_has_all_six_dimensions(self):
        """Spec requires exactly six orthogonal confidence dimensions."""
        for dim_name in self.SPEC_DIMENSIONS:
            assert hasattr(ConfidenceDimension, dim_name.upper()), (
                f"ConfidenceDimension missing spec dimension: {dim_name}"
            )

    def test_has_overall_dimension(self):
        """Overall confidence aggregation must be accessible."""
        assert hasattr(ConfidenceDimension, "OVERALL")
        assert ConfidenceDimension.OVERALL.value == "overall"

    def test_core_dimensions_excludes_overall(self):
        """CORE_DIMENSIONS should be the six dimensions without overall."""
        core_values = [d.value for d in CORE_DIMENSIONS]
        assert len(core_values) == 6
        assert "overall" not in core_values
        for dim_name in self.SPEC_DIMENSIONS:
            assert dim_name in core_values

    def test_dimension_values_are_string_names(self):
        """Enum values should be the lowercase dimension names."""
        assert ConfidenceDimension.SOURCE_RELIABILITY.value == "source_reliability"
        assert ConfidenceDimension.METHOD_QUALITY.value == "method_quality"
        assert ConfidenceDimension.INTERNAL_CONSISTENCY.value == "internal_consistency"
        assert ConfidenceDimension.TEMPORAL_FRESHNESS.value == "temporal_freshness"
        assert ConfidenceDimension.CORROBORATION.value == "corroboration"
        assert ConfidenceDimension.DOMAIN_APPLICABILITY.value == "domain_applicability"


# ============================================================================
# DimensionalConfidence Model Tests
# ============================================================================


class TestDimensionalConfidenceModel:
    """Test DimensionalConfidence class matches spec."""

    def test_has_overall_attribute(self):
        """Must have overall confidence score."""
        dc = DimensionalConfidence(overall=0.7)
        assert dc.overall == 0.7

    def test_has_all_six_dimension_properties(self):
        """Must have properties for all six spec dimensions."""
        dc = DimensionalConfidence.full(
            source_reliability=0.8,
            method_quality=0.7,
            internal_consistency=0.9,
            temporal_freshness=1.0,
            corroboration=0.5,
            domain_applicability=0.6,
        )
        assert dc.source_reliability == 0.8
        assert dc.method_quality == 0.7
        assert dc.internal_consistency == 0.9
        assert dc.temporal_freshness == 1.0
        assert dc.corroboration == 0.5
        assert dc.domain_applicability == 0.6

    def test_values_clamped_to_unit_range(self):
        """Spec: All dimensions in [0.0, 1.0]. Values outside clamped."""
        with pytest.raises(ValueError):
            DimensionalConfidence(overall=1.5)
        with pytest.raises(ValueError):
            DimensionalConfidence(overall=-0.1)

    def test_dimension_values_validated(self):
        """Individual dimensions must be in [0.0, 1.0]."""
        with pytest.raises(ValueError):
            DimensionalConfidence(overall=0.5, source_reliability=1.5)
        with pytest.raises(ValueError):
            DimensionalConfidence(overall=0.5, corroboration=-0.1)

    def test_simple_factory_creates_overall_only(self):
        """simple() creates confidence with just overall score."""
        dc = DimensionalConfidence.simple(0.8)
        assert dc.overall == 0.8
        assert dc.source_reliability is None

    def test_full_factory_calculates_overall(self):
        """full() creates confidence with all dimensions and computes overall."""
        dc = DimensionalConfidence.full(
            source_reliability=0.8,
            method_quality=0.7,
            internal_consistency=0.9,
            temporal_freshness=1.0,
            corroboration=0.5,
            domain_applicability=0.6,
        )
        # Overall should be computed (not the default 0.7)
        assert 0.0 <= dc.overall <= 1.0
        # All dimensions should be set
        assert len(dc.dimensions) == 6

    def test_from_dict_roundtrip(self):
        """to_dict/from_dict must preserve all data."""
        original = DimensionalConfidence.full(
            source_reliability=0.8,
            method_quality=0.7,
            internal_consistency=0.9,
            temporal_freshness=1.0,
            corroboration=0.5,
            domain_applicability=0.6,
        )
        restored = DimensionalConfidence.from_dict(original.to_dict())
        assert abs(original.overall - restored.overall) < 0.001
        for dim in CORE_DIMENSIONS:
            assert original.dimensions.get(dim.value) == restored.dimensions.get(dim.value)

    def test_decay_reduces_temporal_freshness(self):
        """Spec: temporal_freshness decays over time."""
        dc = DimensionalConfidence.full(
            source_reliability=0.8,
            method_quality=0.7,
            internal_consistency=0.9,
            temporal_freshness=1.0,
            corroboration=0.5,
            domain_applicability=0.6,
        )
        decayed = dc.decay(factor=0.9)
        assert decayed.temporal_freshness < dc.temporal_freshness

    def test_boost_corroboration_increases_value(self):
        """Spec: corroboration increases when additional sources agree."""
        dc = DimensionalConfidence(overall=0.7, corroboration=0.3)
        boosted = dc.boost_corroboration(amount=0.2)
        assert boosted.corroboration == pytest.approx(0.5, abs=0.01)


# ============================================================================
# Aggregation Tests
# ============================================================================


class TestConfidenceAggregation:
    """Test confidence aggregation per spec MATH.md."""

    def test_geometric_mean_penalizes_low_dimension(self):
        """Spec: geometric mean ensures single low score impacts overall significantly."""
        # All high except one low
        imbalanced = DimensionalConfidence.full(
            source_reliability=0.9,
            method_quality=0.9,
            internal_consistency=0.9,
            temporal_freshness=0.9,
            corroboration=0.01,  # Extremely low
            domain_applicability=0.9,
        )
        # All medium-high
        balanced = DimensionalConfidence.full(
            source_reliability=0.7,
            method_quality=0.7,
            internal_consistency=0.7,
            temporal_freshness=0.7,
            corroboration=0.7,
            domain_applicability=0.7,
        )
        # Geometric mean should penalize the imbalanced case:
        # even one very low dimension drags down the overall score
        assert imbalanced.overall < balanced.overall

    def test_compute_overall_uses_weighted_geometric_mean(self):
        """Spec: overall_confidence = weighted geometric mean of all dimensions."""
        dims = {
            "source_reliability": 0.8,
            "method_quality": 0.7,
            "internal_consistency": 0.9,
            "temporal_freshness": 1.0,
            "corroboration": 0.5,
            "domain_applicability": 0.6,
        }
        result = _compute_overall(dims, use_geometric=True)
        assert 0.0 <= result <= 1.0
        # Geometric mean should be less than arithmetic mean for these values
        arith_result = _compute_overall(dims, use_geometric=False)
        assert result <= arith_result + 0.01  # Small tolerance

    def test_default_weights_sum_to_one(self):
        """Spec default weights should sum to approximately 1.0."""
        total = sum(DEFAULT_WEIGHTS.values())
        assert abs(total - 1.0) < 0.01, f"Default weights sum to {total}, expected ~1.0"

    def test_default_weights_match_spec(self):
        """Spec: Default weights [0.25, 0.20/0.15, 0.15, 0.15, 0.15, 0.10]."""
        assert DEFAULT_WEIGHTS[ConfidenceDimension.SOURCE_RELIABILITY] == 0.25
        assert DEFAULT_WEIGHTS[ConfidenceDimension.DOMAIN_APPLICABILITY] == 0.10
        # Remaining dimensions get 0.15-0.20
        for dim in CORE_DIMENSIONS:
            assert DEFAULT_WEIGHTS[dim] >= 0.10
            assert DEFAULT_WEIGHTS[dim] <= 0.25

    def test_aggregate_confidence_exists(self):
        """aggregate_confidence function must exist for combining multiple confidences."""
        assert callable(aggregate_confidence)

    def test_aggregate_confidence_geometric_method(self):
        """Geometric aggregation should produce valid result."""
        c1 = DimensionalConfidence.full(0.8, 0.7, 0.9, 1.0, 0.5, 0.6)
        c2 = DimensionalConfidence.full(0.7, 0.8, 0.8, 0.9, 0.6, 0.7)
        result = aggregate_confidence([c1, c2], method="geometric")
        assert 0.0 <= result.overall <= 1.0

    def test_confidence_label_function(self):
        """confidence_label should return human-readable descriptions."""
        assert confidence_label(0.95) == "very high"
        assert confidence_label(0.8) == "high"
        assert confidence_label(0.6) == "moderate"
        assert confidence_label(0.3) == "low"
        assert confidence_label(0.1) == "very low"
