"""Round-trip test: a real .docx with a table → structured table claims.

Regression guard for the historical bug where DOCX tables were silently dropped
(``parse_docx`` only read ``doc.paragraphs``, which excludes table cell text).
Builds a genuine .docx with python-docx, parses it, and asserts the table facts
survive into linearized claims.
"""

from __future__ import annotations

import pytest

docx = pytest.importorskip("docx")

from app.ingestion.parsers.docx_parser import parse_docx
from app.ingestion.table_linearizer import linearize_tables


def _build_docx(path: str) -> None:
    doc = docx.Document()
    doc.add_paragraph("Electrification Policy — Targets")
    table = doc.add_table(rows=3, cols=2)
    cells = [
        ("Metric", "Target"),
        ("EV adoption by 2030", "50%"),
        ("Charging stations", "10000"),
    ]
    for r, (a, b) in enumerate(cells):
        table.rows[r].cells[0].text = a
        table.rows[r].cells[1].text = b
    doc.save(path)


def test_docx_table_cells_become_claims(tmp_path):
    path = str(tmp_path / "policy.docx")
    _build_docx(path)

    text, page_count, tables = parse_docx(path)

    # Prose paragraph is captured...
    assert "Electrification Policy" in text
    # ...and crucially the table is no longer dropped.
    assert len(tables) == 1

    claims = [c for group in linearize_tables(tables) for c in group]
    sentences = [c.sentence for c in claims]

    assert "For EV adoption by 2030, the Target is 50%." in sentences
    assert "For Charging stations, the Target is 10000." in sentences

    ev = next(c for c in claims if c.subject == "EV adoption by 2030")
    assert ev.predicate == "Target"
    assert ev.value == "50%"


def test_docx_without_tables_yields_no_tables(tmp_path):
    path = str(tmp_path / "prose.docx")
    doc = docx.Document()
    doc.add_paragraph("This document has no tables, only a sentence of prose.")
    doc.save(path)

    text, _, tables = parse_docx(path)
    assert "no tables" in text
    assert tables == []
