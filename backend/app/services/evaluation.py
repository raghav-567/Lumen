"""Evaluation service for computing system quality metrics."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def compute_coverage_score(
    total_chunks: int,
    indexed_chunks: int,
) -> float:
    """Coverage = indexed chunks / total chunks."""
    if total_chunks == 0:
        return 0.0
    return round(indexed_chunks / total_chunks, 4)


def compute_contradiction_detection_rate(
    detected_contradictions: int,
    total_comparisons: int,
) -> float:
    """Rate = detected / total comparisons."""
    if total_comparisons == 0:
        return 0.0
    return round(detected_contradictions / total_comparisons, 4)


def compute_average_confidence(confidences: list[float]) -> float:
    """Average confidence across detections."""
    if not confidences:
        return 0.0
    return round(sum(confidences) / len(confidences), 4)
