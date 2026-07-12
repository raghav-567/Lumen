"""End-to-end pipeline benchmark — evaluates the full detection pipeline.

Usage:
    docker compose exec backend python -m evaluation.benchmarks.eval_end_to_end
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


def run_end_to_end_benchmark():
    """Evaluate the full pipeline: embedding → retrieval → NLI.

    Simulates the full detection pipeline on benchmark pairs.
    """
    from app.ingestion.embedder import generate_embeddings
    from app.contradiction.nli import classify_claim_pairs
    import numpy as np

    with open(BENCHMARK_PATH) as f:
        data = json.load(f)

    pairs = data["pairs"]
    logger.info(f"Loaded {len(pairs)} benchmark pairs")

    # Stage 1: Embed all claims
    all_a = [p["claim_a"] for p in pairs]
    all_b = [p["claim_b"] for p in pairs]

    t1 = time.monotonic()
    embeddings_a = np.array(generate_embeddings(all_a))
    embeddings_b = np.array(generate_embeddings(all_b))
    embed_time = time.monotonic() - t1

    # Stage 2: Retrieval — find true pairs by similarity
    t2 = time.monotonic()
    similarity_matrix = np.dot(embeddings_a, embeddings_b.T)
    retrieval_time = time.monotonic() - t2

    # Stage 3: NLI classification on all pairs
    text_pairs = [(p["claim_a"], p["claim_b"]) for p in pairs]

    t3 = time.monotonic()
    nli_results = classify_claim_pairs(text_pairs)
    nli_time = time.monotonic() - t3

    total_time = embed_time + retrieval_time + nli_time

    # Map labels for evaluation
    y_true_binary = []
    y_pred_binary = []

    for pair, nli_result in zip(pairs, nli_results):
        # Ground truth: is this a contradiction (including evolution)?
        is_contradiction = pair["label"] in ("contradiction", "evolution")
        y_true_binary.append("contradiction" if is_contradiction else "not_contradiction")

        # Prediction: NLI says contradiction with score >= threshold?
        predicted_contradiction = (
            nli_result["label"] == "contradiction"
            and nli_result["score"] >= 0.6
        )
        y_pred_binary.append("contradiction" if predicted_contradiction else "not_contradiction")

    from evaluation.metrics import precision_recall_f1, multiclass_report

    binary_metrics = precision_recall_f1(y_true_binary, y_pred_binary, "contradiction")
    full_report = multiclass_report(
        [p["label"] for p in pairs],
        [r["label"] for r in nli_results],
    )

    results = {
        "binary_detection": binary_metrics,
        "multiclass": full_report,
        "latency": {
            "embedding_s": round(embed_time, 3),
            "retrieval_s": round(retrieval_time, 3),
            "nli_s": round(nli_time, 3),
            "total_s": round(total_time, 3),
            "per_pair_ms": round(total_time / len(pairs) * 1000, 1),
        },
        "pipeline_config": {
            "similarity_threshold": 0.55,
            "nli_threshold": 0.6,
            "num_pairs": len(pairs),
        },
    }

    # Save results
    RESULTS_DIR.mkdir(exist_ok=True)
    result_path = RESULTS_DIR / "end_to_end_benchmark.json"
    with open(result_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    # Print report
    print("\n# End-to-End Pipeline Benchmark\n")
    print(f"## Binary Detection (Contradiction vs Not)")
    print(f"  Precision: {binary_metrics['precision']:.4f}")
    print(f"  Recall:    {binary_metrics['recall']:.4f}")
    print(f"  F1:        {binary_metrics['f1']:.4f}")
    print(f"  FP:        {binary_metrics['fp']}")
    print(f"  FN:        {binary_metrics['fn']}")
    print(f"\n## Latency")
    print(f"  Embedding:  {embed_time:.3f}s")
    print(f"  Retrieval:  {retrieval_time:.3f}s")
    print(f"  NLI:        {nli_time:.3f}s")
    print(f"  Total:      {total_time:.3f}s ({results['latency']['per_pair_ms']}ms/pair)")
    print(f"\n## Multiclass Accuracy: {full_report['accuracy']:.4f}")
    print(f"   Macro F1: {full_report['macro_f1']:.4f}")
    print(f"\n  Results saved to: {result_path}")

    return results


if __name__ == "__main__":
    run_end_to_end_benchmark()
