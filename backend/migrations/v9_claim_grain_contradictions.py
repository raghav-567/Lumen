"""V9 Migration — Claim-granularity contradiction dedup (Fix C).

Adds:
  - claim_a_id / claim_b_id columns on contradiction_pairs (FK → claims)
  - CHECK (claim_a_id < claim_b_id) so a pair has a canonical ordering
  - UNIQUE (claim_a_id, claim_b_id) so the same claim pair can't be stored twice
  - supporting index

Docs chunk into a handful of large chunks, so the old chunk-level dedup
collapsed many distinct claim contradictions into a single row. Moving dedup to
claim granularity restores the true contradiction count (and thus drift signal).

Run: docker compose exec backend python -c "import sys; sys.path.insert(0, '/app'); exec(open('/app/migrations/v9_claim_grain_contradictions.py').read()); run_migration()"
"""

from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

MIGRATIONS = [
    (
        "ContradictionPair: claim_a_id",
        "ALTER TABLE contradiction_pairs ADD COLUMN IF NOT EXISTS claim_a_id UUID REFERENCES claims(id) ON DELETE CASCADE;",
    ),
    (
        "ContradictionPair: claim_b_id",
        "ALTER TABLE contradiction_pairs ADD COLUMN IF NOT EXISTS claim_b_id UUID REFERENCES claims(id) ON DELETE CASCADE;",
    ),
    (
        "ContradictionPair: CHECK claim_a_id < claim_b_id",
        """
        DO $$ BEGIN
            ALTER TABLE contradiction_pairs
                ADD CONSTRAINT ck_contradiction_claim_order CHECK (claim_a_id < claim_b_id);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """,
    ),
    (
        "ContradictionPair: UNIQUE (claim_a_id, claim_b_id)",
        """
        DO $$ BEGIN
            ALTER TABLE contradiction_pairs
                ADD CONSTRAINT uq_contradiction_claim_pair UNIQUE (claim_a_id, claim_b_id);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """,
    ),
    (
        "ContradictionPair: index on claim pair",
        "CREATE INDEX IF NOT EXISTS ix_contradiction_claim_pair ON contradiction_pairs (claim_a_id, claim_b_id);",
    ),
    (
        # The old chunk-level UNIQUE index collapsed every claim contradiction
        # between two docs into a single row (docs chunk into a few large chunks).
        # Drop uniqueness; keep a plain index for the recalc join.
        "ContradictionPair: drop UNIQUE chunk index",
        "DROP INDEX IF EXISTS ix_contradiction_pairs_chunks;",
    ),
    (
        "ContradictionPair: non-unique chunk index",
        "CREATE INDEX IF NOT EXISTS ix_contradiction_pairs_chunks_nu ON contradiction_pairs (chunk_a_id, chunk_b_id);",
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

    cursor.close()
    conn.close()
    logger.info(f"\nMigration complete: {success} applied")
    return True


if __name__ == "__main__":
    logger.info("Running V9 Claim-Grain Contradiction Migration...")
    run_migration()
