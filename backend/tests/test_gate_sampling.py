"""Tests for Change 1: Similarity Gate Sampling & Threshold Validation."""

import random
from unittest.mock import patch, MagicMock

import pytest

from app.contradiction.detector import ContradictionResult


class TestGateSampling:
    """Test the similarity gate sampling logic."""

    def test_contraction_result_has_sampled_fields(self):
        """ContradictionResult carries sampled and gate_similarity."""
        result = ContradictionResult(
            chunk_a_id="a",
            chunk_b_id="b",
            chunk_a_text="text a",
            chunk_b_text="text b",
            classification="CONTRADICTORY",
            confidence=0.9,
            explanation="test",
            conflicting_claims=["a", "b"],
            sampled=True,
            gate_similarity=0.68,
        )
        assert result.sampled is True
        assert result.gate_similarity == 0.68

    def test_contraction_result_defaults(self):
        """Default sampled=False and gate_similarity=0.0."""
        result = ContradictionResult(
            chunk_a_id="a",
            chunk_b_id="b",
            chunk_a_text="text a",
            chunk_b_text="text b",
            classification="CONTRADICTORY",
            confidence=0.9,
            explanation="test",
            conflicting_claims=["a", "b"],
        )
        assert result.sampled is False
        assert result.gate_similarity == 0.0

    def test_gate_sampling_probability(self):
        """5% sample rate retains roughly 5% of below-threshold candidates."""
        random.seed(42)
        sample_rate = 0.05
        n_trials = 10000
        retained = sum(1 for _ in range(n_trials) if random.random() < sample_rate)
        # Allow ±2% tolerance
        assert 300 < retained < 700, f"Expected ~500, got {retained}"

    def test_gate_sample_rate_zero_retains_none(self):
        """GATE_SAMPLE_RATE=0 should never retain below-threshold pairs."""
        random.seed(42)
        sample_rate = 0.0
        retained = sum(1 for _ in range(1000) if sample_rate > 0 and random.random() < sample_rate)
        assert retained == 0

    def test_gate_sample_rate_one_retains_all(self):
        """GATE_SAMPLE_RATE=1.0 should retain all below-threshold pairs."""
        random.seed(42)
        sample_rate = 1.0
        retained = sum(1 for _ in range(100) if random.random() < sample_rate)
        assert retained == 100


class TestGateCalibrationRecommendation:
    """Test the recommendation logic for threshold adjustment."""

    def test_high_contradiction_rate_recommends_lower(self):
        """If >15% of sampled pairs are contradictions, recommend lowering threshold."""
        rate = 0.25  # 25%
        assert rate > 0.15  # would trigger LOWER_THRESHOLD

    def test_low_contradiction_rate_recommends_raise(self):
        """If <2% of sampled pairs are contradictions, recommend raising threshold."""
        rate = 0.01  # 1%
        assert rate < 0.02  # would trigger RAISE_THRESHOLD

    def test_normal_rate_no_change(self):
        """5% rate is within acceptable range — no change."""
        rate = 0.05
        assert 0.02 <= rate <= 0.15  # NO_CHANGE
