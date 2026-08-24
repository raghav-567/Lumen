"""V2 Enterprise Schema Migration — Idempotent.

Adds temporal, authority, review, claim structure, embedding versioning,
and processing state columns to existing tables.

Run: docker compose exec backend python migrations/v2_enterprise_schema.py
"""

from __future__ import annotations

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Each migration is (description, SQL). All use IF NOT EXISTS / ADD COLUMN IF NOT EXISTS
# so the script is safe to re-run.
MIGRATIONS = [
    # ── New enum types ──
    (
        "Create processingstatus enum",
        """
        DO $$ BEGIN
            CREATE TYPE processingstatus AS ENUM ('pending','processing','partial','failed','complete');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """,
    ),
    (
        "Create reviewstatus enum",
        """
        DO $$ BEGIN
            CREATE TYPE reviewstatus AS ENUM ('pending','approved','rejected','false_positive','intentional_divergence');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """,
    ),
    (
        "Create claimmodality enum",
        """
        DO $$ BEGIN
            CREATE TYPE claimmodality AS ENUM ('mandatory','optional','prohibited','recommended','informational');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """,
    ),
    (
        "Add 'evolution' to contradictionclassification enum",
        """
        DO $$ BEGIN
            ALTER TYPE contradictionclassification ADD VALUE IF NOT EXISTS 'evolution';
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """,
    ),

    # ── Document: temporal & authority ──
    (
        "Document: effective_from",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS effective_from TIMESTAMPTZ;",
    ),
    (
        "Document: effective_until",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS effective_until TIMESTAMPTZ;",
    ),
    (
        "Document: version_number",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS version_number INTEGER DEFAULT 1;",
    ),
    (
        "Document: supersedes_document_id",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS supersedes_document_id UUID REFERENCES documents(id);",
    ),
    (
        "Document: authority_level",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS authority_level INTEGER DEFAULT 3;",
    ),
    (
        "Document: owner_department",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS owner_department VARCHAR(255);",
    ),
    (
        "Document: document_type",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_type VARCHAR(100);",
    ),
    (
        "Document: processing_status",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_status processingstatus DEFAULT 'pending';",
    ),

    # ── Chunk: embedding versioning ──
    (
        "Chunk: embedding_model_version",
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding_model_version VARCHAR(100);",
    ),
    (
        "Chunk: embedding_dimension",
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding_dimension INTEGER;",
    ),
    (
        "Chunk: embedding_created_at",
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding_created_at TIMESTAMPTZ;",
    ),

    # ── Claim: structured fields ──
    (
        "Claim: subject",
        "ALTER TABLE claims ADD COLUMN IF NOT EXISTS subject VARCHAR(512);",
    ),
    (
        "Claim: predicate",
        "ALTER TABLE claims ADD COLUMN IF NOT EXISTS predicate VARCHAR(512);",
    ),
    (
        "Claim: value",
        "ALTER TABLE claims ADD COLUMN IF NOT EXISTS value TEXT;",
    ),
    (
        "Claim: condition",
        "ALTER TABLE claims ADD COLUMN IF NOT EXISTS condition TEXT;",
    ),
    (
        "Claim: effective_from",
        "ALTER TABLE claims ADD COLUMN IF NOT EXISTS effective_from TIMESTAMPTZ;",
    ),
    (
        "Claim: effective_until",
        "ALTER TABLE claims ADD COLUMN IF NOT EXISTS effective_until TIMESTAMPTZ;",
    ),
    (
        "Claim: modality",
        "ALTER TABLE claims ADD COLUMN IF NOT EXISTS modality claimmodality;",
    ),
    (
        "Claim: confidence",
        "ALTER TABLE claims ADD COLUMN IF NOT EXISTS confidence FLOAT DEFAULT 1.0;",
    ),
    (
        "Claim: extraction_model",
        "ALTER TABLE claims ADD COLUMN IF NOT EXISTS extraction_model VARCHAR(100);",
    ),
    (
        "Claim: content_hash",
        "ALTER TABLE claims ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64);",
    ),
    (
        "Claim: content_hash index",
        "CREATE INDEX IF NOT EXISTS ix_claims_content_hash ON claims(content_hash);",
    ),

    # ── ContradictionPair: review workflow ──
    (
        "ContradictionPair: reviewed_by",
        "ALTER TABLE contradiction_pairs ADD COLUMN IF NOT EXISTS reviewed_by UUID REFERENCES users(id);",
    ),
    (
        "ContradictionPair: reviewed_at",
        "ALTER TABLE contradiction_pairs ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;",
    ),
    (
        "ContradictionPair: review_status",
        "ALTER TABLE contradiction_pairs ADD COLUMN IF NOT EXISTS review_status reviewstatus DEFAULT 'pending';",
    ),
    (
        "ContradictionPair: review_reason",
        "ALTER TABLE contradiction_pairs ADD COLUMN IF NOT EXISTS review_reason TEXT;",
    ),
    (
        "ContradictionPair: is_temporal_evolution",
        "ALTER TABLE contradiction_pairs ADD COLUMN IF NOT EXISTS is_temporal_evolution BOOLEAN DEFAULT FALSE;",
    ),

    # ── Backfill processing_status for existing documents ──
    (
        "Backfill processing_status for processed docs",
        "UPDATE documents SET processing_status = 'complete' WHERE is_processed = TRUE AND processing_status = 'pending';",
    ),
]


def run_migration():
    """Execute all migrations against the database."""
    import psycopg2
    from app.core.config import settings

    # Convert async URL to sync for psycopg2
    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cursor = conn.cursor()

    success = 0
    skipped = 0
    failed = 0

    for desc, sql in MIGRATIONS:
        try:
            cursor.execute(sql.strip())
            logger.info(f"  ✓ {desc}")
            success += 1
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                logger.info(f"  · {desc} (already exists)")
                skipped += 1
                conn.rollback()
                conn.autocommit = True
            else:
                logger.error(f"  ✗ {desc}: {e}")
                failed += 1
                conn.rollback()
                conn.autocommit = True

    cursor.close()
    conn.close()

    logger.info(f"\nMigration complete: {success} applied, {skipped} skipped, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    logger.info("Running V2 Enterprise Schema Migration...")
    ok = run_migration()
    sys.exit(0 if ok else 1)
