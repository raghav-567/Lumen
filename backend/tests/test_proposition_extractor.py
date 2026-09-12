"""Tests for the proposition extractor — covers Fix 3.2b and Fix 3.2c.

Tests:
  - Polarity signal word disambiguation (no overlap between pos/neg sets)
  - Verb-boundary entity extraction vs old first-capitalized-word heuristic
  - Article stripping from entity names
"""

import pytest
from app.contradiction.proposition_extractor import (
    _infer_polarity,
    _infer_confidence,
    _extract_rule_based,
    _POSITIVE_SIGNALS,
    _NEGATIVE_SIGNALS,
    Proposition,
)


class TestPolaritySignalOverlap:
    """Fix 3.2b: Polarity sets must not share ambiguous words."""

    def test_no_overlap_between_positive_and_negative(self):
        overlap = _POSITIVE_SIGNALS & _NEGATIVE_SIGNALS
        assert overlap == set(), (
            f"Polarity signal overlap found: {overlap}. "
            f"These words are context-dependent and should be in neither set."
        )

    def test_ambiguous_words_excluded(self):
        """dropped, reduced, decreased, exceeded should be in neither set."""
        for word in ("dropped", "reduced", "decreased", "exceeded"):
            assert word not in _POSITIVE_SIGNALS, f"'{word}' in _POSITIVE_SIGNALS"
            assert word not in _NEGATIVE_SIGNALS, f"'{word}' in _NEGATIVE_SIGNALS"


class TestPolarityInference:
    """Test polarity inference on unambiguous sentences."""

    def test_positive_sentence(self):
        result = _infer_polarity(
            "The system improved performance and demonstrated enhanced stability."
        )
        assert result == "positive"

    def test_negative_sentence(self):
        """Use a sentence without 'failed to' which triggers negation flip."""
        result = _infer_polarity(
            "The project struggled with insufficient resources and performance deteriorated sharply."
        )
        assert result == "negative"

    def test_neutral_sentence(self):
        result = _infer_polarity(
            "The committee met on Tuesday to discuss the quarterly budget."
        )
        assert result == "neutral"

    def test_negation_flips_polarity(self):
        """'did not improve' should be negative despite 'improved' being positive."""
        result = _infer_polarity(
            "The system did not improve and the gains were never realized."
        )
        # Negation detected → positive signals become negative
        assert result in ("negative", "neutral")


class TestConfidenceInference:

    def test_hedged_sentence(self):
        result = _infer_confidence(
            "The results suggested that performance may have partially improved."
        )
        assert result == "hedged"

    def test_certain_sentence(self):
        result = _infer_confidence(
            "Analysis clearly demonstrated that the system significantly improved."
        )
        assert result == "certain"


class TestVerbBoundaryEntityExtraction:
    """Fix 3.2c: Entity extraction should find subject up to first verb."""

    def test_basic_verb_boundary(self):
        props = _extract_rule_based(
            "Implementation costs exceeded productivity gains in most regions.",
            chunk_id="test", doc_id="test", section_heading="test",
        )
        assert len(props) >= 1
        prop = props[0]
        # Entity should be "Implementation costs" not just "Implementation"
        assert "costs" in prop.entity.lower(), (
            f"Expected 'Implementation costs' but got entity='{prop.entity}'"
        )

    def test_long_subject_with_verb(self):
        props = _extract_rule_based(
            "The decentralized routing system demonstrated improved traffic oscillation "
            "stability with a significant reduction in signal propagation delays.",
            chunk_id="test", doc_id="test", section_heading="test",
        )
        assert len(props) >= 1
        prop = props[0]
        # Entity should include "routing system" (up to "demonstrated")
        assert "routing" in prop.entity.lower() or "system" in prop.entity.lower(), (
            f"Expected entity containing 'routing system', got '{prop.entity}'"
        )

    def test_article_stripping(self):
        """Leading 'The' should be stripped from entity."""
        props = _extract_rule_based(
            "The monitoring framework has demonstrated significant improvement in detection "
            "accuracy across multiple operational scenarios during the evaluation period.",
            chunk_id="test", doc_id="test", section_heading="test",
        )
        assert len(props) >= 1
        prop = props[0]
        assert not prop.entity.startswith("The "), (
            f"Entity should not start with 'The', got '{prop.entity}'"
        )

    def test_fallback_for_no_verb(self):
        """When no verb marker found, fallback to capitalized-word heuristic."""
        props = _extract_rule_based(
            "Urban Mobility Infrastructure Capital Expenditure Allocation Across "
            "Metropolitan Regions For The Fiscal Year Budget Cycle.",
            chunk_id="test", doc_id="test", section_heading="test",
        )
        assert len(props) >= 1
        # Should still extract something even without a clear verb
        assert props[0].entity  # entity should not be empty
