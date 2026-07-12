"""Retrieval-only benchmark — evaluates embedding similarity retrieval quality.

Usage:
    docker compose exec backend python -m evaluation.benchmarks.eval_retrieval
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BENCHMARK_PATH = Path(__file__).parent.parent / "datasets" / "benchmark_v1.json"
RESULTS_DIR = Path(__file__).parent.parent / "results"


def run_retrieval_benchmark():
    """Evaluate embedding retrieval quality using the benchmark dataset.

    For each claim_a, embeds it and retrieves the most similar from all claim_b's.
    Measures whether the true pair is retrieved within top-K.
    """
    from app.ingestion.embedder import generate_embeddings
    import numpy as np

    with open(BENCHMARK_PATH) as f:
        data = json.load(f)

    pairs = data["pairs"]
    logger.info(f"Loaded {len(pairs)} benchmark pairs")

    # Only contradiction/evolution pairs are "relevant" — they should be retrieved
    relevant_labels = {"contradiction", "evolution"}

    # Embed all claims
    all_a = [p["claim_a"] for p in pairs]
    all_b = [p["claim_b"] for p in pairs]

    start = time.monotonic()
    embeddings_a = np.array(generate_embeddings(all_a))
    embeddings_b = np.array(generate_embeddings(all_b))
    embed_elapsed = time.monotonic() - start

    logger.info(f"Embedded {len(all_a)*2} claims in {embed_elapsed:.3f}s")

    # For each claim_a, compute similarity to ALL claim_b's, rank them
    start = time.monotonic()
    similarity_matrix = np.dot(embeddings_a, embeddings_b.T)  # cosine (normalized)
    retrieve_elapsed = time.monotonic() - start

    k_values = [1, 3, 5, 10]
    recall_at_k = {k: 0 for k in k_values}
    mrr_sum = 0.0
    relevant_count = 0

    for i, pair in enumerate(pairs):
        if pair["label"] not in relevant_labels:
            continue

        relevant_count += 1
        scores = similarity_matrix[i]
        ranked_indices = np.argsort(-scores)  # descending

        # True match is index i (claim_b at same index)
        rank = int(np.where(ranked_indices == i)[0][0]) + 1  # 1-indexed

        for k in k_values:
            if rank <= k:
                recall_at_k[k] += 1

        mrr_sum += 1.0 / rank

    results = {
        "retrieval_metrics": {
            f"recall@{k}": round(recall_at_k[k] / max(relevant_count, 1), 4)
            for k in k_values
        },
        "mrr": round(mrr_sum / max(relevant_count, 1), 4),
        "relevant_pairs": relevant_count,
        "total_pairs": len(pairs),
        "latency": {
            "embedding_s": round(embed_elapsed, 3),
            "retrieval_s": round(retrieve_elapsed, 3),
        },
    }

    # Save results
    RESULTS_DIR.mkdir(exist_ok=True)
    result_path = RESULTS_DIR / "retrieval_benchmark.json"
    with open(result_path, "w") as f:
        json.dump(results, f, indent=2)

    # Print report
    print("\n# Retrieval Benchmark Results\n")
    for k, v in results["retrieval_metrics"].items():
        print(f"  {k}: {v:.4f}")
    print(f"  MRR: {results['mrr']:.4f}")
    print(f"\n  Relevant pairs: {relevant_count}")
    print(f"  Embedding latency: {embed_elapsed:.3f}s")
    print(f"\n  Results saved to: {result_path}")

    return results


if __name__ == "__main__":
    run_retrieval_benchmark()
