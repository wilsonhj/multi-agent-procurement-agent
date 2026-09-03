"""An in-memory `EmbedderPort` that hashes tokens into buckets.

**It carries no meaning, deliberately.** A reference that faked semantic
similarity would make `SEMANTIC_SIMILARITY` a capability every adapter appears to
have, and the one contract that actually separates an embedding model from a
lookup table would never fail for anyone. So this declares the capability absent,
with a reason, and the suite `xfail(strict=True)`s the test - which is the shape
ADR-001 adopted the pattern for.

Everything else about the port it does hold honestly: a fixed width, one vector
per input in order, finite components, and the same answer every time.
"""

from __future__ import annotations

import hashlib
import math
import re

from ...ports import EmbedderPort

__all__ = ["InMemoryEmbedder"]

_TOKEN = re.compile(r"[a-z0-9]+")


class InMemoryEmbedder:
    """Bag-of-tokens hashed into a small fixed-width vector."""

    def __init__(self, dimensions: int = 32) -> None:
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        """A property, matching the Protocol.

        A plain attribute would satisfy it too - a read-only Protocol member
        admits either - but a real adapter reads this off a loaded model, so the
        reference keeps the shape that has somewhere to put that.
        """
        return self._dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        """Hash each token into a bucket, then normalise to unit length.

        **`hashlib`, never the builtin `hash()`.** `hash()` on a `str` is salted
        per process by `PYTHONHASHSEED`, so the same text would embed differently
        in two workers - and plan Decision 1 scales by adding worker processes.
        FR-RAG-05's incremental updates mean vectors written by different
        processes sit in one index and are compared with each other, so a
        per-process salt would corrupt neighbourhoods with no data change: the
        A-50 question ("could this change without the data changing?") answered
        wrongly. The same reasoning is why `schema/encoding.py` sorts frozensets
        rather than trusting iteration order.

        Unit length so that cosine and dot product agree, which is what lets the
        contract suite compare scores across adapters without knowing the metric.
        """
        vector = [0.0] * self._dimensions
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            vector[int.from_bytes(digest, "big") % self._dimensions] += 1.0

        norm = math.sqrt(sum(component * component for component in vector))
        return [component / norm for component in vector] if norm else vector


def _conforms(adapter: InMemoryEmbedder) -> EmbedderPort:
    """Static structural check, run by `mypy --strict`."""
    return adapter
