"""V6 Migration — Split ChromaDB into per-org chunks + claims collections.

Reads all existing records from org_*_chunks collections, identifies
entries with is_claim=True metadata, and moves them to the corresponding
org_*_claims collection.

Run: docker compose exec backend python -c "import sys; sys.path.insert(0, '/app'); exec(open('/app/migrations/v6_collection_split.py').read()); run_migration()"
"""

from __future__ import annotations

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def run_migration():
    import chromadb
    from app.core.config import settings

    client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
    collections = client.list_collections()

    chunks_collections = [c for c in collections if c.name.endswith("_chunks")]
    logger.info(f"Found {len(chunks_collections)} org chunk collections to scan")

    total_moved = 0
    total_stayed = 0

    for col in chunks_collections:
        # Derive the claims collection name
        claims_name = col.name.replace("_chunks", "_claims")
        logger.info(f"Processing {col.name} → {claims_name}")

        # Get all records
        try:
            result = col.get(include=["embeddings", "documents", "metadatas"])
        except Exception as e:
            logger.error(f"  Failed to read {col.name}: {e}")
            continue

        if not result or not result["ids"]:
            logger.info(f"  Empty collection, skipping")
            continue

        # Split into claims and chunks
        claim_ids = []
        claim_embeddings = []
        claim_documents = []
        claim_metadatas = []

        for i, _id in enumerate(result["ids"]):
            meta = result["metadatas"][i] if result["metadatas"] else {}
            if meta.get("is_claim"):
                emb = result["embeddings"][i] if result["embeddings"] else []
                # Skip entries with empty or missing embeddings
                if not emb or (isinstance(emb, list) and len(emb) == 0):
                    logger.warning(f"  Skipping claim {_id}: empty embedding")
                    continue
                claim_ids.append(_id)
                claim_embeddings.append(emb)
                claim_documents.append(result["documents"][i] if result["documents"] else "")
                claim_metadatas.append(meta)

        if not claim_ids:
            logger.info(f"  No claims found in {col.name}, skipping")
            total_stayed += len(result["ids"])
            continue

        # Create claims collection and upsert
        claims_col = client.get_or_create_collection(
            name=claims_name,
            metadata={"hnsw:space": "cosine"},
        )

        # Batch upsert in chunks of 500
        batch_size = 500
        for start in range(0, len(claim_ids), batch_size):
            end = start + batch_size
            claims_col.upsert(
                ids=claim_ids[start:end],
                embeddings=claim_embeddings[start:end],
                documents=claim_documents[start:end],
                metadatas=claim_metadatas[start:end],
            )

        # Delete claims from the chunks collection
        try:
            col.delete(ids=claim_ids)
        except Exception as e:
            logger.warning(f"  Failed to delete migrated claims from {col.name}: {e}")

        moved = len(claim_ids)
        stayed = len(result["ids"]) - moved
        total_moved += moved
        total_stayed += stayed
        logger.info(f"  ✓ Moved {moved} claims to {claims_name}, {stayed} chunks remain")

    logger.info(f"\nMigration complete: {total_moved} claims moved, {total_stayed} chunks unchanged")
    return True


if __name__ == "__main__":
    logger.info("Running V6 Collection Split Migration...")
    run_migration()
