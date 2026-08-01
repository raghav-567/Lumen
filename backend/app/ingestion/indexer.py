"""ChromaDB vector store operations with collection-per-org isolation.

Collection naming convention:
  - org_{org_id}_chunks  — raw document chunks
  - org_{org_id}_claims  — extracted factual claims

Each org's data is fully isolated at the collection level.
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache

import chromadb
import os

from app.core.config import settings

logger = logging.getLogger(__name__)

# Suppress ChromaDB telemetry errors
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")


@lru_cache(maxsize=1)
def _get_client():
    """Return a process-wide ChromaDB client.

    Prefers the ChromaDB *server* (HttpClient) when CHROMA_HOST is configured so
    that every process — API, Celery workers, and one-off scripts — shares a
    single writer. The embedded PersistentClient opens the on-disk segments
    directly; multiple processes doing that against the same volume corrupt the
    HNSW vector segments (the root cause of post-delete "stale segment" /
    "Label not found" / silently-zeroed drift). HttpClient routes all access
    through the one server process that owns the files.

    Falls back to an embedded PersistentClient for single-process local use and
    tests (which monkeypatch this factory anyway).
    """
    from chromadb.config import Settings as ChromaSettings

    if settings.CHROMA_HOST:
        last_err = None
        # The server may still be coming up when a worker boots; retry briefly.
        for attempt in range(10):
            try:
                client = chromadb.HttpClient(
                    host=settings.CHROMA_HOST,
                    port=settings.CHROMA_PORT,
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
                client.heartbeat()  # fail fast if the server isn't reachable yet
                return client
            except Exception as e:  # noqa: BLE001 — retry any connection error
                last_err = e
                time.sleep(min(2 ** attempt, 10))
        raise RuntimeError(
            f"Could not connect to ChromaDB server at "
            f"{settings.CHROMA_HOST}:{settings.CHROMA_PORT}: {last_err}"
        )

    return chromadb.PersistentClient(
        path=settings.CHROMA_PERSIST_DIR,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


# Process-wide cache of Collection handles, keyed by collection name. A handle is
# a thin reference to a server-side collection; calling get_or_create_collection
# on every access costs a POST /api/v1/collections round-trip (the
# "...already exists, returning existing collection" log storm) — the dominant
# overhead of the per-claim pairwise scan, which fires one query per (claim,
# candidate) pair. The cache can only go stale if a collection is dropped and
# recreated server-side (reindex_chroma.py): hot-path callers (query_similar,
# the embedding scan) self-heal by invalidating and refetching on any Chroma
# error, and the reindex script invalidates explicitly. A stale handle must
# never silently zero retrieval — see the post-delete drift bugs in
# docker-compose.yml.
_COLLECTION_CACHE: "dict[str, chromadb.Collection]" = {}


def _collection_name(org_id: str, name_suffix: str) -> str:
    # Truncate to 63 chars (ChromaDB limit)
    return f"org_{org_id.replace('-', '_')}_{name_suffix}"[:63]


def get_or_create_collection(
    org_id: str, name_suffix: str = "chunks", *, use_cache: bool = True
) -> chromadb.Collection:
    """Get or create a ChromaDB collection scoped to an organization.

    Args:
        org_id: Organization UUID
        name_suffix: 'chunks' or 'claims' — determines the collection type
        use_cache: serve a cached handle when available (default). Pass False to
            force a fresh fetch (e.g. after invalidating a known-stale handle).

    Returns:
        ChromaDB Collection with cosine distance metric
    """
    collection_name = _collection_name(org_id, name_suffix)
    if use_cache:
        cached = _COLLECTION_CACHE.get(collection_name)
        if cached is not None:
            return cached
    client = _get_client()
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    _COLLECTION_CACHE[collection_name] = collection
    return collection


def invalidate_collection_cache(org_id: str | None = None, name_suffix: str | None = None) -> None:
    """Drop cached Collection handles so the next access refetches from the server.

    Call after any op that deletes/recreates a collection (reindex), or when a
    cached handle errors with a stale server-side id. With no args, clears all.
    """
    if org_id is None:
        _COLLECTION_CACHE.clear()
        return
    if name_suffix is not None:
        _COLLECTION_CACHE.pop(_collection_name(org_id, name_suffix), None)
        return
    prefix = f"org_{org_id.replace('-', '_')}_"
    for key in [k for k in _COLLECTION_CACHE if k.startswith(prefix)]:
        _COLLECTION_CACHE.pop(key, None)


def _collection_for_type(org_id: str, is_claim: bool) -> chromadb.Collection:
    """Route to the correct collection based on data type."""
    suffix = "claims" if is_claim else "chunks"
    return get_or_create_collection(org_id, name_suffix=suffix)


def upsert_embeddings(
    org_id: str,
    ids: list[str],
    embeddings: list[list[float]],
    documents: list[str],
    metadatas: list[dict] | None = None,
) -> None:
    """Upsert embeddings into the correct per-org ChromaDB collection.

    Routes to 'claims' or 'chunks' collection based on the 'is_claim'
    metadata field. If not specified, defaults to 'chunks'.
    """
    from app.ingestion.embedder import get_embedding_version

    version = get_embedding_version()
    final_metadatas = []
    for m in (metadatas or [{}] * len(ids)):
        enriched = {**m, "embedding_version": version}
        final_metadatas.append(enriched)

    # Determine collection type from first metadata entry
    is_claim = False
    if final_metadatas and final_metadatas[0].get("is_claim"):
        is_claim = True

    collection = _collection_for_type(org_id, is_claim)
    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=final_metadatas,
    )
    ctype = "claims" if is_claim else "chunks"
    logger.info(f"Upserted {len(ids)} {ctype} for org {org_id} (embed_v={version})")


def query_similar(
    org_id: str,
    query_embedding: list[float],
    top_k: int = 10,
    where_filter: dict | None = None,
) -> dict:
    """Query similar items from the correct per-org ChromaDB collection.

    Routes to 'claims' collection if where_filter contains is_claim=True,
    otherwise queries 'chunks'. With collection-per-org, org_id filtering
    is enforced by collection boundary — no metadata filter needed.
    """
    from app.ingestion.embedder import get_embedding_version

    # Determine which collection to query
    is_claim = False
    if where_filter and where_filter.get("is_claim"):
        is_claim = True

    suffix = "claims" if is_claim else "chunks"

    # Clean the where_filter: remove 'is_claim' since it's now enforced
    # by collection boundary, not metadata
    clean_filter = None
    if where_filter:
        clean_filter = {k: v for k, v in where_filter.items() if k != "is_claim"}
        if not clean_filter:
            clean_filter = None

    _EMPTY = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    def _run():
        collection = get_or_create_collection(org_id, name_suffix=suffix)
        count = collection.count() or 0
        if count == 0:
            return None
        kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": min(top_k, count),
            "include": ["documents", "metadatas", "distances"],
        }
        if clean_filter:
            kwargs["where"] = clean_filter
        return collection.query(**kwargs)

    try:
        results = _run()
    except Exception as e:
        # A cached handle can point at a collection that was dropped/recreated
        # server-side (reindex). Invalidate and retry once with a fresh handle
        # before giving up — a stale handle must not silently zero retrieval.
        logger.warning(f"ChromaDB query failed ({e}); refetching collection and retrying once")
        invalidate_collection_cache(org_id, suffix)
        try:
            results = _run()
        except Exception as e2:
            logger.error(f"ChromaDB query failed after refetch: {e2}")
            return dict(_EMPTY)

    if results is None:  # empty collection
        return dict(_EMPTY)

    # ── Drop ghost results (stale-HNSW guard) ──
    # After a delete, the HNSW segment can return vector labels whose metadata
    # record is already gone, surfacing as None metadata. Every live vector has
    # at least {"embedding_version": ...} (see upsert_embeddings), so a None meta
    # is always a ghost pointing at deleted data. Left in place it crashes the
    # version check below and poisons every downstream consumer (shortlist,
    # pairwise NLI) that reads `meta["document_id"]` — which silently zeroes
    # drift detection. Filter ghosts out so results stay position-aligned.
    metas0 = (results.get("metadatas") or [[]])[0] or []
    if any(m is None for m in metas0):
        keep = [i for i, m in enumerate(metas0) if m is not None]
        ghost = len(metas0) - len(keep)
        for key in ("ids", "documents", "metadatas", "distances"):
            col_vals = results.get(key)
            if col_vals and col_vals[0] is not None:
                results[key] = [[col_vals[0][i] for i in keep]]
        logger.warning(
            f"Dropped {ghost} ghost result(s) with missing metadata for org {org_id} "
            f"(stale HNSW segment after a delete — reindex recommended)."
        )

    # ── Version safety: warn on cross-model results ──
    current_version = get_embedding_version()
    if results.get("metadatas") and results["metadatas"][0]:
        mismatched = 0
        for meta in results["metadatas"][0]:
            stored_version = meta.get("embedding_version")
            if stored_version and stored_version != current_version:
                mismatched += 1
        if mismatched > 0:
            logger.warning(
                f"Embedding version mismatch: {mismatched}/{len(results['metadatas'][0])} "
                f"results have different embedding version (current={current_version}). "
                f"Consider reindexing."
            )

    return results


def delete_by_document(org_id: str, document_id: str) -> None:
    """Delete all embeddings for a document from both collections."""
    for suffix in ("chunks", "claims"):
        collection = get_or_create_collection(org_id, name_suffix=suffix)
        try:
            collection.delete(where={"document_id": document_id})
        except Exception as e:
            logger.warning(f"Failed to delete {suffix} for doc {document_id}: {e}")


def sweep_orphan_vectors(org_id: str, live_document_ids: "set[str] | list[str]") -> dict:
    """Remove vectors whose parent document is no longer live (deleted or gone).

    ChromaDB is not transactionally tied to Postgres: soft-deleting a document
    via `delete_by_document` only runs on the delete path, so historically-deleted
    docs can leave orphan vectors behind. Those orphans pollute retrieval and get
    mis-attributed as contradiction partners. This sweep reconciles the vector
    store against the set of live document IDs.

    Args:
        org_id: Organization UUID.
        live_document_ids: IDs of documents that should be retained. Any vector
            whose `document_id` metadata is not in this set is deleted.

    Returns:
        Per-collection stats: {suffix: {"scanned": n, "deleted": m}}.
    """
    live = {str(d) for d in live_document_ids}
    stats: dict = {}
    for suffix in ("chunks", "claims"):
        collection = get_or_create_collection(org_id, name_suffix=suffix)
        deleted = 0
        scanned = 0
        try:
            got = collection.get(include=["metadatas"])
            ids = got.get("ids", []) or []
            metas = got.get("metadatas", []) or []
            scanned = len(ids)
            orphan_ids = [
                vid
                for vid, meta in zip(ids, metas)
                if str((meta or {}).get("document_id")) not in live
            ]
            if orphan_ids:
                # Delete in batches to stay well under ChromaDB request limits.
                for i in range(0, len(orphan_ids), 500):
                    collection.delete(ids=orphan_ids[i : i + 500])
                deleted = len(orphan_ids)
        except Exception as e:
            logger.warning(f"Orphan sweep failed for {suffix} (org {org_id}): {e}")
        stats[suffix] = {"scanned": scanned, "deleted": deleted}
        if deleted:
            logger.info(f"Orphan sweep: removed {deleted}/{scanned} {suffix} vectors for org {org_id}")
    return stats


def verify_org_collections(org_id: str) -> dict:
    """Verify that both collections exist for an org, creating if missing.

    Returns collection stats for monitoring.
    """
    stats = {}
    for suffix in ("chunks", "claims"):
        collection = get_or_create_collection(org_id, name_suffix=suffix)
        stats[suffix] = {
            "name": collection.name,
            "count": collection.count(),
        }
    return stats


def list_org_collections() -> list[str]:
    """List all collection names in the ChromaDB instance."""
    client = _get_client()
    collections = client.list_collections()
    return [c.name for c in collections]
