"""Alert routes: list, stats, update."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, forbid_viewer
from app.core.database import get_db
from app.models.models import Alert, AlertStatus, AlertSeverity, User
from app.schemas.schemas import (
    AlertListResponse,
    AlertResponse,
    AlertStatsResponse,
    AlertUpdateRequest,
)

router = APIRouter()


@router.get("", response_model=AlertListResponse)
async def list_alerts(
    status: str | None = Query(None),
    severity: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    filters = [Alert.org_id == user.org_id]
    if status:
        filters.append(Alert.status == status)
    if severity:
        filters.append(Alert.severity == severity)

    result = await db.execute(
        select(Alert)
        .where(and_(*filters))
        .order_by(Alert.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    alerts = result.scalars().all()

    count_q = await db.execute(select(func.count(Alert.id)).where(and_(*filters)))
    total = count_q.scalar() or 0

    return AlertListResponse(
        alerts=[AlertResponse.model_validate(a) for a in alerts],
        total=total,
    )


@router.get("/stats", response_model=AlertStatsResponse)
async def alert_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    base = Alert.org_id == user.org_id

    total_q = await db.execute(select(func.count(Alert.id)).where(base))
    total = total_q.scalar() or 0

    open_q = await db.execute(
        select(func.count(Alert.id)).where(base, Alert.status == AlertStatus.OPEN)
    )
    open_count = open_q.scalar() or 0

    critical_q = await db.execute(
        select(func.count(Alert.id)).where(base, Alert.severity == AlertSeverity.CRITICAL)
    )
    critical = critical_q.scalar() or 0

    high_q = await db.execute(
        select(func.count(Alert.id)).where(base, Alert.severity == AlertSeverity.HIGH)
    )
    high = high_q.scalar() or 0

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    resolved_q = await db.execute(
        select(func.count(Alert.id)).where(
            base,
            Alert.status == AlertStatus.RESOLVED,
            Alert.resolved_at >= today_start,
        )
    )
    resolved_today = resolved_q.scalar() or 0

    return AlertStatsResponse(
        total=total, open=open_count, critical=critical,
        high=high, resolved_today=resolved_today,
    )


@router.patch("/{alert_id}", response_model=AlertResponse)
async def update_alert(
    alert_id: str,
    req: AlertUpdateRequest,
    user: User = Depends(forbid_viewer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Alert).where(Alert.id == alert_id, Alert.org_id == user.org_id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.status = AlertStatus(req.status)
    if req.status == "resolved":
        alert.resolved_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(alert)
    return AlertResponse.model_validate(alert)
