"""`ParserPort` implementations — FR-ING-01/02/03/05.

The port whose siblings matter most: `ports/__init__.py` records the reference
memo's parser-router finding, that no single engine wins across document types,
so this package is expected to hold several modules selected by content
signature rather than one winner. `memory.py` is the in-memory reference; a real
one is `docling.py`, `openpyxl.py`, and so on, each importing its vendor at
module scope and guarded by an optional extra.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ParserSamples"]


@dataclass(frozen=True)
class ParserSamples:
    """The fixtures a parser hands the shared contract suite.

    The suite cannot invent a document that only one backend can read - a
    Docling test needs a PDF and an openpyxl test needs a workbook - so the
    adapter supplies them. This is the machine-readable half of
    `docs/development.md`'s step 6: "add sanitized success, empty, malformed, and
    timeout fixtures". Empty needs no field (`b""` is universal) and timeout has
    no home until ADR-001 decision 3 puts one on adapter configuration.

    `malformed` is the field most likely to be filled in carelessly, and it is
    the one that carries a real contract: bytes this parser cannot read, which it
    must *refuse* rather than return an empty element list for. Passing it
    something the parser happens to parse successfully turns
    `test_input_it_cannot_read_raises_rather_than_yielding_nothing` green while
    testing nothing.
    """

    signature: str
    """A content signature this parser routes on. FR-ING-01, never an extension."""

    foreign_signature: str
    """One it must refuse, so that `supports()` is shown to be able to say no."""

    document: bytes
    """A document it parses successfully, sanitized and committed to the repo."""

    malformed: bytes
    """Bytes it cannot read and must raise on."""
