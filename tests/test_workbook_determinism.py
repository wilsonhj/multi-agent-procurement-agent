"""Byte-identical regeneration, and a test that cannot pass by coincidence.

Issue #13. Freezing `workbook.properties.modified` is not sufficient: openpyxl
re-stamps it on save regardless, and each ZIP local header carries a wall-clock
mtime. Measured: every member decompresses identically while the files hash
differently.

The naive check - save twice, compare hashes - passes whenever both saves land
in the same wall-clock second, which is most of the time. It would green-light a
broken fix. So the load-bearing assertions here are on the archive metadata
itself, not on a hash comparison that luck can satisfy.
"""

import hashlib
import zipfile
from pathlib import Path

from openpyxl import Workbook

from procurement_agent.services.output import (
    DETERMINISTIC_APPLICATION,
    DETERMINISTIC_TIMESTAMP,
    normalize_archive,
)


def _write(path: Path) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet["A1"] = "PV Modules"
    sheet["B2"] = 650
    workbook.save(path)
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_every_archive_member_carries_the_fixed_timestamp(tmp_path: Path) -> None:
    """The assertion luck cannot satisfy: no member may keep a clock-derived mtime."""
    book = normalize_archive(_write(tmp_path / "book.xlsx"))
    with zipfile.ZipFile(book) as archive:
        stamps = {info.date_time for info in archive.infolist()}
    assert stamps == {DETERMINISTIC_TIMESTAMP}


def test_unnormalized_saves_are_not_byte_identical_in_general(tmp_path: Path) -> None:
    """Why normalisation is needed at all: the raw archive carries the clock.

    Asserted on the metadata rather than on hashes, because two raw saves inside
    one wall-clock second *do* hash the same - exactly the coincidence that makes
    the naive test unsound.
    """
    raw = _write(tmp_path / "raw.xlsx")
    with zipfile.ZipFile(raw) as archive:
        stamps = {info.date_time for info in archive.infolist()}
    assert stamps != {DETERMINISTIC_TIMESTAMP}


def test_normalized_saves_are_byte_identical(tmp_path: Path) -> None:
    first = normalize_archive(_write(tmp_path / "first.xlsx"))
    second = normalize_archive(_write(tmp_path / "second.xlsx"))
    assert _digest(first) == _digest(second)


def test_library_version_is_not_embedded_in_the_output(tmp_path: Path) -> None:
    """`docProps/app.xml` otherwise carries `Openpyxl <version>` verbatim, so a
    patch bump changes the bytes with zero data change and invalidates AC-7."""
    book = normalize_archive(_write(tmp_path / "book.xlsx"))
    with zipfile.ZipFile(book) as archive:
        app = archive.read("docProps/app.xml").decode()
    assert "Openpyxl" not in app
    assert DETERMINISTIC_APPLICATION in app


def test_normalized_workbook_still_opens_and_keeps_its_data(tmp_path: Path) -> None:
    """Determinism is worthless if it corrupts the file."""
    from openpyxl import load_workbook

    book = normalize_archive(_write(tmp_path / "book.xlsx"))
    sheet = load_workbook(book).active
    assert sheet is not None
    assert sheet["A1"].value == "PV Modules"
    assert sheet["B2"].value == 650
