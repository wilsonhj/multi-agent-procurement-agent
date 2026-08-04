"""Retrieval (FR-RAG-03, FR-RAG-04).

Hybrid retrieval, reranking, and metadata filtering by category, supplier,
doc-type and source-tier.

FR-RAG-03 says the lexical leg is **BM25**, which this docstring used to repeat.
Plan Decision 3b reverses it: dense `pgvector` plus Postgres `tsvector`/GIN plus
`pg_trgm`, fused with Reciprocal Rank Fusion (k=60), then reranked. There is no
permissively licensed true-BM25 for PostgreSQL, and `pg_trgm` is the leg that
actually matters here - it matches `JKM610N-66HL4M-V` against
`JKM610N 66HL4M V`, which BM25 does not. Registered as A-24.
"""

from __future__ import annotations

from ...ports import EmbedderPort, RerankerPort, RetrievedChunk, VectorStorePort
from ...schema import ComponentCategory, SourceTier


def retrieve(
    query: str,
    *,
    embedder: EmbedderPort,
    store: VectorStorePort,
    reranker: RerankerPort,
    limit: int = 10,
    category: ComponentCategory | None = None,
    supplier: str | None = None,
    source_tier: SourceTier | None = None,
    allowed_document_ids: set[str] | None = None,
) -> list[RetrievedChunk]:
    """Hybrid retrieval with reranking.

    allowed_document_ids is threaded down into the store rather than applied
    afterwards because NFR-03 requires access control enforced *at retrieval
    time* via metadata filtering. Filtering after the fact would let restricted
    content influence ranking.

    FR-RAG-03: system-of-record chunks must remain distinguishable from web
    supplements at all times, so source_tier is preserved on every result.
    """
    raise NotImplementedError
