"""An in-memory `ParserPort` over a comma-delimited grid.

**What this is for.** It is the control in the conformance suite: it shows that
`ParserPort` can be satisfied by *something*, so a red contract test is evidence
about the adapter under test rather than about a contract nobody has ever met. It
is not a production parser and there is nothing here a real one should copy
except the shape.

**Why a delimited grid and not a paragraph of prose.** FR-ING-02 is spreadsheets,
and a grid is the smallest input that makes two things honest at once. It has a
genuine table, so `TABLE_STRUCTURE` is a capability this reference really holds
rather than one faked with a hard-coded element. And it has no pagination at all,
so `PAGE_NUMBERS` is `NOT_APPLICABLE` for a real reason - which is what keeps the
suite's skip path exercised by an honest example instead of a contrived one.
"""

from __future__ import annotations

from ...ports import ParsedElement, ParserPort
from ..parsed_element import TextElement

__all__ = ["InMemoryParser"]


class InMemoryParser:
    """Parses UTF-8 comma-delimited text into a heading, a table and body rows."""

    SIGNATURES = frozenset({"text/csv"})
    """Media types, compared exactly.

    Exact membership rather than a prefix or suffix test, because FR-ING-01 says
    routing is by content signature "never by file extension" and a suffix test
    is an extension test wearing a media type's clothes - `".csv"` and
    `"quote.csv"` would both match a `str.endswith("csv")`.
    """

    def supports(self, content_signature: str) -> bool:
        return content_signature in self.SIGNATURES

    def parse(self, data: bytes) -> list[ParsedElement]:
        """Decode strictly, then emit heading, table and one body row each.

        `decode("utf-8")` without `errors=` is load-bearing: undecodable bytes
        raise `UnicodeDecodeError` rather than producing replacement characters.
        A parser that returns elements full of U+FFFD, or an empty list, is
        indistinguishable from one that read a genuinely empty file, and
        FR-ING-09's per-page audit for missing text is built on telling those
        apart.

        The return type is annotated `list[ParsedElement]` and not
        `list[TextElement]` because `list` is invariant: the narrower annotation
        does not satisfy the Protocol's signature and `mypy --strict` rejects it.
        Worth knowing before writing the second adapter rather than during it.
        """
        rows = [
            [cell.strip() for cell in line.split(",")]
            for line in data.decode("utf-8").splitlines()
            if line.strip()
        ]
        if not rows:
            return []

        header, *body = rows
        elements: list[ParsedElement] = [
            TextElement(kind="heading", text=" | ".join(header), page=None),
            TextElement(
                kind="table",
                text="\n".join(" | ".join(row) for row in rows),
                page=None,
            ),
        ]
        elements.extend(TextElement(kind="body", text=" | ".join(row), page=None) for row in body)
        return elements


def _conforms(adapter: InMemoryParser) -> ParserPort:
    """Static structural check, run by `mypy --strict`.

    The runtime `isinstance` in the matrix suite checks that the attributes
    exist; this checks that their signatures still match. Neither subsumes the
    other, and the class deliberately inherits nothing so that the only thing
    binding it to the port is its shape.
    """
    return adapter
