"""Comparison / Output (FR-OUT-01 .. FR-OUT-06).

Canonical schema -> multi-tab Excel writer with provenance and conditional
formatting.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

from ...schema import CanonicalField, CellFlag, ComponentInstance, WorkbookTab

#: plan.md Decision 8c. 1980-01-01 is the ZIP format's epoch floor; noon keeps
#: every member clear of it under any timezone interpretation.
DETERMINISTIC_TIMESTAMP = (1980, 1, 1, 12, 0, 0)

#: Replaces openpyxl's `Microsoft Excel Compatible / Openpyxl <version>`, which
#: embeds the library version in `docProps/app.xml` and so changes the output
#: bytes on a patch bump with zero data change.
DETERMINISTIC_APPLICATION = "Procurement Agent"

_APPLICATION_RE = re.compile(rb"<Application>[^<]*</Application>")
_APP_VERSION_RE = re.compile(rb"<AppVersion>[^<]*</AppVersion>")


def normalize_archive(path: Path) -> Path:
    """Strip every wall-clock and library-version trace from a saved `.xlsx`.

    Required by FR-OUT-06 and AC-7. Freezing `workbook.properties.modified` is
    **not sufficient**: openpyxl re-stamps it unconditionally on save
    (`openpyxl/writer/excel.py:292`, no opt-out), and even with it pinned the
    archive still differs run to run because each ZIP local header carries an
    mtime derived from the clock via `writestr`. Measured: all members
    decompress byte-identically while the files hash differently. See issue #13.

    Rewriting the archive is the only fix openpyxl leaves available, and it also
    lets `openpyxl` float on a version range instead of being pinned exactly.
    """
    with zipfile.ZipFile(path) as source:
        members = [(info, source.read(info.filename)) for info in source.infolist()]

    staging = path.with_suffix(path.suffix + ".normalizing")
    with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED) as target:
        for info, payload in members:
            if info.filename == "docProps/app.xml":
                payload = _APPLICATION_RE.sub(
                    f"<Application>{DETERMINISTIC_APPLICATION}</Application>".encode(), payload
                )
                payload = _APP_VERSION_RE.sub(b"<AppVersion>1.0</AppVersion>", payload)
            rewritten = zipfile.ZipInfo(info.filename, date_time=DETERMINISTIC_TIMESTAMP)
            rewritten.compress_type = info.compress_type
            rewritten.external_attr = info.external_attr
            target.writestr(rewritten, payload)

    shutil.move(staging, path)
    return path


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
