"""Celery background tasks for document processing, contradiction scanning, and drift recalculation."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4, UUID

from app.tasks.worker import celery_app
from app.core.config import settings

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.process_document")
def process_document(document_id: str, org_id: str, file_path: str, file_type: str):
    """Background task: parse, chunk, embed, and index a document.

    Processing state machine:
        PENDING → PROCESSING → COMPLETE
                      ↓
                   PARTIAL → (retry) → PROCESSING
                      ↓
                   FAILED  → (manual retry) → PENDING
    """
    try:
        from app.ingestion.router import ingest_document
        from app.core.database import SyncSession
        from app.models.models import Document, Chunk, Claim, ProcessingStatus, ContradictionPair
        from sqlalchemy.exc import OperationalError, IntegrityError, ProgrammingError

        session = SyncSession()
        try:
            doc = session.query(Document).filter(Document.id == document_id).first()
            if not doc:
                logger.error(f"Document {document_id} not found")
                return {"status": "error", "message": "Document not found"}

            doc_title = doc.title

            # ── Set PROCESSING state ──
            doc.processing_status = ProcessingStatus.PROCESSING
            if not doc.metadata_:
                doc.metadata_ = {}
            doc.metadata_["processing_started_at"] = datetime.now(timezone.utc).isoformat()
            session.commit()

            # ── Check for resume: skip already completed stages ──
            failed_stage = (doc.metadata_ or {}).get("failed_stage")
            completed_stages = (doc.metadata_ or {}).get("completed_stages", [])

            logger.info(f"Processing {file_type} document: {document_id} "
                        f"(resume_from={failed_stage}, completed={completed_stages})")

            # ── Stage 1: Parse + Chunk + Embed ──
            result = None
            if "ingestion" not in completed_stages:
                try:
                    result = ingest_document(
                        file_path=file_path,
                        file_type=file_type,
                        document_id=document_id,
                        org_id=org_id,
                        document_title=doc_title,
                    )
                    doc.metadata_["completed_stages"] = completed_stages + ["ingestion"]
                    doc.metadata_.pop("failed_stage", None)
                    session.commit()
                except Exception as e:
                    doc.processing_status = ProcessingStatus.FAILED
                    doc.metadata_["failed_stage"] = "ingestion"
                    doc.metadata_["failure_error"] = str(e)[:500]
                    session.commit()
                    logger.error(f"Stage 'ingestion' failed for {document_id}: {e}")
                    raise
            else:
                logger.info(f"Skipping completed stage 'ingestion' for {document_id}")

            if not result:
                doc.is_processed = True
                doc.processing_status = ProcessingStatus.COMPLETE
                session.commit()
                return {"status": "success", "chunk_count": 0}

            chunk_dicts, all_claims, page_count = result

            # ── Stage 2: Persist chunks ──
            try:
                from app.ingestion.embedder import get_embedding_info
                embed_info = get_embedding_info()

                for cd in chunk_dicts:
                    chunk = Chunk(
                        id=uuid4(),
                        document_id=UUID(document_id),
                        content=cd["content"],
                        chunk_index=cd["chunk_index"],
                        start_page=cd.get("start_page"),
                        end_page=cd.get("end_page"),
                        token_count=cd.get("token_count", 0),
                        embedding_id=cd.get("embedding_id"),
                        embedding_model_version=embed_info["version"],
                        embedding_dimension=embed_info["dimension"],
                        embedding_created_at=datetime.now(timezone.utc),
                    )
                    session.add(chunk)

                session.flush()
                doc.metadata_["completed_stages"] = (doc.metadata_.get("completed_stages") or []) + ["persist_chunks"]
                session.commit()
            except Exception as e:
                doc.processing_status = ProcessingStatus.PARTIAL
                doc.metadata_["failed_stage"] = "persist_chunks"
                doc.metadata_["failure_error"] = str(e)[:500]
                session.commit()
                logger.error(f"Stage 'persist_chunks' failed for {document_id}: {e}")
                raise

            # ── Stage 3: Persist claims ──
            try:
                db_chunks = session.query(Chunk).filter(Chunk.document_id == document_id).all()
                chunk_index_map = {c.chunk_index: c.id for c in db_chunks}

                for idx, cl in enumerate(all_claims):
                    chunk_db_id = chunk_index_map.get(cl["chunk_index"])
                    if chunk_db_id:
                        claim = Claim(
                            id=uuid4(),
                            document_id=UUID(document_id),
                            chunk_id=chunk_db_id,
                            content=cl["content"],
                            original_sentence=cl["original_sentence"],
                            importance_weight=cl["importance_weight"],
                            embedding_id=f"{document_id}_claim_{idx}",
                            subject=cl.get("subject", ""),
                            predicate=cl.get("predicate", ""),
                            value=cl.get("value", ""),
                            condition=cl.get("condition", ""),
                            modality=cl.get("modality"),
                            confidence=cl.get("confidence", 1.0),
                            extraction_model=cl.get("extraction_model", "unknown"),
                            content_hash=cl.get("content_hash", ""),
                        )
                        session.add(claim)

                doc.is_processed = True
                doc.processing_status = ProcessingStatus.COMPLETE
                doc.page_count = page_count if page_count else doc.page_count
                doc.metadata_["completed_stages"] = (doc.metadata_.get("completed_stages") or []) + ["persist_claims"]
                doc.metadata_["processing_completed_at"] = datetime.now(timezone.utc).isoformat()
                doc.metadata_.pop("failed_stage", None)
                doc.metadata_.pop("failure_error", None)
                session.commit()
            except Exception as e:
                doc.processing_status = ProcessingStatus.PARTIAL
                doc.metadata_["failed_stage"] = "persist_claims"
                doc.metadata_["failure_error"] = str(e)[:500]
                session.commit()
                logger.error(f"Stage 'persist_claims' failed for {document_id}: {e}")
                raise

            logger.info(f"Document {document_id} processed: {len(chunk_dicts)} chunks, {len(all_claims)} claims")

            # ── Invalidate cached explanations (Change 8) ──
            # New document content may change the context of existing contradictions
            try:
                stale_count = (
                    session.query(ContradictionPair)
                    .filter(
                        ContradictionPair.org_id == org_id,
                        ContradictionPair.explanation_valid == True,
                        ContradictionPair.explanation.isnot(None),
                    )
                    .update({"explanation_valid": False})
                )
                session.commit()
                if stale_count > 0:
                    logger.info(f"Invalidated {stale_count} cached explanations in org {org_id}")
            except (OperationalError, IntegrityError, ProgrammingError) as e:
                logger.warning(f"Explanation invalidation failed (DB error): {e}")

            # Trigger contradiction scan
            run_contradiction_scan.delay(
                document_id=document_id,
                org_id=org_id,
            )

            return {"status": "success", "chunk_count": len(chunk_dicts)}

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    except Exception as e:
        logger.error(f"Document processing failed: {e}", exc_info=True)
        raise


@celery_app.task(name="tasks.retry_failed_document", bind=True, max_retries=3)
def retry_failed_document(self, document_id: str, org_id: str):
    """Retry a failed document by resetting its state and reprocessing."""
    try:
        from app.core.database import SyncSession
        from app.models.models import Document, ProcessingStatus

        session = SyncSession()
        try:
            doc = session.query(Document).filter(Document.id == document_id).first()
            if not doc:
                return {"status": "error", "message": "Document not found"}

            if doc.processing_status not in (ProcessingStatus.FAILED, ProcessingStatus.PARTIAL):
                return {"status": "skipped", "message": f"Document is {doc.processing_status.value}, not retryable"}

            logger.info(f"Retrying failed document {document_id} "
                        f"(failed_stage={doc.metadata_.get('failed_stage')})")

            # Reset to PENDING for fresh retry
            doc.processing_status = ProcessingStatus.PENDING
            session.commit()

            # Re-trigger processing
            process_document.delay(
                document_id=document_id,
                org_id=org_id,
                file_path=doc.file_path,
                file_type=doc.file_type.value,
            )

            return {"status": "retrying"}
        finally:
            session.close()

    except Exception as e:
        logger.error(f"Retry failed for {document_id}: {e}")
        raise self.retry(exc=e, countdown=30)


def _shortlist_candidate_docs(org_id: str, document_id: str, doc_chunks) -> list[str]:
    """Return live candidate docs to scan against, by loose document-level similarity.

    Embeds each chunk of the source doc, retrieves similar chunks across the org,
    and collects the distinct parent doc IDs whose best similarity clears the
    (deliberately loose) SHORTLIST_SIM_THRESHOLD. Excludes the source doc itself
    and any deleted doc. Bounded by RESCAN_MAX_CANDIDATES.
    """
    from app.core.config import settings
    from app.core.database import SyncSession
    from app.models.models import Document
    from app.ingestion.embedder import generate_single_embedding
    from app.ingestion.indexer import query_similar

    best_sim: dict[str, float] = {}
    for ch in doc_chunks:
        if not ch.content:
            continue
        try:
            emb = generate_single_embedding(ch.content)
            # Query the claims collection (claim-level detection); it is the
            # retrieval surface that actually feeds the pairwise scan.
            res = query_similar(
                org_id,
                emb,
                top_k=max(settings.RESCAN_MAX_CANDIDATES * 4, 40),
                where_filter={"is_claim": True},
            )
        except Exception as e:
            logger.warning(f"Shortlist retrieval failed for a chunk of {document_id}: {e}")
            continue
        ids = res.get("ids", [[]])
        metas = res.get("metadatas", [[]])
        dists = res.get("distances", [[]])
        if not ids or not ids[0]:
            continue
        for i, _vid in enumerate(ids[0]):
            meta = metas[0][i] if metas and metas[0] else {}
            did = str(meta.get("document_id"))
            if not did or did == str(document_id):
                continue
            dist = dists[0][i] if dists and dists[0] else 1.0
            sim = 1.0 - dist
            if sim > best_sim.get(did, -1.0):
                best_sim[did] = sim

    candidates = [d for d, s in best_sim.items() if s >= settings.SHORTLIST_SIM_THRESHOLD]
    if not candidates:
        return []

    # Drop deleted docs and rank by similarity, bounded.
    session = SyncSession()
    try:
        live = {
            str(row[0])
            for row in session.query(Document.id)
            .filter(Document.id.in_(candidates), Document.deleted_at.is_(None))
            .all()
        }
    finally:
        session.close()

    ranked = sorted((d for d in candidates if d in live), key=lambda d: best_sim[d], reverse=True)
    return ranked[: settings.RESCAN_MAX_CANDIDATES]


def _scan_and_persist_pair(session, org_id, source_doc_id, doc_title, candidate_doc_id, metrics=None) -> int:
    """Routed contradiction scan of one (source, candidate) doc pair, persisted at claim grain.

    Builds embedding→chunk/doc/claim maps over live docs, runs the routed scanner
    for the single pair, then dedups and stores ContradictionPairs (+ alerts).
    Returns the number of NEW pairs saved. Shared by the queued fan-out task (Fix B)
    — keeping detection+persistence in one place so a single pair is a unit of work.
    """
    from app.models.models import (
        Document, Chunk, Claim, Alert, AlertType, AlertSeverity, AlertStatus,
        ContradictionPair, ContradictionClassification, ScannedPair,
    )
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.contradiction.detector import scan_document_pair_routed
    from app.temporal.resolver import (
        classify_temporal_relationship, get_document_temporal_context,
    )
    from sqlalchemy import and_, or_

    # ── Embedding-ID maps across live docs ──
    all_org_chunks = session.query(Chunk).join(
        Document, Chunk.document_id == Document.id
    ).filter(Document.org_id == org_id).all()
    embedding_to_chunk_id = {c.embedding_id: str(c.id) for c in all_org_chunks if c.embedding_id}
    embedding_to_doc_id = {c.embedding_id: str(c.document_id) for c in all_org_chunks if c.embedding_id}
    embedding_to_claim_id = {}
    all_org_claims = session.query(Claim).join(
        Document, Claim.document_id == Document.id
    ).filter(Document.org_id == org_id, Document.deleted_at.is_(None)).all()
    for cl in all_org_claims:
        if cl.embedding_id:
            embedding_to_chunk_id[cl.embedding_id] = str(cl.chunk_id)
            embedding_to_doc_id[cl.embedding_id] = str(cl.document_id)
            embedding_to_claim_id[cl.embedding_id] = str(cl.id)

    def _doc_inputs(did):
        chs = session.query(Chunk).filter(Chunk.document_id == did).order_by(Chunk.chunk_index).all()
        text = "\n".join(ch.content for ch in chs if ch.content)
        emb_ids = [ch.embedding_id for ch in chs if ch.embedding_id]
        return text, emb_ids

    src_text, src_emb = _doc_inputs(source_doc_id)
    cand_text, cand_emb = _doc_inputs(candidate_doc_id)

    results, scan_path = scan_document_pair_routed(
        org_id=org_id,
        doc_a_text=src_text,
        doc_b_text=cand_text,
        doc_a_id=str(source_doc_id),
        doc_b_id=str(candidate_doc_id),
        doc_a_chunk_ids=src_emb,
        doc_b_chunk_ids=cand_emb,
        metrics=metrics,
    )
    if results:
        logger.info(
            f"Routed scan ({scan_path}) {source_doc_id}↔{candidate_doc_id}: "
            f"{len(results)} contradictions"
        )

    _doc_context_cache = {}

    def _get_doc_context(doc_id_str):
        if doc_id_str not in _doc_context_cache:
            d = session.query(Document).filter(Document.id == doc_id_str).first()
            _doc_context_cache[doc_id_str] = (
                get_document_temporal_context(d) if d else {"id": doc_id_str}
            )
        return _doc_context_cache[doc_id_str]

    saved_count = 0
    for c in results:
        db_chunk_a_id = embedding_to_chunk_id.get(c.chunk_a_id)
        db_chunk_b_id = embedding_to_chunk_id.get(c.chunk_b_id)
        target_doc_id = embedding_to_doc_id.get(c.chunk_b_id)

        if not db_chunk_a_id or not db_chunk_b_id:
            logger.warning(
                f"Skipping contradiction: could not resolve chunk IDs "
                f"({c.chunk_a_id} → {db_chunk_a_id}, {c.chunk_b_id} → {db_chunk_b_id})"
            )
            continue

        # ── Resolve claim IDs and canonicalize ordering (Fix C) ──
        claim_a_id = embedding_to_claim_id.get(c.chunk_a_id)
        claim_b_id = embedding_to_claim_id.get(c.chunk_b_id)

        if claim_a_id and claim_b_id:
            if claim_a_id == claim_b_id:
                continue  # self-pair; CHECK requires strict ordering
            if claim_a_id > claim_b_id:
                claim_a_id, claim_b_id = claim_b_id, claim_a_id
                db_chunk_a_id, db_chunk_b_id = db_chunk_b_id, db_chunk_a_id

            existing = session.query(ContradictionPair).filter(
                ContradictionPair.claim_a_id == claim_a_id,
                ContradictionPair.claim_b_id == claim_b_id,
            ).first()
            if existing:
                continue
        else:
            claim_a_id = claim_b_id = None
            existing = session.query(ContradictionPair).filter(
                or_(
                    and_(ContradictionPair.chunk_a_id == db_chunk_a_id, ContradictionPair.chunk_b_id == db_chunk_b_id),
                    and_(ContradictionPair.chunk_a_id == db_chunk_b_id, ContradictionPair.chunk_b_id == db_chunk_a_id),
                )
            ).first()
            if existing:
                continue

        # ── Temporal reasoning: evolution vs contradiction ──
        is_evolution = False
        is_inferred_lineage = False
        temporal_reason = ""
        classification = ContradictionClassification(c.classification.lower())

        if c.requires_review:
            alert_severity = AlertSeverity.MEDIUM
        elif c.confidence > 0.8:
            alert_severity = AlertSeverity.HIGH
        else:
            alert_severity = AlertSeverity.MEDIUM

        if target_doc_id:
            try:
                ctx_a = _get_doc_context(str(source_doc_id))
                ctx_b = _get_doc_context(str(target_doc_id))
                temporal = classify_temporal_relationship(
                    ctx_a, ctx_b, c.chunk_a_text, c.chunk_b_text
                )
                if not temporal.is_genuine_contradiction:
                    is_evolution = True
                    is_inferred_lineage = temporal.inferred
                    temporal_reason = temporal.reason
                    classification = ContradictionClassification.EVOLUTION
                    alert_severity = AlertSeverity.LOW
            except Exception as e:
                logger.debug(f"Temporal check failed, treating as contradiction: {e}")

        pair = ContradictionPair(
            id=uuid4(),
            org_id=org_id,
            chunk_a_id=db_chunk_a_id,
            chunk_b_id=db_chunk_b_id,
            claim_a_id=claim_a_id,
            claim_b_id=claim_b_id,
            classification=classification,
            confidence=c.confidence,
            scan_path=getattr(c, "scan_path", None) or None,
            contradiction_type=getattr(c, "contradiction_type", None) or None,
            explanation=c.explanation if not is_evolution else f"[Policy Evolution] {temporal_reason}. {c.explanation}",
            conflicting_claims=c.conflicting_claims,
            is_temporal_evolution=is_evolution,
            inferred_lineage=is_inferred_lineage,
            sampled=c.sampled,
            gate_similarity=c.gate_similarity,
        )
        session.add(pair)

        alert = Alert(
            id=uuid4(),
            org_id=org_id,
            alert_type=AlertType.CONTRADICTION,
            severity=alert_severity,
            source_doc_id=str(source_doc_id),
            target_doc_id=str(target_doc_id) if target_doc_id else None,
            source_chunk_id=db_chunk_a_id,
            target_chunk_id=db_chunk_b_id,
            title=f"{'Policy evolution' if is_evolution else 'Contradiction'} detected in {doc_title}",
            description=c.explanation if not is_evolution else f"[Policy Evolution] {temporal_reason}",
            evidence={
                "claim_a": c.conflicting_claims[0] if len(c.conflicting_claims) > 0 else c.chunk_a_text[:200],
                "claim_b": c.conflicting_claims[1] if len(c.conflicting_claims) > 1 else c.chunk_b_text[:200],
                "confidence": c.confidence,
                "confidence_band": c.confidence_band,
                "requires_review": c.requires_review,
                "is_temporal_evolution": is_evolution,
                "temporal_reason": temporal_reason,
            },
            status=AlertStatus.OPEN,
        )
        session.add(alert)
        session.flush()

        if not is_evolution and alert.severity in (AlertSeverity.HIGH, AlertSeverity.CRITICAL):
            from app.alerting.webhooks import trigger_alert_webhook
            trigger_alert_webhook(org_id, {
                "id": str(alert.id),
                "alert_type": alert.alert_type.value,
                "severity": alert.severity.value,
                "title": alert.title,
                "description": alert.description,
                "evidence": alert.evidence,
            })

        saved_count += 1

    # ── Ledger: record this pair as scanned (canonical order, UUID-value sorted
    # to match Postgres' ck_scanned_pair_order), so reconciliation never
    # re-queues it. ON CONFLICT DO NOTHING keeps it idempotent and race-safe when
    # two reconcile passes overlap. Committed with the scan results by the caller.
    a_id, b_id = sorted((str(source_doc_id), str(candidate_doc_id)), key=UUID)
    if a_id != b_id:
        session.execute(
            pg_insert(ScannedPair.__table__)
            .values(id=uuid4(), org_id=org_id, doc_a_id=a_id, doc_b_id=b_id)
            .on_conflict_do_nothing(constraint="uq_scanned_pair")
        )

    return saved_count


@celery_app.task(name="tasks.scan_document_pair", rate_limit=settings.RESCAN_TASK_RATE_LIMIT)
def scan_document_pair(org_id: str, source_doc_id: str, candidate_doc_id: str):
    """Scan one (source, candidate) document pair for contradictions (queued fan-out, Fix B).

    Rate-limited so a burst of uploads can't flood the worker with CPU-bound NLI.
    Idempotent: claim-grain dedup means re-running never duplicates pairs.
    """
    from app.core.database import SyncSession
    from app.models.models import Document

    session = SyncSession()
    saved = 0
    try:
        doc = session.query(Document).filter(Document.id == source_doc_id).first()
        if not doc:
            return {"status": "error", "reason": "source_not_found"}
        saved = _scan_and_persist_pair(session, org_id, source_doc_id, doc.title, candidate_doc_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    # Recalc drift inline the moment this pair yields contradictions, so the doc
    # reflects them right away. The chord callback recalc can be starved for many
    # minutes behind other slow NLI scans in the FIFO queue (a reconcile mesh, a
    # bulk upload) — which is why an uploaded doc kept showing 0 even though its
    # pairs were already saved. Debounced per org so a scan burst doesn't recompute
    # the whole org on every single pair.
    if saved > 0:
        _recalc_drift_debounced(org_id)

    return {"status": "success", "saved": saved, "pair": [str(source_doc_id), str(candidate_doc_id)]}


def _recalc_drift_debounced(org_id: str, min_interval_s: int = 15) -> None:
    """Run an inline org drift recalc, at most once per min_interval_s per org.

    Lets drift climb in near-real-time as contradictions are found, without
    recomputing the whole org on every single pair scan during a burst. Runs
    synchronously in the current worker process (no queue hop), so it can't be
    starved behind slow scan tasks. Falls through to recalc if Redis is down.
    """
    try:
        import redis as _redis
        r = _redis.Redis.from_url(settings.REDIS_URL)
        if not r.set(f"recalc_recent:{org_id}", "1", nx=True, ex=min_interval_s):
            return  # recalc ran very recently; the final chord recalc will catch up
    except Exception:
        pass  # redis unavailable → just recalc
    try:
        recalculate_drift_scores(org_id=org_id)
    except Exception as e:
        logger.warning(f"Inline drift recalc failed for org {org_id}: {e}")


def _schedule_reconcile(org_id: str, countdown: int = 45, debounce_s: int = 120) -> None:
    """Schedule at most one deferred reconciliation per org, debounced via Redis.

    A burst of uploads would otherwise each trigger a full org-mesh reconcile,
    flooding the worker with slow NLI scans. An NX lock collapses the burst into
    a single deferred pass that runs once claims have settled. If Redis is
    unavailable we still schedule one (correctness over de-dup).
    """
    try:
        import redis as _redis
        r = _redis.Redis.from_url(settings.REDIS_URL)
        acquired = r.set(f"reconcile_pending:{org_id}", "1", nx=True, ex=debounce_s)
        if not acquired:
            return  # a reconcile is already pending for this org
    except Exception as e:
        logger.warning(f"Reconcile debounce lock unavailable for {org_id}: {e}")
    reconcile_contradiction_scans.apply_async(kwargs={"org_id": org_id}, countdown=countdown)


@celery_app.task(name="tasks.reconcile_contradiction_scans")
def reconcile_contradiction_scans(org_id: str):
    """Queue any live-doc pair missing from the scanned-pairs ledger, then recalc drift.

    Closes the concurrent/bulk-upload gap (CLAUDE.md §10): when one document's
    candidate shortlist is built before another's claims finish indexing, their
    pair is never scanned and nothing rescans it. This pass enumerates every
    unordered pair of live docs, subtracts the ledger, and fans out
    scan_document_pair for the gaps (bounded by RECONCILE_MAX_PAIRS), with a drift
    recalc as the chord callback. Ledger-gated, so it converges — a scanned pair
    is never re-queued — and the catch-up scans do NOT re-trigger reconciliation.
    """
    from itertools import combinations
    from celery import chord, group
    from app.core.database import SyncSession
    from app.models.models import Document, ScannedPair
    from uuid import UUID as _UUID

    session = SyncSession()
    try:
        live = sorted(
            (str(r[0]) for r in session.query(Document.id)
             .filter(Document.org_id == org_id, Document.deleted_at.is_(None)).all()),
            key=_UUID,
        )
        scanned = {
            (str(a), str(b))
            for a, b in session.query(ScannedPair.doc_a_id, ScannedPair.doc_b_id)
            .filter(ScannedPair.org_id == org_id).all()
        }
    finally:
        session.close()

    # combinations over UUID-sorted ids yields canonical (a, b) pairs aligned with
    # how the ledger stores them, so set membership lines up exactly.
    missing = [pair for pair in combinations(live, 2) if pair not in scanned]

    if not missing:
        recalculate_drift_scores.delay(org_id=org_id)
        logger.info(f"Reconcile org {org_id}: no missing pairs ({len(live)} live docs)")
        return {"status": "success", "queued": 0, "missing": 0}

    capped = missing[: settings.RECONCILE_MAX_PAIRS]
    chord(
        group(scan_document_pair.s(org_id, a, b) for a, b in capped)
    )(recalculate_drift_scores.si(org_id=org_id))

    if len(missing) > len(capped):
        logger.warning(
            f"Reconcile org {org_id}: {len(missing)} missing pairs, queued {len(capped)} "
            f"(capped at {settings.RECONCILE_MAX_PAIRS}); rerun reconcile to drain the rest"
        )
    else:
        logger.info(f"Reconcile org {org_id}: queued {len(capped)} previously-unscanned pair(s)")
    return {"status": "success", "queued": len(capped), "missing": len(missing)}


@celery_app.task(name="tasks.run_contradiction_scan")
def run_contradiction_scan(document_id: str, org_id: str):
    """Background task: scan for contradictions using NLI on claims."""
    try:
        from app.contradiction.detector import scan_claims_nli
        from app.ingestion.indexer import get_or_create_collection, query_similar
        from app.core.database import SyncSession
        from app.models.models import (
            Document, Chunk, Claim, Alert, AlertType, AlertSeverity, AlertStatus,
            ContradictionPair, ContradictionClassification,
        )
        from app.core.config import settings

        session = SyncSession()
        try:
            doc = session.query(Document).filter(Document.id == document_id).first()
            if not doc:
                logger.error(f"Document {document_id} not found for contradiction scan")
                return {"status": "error"}

            doc_title = doc.title

            # Fetch claims for this document
            claims = session.query(Claim).filter(Claim.document_id == document_id).all()

            if not claims:
                # Try to extract claims from existing chunks first
                from app.ingestion.extractor import extract_claims
                from app.ingestion.embedder import generate_embeddings
                from app.ingestion.indexer import upsert_embeddings

                chunks = session.query(Chunk).filter(Chunk.document_id == document_id).all()
                if chunks:
                    logger.info(f"No claims found for {document_id}, extracting from {len(chunks)} chunks")
                    all_extracted_claims = []
                    for c in chunks:
                        extracted = extract_claims(c.content)
                        for ecl in extracted:
                            all_extracted_claims.append({
                                "content": ecl.content,
                                "original_sentence": ecl.original_sentence,
                                "importance_weight": ecl.importance_weight,
                                "chunk_index": c.chunk_index,
                                "chunk_id": c.id,
                            })

                    if all_extracted_claims:
                        # Persist claims to DB
                        for i, cl in enumerate(all_extracted_claims):
                            claim = Claim(
                                id=uuid4(),
                                document_id=UUID(document_id),
                                chunk_id=cl["chunk_id"],
                                content=cl["content"],
                                original_sentence=cl["original_sentence"],
                                importance_weight=cl["importance_weight"],
                                embedding_id=f"{document_id}_claim_{i}",
                            )
                            session.add(claim)
                        session.flush()

                        # Index claim embeddings in ChromaDB
                        claim_texts = [cl["content"] for cl in all_extracted_claims]
                        claim_embeddings = generate_embeddings(claim_texts)
                        claim_ids = [f"{document_id}_claim_{i}" for i in range(len(all_extracted_claims))]
                        claim_metadatas = [
                            {
                                "document_id": document_id,
                                "document_title": doc_title,
                                "chunk_index": cl["chunk_index"],
                                "is_claim": True,
                            }
                            for cl in all_extracted_claims
                        ]
                        upsert_embeddings(org_id, claim_ids, claim_embeddings, claim_texts, claim_metadatas)
                        logger.info(f"Extracted and indexed {len(all_extracted_claims)} claims for {document_id}")

                        # Re-fetch claims from DB
                        claims = session.query(Claim).filter(Claim.document_id == document_id).all()

            if not claims:
                # Final fallback: use chunks directly
                chunks = session.query(Chunk).filter(Chunk.document_id == document_id).all()
                claims_data = [
                    {"id": c.embedding_id, "text": c.content, "chunk_id": str(c.id)}
                    for c in chunks if c.embedding_id
                ]
            else:
                claims_data = [
                    {
                        "id": cl.embedding_id,
                        "text": cl.content,
                        "chunk_id": str(cl.chunk_id),
                        "modality": getattr(cl, "modality", None),
                    }
                    for cl in claims if cl.embedding_id
                ]

            # ── Drift denominator: this doc's salient claim count ──
            if settings.NOISE_FILTER_ENABLED:
                from app.pipeline.noise_filter import check_claim_worthy
                salient = [c for c in claims_data if check_claim_worthy(c["text"])[0]]
            else:
                salient = claims_data
            doc.aligned_claims = len(salient)

            # ── Shortlist candidate live docs (loose). Each (this_doc, candidate)
            # pair is scanned by a bounded fan-out of queued jobs below
            # (Fix A: routed pairwise scan; Fix B: queued fan-out). ──
            this_chunks = (
                session.query(Chunk)
                .filter(Chunk.document_id == document_id)
                .order_by(Chunk.chunk_index)
                .all()
            )
            candidate_doc_ids = _shortlist_candidate_docs(org_id, str(document_id), this_chunks)
            logger.info(
                f"Routed scan: {len(candidate_doc_ids)} candidate docs for {document_id}"
            )

            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        # ── Bounded fan-out of pairwise scans, then reconcile + recalc (Fix B) ──
        # One queued, rate-limited job per candidate doc (parallel + bounded),
        # with a chord callback that runs reconciliation once all pairs finish.
        #
        # The shortlist above is built from the claims vector collection, which is
        # populated earlier in this same task. Under rapid/concurrent uploads, doc
        # N's shortlist can run before doc N-1's claims finish indexing, so the
        # (N-1, N) pair is skipped here. reconcile_contradiction_scans is the
        # callback (not recalc directly): by the time it runs, all claims are
        # indexed, and it diffs live-doc pairs against the scanned-pairs ledger to
        # queue whatever this race missed — then recalculates drift. Closes the
        # former known limitation (CLAUDE.md §10).
        from celery import chord, group

        # Recalc is the chord callback — drift updates as soon as THIS doc's own
        # shortlist pairs finish scanning (a small, bounded fan-out). Reconcile is
        # deliberately NOT chained here: it does a full org-mesh diff and can queue
        # many slow NLI scans, which would sit ahead of this recalc in the worker
        # queue and starve it — the doc would keep showing 0 even though its pairs
        # are already saved. Reconcile runs separately, debounced (see below).
        if candidate_doc_ids:
            chord(
                group(
                    scan_document_pair.s(org_id, str(document_id), cand)
                    for cand in candidate_doc_ids
                )
            )(recalculate_drift_scores.si(org_id=org_id))
        else:
            recalculate_drift_scores.delay(org_id=org_id)

        # Background race-safety net (concurrent/bulk uploads), kept off the hot
        # path and collapsed to one deferred pass per burst so it can't flood.
        _schedule_reconcile(org_id)

        logger.info(
            f"Contradiction scan for {document_id}: fanned out "
            f"{len(candidate_doc_ids)} pairwise scan(s)"
        )
        return {"status": "success", "candidates": len(candidate_doc_ids)}

    except Exception as e:
        logger.error(f"Contradiction scan failed: {e}", exc_info=True)
        raise


@celery_app.task(name="tasks.recalculate_drift_scores")
def recalculate_drift_scores(org_id: str):
    """Background task: recalculate drift scores for all documents using the dual drift formula."""
    try:
        from app.core.database import SyncSession
        from app.models.models import Document, Alert, AlertType, AlertStatus, Chunk, Claim, ContradictionPair, OrgDriftWeights
        from app.drift.scorer import compute_dual_drift_score, compute_age_decay
        from app.ingestion.indexer import get_or_create_collection, query_similar
        from app.ingestion.embedder import generate_single_embedding
        from sqlalchemy import func, or_

        session = SyncSession()
        try:
            # Load per-org weights (if configured)
            org_weights_row = session.query(OrgDriftWeights).filter(OrgDriftWeights.org_id == org_id).first()
            org_weights = None
            if org_weights_row:
                org_weights = {
                    "density_weight": org_weights_row.density_weight,
                    "confidence_weight": org_weights_row.confidence_weight,
                    "volume_weight": org_weights_row.volume_weight,
                    "factual_weight": org_weights_row.factual_weight,
                    "semantic_weight": org_weights_row.semantic_weight,
                }
                logger.info(f"Using custom drift weights for org {org_id}: {org_weights}")

            docs = (
                session.query(Document)
                .filter(Document.org_id == org_id, Document.deleted_at.is_(None))
                .all()
            )

            if not docs:
                logger.info(f"No documents found for org {org_id}")
                return {"status": "success", "updated_count": 0}

            for doc in docs:
                # Factor 1: Age decay
                age_decay = compute_age_decay(doc.created_at)

                # Factor 2: Contradiction ratio (exclude temporal evolutions)
                all_pairs = (
                    session.query(ContradictionPair)
                    .join(Chunk, or_(ContradictionPair.chunk_a_id == Chunk.id, ContradictionPair.chunk_b_id == Chunk.id))
                    .filter(Chunk.document_id == doc.id)
                    .distinct(ContradictionPair.id)
                    .all()
                )
                # Only genuine contradictions count toward factual drift
                contradictions = [
                    p for p in all_pairs
                    if not p.is_temporal_evolution
                    and p.review_status not in ('REJECTED', 'FALSE_POSITIVE', 'INTENTIONAL_DIVERGENCE')
                ]

                aligned_claims = doc.aligned_claims or 0
                denom = max(aligned_claims, 1)
                contradiction_ratio = len(contradictions) / denom
                avg_confidence = (
                    sum(c.confidence for c in contradictions) / len(contradictions)
                    if contradictions else 0.0
                )

                # Factor 3: Semantic shift (embedding dispersion)
                semantic_shift = 0.0
                try:
                    chunks = session.query(Chunk).filter(Chunk.document_id == doc.id).all()
                    if chunks:
                        sample = chunks[0]
                        if sample.content:
                            emb = generate_single_embedding(sample.content)
                            similar = query_similar(str(org_id), emb, top_k=10)
                            if similar["distances"] and similar["distances"][0]:
                                # Filter out self-matches (distance ≈ 0)
                                cross_doc_dists = [
                                    d for i, d in enumerate(similar["distances"][0])
                                    if d > 0.01  # exclude self-match
                                ]
                                if cross_doc_dists:
                                    avg_dist = sum(cross_doc_dists) / len(cross_doc_dists)
                                    semantic_shift = min(1.0, avg_dist)
                except Exception as e:
                    logger.warning(f"Semantic shift computation failed for {doc.id}: {e}")

                # Compute dual drift
                scores = compute_dual_drift_score(
                    contradiction_ratio=contradiction_ratio,
                    avg_contradiction_confidence=avg_confidence,
                    semantic_shift=semantic_shift,
                    age_decay=age_decay,
                    contradiction_count=len(contradictions),
                    aligned_claims_count=aligned_claims,
                    authority_level=doc.authority_level or 3,
                    org_weights=org_weights,
                )

                doc.factual_drift_score = scores["factual_drift_score"]
                doc.semantic_drift_score = scores["semantic_drift_score"]
                doc.drift_score = scores["combined_drift_score"]
                doc.drift_type = scores["drift_type"]

            session.commit()
            logger.info(f"Recalculated drift scores for {len(docs)} documents in org {org_id}")
            return {"status": "success", "updated_count": len(docs)}

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    except Exception as e:
        logger.error(f"Drift recalculation failed: {e}", exc_info=True)
        raise


@celery_app.task(name="tasks.backfill_alert_explanations")
def backfill_alert_explanations(org_id: str):
    """Retroactively generate Gemini explanations for alerts with placeholder text."""
    try:
        from app.contradiction.detector import _generate_explanation
        from app.core.database import SyncSession
        from app.models.models import Alert

        session = SyncSession()
        try:
            # Find alerts with the old NLI template explanation
            alerts = session.query(Alert).filter(
                Alert.org_id == org_id,
                Alert.description.like("NLI model detected contradiction with score%"),
            ).all()

            updated = 0
            for alert in alerts:
                evidence = alert.evidence or {}
                claim_a = evidence.get("claim_a", "")
                claim_b = evidence.get("claim_b", "")
                confidence = evidence.get("confidence", 0.0)

                if claim_a and claim_b:
                    explanation = _generate_explanation(claim_a, claim_b, confidence)
                    # Only update if we got a real explanation (not the fallback)
                    if "NLI model detected" not in explanation and "The system detected" not in explanation:
                        alert.description = explanation
                        updated += 1
                        logger.info(f"Updated explanation for alert {alert.id}")

            session.commit()
            logger.info(f"Backfilled {updated}/{len(alerts)} alert explanations in org {org_id}")
            return {"status": "success", "updated": updated, "total": len(alerts)}

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    except Exception as e:
        logger.error(f"Backfill alert explanations failed: {e}", exc_info=True)
        raise


@celery_app.task(name="tasks.sweep_orphan_vectors")
def sweep_orphan_vectors(org_id: str):
    """Reconcile the vector store against live documents, deleting orphan vectors.

    Removes ChromaDB vectors whose parent document is soft-deleted or no longer
    present in Postgres (P0). Safe to run repeatedly.
    """
    try:
        from app.core.database import SyncSession
        from app.models.models import Document
        from app.ingestion.indexer import sweep_orphan_vectors as _sweep

        session = SyncSession()
        try:
            live_ids = {
                str(row[0])
                for row in session.query(Document.id)
                .filter(Document.org_id == org_id, Document.deleted_at.is_(None))
                .all()
            }
        finally:
            session.close()

        stats = _sweep(org_id, live_ids)
        logger.info(f"Orphan vector sweep for org {org_id}: {stats}")
        return {"status": "success", "stats": stats}

    except Exception as e:
        logger.error(f"Orphan vector sweep failed: {e}", exc_info=True)
        raise

