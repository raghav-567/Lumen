"""Temporal reasoning for policy evolution vs contradiction detection.

Determines whether two conflicting claims represent a genuine contradiction
(both policies active simultaneously) or a valid policy evolution (one
supersedes the other).

This prevents the system from penalizing normal organizational document
lifecycle where policies are updated over time.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.ingestion.embedder import generate_embeddings

logger = logging.getLogger(__name__)


# ── Temporal classification ──────────────────────────────────


class TemporalClassification:
    """Result of temporal relationship analysis between two documents."""

    CONTRADICTION = "contradiction"        # Both active, genuinely conflicting
    EVOLUTION = "evolution"                # One supersedes the other (valid update)
    ACTIVE_CONFLICT = "active_conflict"    # Both active, temporal overlap, needs review
    EXPIRED = "expired"                    # Source policy has expired, low priority

    def __init__(self, classification: str, reason: str, confidence: float = 1.0, inferred: bool = False):
        self.classification = classification
        self.reason = reason
        self.confidence = confidence
        self.inferred = inferred  # True when resolved via heuristic lineage, not explicit supersession

    @property
    def is_genuine_contradiction(self) -> bool:
        """Whether this should count toward factual drift."""
        return self.classification in (self.CONTRADICTION, self.ACTIVE_CONFLICT)

    def __repr__(self):
        inf = ", inferred" if self.inferred else ""
        return f"TemporalClassification({self.classification}, conf={self.confidence:.2f}{inf})"


def classify_temporal_relationship(
    doc_a: dict,
    doc_b: dict,
    claim_a_text: str = "",
    claim_b_text: str = "",
) -> TemporalClassification:
    """Determine if two documents' conflicting claims are a contradiction or evolution.

    Args:
        doc_a: Source document metadata dict with keys:
               id, title, effective_from, effective_until, version_number,
               supersedes_document_id, owner_department, created_at
        doc_b: Target document metadata dict (same keys)
        claim_a_text: Optional claim text from doc_a (for lineage inference)
        claim_b_text: Optional claim text from doc_b (for lineage inference)

    Returns:
        TemporalClassification indicating the relationship type.
    """
    # ── Check 1: Explicit supersession ──
    if doc_b.get("supersedes_document_id") == doc_a.get("id"):
        return TemporalClassification(
            TemporalClassification.EVOLUTION,
            f"Document B explicitly supersedes Document A",
            confidence=1.0,
        )
    if doc_a.get("supersedes_document_id") == doc_b.get("id"):
        return TemporalClassification(
            TemporalClassification.EVOLUTION,
            f"Document A explicitly supersedes Document B",
            confidence=1.0,
        )

    # ── Check 2: Expired policy ──
    now = datetime.now(timezone.utc)
    a_expired = _is_expired(doc_a.get("effective_until"), now)
    b_expired = _is_expired(doc_b.get("effective_until"), now)

    if a_expired and not b_expired:
        return TemporalClassification(
            TemporalClassification.EVOLUTION,
            "Document A has expired; Document B is the active version",
            confidence=0.9,
        )
    if b_expired and not a_expired:
        return TemporalClassification(
            TemporalClassification.EVOLUTION,
            "Document B has expired; Document A is the active version",
            confidence=0.9,
        )
    if a_expired and b_expired:
        return TemporalClassification(
            TemporalClassification.EXPIRED,
            "Both documents have expired",
            confidence=0.95,
        )

    # ── Check 3: Non-overlapping effective periods ──
    a_until = _parse_dt(doc_a.get("effective_until"))
    b_from = _parse_dt(doc_b.get("effective_from"))
    a_from = _parse_dt(doc_a.get("effective_from"))
    b_until = _parse_dt(doc_b.get("effective_until"))

    if a_until and b_from and a_until < b_from:
        return TemporalClassification(
            TemporalClassification.EVOLUTION,
            "Document A's effective period ended before Document B took effect",
            confidence=0.85,
        )
    if b_until and a_from and b_until < a_from:
        return TemporalClassification(
            TemporalClassification.EVOLUTION,
            "Document B's effective period ended before Document A took effect",
            confidence=0.85,
        )

    # ── Check 4: Same lineage (inferred) ──
    lineage_result = _check_lineage(doc_a, doc_b)
    if lineage_result:
        return lineage_result

    # ── Default: genuine contradiction (both active, no supersession) ──
    return TemporalClassification(
        TemporalClassification.CONTRADICTION,
        "Both documents are active with no supersession relationship detected",
        confidence=0.7,
    )


# ── Helper functions ──────────────────────────────────────────


def _is_expired(effective_until, now: datetime) -> bool:
    """Check if a document's effective period has passed."""
    dt = _parse_dt(effective_until)
    if dt is None:
        return False  # No expiry set → still active
    return dt < now


