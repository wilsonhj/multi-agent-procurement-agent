"""Swap points required by NFR-04.

    "Parsers, OCR, embedders, vector store, reranker, and LLM must be swappable
    behind stable interfaces."

Six interfaces, one per named swap point. They are structural Protocols rather
than base classes so that adapters can wrap third-party clients without
inheriting from anything here, and so no concrete dependency leaks into the core
package. Concrete adapters live under adapters/ and are pulled in by the
optional extras declared in pyproject.toml.

The reference memo's parser-router finding applies directly: no single engine
wins across document types, so ParserPort is expected to have several
implementations selected by content signature (FR-ING-01), not one.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..schema import ComponentCategory, SourceTier

__all__ = [
    "EmbedderPort",
    "LLMPort",
    "OCRPort",
    "ParsedElement",
    "ParserPort",
    "RerankerPort",
    "RetrievedChunk",
    "VectorStorePort",
]


class ParsedElement(Protocol):
    """A layout-aware unit of a parsed document (FR-ING-03/05)."""

    kind: str
    """heading, body, table or figure."""
    text: str
    page: int | None


class RetrievedChunk(Protocol):
    """A chunk returned from retrieval.

    FR-RAG-03 requires that system-of-record chunks stay distinguishable from
    web supplements at all times, so source_tier travels with every chunk rather
    than being looked up later.
    """

    chunk_id: str
    document_id: str
    text: str
    page: int | None
    source_tier: SourceTier
    score: float


@runtime_checkable
class ParserPort(Protocol):
    """Format-native parsing. One implementation per document family."""

    def supports(self, content_signature: str) -> bool:
        """FR-ING-01 routes by content signature, never by file extension."""
        ...

    def parse(self, data: bytes) -> list[ParsedElement]: ...


@runtime_checkable
class OCRPort(Protocol):
    """Fallback for scanned PDFs and images (FR-ING-04)."""

    def needs_ocr(self, elements: list[ParsedElement]) -> bool:
        """Auto-detect absent or low text coverage."""
        ...

    def recognize(self, data: bytes) -> list[ParsedElement]:
        """Handle skew, rotation, multi-column and tables; retain bounding boxes."""
        ...


@runtime_checkable
class EmbedderPort(Protocol):
    """Embedding generation (FR-RAG-02).

    NFR-03 requires a self-hosted or enterprise endpoint for confidential
    documents, with no third-party training on contract data.
    """

    @property
    def dimensions(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class VectorStorePort(Protocol):
    """ANN index over chunks (HNSW/IVF, cosine per FR-RAG-02)."""

    def upsert(
        self, chunk_ids: list[str], vectors: list[list[float]], metadata: list[dict[str, Any]]
    ) -> None:
        """FR-RAG-05: incremental add/update by stable ID, no full re-index."""
        ...

    def delete(self, chunk_ids: list[str]) -> None: ...

    def search(
        self,
        vector: list[float],
        *,
        limit: int,
        category: ComponentCategory | None = None,
        supplier: str | None = None,
        source_tier: SourceTier | None = None,
        allowed_document_ids: set[str] | None = None,
    ) -> list[RetrievedChunk]:
        """Metadata-filtered search.

        allowed_document_ids carries NFR-03 access control. It is a search
        parameter rather than a post-filter because the requirement is that
        access control is enforced at retrieval time.
        """
        ...


@runtime_checkable
class RerankerPort(Protocol):
    """Reranking over hybrid vector + BM25 candidates (FR-RAG-03)."""

    def rerank(
        self, query: str, chunks: list[RetrievedChunk], *, limit: int
    ) -> list[RetrievedChunk]: ...


@runtime_checkable
class LLMPort(Protocol):
    """Schema-constrained generation (FR-ING-07).

    Extraction uses JSON-schema or tool-use output with validation. Prompts use
    retrieved context only and must be able to return an explicit
    "insufficient evidence" result rather than fabricating a value (FR-RAG-04),
    which is why extract returns None rather than raising on a miss.
    """

    def extract(
        self,
        *,
        prompt: str,
        context: list[RetrievedChunk],
        json_schema: dict[str, Any],
    ) -> dict[str, Any] | None: ...
