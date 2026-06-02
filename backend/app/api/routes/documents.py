"""Document upload, listing, retrieval, and deletion routes."""

from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

_utcnow = lambda: datetime.now(timezone.utc)  # noqa

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.models import Document, FileType, User
from app.schemas.schemas import DocumentListResponse, DocumentResponse

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_TYPES = {
    "application/pdf": FileType.PDF,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": FileType.DOCX,
    "text/plain": FileType.TXT,
    "text/markdown": FileType.MD,
}

EXTENSION_MAP = {
    ".pdf": FileType.PDF,
    ".docx": FileType.DOCX,
    ".txt": FileType.TXT,
    ".md": FileType.MD,
}


@router.post("/upload", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import hashlib
    from app.models.models import ProcessingStatus

    # Determine file type
    ext = Path(file.filename or "").suffix.lower()
    file_type = EXTENSION_MAP.get(ext) or ALLOWED_TYPES.get(file.content_type or "")
    if not file_type:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext or file.content_type}")

    # Read file bytes
    content = await file.read()
    file_size = len(content)
    if file_size > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File exceeds {settings.MAX_FILE_SIZE_MB}MB limit")

    # ── Content hash deduplication ──
    content_hash = hashlib.sha256(content).hexdigest()
    org_id = user.org_id

    # Check for exact duplicate (same content in same org)
    dup_result = await db.execute(
        select(Document).where(
            Document.org_id == org_id,
            Document.content_hash == content_hash,
            Document.deleted_at.is_(None),
        )
    )
    existing_dup = dup_result.scalar_one_or_none()
    if existing_dup:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Document with identical content already exists",
                "existing_document_id": str(existing_dup.id),
                "existing_title": existing_dup.title,
            },
        )

    # ── Filename-based version detection ──
    title = Path(file.filename or "Untitled").stem
    supersedes_id = None
    version_number = 1

    filename_result = await db.execute(
        select(Document).where(
            Document.org_id == org_id,
            Document.filename == (file.filename or ""),
            Document.deleted_at.is_(None),
        ).order_by(Document.created_at.desc())
    )
    existing_by_name = filename_result.scalar_one_or_none()

    if existing_by_name:
        # New content, same filename → version update
        supersedes_id = existing_by_name.id
        version_number = (existing_by_name.version_number or 1) + 1

        # Mark old document as superseded
        existing_by_name.processing_status = ProcessingStatus.COMPLETE
        existing_by_name.effective_until = _utcnow()

        logger.info(
            f"Version update: '{title}' v{version_number} supersedes "
            f"v{existing_by_name.version_number or 1} ({existing_by_name.id})"
        )

    # Save file to disk
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    doc_id = uuid4()
    saved_filename = f"{doc_id}{ext}"
    file_path = upload_dir / saved_filename

    with open(file_path, "wb") as f:
        f.write(content)

    doc = Document(
        id=doc_id,
        org_id=org_id,
        title=title,
        filename=file.filename or saved_filename,
        file_path=str(file_path),
        file_type=file_type,
        file_size=file_size,
        uploaded_by=user.id,
        content_hash=content_hash,
        supersedes_document_id=supersedes_id,
        version_number=version_number,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # Trigger background processing
    from app.tasks.tasks import process_document
    process_document.delay(
        document_id=str(doc.id),
        org_id=str(user.org_id),
        file_path=str(file_path),
        file_type=file_type.value,
    )

    return DocumentResponse.model_validate(doc)


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Document)
        .where(Document.org_id == user.org_id, Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    docs = result.scalars().all()

    count_q = await db.execute(
        select(func.count(Document.id))
        .where(Document.org_id == user.org_id, Document.deleted_at.is_(None))
    )
    total = count_q.scalar() or 0

    return DocumentListResponse(
        documents=[DocumentResponse.model_validate(d) for d in docs],
        total=total,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.org_id == user.org_id,
            Document.deleted_at.is_(None),
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse.model_validate(doc)


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timezone
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.org_id == user.org_id,
            Document.deleted_at.is_(None),
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    doc.deleted_at = datetime.now(timezone.utc)
    await db.commit()


@router.patch("/{document_id}")
async def update_document_metadata(
    document_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    authority_level: int | None = None,
    owner_department: str | None = None,
    document_type: str | None = None,
    effective_from: str | None = None,
    effective_until: str | None = None,
    version_number: int | None = None,
):
    """Update document governance metadata (authority, department, dates)."""
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.org_id == user.org_id,
            Document.deleted_at.is_(None),
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if authority_level is not None:
        if authority_level < 1 or authority_level > 5:
            raise HTTPException(400, "authority_level must be 1-5")
        doc.authority_level = authority_level

    if owner_department is not None:
        doc.owner_department = owner_department

    if document_type is not None:
        doc.document_type = document_type

    if effective_from is not None:
        from dateutil.parser import parse as dt_parse
        doc.effective_from = dt_parse(effective_from)

    if effective_until is not None:
        from dateutil.parser import parse as dt_parse
        doc.effective_until = dt_parse(effective_until)

    if version_number is not None:
        doc.version_number = version_number

    await db.commit()
    await db.refresh(doc)

    return {
        "id": str(doc.id),
        "authority_level": doc.authority_level,
        "owner_department": doc.owner_department,
        "document_type": doc.document_type,
        "effective_from": doc.effective_from.isoformat() if doc.effective_from else None,
        "effective_until": doc.effective_until.isoformat() if doc.effective_until else None,
        "version_number": doc.version_number,
    }


@router.post("/{document_id}/retry")
async def retry_failed_document(
    document_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retry processing a failed/partial document."""
    from app.models.models import ProcessingStatus

    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.org_id == user.org_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.processing_status not in (ProcessingStatus.FAILED, ProcessingStatus.PARTIAL):
        raise HTTPException(400, f"Document is '{doc.processing_status.value}', not retryable")

    from app.tasks.tasks import retry_failed_document as retry_task
    retry_task.delay(document_id=document_id, org_id=str(user.org_id))

    return {"status": "retry_queued", "document_id": document_id}


@router.get("/{document_id}/propagation")
async def get_propagation_impact(
    document_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trace the impact of changing this document across dependent documents."""
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.org_id == user.org_id,
            Document.deleted_at.is_(None),
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Build graph and trace impact (runs synchronously — fast for <100 docs)
    from app.core.database import SyncSession
    from app.propagation.analyzer import build_dependency_graph, trace_impact

    sync_session = SyncSession()
    try:
        graph = build_dependency_graph(sync_session, str(user.org_id))
        affected = trace_impact(graph, document_id)
    finally:
        sync_session.close()

    return {
        "source_document": {
            "id": str(doc.id),
            "title": doc.title,
            "authority_level": doc.authority_level,
        },
        "affected_documents": affected,
        "total_affected": len(affected),
        "graph_stats": {
            "total_nodes": graph.number_of_nodes(),
            "total_edges": graph.number_of_edges(),
        },
    }
