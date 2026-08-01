"""Document ingestion router — orchestrates parsing, chunking, embedding, and indexing."""

from __future__ import annotations

import logging
from pathlib import Path

from app.ingestion.chunker import chunk_text, ChunkResult
from app.ingestion.cleaner import clean_text
from app.ingestion.embedder import generate_embeddings
from app.ingestion.indexer import upsert_embeddings
from app.ingestion.extractor import extract_claims
from app.ingestion.table_linearizer import ParsedTable, linearize_tables

logger = logging.getLogger(__name__)


def ingest_document(
    file_path: str,
    file_type: str,
    document_id: str,
    org_id: str,
    document_title: str = "Untitled",
) -> list[dict]:
    """Full ingestion pipeline: parse → clean → chunk → embed → index.

    Returns list of chunk dicts with content, embedding_id, etc.
    """
    logger.info(f"Parsing {file_type} document: {document_id}")

    # 1. Parse
    text, page_count, page_map, tables = _parse_file(file_path, file_type)

    # 2. Clean
    text = clean_text(text)

    # 3. Chunk prose
    prose_chunks = (
        chunk_text(text, page_map=page_map if page_map else None)
        if text.strip()
        else []
    )

    # 3b. Tables → synthetic chunks + structured claims (one chunk per table)
    table_chunks, table_claims = _build_table_artifacts(
        tables, document_id, start_index=len(prose_chunks)
    )

    chunks = prose_chunks + table_chunks
    logger.info(
        f"Created {len(prose_chunks)} prose + {len(table_chunks)} table chunks "
        f"from {Path(file_path).name}"
    )

    if not chunks:
        logger.warning(f"Document {document_id} produced no text after cleaning")
        return []

    # 4. Embed chunks
    chunk_texts = [c.content for c in chunks]
    embeddings = generate_embeddings(chunk_texts)

    # 5. Index in ChromaDB
    chunk_ids = [f"{document_id}_chunk_{c.chunk_index}" for c in chunks]
    metadatas = [
        {
            "document_id": document_id,
            "document_title": document_title,
            "chunk_index": c.chunk_index,
            "start_page": c.start_page or 0,
            "end_page": c.end_page or 0,
            "is_claim": False,
            "is_table": bool(c.is_table),
        }
        for c in chunks
    ]

    upsert_embeddings(org_id, chunk_ids, embeddings, chunk_texts, metadatas)

    # 6. Extract and embed claims
    from app.ingestion.extractor import compute_content_hash

    all_claims = []
    for c in prose_chunks:
        claims = extract_claims(c.content)
        content_hash = compute_content_hash(c.content)
        for claim in claims:
            all_claims.append({
                "content": claim.content,
                "original_sentence": claim.original_sentence,
                "importance_weight": claim.importance_weight,
                "chunk_index": c.chunk_index,
                # Structured fields from LLM extraction
                "subject": claim.subject,
                "predicate": claim.predicate,
                "value": claim.value,
                "condition": claim.condition,
                "effective_from": claim.effective_from,
                "effective_until": claim.effective_until,
                "modality": claim.modality,
                "confidence": claim.confidence,
                "extraction_model": claim.extraction_model,
                "content_hash": content_hash,
            })

    # 6b. Table claims are already structured — append after prose claims so
    # the claim embedding order stays aligned with persistence (both enumerate
    # all_claims in this order).
    all_claims.extend(table_claims)

    if all_claims:
        claim_texts = [cl["content"] for cl in all_claims]
        claim_embeddings = generate_embeddings(claim_texts)
        claim_ids = [f"{document_id}_claim_{i}" for i in range(len(all_claims))]
        claim_metadatas = [
            {
                "document_id": document_id,
                "document_title": document_title,
                "chunk_index": cl["chunk_index"],
                "is_claim": True,
            }
            for cl in all_claims
        ]
        upsert_embeddings(org_id, claim_ids, claim_embeddings, claim_texts, claim_metadatas)

    # Return chunk data for DB persistence
    return [
        {
            "content": c.content,
            "chunk_index": c.chunk_index,
            "start_page": c.start_page,
            "end_page": c.end_page,
            "token_count": c.token_count,
            "embedding_id": chunk_ids[i],
        }
        for i, c in enumerate(chunks)
    ], all_claims, page_count


def _parse_file(
    file_path: str, file_type: str
) -> tuple[str, int, dict, list[ParsedTable]]:
    """Route to the appropriate parser, returning (text, page_count, page_map, tables)."""
    if file_type == "pdf":
        from app.ingestion.parsers.pdf_parser import parse_pdf
        return parse_pdf(file_path)
    elif file_type == "docx":
        from app.ingestion.parsers.docx_parser import parse_docx
        text, page_count, tables = parse_docx(file_path)
        return text, page_count, {}, tables
    elif file_type in ("txt", "md"):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        return text, 1, {}, []
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


def _build_table_artifacts(
    tables: list[ParsedTable],
    document_id: str,
    start_index: int,
) -> tuple[list[ChunkResult], list[dict]]:
    """Turn parsed tables into synthetic chunks + structured claim dicts.

    Each non-empty table gets its own chunk (so its linearized text is embedded
    for retrieval/semantic drift) and a claim per cell (so claim-level NLI can
    detect contradictions against other documents' tables). Table claims skip
    the prose salience filter — they are already well-formed structured facts.
    """
    from app.ingestion.extractor import compute_content_hash

    if not tables:
        return [], []

    chunk_results: list[ChunkResult] = []
    claims: list[dict] = []
    idx = start_index

    for table_claims in linearize_tables(tables):
        if not table_claims:
            continue
        chunk_content = " ".join(tc.sentence for tc in table_claims)
        chunk_results.append(
            ChunkResult(
                content=chunk_content,
                chunk_index=idx,
                token_count=len(chunk_content.split()),
                is_table=True,
            )
        )
        for tc in table_claims:
            claims.append({
                "content": tc.sentence,
                "original_sentence": tc.sentence,
                "importance_weight": 1.2,  # table facts are high-signal
                "chunk_index": idx,
                # subject/predicate are String(512) columns — guard overflow.
                "subject": tc.subject[:500],
                "predicate": tc.predicate[:500],
                "value": tc.value,
                "condition": "",
                "effective_from": "",
                "effective_until": "",
                "modality": "INFORMATIONAL",
                "confidence": 1.0,
                "extraction_model": "table_rule_based",
                "content_hash": compute_content_hash(tc.sentence),
            })
        idx += 1

    return chunk_results, claims
