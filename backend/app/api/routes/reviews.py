"""Human-in-the-loop review workflow for contradictions.

Provides endpoints for reviewers to approve, reject, or reclassify
detected contradictions, feeding into active learning heuristics.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import or_, and_

from app.core.database import get_db
from app.api.deps import get_current_user, forbid_viewer
from app.models.models import (
    ContradictionPair, ReviewStatus, Document, User, Chunk,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reviews", tags=["Reviews"])


# ── Schemas ──────────────────────────────────────────────


class ReviewSubmission(BaseModel):
    review_status: str  # approved, rejected, false_positive, intentional_divergence
    review_reason: str = ""


class ReviewResponse(BaseModel):
    id: str
    review_status: str
    reviewed_by: str | None
    reviewed_at: str | None
    review_reason: str


class ContradictionDetail(BaseModel):
    id: str
    org_id: str
    chunk_a_text: str
    chunk_b_text: str
    doc_a_title: str
    doc_b_title: str
    classification: str
    confidence: float
    explanation: str | None
    review_status: str
    reviewed_by: str | None
    reviewed_at: str | None
    review_reason: str | None
    is_temporal_evolution: bool
    created_at: str


# ── Endpoints ────────────────────────────────────────────


@router.patch("/{contradiction_id}")
async def submit_review(
    contradiction_id: str,
    body: ReviewSubmission,
    session=Depends(get_db),
    current_user: User = Depends(forbid_viewer),
):
    """Submit a review verdict on a contradiction pair."""
    from sqlalchemy import select
    from app.models.models import HeuristicFeedback
    import re
    import uuid

    # Validate review status
    valid_statuses = {"APPROVED", "REJECTED", "FALSE_POSITIVE", "INTENTIONAL_DIVERGENCE"}
    status_upper = body.review_status.upper()
    if status_upper not in valid_statuses:
        raise HTTPException(400, f"Invalid review_status. Must be one of: {valid_statuses}")

    # Scope to the caller's org — a pair in another org must read as 404.
    result = await session.execute(
        select(ContradictionPair).where(
            ContradictionPair.id == contradiction_id,
            ContradictionPair.org_id == current_user.org_id,
        )
    )
    pair = result.scalar_one_or_none()
    if not pair:
        raise HTTPException(404, "Contradiction pair not found")

    old_classification = pair.classification.value if pair.classification else None

    pair.review_status = ReviewStatus(status_upper)
    pair.reviewed_by = current_user.id
    pair.reviewed_at = datetime.now(timezone.utc)
    pair.review_reason = body.review_reason

    # ── Heuristic feedback logging (Change 3) ──
    # If this was an inferred lineage EVOLUTION, log the review for threshold tuning
    if pair.inferred_lineage:
        # Extract heuristic signals from the explanation text
        title_sim = None
        date_gap = None
        sim_match = re.search(r"sim=(\d+\.\d+)", pair.explanation or "")
        if sim_match:
            title_sim = float(sim_match.group(1))
        gap_match = re.search(r"newer by (\d+) days", pair.explanation or "")
        if gap_match:
            date_gap = int(gap_match.group(1))

        feedback = HeuristicFeedback(
            id=uuid.uuid4(),
            pair_id=pair.id,
            org_id=pair.org_id,
            title_similarity_score=title_sim,
            date_gap_days=date_gap,
            department_match=True,  # lineage heuristic requires dept match
            reviewer_decision=status_upper,
            original_classification=old_classification,
            reviewed_by=current_user.id,
        )
        session.add(feedback)
        logger.info(
            f"Heuristic feedback logged: pair={contradiction_id}, "
            f"decision={status_upper}, title_sim={title_sim}, date_gap={date_gap}"
        )

    await session.commit()

    logger.info(
        f"Review submitted: pair={contradiction_id}, "
        f"status={status_upper}, by={current_user.email}"
    )

    return {
        "id": str(pair.id),
        "review_status": pair.review_status.value,
        "reviewed_by": str(current_user.id),
        "reviewed_at": pair.reviewed_at.isoformat(),
        "review_reason": pair.review_reason,
    }


@router.get("")
async def list_contradictions(
    review_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List contradiction pairs with optional filtering by review status."""
    from sqlalchemy import select, func

    # Always scoped to the caller's org — no caller-supplied org override.
    query = select(ContradictionPair).where(
        ContradictionPair.org_id == current_user.org_id
    )

    if review_status:
        try:
            status_enum = ReviewStatus(review_status.upper())
            query = query.where(ContradictionPair.review_status == status_enum)
        except ValueError:
            raise HTTPException(400, f"Invalid review_status: {review_status}")

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar()

    # Fetch page
    query = query.order_by(ContradictionPair.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    pairs = result.scalars().all()

    items = []
    for p in pairs:
        # Fetch chunk texts and document titles
        chunk_a = await session.get(Chunk, p.chunk_a_id)
        chunk_b = await session.get(Chunk, p.chunk_b_id)
        doc_a = await session.get(Document, chunk_a.document_id) if chunk_a else None
        doc_b = await session.get(Document, chunk_b.document_id) if chunk_b else None

        items.append({
            "id": str(p.id),
            "chunk_a_text": chunk_a.content[:300] if chunk_a else "",
            "chunk_b_text": chunk_b.content[:300] if chunk_b else "",
            "doc_a_title": doc_a.title if doc_a else "Unknown",
            "doc_b_title": doc_b.title if doc_b else "Unknown",
            "classification": p.classification.value if p.classification else "",
            "confidence": p.confidence,
            "explanation": p.explanation,
            "review_status": p.review_status.value if p.review_status else "PENDING",
            "reviewed_by": str(p.reviewed_by) if p.reviewed_by else None,
            "reviewed_at": p.reviewed_at.isoformat() if p.reviewed_at else None,
            "review_reason": p.review_reason,
            "is_temporal_evolution": p.is_temporal_evolution or False,
            "inferred_lineage": p.inferred_lineage or False,
            "explanation_valid": p.explanation_valid if p.explanation_valid is not None else True,
            "sampled": getattr(p, "sampled", False) or False,
            "gate_similarity": getattr(p, "gate_similarity", None),
            "created_at": p.created_at.isoformat(),
        })

    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/stats")
async def review_stats(
    session=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get review workflow statistics for the caller's organization."""
    from sqlalchemy import select, func

    target_org = str(current_user.org_id)

    # Count by review status
    status_query = (
        select(ContradictionPair.review_status, func.count())
        .where(ContradictionPair.org_id == target_org)
        .group_by(ContradictionPair.review_status)
    )
    result = await session.execute(status_query)
    status_counts = {
        (row[0].value if row[0] else "PENDING"): row[1]
        for row in result.all()
    }

    # Count temporal evolutions
    evo_query = (
        select(func.count())
        .where(
            ContradictionPair.org_id == target_org,
            ContradictionPair.is_temporal_evolution == True,
        )
    )
    evo_result = await session.execute(evo_query)
    temporal_evolutions = evo_result.scalar() or 0

    total = sum(status_counts.values())
    reviewed = total - status_counts.get("PENDING", 0)

    return {
        "total_pairs": total,
        "reviewed": reviewed,
        "pending": status_counts.get("PENDING", 0),
        "approved": status_counts.get("APPROVED", 0),
        "rejected": status_counts.get("REJECTED", 0),
        "false_positive": status_counts.get("FALSE_POSITIVE", 0),
        "intentional_divergence": status_counts.get("INTENTIONAL_DIVERGENCE", 0),
        "temporal_evolutions": temporal_evolutions,
        "review_rate": round(reviewed / max(total, 1), 4),
    }


@router.post("/{contradiction_id}/explain")
async def generate_explanation(
    contradiction_id: str,
    session=Depends(get_db),
    current_user: User = Depends(forbid_viewer),
):
    """Generate an LLM explanation for a contradiction (lazy mode).

    Called when user views a contradiction that only has a template explanation.
    Generates a rich explanation via Groq/Gemini and caches it in the DB.
    """
    from sqlalchemy import select
    from app.contradiction.detector import generate_explanation_on_demand

    # Scope to the caller's org so this can't trigger an LLM call on another
    # tenant's data.
    result = await session.execute(
        select(ContradictionPair).where(
            ContradictionPair.id == contradiction_id,
            ContradictionPair.org_id == current_user.org_id,
        )
    )
    pair = result.scalar_one_or_none()
    if not pair:
        raise HTTPException(404, "Contradiction pair not found")

    # Check if already has a real explanation (not template)
    if pair.explanation and "Contradiction detected with" not in pair.explanation:
        return {"explanation": pair.explanation, "cached": True}

    # Fetch claim texts
    chunk_a = await session.get(Chunk, pair.chunk_a_id)
    chunk_b = await session.get(Chunk, pair.chunk_b_id)

    claim_a = chunk_a.content[:500] if chunk_a else ""
    claim_b = chunk_b.content[:500] if chunk_b else ""

    # Generate explanation (sync call — fast enough for single pair)
    import asyncio
    explanation = await asyncio.to_thread(
        generate_explanation_on_demand, claim_a, claim_b, pair.confidence
    )

    # Cache the explanation
    pair.explanation = explanation
    await session.commit()

    logger.info(f"Generated lazy explanation for pair {contradiction_id}")

    return {"explanation": explanation, "cached": False}
