"""Unit tests for table linearization → structured claims.

Pure-Python; no embeddings/DB. Verifies that tabular facts become well-formed,
NLI-comparable claims with subject/predicate/value populated, and that two
tables disagreeing on a cell produce sentences that differ only in the value.
"""

from __future__ import annotations

from app.ingestion.table_linearizer import (
    ParsedTable,
    TableClaim,
    linearize_table,
    linearize_tables,
)


def _sentences(claims: list[TableClaim]) -> list[str]:
    return [c.sentence for c in claims]


def test_matrix_table_with_header_and_row_labels():
    rows = [
        ["Vehicle class", "2030 Target", "Subsidy"],
        ["Passenger vehicles", "50%", "$5000"],
        ["Trucks", "20%", "$8000"],
    ]
    claims = linearize_table(rows)

    # 2 data rows × 2 value columns = 4 claims
    assert len(claims) == 4

    by_sentence = {c.sentence: c for c in claims}
    assert "For Passenger vehicles, the 2030 Target is 50%." in by_sentence
    assert "For Trucks, the Subsidy is $8000." in by_sentence

    c = by_sentence["For Passenger vehicles, the 2030 Target is 50%."]
    assert c.subject == "Passenger vehicles"
    assert c.predicate == "2030 Target"
    assert c.value == "50%"


def test_contradicting_tables_differ_only_in_value():
    """The contradiction-detection guarantee: parallel sentences, value differs."""
    doc_a = [["Metric", "Target"], ["EV adoption", "50%"]]
    doc_b = [["Metric", "Target"], ["EV adoption", "20%"]]

    a = _sentences(linearize_table(doc_a))
    b = _sentences(linearize_table(doc_b))

    assert a == ["For EV adoption, the Target is 50%."]
    assert b == ["For EV adoption, the Target is 20%."]
    # Differ only in the value token — keeps them above the similarity gate.
    assert a[0].replace("50%", "X") == b[0].replace("20%", "X")


def test_caption_is_woven_into_sentence():
    rows = [["Item", "Limit"], ["Speed", "60 km/h"]]
    claims = linearize_table(rows, caption="Road Rules")
    assert claims[0].sentence == "In Road Rules, for Speed, the Limit is 60 km/h."


def test_empty_and_missing_cells_are_skipped():
    rows = [
        ["Region", "Quota", "Notes"],
        ["North", "", "n/a"],          # empty quota cell skipped
        ["South", "100", ""],          # empty notes cell skipped
    ]
    claims = linearize_table(rows)
    sentences = _sentences(claims)
    assert "For North, the Quota is" not in " ".join(sentences)
    assert "For North, the Notes is n/a." in sentences
    assert "For South, the Quota is 100." in sentences
    assert all("the Notes is ." not in s for s in sentences)


def test_two_column_key_value_table_without_header():
    # First row's value is numericish → treated as key/value, not a header row.
    rows = [
        ["Maximum speed", "50 km/h"],
        ["Minimum age", "18 years"],
    ]
    claims = linearize_table(rows)
    sentences = _sentences(claims)
    assert "The Maximum speed is 50 km/h." in sentences
    assert "The Minimum age is 18 years." in sentences
    assert claims[0].predicate == "is"


def test_merged_cells_duplicate_rows_are_deduped():
    rows = [
        ["Phase", "Year"],
        ["Phase 1", "2025"],
        ["Phase 1", "2025"],  # duplicate (e.g. merged cell repeat)
    ]
    claims = linearize_table(rows)
    assert _sentences(claims) == ["For Phase 1, the Year is 2025."]


def test_degenerate_tables_return_nothing():
    assert linearize_table([]) == []
    assert linearize_table([[""]]) == []
    assert linearize_table([["", ""], ["", ""]]) == []
    # Single header-only row → no data rows → no claims.
    assert linearize_table([["A", "B", "C"]]) == []


def test_whitespace_in_cells_is_normalized():
    rows = [["Field", "Value"], ["  Annual   budget ", "  1.2  billion "]]
    claims = linearize_table(rows)
    assert claims[0].sentence == "For Annual budget, the Value is 1.2 billion."


def test_linearize_tables_preserves_grouping():
    tables = [
        ParsedTable(rows=[["K", "V"], ["a", "1"]]),
        ParsedTable(rows=[]),  # empty → empty group
        ParsedTable(rows=[["Metric", "Target"], ["x", "9"]]),
    ]
    grouped = linearize_tables(tables)
    assert len(grouped) == 3
    assert len(grouped[0]) == 1
    assert grouped[1] == []
    assert len(grouped[2]) == 1
