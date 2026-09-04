"""A canonical form must be a function of the thing it is a canonical form *of*.

Four defects, one shape. Each was individually correct against its own docstring;
what nothing checked was the *relation* between a key and the row it orders, or
between a normalisation rule and every member of the type it governs. All four
survived 823 tests, and all four break AC-7 - two generations from an unchanged
store are byte-identical.

**A sort key narrower than its row.** `sorted` is stable, so a tie does not
reorder: it hands the order to arrival order, and the bytes move with no value
changing. `_value_sort_key` read nine components while `_field_row` emitted ten
(`conflict_status` and `resolution` were missing), and `ordering_key()`
deliberately excludes the raw `supplier`/`model` that `_component_row` emits.

**A normalisation applied to some members of a type and missed on others.**
`-0.0 == 0.0` and the two hash alike, so every equality the codebase has calls
two such stores identical - while their SHA-256s differ. The repo folds `-0.0` in
three places and missed the two `confidence` slots, where `ge=0.0` admits it
because `-0.0 >= 0.0` is True.

**A closed world with one door left open.** `encode_value` refuses non-finite
floats because "NaN is not equal to itself, so no injective encoding of it
exists"; the `$decimal` branch had no such guard, so `Decimal("NaN")` was the
hole the float rule exists to close.

The tripwire in `test_every_field_row_key_is_discriminated_by_the_sort_key` is
the durable half: it fails when a *new* key joins the row, so the next author has
to decide whether the sort key covers it rather than finding out from a hash that
moved.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from procurement_agent.schema import (
    CanonicalField,
    ComponentCategory,
    ComponentInstance,
    Condition,
    ConflictCandidate,
    ConflictStatus,
    DeclaredBand,
    Resolution,
    ResolutionAction,
    SourceRef,
    SourceTier,
    ToleranceKind,
    UnresolvedStatus,
)
from procurement_agent.schema.encoding import UnencodableValueError, encode_value
from procurement_agent.services.output.projection import (
    ProjectionPolicy,
    _component_row,
    _field_row,
    _value_sort_key,
    project_store,
    projection_digest,
)

POLICY = ProjectionPolicy(confidence_threshold=0.7, policy_version="v1")

RESOLUTION = Resolution(
    action=ResolutionAction.KEEP_SYSTEM_OF_RECORD,
    resolved_by="reviewer@example.test",
    resolved_at=datetime(2026, 1, 1, tzinfo=UTC),
    rationale="the contract value stands",
)


def _field(
    *,
    value: object = 550.0,
    confidence: float = 0.9,
    conflict_status: ConflictStatus = ConflictStatus.NONE,
    resolution: Resolution | None = None,
) -> CanonicalField:
    return CanonicalField(
        value=value,
        unit="W",
        condition=Condition(),
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="doc-1"),
        confidence=confidence,
        unresolved_status=(
            UnresolvedStatus.NONE
            if conflict_status is ConflictStatus.RESOLVED
            else UnresolvedStatus(conflict_status.value)
        ),
        resolution=resolution,
    )


def _instance(
    fields: list[CanonicalField],
    *,
    supplier: str = "Adani Solar",
    model: str = "ASB-M10-144-550",
    manufacturer_key: str | None = "adani",
    model_family: str | None = "ASB-M10-144",
    surrogate_id: str | None = None,
) -> ComponentInstance:
    """Every field `_component_row` emits is settable.

    The first version of this helper hardcoded `manufacturer_key` and
    `model_family` and never took `surrogate_id`, which made the three fallback
    branches of `ordering_key()` - `manufacturer_key or supplier`, and its two
    siblings - **unreachable from the file written to cover them**. Section 1
    below was verified structurally by a tripwire and section 2 only by example,
    so the gap survived. The same accident as the old twin test giving its two
    instances `page=1` and `page=2`, which is why they never actually tied.
    """
    return ComponentInstance(
        supplier=supplier,
        model=model,
        component_category=ComponentCategory.PV_MODULES,
        nameplate=550.0,
        manufacturer_key=manufacturer_key,
        model_family=model_family,
        surrogate_id=surrogate_id,
        fields={"nameplate_power": fields},
    )


def _digest(components: list[ComponentInstance]) -> str:
    return projection_digest(
        project_store(components=components, conflicts=[], sources=[], policy=POLICY)
    )


# --------------------------------------------------------------------------
# 1. `_value_sort_key` must discriminate everything `_field_row` emits
# --------------------------------------------------------------------------


def test_two_values_differing_only_in_conflict_status_do_not_tie() -> None:
    """`conflict_status` was emitted by the row and absent from the key.

    The rows do not merely reorder - they render different `flags`, because
    `flags_for` reads the status. So the artifact differs in content while its
    byte order is decided by whichever value the store happened to yield first.
    """
    clean = _field(conflict_status=ConflictStatus.NONE)
    open_ = _field(conflict_status=ConflictStatus.OPEN)

    assert clean != open_
    assert _value_sort_key(clean) != _value_sort_key(open_)


def test_two_values_differing_only_in_resolution_do_not_tie() -> None:
    """The other half of the same gap. A resolved value and an unresolved one
    are different rows - and FR-HITL-06 makes the resolution the audited half."""
    unresolved = _field()
    resolved = _field(conflict_status=ConflictStatus.RESOLVED, resolution=RESOLUTION)

    assert _value_sort_key(unresolved) != _value_sort_key(resolved)


def test_arrival_order_of_two_values_cannot_reach_the_digest() -> None:
    """The property, stated as the property rather than as an inequality of keys.

    A tie is invisible in a single sort - it shows up only as a *different* sort
    from a different input order, which is why both permutations are built.
    """
    clean = _field(conflict_status=ConflictStatus.NONE)
    open_ = _field(conflict_status=ConflictStatus.OPEN)

    assert _digest([_instance([clean, open_])]) == _digest([_instance([open_, clean])])


def test_every_field_row_key_is_discriminated_by_the_sort_key() -> None:
    """The tripwire, and the durable half of this file.

    Pins the exact key set `_field_row` emits. Adding a key to the row fails
    here, which forces the author to decide whether `_value_sort_key` covers it -
    rather than discovering it later from a hash that moved with no data change.

    `flags` is deliberately not a separate concern: `flags_for` is a pure
    function of `value`, `confidence`, `conflict_status` and `source_tier`, every
    one of which the key now reads.

    `store_written_at` is the reserved slot `_store_row` stamps, and
    `_field_row` passes it `None` unconditionally - `CanonicalField` carries no
    store write timestamp. A constant discriminates nothing, so the key does not
    read it. **If it ever becomes reachable it must join the key**, and this
    tripwire will not say so on its own, because the key set does not change when
    a constant becomes a variable.
    """
    emitted = set(_field_row(_field(), policy=POLICY))
    assert emitted == {
        "value",
        "unit",
        "verbatim_value",
        "condition",
        "source_tier",
        "source_ref",
        "confidence",
        "conflict_status",
        "resolution",
        "flags",
        "store_written_at",
    }, "a key joined `_field_row`; decide whether `_value_sort_key` must read it"
    assert _field_row(_field(), policy=POLICY)["store_written_at"] is None, (
        "store_written_at is no longer a constant; it must now join _value_sort_key"
    )


# --------------------------------------------------------------------------
# 2. `ordering_key()` must discriminate everything `_component_row` emits
# --------------------------------------------------------------------------


def test_two_entity_spellings_sharing_a_manufacturer_key_do_not_tie() -> None:
    """D-4 stage 1 folds `Adani Solar` and `Adani Green` onto one
    `manufacturer_key`, and `ordering_key()` reads the normalised key so the
    entity split is not reopened in the row order. But `_component_row` emits the
    **raw** supplier, so the two rows differ while the key tied completely.

    This is the case `ordering_key()`'s own docstring is written around, in the
    `surrogate_id is None` state it names as the dangerous one - freshly
    ingested, before the matcher has run.
    """
    a = _instance([_field()], supplier="Adani Solar")
    b = _instance([_field()], supplier="Adani Green")

    assert a != b
    assert a.ordering_key() != b.ordering_key()


def test_two_models_sharing_a_family_do_not_tie() -> None:
    """The `model_family` half of the same gap."""
    a = _instance([_field()], model="ASB-M10-144-550A")
    b = _instance([_field()], model="ASB-M10-144-550B")

    assert a.ordering_key() != b.ordering_key()


def test_arrival_order_of_two_components_cannot_reach_the_digest() -> None:
    a = _instance([_field()], supplier="Adani Solar")
    b = _instance([_field()], supplier="Adani Green")

    assert _digest([a, b]) == _digest([b, a])


@pytest.mark.parametrize(
    ("field_name", "absent", "present"),
    [
        ("manufacturer_key", None, "Adani Solar"),
        ("model_family", None, "ASB-M10-144-550"),
        ("surrogate_id", None, ""),
    ],
)
def test_a_fallback_operator_does_not_collapse_a_field_the_row_emits(
    field_name: str, absent: str | None, present: str | None
) -> None:
    """The residual the first version of this fix left behind.

    Three elements of `ordering_key()` are written `x or y`:

        manufacturer_key or supplier
        model_family     or model
        surrogate_id     or ""

    Each `or` collapses an *absent* value into another field's value, while
    `_component_row` emits all three raw and unfolded. So adding the raw
    `supplier`/`model` closed the two missing fields and left the three lossy
    *operators* - 3 of 7 emitted identity fields still undiscriminated.

    `manufacturer_key` is naturally reachable rather than contrived:
    `identity_keys("sungrow", ...).manufacturer_key == "sungrow"`, so any
    supplier already in normalised form makes the fallback and the value equal,
    and a partially-normalised store - the state `ordering_key`'s docstring says
    must be supported - ties.
    """
    a = _instance([_field()], **{field_name: absent})  # type: ignore[arg-type]
    b = _instance([_field()], **{field_name: present})  # type: ignore[arg-type]

    assert a != b
    assert a.ordering_key() != b.ordering_key()
    assert _digest([a, b]) == _digest([b, a])


def test_every_component_row_key_is_discriminated_by_the_ordering_key() -> None:
    """Section 2's tripwire, missing from the first version of this file.

    Section 1 got one and section 2 did not, which is exactly why the three
    fallback operators survived: a structural check catches a *class* of gap,
    an example catches the instance you thought of. Adding a key to
    `_component_row` now fails here.

    `fields` is covered through `_stored_values()`, and `component_category`,
    `nameplate` and `store_written_at` are read directly; the remaining five are
    the identity strings the final canonical element covers.
    """
    emitted = set(_component_row(_instance([_field()]), policy=POLICY))
    assert emitted == {
        "supplier",
        "model",
        "component_category",
        "nameplate",
        "surrogate_id",
        "manufacturer_key",
        "model_family",
        "fields",
        "store_written_at",
    }, "a key joined `_component_row`; decide whether `ordering_key()` must read it"


def test_the_entity_split_still_governs_the_primary_order() -> None:
    """The raw strings are a *final* tie-break, not a sort dimension.

    `test_the_tiebreak_does_not_reopen_the_entity_split` pins the same invariant
    from the other side. Two spellings of one manufacturer must still sort
    adjacently - between them and a different manufacturer, the normalised key
    decides, not the raw string. `Zenith` sorts after both raw spellings and
    before neither once normalised.
    """
    adani_a = _instance([_field()], supplier="Adani Solar")
    adani_b = _instance([_field()], supplier="Adani Green")
    other = _instance([_field()], supplier="Zenith", manufacturer_key="zenith")

    ordered = sorted([other, adani_b, adani_a], key=ComponentInstance.ordering_key)
    assert [c.manufacturer_key for c in ordered] == ["adani", "adani", "zenith"]


# --------------------------------------------------------------------------
# 3. `-0.0` must be folded in every float that reaches the bytes
# --------------------------------------------------------------------------


def test_negative_zero_confidence_is_folded_on_both_models() -> None:
    """`-0.0 >= 0.0` is True, so `ge=0.0` admits it, and `-0.0 == 0.0` with equal
    hashes - so every equality the codebase has calls the two identical while
    `json.dumps` writes `-0.0` and moves the digest.

    Both models, because the defect is the type and not the file:
    `CanonicalField.confidence` reaches the C6 projection as a bare float, and
    `ConflictCandidate.confidence` is an element `conflict_hitl._ordering_key`
    sorts on.
    """
    assert repr(_field(confidence=-0.0).confidence) == "0.0"

    candidate = ConflictCandidate(
        value=550.0,
        unit="W",
        condition=Condition(),
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="doc-1"),
        confidence=-0.0,
    )
    assert repr(candidate.confidence) == "0.0"


def test_two_stores_differing_only_by_a_signed_zero_hash_alike() -> None:
    """A-6 stated literally: two artifacts that are equal under every equality
    the codebase has, with different SHA-256s."""
    positive = _instance([_field(confidence=0.0)])
    negative = _instance([_field(confidence=-0.0)])

    assert positive == negative
    assert _digest([positive]) == _digest([negative])


def test_the_two_older_negative_zero_folds_are_pinned_structurally() -> None:
    """Found by mutating the fix, not by writing it.

    `DeclaredBand.low/high` and `ConditionDimensions` have folded `-0.0` since
    long before this file, and **reverting either left all 841 tests green.**
    The test that looks like it covers one of them is
    `test_condition_grouping.test_tap_position_is_a_number_so_spelling_cannot_split_it`:

        Condition(tap_position_pct=0.0).grouping_key()
            == Condition(tap_position_pct=-0.0).grouping_key()

    `-0.0 == 0.0`, so that tuple equality holds *whether or not the fold
    happens* - `assert f(x) == f(x)` wearing a disguise, and the same blind spot
    that let a raw `StrEnum` leak through an encoder's equality assertions.

    A signed zero is only visible structurally. `math.copysign` is the check;
    `==` never will be.
    """
    band = DeclaredBand(low=-0.0, high=1.0, kind=ToleranceKind.ABSOLUTE, unit="W")
    assert math.copysign(1.0, band.low) == 1.0

    # NOT `... or 0.0`: `-0.0` is falsy, so the fallback would swallow exactly
    # the value under test and the assertion would hold against any
    # implementation. This mutation survived until the guard was written this
    # way - the third variant of the same blind spot in one test file.
    tap = Condition(tap_position_pct=-0.0).tap_position_pct
    assert tap is not None
    assert math.copysign(1.0, tap) == 1.0


def test_negative_zero_in_the_polymorphic_value_slot_is_folded() -> None:
    """`CanonicalField.value` is `object | None` - the slot `encoding.py` exists
    for - and it reaches the bytes and the sort position alike."""
    positive = _instance([_field(value=0.0)])
    negative = _instance([_field(value=-0.0)])

    assert _digest([positive]) == _digest([negative])


# --------------------------------------------------------------------------
# 4. The `$decimal` branch must be as closed as the `float` branch
# --------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["NaN", "-NaN", "sNaN", "Infinity", "-Infinity"])
def test_non_finite_decimals_are_refused(text: str) -> None:
    """The `float` branch refuses these because "no injective encoding of NaN
    exists - this is the encoder refusing to be the hole in that". The `$decimal`
    branch *was* that hole: `Decimal("NaN")` encoded to stable bytes despite not
    being equal to itself, and `Decimal("Infinity")` was accepted where
    `float("inf")` is refused - the same mathematical value, opposite answers."""
    with pytest.raises(UnencodableValueError, match="non-finite"):
        encode_value(Decimal(text))


def test_two_nan_decimals_no_longer_share_one_encoding() -> None:
    """The mirror form: two values that are *not equal* had one byte string.

    Driven through the polymorphic slot rather than through `encode_value`
    directly, because `CanonicalField.value` is where a `Decimal` actually
    arrives and where injectivity is required.

    **The slot now refuses it outright**, which is what `encode_value`'s error
    message always claimed ("The schema rejects these at construction") and did
    not do. So the case is asserted at both layers: the store cannot take the
    value, and the encoder is still the backstop for a field that reached the
    state by a route that skips field validation - `model_construct` is the one
    the class docstring enumerates, and it is exactly how a row read back from
    a store arrives.
    """
    assert Decimal("NaN") != Decimal("NaN")
    with pytest.raises(ValidationError):
        _field(value=Decimal("NaN"))

    def bypassed() -> CanonicalField:
        return CanonicalField.model_construct(
            value=Decimal("NaN"),
            unit="W",
            condition=Condition(),
            source_tier=SourceTier.SYSTEM_OF_RECORD,
            source_ref=SourceRef(document_id="doc-1"),
            confidence=0.9,
            conflict_status=ConflictStatus.NONE,
            resolution=None,
        )

    # Two calls, so the two `Decimal("NaN")`s are distinct objects: dict equality
    # takes an identity fast path, so comparing one field against a rebuild of
    # its own `__dict__` would report equal for a reason that has nothing to do
    # with NaN.
    assert bypassed() != bypassed()
    with pytest.raises(UnencodableValueError, match="non-finite"):
        encode_value(bypassed())


def test_finite_decimals_still_encode_and_keep_their_printed_precision() -> None:
    """The guard must not touch the case D-2's rounding floor depends on:
    `_decimals` reads `str(value)`, so the trailing zero decides whether a human
    is asked to review. `normalize()` stays banned."""
    assert encode_value(Decimal("22.00")) == {"$decimal": "22.00"}
    assert encode_value(Decimal("22")) == {"$decimal": "22"}


def test_signed_zero_decimals_share_an_encoding() -> None:
    """Same injectivity hole the float branch already closed with `+ 0.0`.

    `Decimal("-0.0") == Decimal("0.0")` and the two hash alike, so they are one
    value; `str()` still writes two spellings and C6 forks. Precision of a
    *non-zero* trailing zero is data (`22.00` vs `22`); the sign of zero is not.
    """
    assert Decimal("-0.0") == Decimal("0.0")
    assert encode_value(Decimal("-0.0")) == encode_value(Decimal("0.0"))
    assert encode_value(Decimal("-0.0")) == {"$decimal": "0.0"}
    assert encode_value(Decimal("-0.00")) == {"$decimal": "0.00"}
