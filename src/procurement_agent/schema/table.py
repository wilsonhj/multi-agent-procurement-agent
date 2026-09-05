"""Structured table payload carried on `ParsedElement.table` (P2-C1 / D-23)."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CellSpan", "TableData"]


@dataclass(frozen=True)
class CellSpan:
    """A merged region inside `TableData.rows`.

    Origin is the top-left cell of the span, 0-based, matching the envelope
    convention on `ParsedElement.bbox`. `rowspan`/`colspan` are the occupied
    extents; a 1×1 span is a cell that is not merged.
    """

    row: int
    column: int
    rowspan: int
    colspan: int


@dataclass(frozen=True)
class TableData:
    """A table that survived as a table rather than being flattened to prose.

    Present on a `ParsedElement` iff `kind == "table"`. Cells live here, not as
    a fifth element kind. Numbers in `rows` are already text; the parser that
    produced them is responsible for `repr()` (D-14).
    """

    rows: tuple[tuple[str, ...], ...]
    header_rows: int
    caption: str | None
    merged: tuple[CellSpan, ...]
