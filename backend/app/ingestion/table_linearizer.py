"""Linearize tabular data into structured, NLI-comparable claims.

Tables carry some of the most contradiction-prone facts in policy documents
(targets, limits, dates, budgets) but are invisible to a prose pipeline: the
salience filter is tuned for sentences and would reject a bare row, and the
DOCX parser historically dropped tables entirely.

This module converts a parsed table into a list of ``TableClaim`` objects, each
a self-contained declarative sentence with structured ``subject``/``predicate``/
``value`` fields populated from the cell's position:

    row label   → subject
    column head → predicate
    cell value  → value

The sentence templates are deliberately *parallel* ("For {row}, the {col} is
{value}.") so two documents that disagree on the same cell produce sentences
that differ only in the value — which keeps them above the embedding similarity
gate and lets the cross-encoder NLI flag them as a contradiction.

Pure Python, no heavy dependencies, so it is cheaply unit-testable.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Guard against pathological tables blowing up the claim count.
_MAX_CELLS_PER_TABLE = 400


@dataclass
class ParsedTable:
    """A raw table extracted by a parser, before linearization."""

    rows: list[list[str]]
    caption: str = ""
    page: int | None = None


@dataclass
class TableClaim:
    """A single linearized table fact, ready to become a Claim."""

    sentence: str
    subject: str = ""
    predicate: str = ""
    value: str = ""


def _norm(cell: object) -> str:
    """Normalize a cell into a clean single-line string."""
    if cell is None:
        return ""
    return re.sub(r"\s+", " ", str(cell)).strip()


def _is_numericish(s: str) -> bool:
    """True when a cell reads like a value (number/percent/money/unit) not a label.

    e.g. "50%", "$8000", "50 km/h", "1.2 billion" → value; "2030 Target",
    "Vehicle class" → label.
    """
    if not s or not re.search(r"\d", s):
        return False
    alpha = sum(c.isalpha() for c in s)
    return alpha / max(len(s), 1) < 0.5


def _has_alnum(s: str) -> bool:
    return any(c.isalnum() for c in s)


def linearize_table(
    rows: list[list[str]], caption: str = ""
) -> list[TableClaim]:
    """Convert one table's rows into structured claims.

    Supports two layouts that cover the vast majority of policy tables:

    * **Matrix** — a header row plus a row-label column. Each data cell becomes
      "For {row label}, the {column header} is {value}."
    * **Key/value** — a two-column table with no header row. Each row becomes
      "The {key} is {value}."

    Tables that fit neither shape (e.g. a header-less wide grid) are skipped
    rather than emitting low-precision noise.
    """
    grid = [[_norm(c) for c in row] for row in (rows or [])]
    grid = [row for row in grid if any(row)]  # drop fully-empty rows
    if not grid:
        return []

    n_cols = max(len(r) for r in grid)
    cap = _norm(caption)

    claims: list[TableClaim] = []
    seen: set[str] = set()

    def _emit(subject: str, predicate: str, value: str, sentence: str) -> None:
        if sentence in seen:
            return
        seen.add(sentence)
        claims.append(
            TableClaim(
                sentence=sentence,
                subject=subject,
                predicate=predicate,
                value=value,
            )
        )

    header = grid[0]
    header_nonempty = [c for c in header if c]

    # Decide layout. The hard case is a 2-column table: a header row ("Metric",
    # "Target") vs a key/value first data row ("Max speed", "50 km/h"). The tell
    # is the second cell — a header's is another label, a data row's is a value.
    if n_cols == 2:
        second = header[1] if len(header) > 1 else ""
        is_matrix = (
            len(grid) >= 2
            and len(header_nonempty) == 2
            and not _is_numericish(header[0])
            and not _is_numericish(second)
        )
    else:
        is_matrix = (
            len(grid) >= 2
            and n_cols >= 2
            and len(header_nonempty) >= 2
            and sum(_is_numericish(c) for c in header if c) <= len(header_nonempty) // 2
        )

    if is_matrix:
        # ── Matrix mode: header row + row-label column ──
        for row in grid[1:]:
            if not row:
                continue
            row_label = row[0]
            if not row_label or not _has_alnum(row_label):
                continue
            for j in range(1, n_cols):
                col_head = header[j] if j < len(header) else ""
                value = row[j] if j < len(row) else ""
                if not col_head or not value or not _has_alnum(value):
                    continue
                if value == row_label:
                    continue
                if cap:
                    sentence = f"In {cap}, for {row_label}, the {col_head} is {value}."
                else:
                    sentence = f"For {row_label}, the {col_head} is {value}."
                _emit(row_label, col_head, value, sentence)
                if len(claims) >= _MAX_CELLS_PER_TABLE:
                    return claims

    elif n_cols == 2:
        # ── Key/value mode: "<key> is <value>" per row ──
        for row in grid:
            key = row[0] if len(row) > 0 else ""
            value = row[1] if len(row) > 1 else ""
            if not key or not value or not _has_alnum(value):
                continue
            if _is_numericish(key) or key == value:
                continue
            if cap:
                sentence = f"In {cap}, the {key} is {value}."
            else:
                sentence = f"The {key} is {value}."
            _emit(key, "is", value, sentence)
            if len(claims) >= _MAX_CELLS_PER_TABLE:
                return claims
    else:
        logger.debug(
            "Skipping table (no header, %d cols) — unsupported layout", n_cols
        )

    return claims


def linearize_tables(tables: list[ParsedTable]) -> list[list[TableClaim]]:
    """Linearize many tables, preserving per-table grouping.

    Returned outer list is aligned with ``tables``; empty tables yield an empty
    inner list (callers can skip those). Grouping is kept so the ingestion
    pipeline can give each source table its own synthetic chunk.
    """
    out: list[list[TableClaim]] = []
    for t in tables or []:
        rows = t.rows if isinstance(t, ParsedTable) else t
        caption = t.caption if isinstance(t, ParsedTable) else ""
        out.append(linearize_table(rows, caption=caption))
    return out
