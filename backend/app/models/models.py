"""SQLAlchemy ORM models for the Knowledge Drift Detection System."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (Boolean, CheckConstraint, Column, DateTime, Enum, Float,
                        ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base

_utcnow = lambda: datetime.now(timezone.utc)  # noqa
_uuid = uuid.uuid4


# ── Enums ─────────────────────────────────────────────


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


class PlanTier(str, enum.Enum):
    STARTER = "STARTER"
    PROFESSIONAL = "PROFESSIONAL"
    ENTERPRISE = "ENTERPRISE"


class FileType(str, enum.Enum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    MD = "md"


class AlertType(str, enum.Enum):
    CONTRADICTION = "contradiction"
    SEMANTIC_DRIFT = "semantic_drift"
    STALE_CONTENT = "stale_content"
    MISSING_REFERENCE = "missing_reference"


class AlertSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertStatus(str, enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ContradictionClassification(str, enum.Enum):
    CONSISTENT = "consistent"
    CONTRADICTORY = "contradictory"
    SUPERSEDES = "supersedes"
    UNRELATED = "unrelated"
    EVOLUTION = "evolution"


class ProcessingStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    COMPLETE = "COMPLETE"


class ReviewStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    INTENTIONAL_DIVERGENCE = "INTENTIONAL_DIVERGENCE"


class ClaimModality(str, enum.Enum):
    MANDATORY = "MANDATORY"
    OPTIONAL = "OPTIONAL"
    PROHIBITED = "PROHIBITED"
    RECOMMENDED = "RECOMMENDED"
    INFORMATIONAL = "INFORMATIONAL"


# ── Models ────────────────────────────────────────────


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False)
    plan = Column(Enum(PlanTier), nullable=False, default=PlanTier.STARTER)
    settings = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    users = relationship("User", back_populates="organization")
    documents = relationship("Document", back_populates="organization")
    alerts = relationship("Alert", back_populates="organization")


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email = Column(String(320), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)
    full_name = Column(String(255))
    role = Column(Enum(UserRole, name='userrole', create_type=False), nullable=False, default=UserRole.MEMBER)
    is_active = Column(Boolean, default=True, nullable=False)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    organization = relationship("Organization", back_populates="users")


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    title = Column(String(512), nullable=False)
    filename = Column(String(512), nullable=False)
    file_path = Column(String(1024), nullable=False)
    file_type = Column(Enum(FileType), nullable=False)
    file_size = Column(Integer)  # bytes
    page_count = Column(Integer)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    metadata_ = Column("metadata", JSONB, default=dict)
    drift_score = Column(Float, default=0.0)
    semantic_drift_score = Column(Float, default=0.0)
    factual_drift_score = Column(Float, default=0.0)
    aligned_claims = Column(Integer, default=0)
    drift_type = Column(String(50), nullable=True)
    is_processed = Column(Boolean, default=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # ── Temporal & Authority (Phase A1) ──
    effective_from = Column(DateTime(timezone=True), nullable=True)
    effective_until = Column(DateTime(timezone=True), nullable=True)
    version_number = Column(Integer, default=1)
    supersedes_document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True)
    authority_level = Column(Integer, default=3)  # 1 (note) to 5 (legal master policy)
    owner_department = Column(String(255), nullable=True)
    document_type = Column(String(100), nullable=True)  # policy, sop, wiki, memo, etc.
    processing_status = Column(
        Enum(ProcessingStatus, name="processingstatus", create_type=False),
        default=ProcessingStatus.PENDING,
    )

    organization = relationship("Organization", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")
    supersedes = relationship("Document", remote_side="Document.id", foreign_keys=[supersedes_document_id])

    # ── Content deduplication (Change 7) ──
    content_hash = Column(String(64), nullable=True, index=True)  # SHA-256 hex digest

    __table_args__ = (
        Index("ix_documents_org_created", "org_id", "created_at"),
        Index("ix_documents_org_drift", "org_id", "drift_score"),
        Index("ix_documents_org_hash", "org_id", "content_hash"),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    start_page = Column(Integer)
    end_page = Column(Integer)
    token_count = Column(Integer)
    embedding_id = Column(String(255))  # ChromaDB document ID
    metadata_ = Column("metadata", JSONB, default=dict)
    search_vector = Column(TSVECTOR)  # PostgreSQL full-text search
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # ── Embedding versioning (Phase A2) ──
    embedding_model_version = Column(String(100), nullable=True)
    embedding_dimension = Column(Integer, nullable=True)
    embedding_created_at = Column(DateTime(timezone=True), nullable=True)

    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_document", "document_id"),
        Index("ix_chunks_search_vector", "search_vector", postgresql_using="gin"),
    )


class Claim(Base):
    __tablename__ = "claims"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_id = Column(UUID(as_uuid=True), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    original_sentence = Column(Text, nullable=False)
    importance_weight = Column(Float, default=1.0)
    embedding_id = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # ── Structured claim fields (Phase A3) ──
    subject = Column(String(512), nullable=True)
    predicate = Column(String(512), nullable=True)
    value = Column(Text, nullable=True)
    condition = Column(Text, nullable=True)
    effective_from = Column(DateTime(timezone=True), nullable=True)
    effective_until = Column(DateTime(timezone=True), nullable=True)
    modality = Column(
        Enum(ClaimModality, name="claimmodality", create_type=False),
        nullable=True,
    )
    confidence = Column(Float, default=1.0)
    extraction_model = Column(String(100), nullable=True)  # e.g. "qwen2.5:3b" or "nltk_rule_based"
    content_hash = Column(String(64), nullable=True, index=True)  # SHA256 for cache lookup

    document = relationship("Document", foreign_keys=[document_id])
    chunk = relationship("Chunk", foreign_keys=[chunk_id])

    __table_args__ = (
        Index("ix_claims_document_id", "document_id"),
        Index("ix_claims_content_hash", "content_hash"),
    )


class Entity(Base):
    __tablename__ = "entities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String(512), nullable=False)
    entity_type = Column(String(100), nullable=False)  # PERSON, POLICY, REGULATION, etc.
    source_chunk_id = Column(UUID(as_uuid=True), ForeignKey("chunks.id"))
    properties = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        Index("ix_entities_org_name", "org_id", "name"),
    )


class Relation(Base):
    __tablename__ = "relations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    source_entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False)
    target_entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False)
    relation_type = Column(String(255), nullable=False)
    source_chunk_id = Column(UUID(as_uuid=True), ForeignKey("chunks.id"))
    confidence = Column(Float, default=1.0)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    source_entity = relationship("Entity", foreign_keys=[source_entity_id])
    target_entity = relationship("Entity", foreign_keys=[target_entity_id])


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    alert_type = Column(Enum(AlertType), nullable=False)
    severity = Column(Enum(AlertSeverity), default=AlertSeverity.MEDIUM, nullable=False)
    source_doc_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"))
    target_doc_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True)
    source_chunk_id = Column(UUID(as_uuid=True), ForeignKey("chunks.id"), nullable=True)
    target_chunk_id = Column(UUID(as_uuid=True), ForeignKey("chunks.id"), nullable=True)
    title = Column(String(512), nullable=False)
    description = Column(Text)
    evidence = Column(JSONB, default=dict)
    status = Column(Enum(AlertStatus), default=AlertStatus.OPEN, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    organization = relationship("Organization", back_populates="alerts")
    source_doc = relationship("Document", foreign_keys=[source_doc_id])
    target_doc = relationship("Document", foreign_keys=[target_doc_id])

    __table_args__ = (
        Index("ix_alerts_org_status_severity", "org_id", "status", "severity"),
    )


class ContradictionPair(Base):
    __tablename__ = "contradiction_pairs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    chunk_a_id = Column(UUID(as_uuid=True), ForeignKey("chunks.id"), nullable=False)
    chunk_b_id = Column(UUID(as_uuid=True), ForeignKey("chunks.id"), nullable=False)
    classification = Column(Enum(ContradictionClassification), nullable=False)
    confidence = Column(Float, nullable=False)
    explanation = Column(Text)
    conflicting_claims = Column(JSONB, default=list)
    aligned_claims_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # ── Human review workflow (Phase B3) ──
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_status = Column(
        Enum(ReviewStatus, name="reviewstatus", create_type=False),
        default=ReviewStatus.PENDING,
    )
    review_reason = Column(Text, nullable=True)
    is_temporal_evolution = Column(Boolean, default=False)

    # ── Gate calibration (Change 1) ──
    sampled = Column(Boolean, default=False)           # below-threshold pair retained for calibration
    gate_similarity = Column(Float, nullable=True)     # embedding similarity at time of detection

    # ── Temporal feedback loop (Change 3) ──
    inferred_lineage = Column(Boolean, default=False)  # True if EVOLUTION was inferred, not explicit

    # ── Explanation cache invalidation (Change 8) ──
    explanation_valid = Column(Boolean, default=True)  # False = stale, needs re-generation

    # ── Contradiction taxonomy (Fix 3.5) ──
    contradiction_type = Column(String(50), nullable=True)  # direct_opposition, outcome_inversion, etc.
    scan_path = Column(String(20), nullable=True)           # "structured" or "embedding"

    # ── Claim-granularity dedup (Fix C) ──
    # When both are set, the pair is keyed/deduped at claim granularity instead
    # of chunk granularity (docs chunk into a few large chunks, so chunk-level
    # dedup collapsed many distinct claim contradictions into one row). Nullable
    # for legacy/chunk-fallback rows; the CHECK only binds when both are present.
    claim_a_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=True)
    claim_b_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=True)

    chunk_a = relationship("Chunk", foreign_keys=[chunk_a_id])
    chunk_b = relationship("Chunk", foreign_keys=[chunk_b_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by])

    __table_args__ = (
        # Enforce a canonical ordering so (X,Y) and (Y,X) can't both be stored,
        # and back it with a uniqueness guard. Both only bind when claim ids are
        # non-null (NULLs compare as unknown / are distinct in Postgres).
        CheckConstraint("claim_a_id < claim_b_id", name="ck_contradiction_claim_order"),
        UniqueConstraint("claim_a_id", "claim_b_id", name="uq_contradiction_claim_pair"),
        Index("ix_contradiction_claim_pair", "claim_a_id", "claim_b_id"),
    )


class ScannedPair(Base):
    """Ledger of (doc_a, doc_b) pairs already run through the contradiction scanner.

    Stored canonically (doc_a_id < doc_b_id), regardless of which doc was the scan
    source, so reconciliation can cheaply diff "all live-doc pairs" against "pairs
    already scanned" and re-queue only the gaps. Closes the concurrent/bulk-upload
    race where one doc's shortlist runs before another's claims finish indexing,
    so a pair is silently never scanned (CLAUDE.md §10).
    """
    __tablename__ = "scanned_pairs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    doc_a_id = Column(UUID(as_uuid=True), nullable=False)  # canonical: doc_a_id < doc_b_id
    doc_b_id = Column(UUID(as_uuid=True), nullable=False)
    scanned_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("doc_a_id < doc_b_id", name="ck_scanned_pair_order"),
        UniqueConstraint("org_id", "doc_a_id", "doc_b_id", name="uq_scanned_pair"),
        Index("ix_scanned_pairs_org", "org_id"),
    )


class HeuristicFeedback(Base):
    """Logs reviewer overrides of inferred lineage decisions.

    When a reviewer marks an inferred_lineage=True EVOLUTION pair as
    CONTRADICTORY (false evolution), this table captures the heuristic
    signals that led to the wrong decision, enabling threshold tuning.
    """
    __tablename__ = "heuristic_feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    pair_id = Column(UUID(as_uuid=True), ForeignKey("contradiction_pairs.id"), nullable=False)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    title_similarity_score = Column(Float, nullable=True)
    date_gap_days = Column(Integer, nullable=True)
    department_match = Column(Boolean, default=True)
    reviewer_decision = Column(String(50), nullable=False)  # e.g. APPROVED, REJECTED, FALSE_POSITIVE
    original_classification = Column(String(50), nullable=True)  # what the heuristic said
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    pair = relationship("ContradictionPair", foreign_keys=[pair_id])

    __table_args__ = (
        Index("ix_heuristic_feedback_org", "org_id"),
    )


class OrgDriftWeights(Base):
    """Per-organization drift scoring weights.

    Allows each org to tune how factual vs semantic drift is weighted,
    and how internal factual drift sub-signals are balanced.
    """
    __tablename__ = "org_drift_weights"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, unique=True)

    # Factual drift sub-signal weights (must sum to 1.0)
    density_weight = Column(Float, default=0.45)      # contradiction density signal
    confidence_weight = Column(Float, default=0.35)    # avg NLI confidence signal
    volume_weight = Column(Float, default=0.20)        # contradiction count signal

    # Combined drift blend weights (must sum to 1.0)
    factual_weight = Column(Float, default=0.60)       # factual → combined
    semantic_weight = Column(Float, default=0.40)       # semantic → combined

    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    organization = relationship("Organization", foreign_keys=[org_id])

