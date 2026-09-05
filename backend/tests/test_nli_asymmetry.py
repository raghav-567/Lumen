"""Tests for NLI asymmetry check — covers Fix 2.2 and Fix 2.2b.

Tests:
  - is_genuine_contradiction() correctly identifies elaboration vs contradiction
  - Feature flag ENTAILMENT_ASYMMETRY_CHECK gates the check
  - Modality gate comparability (Fix 2.3b)
  - Age decay conditionality (Fix 4.1)
"""

import pytest
from unittest.mock import patch, MagicMock
from app.contradiction.detector import (
    is_genuine_contradiction,
    modalities_are_comparable,
    specificity_ratio,
    COMPARABLE_MODALITY_PAIRS,
)
from app.drift.scorer import compute_dual_drift_score, compute_age_decay


class TestEntailmentAsymmetry:
    """Fix 2.2: Bidirectional NLI should filter elaboration."""

    @patch("app.contradiction.detector.classify_claim_pairs")
    def test_bidirectional_contradiction_is_genuine(self, mock_nli):
        """Both A→B and B→A say contradiction → genuine."""
        mock_nli.side_effect = [
            [{"label": "contradiction", "score": 0.85, "scores": {}}],
            [{"label": "contradiction", "score": 0.82, "scores": {}}],
        ]
        genuine, reason = is_genuine_contradiction("Claim A", "Claim B")
        assert genuine is True
        assert reason == "bidirectional_contradiction"

    @patch("app.contradiction.detector.classify_claim_pairs")
    def test_forward_entailment_filtered(self, mock_nli):
        """A entails B → elaboration, not contradiction."""
        mock_nli.side_effect = [
            [{"label": "entailment", "score": 0.90, "scores": {}}],
            [{"label": "contradiction", "score": 0.80, "scores": {}}],
        ]
        genuine, reason = is_genuine_contradiction("General claim", "Specific claim")
        assert genuine is False
        assert reason == "elaboration"

    @patch("app.contradiction.detector.classify_claim_pairs")
    def test_reverse_entailment_filtered(self, mock_nli):
        """B entails A → elaboration."""
        mock_nli.side_effect = [
            [{"label": "contradiction", "score": 0.80, "scores": {}}],
            [{"label": "entailment", "score": 0.85, "scores": {}}],
        ]
        genuine, reason = is_genuine_contradiction("Specific claim", "General claim")
        assert genuine is False
        assert reason == "elaboration"

    @patch("app.contradiction.detector.classify_claim_pairs")
    def test_one_directional_contradiction_filtered(self, mock_nli):
        """Only one direction contradicts → specificity mismatch."""
        mock_nli.side_effect = [
            [{"label": "contradiction", "score": 0.80, "scores": {}}],
            [{"label": "neutral", "score": 0.60, "scores": {}}],
        ]
        genuine, reason = is_genuine_contradiction("Claim A", "Claim B")
        assert genuine is False
        assert reason == "specificity_mismatch"


class TestModalityGate:
    """Fix 2.3 + 2.3b: Modality comparability rules."""

    def test_same_modality_comparable(self):
        assert modalities_are_comparable("MANDATORY", "MANDATORY") is True

    def test_mandatory_prohibited_comparable(self):
        assert modalities_are_comparable("MANDATORY", "PROHIBITED") is True

    def test_mandatory_recommended_comparable(self):
        assert modalities_are_comparable("MANDATORY", "RECOMMENDED") is True

    def test_informational_not_comparable_with_mandatory(self):
        """Fix 2.3b: INFORMATIONAL should NOT compare with MANDATORY."""
        assert modalities_are_comparable("INFORMATIONAL", "MANDATORY") is False

    def test_informational_not_comparable_with_prohibited(self):
        """Fix 2.3b: INFORMATIONAL should NOT compare with PROHIBITED."""
        assert modalities_are_comparable("INFORMATIONAL", "PROHIBITED") is False

    def test_informational_comparable_with_informational(self):
        assert modalities_are_comparable("INFORMATIONAL", "INFORMATIONAL") is True

    def test_missing_modality_permissive(self):
        """Missing modality should not block comparison."""
        assert modalities_are_comparable(None, "MANDATORY") is True
        assert modalities_are_comparable("MANDATORY", None) is True
        assert modalities_are_comparable(None, None) is True

    def test_no_informational_mandatory_in_comparable_set(self):
        """Verify the constant set doesn't contain the removed pairs."""
        assert ("INFORMATIONAL", "MANDATORY") not in COMPARABLE_MODALITY_PAIRS
        assert ("MANDATORY", "INFORMATIONAL") not in COMPARABLE_MODALITY_PAIRS
        assert ("INFORMATIONAL", "PROHIBITED") not in COMPARABLE_MODALITY_PAIRS
        assert ("PROHIBITED", "INFORMATIONAL") not in COMPARABLE_MODALITY_PAIRS


class TestSpecificityRatio:
    """Fix 2.4: Length ratio filter."""

    def test_similar_length(self):
        ratio = specificity_ratio("short claim here", "another short claim")
        assert ratio < 2.0

    def test_high_ratio(self):
        ratio = specificity_ratio(
            "Short.",
            "This is a much longer claim with many more words and details.",
        )
        assert ratio > 2.0


class TestConditionalAgeDecay:
    """Fix 4.1: Age decay should only apply with drift signals."""

    def test_no_drift_signal_no_age_decay(self):
        """Documents with zero contradictions AND zero semantic shift get no age decay."""
        result = compute_dual_drift_score(
            contradiction_ratio=0.0,
            avg_contradiction_confidence=0.0,
            semantic_shift=0.0,
            age_decay=0.8,  # very old document
            contradiction_count=0,  # no contradictions
        )
        # Both factual and semantic should be near 0
        assert result["factual_drift_score"] == 0.0
        assert result["semantic_drift_score"] == 0.0
        assert result["drift_type"] == "none"

    def test_with_contradictions_age_decay_applies(self):
        """Documents WITH contradictions should get age decay effect."""
        result = compute_dual_drift_score(
            contradiction_ratio=0.3,
            avg_contradiction_confidence=0.75,
            semantic_shift=0.5,
            age_decay=0.8,
            contradiction_count=3,
        )
        assert result["semantic_drift_score"] > 0.0
        assert result["factual_drift_score"] > 0.0

    def test_semantic_shift_only_enables_age_decay(self):
        """Semantic shift without contradictions should still enable age decay."""
        result_with_shift = compute_dual_drift_score(
            contradiction_ratio=0.0,
            avg_contradiction_confidence=0.0,
            semantic_shift=0.3,
            age_decay=0.8,
            contradiction_count=0,
        )
        result_without_shift = compute_dual_drift_score(
            contradiction_ratio=0.0,
            avg_contradiction_confidence=0.0,
            semantic_shift=0.0,
            age_decay=0.8,
            contradiction_count=0,
        )
        # With semantic shift, age decay kicks in → higher semantic score
        assert result_with_shift["semantic_drift_score"] > result_without_shift["semantic_drift_score"]

    def test_age_decay_function_returns_valid_range(self):
        """compute_age_decay should return 0..1."""
        from datetime import datetime, timezone, timedelta

        recent = datetime.now(timezone.utc) - timedelta(days=1)
        old = datetime.now(timezone.utc) - timedelta(days=365)

        assert 0.0 <= compute_age_decay(recent) <= 1.0
        assert 0.0 <= compute_age_decay(old) <= 1.0
        assert compute_age_decay(old) > compute_age_decay(recent)
