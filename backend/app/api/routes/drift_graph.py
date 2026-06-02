"""Drift scores and Knowledge Graph visualization routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.models import Document, Entity, Relation, User, ContradictionPair
from app.schemas.schemas import (
    DriftScoreResponse,
    DriftScoresListResponse,
    GraphVisualizationResponse,
)

router = APIRouter()


@router.get("/drift/scores", response_model=DriftScoresListResponse)
async def get_drift_scores(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document)
        .where(Document.org_id == user.org_id, Document.deleted_at.is_(None))
        .order_by(Document.drift_score.desc())
        .limit(50)
    )
    docs = result.scalars().all()

    scores = [
        DriftScoreResponse(
            document_id=d.id,
            title=d.title,
            drift_score=d.drift_score or 0.0,
            semantic_drift_score=d.semantic_drift_score or 0.0,
            factual_drift_score=d.factual_drift_score or 0.0,
            drift_type=d.drift_type,
        )
        for d in docs
    ]

    return DriftScoresListResponse(scores=scores)


@router.post("/drift/scan", status_code=202)
async def trigger_drift_scan(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.tasks.tasks import recalculate_drift_scores
    recalculate_drift_scores.delay(org_id=str(user.org_id))
    return {"status": "scan_queued"}


@router.get("/graph/visualize", response_model=GraphVisualizationResponse)
async def visualize_graph(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get knowledge graph in D3.js-compatible format for visualization."""
    entities_q = await db.execute(
        select(Entity).where(Entity.org_id == user.org_id).limit(500)
    )
    entities = entities_q.scalars().all()
    entity_map = {str(e.id): e for e in entities}

    relations_q = await db.execute(
        select(Relation).where(Relation.org_id == user.org_id).limit(1000)
    )
    relations = relations_q.scalars().all()

    nodes = [
        {
            "id": str(e.id),
            "name": e.name,
            "type": e.entity_type,
            "label": e.name.replace("_", " ").title(),
        }
        for e in entities
    ]

    links = [
        {
            "source": str(r.source_entity_id),
            "target": str(r.target_entity_id),
            "relation": r.relation_type,
            "confidence": r.confidence,
        }
        for r in relations
        if str(r.source_entity_id) in entity_map and str(r.target_entity_id) in entity_map
    ]

    # Inject Contradiction Links
    contradictions_q = await db.execute(
        select(ContradictionPair).where(ContradictionPair.org_id == user.org_id)
    )
    contradictions = contradictions_q.scalars().all()

    # Map chunk_id to its entities
    chunk_to_entities: dict[str, list[str]] = {}
    for e in entities:
        if e.source_chunk_id:
            chunk_to_entities.setdefault(str(e.source_chunk_id), []).append(str(e.id))

    for c in contradictions:
        a_entities = chunk_to_entities.get(str(c.chunk_a_id), [])
        b_entities = chunk_to_entities.get(str(c.chunk_b_id), [])

        if a_entities and b_entities:
            links.append({
                "source": a_entities[0],
                "target": b_entities[0],
                "relation": "CONTRADICTS",
                "confidence": c.confidence,
            })

    return GraphVisualizationResponse(nodes=nodes, links=links)


@router.get("/graph/entities")
async def list_entities(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Entity).where(Entity.org_id == user.org_id).limit(200)
    )
    entities = result.scalars().all()
    return [
        {"id": str(e.id), "name": e.name, "type": e.entity_type}
        for e in entities
    ]


@router.get("/drift/topics")
async def get_topic_drift(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Compute topic drift analysis for the organization."""
    from app.core.database import SyncSession
    from app.drift.topic_engine import compute_org_topic_drift

    sync_session = SyncSession()
    try:
        result = compute_org_topic_drift(sync_session, str(user.org_id))
    finally:
        sync_session.close()

    return result
