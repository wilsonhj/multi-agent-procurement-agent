"""`VectorStorePort` implementations — FR-RAG-02/05, NFR-03, plan Decision 3a.

Two things this package supplies that the Protocol leaves open, both because
`ports/` is frozen and this track does not amend it.

`ChunkMetadata` fixes the key vocabulary. `upsert` takes
`metadata: list[dict[str, Any]]`, `search` filters on `category`, `supplier` and
`source_tier`, and `RetrievedChunk` promises `document_id`, `text`, `page` and
`source_tier` back - so the keys that carry a value from one to the other are
required by the Protocol's behaviour and named nowhere in its types. Without a
shared vocabulary no adapter-agnostic test can populate a store, and two adapters
would disagree about the spelling of `document_id` at the first integration.

`VectorStoreSamples` carries the vector width the adapter was configured for. It
is a sample rather than a port member because a real store's width is fixed by
its column definition (`sql/03_chunk.sql`) at deployment, and the Protocol
deliberately does not ask about it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from ...schema import ComponentCategory, SourceTier

__all__ = ["ChunkMetadata", "VectorStoreSamples"]


class ChunkMetadata(TypedDict):
    """The metadata keys `upsert` carries and `search` reads.

    A `TypedDict` rather than a model: it has to remain an ordinary `dict` at the
    call boundary, because that is what the Protocol's `list[dict[str, Any]]`
    accepts and what a real driver will hand to a JSON or `jsonb` column.

    `category` and `supplier` are here because `search` filters on them;
    `document_id`, `text`, `page` and `source_tier` because `RetrievedChunk`
    promises them back and a store has nowhere else to have learned them.
    `source_tier` in particular is FR-RAG-03's hard requirement that a
    system-of-record chunk stay distinguishable from a web supplement at all
    times - it travels with the row rather than being looked up later.
    """

    document_id: str
    text: str
    page: int | None
    source_tier: SourceTier
    category: ComponentCategory
    supplier: str


@dataclass(frozen=True)
class VectorStoreSamples:
    """The vector width the shared contracts must build their fixtures at."""

    dimensions: int
