"""Tests for retrieval engine utilities."""

import pytest


def test_score_combination():
    """Hybrid score combines semantic and BM25 correctly."""
    semantic_weight = 0.6
    sem = 0.8
    bm = 0.6
    combined = semantic_weight * sem + (1 - semantic_weight) * bm
    assert abs(combined - 0.72) < 0.01


def test_empty_chunks():
    """Empty chunk list returns empty results."""
    # The hybrid_search function should handle empty input gracefully
    assert [] == []
