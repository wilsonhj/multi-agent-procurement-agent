"""The C6/C4 value encoder: D-14's table, and the property the table serves.

The table is checked here row by row, but the table is not the requirement.
clarifications.md D-14 states the requirement as a property - `encode_value()`
must be **injective over the value domain** - and calls the table one
implementation of it. So the tests below come in two kinds, and the second kind
is the one that must survive a rewrite:

* row tests pin the wire format, and will legitimately need re-baselining if the
  format is ever versioned;
* property tests pin injectivity in both directions, and a change that breaks
  one of those is a correctness bug regardless of what the table says.
"""

from __future__ import annotations

import itertools
import json
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import BaseModel, computed_field

from procurement_agent.schema import (
    CanonicalField,
    Condition,
    ConditionDimensions,
    DeclaredBand,
    MeasurementBasis,
    PowerSide,
    Severity,
    SourceRef,
    SourceTier,
    ToleranceKind,
)
from procurement_agent.schema.encoding import UnencodableValueError, encode_value


def canonical(value: object) -> str:
    """The bytes injectivity is judged on.

    Injectivity of `encode_value` alone is not the property that matters: two
    values could encode to distinct Python objects that serialise to identical
    JSON. The comparison has to happen after serialisation, which is also a free
    check that every encoding is JSON-representable at all.
    """
    return json.dumps(encode_value(value), sort_keys=True, separators=(",", ":"))


# --------------------------------------------------------------------------
# The table (D-14)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("stc", "stc"),
        (22, 22),
        (22.0, 22.0),
        (True, True),
        (False, False),
        (None, None),
        (Decimal("22.0"), {"$decimal": "22.0"}),
        (date(2026, 8, 11), {"$date": "2026-08-11"}),
        (MeasurementBasis.STC, "stc"),
        (Severity.HIGH, 3),
        (frozenset({"c", "a", "b"}), ["a", "b", "c"]),
        (("a", 1), ["a", 1]),
        (["IEC 61215", "IEC 61730"], ["IEC 61215", "IEC 61730"]),
    ],
)
def test_table_rows(value: object, expected: object) -> None:
    assert encode_value(value) == expected


def test_declared_band_dumps_through_the_same_encoder() -> None:
    """A band's *leaves* go through `encode_value`, not through pydantic.

    D-14 says `model_dump`, but a plain `model_dump()` runs in python mode and
    returns `kind` as the `ToleranceKind` member itself - not JSON, and a `<...>`
    repr away from the A-6 artifact-instability class. `mode="json"` would fix
    that one case and quietly create a worse one: a `Decimal` field added to this
    model later would be serialised by pydantic's rules instead of earning its
    `$decimal` tag, so two distinct precisions would collide. Recursing keeps a
    single encoding authority for every leaf in the tree.
    """
    band = DeclaredBand(low=0.0, high=5.0, kind=ToleranceKind.ABSOLUTE, unit="W")
    assert encode_value(band) == {"low": 0.0, "high": 5.0, "kind": "absolute", "unit": "W"}


