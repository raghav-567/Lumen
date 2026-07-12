"""Knowledge propagation analysis — evidence-backed dependency graphs.

Infers document dependencies from real signals (not fake visual graphs):
- Shared entities between documents
- Semantic similarity between chunks (cross-document)
- Explicit citation / title references
- Same department / document lineage

Then traces the impact of a change in one document across all dependent docs.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict

import networkx as nx

logger = logging.getLogger(__name__)


# ── Dependency signals ──────────────────────────────────────


def compute_dependency_strength(
    session,
    doc_a,
    doc_b,
    org_id: str,
) -> tuple[float, list[dict]]:
    """Compute dependency strength between two documents from real signals.

    Returns:
        (strength: 0-1, evidence: list of signal dicts)
    """
    from app.models.models import Chunk, Entity

    signals = []
    total_weight = 0.0

    # ── Signal 1: Shared entities (weight 0.30) ──
    try:
        entities_a = set()
        entities_b = set()

        chunks_a = session.query(Chunk).filter(Chunk.document_id == doc_a.id).all()
        chunks_b = session.query(Chunk).filter(Chunk.document_id == doc_b.id).all()

        chunk_ids_a = [c.id for c in chunks_a]
        chunk_ids_b = [c.id for c in chunks_b]

        if chunk_ids_a:
            ents_a = session.query(Entity).filter(
                Entity.source_chunk_id.in_(chunk_ids_a)
            ).all()
            entities_a = {(e.name.lower(), e.entity_type) for e in ents_a}

        if chunk_ids_b:
            ents_b = session.query(Entity).filter(
                Entity.source_chunk_id.in_(chunk_ids_b)
            ).all()
            entities_b = {(e.name.lower(), e.entity_type) for e in ents_b}

        shared = entities_a & entities_b
        if shared and entities_a and entities_b:
            overlap = len(shared) / min(len(entities_a), len(entities_b))
            score = min(1.0, overlap)
            total_weight += score * 0.30
            signals.append({
                "type": "shared_entities",
                "score": round(score, 3),
                "count": len(shared),
                "examples": [f"{name} ({etype})" for name, etype in list(shared)[:5]],
            })
    except Exception as e:
        logger.debug(f"Entity overlap check failed: {e}")

    # ── Signal 2: Semantic similarity (weight 0.25) ──
    try:
        from app.ingestion.embedder import generate_embeddings
        import numpy as np

        texts_a = [c.content[:500] for c in chunks_a[:5]]
        texts_b = [c.content[:500] for c in chunks_b[:5]]

        if texts_a and texts_b:
            emb_a = np.array(generate_embeddings(texts_a))
            emb_b = np.array(generate_embeddings(texts_b))
            sim_matrix = np.dot(emb_a, emb_b.T)
            max_sim = float(sim_matrix.max())
            avg_sim = float(sim_matrix.mean())

            if max_sim > 0.7:
                score = min(1.0, (max_sim - 0.7) / 0.3)  # Normalize 0.7-1.0 → 0-1
                total_weight += score * 0.25
                signals.append({
                    "type": "semantic_similarity",
                    "score": round(score, 3),
                    "max_similarity": round(max_sim, 3),
                    "avg_similarity": round(avg_sim, 3),
                })
    except Exception as e:
        logger.debug(f"Semantic similarity check failed: {e}")

    # ── Signal 3: Explicit citation / title reference (weight 0.25) ──
    try:
        title_b_lower = doc_b.title.lower()
        title_a_lower = doc_a.title.lower()

        # Check if doc_a mentions doc_b's title (or vice versa)
        a_cites_b = any(
            title_b_lower in c.content.lower()
            for c in chunks_a
        ) if len(title_b_lower) > 5 else False

        b_cites_a = any(
            title_a_lower in c.content.lower()
            for c in chunks_b
        ) if len(title_a_lower) > 5 else False

        if a_cites_b or b_cites_a:
            score = 1.0 if (a_cites_b and b_cites_a) else 0.7
            total_weight += score * 0.25
            signals.append({
                "type": "explicit_citation",
                "score": round(score, 3),
                "a_cites_b": a_cites_b,
                "b_cites_a": b_cites_a,
            })
    except Exception as e:
        logger.debug(f"Citation check failed: {e}")

    # ── Signal 4: Same department (weight 0.20) ──
    try:
        dept_a = (doc_a.owner_department or "").strip().lower()
        dept_b = (doc_b.owner_department or "").strip().lower()

        if dept_a and dept_b and dept_a == dept_b:
            score = 0.5  # Same department is weak signal alone
            total_weight += score * 0.20
            signals.append({
                "type": "same_department",
                "score": round(score, 3),
                "department": dept_a,
            })
    except Exception as e:
        logger.debug(f"Department check failed: {e}")

    return round(total_weight, 4), signals


# ── Graph building ──────────────────────────────────────


def build_dependency_graph(session, org_id: str, min_strength: float = 0.15) -> nx.DiGraph:
    """Build an evidence-backed dependency graph for all documents in an org.

    Only adds edges where real dependency signals exist above the threshold.
    """
    from app.models.models import Document

    docs = (
        session.query(Document)
        .filter(Document.org_id == org_id, Document.deleted_at.is_(None))
        .all()
    )

    G = nx.DiGraph()
    for doc in docs:
        G.add_node(str(doc.id), title=doc.title, authority=doc.authority_level or 3)

    # Compare all document pairs (O(n²) but n is typically small per org)
    for i, doc_a in enumerate(docs):
        for doc_b in docs[i + 1:]:
            strength, evidence = compute_dependency_strength(
                session, doc_a, doc_b, org_id
            )
            if strength >= min_strength:
                G.add_edge(
                    str(doc_a.id), str(doc_b.id),
                    weight=strength,
                    evidence=evidence,
                )
                G.add_edge(
                    str(doc_b.id), str(doc_a.id),
                    weight=strength,
                    evidence=evidence,
                )

    logger.info(
        f"Built dependency graph for org {org_id}: "
        f"{G.number_of_nodes()} nodes, {G.number_of_edges()} edges"
    )
    return G


# ── Impact tracing ──────────────────────────────────────


def trace_impact(
    graph: nx.DiGraph,
    changed_doc_id: str,
    max_depth: int = 3,
) -> list[dict]:
    """BFS from a changed document to find all potentially affected documents.

    Returns list of affected docs sorted by impact severity (proximity × edge weight).
    """
    if changed_doc_id not in graph:
        return []

    affected = []
    visited = {changed_doc_id}
    queue = [(changed_doc_id, 0, 1.0)]  # (node_id, depth, cumulative_weight)

    while queue:
        current, depth, cum_weight = queue.pop(0)

        if depth >= max_depth:
            continue

        for neighbor in graph.successors(current):
            if neighbor in visited:
                continue

            visited.add(neighbor)
            edge_data = graph.get_edge_data(current, neighbor, default={})
            edge_weight = edge_data.get("weight", 0.1)
            new_cum_weight = cum_weight * edge_weight

            node_data = graph.nodes.get(neighbor, {})
            affected.append({
                "document_id": neighbor,
                "title": node_data.get("title", "Unknown"),
                "authority_level": node_data.get("authority", 3),
                "depth": depth + 1,
                "impact_score": round(new_cum_weight, 4),
                "evidence": edge_data.get("evidence", []),
            })

            queue.append((neighbor, depth + 1, new_cum_weight))

    # Sort by impact score descending
    affected.sort(key=lambda x: x["impact_score"], reverse=True)
    return affected
