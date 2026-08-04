"""Indexing (FR-RAG-01, FR-RAG-02, FR-RAG-05).

Chunking, embeddings, vector index, lexical index, metadata store.

Both index kinds named in the TRS are reversed by the plan, and this docstring
asserted the TRS side of each:

- FR-RAG-02 mandates an **ANN index (HNSW/IVF)**; plan Decision 3a chooses exact
  pgvector search with no ANN index, because filtered ANN search was measured
  silently under-returning on a filtered top-k. Registered as A-23.
- FR-RAG-03 mandates **BM25**; plan Decision 3b chooses Postgres `tsvector`/GIN
  plus `pg_trgm`, because no permissively licensed true-BM25 exists for
  PostgreSQL. Registered as A-24.
"""

from __future__ import annotations

from ...ports import EmbedderPort, ParsedElement, VectorStorePort
from ...schema import SourceDocument


def chunk(elements: list[ParsedElement], *, size_tokens: int, overlap_ratio: float) -> list[str]:
    """Structure-aware chunking (FR-RAG-01), as revised by plan Decision 6.

    512-token prose chunks split on structure first, with **0-10% overlap** -
    not the TRS's 10-20%, which analysis A-7 found gave no measurable benefit
    once Docling supplies real section boundaries. `config.chunk_overlap_ratio`
    enforces the revised band (`le=0.10`), so the older figure this docstring
    used to quote was not even settable.

    Tables are **never** token-chunked - not "where feasible", never; A-8 flags
    the TRS's softer wording precisely so it is not read as permission. That is
    why this takes parsed elements rather than a flat string.
    """
    raise NotImplementedError


def index_document(
    document: SourceDocument,
    elements: list[ParsedElement],
    *,
    embedder: EmbedderPort,
    store: VectorStorePort,
) -> None:
    """Embed and index one document.

    Metadata written per FR-RAG-02: doc ID, chunk ID, component category,
    supplier, doc type, page, source URI, timestamps, source-tier flag.

    Idempotent by content hash (NFR-05, AC-5): re-indexing an unchanged document
    must not create duplicates.
    """
    raise NotImplementedError
