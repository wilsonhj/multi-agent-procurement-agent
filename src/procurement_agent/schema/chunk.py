"""The unit `chunk()` returns (P2-C2 / story-2 §1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["ChunkRecord"]


@dataclass(frozen=True)
class ChunkRecord:
    """One indexable unit after structure-aware chunking.

    `chunk_id` is a function of stored data only:
    `sha256(document_id, kind, table_id or None, ordinal)[:32]`. Track 2
    implements the hash; this freeze documents the rule so a later clock,
    embedding, or model name cannot sneak into identity (A-50).

    `text` is what is embedded, after `context_prefix` is prepended. `body` is
    the chunk without that prefix (stored as `chunk_text`) so a citation shows
    what the document said.
    """

    chunk_id: str
    document_id: str
    kind: Literal["prose", "table_full", "table_row", "table_summary"]
    text: str
    body: str
    context_prefix: str
    page: int | None
    section: str | None
    table_id: str | None
    ordinal: int
