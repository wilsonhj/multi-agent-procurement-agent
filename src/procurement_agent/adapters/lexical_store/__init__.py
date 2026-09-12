"""`LexicalSearchPort` implementations — Decision 3b, D-25.

The in-memory reference lives here. Track 2 adds the Postgres tsvector/pg_trgm
backend. The Protocol itself is search-only; upsert is a reference convenience
so tests can stock a store without inventing a second port method.
`LexicalStoreSamples.load` is how the shared contracts stock an adapter without
naming `InMemoryLexicalStore`.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...schema import ComponentCategory, SourceTier

__all__ = ["LexicalStoreSamples"]


@dataclass(frozen=True)
class LexicalStoreSamples:
    """Marker that this adapter can be stocked for the shared contracts.

    `upsert` is not on `LexicalSearchPort`. The suite stocks via `load`, which
    calls the adapter's own `upsert` if present.
    """

    def load(
        self,
        store: object,
        *,
        chunk_ids: list[str],
        texts: list[str],
        document_ids: list[str],
        pages: list[int | None],
        source_tiers: list[SourceTier],
        categories: list[ComponentCategory],
        suppliers: list[str],
    ) -> None:
        upsert = getattr(store, "upsert", None)
        if upsert is None:
            raise TypeError(f"{type(store).__name__} has no upsert; the suite cannot stock it")
        upsert(
            chunk_ids,
            texts,
            document_ids,
            pages,
            source_tiers,
            categories,
            suppliers,
        )
