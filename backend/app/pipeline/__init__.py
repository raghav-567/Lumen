"""Multi-level document processing cache.

Three cache levels:
  L1 — Parse cache:  SHA256(file_bytes + parser_version) → parsed text + page map
  L2 — Chunk cache:  SHA256(cleaned_text + chunking_version) → chunk list
  L3 — Claim cache:  SHA256(chunk_text + extraction_model + embedding_model) → claims + embeddings

All caches use the database (JSONB columns on Document/Chunk) to avoid
external dependencies. Cache keys are stored in document metadata.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

PARSER_VERSION = "v2"
CHUNKING_VERSION = "v1"


def _sha256(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8") if isinstance(p, str) else p)
    return h.hexdigest()[:16]


# ── L1: Parse cache ─────────────────────────────────

def get_parse_cache_key(file_path: str) -> str:
    """Compute cache key from file content hash + parser version."""
    try:
        with open(file_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:
        return ""
    return _sha256(file_hash, PARSER_VERSION)


def check_parse_cache(session, document_id: str) -> dict | None:
    """Check if parsed text is already cached for this document."""
    from app.models.models import Document
    doc = session.query(Document).filter(Document.id == document_id).first()
    if not doc or not doc.metadata_:
        return None
    cached = doc.metadata_.get("parse_cache")
    if not cached:
        return None
    return cached


def store_parse_cache(session, document_id: str, cache_key: str,
                      text: str, page_count: int, page_map: dict | None):
    """Store parsed text in document metadata."""
    from app.models.models import Document
    doc = session.query(Document).filter(Document.id == document_id).first()
    if not doc:
        return
    if not doc.metadata_:
        doc.metadata_ = {}
    doc.metadata_["parse_cache"] = {
        "key": cache_key,
        "text_length": len(text),
        "page_count": page_count,
        "parser_version": PARSER_VERSION,
    }
    session.commit()


# ── L2: Chunk cache ──────────────────────────────────

def get_chunk_cache_key(text: str) -> str:
    return _sha256(text[:10000], CHUNKING_VERSION)


# ── L3: Claim cache ─────────────────────────────────

def get_claim_cache_key(chunk_text: str, extraction_model: str, embedding_model: str) -> str:
    return _sha256(chunk_text, extraction_model, embedding_model)


def check_claim_cache(session, document_id: str, content_hash: str) -> list | None:
    """Check if claims for a specific content hash are already in DB."""
    from app.models.models import Claim
    existing = (
        session.query(Claim)
        .filter(Claim.document_id == document_id, Claim.content_hash == content_hash)
        .all()
    )
    if existing:
        logger.debug(f"Claim cache hit: {content_hash[:8]} → {len(existing)} claims")
        return existing
    return None


# ── Metrics ──────────────────────────────────────────

class CacheMetrics:
    """Track cache hit/miss rates for observability."""

    def __init__(self):
        self.parse_hits = 0
        self.parse_misses = 0
        self.chunk_hits = 0
        self.chunk_misses = 0
        self.claim_hits = 0
        self.claim_misses = 0

    def report(self) -> dict:
        total_parse = self.parse_hits + self.parse_misses
        total_claim = self.claim_hits + self.claim_misses
        return {
            "parse_hit_rate": round(self.parse_hits / max(total_parse, 1), 2),
            "claim_hit_rate": round(self.claim_hits / max(total_claim, 1), 2),
            "parse_hits": self.parse_hits,
            "claim_hits": self.claim_hits,
        }
