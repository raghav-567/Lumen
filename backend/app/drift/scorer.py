"""Dual drift scoring system: Factual + Semantic."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def compute_age_decay(created_at: datetime, half_life_days: float = 90.0) -> float:
    """Calculate age decay factor. Older documents drift more.

    Returns 0..1 where 1 = very old (high drift contribution).
    """
    if not created_at:
        return 0.0
    now = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_days = (now - created_at).total_seconds() / 86400
    decay = 1.0 - math.exp(-0.693 * age_days / half_life_days)  # 0.693 = ln(2)
    return min(1.0, max(0.0, decay))


def compute_dual_drift_score(
    contradiction_ratio: float = 0.0,
    avg_contradiction_confidence: float = 0.0,
    semantic_shift: float = 0.0,
    age_decay: float = 0.0,
    contradiction_count: int = 0,
    aligned_claims_count: int = 0,
    authority_level: int = 3,
    org_weights: dict | None = None,
) -> dict:
    """Compute separate Factual (Inconsistency) and Semantic drift scores.

    Args:
        authority_level: Document authority (1=note, 3=standard, 5=legal master).
                         Higher authority amplifies drift importance.
        org_weights: Optional per-org weight overrides. Keys:
            - density_weight, confidence_weight, volume_weight (factual sub-signals)
            - factual_weight, semantic_weight (combined blend)

    Returns dict with:
    - factual_drift_score: 0..100 (Inconsistency participation score)
    - semantic_drift_score: 0..100
    - combined_drift_score: 0..100
    - drift_type: 'factual' | 'semantic' | 'both' | 'none'
    """
    # ── Resolve weights ──
    w = org_weights or {}
    w_density = w.get("density_weight", 0.45)
    w_confidence = w.get("confidence_weight", 0.35)
    w_volume = w.get("volume_weight", 0.20)
    w_factual = w.get("factual_weight", 0.60)
    w_semantic = w.get("semantic_weight", 0.40)

    # Authority weight: level 3 = 1.0x (neutral), level 5 = 1.67x, level 1 = 0.33x
    authority_weight = (authority_level or 3) / 3.0

    # ── Inconsistency Score (Factual Drift) ──
    if contradiction_count > 0:
        effective_ratio = min(1.0, contradiction_ratio)
        density_signal = 1.0 - math.exp(-3.0 * effective_ratio)
        confidence_signal = avg_contradiction_confidence
        volume_signal = min(1.0, contradiction_count / 5.0)
        inconsistency_raw = (
            density_signal * w_density +
            confidence_signal * w_confidence +
            volume_signal * w_volume
        )
    else:
        inconsistency_raw = 0.0

    # Apply authority weight to factual drift
    factual_drift = min(100.0, inconsistency_raw * 100 * authority_weight)

    # ── Semantic Drift (embedding shift based) ──
    ref_factor = min(1.0, contradiction_count / 10) if contradiction_count > 0 else 0.0
    # Fix 4.1: Age decay contributes when there is ANY signal of inconsistency
    # (contradictions OR semantic shift). Old-but-fully-consistent docs get no penalty.
    has_drift_signal = contradiction_count > 0 or semantic_shift > 0.0
    effective_age_decay = age_decay if has_drift_signal else 0.0
    semantic_raw = (
        semantic_shift * 0.5 +
        effective_age_decay * 0.3 +
        ref_factor * 0.2
    )
    semantic_drift = min(100.0, semantic_raw * 100)

    # ── Combined score (weighted) ──
    combined = w_factual * factual_drift + w_semantic * semantic_drift

    # ── Determine drift type ──
    factual_threshold = 10.0
    semantic_threshold = 10.0

    is_factual = factual_drift >= factual_threshold
    is_semantic = semantic_drift >= semantic_threshold

    if is_factual and is_semantic:
        drift_type = "both"
    elif is_factual:
        drift_type = "factual"
    elif is_semantic:
        drift_type = "semantic"
    else:
        drift_type = "none"

    return {
        "factual_drift_score": round(factual_drift, 2),
        "semantic_drift_score": round(semantic_drift, 2),
        "combined_drift_score": round(combined, 2),
        "drift_type": drift_type,
        "authority_weight": round(authority_weight, 3),
        "weights_used": {
            "density": w_density, "confidence": w_confidence, "volume": w_volume,
            "factual_blend": w_factual, "semantic_blend": w_semantic,
        },
    }

