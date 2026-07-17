"""Pipeline operational metrics tracker.

Tracks all reduction stages of the hierarchical candidate pipeline
for observability and performance tuning.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PipelineMetrics:
    """Tracks metrics across the entire contradiction detection pipeline."""

    # Document-level
    document_id: str = ""
    document_title: str = ""

    # Timing
    start_time: float = 0.0
    stage_times: dict[str, float] = field(default_factory=dict)

    # Claim reduction funnel
    raw_sentences: int = 0
    after_noise_filter: int = 0
    after_salience_filter: int = 0
    after_dedup: int = 0
    claims_scanned: int = 0

    # Retrieval
    total_candidates_retrieved: int = 0
    after_similarity_gate: int = 0
    after_rerank: int = 0

    # NLI
    nli_comparisons: int = 0
    nli_skipped: int = 0
    contradictions_found: int = 0

    # Cache
    claim_cache_hits: int = 0
    claim_cache_misses: int = 0

    # Cluster routing
    cluster_routed: bool = False
    clusters_queried: int = 0

    # Explanation
    explanations_generated: int = 0
    explanations_deferred: int = 0

    def start(self):
        self.start_time = time.monotonic()

    def stage_start(self, name: str):
        self.stage_times[f"{name}_start"] = time.monotonic()

    def stage_end(self, name: str):
        start_key = f"{name}_start"
        if start_key in self.stage_times:
            elapsed = time.monotonic() - self.stage_times[start_key]
            self.stage_times[name] = round(elapsed, 3)
            del self.stage_times[start_key]

    @property
    def total_time(self) -> float:
        if self.start_time == 0:
            return 0.0
        return round(time.monotonic() - self.start_time, 2)

    @property
    def claim_reduction_ratio(self) -> float:
        if self.raw_sentences == 0:
            return 0.0
        return round(1.0 - (self.claims_scanned / max(self.raw_sentences, 1)), 2)

    @property
    def candidate_reduction_ratio(self) -> float:
        if self.total_candidates_retrieved == 0:
            return 0.0
        return round(1.0 - (self.nli_comparisons / max(self.total_candidates_retrieved, 1)), 2)

    def report(self) -> dict:
        """Generate a structured metrics report."""
        return {
            "document": {
                "id": self.document_id[:8] if self.document_id else "",
                "title": self.document_title[:50],
            },
            "timing": {
                "total_seconds": self.total_time,
                "stages": {k: v for k, v in self.stage_times.items() if not k.endswith("_start")},
            },
            "claim_funnel": {
                "raw_sentences": self.raw_sentences,
                "after_noise_filter": self.after_noise_filter,
                "after_salience": self.after_salience_filter,
                "after_dedup": self.after_dedup,
                "scanned": self.claims_scanned,
                "reduction_ratio": self.claim_reduction_ratio,
            },
            "retrieval": {
                "total_candidates": self.total_candidates_retrieved,
                "after_similarity_gate": self.after_similarity_gate,
                "after_rerank": self.after_rerank,
                "candidate_reduction": self.candidate_reduction_ratio,
                "cluster_routed": self.cluster_routed,
            },
            "nli": {
                "comparisons": self.nli_comparisons,
                "skipped": self.nli_skipped,
                "contradictions": self.contradictions_found,
            },
            "cache": {
                "claim_hits": self.claim_cache_hits,
                "claim_misses": self.claim_cache_misses,
            },
            "explanations": {
                "generated": self.explanations_generated,
                "deferred": self.explanations_deferred,
            },
        }

    def log_summary(self):
        """Log a one-line summary of pipeline performance."""
        logger.info(
            f"Pipeline [{self.document_id[:8]}]: "
            f"{self.raw_sentences}→{self.after_noise_filter}→{self.after_dedup}→{self.claims_scanned} claims, "
            f"{self.total_candidates_retrieved}→{self.after_similarity_gate}→{self.nli_comparisons} candidates, "
            f"{self.contradictions_found} contradictions, "
            f"{self.total_time}s total"
        )
