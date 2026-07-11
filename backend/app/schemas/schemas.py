"""Pydantic schemas for request/response validation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# ── Auth ──────────────────────────────────────────────


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1)
    org_name: str = "My Organization"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    org_id: UUID
    role: str
    is_active: bool

    class Config:
        from_attributes = True


# ── Documents ─────────────────────────────────────────


class DocumentResponse(BaseModel):
    id: UUID
    title: str
    filename: str
    file_type: str
    file_size: Optional[int] = None
    page_count: Optional[int] = None
    drift_score: float = 0.0
    semantic_drift_score: float = 0.0
    factual_drift_score: float = 0.0
    drift_type: Optional[str] = None
    is_processed: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


# ── Alerts ────────────────────────────────────────────


class AlertResponse(BaseModel):
    id: UUID
    alert_type: str
    severity: str
    title: str
    description: Optional[str] = None
    evidence: Optional[dict] = None
    status: str
    source_doc_id: Optional[UUID] = None
    target_doc_id: Optional[UUID] = None
    source_chunk_id: Optional[UUID] = None
    target_chunk_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AlertListResponse(BaseModel):
    alerts: list[AlertResponse]
    total: int


class AlertUpdateRequest(BaseModel):
    status: str


class AlertStatsResponse(BaseModel):
    total: int
    open: int
    critical: int
    high: int
    resolved_today: int


# ── Drift ─────────────────────────────────────────────


class DriftScoreResponse(BaseModel):
    document_id: UUID
    title: str
    drift_score: float
    semantic_drift_score: float = 0.0
    factual_drift_score: float = 0.0
    drift_type: Optional[str] = None
    contradiction_count: int = 0
    contradiction_examples: list = []
    factors: dict = {}


class DriftScoresListResponse(BaseModel):
    scores: list[DriftScoreResponse]


# ── Search ────────────────────────────────────────────


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10


class SearchResultItem(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    content: str
    score: float
    page: Optional[int] = None


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    query: str
    total: int


# ── Graph ─────────────────────────────────────────────


class GraphNode(BaseModel):
    id: str
    name: str
    type: str
    label: str


class GraphLink(BaseModel):
    source: str
    target: str
    relation: str
    confidence: float


class GraphVisualizationResponse(BaseModel):
    nodes: list[dict[str, Any]]
    links: list[dict[str, Any]]


# ── Evaluation ────────────────────────────────────────


class EvaluationResult(BaseModel):
    metric: str
    value: float
    details: dict = {}
