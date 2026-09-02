"""V8 Migration — Contradiction taxonomy and scan path.

Adds:
  - contradiction_type column on contradiction_pairs (Fix 3.5)
  - scan_path column on contradiction_pairs (Fix 3.5)

Run: docker compose exec backend python -c "import sys; sys.path.insert(0, '/app'); exec(open('/app/migrations/v8_contradiction_taxonomy.py').read()); run_migration()"
"""

from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

MIGRATIONS = [
    (
        "ContradictionPair: contradiction_type",
        "ALTER TABLE contradiction_pairs ADD COLUMN IF NOT EXISTS contradiction_type VARCHAR(50);",
    ),
    (
        "ContradictionPair: scan_path",
        "ALTER TABLE contradiction_pairs ADD COLUMN IF NOT EXISTS scan_path VARCHAR(20);",
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
    logger.info("Running V8 Contradiction Taxonomy Migration...")
    run_migration()
