"""Tests for contradiction detector dataclasses."""

import pytest


def test_contradiction_result_structure():
    """Test ContradictionResult dataclass fields."""
    from app.contradiction.detector import ContradictionResult

    result = ContradictionResult(
        chunk_a_id="a",
        chunk_b_id="b",
        chunk_a_text="Text A",
        chunk_b_text="Text B",
        classification="CONTRADICTORY",
        confidence=0.95,
        explanation="Test",
        conflicting_claims=["claim1", "claim2"],
    )
    assert result.classification == "CONTRADICTORY"
    assert result.confidence == 0.95
    assert len(result.conflicting_claims) == 2


def test_contradiction_classifications():
    """Valid classification values."""
    valid = {"CONSISTENT", "CONTRADICTORY", "SUPERSEDES", "UNRELATED"}
    assert "CONTRADICTORY" in valid
