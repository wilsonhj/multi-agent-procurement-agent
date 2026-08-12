"""An in-memory `LLMPort` that reads labelled lines out of its context.

It does no generation at all: it looks for `key: value` in the retrieved chunks,
coerces to the type the schema asks for, and returns `None` the moment a required
key is not there. That is a deliberately unimpressive extractor and a deliberately
strict one, because the two contracts worth proving expressible on this port are
both refusals.

**Retrieved context only.** The keys are read from the chunks it was handed and
from nowhere else, so `extract` with an empty context can only return `None`.
FR-RAG-04's requirement is that the model be *able* to say it has insufficient
evidence; a reference that could answer from anywhere would make that contract
unfalsifiable.

**No partial objects.** A missing required key fails the whole extraction rather
than returning the fields it did find. The Protocol returns
`dict[str, Any] | None`, so a partial dict is indistinguishable from a complete
one to the caller, and the fields it omitted would arrive downstream as absent
rather than as unknown.
"""

from __future__ import annotations

import re
from typing import Any

from ...ports import LLMPort, RetrievedChunk

__all__ = ["InMemoryLLM"]

_COERCE: dict[str, type] = {
    "number": float,
    "integer": int,
    "string": str,
    "boolean": bool,
}


class InMemoryLLM:
    """Reads `key: value` lines from the context, typed by the schema."""

    def extract(
        self,
        *,
        prompt: str,
        context: list[RetrievedChunk],
        json_schema: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Return every required property, or `None`.

        `prompt` is unused, and that is the honest signature rather than an
        oversight: this reference has no instruction-following to apply it to.
        A real adapter's contract obligations do not change with the prompt
        either - the prompt selects *what* to extract, and the port's promises
        are about what happens when it cannot be found.

        Properties outside the schema are never emitted, which is the part
        `SCHEMA_CONSTRAINED` is checked on: FR-ING-07's validation happens
        against this dict, and a stray key fails it two stages after the document
        that produced it has been forgotten.
        """
        properties: dict[str, Any] = json_schema.get("properties", {})
        required: list[str] = json_schema.get("required", [])
        haystack = "\n".join(chunk.text for chunk in context)

        found: dict[str, Any] = {}
        for name in required:
            match = re.search(rf"^\s*{re.escape(name)}\s*:\s*(.+?)\s*$", haystack, re.MULTILINE)
            if match is None:
                return None
            coerce = _COERCE.get(str(properties.get(name, {}).get("type", "string")), str)
            try:
                found[name] = coerce(match.group(1))
            except ValueError:
                # A value that will not coerce is not a value that was read: the
                # schema said number and the document said "approximately 350".
                # Returning the text would push a type error downstream, where
                # the source is gone; declining keeps the failure where the
                # evidence is.
                return None
        return found


def _conforms(adapter: InMemoryLLM) -> LLMPort:
    """Static structural check, run by `mypy --strict`."""
    return adapter
