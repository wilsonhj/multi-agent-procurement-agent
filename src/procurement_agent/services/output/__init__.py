"""Comparison / Output (FR-OUT-01 .. FR-OUT-06).

Canonical schema -> multi-tab Excel writer with provenance and conditional
formatting.
"""

from __future__ import annotations

from pathlib import Path

from ...schema import CanonicalField, CellFlag, ComponentInstance, WorkbookTab


def flags_for(field: CanonicalField, *, confidence_threshold: float) -> set[CellFlag]:
    """Which of the four conditional-formatting states apply to a cell (FR-OUT-04).

    A cell can carry more than one: a web-supplemented value can also be
    low-confidence.
    """
    from ...schema import ConflictStatus

    flags: set[CellFlag] = set()
    if field.is_missing():
        flags.add(CellFlag.MISSING_DATA)
    if field.is_web_supplemented():
        flags.add(CellFlag.WEB_SUPPLEMENTED)
    if field.confidence < confidence_threshold:
        flags.add(CellFlag.LOW_CONFIDENCE)
    if field.conflict_status in {ConflictStatus.OPEN, ConflictStatus.INSUFFICIENT_EVIDENCE}:
        flags.add(CellFlag.UNRESOLVED_CONFLICT)
    return flags


def write_workbook(
    components: list[ComponentInstance],
    destination: Path,
    *,
    suppliers_as_rows: bool = True,
    confidence_threshold: float = 0.80,
) -> Path:
    """Emit the workbook. All thirteen tabs, always (FR-OUT-02, AC-3).

    Must be deterministically regenerable from the canonical store (FR-OUT-06),
    which means no timestamps or ordering derived from anything but the store
    itself, plus an explicit generated-on stamp and per-source data vintage.

    Every comparison cell carries provenance via cell comment, a link into the
    Sources tab, or an adjacent column (FR-OUT-03). No unsourced values
    (NFR-01, AC-4).
    """
    raise NotImplementedError


def expected_tabs() -> list[WorkbookTab]:
    """The thirteen tabs in order. AC-3 asserts against this."""
    return list(WorkbookTab)
