"""V4 Migration — Document content_hash for deduplication.

Adds:
  - content_hash (VARCHAR(64)) to documents
  - Composite index on (org_id, content_hash)

Run: docker compose exec backend python -c "import sys; sys.path.insert(0, '/app'); exec(open('/app/migrations/v4_document_dedup.py').read()); run_migration()"
"""

from __future__ import annotations

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

MIGRATIONS = [
    (
        "Document: content_hash",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64);",
    ),
    (
        "Document: content_hash index",
        "CREATE INDEX IF NOT EXISTS ix_documents_content_hash ON documents(content_hash);",
    ),
    (
        "Document: org_hash composite index",
        "CREATE INDEX IF NOT EXISTS ix_documents_org_hash ON documents(org_id, content_hash);",
    ),
]


def run_migration():
    import psycopg2
    from app.core.config import settings

    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cursor = conn.cursor()

    success = 0
    for desc, sql in MIGRATIONS:
        try:
            cursor.execute(sql.strip())
            logger.info(f"  ✓ {desc}")
            success += 1
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.info(f"  · {desc} (already exists)")
            else:
                logger.error(f"  ✗ {desc}: {e}")

    # Backfill content_hash for existing documents
    try:
        cursor.execute("SELECT COUNT(*) FROM documents WHERE content_hash IS NULL AND file_path IS NOT NULL")
        to_backfill = cursor.fetchone()[0]
        if to_backfill > 0:
            logger.info(f"  Backfilling {to_backfill} documents with content_hash...")
            cursor.execute("""
                SELECT id, file_path FROM documents 
                WHERE content_hash IS NULL AND file_path IS NOT NULL
            """)
            import hashlib
            updated = 0
            for doc_id, file_path in cursor.fetchall():
                try:
                    with open(file_path, "rb") as f:
                        h = hashlib.sha256(f.read()).hexdigest()
                    cursor.execute(
                        "UPDATE documents SET content_hash = %s WHERE id = %s",
                        (h, doc_id)
                    )
                    updated += 1
                except FileNotFoundError:
                    pass
            logger.info(f"  ✓ Backfilled {updated}/{to_backfill} documents")
    except Exception as e:
        logger.warning(f"  Backfill skipped: {e}")

    cursor.close()
    conn.close()
    logger.info(f"\nMigration complete: {success} applied")
    return True


if __name__ == "__main__":
    logger.info("Running V4 Document Dedup Migration...")
    run_migration()
