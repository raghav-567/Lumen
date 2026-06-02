"""Semantic search route."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.models import Document, Chunk, User
from app.schemas.schemas import SearchRequest, SearchResponse, SearchResultItem

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/search", response_model=SearchResponse)
async def semantic_search(
    req: SearchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.ingestion.embedder import generate_single_embedding
    from app.ingestion.indexer import query_similar

    query_embedding = generate_single_embedding(req.query)
    chroma_results = query_similar(str(user.org_id), query_embedding, top_k=req.top_k)

    results = []
    if chroma_results["ids"] and chroma_results["ids"][0]:
        for i, _id in enumerate(chroma_results["ids"][0]):
            metadata = chroma_results["metadatas"][0][i] if chroma_results["metadatas"] else {}
            text = chroma_results["documents"][0][i] if chroma_results["documents"] else ""
            distance = chroma_results["distances"][0][i] if chroma_results["distances"] else 1.0
            score = max(0.0, 1.0 - distance)

            doc_id = metadata.get("document_id", "")
            doc_title = metadata.get("document_title", "Untitled")

            results.append(SearchResultItem(
                chunk_id=_id,
                document_id=doc_id,
                document_title=doc_title,
                content=text,
                score=round(score, 4),
                page=metadata.get("start_page"),
            ))

    return SearchResponse(results=results, query=req.query, total=len(results))
