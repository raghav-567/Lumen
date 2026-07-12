"""NLI-only benchmark — evaluates contradiction classification in isolation.

Usage:
    docker compose exec backend python -m evaluation.benchmarks.eval_nli
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BENCHMARK_PATH = Path(__file__).parent.parent / "datasets" / "benchmark_v1.json"
RESULTS_DIR = Path(__file__).parent.parent / "results"


def run_nli_benchmark():
    """Evaluate NLI model on the benchmark dataset."""
    from app.contradiction.nli import classify_claim_pairs

    with open(BENCHMARK_PATH) as f:
        data = json.load(f)

    pairs_data = data["pairs"]
    logger.info(f"Loaded {len(pairs_data)} benchmark pairs")

    # Build input pairs
    text_pairs = [(p["claim_a"], p["claim_b"]) for p in pairs_data]

    # Run NLI classification with timing
    start = time.monotonic()
    nli_results = classify_claim_pairs(text_pairs)
    elapsed = time.monotonic() - start

    logger.info(f"NLI inference: {elapsed:.3f}s for {len(text_pairs)} pairs ({elapsed/len(text_pairs)*1000:.1f}ms/pair)")

    # Map benchmark labels to NLI-compatible labels
    # evolution → contradiction (NLI model doesn't know about evolution)
    label_map = {
        "contradiction": "contradiction",
        "entailment": "entailment",
        "neutral": "neutral",
        "evolution": "contradiction",  # NLI sees evolution as contradiction-like
    }

    y_true = [label_map.get(p["label"], p["label"]) for p in pairs_data]
    y_pred = [r["label"] for r in nli_results]
    y_scores = [r["score"] for r in nli_results]

    # Compute metrics
    from evaluation.metrics import multiclass_report, format_report

    report = multiclass_report(y_true, y_pred)
    report["latency"] = {
        "total_s": round(elapsed, 3),
        "per_pair_ms": round(elapsed / len(text_pairs) * 1000, 1),
    }

    # Per-difficulty breakdown
    difficulty_results = {}
    for pair, pred, true in zip(pairs_data, y_pred, y_true):
        d = pair.get("difficulty", "unknown")
        if d not in difficulty_results:
            difficulty_results[d] = {"correct": 0, "total": 0}
        difficulty_results[d]["total"] += 1
        if pred == true:
            difficulty_results[d]["correct"] += 1

    for d, r in difficulty_results.items():
        r["accuracy"] = round(r["correct"] / max(r["total"], 1), 4)

    report["per_difficulty"] = difficulty_results

    # Save results
    RESULTS_DIR.mkdir(exist_ok=True)
    result_path = RESULTS_DIR / "nli_benchmark.json"
    with open(result_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    # Print report
    print(format_report(report, title="NLI Benchmark Results"))
    print(f"\nLatency: {report['latency']['per_pair_ms']}ms/pair")
    print(f"\nPer-difficulty accuracy:")
    for d, r in difficulty_results.items():
        print(f"  {d}: {r['accuracy']:.2%} ({r['correct']}/{r['total']})")

    print(f"\nResults saved to: {result_path}")
    return report


if __name__ == "__main__":
    run_nli_benchmark()
