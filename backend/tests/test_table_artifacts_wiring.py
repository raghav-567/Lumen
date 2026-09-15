"""Tests for router wiring of tables → synthetic chunks + claim dicts.

Verifies the contract the persistence layer relies on: each table gets its own
chunk index (continuing after the prose chunks), every table claim points at a
real chunk index, and the claim dicts carry the keys tasks.py reads.
"""

from __future__ import annotations

from app.ingestion.router import _build_table_artifacts
from app.ingestion.table_linearizer import ParsedTable

_CLAIM_KEYS = {
    "content", "original_sentence", "importance_weight", "chunk_index",
    "subject", "predicate", "value", "condition", "modality",
    "confidence", "extraction_model", "content_hash",
}


def test_each_table_gets_its_own_chunk_after_prose():
    tables = [
        ParsedTable(rows=[["Metric", "Target"], ["EV adoption", "50%"]]),
        ParsedTable(rows=[["Item", "Limit"], ["Speed", "60 km/h"]]),
    ]
    # Pretend the document already produced 4 prose chunks (indices 0..3).
    chunks, claims = _build_table_artifacts(tables, "doc-1", start_index=4)

    # One synthetic chunk per non-empty table, indexed 4 and 5.
    assert [c.chunk_index for c in chunks] == [4, 5]
    assert all(c.is_table for c in chunks)

    # Every claim maps to a real table chunk index.
    chunk_indices = {c.chunk_index for c in chunks}
    assert all(cl["chunk_index"] in chunk_indices for cl in claims)
    assert {cl["chunk_index"] for cl in claims} == {4, 5}


def test_claim_dicts_have_persistence_keys_and_structured_fields():
    tables = [ParsedTable(rows=[["Metric", "Target"], ["EV adoption", "50%"]])]
    _chunks, claims = _build_table_artifacts(tables, "doc-1", start_index=0)

    assert len(claims) == 1
    cl = claims[0]
    assert _CLAIM_KEYS.issubset(cl.keys())
    assert cl["content"] == "For EV adoption, the Target is 50%."
    assert cl["subject"] == "EV adoption"
    assert cl["predicate"] == "Target"
    assert cl["value"] == "50%"
    assert cl["modality"] == "INFORMATIONAL"
    assert cl["extraction_model"] == "table_rule_based"
    assert cl["content_hash"]  # non-empty hash


def test_empty_tables_produce_nothing():
    chunks, claims = _build_table_artifacts([], "doc-1", start_index=0)
    assert chunks == [] and claims == []

    # A table that linearizes to no claims must not consume a chunk index.
    chunks, claims = _build_table_artifacts(
        [ParsedTable(rows=[["only-header-row"]])], "doc-1", start_index=2
    )
    assert chunks == [] and claims == []


def test_synthetic_chunk_content_concatenates_sentences():
    tables = [ParsedTable(rows=[
        ["Metric", "Target"], ["EV adoption", "50%"], ["Charging", "10000"],
    ])]
    chunks, _claims = _build_table_artifacts(tables, "doc-1", start_index=0)
    assert len(chunks) == 1
    assert "For EV adoption, the Target is 50%." in chunks[0].content
    assert "For Charging, the Target is 10000." in chunks[0].content