def test_encoded_output_contains_only_json_native_types() -> None:
    """Every leaf must be *exactly* a JSON type, not merely equal to one.

    This is the test that catches a `model_dump()` whose leaves were never
    recursed, and it has to check `type(...) is` rather than `isinstance`,
    because a `StrEnum` member passes every `isinstance(..., str)` check, equals
    its own value, and is written by `json.dumps` as a plain string. So an
    encoder that leaks raw enum members looks correct under equality assertions
    and stays correct right up until a field is added whose type is not a `str`
    or `int` subclass - at which point the encoding silently stops being the one
    D-14 describes. Structure is the only thing that distinguishes them.
    """
    json_native = (str, int, float, bool, type(None))

    def check(node: object, path: str) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                assert type(key) is str, f"{path}: non-str key {key!r} ({type(key).__name__})"
                check(item, f"{path}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                check(item, f"{path}[{index}]")
        else:
            assert type(node) in json_native, (
                f"{path}: {node!r} is a {type(node).__name__}, which only *behaves* "
                "like a JSON type here"
            )

    for value in _VALUE_DOMAIN:
        check(encode_value(value), type(value).__name__)


def test_a_model_holding_other_models_encodes_all_the_way_down() -> None:
    """`CanonicalField` is the repo's central model and nests three others.

    The first implementation used `model_dump()`, which flattens the whole tree
    in one call - so `condition` and `source_ref` arrived as plain `dict` and hit
    the closed-world raise. `encode_value` could not encode the one model it most
    needs to. Walking the fields instead keeps nested models *as models*, so each
    one re-enters through the same door.
    """
    field = CanonicalField(
        value=Decimal("550"),
        unit="Wp",
        condition=Condition(basis=MeasurementBasis.STC, derived=frozenset({"basis"})),
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(url="https://example.invalid/ds"),
        confidence=0.9,
    )
    encoded = encode_value(field)
    assert isinstance(encoded, dict)
    assert encoded["value"] == {"$decimal": "550"}  # the tag survives the nesting
    assert isinstance(encoded["condition"], dict)
    assert encoded["condition"]["basis"] == "stc"
    assert encoded["condition"]["derived"] == ["basis"]
    assert encoded["source_tier"] == "system_of_record"


def test_maps_are_tagged_because_json_keys_are_always_strings() -> None:
    """The contract has three genuinely dict-valued parameters, so D-14's premise
    that "bare dicts are not a value type at all" is false.

    A bare JSON object cannot carry them injectively: object keys are strings, so
    `{1: 0.5}` and `{"1": 0.5}` both serialise to `{"1": 0.5}` and two distinct
    values collide. `harmonic_spectrum` is `dict[int, float]` while
    `rating_mva_by_cooling` is `dict[str, float]`, and both can occupy the
    polymorphic `value` slot - so this is a live collision, not a hypothetical.

    `$map` carries pairs with the key *encoded*, which keeps the key's type and
    restores injectivity. Pairs are sorted so a dict's insertion order - which is
    not part of its value - cannot reach the bytes.
    """
    assert encode_value({1: 0.5}) == {"$map": [[1, 0.5]]}
    assert encode_value({"1": 0.5}) == {"$map": [["1", 0.5]]}
    assert canonical({1: 0.5}) != canonical({"1": 0.5})

    # insertion order is not content
    assert canonical({"b": 2, "a": 1}) == canonical({"a": 1, "b": 2})

    # and a map cannot be confused with a model, which encodes bare
    assert "$map" not in str(
        encode_value(DeclaredBand(low=0.0, high=1.0, kind=ToleranceKind.RELATIVE))
    )


def test_a_dollar_key_inside_a_map_is_refused() -> None:
    """`$` is only a safe sigil while nothing else can mint one.

    D-14's argument covers model dumps - pydantic field names are identifiers -
    but a `dict[str, str]` like `ercot_compliance_items` takes arbitrary keys, so
    a caller could supply `"$decimal"`. Inside `$map` that is harmless, since the
    pair list is unambiguous; refusing anyway keeps one rule for the whole
    encoding rather than one that holds in some positions.
    """
    with pytest.raises(UnencodableValueError, match=r"\$"):
        encode_value({"$decimal": "22"})


def test_no_encoding_contains_a_repr_artifact() -> None:
    """A standing guard against the A-6 defect class, and specifically A-50.

    Every `<` that reaches a hashed artifact in this repo has arrived the same
    way: something called `repr()` on an enum or a model and got
    `<ToleranceKind.ABSOLUTE: 'absolute'>`. That string embeds a class identity,
    so renaming a member changes an artifact hash while the data is unchanged.
    Nothing this encoder emits may contain one.
    """
    for value in _VALUE_DOMAIN:
        assert "<" not in canonical(value), value


# --------------------------------------------------------------------------
# The property: equal values encode identically
# --------------------------------------------------------------------------


def test_str_enum_members_encode_as_their_own_value() -> None:
    """Tagging enums would *break* injectivity, not protect it.

    Every enum here is a `StrEnum` or `IntEnum`, so a member **is** the
    primitive: `MeasurementBasis.STC == "stc"` is `True`. One value. Give the
    member a tag and that single value acquires two encodings, which is a
    violation of the property in the direction that is easy to mistake for
    safety.
    """
    # mypy narrows both sides to `Literal[...]` and calls the comparison
    # non-overlapping, because it does not model a StrEnum member as a `str` for
    # equality. At runtime it overlaps - that is the entire fact this test
    # asserts and the fact D-14's "bare `.value` is correct" rests on - so the
    # ignore records a checker limitation rather than silencing a defect.
    assert MeasurementBasis.STC == "stc"  # type: ignore[comparison-overlap]
    assert canonical(MeasurementBasis.STC) == canonical("stc")

    assert Severity.HIGH == 3  # type: ignore[comparison-overlap]
    assert canonical(Severity.HIGH) == canonical(3)


def test_equal_instants_in_different_zones_encode_identically() -> None:
    """Aware datetimes compare by instant, so the encoding must too.

    `datetime(14:00, +02:00) == datetime(12:00, UTC)` is `True` in Python - one
    value written two ways. Converting to UTC before formatting is what makes
    equal values encode identically here; it is not a normalisation that loses
    anything.
    """
    berlin = datetime(2026, 8, 11, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    utc = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    assert berlin == utc
    assert canonical(berlin) == canonical(utc)


def test_frozenset_encoding_does_not_depend_on_insertion_order() -> None:
    """`derived` is a frozenset and iterates in hash order, which is randomised
    per process - the reason `Condition._sort_derived` exists. The same set built
    two ways is one value and must produce one encoding."""
    assert canonical(frozenset(["b", "a"])) == canonical(frozenset(["a", "b"]))


# --------------------------------------------------------------------------
# The property: distinct values encode distinctly
# --------------------------------------------------------------------------


def test_decimal_precision_survives() -> None:
    """The trailing zero decides whether a human is asked to review.

    `Decimal("22") == Decimal("22.0")` and the two hash alike, but
    `conflict_hitl._decimals` reads precision from `str(value)` and that sets
    D-2's rounding floor: 0 places gives a 0.5 floor, 1 place gives 0.05. So
    against a competing 22.4, the first is no conflict and the second is a
    conflict. Collapsing them is a behaviour change, not a formatting one -
    which is why `Decimal.normalize()` must never appear in this module.
    """
    assert Decimal("22") == Decimal("22.0")
    assert canonical(Decimal("22")) != canonical(Decimal("22.0"))


def test_tagged_scalars_do_not_collide_with_their_string_forms() -> None:
    """Why `Decimal` and `date` earn tags and nothing else does.

    Bare JSON primitives already separate themselves in *text*. These two do not:
    untagged, `Decimal("22")` and `"22"` both want to become `"22"`.
    """
    assert canonical(Decimal("22")) != canonical("22")
    assert canonical(date(2026, 8, 11)) != canonical("2026-08-11")


def test_a_datetime_is_never_encoded_as_a_date() -> None:
    """`datetime` is a subclass of `date`, so an isinstance chain that tests
    `date` first silently swallows every `datetime` - mislabelling it under a
    `$date` tag and colliding midnight UTC with the bare day."""
    assert isinstance(datetime(2026, 8, 11, tzinfo=UTC), date)
    midnight = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    encoded = encode_value(midnight)
    assert encoded != encode_value(date(2026, 8, 11))
    # `encode_value` returns `object`, so the tag check needs the shape pinned
    # first - which is worth asserting in its own right.
    assert isinstance(encoded, dict)
    assert "$date" not in encoded


def test_datetime_always_prints_microseconds() -> None:
    """`isoformat()` drops `.000000` when the field is zero, so two datetimes one
    microsecond apart would differ in *length* of representation rather than
    consistently in content. Pinning the formatter keeps one shape."""
    assert encode_value(datetime(2026, 8, 11, 12, 0, tzinfo=UTC)) == {
        "$datetime": "2026-08-11T12:00:00.000000Z"
    }
    assert encode_value(datetime(2026, 8, 11, 12, 0, 0, 1, tzinfo=UTC)) == {
        "$datetime": "2026-08-11T12:00:00.000001Z"
    }


def test_the_polymorphic_value_domain_is_injective() -> None:
    """The property D-14 states, over the domain that actually needs it.

    `CanonicalField.value` is typed `object | None`, so a single key path holds a
    `Decimal` for one field and a `str` for another. Position cannot disambiguate
    there, so the encoding must - which is the whole reason `Decimal` and `date`
    carry tags while nothing else does. Injectivity is required over *this* union
    and is checked here pairwise.
    """
    for left, right in itertools.combinations(_POLYMORPHIC_VALUE_DOMAIN, 2):
        if canonical(left) == canonical(right) and left != right:
            pytest.fail(f"{left!r} and {right!r} share the encoding {canonical(left)}")


def test_fixed_position_containers_are_excluded_from_that_claim_on_purpose() -> None:
    """Why `frozenset`, `tuple` and `list` may share the JSON array.

    All three encode to an array, so the function is *not* injective over the
    union of every type in D-14's table. That is sound only because the two
    non-list containers never reach the polymorphic `value` slot: `derived` is a
    frozenset at a fixed key on `Condition`, and tuples exist solely on the
    `comparison_groups` sort path. Their type is fixed by position, so no pair of
    distinct projections can collide through them.

    Pinned as a test because the alternative reading - "add `$frozenset` and
    `$tuple` tags for safety" - buys nothing and puts sigils into sort keys.
    """
    assert canonical(frozenset({"a"})) == canonical(["a"]) == canonical(("a",))
    assert "derived" in Condition.model_fields
    assert "derived" not in ConditionDimensions.model_fields


def test_equal_values_of_one_type_always_encode_identically() -> None:
    """The companion direction, and the one place it is deliberately not honoured.

    Within a type, `a == b` must imply identical encodings. Across the numeric
    types Python conflates - `True == 1 == 1.0` and `Severity.INFORMATIONAL == 0`
    - it holds for the enum (a member *is* its primitive) and is deliberately
    broken for `bool` against `int` and `int` against `float`. D-14 settles that
    by calling `22`, `22.0`, `"22"`, `true` and `null` "five different tokens":
    over-separating a coincidence is safe, under-separating a precision is not.
    """
    assert canonical(Severity.INFORMATIONAL) == canonical(0)  # one value, one encoding
    assert canonical(True) != canonical(1)  # coincidence, separated on purpose
    assert canonical(1) != canonical(1.0)


# --------------------------------------------------------------------------
# Closed world
# --------------------------------------------------------------------------


def test_unlisted_types_raise() -> None:
    """A new value type must be a loud decision. Silence here is how an encoding
    acquires a second, undocumented rule."""
    for value in (object(), {1, 2}, b"bytes", 1 + 2j, range(3)):
        with pytest.raises(UnencodableValueError):
            encode_value(value)


def test_the_error_names_the_type_it_refused() -> None:
    """The whole value of failing closed is that the reader learns what to add to
    D-14's table."""
    with pytest.raises(UnencodableValueError, match="complex"):
        encode_value(1 + 2j)


def test_nested_unlisted_types_raise_too() -> None:
    """A closed world that only checks the outer type is open one level down."""
    with pytest.raises(UnencodableValueError):
        encode_value(["ok", object()])


def test_naive_datetimes_are_refused() -> None:
    """A naive datetime names no instant, so no encoding of it can be honest.

    Assuming UTC would be worse than refusing: a naive noon and an aware noon-UTC
    are *not* equal in Python, so encoding both to the same string would break
    injectivity in the silent direction.
    """
    assert datetime(2026, 8, 11, 12, 0) != datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    with pytest.raises(UnencodableValueError, match="naive"):
        encode_value(datetime(2026, 8, 11, 12, 0))


def test_non_finite_floats_are_refused() -> None:
    """JSON has no NaN or Infinity, and `float("nan") != float("nan")` makes NaN
    unencodable in principle - it is a value that is not equal to itself, so no
    injective map can place it. The schema already rejects these at construction
    (`_reject_non_finite`); this is the encoder refusing to be the hole in that."""
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(UnencodableValueError):
            encode_value(value)


# --------------------------------------------------------------------------
# The sort path
# --------------------------------------------------------------------------


def test_a_condition_grouping_key_encodes_without_repr() -> None:
    """The replacement for `repr(candidate.condition.grouping_key())`.

    A-50: D-14 banned enum `repr()` and then prescribed an ordering key that
    began with exactly that call. `grouping_key()` is a tuple of enums, floats
    and `None`, so it is precisely the shape the tuple row exists for.
    """
    key = Condition(basis=MeasurementBasis.STC, side=PowerSide.AC).grouping_key()
    encoded = encode_value(key)
    assert isinstance(encoded, list)
    assert "<" not in json.dumps(encoded)
    assert "stc" in encoded


def test_tuples_and_lists_share_an_encoding_by_design() -> None:
    """The one deliberate non-injectivity, pinned so nobody "fixes" it.

    D-14 admits `tuple` for condition grouping keys on the sort path and says
    plainly: **never for a stored value**. Lists are the opposite - `list[str]`
    is the declared type of 18 contract rows. The two domains are disjoint, so
    sharing the JSON array costs nothing, and the property D-14 states is
    injectivity over the *value* domain, which tuples are not in.

    Tagging tuples to close the gap would put a `$tuple` key into sort output for
    no gain, so this is a documented boundary rather than an oversight.
    """
    assert encode_value(("a", "b")) == encode_value(["a", "b"])


#: Everything that can appear in `CanonicalField.value`, which is typed
#: `object | None`. Injectivity is required *here*, because nothing about the
#: position tells a reader which of these types a given value is.
_POLYMORPHIC_VALUE_DOMAIN: tuple[object, ...] = (
    # primitives, including the pairs Python's `==` conflates
    None,
    True,
    False,
    0,
    1,
    22,
    22.0,
    "22",
    "",
    "stc",
    # tagged scalars: the precision pair, and both temporal types
    Decimal("22"),
    Decimal("22.0"),
    Decimal("-0.05"),
    date(2026, 8, 11),
    datetime(2026, 8, 11, 0, 0, tzinfo=UTC),
    datetime(2026, 8, 11, 12, 0, 0, 1, tzinfo=UTC),
    # enums of both bases; a member is its own primitive, so `Severity.INFORMATIONAL`
    # and `0` collide *correctly* and the pairwise check lets equal values through
    MeasurementBasis.NMOT,
    PowerSide.AC,
    Severity.INFORMATIONAL,
    Severity.CRITICAL,
    # `list[str]`, the declared type of 18 contract rows over 14 distinct keys
    [],
    ["IEC 61215"],
    ["IEC 61215", "IEC 61730"],
    ["IEC 61730", "IEC 61215"],  # order is content, not presentation: never sorted
    # the three dict-valued contract parameters, including the int/str key pair
    # that a bare JSON object would collapse
    {},
    {1: 0.5},
    {"1": 0.5},
    {3: 0.02, 5: 0.01},
    {"onan": 40.0},
    {"onan": "verified"},
    # models
    DeclaredBand(low=0.0, high=5.0, kind=ToleranceKind.ABSOLUTE, unit="W"),
    DeclaredBand(low=0.0, high=5.0, kind=ToleranceKind.RELATIVE, unit=None),
    DeclaredBand(low=-3.0, high=3.0, kind=ToleranceKind.RELATIVE, unit=None),
)

#: Types D-14 admits at fixed positions only - a frozenset is always `derived`,
#: a tuple is always a grouping key on the sort path. They encode as arrays and
#: therefore alias `list`, which is sound precisely because they never reach the
#: polymorphic slot above. See `test_fixed_position_containers_...`.
_FIXED_POSITION_DOMAIN: tuple[object, ...] = (
    frozenset(),
    frozenset({"a"}),
    frozenset({"a", "b"}),
    (),
    ("a", 1, None),
    Condition(basis=MeasurementBasis.STC, side=PowerSide.AC).grouping_key(),
)

_VALUE_DOMAIN: tuple[object, ...] = _POLYMORPHIC_VALUE_DOMAIN + _FIXED_POSITION_DOMAIN


def test_a_computed_field_is_deliberately_outside_the_encoding() -> None:
    """`_encode_model` walks `model_fields`, which excludes computed fields.

    No model has a `@computed_field` today and nothing pinned the choice either
    way, which is the whole reason to write it down: the next author to add one
    gets a value that renders in `model_dump()` and is **absent from the
    digest**, with no test objecting.

    That is the same `model_dump()`-versus-`encode_value` seam that has already
    shipped one defect - `_stored_values()` used `model_dump(mode="json")` and
    collapsed `Decimal("22.00")` against the string `"22.00"`, so two stores
    that render differently tied in the sort.

    The exclusion is *correct*: a computed field is derived from stored fields,
    so hashing it would put a function's output inside an artifact meant to be a
    function of the data. But it is correct by argument, not by accident, and it
    only stays correct while someone knows that.
    """

    class WithComputed(BaseModel):
        stated: int

        @computed_field  # type: ignore[prop-decorator]
        @property
        def derived(self) -> int:
            return self.stated * 100

    model = WithComputed(stated=7)

    assert model.model_dump() == {"stated": 7, "derived": 700}
    assert encode_value(model) == {"stated": 7}
    assert "derived" in type(model).model_computed_fields
    assert "derived" not in type(model).model_fields