def _parse_dt(value) -> datetime | None:
    """Parse a datetime from various formats."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            from dateutil.parser import parse as dt_parse
            dt = dt_parse(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, ImportError):
            return None
    return None


def _check_lineage(doc_a: dict, doc_b: dict) -> TemporalClassification | None:
    """Infer if two documents are in the same lineage (updated versions of each other).

    Signals used:
    - Same department
    - Title similarity > 0.85
    - Different version numbers
    """
    # Same department check
    dept_a = (doc_a.get("owner_department") or "").strip().lower()
    dept_b = (doc_b.get("owner_department") or "").strip().lower()

    if not dept_a or not dept_b:
        # Can't infer lineage without department info
        return None

    if dept_a != dept_b:
        # Different departments → likely not same lineage
        return None

    # Title similarity check
    title_a = (doc_a.get("title") or "").strip()
    title_b = (doc_b.get("title") or "").strip()

    if not title_a or not title_b:
        return None

    try:
        embeddings = generate_embeddings([title_a, title_b])
        # Cosine similarity (embeddings are normalized)
        import numpy as np
        sim = float(np.dot(embeddings[0], embeddings[1]))

        if sim > 0.85:
            # High title similarity + same department → likely same policy lineage
            v_a = doc_a.get("version_number", 1) or 1
            v_b = doc_b.get("version_number", 1) or 1

            if v_b > v_a:
                return TemporalClassification(
                    TemporalClassification.EVOLUTION,
                    f"Inferred lineage: same department, similar titles (sim={sim:.2f}), "
                    f"Doc B is version {v_b} vs Doc A version {v_a}",
                    confidence=min(0.9, sim),
                    inferred=True,
                )
            elif v_a > v_b:
                return TemporalClassification(
                    TemporalClassification.EVOLUTION,
                    f"Inferred lineage: same department, similar titles (sim={sim:.2f}), "
                    f"Doc A is version {v_a} vs Doc B version {v_b}",
                    confidence=min(0.9, sim),
                    inferred=True,
                )
            else:
                # Same version but high similarity + same dept
                # Check creation dates
                a_created = _parse_dt(doc_a.get("created_at"))
                b_created = _parse_dt(doc_b.get("created_at"))
                if a_created and b_created and abs((b_created - a_created).days) > 30:
                    date_gap = abs((b_created - a_created).days)
                    newer = "B" if b_created > a_created else "A"
                    return TemporalClassification(
                        TemporalClassification.EVOLUTION,
                        f"Inferred lineage: same department, similar titles (sim={sim:.2f}), "
                        f"Doc {newer} is newer by {date_gap} days",
                        confidence=min(0.8, sim),
                        inferred=True,
                    )
    except Exception as e:
        logger.debug(f"Lineage check failed: {e}")

    return None


def get_document_temporal_context(doc) -> dict:
    """Extract temporal metadata from a document ORM object into a dict."""
    return {
        "id": str(doc.id),
        "title": doc.title,
        "effective_from": doc.effective_from,
        "effective_until": doc.effective_until,
        "version_number": doc.version_number,
        "supersedes_document_id": str(doc.supersedes_document_id) if doc.supersedes_document_id else None,
        "owner_department": doc.owner_department,
        "created_at": doc.created_at,
    }
