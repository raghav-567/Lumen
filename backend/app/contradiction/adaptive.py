"""Active learning heuristics — adaptive threshold calibration.

Uses reviewer feedback patterns to dynamically adjust contradiction
detection thresholds WITHOUT fine-tuning any models.

Signals tracked:
- False positive rate (per org)
- Rejection patterns by document type
- Confidence distribution of rejected vs approved pairs

Adaptations:
- Dynamic NLI confidence threshold
- Document-type-specific suppression
- Repeated false positive suppression
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


def compute_adaptive_threshold(session, org_id: str, base_threshold: float = 0.6) -> float:
    """Adjust NLI confidence threshold based on historical false positive rate.

    If reviewers consistently reject detections (high FP rate), tighten the
    threshold to reduce noise. If FP rate is low, keep threshold relaxed.

    Args:
        session: SQLAlchemy sync session
        org_id: Organization ID
        base_threshold: Starting threshold (default 0.6)

    Returns:
        Adjusted threshold (higher = more conservative)
    """
    from app.models.models import ContradictionPair, ReviewStatus

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    recent_reviews = (
        session.query(ContradictionPair)
        .filter(
            ContradictionPair.org_id == org_id,
            ContradictionPair.reviewed_at.isnot(None),
            ContradictionPair.reviewed_at >= cutoff,
        )
        .all()
    )

    if len(recent_reviews) < 5:
        # Not enough data — use base threshold
        return base_threshold

    false_positives = [
        r for r in recent_reviews
        if r.review_status in (ReviewStatus.FALSE_POSITIVE, ReviewStatus.REJECTED)
    ]
    fp_rate = len(false_positives) / len(recent_reviews)

    # Adaptive adjustment:
    # FP < 10% → keep base (system is working well)
    # FP 10-30% → slight tightening
    # FP > 30% → aggressive tightening (up to 0.85)
    if fp_rate > 0.3:
        adjusted = min(0.85, base_threshold + (fp_rate * 0.3))
    elif fp_rate > 0.1:
        adjusted = min(0.75, base_threshold + (fp_rate * 0.15))
    else:
        adjusted = base_threshold

    logger.info(
        f"Adaptive threshold for org {org_id}: {adjusted:.3f} "
        f"(base={base_threshold}, fp_rate={fp_rate:.2%}, "
        f"reviews={len(recent_reviews)})"
    )
    return round(adjusted, 3)


def get_suppression_rules(session, org_id: str) -> dict:
    """Compute suppression rules from reviewer patterns.

    Returns a dict of rules that should be applied to filter detections
    before surfacing them as alerts.
    """
    from app.models.models import ContradictionPair, ReviewStatus, Chunk, Document

    cutoff = datetime.now(timezone.utc) - timedelta(days=60)

    rejected_pairs = (
        session.query(ContradictionPair)
        .filter(
            ContradictionPair.org_id == org_id,
            ContradictionPair.review_status.in_([
                ReviewStatus.FALSE_POSITIVE,
                ReviewStatus.REJECTED,
            ]),
            ContradictionPair.reviewed_at >= cutoff,
        )
        .all()
    )

    if not rejected_pairs:
        return {"suppressed_doc_type_pairs": [], "min_confidence_override": None}

    # Track rejection patterns by document type pairs
    doc_type_rejections = defaultdict(int)
    doc_type_totals = defaultdict(int)

    for pair in rejected_pairs:
        try:
            chunk_a = session.get(Chunk, pair.chunk_a_id)
            chunk_b = session.get(Chunk, pair.chunk_b_id)
            if not chunk_a or not chunk_b:
                continue

            doc_a = session.get(Document, chunk_a.document_id)
            doc_b = session.get(Document, chunk_b.document_id)
            if not doc_a or not doc_b:
                continue

            type_pair = tuple(sorted([
                doc_a.document_type or "unknown",
                doc_b.document_type or "unknown",
            ]))
            doc_type_rejections[type_pair] += 1
        except Exception:
            continue

    # Count total pairs for the same type combinations
    all_pairs = (
        session.query(ContradictionPair)
        .filter(
            ContradictionPair.org_id == org_id,
            ContradictionPair.reviewed_at >= cutoff,
        )
        .all()
    )

    for pair in all_pairs:
        try:
            chunk_a = session.get(Chunk, pair.chunk_a_id)
            chunk_b = session.get(Chunk, pair.chunk_b_id)
            if not chunk_a or not chunk_b:
                continue

            doc_a = session.get(Document, chunk_a.document_id)
            doc_b = session.get(Document, chunk_b.document_id)
            if not doc_a or not doc_b:
                continue

            type_pair = tuple(sorted([
                doc_a.document_type or "unknown",
                doc_b.document_type or "unknown",
            ]))
            doc_type_totals[type_pair] += 1
        except Exception:
            continue

    # Suppress type pairs with >50% rejection rate
    suppressed_pairs = []
    for type_pair, rejections in doc_type_rejections.items():
        total = doc_type_totals.get(type_pair, rejections)
        rejection_rate = rejections / max(total, 1)
        if rejection_rate > 0.5 and total >= 3:
            suppressed_pairs.append({
                "types": list(type_pair),
                "rejection_rate": round(rejection_rate, 3),
                "total_reviewed": total,
            })
            logger.info(
                f"Suppressing doc type pair {type_pair}: "
                f"{rejection_rate:.0%} rejection rate ({rejections}/{total})"
            )

    return {
        "suppressed_doc_type_pairs": suppressed_pairs,
        "min_confidence_override": None,
        "total_rejected": len(rejected_pairs),
        "total_reviewed": len(all_pairs),
    }


def should_suppress_detection(
    suppression_rules: dict,
    doc_a_type: str | None,
    doc_b_type: str | None,
    confidence: float,
    adaptive_threshold: float,
) -> tuple[bool, str]:
    """Check if a detection should be suppressed based on active learning rules.

    Returns:
        (should_suppress: bool, reason: str)
    """
    # Check confidence threshold
    if confidence < adaptive_threshold:
        return True, f"Below adaptive threshold ({confidence:.3f} < {adaptive_threshold:.3f})"

    # Check document type pair suppression
    if doc_a_type and doc_b_type:
        type_pair = tuple(sorted([doc_a_type or "unknown", doc_b_type or "unknown"]))
        for rule in suppression_rules.get("suppressed_doc_type_pairs", []):
            if tuple(sorted(rule["types"])) == type_pair:
                return True, f"Suppressed doc type pair: {type_pair} ({rule['rejection_rate']:.0%} rejection rate)"

    return False, ""
