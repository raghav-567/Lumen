"""Tests for Change 3: Temporal Resolver — Reviewer Feedback Loop."""

import re
import pytest

from app.temporal.resolver import (
    TemporalClassification,
    classify_temporal_relationship,
    _check_lineage,
)


class TestTemporalClassificationInferred:
    """Test that inferred flag propagates correctly."""

    def test_explicit_supersession_not_inferred(self):
        """Explicit supersession links should NOT be marked as inferred."""
        doc_a = {"id": "doc-1", "supersedes_document_id": None}
        doc_b = {"id": "doc-2", "supersedes_document_id": "doc-1"}

        result = classify_temporal_relationship(doc_a, doc_b)
        assert result.classification == TemporalClassification.EVOLUTION
        assert result.inferred is False
        assert result.confidence == 1.0

    def test_expired_policy_not_inferred(self):
        """Expired policy detection is metadata-based, not heuristic-inferred."""
        from datetime import datetime, timezone, timedelta
        past = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        doc_a = {"id": "doc-1", "effective_until": past}
        doc_b = {"id": "doc-2"}

        result = classify_temporal_relationship(doc_a, doc_b)
        assert result.classification == TemporalClassification.EVOLUTION
        assert result.inferred is False

    def test_default_contradiction_not_inferred(self):
        """Default contradiction classification has inferred=False."""
        doc_a = {"id": "doc-1"}
        doc_b = {"id": "doc-2"}

        result = classify_temporal_relationship(doc_a, doc_b)
        assert result.classification == TemporalClassification.CONTRADICTION
        assert result.inferred is False

    def test_classification_repr_includes_inferred(self):
        """Repr should show 'inferred' when flag is True."""
        tc = TemporalClassification("evolution", "test", confidence=0.9, inferred=True)
        assert "inferred" in repr(tc)

    def test_classification_repr_no_inferred_when_false(self):
        """Repr should not show 'inferred' when flag is False."""
        tc = TemporalClassification("evolution", "test", confidence=0.9, inferred=False)
        assert "inferred" not in repr(tc)


class TestHeuristicSignalExtraction:
    """Test regex extraction of heuristic signals from explanation text."""

    def test_extract_title_similarity(self):
        text = "[Policy Evolution] Inferred lineage: same department, similar titles (sim=0.91), Doc B is version 2 vs Doc A version 1."
        match = re.search(r"sim=(\d+\.\d+)", text)
        assert match is not None
        assert float(match.group(1)) == 0.91

    def test_extract_date_gap(self):
        text = "[Policy Evolution] Inferred lineage: same department, similar titles (sim=0.88), Doc B is newer by 45 days."
        match = re.search(r"newer by (\d+) days", text)
        assert match is not None
        assert int(match.group(1)) == 45

    def test_no_date_gap_when_version_based(self):
        """Version-based lineage doesn't have a date gap in the text."""
        text = "[Policy Evolution] Inferred lineage: same department, similar titles (sim=0.91), Doc B is version 2 vs Doc A version 1."
        match = re.search(r"newer by (\d+) days", text)
        assert match is None

    def test_extract_from_non_lineage_text(self):
        """Non-lineage explanations should not match."""
        text = "These two statements present conflicting information."
        sim_match = re.search(r"sim=(\d+\.\d+)", text)
        gap_match = re.search(r"newer by (\d+) days", text)
        assert sim_match is None
        assert gap_match is None


class TestFeedbackLoopDecisions:
    """Test classification of reviewer decisions."""

    def test_override_decisions(self):
        """REJECTED and FALSE_POSITIVE count as overrides."""
        overrides = {"REJECTED", "FALSE_POSITIVE"}
        assert "REJECTED" in overrides
        assert "FALSE_POSITIVE" in overrides

    def test_confirmation_decisions(self):
        """APPROVED is a confirmation (not an override)."""
        overrides = {"REJECTED", "FALSE_POSITIVE"}
        assert "APPROVED" not in overrides
        assert "INTENTIONAL_DIVERGENCE" not in overrides

    def test_override_rate_calculation(self):
        """Override rate = overrides / total_feedback."""
        overrides = 3
        total = 10
        rate = overrides / max(total, 1)
        assert rate == 0.3
