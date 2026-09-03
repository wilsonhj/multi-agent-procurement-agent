"""`OCRPort` implementations — FR-ING-04.

The fallback for scanned PDFs and images. Note that one clause of FR-ING-04
cannot be met through this port as `ports` currently declares it: see
`adapters.UNEXPRESSIBLE_BOUNDING_BOXES`.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["OCRSamples"]


@dataclass(frozen=True)
class OCRSamples:
    """The fixture an OCR adapter hands the shared contract suite.

    Only the scan: `needs_ocr` takes `ParsedElement`s, which the suite can build
    itself from the Protocol, so the two halves of this port need very different
    amounts of help. A real adapter's `scan` is a committed sanitized image, and
    `docs/development.md` is explicit that it must never be a customer document.
    """

    scan: bytes
