"""V5 Migration — Temporal feedback loop.

Adds:
  - inferred_lineage (BOOLEAN) to contradiction_pairs
  - heuristic_feedback table

Run: docker compose exec backend python -c "import sys; sys.path.insert(0, '/app'); exec(open('/app/migrations/v5_temporal_feedback.py').read()); run_migration()"
"""

from __future__ import annotations

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

MIGRATIONS = [
    (
        "ContradictionPair: inferred_lineage",
        "ALTER TABLE contradiction_pairs ADD COLUMN IF NOT EXISTS inferred_lineage BOOLEAN DEFAULT FALSE;",
    ),
    (
        "Create heuristic_feedback table",
        """
        CREATE TABLE IF NOT EXISTS heuristic_feedback (
            id UUID PRIMARY KEY,
            pair_id UUID NOT NULL REFERENCES contradiction_pairs(id),
            org_id UUID NOT NULL REFERENCES organizations(id),
            title_similarity_score FLOAT,
            date_gap_days INTEGER,
            department_match BOOLEAN DEFAULT TRUE,
            reviewer_decision VARCHAR(50) NOT NULL,
            original_classification VARCHAR(50),
            reviewed_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
    ),
    (
        "heuristic_feedback: org index",
        "CREATE INDEX IF NOT EXISTS ix_heuristic_feedback_org ON heuristic_feedback(org_id);",
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
    logger.info("Running V5 Temporal Feedback Migration...")
    run_migration()
