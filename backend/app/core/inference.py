"""Unified batch inference abstraction with latency tracking.

Provides memory-aware, configurable batching for all ML inference calls:
- Embedding generation
- NLI classification
- Reranking
- LLM extraction

Usage:
    processor = BatchProcessor(batch_size=16)
    results = processor.process(items, model.predict, desc="NLI")
"""

from __future__ import annotations

import logging
import time
from typing import TypeVar, Callable, Sequence

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


class BatchProcessor:
    """Memory-aware batch inference with latency tracking."""

    def __init__(self, batch_size: int = 16, max_items: int = 10000):
        """
        Args:
            batch_size: Number of items per inference batch
            max_items: Safety cap on total items to process
        """
        self.batch_size = batch_size
        self.max_items = max_items
        self._last_latency: float = 0.0
        self._total_latency: float = 0.0
        self._total_items: int = 0

    def process(
        self,
        items: Sequence[T],
        inference_fn: Callable[[list[T]], list[R]],
        desc: str = "inference",
    ) -> list[R]:
        """Process items in batches with timing metrics.

        Args:
            items: Input items to process
            inference_fn: Function that takes a batch (list) and returns results (list)
            desc: Description for logging

        Returns:
            Flat list of results from all batches
        """
        if not items:
            return []

        # Safety cap
        items = items[:self.max_items]

        results: list[R] = []
        total_start = time.monotonic()
        num_batches = (len(items) + self.batch_size - 1) // self.batch_size

        for batch_idx, start_idx in enumerate(range(0, len(items), self.batch_size)):
            batch = list(items[start_idx : start_idx + self.batch_size])
            batch_start = time.monotonic()

            batch_results = inference_fn(batch)

            batch_elapsed = time.monotonic() - batch_start
            results.extend(batch_results)

            if num_batches > 1:
                logger.debug(
                    f"[{desc}] batch {batch_idx+1}/{num_batches}: "
                    f"{len(batch)} items, {batch_elapsed:.3f}s"
                )

        total_elapsed = time.monotonic() - total_start
        self._last_latency = total_elapsed
        self._total_latency += total_elapsed
        self._total_items += len(items)

        logger.info(
            f"[{desc}] processed {len(items)} items in {total_elapsed:.3f}s "
            f"({num_batches} batches, {total_elapsed/max(len(items),1)*1000:.1f}ms/item)"
        )

        return results

    @property
    def stats(self) -> dict:
        """Return cumulative inference stats."""
        return {
            "last_latency_s": round(self._last_latency, 4),
            "total_latency_s": round(self._total_latency, 4),
            "total_items": self._total_items,
            "avg_ms_per_item": round(
                (self._total_latency / max(self._total_items, 1)) * 1000, 2
            ),
        }


# ── Pre-configured processors ────────────────────────────────


# Embedding: larger batches are efficient for sentence-transformers
embedding_processor = BatchProcessor(batch_size=32)

# NLI: cross-encoder, moderate batch size
nli_processor = BatchProcessor(batch_size=16)

# Reranking: cross-encoder, moderate batch size
rerank_processor = BatchProcessor(batch_size=16)

# LLM extraction: sequential (batch_size=1) since LLM calls are individual
extraction_processor = BatchProcessor(batch_size=1)
