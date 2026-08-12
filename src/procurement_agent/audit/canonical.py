"""H.2 - RFC 8785 (JCS) canonicalisation, in Python and not in SQL.

**Not `jsonb`.** `sql/07_audit_event.sql` stores `payload` as a generated
`jsonb` column and says explicitly that it is "never used to reverify the hash".
`jsonb` normalises key order but preserves whatever numeric literal text it was
given, so `1.0` and `1.00` remain textually distinct after a round trip - the
one thing a canonicaliser must not do. The bytes have to be produced before the
value reaches the server.

**Not `json.dumps(sort_keys=True)` either.** D-13 verified two disagreements
that both change the digest: JCS sorts keys by UTF-16 code unit where Python
sorts by code point, and JCS serialises numbers by ECMAScript rules where Python
emits `float.__repr__`, so `10.0` canonicalises to `10`. A hand-rolled near-JCS
produces chains that verify here and fail everywhere else, which is silent until
somebody outside this repo audits. `tests/test_audit_canonicalisation.py` keeps
both disagreements executable rather than remembered.

This module is a thin wrapper and stays one. The whole argument for depending on
`rfc8785` is that conformance becomes somebody else's problem, and every line of
compensation added here would take some of that problem back.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import rfc8785

__all__ = ["CanonicalisationError", "JsonObject", "JsonValue", "canonical_text", "canonicalise"]

#: What JCS can serialise. Structurally identical to `rfc8785`'s own `_Value`,
#: restated because that name is private and this package's public signatures
#: should not depend on it.
#:
#: Worth one annotation at each call site that builds a payload, because a
#: heterogeneous dict literal infers as `dict[str, object]` and will not satisfy
#: this. That friction is the feature: annotating `payload: JsonObject = {...}`
#: is what makes mypy reject a `Decimal` or a `datetime` in a payload at check
#: time rather than at the first append. Those types have a JSON form under
#: `schema.encoding.encode_value`, and that is where they should acquire it.
type JsonValue = bool | int | str | float | None | Sequence[JsonValue] | Mapping[str, JsonValue]

#: The narrower type D-13 requires in two places - the preimage envelope and the
#: `payload` inside it. Both are objects; neither may be a bare scalar.
type JsonObject = Mapping[str, JsonValue]

#: Raised when a value has no JCS representation: a non-finite float, or an
#: integer outside the range an IEEE 754 double represents exactly.
#:
#: Aliased rather than subclassed so `except` clauses in this repo also catch
#: what the library raises directly - a wrapper exception hierarchy that
#: silently fails to cover the wrapped library is worse than no wrapper.
CanonicalisationError = rfc8785.CanonicalizationError


def canonicalise(value: JsonValue) -> bytes:
    """The RFC 8785 canonical UTF-8 encoding of `value`.

    Bytes rather than `str` is the primitive because RFC 8785 section 3.2.4
    makes UTF-8 generation part of the specification: the canonical form of a
    JSON value *is* a byte string, and the digest is computed over it directly.

    Raises:
        CanonicalisationError: on NaN, an infinity, or an integer beyond
            2**53-1 - values RFC 8785 section 3.2.2.3 excludes. Refusing is the
            only safe answer: rounding one silently would produce a digest no
            conformant implementation reproduces.
    """
    return rfc8785.dumps(value)


def canonical_text(value: JsonValue) -> str:
    """`canonicalise`, decoded - what the `payload_canonical` column stores.

    That column is `text`, so a `str` is needed somewhere; doing the decode here
    keeps the single UTF-8 boundary in one place, and it is lossless in both
    directions because the bytes are UTF-8 by construction.
    """
    return canonicalise(value).decode("utf-8")
