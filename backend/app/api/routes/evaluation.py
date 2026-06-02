"""Evaluation endpoint for system metrics."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.models import Document, Chunk, Alert, Entity, Relation, User

router = APIRouter()


@router.get("/evaluation/metrics")
async def get_metrics(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = user.org_id

    doc_count_q = await db.execute(
        select(func.count(Document.id)).where(Document.org_id == org_id, Document.deleted_at.is_(None))
    )
    doc_count = doc_count_q.scalar() or 0

    chunk_count_q = await db.execute(
        select(func.count(Chunk.id))
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.org_id == org_id)
    )
    chunk_count = chunk_count_q.scalar() or 0

    alert_count_q = await db.execute(
        select(func.count(Alert.id)).where(Alert.org_id == org_id)
    )
    alert_count = alert_count_q.scalar() or 0

    entity_count_q = await db.execute(
        select(func.count(Entity.id)).where(Entity.org_id == org_id)
    )
    entity_count = entity_count_q.scalar() or 0

    relation_count_q = await db.execute(
        select(func.count(Relation.id)).where(Relation.org_id == org_id)
    )
    relation_count = relation_count_q.scalar() or 0

    avg_drift_q = await db.execute(
        select(func.avg(Document.drift_score))
        .where(Document.org_id == org_id, Document.deleted_at.is_(None))
    )
    avg_drift = avg_drift_q.scalar() or 0.0

    return {
        "documents": doc_count,
        "chunks": chunk_count,
        "alerts": alert_count,
        "entities": entity_count,
        "relations": relation_count,
        "average_drift_score": round(float(avg_drift), 2),
    }
