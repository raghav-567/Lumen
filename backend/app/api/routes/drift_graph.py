"""Drift scores and Knowledge Graph visualization routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, forbid_viewer
from app.core.config import settings
from app.core.database import get_db
from app.core.ratelimit import rate_limit
from app.models.models import Document, Entity, Relation, User, ContradictionPair, Claim, Chunk
from app.schemas.schemas import (
    DriftScoreResponse,
    DriftScoresListResponse,
    GraphVisualizationResponse,
)

router = APIRouter()


def build_document_contradiction_graph(documents, pairs, claim_to_doc, chunk_to_doc):
    """Assemble a document-contradiction graph from data we already have.

    Nodes = live documents. Edges = one per unordered document pair that shares ≥1
    contradiction, weighted by the number of claim-grain ContradictionPairs between
    the two docs. Pure function (no DB) so it can be unit-tested directly.

    Args:
        documents: iterable of Document ORM rows (already filtered to live + org).
        pairs: iterable of ContradictionPair rows for the org.
        claim_to_doc: {str(claim_id): str(document_id)} for live docs.
        chunk_to_doc: {str(chunk_id): str(document_id)} for live docs (fallback path).

    Returns:
        (nodes, links) as lists of plain dicts matching GraphVisualizationResponse.
    """
    from collections import defaultdict

    live_doc_ids = {str(d.id) for d in documents}

    nodes = [
        {
            "id": str(d.id),
            "name": d.title or d.filename,
            "type": "DOCUMENT",
            "label": d.title or d.filename,
            "drift_score": d.drift_score or 0.0,
            "factual_drift": d.factual_drift_score or 0.0,
            "semantic_drift": d.semantic_drift_score or 0.0,
        }
        for d in documents
    ]

    def _resolve_doc(claim_id, chunk_id):
        # Prefer the direct claim→document path (claim-grain); fall back to chunk.
        if claim_id is not None:
            did = claim_to_doc.get(str(claim_id))
            if did:
                return did
        if chunk_id is not None:
            return chunk_to_doc.get(str(chunk_id))
        return None

    groups: dict = defaultdict(lambda: {"weight": 0, "max": 0.0, "sum": 0.0, "types": defaultdict(int)})
    for p in pairs:
        doc_a = _resolve_doc(p.claim_a_id, p.chunk_a_id)
        doc_b = _resolve_doc(p.claim_b_id, p.chunk_b_id)
        if not doc_a or not doc_b or doc_a == doc_b:
            continue  # unresolved or self-pair
        if doc_a not in live_doc_ids or doc_b not in live_doc_ids:
            continue  # defensive: skip pairs touching deleted docs (post-P0 shouldn't happen)
        key = tuple(sorted((doc_a, doc_b)))
        g = groups[key]
        conf = p.confidence or 0.0
        g["weight"] += 1
        g["max"] = max(g["max"], conf)
        g["sum"] += conf
        if p.contradiction_type:
            g["types"][p.contradiction_type] += 1

    links = [
        {
            "source": a,
            "target": b,
            "relation": "CONTRADICTS",
            "confidence": round(g["max"], 4),
            "weight": g["weight"],
            "avg_confidence": round(g["sum"] / g["weight"], 4),
            "types": dict(g["types"]),
        }
        for (a, b), g in groups.items()
    ]

    return nodes, links


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


@router.post(
    "/drift/scan",
    status_code=202,
    dependencies=[Depends(rate_limit(settings.SCAN_RATE_LIMIT))],
)
async def trigger_drift_scan(
    user: User = Depends(forbid_viewer),
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
    """Document-contradiction graph: nodes = live docs, edges = inter-doc contradictions.

    Built entirely from the ContradictionPair table (claim-grain) — no entity
    extraction, no LLM. Edge weight = number of contradicting claim pairs between two
    documents. (The legacy Entity/Relation graph is retained in the models and
    `graph/builder.py` for a possible future feature, but this route no longer depends
    on it — entity extraction was never wired into the pipeline.)
    """
    # Nodes: live documents in the org.
    docs_q = await db.execute(
        select(Document).where(Document.org_id == user.org_id, Document.deleted_at.is_(None))
    )
    documents = docs_q.scalars().all()

    # Resolution maps (live docs only): claim/chunk id -> document id.
    claim_rows = await db.execute(
        select(Claim.id, Claim.document_id)
        .join(Document, Claim.document_id == Document.id)
        .where(Document.org_id == user.org_id, Document.deleted_at.is_(None))
    )
    claim_to_doc = {str(cid): str(did) for cid, did in claim_rows.all()}

    chunk_rows = await db.execute(
        select(Chunk.id, Chunk.document_id)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.org_id == user.org_id, Document.deleted_at.is_(None))
    )
    chunk_to_doc = {str(cid): str(did) for cid, did in chunk_rows.all()}

    # Edges: contradiction pairs grouped by document pair.
    pairs_q = await db.execute(
        select(ContradictionPair).where(ContradictionPair.org_id == user.org_id)
    )
    pairs = pairs_q.scalars().all()

    nodes, links = build_document_contradiction_graph(documents, pairs, claim_to_doc, chunk_to_doc)
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
