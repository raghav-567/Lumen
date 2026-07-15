"""Run all evaluation benchmarks and generate a unified report.

Usage:
    docker compose exec backend python -m evaluation.run_all
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).parent / "results"


def run_all():
    """Execute all benchmark suites sequentially."""
    RESULTS_DIR.mkdir(exist_ok=True)

    all_results = {}

    # 1. NLI benchmark
    print("=" * 60)
    print("  Running NLI Benchmark")
    print("=" * 60)
    try:
        from evaluation.benchmarks.eval_nli import run_nli_benchmark
        all_results["nli"] = run_nli_benchmark()
    except Exception as e:
        logger.error(f"NLI benchmark failed: {e}")
        all_results["nli"] = {"error": str(e)}

    # 2. Retrieval benchmark
    print("\n" + "=" * 60)
    print("  Running Retrieval Benchmark")
    print("=" * 60)
    try:
        from evaluation.benchmarks.eval_retrieval import run_retrieval_benchmark
        all_results["retrieval"] = run_retrieval_benchmark()
    except Exception as e:
        logger.error(f"Retrieval benchmark failed: {e}")
        all_results["retrieval"] = {"error": str(e)}

    # 3. End-to-end benchmark
    print("\n" + "=" * 60)
    print("  Running End-to-End Benchmark")
    print("=" * 60)
    try:
        from evaluation.benchmarks.eval_end_to_end import run_end_to_end_benchmark
        all_results["end_to_end"] = run_end_to_end_benchmark()
    except Exception as e:
        logger.error(f"End-to-end benchmark failed: {e}")
        all_results["end_to_end"] = {"error": str(e)}

    # Save unified results
    result_path = RESULTS_DIR / "full_benchmark.json"
    with open(result_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    # Summary
    print("\n" + "=" * 60)
    print("  BENCHMARK SUMMARY")
    print("=" * 60)

    if "nli" in all_results and "accuracy" in all_results.get("nli", {}):
        nli = all_results["nli"]
        print(f"\n  NLI Accuracy:     {nli['accuracy']:.4f}")
        print(f"  NLI Macro F1:     {nli['macro_f1']:.4f}")

    if "retrieval" in all_results and "mrr" in all_results.get("retrieval", {}):
        ret = all_results["retrieval"]
        print(f"\n  Retrieval MRR:    {ret['mrr']:.4f}")
        for k, v in ret.get("retrieval_metrics", {}).items():
            print(f"  Retrieval {k}: {v:.4f}")

    if "end_to_end" in all_results and "binary_detection" in all_results.get("end_to_end", {}):
        e2e = all_results["end_to_end"]["binary_detection"]
        print(f"\n  E2E F1:           {e2e['f1']:.4f}")
        print(f"  E2E Precision:    {e2e['precision']:.4f}")
        print(f"  E2E Recall:       {e2e['recall']:.4f}")

    print(f"\n  Full results: {result_path}")
    return all_results


if __name__ == "__main__":
    run_all()
