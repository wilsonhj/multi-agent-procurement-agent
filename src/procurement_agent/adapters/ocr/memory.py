"""An in-memory `OCRPort` standing in for a recognition engine.

The bytes it is handed are UTF-8 text with form feeds for page breaks rather than
pixels; recognition is not what this reference is proving. What it does prove is
that the port's two halves can be satisfied together - a coverage detector that
answers both ways, and a recogniser that returns page-attributed elements - and
that is the part a real engine has to fit.

`TABLE_STRUCTURE` is declared `UNIMPLEMENTED` rather than `NOT_APPLICABLE`: a
scanned datasheet has tables, this reference simply does not recover them. The
distinction is the whole point of the two kinds, and the suite treats them
differently for it.
"""

from __future__ import annotations

from ...ports import OCRPort, ParsedElement
from ..parsed_element import TextElement

__all__ = ["InMemoryOCR"]


class InMemoryOCR:
    """Splits on form feeds, one element per page."""

    MIN_CHARS_PER_PAGE = 40
    """Below this density, a page is treated as having no usable text layer.

    Per page rather than per document, because the failure FR-ING-04 names is a
    *scanned* page inside an otherwise text-bearing PDF - a document-wide total
    hides exactly that, since twenty good pages carry one image-only page over
    any absolute floor. The number is a placeholder for a measured one; the gold
    set (B.9 / D-11) is what would calibrate it, and it does not exist yet.
    """

    def needs_ocr(self, elements: list[ParsedElement]) -> bool:
        """FR-ING-04's auto-detection: absent or low text coverage."""
        if not elements:
            return True
        pages = {element.page for element in elements}
        characters = sum(len(element.text.strip()) for element in elements)
        return characters / max(len(pages), 1) < self.MIN_CHARS_PER_PAGE

    def recognize(self, data: bytes) -> list[ParsedElement]:
        """One body element per page, numbered from 1.

        Pages are numbered rather than carried through from the input because
        that is what a recogniser does: the page index is the only provenance an
        image-only document has, and NFR-01 needs it to survive to `SourceRef`.
        """
        return [
            TextElement(kind="body", text=page.strip(), page=number)
            for number, page in enumerate(data.decode("utf-8").split("\f"), start=1)
            if page.strip()
        ]


def _conforms(adapter: InMemoryOCR) -> OCRPort:
    """Static structural check, run by `mypy --strict`."""
    return adapter
