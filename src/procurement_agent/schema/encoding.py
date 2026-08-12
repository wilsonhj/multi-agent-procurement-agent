"""The single value encoder behind contracts C4 and C6.

Both the audit preimage (D-13) and the workbook projection (D-14) have to turn
arbitrary field values into something hashable, and doing that twice is how the
two drift apart. This module is the one authority: `encode_value` maps a value
to JSON-representable Python, and every caller that needs canonical bytes runs
its output through a serialiser rather than inventing a second set of rules.

**The requirement is a property, not the table.** D-14 states it as: the encoding
must be *injective over the value domain*. The domain that needs it is the
polymorphic one - `CanonicalField.value` is typed `object | None`, so a single
key path carries a `Decimal` for one field and a `str` for another, and nothing
about the position tells a reader which. That is why `Decimal`, `date` and
`datetime` carry tags and no other type does: bare JSON already separates `22`,
`22.0`, `"22"`, `true` and `null` in *text*, but `Decimal("22")` and `"22"` both
want to become `"22"`.

**Closed world.** An unlisted type raises rather than falling back, so a new
value type is a loud decision recorded in D-14 instead of a silent second
encoding rule. `tests/test_encoding.py` holds the property tests.

Placement: `schema` sits below `services` and cannot import it (see
`component.py`), and both consumers live in `services`, so the shared encoder
belongs here.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from math import isfinite

from pydantic import BaseModel

__all__ = ["UnencodableValueError", "encode_value"]


class UnencodableValueError(TypeError):
    """A value fell outside D-14's table.

    A `TypeError` subclass because that is what it is - the caller passed a type
    the contract does not admit. Raising rather than degrading is the point: the
    alternative is an artifact whose hash is computed over an encoding nobody
    wrote down.
    """


def encode_value(value: object) -> object:
    """Encode `value` as JSON-representable Python, per D-14's table.

    The isinstance order below is load-bearing in three places and each one has
    already been a bug somewhere:

    * `datetime` is a **subclass of `date`**, so testing `date` first silently
      swallows every datetime, mislabels it under a `$date` tag, and collides
      midnight UTC with the bare day.
    * `bool` is a **subclass of `int`**. Both encode bare so the result is the
      same, but the check is explicit because a later edit that gives `int` a
      tag would otherwise tag `True` too.
    * every enum here is a `StrEnum` or an `IntEnum`, so a member **is** a `str`
      or an `int`. `Enum` is tested first and recurses on `.value`, which for
      those bases is the identity - `MeasurementBasis.STC == "stc"` is one
      value, and tagging it would give that single value two encodings and
      *break* injectivity rather than protect it.

    Raises:
        UnencodableValueError: on any type not in the table, at any depth.
    """
    if value is None:
        return None

    # Before str/int: a StrEnum member is both. `.value` is the identity for the
    # StrEnum and IntEnum bases used here; recursing rather than returning it raw
    # keeps a hypothetical plain `Enum` with a structured value inside the table.
    if isinstance(value, Enum):
        return encode_value(value.value)

    if isinstance(value, bool):  # before int - bool is an int subclass
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if not isfinite(value):
            raise UnencodableValueError(
                f"non-finite float {value!r}: JSON cannot represent it, and NaN is not "
                "equal to itself so no injective encoding of it exists. The schema "
                "rejects these at construction (`_reject_non_finite`); this is the "
                "encoder refusing to be the hole in that."
            )
        return value

    if isinstance(value, str):
        return value

    if isinstance(value, Decimal):
        # `str()`, never `normalize()`: `Decimal("22")` and `Decimal("22.0")` are
        # equal and hash alike, but `conflict_hitl._decimals` reads precision from
        # this exact text and it sets D-2's rounding floor - 0 places gives 0.5,
        # 1 place gives 0.05. Against a competing 22.4 that is the difference
        # between no conflict and a human being asked to review, so collapsing
        # the trailing zero is a behaviour change, not a formatting one.
        return {"$decimal": str(value)}

    if isinstance(value, datetime):  # before date - datetime is a date subclass
        return {"$datetime": _rfc3339(value)}

    if isinstance(value, date):
        return {"$date": value.isoformat()}

    if isinstance(value, BaseModel):
        return _encode_model(value)

    if isinstance(value, frozenset):
        # Sorted because a frozenset iterates in hash order, which is randomised
        # per process - the same reason `Condition._sort_derived` exists. Sorting
        # the encoded forms rather than the raw members keeps the order total even
        # for a mixed-type set, where `sorted()` on the members would raise.
        return sorted((encode_value(item) for item in value), key=_sort_key)

    if isinstance(value, list | tuple):
        # `list` is the declared type of 18 contract fields, and order there is
        # content rather than presentation, so it is never sorted. `tuple` is
        # admitted for condition grouping keys on the sort path and never for a
        # stored value; the two share the JSON array deliberately, which is sound
        # because a tuple never reaches the polymorphic `value` slot where
        # injectivity is required. See `test_fixed_position_containers_...`.
        return [encode_value(item) for item in value]

    raise UnencodableValueError(
        f"{type(value).__name__} is not in the D-14 encoding table. Add a row there "
        "with its injectivity argument before encoding it, rather than widening this "
        "function - a silent fallback is how an artifact acquires a second, "
        "undocumented encoding rule."
    )


def _encode_model(model: BaseModel) -> dict[str, object]:
    """Dump a model and route every leaf back through `encode_value`.

    D-14 says `model_dump` for `DeclaredBand`, which needs one clarification and
    one correction. Plain `model_dump()` runs in *python mode* and returns `kind`
    as the `ToleranceKind` member itself, which is not JSON and is one `repr()`
    away from `<ToleranceKind.ABSOLUTE: 'absolute'>` - the A-6 class of defect,
    where an artifact hash moves because a member was renamed. And `mode="json"`
    would fix that single case while creating a worse one: a `Decimal` field
    added to this model later would be serialised by pydantic's rules instead of
    earning its `$decimal` tag, so two distinct precisions would collide.
    Recursing keeps one encoding authority for every leaf.
    """
    dumped = model.model_dump()
    for key in dumped:
        if key.startswith("$"):
            # D-14's backstop. `$` is safe as a sigil because pydantic field names
            # are Python identifiers, so only a deliberate alias could mint a key
            # that shadows a tag - and if one ever does, it must not do so quietly.
            raise UnencodableValueError(
                f"{type(model).__name__} dumps a key {key!r} beginning with the tag "
                "sigil, which would be indistinguishable from an encoded scalar."
            )
    return {key: encode_value(item) for key, item in dumped.items()}


def _rfc3339(value: datetime) -> str:
    """RFC 3339 in UTC with microseconds always printed.

    Two properties, both required:

    * **Aware only.** A naive datetime names no instant, so no encoding of it can
      be honest. Assuming UTC would be worse than refusing - a naive noon and an
      aware noon-UTC are *not* equal in Python, so encoding both to one string
      would break injectivity in the silent direction.
    * **Converted, then formatted.** Aware datetimes compare by instant, so
      `14:00+02:00 == 12:00Z` is one value written two ways and must encode once.
      The conversion is what makes equal values encode identically; it loses
      nothing.

    `isoformat()` omits `.000000` when the field is zero, which is why the format
    is pinned here rather than delegated.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise UnencodableValueError(
            f"naive datetime {value!r}: it names no instant, so it cannot be encoded "
            "without inventing a zone. Attach one at the boundary that produced it."
        )
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _sort_key(encoded: object) -> str:
    """A total order over encoded values, for `frozenset` output only.

    Set members can be of mixed type, where `sorted()` on the values themselves
    raises. Ordering by canonical JSON text is total, deterministic across
    processes, and never consulted for anything a reader sees - the projection's
    meaning does not depend on which order a set is written in, only on its being
    the *same* order every run.
    """
    return json.dumps(encoded, sort_keys=True, separators=(",", ":"))
