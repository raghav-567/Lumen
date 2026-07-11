"""Cross-encoder reranking for improved retrieval quality.

Inserted between ChromaDB candidate retrieval and NLI classification to
filter out false-positive similar chunks before the expensive NLI step.

Model: BAAI/bge-reranker-base (278MB, CPU-friendly, no GPU needed)

Pipeline:
    embed query → ChromaDB top-20 → rerank to top-5 → NLI classify
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache

from sentence_transformers import CrossEncoder

from app.core.config import settings
from app.core.inference import rerank_processor

logger = logging.getLogger(__name__)

RERANKER_MODEL = "BAAI/bge-reranker-base"


@lru_cache(maxsize=1)
def _get_reranker() -> CrossEncoder:
    """Load the reranker model (cached, loaded once)."""
    logger.info(f"Loading reranker model: {RERANKER_MODEL}")
    model = CrossEncoder(RERANKER_MODEL, max_length=512)
    return model


def rerank_candidates(
    query: str,
    candidates: list[dict],
    top_k: int | None = None,
    threshold: float | None = None,
) -> list[dict]:
    """Rerank candidate chunks/claims by cross-encoder relevance.

    Args:
        query: The source claim text
        candidates: List of dicts with at least a 'text' key
        top_k: Number of top results to return (default: settings.RERANK_FINAL_K)
        threshold: Minimum rerank score to keep (default: settings.RERANK_THRESHOLD)

    Returns:
        Reranked and filtered candidate list, each enriched with 'rerank_score'
    """
    if not candidates:
        return []

    if not settings.RERANK_ENABLED:
        return candidates

    top_k = top_k or settings.RERANK_FINAL_K
    threshold = threshold if threshold is not None else settings.RERANK_THRESHOLD

    model = _get_reranker()

    # Build pairs for cross-encoder
    pairs = [(query, cand["text"]) for cand in candidates]

    # Score with batch processor for latency tracking
    start = time.monotonic()
    scores = model.predict(pairs, batch_size=rerank_processor.batch_size)
    elapsed = time.monotonic() - start

    logger.info(
        f"[Reranker] scored {len(pairs)} pairs in {elapsed:.3f}s "
        f"({elapsed/max(len(pairs),1)*1000:.1f}ms/pair)"
    )

    # Attach scores and filter
    for cand, score in zip(candidates, scores):
        cand["rerank_score"] = float(score)

    # Filter by threshold
    filtered = [c for c in candidates if c["rerank_score"] >= threshold]

    # Sort by rerank score descending
    filtered.sort(key=lambda x: x["rerank_score"], reverse=True)

    # Return top-k
    return filtered[:top_k]
