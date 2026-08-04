"""PDF document parser using PyMuPDF."""

from __future__ import annotations

import logging
from pathlib import Path

import fitz  # PyMuPDF

from app.ingestion.table_linearizer import ParsedTable

logger = logging.getLogger(__name__)


def parse_pdf(
    file_path: str,
) -> tuple[str, int, dict[int, int], list[ParsedTable]]:
    """Parse a PDF file and return (text, page_count, page_map, tables).

    ``page_map`` maps page_number -> character_offset in the combined text.
    ``tables`` holds structured tables detected via PyMuPDF's table finder; the
    raw cell text also remains inline in ``text`` (PyMuPDF's ``get_text`` can't
    cleanly exclude table regions), but that jumbled copy is low-salience and is
    filtered out downstream, while the structured copy drives table-drift
    detection.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {file_path}")

    doc = fitz.open(str(path))
    text_parts: list[str] = []
    page_map: dict[int, int] = {}
    tables: list[ParsedTable] = []
    offset = 0

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_text = page.get_text()

        page_map[page_num + 1] = offset
        text_parts.append(page_text)
        offset += len(page_text) + 1  # +1 for newline

        # Table detection is best-effort: a malformed page must not abort parsing.
        try:
            found = page.find_tables()
            for tab in found.tables:
                rows = tab.extract()
                if rows and any(any(c for c in r) for r in rows):
                    tables.append(ParsedTable(rows=rows, page=page_num + 1))
        except Exception as e:  # noqa: BLE001 — find_tables can throw on odd pages
            logger.warning(f"Table detection failed on page {page_num + 1}: {e}")

    page_count = len(doc)
    doc.close()
    full_text = "\n".join(text_parts)

    logger.info(
        f"Parsed PDF {path.name}: {page_count} pages, {len(full_text)} chars, "
        f"{len(tables)} tables"
    )
    return full_text, page_count, page_map, tables
