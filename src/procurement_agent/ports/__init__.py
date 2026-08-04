"""Swap points required by NFR-04.

    "Parsers, OCR, embedders, vector store, reranker, and LLM must be swappable
    behind stable interfaces."

Six interfaces, one per named swap point. They are structural Protocols rather
than base classes so that adapters can wrap third-party clients without
inheriting from anything here, and so no concrete dependency leaks into the core
package. No concrete adapter exists yet; when one does it will depend on an
optional extra declared in pyproject.toml, never on the core - the extras
there currently declare dependency groups only.

**These Protocols are synchronous, deliberately.** Concurrency in this system is
per-process, not per-coroutine: the runner is a Postgres job table with a
`SELECT ... FOR UPDATE SKIP LOCKED` worker loop (plan.md Decision 1), so scaling
means more worker processes. Parse and OCR are CPU-bound in-process; embedding
and reranking already take batches, so their parallelism is inside the payload
rather than at the call boundary; and the vector store is a local Postgres
round-trip under Decision 3a. A caller that needs overlap can wrap any of these
in a ThreadPoolExecutor or ProcessPoolExecutor without touching the interface,
and an async variant can be added alongside later - Protocols are structural, so
that is additive rather than a breaking change.

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
    """The reranker's score, and the reranker's alone (A-43).

    Retrieval has no fusion stage whose score could compete with it: the store
    returns a deduped candidate union, and `RerankerPort.rerank` produces the
    final order and this number. On the one degraded path - reranker
    unavailable - this carries the dense cosine score instead, and the result
    order is dense-score order.
    """


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
    """Vector store over chunks.

    FR-RAG-02 asks for an ANN index (HNSW/IVF, cosine); **plan Decision 3a
    reverses that** - exact search, because pgvector was measured silently
    under-returning on a filtered top-k, and an HNSW index cost more than the
    table. The Protocol is agnostic; do not build an ANN index on the strength
    of the requirement text alone.

    **This port owns the whole of hybrid retrieval, not just its dense leg**
    (A-43). Decision 3b's lexical legs - Postgres `tsvector`/GIN and `pg_trgm` -
    match on the query *text*, so `search` takes the text beside the vector.
    Until it did, Decision 3b was unimplementable through the ports: reaching
    those legs meant either raw SQL inside `services.retrieval` - a second,
    un-swappable path into the store, when NFR-04 names the vector store as a
    swap point and a swap that leaves two thirds of retrieval behind is not one -
    or three separate round-trips fused in Python.
    """

    def upsert(
        self, chunk_ids: list[str], vectors: list[list[float]], metadata: list[dict[str, Any]]
    ) -> None:
        """FR-RAG-05: incremental add/update by stable ID, no full re-index."""
        ...

    def delete(self, chunk_ids: list[str]) -> None: ...

    def search(
        self,
        vector: list[float],
        query_text: str,
        *,
        limit: int,
        category: ComponentCategory | None = None,
        supplier: str | None = None,
        source_tier: SourceTier | None = None,
        allowed_document_ids: set[str] | None = None,
    ) -> list[RetrievedChunk]:
        """Metadata-filtered hybrid search: **one statement, three legs**.

        `vector` and `query_text` are the same query in two representations -
        the dense leg ranks by `vector`, the `tsvector` and `pg_trgm` legs match
        `query_text`. Both are required; there is no dense-only call, because a
        caller that could omit the text would silently get a third of Decision
        3b and no error.

        The pgvector adapter must implement this as **a single SQL statement**
        (A-43):

        1. one CTE applying the `category`/`supplier`/`source_tier`/
           `allowed_document_ids` filter, evaluated under the Decision 3c row
           policies the connection already rides;
        2. three legs ranked over *that CTE* - cosine distance on `embedding`,
           `ts_rank_cd` on `tsv`, similarity on `chunk_text gin_trgm_ops` - each
           taking `limit // 3` rows;
        3. union and dedup by `chunk_id` inside the statement, `LIMIT limit`.

        One CTE is the point: filtering happens before ranking in all three legs
        at once, so restricted content cannot influence any of them. Three
        round-trips fused in Python would be three places to forget the ACL
        predicate, and under NFR-03/AC-8 one omission is a leak. It is also what
        makes the C.9 regression test (`len(results) == k` on a filtered query)
        cover every leg with a single query rather than one leg out of three.

        `limit` is the **candidate budget** handed to the reranker, not the
        caller's final k, which is why the legs take `limit // 3`: floor
        division makes the deduped union provably no larger than the budget, and
        that property is what licenses retrieval having no fusion stage at all
        (see `RerankerPort`). Dedup keeps one row per `chunk_id` carrying its
        dense score where it has one - the order the reranker-unavailable
        fallback uses; rows only a lexical leg found sort last there.

        allowed_document_ids carries NFR-03 access control. It is a search
        parameter rather than a post-filter because the requirement is that
        access control is enforced at retrieval time.
        """
        ...


@runtime_checkable
class RerankerPort(Protocol):
    """Reranking over hybrid retrieval candidates.

    FR-RAG-03 says vector + BM25; **plan Decision 3b reverses the BM25 half** -
    there is no permissively licensed true-BM25 for PostgreSQL, so the lexical
    leg is Postgres `tsvector`/GIN plus `pg_trgm`, unioned and deduped inside
    `VectorStorePort.search`'s single statement.

    Not the embedding model's sparse output, which this docstring previously
    claimed: that is a *contingency* under Decision 5 (swap Qwen3-Embedding-4B
    for `bge-m3`, which emits dense, learned-sparse and ColBERT vectors in one
    pass) held in reserve if Postgres FTS proves weak on part numbers. The same
    substitution appears in the deviation note beside FR-RAG-03 in `spec.md`,
    which is why it is spelled out here. Reranking is what lets the design get
    away without BM25 at all, which is this port's stake in the decision.

    **This port is now the only thing that orders results** (A-43). Decision 3b
    originally fused the three legs with RRF (k=60) before reranking; that stage
    is gone, and it cost nothing to remove. RRF's only observable effect here was
    choosing which candidates made the rerank cut-off - Decision 3b says outright
    that the ranking function "barely matters" because the cross-encoder
    determines final order - and `search` sizes its legs so the whole deduped
    union already fits inside the rerank budget. A fusion step over a union that
    already fits can only drop candidates, so union recall >= RRF recall by
    construction.

    **Degraded path:** if the reranker is unavailable, that request falls back to
    dense-score order. Not to RRF - reintroducing it as the fallback would put
    back the stage this decision removed, on the path where it is least
    justified and least exercised.
    """

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
