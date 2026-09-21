"""Re-index chunks and claims from PostgreSQL into ChromaDB (live docs only).

Drops and recreates each org's collections before reindexing, which also heals a
corrupted/empty HNSW vector segment (e.g. after a large delete). Only live
documents (deleted_at IS NULL) are indexed, so this never resurrects orphan
vectors that the delete path / orphan sweep removed (P0).

Run inside the backend container:
  python -m scripts.reindex_chroma            # all orgs
  python -m scripts.reindex_chroma <org_id>   # one org
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.models.models import Chunk, Claim, Document

def get_sync_url():
    url = settings.DATABASE_URL
    if '+asyncpg' in url:
        url = url.replace('+asyncpg', '')
    return url

def _rebuild_collection(org_str, suffix):
    """Drop and recreate a collection so its vector segment is rebuilt cleanly."""
    from app.ingestion.indexer import (
        _get_client, get_or_create_collection, invalidate_collection_cache,
    )
    name = f"org_{org_str.replace('-', '_')}_{suffix}"[:63]
    try:
        _get_client().delete_collection(name)
    except Exception:
        pass  # may not exist yet
    # Drop the cached handle for the now-deleted collection so we recreate fresh.
    invalidate_collection_cache(org_str, suffix)
    return get_or_create_collection(org_str, suffix)


def reindex(org_filter=None):
    engine = create_engine(get_sync_url())
    Session = sessionmaker(bind=engine)
    session = Session()

    from app.ingestion.embedder import generate_embeddings

    try:
        # Get orgs (optionally a single one)
        if org_filter:
            orgs = [(org_filter,)]
        else:
            orgs = session.query(Document.org_id).distinct().all()
        logger.info(f"Found {len(orgs)} organizations to reindex")

        for (org_id,) in orgs:
            org_str = str(org_id)
            logger.info(f"\n{'='*60}")
            logger.info(f"Reindexing org: {org_str}")

            # --- Reindex chunks (live docs only) ---
            chunks = (
                session.query(Chunk)
                .join(Document, Chunk.document_id == Document.id)
                .filter(Document.org_id == org_id, Document.deleted_at.is_(None))
                .all()
            )
            logger.info(f"  Found {len(chunks)} chunks")

            # Clean rebuild even when empty, to clear any stale/corrupt segment.
            chunk_collection = _rebuild_collection(org_str, "chunks")
            if chunks:
                batch_size = 50
                total_indexed = 0

                # Deduplicate chunks by embedding_id
                seen_ids = set()
                unique_chunks = []
                for c in chunks:
                    if c.content:
                        eid = c.embedding_id or str(c.id)
                        if eid not in seen_ids:
                            seen_ids.add(eid)
                            unique_chunks.append(c)
                logger.info(f"  Unique chunks after dedup: {len(unique_chunks)} (from {len(chunks)})")

                for i in range(0, len(unique_chunks), batch_size):
                    batch = unique_chunks[i:i+batch_size]
                    if not batch:
                        continue

                    texts = [c.content for c in batch]
                    # Use embedding_id as ChromaDB key (matches original pipeline)
                    ids = [c.embedding_id or str(c.id) for c in batch]

                    embeddings = generate_embeddings(texts)

                    metadatas = []
                    for c in batch:
                        metadatas.append({
                            "document_id": str(c.document_id),
                            "chunk_index": c.chunk_index if hasattr(c, 'chunk_index') else 0,
                            "document_title": "",
                        })

                    chunk_collection.upsert(
                        ids=ids,
                        embeddings=embeddings,
                        documents=texts,
                        metadatas=metadatas,
                    )
                    total_indexed += len(ids)
                    logger.info(f"    Indexed chunk batch {i//batch_size + 1}: {len(ids)} chunks")

                logger.info(f"  Total chunks indexed: {total_indexed}")
                logger.info(f"  Chunk collection count: {chunk_collection.count()}")

            # --- Reindex claims (live docs only) ---
            claims = (
                session.query(Claim)
                .join(Document, Claim.document_id == Document.id)
                .filter(Document.org_id == org_id, Document.deleted_at.is_(None))
                .all()
            )
            logger.info(f"  Found {len(claims)} claims")

            claim_collection = _rebuild_collection(org_str, "claims")
            if claims:
                batch_size = 50
                total_indexed = 0

                # Deduplicate claims by embedding_id (multiple DB rows can share same embedding_id)
                seen_ids = set()
                unique_claims = []
                for c in claims:
                    if c.content:
                        eid = c.embedding_id or str(c.id)
                        if eid not in seen_ids:
                            seen_ids.add(eid)
                            unique_claims.append(c)
                logger.info(f"  Unique claims after dedup: {len(unique_claims)} (from {len(claims)})")

                for i in range(0, len(unique_claims), batch_size):
                    batch = unique_claims[i:i+batch_size]
                    if not batch:
                        continue

                    texts = [c.content for c in batch]
                    ids = [c.embedding_id or str(c.id) for c in batch]

                    embeddings = generate_embeddings(texts)

                    metadatas = []
                    for c in batch:
                        metadatas.append({
                            "document_id": str(c.document_id),
                            "chunk_id": str(c.chunk_id),
                            "is_claim": True,
                            "modality": c.modality.value if c.modality else "INFORMATIONAL",
                        })

                    claim_collection.upsert(
                        ids=ids,
                        embeddings=embeddings,
                        documents=texts,
                        metadatas=metadatas,
                    )
                    total_indexed += len(ids)
                    logger.info(f"    Indexed claim batch {i//batch_size + 1}: {len(ids)} claims")

                logger.info(f"  Total claims indexed: {total_indexed}")
                logger.info(f"  Claim collection count: {claim_collection.count()}")

        logger.info(f"\n{'='*60}")
        logger.info("Reindexing complete!")

    except Exception as e:
        logger.error(f"Reindex failed: {e}", exc_info=True)
        raise
    finally:
        session.close()

if __name__ == "__main__":
    reindex(sys.argv[1] if len(sys.argv) > 1 else None)
