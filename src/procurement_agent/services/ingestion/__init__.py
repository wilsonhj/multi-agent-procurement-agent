"""Ingestion & Extraction (FR-ING-01 .. FR-ING-10).

File-type detection -> format parsers -> OCR fallback -> text/table/layout ->
schema-constrained field extraction -> canonical records + chunks.
"""

from __future__ import annotations

from ...ports import LLMPort, OCRPort, ParsedElement, ParserPort
from ...schema import ComponentInstance, DocumentType, SourceDocument


def detect_content_signature(data: bytes) -> str:
    """Identify a file by content, never by extension (FR-ING-01).

    Accepted: .xlsx .csv .pdf .docx and images .jpg/.jpeg .png .tif/.tiff .bmp
    .webp .heic
    """
    raise NotImplementedError


def classify_document(elements: list[ParsedElement]) -> DocumentType:
    """Assign one of the eight document types, stored as metadata (FR-ING-06)."""
    raise NotImplementedError


def normalize_unit(raw: str) -> tuple[float | None, str | None]:
    """Convert to canonical units while retaining the verbatim original (FR-ING-08).

    Canonical forms named in the TRS: W/Wp, %/degC vs %/K, kVA/MVA, $/W, kWh/MWh.
    """
    raise NotImplementedError


def ingest(
    data: bytes,
    source_uri: str,
    *,
    parsers: list[ParserPort],
    ocr: OCRPort,
    llm: LLMPort,
) -> tuple[SourceDocument, list[ComponentInstance]]:
    """Run one file through the full ingestion path.

    Parsers are a list, not one instance: the reference memo's parser-router
    finding is that no single engine wins across document types, so the caller
    supplies the candidates and `supports()` selects.

    Fields extracted below the configured confidence threshold are flagged for
    HITL rather than committed silently (FR-ING-10).
    """
    raise NotImplementedError
