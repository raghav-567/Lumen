"""V3 Migration — Gate calibration columns on ContradictionPairs.

Adds:
  - sampled (BOOLEAN DEFAULT FALSE)
  - gate_similarity (FLOAT)

Run: docker compose exec backend python migrations/v3_gate_calibration.py
"""

from __future__ import annotations

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

MIGRATIONS = [
    (
        "ContradictionPair: sampled",
        "ALTER TABLE contradiction_pairs ADD COLUMN IF NOT EXISTS sampled BOOLEAN DEFAULT FALSE;",
    ),
    (
        "ContradictionPair: gate_similarity",
        "ALTER TABLE contradiction_pairs ADD COLUMN IF NOT EXISTS gate_similarity FLOAT;",
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
    logger.info("Running V3 Gate Calibration Migration...")
    run_migration()
