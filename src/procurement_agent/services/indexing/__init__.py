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

**One LLM call survives in this path, and it is per table, not per chunk**
(A-44). Decision 6 originally asked for an LLM-generated context prefix on every
chunk; `context_prefix` below builds it from the chunk's own validated metadata
instead. `table_summary` stays generated - one call per *table*, for vocabulary
("temperature coefficient", "derating") that genuinely appears nowhere in the
cells - and is now the only generated text this module writes.
"""

from __future__ import annotations

from ...ports import EmbedderPort, ParsedElement, VectorStorePort
from ...schema import DocumentType, SourceDocument


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


def context_prefix(
    *,
    supplier: str | None,
    model: str | None,
    document_type: DocumentType | None,
    section: str | None,
    page: int | None,
) -> str | None:
    """Build a chunk's `context_prefix` from metadata, deterministically (A-44).

    Decision 6's contextual retrieval: document/section context prepended to the
    text that gets **embedded** only, kept in its own column so a citation still
    shows a reviewer the verbatim `chunk_text` (`sql/03_chunk.sql`). That split
    is unchanged. What changed is where the sentence comes from - Decision 6 and
    task C.3 asked for 1-2 **LLM-generated** sentences per chunk; this builds it
    from columns the chunk row already carries.

    Format, components joined in this order and each omitted when absent::

        "<supplier> <model> <document type> - <section> (p. <page>): "
        "Jinko Solar JKM610N-66HL4M-V spec sheet - Electrical Characteristics (p. 4): "

    `document_type` renders as its value with underscores replaced by spaces
    (`spec_sheet` -> "spec sheet"). Returns None - not "" - when no component is
    present, matching the column's "NULL where the row carries no usable
    metadata". Separators are ASCII, so the same metadata produces the same bytes
    from any writer.

    **Why this signature has no `LLMPort`, and why that is the lock.** One call
    per chunk was the smaller objection. The real one is that the prefix is
    baked into every embedding, so changing strategy later means a full
    re-embed - precisely the operation FR-RAG-05's incremental philosophy exists
    to avoid - and a generated prefix that misstates a model number poisons dense
    retrieval for the row-lookup queries this product cares most about
    ("what is the Voc of module X", task C.2). Metadata validated at ingest
    cannot misstate it. The ~67% retrieval-failure reduction quoted for the
    generated form is imported from large-corpus benchmarks; D-11 states flatly
    that no benchmark exists for this task and every accuracy figure here is
    extrapolated, so it does not buy an unbounded hallucination surface on the
    hot path.
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
