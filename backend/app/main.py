"""FastAPI application entry-point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import get_current_user, require_admin
from app.core.config import settings
from app.core.database import create_tables
from app.models.models import User

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs on startup / shutdown."""
    from app.core.logging import configure_logging
    configure_logging()
    logger.info("Starting %s …", settings.APP_NAME)
    await create_tables()
    yield
    logger.info("Shutting down %s …", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    description="AI-powered knowledge drift detection system",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────
# Locked to the configured frontend origin(s) — never "*" with credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Correlation ID Middleware ─────────────────────────────
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class CorrelationIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        from app.core.logging import set_correlation_id
        cid = request.headers.get("X-Correlation-ID") or None
        cid = set_correlation_id(cid)
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        return response

app.add_middleware(CorrelationIDMiddleware)

# ── Routes ────────────────────────────────────────────
from app.api.routes import auth, documents, alerts, drift_graph, search, evaluation, reviews, admin  # noqa

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["Documents"])
app.include_router(alerts.router, prefix="/api/v1/alerts", tags=["Alerts"])
app.include_router(drift_graph.router, prefix="/api/v1", tags=["Drift & Graph"])
app.include_router(search.router, prefix="/api/v1", tags=["Search"])
app.include_router(evaluation.router, prefix="/api/v1", tags=["Evaluation"])
app.include_router(reviews.router, prefix="/api/v1", tags=["Reviews"])
app.include_router(admin.router, prefix="/api/v1", tags=["Admin"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.APP_NAME}


@app.get("/health/deep")
async def deep_health(_: "User" = Depends(get_current_user)):
    """Deep health check — probes all dependencies.

    Gated behind auth: it discloses internal topology (model names, collection
    counts) that shouldn't be public.
    """
    import time
    checks = {}

    # Postgres
    try:
        from sqlalchemy import text
        from app.core.database import get_db
        async for db in get_db():
            start = time.monotonic()
            await db.execute(text("SELECT 1"))
            checks["postgres"] = {
                "status": "ok",
                "latency_ms": round((time.monotonic() - start) * 1000, 1),
            }
    except Exception as e:
        checks["postgres"] = {"status": "error", "error": str(e)[:200]}

    # Redis
    try:
        import redis as redis_lib
        start = time.monotonic()
        r = redis_lib.Redis.from_url(settings.REDIS_URL, socket_timeout=3)
        r.ping()
        checks["redis"] = {
            "status": "ok",
            "latency_ms": round((time.monotonic() - start) * 1000, 1),
        }
    except Exception as e:
        checks["redis"] = {"status": "error", "error": str(e)[:200]}

    # ChromaDB
    try:
        from app.ingestion.indexer import _get_client
        start = time.monotonic()
        client = _get_client()
        collections = client.list_collections()
        checks["chromadb"] = {
            "status": "ok",
            "collections": len(collections),
            "latency_ms": round((time.monotonic() - start) * 1000, 1),
        }
    except Exception as e:
        checks["chromadb"] = {"status": "error", "error": str(e)[:200]}

    # Ollama
    try:
        import httpx
        start = time.monotonic()
        resp = httpx.get(f"{settings.OLLAMA_URL}/api/tags", timeout=3)
        models = resp.json().get("models", [])
        checks["ollama"] = {
            "status": "ok",
            "models": [m["name"] for m in models],
            "latency_ms": round((time.monotonic() - start) * 1000, 1),
        }
    except Exception as e:
        checks["ollama"] = {"status": "degraded", "error": str(e)[:200]}

    # Celery
    try:
        from app.tasks.worker import celery_app
        start = time.monotonic()
        inspect = celery_app.control.inspect(timeout=2)
        active = inspect.active() or {}
        checks["celery"] = {
            "status": "ok",
            "workers": len(active),
            "latency_ms": round((time.monotonic() - start) * 1000, 1),
        }
    except Exception as e:
        checks["celery"] = {"status": "error", "error": str(e)[:200]}

    all_ok = all(c.get("status") == "ok" for c in checks.values())
    overall = "ok" if all_ok else "degraded"

    return {
        "status": overall,
        "service": settings.APP_NAME,
        "checks": checks,
    }


@app.get("/metrics")
async def pipeline_metrics(current_user: User = Depends(require_admin)):
    """Aggregate pipeline metrics for observability.

    Admin-only and scoped to the caller's organization — never global across
    tenants.
    """
    from sqlalchemy import select, func
    from app.core.database import get_db
    from app.models.models import (
        Document, Claim, Chunk, ContradictionPair,
        Alert, ProcessingStatus, ReviewStatus,
    )

    org_id = current_user.org_id

    async for db in get_db():
        # Document counts by processing status (this org only)
        status_query = (
            select(Document.processing_status, func.count())
            .where(Document.org_id == org_id)
            .group_by(Document.processing_status)
        )
        result = await db.execute(status_query)
        doc_status = {
            (row[0].value if row[0] else "unknown"): row[1]
            for row in result.all()
        }

        # Totals (org-scoped; chunks/claims join through Document)
        total_docs = sum(doc_status.values())
        total_chunks = (await db.execute(
            select(func.count(Chunk.id))
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.org_id == org_id)
        )).scalar() or 0
        total_claims = (await db.execute(
            select(func.count(Claim.id))
            .join(Document, Claim.document_id == Document.id)
            .where(Document.org_id == org_id)
        )).scalar() or 0
        total_contradictions = (await db.execute(
            select(func.count(ContradictionPair.id))
            .where(ContradictionPair.org_id == org_id)
        )).scalar() or 0
        total_alerts = (await db.execute(
            select(func.count(Alert.id)).where(Alert.org_id == org_id)
        )).scalar() or 0

        # Review stats (org-scoped)
        review_query = (
            select(ContradictionPair.review_status, func.count())
            .where(ContradictionPair.org_id == org_id)
            .group_by(ContradictionPair.review_status)
        )
        result = await db.execute(review_query)
        review_stats = {
            (row[0].value if row[0] else "PENDING"): row[1]
            for row in result.all()
        }

        # Temporal evolution count (org-scoped)
        evo_count = (await db.execute(
            select(func.count(ContradictionPair.id))
            .where(
                ContradictionPair.org_id == org_id,
                ContradictionPair.is_temporal_evolution == True,
            )
        )).scalar() or 0

        # Average drift score (org-scoped)
        avg_drift = (await db.execute(
            select(func.avg(Document.drift_score))
            .where(Document.org_id == org_id, Document.deleted_at.is_(None))
        )).scalar() or 0.0

        return {
            "pipeline": {
                "total_documents": total_docs,
                "document_status": doc_status,
                "total_chunks": total_chunks,
                "total_claims": total_claims,
                "claims_per_doc": round(total_claims / max(total_docs, 1), 1),
            },
            "detection": {
                "total_contradictions": total_contradictions,
                "temporal_evolutions": evo_count,
                "genuine_contradictions": total_contradictions - evo_count,
                "total_alerts": total_alerts,
            },
            "review": review_stats,
            "drift": {
                "avg_drift_score": round(float(avg_drift), 2),
            },
            "optimization": {
                "noise_filter": settings.NOISE_FILTER_ENABLED,
                "dedup": settings.DEDUP_ENABLED,
                "cluster_routing": settings.CLUSTER_ROUTING_ENABLED,
                "similarity_gate": settings.SIMILARITY_GATE_THRESHOLD,
                "reranker": settings.RERANK_ENABLED,
                "lazy_explanations": settings.LAZY_EXPLANATIONS,
                "dynamic_retrieval": settings.DYNAMIC_RETRIEVAL,
            },
        }
