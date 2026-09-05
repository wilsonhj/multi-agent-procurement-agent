"""`LexicalSearchPort` implementations — Decision 3b, D-25.

The in-memory reference lives here. Track 2 adds the Postgres tsvector/pg_trgm
backend. The Protocol itself is search-only; upsert is a reference convenience
so tests can stock a store without inventing a second port method.
"""

from __future__ import annotations

__all__: list[str] = []
