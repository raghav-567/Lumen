"""Hybrid retrieval engine combining semantic + BM25 keyword search."""

from __future__ import annotations

import logging

from rank_bm25 import BM25Okapi

from app.ingestion.embedder import generate_single_embedding
from app.ingestion.indexer import query_similar

logger = logging.getLogger(__name__)


def hybrid_search(
    org_id: str,
    query: str,
    chunks: list[dict],
    top_k: int = 10,
    semantic_weight: float = 0.6,
) -> list[dict]:
    """Hybrid search combining semantic similarity and BM25 keyword matching.

    Args:
        org_id: Organization ID for ChromaDB collection
        query: Search query string
        chunks: List of chunk dicts with 'content' and 'id' keys
        top_k: Number of results to return
        semantic_weight: Weight for semantic score (1 - this = BM25 weight)
    """
    if not chunks:
        return []

    # Semantic search via ChromaDB
    query_embedding = generate_single_embedding(query)
    semantic_results = query_similar(org_id, query_embedding, top_k=top_k * 2)

    semantic_scores = {}
    if semantic_results["ids"] and semantic_results["ids"][0]:
        for i, cid in enumerate(semantic_results["ids"][0]):
            dist = semantic_results["distances"][0][i] if semantic_results["distances"] else 1.0
            semantic_scores[cid] = max(0.0, 1.0 - dist)

    # BM25 keyword search
    tokenized_chunks = [c["content"].lower().split() for c in chunks]
    chunk_ids = [c.get("id", str(i)) for i, c in enumerate(chunks)]

    bm25 = BM25Okapi(tokenized_chunks)
    bm25_scores_raw = bm25.get_scores(query.lower().split())

    # Normalize BM25 scores
    max_bm25 = max(bm25_scores_raw) if max(bm25_scores_raw) > 0 else 1.0
    bm25_scores = {
        cid: score / max_bm25
        for cid, score in zip(chunk_ids, bm25_scores_raw)
    }

    # Combine scores
    all_ids = set(semantic_scores.keys()) | set(bm25_scores.keys())
    combined = []
    for cid in all_ids:
        sem = semantic_scores.get(cid, 0.0)
        bm = bm25_scores.get(cid, 0.0)
        final = semantic_weight * sem + (1 - semantic_weight) * bm
        combined.append({"id": cid, "score": final, "semantic": sem, "bm25": bm})

    combined.sort(key=lambda x: x["score"], reverse=True)
    return combined[:top_k]
