"""Retrieval (FR-RAG-03, FR-RAG-04).

Hybrid retrieval, reranking, and metadata filtering by category, supplier,
doc-type and source-tier.

FR-RAG-03 says the lexical leg is **BM25**, which this docstring used to repeat.
Plan Decision 3b reverses it: dense `pgvector` plus Postgres `tsvector`/GIN plus
`pg_trgm`, then reranked. There is no permissively licensed true-BM25 for
PostgreSQL, and `pg_trgm` is the leg that actually matters here - it matches
`JKM610N-66HL4M-V` against `JKM610N 66HL4M V`, which BM25 does not. Registered
as A-24.

**Two things about that reversal changed in A-43**, and this module is where both
land:

- The three legs are **one SQL statement inside the pgvector adapter**, not three
  calls orchestrated here. This service never composes SQL: it hands
  `VectorStorePort.search` a vector, the query text and a filter set, and the
  store applies the filter in a single shared CTE that all three legs rank over.
  That is what keeps the NFR-03/AC-8 rule below - filter before ranking - a
  single place rather than three.
- **RRF (k=60) is gone.** The store returns the deduped candidate union and the
  reranker alone determines final order and `RetrievedChunk.score`. See
  `ports.RerankerPort` for why removing it cannot cost recall, and for the one
  degraded path.
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
    rerank_budget: int = 50,
    category: ComponentCategory | None = None,
    supplier: str | None = None,
    source_tier: SourceTier | None = None,
    allowed_document_ids: set[str] | None = None,
) -> list[RetrievedChunk]:
    """Hybrid retrieval with reranking.

    Two calls, in this order, and nothing between them:

    1. `store.search(embedder.embed([query])[0], query, limit=rerank_budget, ...)`
       - one statement, three legs, one shared filter (see
       `VectorStorePort.search`). `query` goes down as text as well as as a
       vector, because the `tsvector` and `pg_trgm` legs match text; before A-43
       the port took only the vector and the lexical legs had no interface to
       reach.
    2. `reranker.rerank(query, candidates, limit=limit)` - the whole candidate
       union, not a fused top-N of it. There is no fusion stage between the two
       calls; adding one back would only shrink what the cross-encoder sees.

    `rerank_budget` is the candidate budget, defaulting to Decision 5's rerank
    top-50; `limit` is the final k the caller keeps (Decision 5 suggests 5-8).
    The store divides the budget across the three legs, so the deduped union
    never exceeds it - the property that makes RRF removable rather than merely
    unfashionable. Raising the budget raises the per-leg K with it (at 60 the
    legs take 20 each) and the argument is unchanged.

    allowed_document_ids is threaded down into the store rather than applied
    afterwards because NFR-03 requires access control enforced *at retrieval
    time* via metadata filtering. Filtering after the fact would let restricted
    content influence ranking - and with three legs that is three chances to get
    it wrong, which is the second reason the filter lives in one CTE in the
    store rather than in this function.

    FR-RAG-03: system-of-record chunks must remain distinguishable from web
    supplements at all times, so source_tier is preserved on every result.
    """
    raise NotImplementedError
