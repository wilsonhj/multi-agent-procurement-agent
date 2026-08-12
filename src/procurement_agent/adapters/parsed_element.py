"""What the adapter side has to supply about `ports.ParsedElement`.

`ParsedElement` is the unit both `ParserPort` and `OCRPort` return, and it is
declared as three annotated attributes. Two of the things a consumer needs from
it are stated in its docstring and absent from its type, and one clause of
FR-ING-04 cannot be stated at all. All three live here, on the adapter side of
the boundary, because `ports/` is the frozen interface and this track does not
amend it - they are reported as findings instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ports import ParsedElement

__all__ = ["PARSED_ELEMENT_KINDS", "UNEXPRESSIBLE_BOUNDING_BOXES", "TextElement"]


PARSED_ELEMENT_KINDS: frozenset[str] = frozenset({"heading", "body", "table", "figure"})
"""The `kind` vocabulary, which the Protocol states only in prose.

`kind` is typed `str` and documented as "heading, body, table or figure". A
Protocol cannot express a closed vocabulary over a `str`, so an adapter emitting
`"paragraph"` or `"Table"` is correct under the type and unusable to every
consumer that switches on the value. `_assert_element_shape` in the contract
suite is what holds adapters to it meanwhile.
"""


UNEXPRESSIBLE_BOUNDING_BOXES = (
    "FR-ING-04 requires OCR to retain bounding boxes, and OCRPort.recognize's own "
    "docstring promises them, but ParsedElement declares kind, text and page and "
    "nothing else. Structural typing means an adapter may return elements that "
    "carry a box; it means no consumer may rely on one, so no contract test can "
    "assert it and no capability can honestly cover it. The gap is in the Protocol. "
    "Closing it means adding the member to ParsedElement - a ports/ change, out of "
    "this track's scope - after which BOUNDING_BOXES becomes an ordinary capability "
    "and OCR adapters declare it. Pinned by "
    "test_fr_ing_04s_bounding_box_clause_is_not_expressible_through_parsedelement."
)
"""A requirement clause the interface cannot carry, named so it is not forgotten.

The house precedent is `confidence.UNIMPLEMENTED_REVIEW_ROUTING`: a gap with a
constant and a test naming it is a gap someone can find; one with only a comment
is a gap that gets rediscovered.
"""


@dataclass
class TextElement:
    """The concrete `ParsedElement` the in-memory references return.

    **Not frozen, and that is a finding rather than a preference.**
    `ParsedElement` declares plain annotated attributes, which a type checker
    reads as read-write, so a frozen implementation is not guaranteed to satisfy
    it. `docs/architecture.md` asks for "frozen models for immutable evidence",
    and a parsed element is evidence; the Protocol as written cannot promise that
    an immutable one is admissible. Declaring the members `ReadOnly`, or as
    properties, would be the fix, and it belongs in `ports/`.
    """

    kind: str
    text: str
    page: int | None


def _conforms(element: TextElement) -> ParsedElement:
    """Static proof, checked by `mypy --strict`, that the shape still matches.

    `isinstance` against a `runtime_checkable` Protocol checks attribute presence
    only, and `ParsedElement` is not even runtime-checkable. This is the check
    that fails when a member is renamed or retyped.
    """
    return element
