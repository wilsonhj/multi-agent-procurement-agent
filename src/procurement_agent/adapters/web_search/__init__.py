"""`WebSearchPort` implementations — FR-WEB-01/02, D-20.

The in-memory reference lives here. Track 3 adds the Brave backend. Hits carry
`url`, `title`, `retrieved_at` and `provider` only; snippet and rank stay off
the type (D-20).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["WebSearchSamples"]


@dataclass(frozen=True)
class WebSearchSamples:
    """The query the shared contracts send against this adapter's fixture map."""

    query: str
