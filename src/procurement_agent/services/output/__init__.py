"""Comparison / Output (FR-OUT-01 .. FR-OUT-06).

Canonical schema -> multi-tab Excel writer with provenance and conditional
formatting.
"""

from __future__ import annotations

import os
import re
import tempfile
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

#: plan.md Decision 8c: sorted entries with `[Content_Types].xml` forced first.
#: openpyxl 3.1.5 writes it *last*, so preserving `infolist()` order preserves a
#: non-conformant archive.
CONTENT_TYPES = "[Content_Types].xml"

#: Decision 8c. Pinned so output bytes do not depend on the host's zlib default,
#: which varies across Python builds.
DETERMINISTIC_COMPRESSLEVEL = 6

#: Decision 8c: always "Unix", else `ZipInfo.__init__` picks 0 on Windows and 3
#: elsewhere, so the same store would produce different bytes per platform.
_CREATE_SYSTEM_UNIX = 3
_EXTERNAL_ATTR = 0o644 << 16

_APPLICATION_RE = re.compile(rb"<Application>[^<]*</Application>")
_APP_VERSION_RE = re.compile(rb"<AppVersion>[^<]*</AppVersion>")
_DCTERMS_RE = re.compile(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:)")

#: The epoch as it appears inside `docProps/core.xml`, matching the ZIP stamp.
#: Substituted with \g<N> back-references, not \N - the replacement starts with
#: "1980", so "\1" + "1980..." would parse as group 11.
_CORE_XML_EPOCH = b"1980-01-01T12:00:00Z"


def normalize_archive(path: Path) -> Path:
    """Strip every wall-clock, library-version and platform trace from an `.xlsx`.

    Required by FR-OUT-06 and AC-7. Freezing `workbook.properties.modified` is
    **not sufficient**: openpyxl re-stamps it unconditionally on save
    (`openpyxl/writer/excel.py:292`, no opt-out), and each ZIP local header
    carries an mtime derived from the clock. See issue #13.

    Five sources of run-to-run variance, all of which have to go - missing any
    one leaves the archive non-deterministic while looking fixed:

    1. ZIP local-header mtimes, from the clock via `writestr`.
    2. `docProps/core.xml` `dcterms:created` / `dcterms:modified`. This is the one
       an earlier version of this function missed, so two saves seconds apart
       still differed while every other member was byte-identical.
    3. `docProps/app.xml`, which embeds the openpyxl version verbatim.
    4. Compression level. Decision 8c warns by name that `ZipFile(compresslevel=)`
       is **silently ignored** for a hand-built `ZipInfo` - it must be set as
       `_compresslevel` on the info object itself.
    5. `create_system` and `external_attr`, which otherwise vary by platform.

    Member order is normalised too: sorted, with `[Content_Types].xml` first per
    Decision 8c. openpyxl writes it last.
    """
    with zipfile.ZipFile(path) as source:
        members = {info.filename: source.read(info.filename) for info in source.infolist()}

    ordered = sorted(members, key=lambda name: (name != CONTENT_TYPES, name))

    # `mkstemp`, not pid: two callers in one process share a pid, and the loser
    # of the race raised FileNotFoundError out of a call that had succeeded.
    handle, staging_name = tempfile.mkstemp(
        dir=path.parent, prefix=f"{path.name}.", suffix=".normalizing"
    )
    os.close(handle)
    staging = Path(staging_name)
    try:
        with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED) as target:
            for name in ordered:
                payload = members[name]
                # OPC part names are case-insensitive; openpyxl always writes
                # this casing, but a foreign workbook need not.
                lowered = name.casefold()
                if lowered == "docprops/app.xml":
                    payload = _APPLICATION_RE.sub(
                        f"<Application>{DETERMINISTIC_APPLICATION}</Application>".encode(), payload
                    )
                    payload = _APP_VERSION_RE.sub(b"<AppVersion>1.0</AppVersion>", payload)
                elif lowered == "docprops/core.xml":
                    payload = _DCTERMS_RE.sub(rb"\g<1>" + _CORE_XML_EPOCH + rb"\g<2>", payload)

                info = zipfile.ZipInfo(name, date_time=DETERMINISTIC_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                # Private on purpose: Decision 8c records that
                # `ZipFile(compresslevel=)` is silently ignored for a hand-built
                # ZipInfo, and stdlib exposes no public setter. Untyped, hence
                # the ignore.
                info._compresslevel = DETERMINISTIC_COMPRESSLEVEL  # type: ignore[attr-defined]
                info.create_system = _CREATE_SYSTEM_UNIX
                info.external_attr = _EXTERNAL_ATTR
                target.writestr(info, payload)
        # os.replace, not shutil.move: same directory, so this is an atomic
        # rename. shutil.move falls back to copy-then-unlink across filesystems,
        # and a copy that dies partway leaves the destination truncated - at
        # which point unlinking the staging file destroys the only intact copy.
        os.replace(staging, path)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise
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
    confidence_threshold: float,
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
    """The thirteen tabs in order, for a writer to iterate (FR-OUT-02).

    Pinned by `test_expected_tabs_returns_all_thirteen_in_order`. AC-3 itself is
    *not* asserted here and cannot be until `write_workbook` exists - AC-3 wants
    thirteen tabs in a generated workbook with conditional formatting, and this
    is only the order they go in.
    """
    return list(WorkbookTab)
