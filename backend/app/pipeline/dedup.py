"""Semantic deduplication of claims.

Removes near-duplicate claims within a document before retrieval.
Uses embedding cosine similarity with configurable threshold.

Expected reduction: ~120 filtered claims → ~70 unique claims
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

DEDUP_THRESHOLD = 0.93  # cosine similarity above this = duplicate


def deduplicate_claims(
    claims: list[dict],
    embeddings: np.ndarray,
    threshold: float = DEDUP_THRESHOLD,
) -> tuple[list[dict], list[int], dict]:
    """Remove near-duplicate claims using embedding cosine similarity.

    Args:
        claims: List of claim dicts (must have 'content' key)
        embeddings: (N, D) array of claim embeddings
        threshold: Cosine similarity threshold for deduplication

    Returns:
        Tuple of (unique_claims, kept_indices, metrics)
    """
    n = len(claims)
    if n <= 1:
        return claims, list(range(n)), {"removed": 0, "kept": n}

    # Normalize for cosine similarity
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-8)
    normalized = embeddings / norms

    # Track which claims to keep
    kept = [True] * n
    duplicates_of: dict[int, int] = {}  # maps duplicate → representative

    # Greedy deduplication: for each claim, check against all previous kept claims
    for i in range(1, n):
        if not kept[i]:
            continue
        for j in range(i):
            if not kept[j]:
                continue
            sim = float(np.dot(normalized[i], normalized[j]))
            if sim >= threshold:
                kept[i] = False
                duplicates_of[i] = j
                break

    kept_indices = [i for i in range(n) if kept[i]]
    unique_claims = [claims[i] for i in kept_indices]

    removed = n - len(unique_claims)
    metrics = {
        "input_claims": n,
        "unique_claims": len(unique_claims),
        "removed": removed,
        "dedup_ratio": round(removed / max(n, 1), 2),
    }

    if removed > 0:
        logger.info(
            f"Semantic dedup: {n} → {len(unique_claims)} claims "
            f"(removed {removed}, threshold={threshold})"
        )

    return unique_claims, kept_indices, metrics
