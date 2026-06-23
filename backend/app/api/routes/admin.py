"""Admin endpoints for pipeline calibration and diagnostics.

Provides data-driven threshold tuning based on sampled gate pairs
and other operational insights.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, case, and_

from app.core.database import get_db
from app.api.deps import get_current_user, require_admin
from app.models.models import ContradictionPair, User, ContradictionClassification, HeuristicFeedback
from app.core.config import settings

logger = logging.getLogger(__name__)
# Every admin endpoint requires the ADMIN role (enforced at the router level)
# and is scoped to the caller's own org — no caller-supplied org override.
router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(require_admin)])


@router.get("/gate-calibration")
async def gate_calibration(
    session=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Analyze sampled below-threshold pairs to validate the similarity gate.

    Returns:
        - Total sampled pairs
        - How many were actual contradictions (NLI confirmed)
        - Contradiction rate among sampled pairs
        - Similarity distribution of sampled contradictions
        - Recommended threshold adjustment
    """
    target_org = str(current_user.org_id)

    # Count all sampled pairs
    total_sampled = (await session.execute(
        select(func.count(ContradictionPair.id))
        .where(ContradictionPair.org_id == target_org, ContradictionPair.sampled == True)
    )).scalar() or 0

    # Count all non-sampled pairs (above threshold)
    total_above_threshold = (await session.execute(
        select(func.count(ContradictionPair.id))
        .where(ContradictionPair.org_id == target_org, ContradictionPair.sampled == False)
    )).scalar() or 0

    # Among sampled: how many were contradictions vs not
    sampled_contradictions = (await session.execute(
        select(func.count(ContradictionPair.id))
        .where(
            ContradictionPair.org_id == target_org,
            ContradictionPair.sampled == True,
            ContradictionPair.classification == ContradictionClassification.CONTRADICTORY,
        )
    )).scalar() or 0

    # Similarity stats for sampled contradictions
    sim_stats = (await session.execute(
        select(
            func.avg(ContradictionPair.gate_similarity),
            func.min(ContradictionPair.gate_similarity),
            func.max(ContradictionPair.gate_similarity),
        )
        .where(
            ContradictionPair.org_id == target_org,
            ContradictionPair.sampled == True,
            ContradictionPair.classification == ContradictionClassification.CONTRADICTORY,
        )
    )).one()

    # Similarity stats for ALL detected pairs (above threshold)
    above_sim_stats = (await session.execute(
        select(
            func.avg(ContradictionPair.gate_similarity),
            func.min(ContradictionPair.gate_similarity),
        )
        .where(
            ContradictionPair.org_id == target_org,
            ContradictionPair.sampled == False,
            ContradictionPair.gate_similarity.isnot(None),
        )
    )).one()

    # Compute recommendation
    sampled_contradiction_rate = (
        sampled_contradictions / max(total_sampled, 1)
    )

    current_threshold = settings.SIMILARITY_GATE_THRESHOLD
    recommended = current_threshold

    if total_sampled >= 10:
        if sampled_contradiction_rate > 0.15:
            # >15% of below-threshold pairs are real contradictions — threshold too aggressive
            if sim_stats[0]:  # avg similarity of sampled contradictions
                recommended = max(0.5, float(sim_stats[1]) - 0.05)  # 5% below min sampled contradiction
        elif sampled_contradiction_rate < 0.02:
            # <2% — threshold could be raised for more efficiency
            recommended = min(0.90, current_threshold + 0.03)

    return {
        "current_threshold": current_threshold,
        "sample_rate": settings.GATE_SAMPLE_RATE,
        "total_sampled_pairs": total_sampled,
        "total_above_threshold_pairs": total_above_threshold,
        "sampled_contradictions": sampled_contradictions,
        "sampled_contradiction_rate": round(sampled_contradiction_rate, 4),
        "sampled_similarity": {
            "avg": round(float(sim_stats[0]), 4) if sim_stats[0] else None,
            "min": round(float(sim_stats[1]), 4) if sim_stats[1] else None,
            "max": round(float(sim_stats[2]), 4) if sim_stats[2] else None,
        },
        "above_threshold_similarity": {
            "avg": round(float(above_sim_stats[0]), 4) if above_sim_stats[0] else None,
            "min": round(float(above_sim_stats[1]), 4) if above_sim_stats[1] else None,
        },
        "recommendation": {
            "action": (
                "LOWER_THRESHOLD" if sampled_contradiction_rate > 0.15
                else "RAISE_THRESHOLD" if total_sampled >= 10 and sampled_contradiction_rate < 0.02
                else "NO_CHANGE"
            ),
            "suggested_threshold": round(recommended, 3),
            "reason": (
                f"{sampled_contradiction_rate*100:.1f}% of sampled below-threshold pairs are real contradictions — threshold may be too aggressive"
                if sampled_contradiction_rate > 0.15
                else f"Only {sampled_contradiction_rate*100:.1f}% contradiction rate in samples — threshold could be tightened"
                if total_sampled >= 10 and sampled_contradiction_rate < 0.02
                else f"Insufficient data ({total_sampled} samples, need ≥10) or rate ({sampled_contradiction_rate*100:.1f}%) in acceptable range"
            ),
        },
    }


