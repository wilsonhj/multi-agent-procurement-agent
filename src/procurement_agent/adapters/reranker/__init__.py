"""`RerankerPort` implementations — FR-RAG-03, plan Decision 3b.

No samples type: the port takes a query string and `RetrievedChunk`s, both of
which the contract suite builds from the Protocol.

This is the port that carries Decision 3b. There is no permissively licensed
true BM25 for PostgreSQL, so the lexical leg is `tsvector`/`pg_trgm` fused with
RRF - a weaker retriever than the requirement text assumes - and reranking is
what the design relies on to make up the difference. A reranker that is itself
term matching adds nothing to that fusion, which is why `SEMANTIC_SIMILARITY` is
the capability this port is really judged on.
"""

from __future__ import annotations

__all__: list[str] = []
