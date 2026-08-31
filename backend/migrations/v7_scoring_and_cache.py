"""V7 Migration — Drift weights, explanation invalidation, Celery result tables.

Adds:
  - org_drift_weights table (Change 5)
  - explanation_valid column on contradiction_pairs (Change 8)
  - Celery result backend tables are auto-created by Celery

Run: docker compose exec backend python -c "import sys; sys.path.insert(0, '/app'); exec(open('/app/migrations/v7_scoring_and_cache.py').read()); run_migration()"
"""

from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

MIGRATIONS = [
    (
        "Create org_drift_weights table",
        """
        CREATE TABLE IF NOT EXISTS org_drift_weights (
            id UUID PRIMARY KEY,
            org_id UUID NOT NULL UNIQUE REFERENCES organizations(id),
            density_weight FLOAT DEFAULT 0.45,
            confidence_weight FLOAT DEFAULT 0.35,
            volume_weight FLOAT DEFAULT 0.20,
            factual_weight FLOAT DEFAULT 0.60,
            semantic_weight FLOAT DEFAULT 0.40,
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            updated_by UUID REFERENCES users(id)
        );
        """,
    ),
    (
        "ContradictionPair: explanation_valid",
        "ALTER TABLE contradiction_pairs ADD COLUMN IF NOT EXISTS explanation_valid BOOLEAN DEFAULT TRUE;",
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
    logger.info("Running V7 Scoring & Cache Migration...")
    run_migration()
