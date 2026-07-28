"""Indexing (FR-RAG-01, FR-RAG-02, FR-RAG-05).

Chunking, embeddings, vector index (HNSW/IVF) + keyword index (BM25),
metadata store.
"""

from __future__ import annotations

from ...ports import EmbedderPort, ParsedElement, VectorStorePort
from ...schema import SourceDocument


def chunk(elements: list[ParsedElement], *, size_tokens: int, overlap_ratio: float) -> list[str]:
    """Structure-aware chunking (FR-RAG-01).

    ~400-512 tokens with 10-20% overlap, preserving section boundaries. Tables
    are chunked as whole units where feasible, which is why this takes parsed
    elements rather than a flat string.
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
