"""Alerting service for managing alert lifecycle."""

from __future__ import annotations

import logging
from uuid import uuid4

from app.models.models import Alert, AlertType, AlertSeverity, AlertStatus

logger = logging.getLogger(__name__)


def create_alert(
    session,
    org_id: str,
    alert_type: AlertType,
    severity: AlertSeverity,
    title: str,
    description: str = "",
    evidence: dict | None = None,
    source_doc_id: str | None = None,
    target_doc_id: str | None = None,
    source_chunk_id: str | None = None,
    target_chunk_id: str | None = None,
) -> Alert:
    """Create and persist a new alert."""
    alert = Alert(
        id=uuid4(),
        org_id=org_id,
        alert_type=alert_type,
        severity=severity,
        title=title,
        description=description,
        evidence=evidence or {},
        source_doc_id=source_doc_id,
        target_doc_id=target_doc_id,
        source_chunk_id=source_chunk_id,
        target_chunk_id=target_chunk_id,
        status=AlertStatus.OPEN,
    )
    session.add(alert)
    return alert
