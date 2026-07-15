"""Shared evaluation metrics for KnowledgeDrift benchmarking."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any


def precision_recall_f1(y_true: list[str], y_pred: list[str], positive_label: str = "contradiction") -> dict:
    """Compute precision, recall, F1 for a binary classification task."""
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == positive_label and p == positive_label)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t != positive_label and p == positive_label)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == positive_label and p != positive_label)

    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-8)

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "support": sum(1 for t in y_true if t == positive_label),
    }


def confusion_matrix(y_true: list[str], y_pred: list[str], labels: list[str] | None = None) -> dict:
    """Compute confusion matrix."""
    if labels is None:
        labels = sorted(set(y_true + y_pred))

    matrix = {true_label: {pred_label: 0 for pred_label in labels} for true_label in labels}
    for t, p in zip(y_true, y_pred):
        if t in matrix and p in matrix[t]:
            matrix[t][p] += 1

    return {"labels": labels, "matrix": matrix}


def multiclass_report(y_true: list[str], y_pred: list[str]) -> dict:
    """Compute per-class and overall metrics."""
    labels = sorted(set(y_true + y_pred))
    per_class = {}

    for label in labels:
        per_class[label] = precision_recall_f1(y_true, y_pred, positive_label=label)

    # Macro average
    macro_p = sum(m["precision"] for m in per_class.values()) / max(len(labels), 1)
    macro_r = sum(m["recall"] for m in per_class.values()) / max(len(labels), 1)
    macro_f1 = sum(m["f1"] for m in per_class.values()) / max(len(labels), 1)

    # Accuracy
    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    accuracy = correct / max(len(y_true), 1)

    return {
        "per_class": per_class,
        "accuracy": round(accuracy, 4),
        "macro_precision": round(macro_p, 4),
        "macro_recall": round(macro_r, 4),
        "macro_f1": round(macro_f1, 4),
        "total_samples": len(y_true),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels),
    }


def retrieval_metrics(
    queries: list[str],
    retrieved_ids: list[list[str]],
    relevant_ids: list[list[str]],
    k_values: list[int] | None = None,
) -> dict:
    """Compute retrieval quality metrics.

    Args:
        queries: List of query texts
        retrieved_ids: For each query, list of retrieved document IDs in rank order
        relevant_ids: For each query, list of truly relevant document IDs
        k_values: K values for Recall@K (default: [5, 10, 20])
    """
    k_values = k_values or [5, 10, 20]
    n = len(queries)

    recall_at_k = {k: 0.0 for k in k_values}
    mrr_sum = 0.0

    for i in range(n):
        rel_set = set(relevant_ids[i])
        retr = retrieved_ids[i]

        # Recall@K
        for k in k_values:
            hits = len(rel_set & set(retr[:k]))
            recall_at_k[k] += hits / max(len(rel_set), 1)

        # MRR (Mean Reciprocal Rank)
        for rank, rid in enumerate(retr, 1):
            if rid in rel_set:
                mrr_sum += 1.0 / rank
                break

    return {
        f"recall@{k}": round(recall_at_k[k] / max(n, 1), 4) for k in k_values
    } | {
        "mrr": round(mrr_sum / max(n, 1), 4),
        "num_queries": n,
    }


def format_report(metrics: dict, title: str = "Evaluation Report") -> str:
    """Format metrics dict into a readable markdown report."""
    lines = [f"# {title}\n"]

    if "accuracy" in metrics:
        lines.append(f"**Accuracy:** {metrics['accuracy']:.4f}")
        lines.append(f"**Macro F1:** {metrics['macro_f1']:.4f}")
        lines.append(f"**Samples:** {metrics['total_samples']}\n")

        if "per_class" in metrics:
            lines.append("| Class | Precision | Recall | F1 | Support |")
            lines.append("|-------|-----------|--------|-----|---------|")
            for cls, m in metrics["per_class"].items():
                lines.append(f"| {cls} | {m['precision']:.4f} | {m['recall']:.4f} | {m['f1']:.4f} | {m['support']} |")

        if "confusion_matrix" in metrics:
            cm = metrics["confusion_matrix"]
            labels = cm["labels"]
            lines.append(f"\n## Confusion Matrix\n")
            lines.append("| True \\ Pred | " + " | ".join(labels) + " |")
            lines.append("|" + "|".join(["---"] * (len(labels) + 1)) + "|")
            for true_label in labels:
                row = [str(cm["matrix"][true_label][pred_label]) for pred_label in labels]
                lines.append(f"| {true_label} | " + " | ".join(row) + " |")

    return "\n".join(lines)