@router.get("/lineage-heuristic-stats")
async def lineage_heuristic_stats(
    session=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Analyze reviewer feedback on inferred lineage decisions.

    Returns:
        - Total inferred evolutions
        - Total reviewed (with breakdown by decision)
        - Override rate (how often reviewers disagreed with the heuristic)
        - Average title_similarity and date_gap for confirmed vs overridden
    """
    target_org = str(current_user.org_id)

    # Total inferred lineage pairs
    total_inferred = (await session.execute(
        select(func.count(ContradictionPair.id))
        .where(
            ContradictionPair.org_id == target_org,
            ContradictionPair.inferred_lineage == True,
        )
    )).scalar() or 0

    # Total feedback entries
    total_feedback = (await session.execute(
        select(func.count(HeuristicFeedback.id))
        .where(HeuristicFeedback.org_id == target_org)
    )).scalar() or 0

    # Overrides: reviewer marked as REJECTED or FALSE_POSITIVE (disagreed with EVOLUTION)
    override_decisions = {"REJECTED", "FALSE_POSITIVE"}

    overrides = (await session.execute(
        select(func.count(HeuristicFeedback.id))
        .where(
            HeuristicFeedback.org_id == target_org,
            HeuristicFeedback.reviewer_decision.in_(override_decisions),
        )
    )).scalar() or 0

    confirmations = total_feedback - overrides
    override_rate = overrides / max(total_feedback, 1)

    # Stats for overrides
    override_stats = (await session.execute(
        select(
            func.avg(HeuristicFeedback.title_similarity_score),
            func.avg(HeuristicFeedback.date_gap_days),
        )
        .where(
            HeuristicFeedback.org_id == target_org,
            HeuristicFeedback.reviewer_decision.in_(override_decisions),
        )
    )).one()

    # Stats for confirmations
    confirm_stats = (await session.execute(
        select(
            func.avg(HeuristicFeedback.title_similarity_score),
            func.avg(HeuristicFeedback.date_gap_days),
        )
        .where(
            HeuristicFeedback.org_id == target_org,
            HeuristicFeedback.reviewer_decision.notin_(override_decisions),
        )
    )).one()

    return {
        "total_inferred_evolutions": total_inferred,
        "total_reviewed": total_feedback,
        "overrides": overrides,
        "confirmations": confirmations,
        "override_rate": round(override_rate, 4),
        "overridden_signals": {
            "avg_title_similarity": round(float(override_stats[0]), 4) if override_stats[0] else None,
            "avg_date_gap_days": round(float(override_stats[1]), 1) if override_stats[1] else None,
        },
        "confirmed_signals": {
            "avg_title_similarity": round(float(confirm_stats[0]), 4) if confirm_stats[0] else None,
            "avg_date_gap_days": round(float(confirm_stats[1]), 1) if confirm_stats[1] else None,
        },
        "recommendation": (
            f"High override rate ({override_rate*100:.1f}%) — consider raising title_similarity threshold above 0.85"
            if total_feedback >= 5 and override_rate > 0.3
            else f"Low override rate ({override_rate*100:.1f}%) — heuristic performing well"
            if total_feedback >= 5
            else f"Insufficient data ({total_feedback} reviews, need ≥5 for reliable stats)"
        ),
    }


@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """Get persistent task status from Postgres result backend.

    Unlike Redis-backed results, these survive restarts and are queryable
    for up to 7 days after completion (configurable via result_expires).
    """
    from app.tasks.worker import celery_app

    result = celery_app.AsyncResult(task_id)

    response = {
        "task_id": task_id,
        "status": result.status,  # PENDING, STARTED, SUCCESS, FAILURE, RETRY, REVOKED
        "ready": result.ready(),
        "successful": result.successful() if result.ready() else None,
    }

    if result.ready():
        if result.successful():
            task_result = result.result
            # Truncate large results
            if isinstance(task_result, dict):
                response["result"] = task_result
            elif isinstance(task_result, str) and len(task_result) > 1000:
                response["result"] = task_result[:1000] + "..."
            else:
                response["result"] = task_result
        else:
            response["error"] = str(result.result)
            response["traceback"] = result.traceback[:2000] if result.traceback else None

    # Extended info (available with result_extended=True)
    if hasattr(result, "name") and result.name:
        response["task_name"] = result.name
    if hasattr(result, "date_done") and result.date_done:
        response["completed_at"] = str(result.date_done)

    return response


@router.get("/drift-weights")
async def get_drift_weights(
    session=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current drift scoring weights for the caller's org."""
    from app.models.models import OrgDriftWeights

    target_org = str(current_user.org_id)
    result = await session.execute(
        select(OrgDriftWeights).where(OrgDriftWeights.org_id == target_org)
    )
    weights = result.scalar_one_or_none()

    if not weights:
        return {
            "org_id": target_org,
            "source": "defaults",
            "density_weight": 0.45,
            "confidence_weight": 0.35,
            "volume_weight": 0.20,
            "factual_weight": 0.60,
            "semantic_weight": 0.40,
        }

    return {
        "org_id": target_org,
        "source": "custom",
        "density_weight": weights.density_weight,
        "confidence_weight": weights.confidence_weight,
        "volume_weight": weights.volume_weight,
        "factual_weight": weights.factual_weight,
        "semantic_weight": weights.semantic_weight,
        "updated_at": weights.updated_at.isoformat() if weights.updated_at else None,
    }


@router.put("/drift-weights")
async def update_drift_weights(
    body: dict,
    session=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update per-org drift scoring weights. Validates sum constraints."""
    from app.models.models import OrgDriftWeights
    from fastapi import HTTPException
    import uuid

    # Always the caller's own org — ignore any org_id supplied in the body.
    target_org = str(current_user.org_id)

    # Extract weights with defaults
    density = body.get("density_weight", 0.45)
    confidence = body.get("confidence_weight", 0.35)
    volume = body.get("volume_weight", 0.20)
    factual = body.get("factual_weight", 0.60)
    semantic = body.get("semantic_weight", 0.40)

    # Validate sub-signal weights sum to ~1.0
    sub_sum = density + confidence + volume
    if abs(sub_sum - 1.0) > 0.01:
        raise HTTPException(400, f"density + confidence + volume must sum to 1.0 (got {sub_sum:.3f})")

    blend_sum = factual + semantic
    if abs(blend_sum - 1.0) > 0.01:
        raise HTTPException(400, f"factual + semantic must sum to 1.0 (got {blend_sum:.3f})")

    result = await session.execute(
        select(OrgDriftWeights).where(OrgDriftWeights.org_id == target_org)
    )
    weights = result.scalar_one_or_none()

    if weights:
        weights.density_weight = density
        weights.confidence_weight = confidence
        weights.volume_weight = volume
        weights.factual_weight = factual
        weights.semantic_weight = semantic
        weights.updated_by = current_user.id
    else:
        weights = OrgDriftWeights(
            id=uuid.uuid4(),
            org_id=target_org,
            density_weight=density,
            confidence_weight=confidence,
            volume_weight=volume,
            factual_weight=factual,
            semantic_weight=semantic,
            updated_by=current_user.id,
        )
        session.add(weights)

    await session.commit()

    return {
        "org_id": target_org,
        "density_weight": density,
        "confidence_weight": confidence,
        "volume_weight": volume,
        "factual_weight": factual,
        "semantic_weight": semantic,
        "status": "updated",
    }
