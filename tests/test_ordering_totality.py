"""`ComponentInstance.ordering_key` is a *total* order, not merely a sort key.

AC-7 wants byte-identical output from an unchanged store, and `sorted` is stable
- so a complete tie does not reorder, it leaks **arrival order**. Two instances
whose keys are equal come out in whichever order they were loaded, and the
workbook differs run to run without any value changing.

The tie-break was `surrogate_id or ""`, which yields `""` on *both* sides
whenever no surrogate has been assigned. Worse, its own docstring justified it
with the Adani case - "two Adani entities publish `ASB-M10-144-550` with
genuinely different specs (PTC 509.9 vs 518.2)" - and those specs live in
`fields`, which the key did not read. **The tie-break did not cover the scenario
it was written for**, and `test_canonical_ordering` missed it by giving both
sides a surrogate.

The fix is a final content-derived element. `test_canonical_ordering` and
`test_identity` pin what it must *not* disturb, and both still pass: the entity
split still collapses `Trina Solar` and `Trina Solar Co.,Ltd`, so the tie-break
reads stored values and never the raw supplier or model.
"""

from __future__ import annotations

import json
from decimal import Decimal
from itertools import permutations

import pytest

from procurement_agent.schema import (
    CanonicalField,
    ComponentCategory,
    ComponentInstance,
    Condition,
    MeasurementBasis,
    SourceRef,
    SourceTier,
)
from procurement_agent.schema.encoding import UnencodableValueError, encode_value
from procurement_agent.services.identity import identity_keys


def _value(value: object, *, basis: MeasurementBasis | None = None) -> CanonicalField:
    return CanonicalField(
        value=value,
        unit="Wp",
        condition=Condition(basis=basis),
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="cec-listing"),
        confidence=0.9,
    )


def _adani(ptc: float | None) -> ComponentInstance:
    """The docstring's own worked example, encoded the way the contract encodes it.

    There is no `ptc` contract key: PTC is the CEC list's power column, so it is
    `nameplate_power` under `basis=ptc` (see the Conditions table). Which is
    exactly why it lives in `fields` and not in the key.
    """
    return ComponentInstance(
        supplier="Adani",
        model="ASB-M10-144-550",
        component_category=ComponentCategory.PV_MODULES,
        nameplate=550.0,
        fields=(
            {"nameplate_power": [_value(ptc, basis=MeasurementBasis.PTC)]}
            if ptc is not None
            else {}
        ),
    )


def _adani_valued(value: object) -> ComponentInstance:
    """`_adani`, with the stored value's *type* under the caller's control.

    `_adani` takes a `float | None` because that is the shape of the worked
    example. The tiebreak's failure mode is about the type of the stored value,
    not its magnitude, so it needs a constructor that can hold a `Decimal` and a
    `str` in the same slot.
    """
    return ComponentInstance(
        supplier="Adani",
        model="ASB-M10-144-550",
        component_category=ComponentCategory.PV_MODULES,
        nameplate=550.0,
        fields={"nameplate_power": [_value(value, basis=MeasurementBasis.PTC)]},
    )


def test_the_cited_case_is_the_one_that_tied() -> None:
    """The two Adani entities the tie-break was written for. Neither has a
    surrogate - nothing has run the matcher over them yet, which is the state a
    freshly ingested store is in - so the old key ended `''` on both sides."""
    a, b = _adani(509.9), _adani(518.2)
    assert a.ordering_key() != b.ordering_key(), (
        "the two instances the tie-break exists for still sort equal"
    )


def test_the_order_does_not_depend_on_arrival_order() -> None:
    """The property, stated as the property rather than as an inequality of keys.

    `sorted` is stable, so a tie is invisible in a single sort - it only shows up
    as a *different* sort from a different input order. Both permutations are
    tried, which is what a stable sort makes necessary.

    The comparison is over what each row *says*, not over its key: collecting
    `ordering_key()` here would compare two ties against each other and pass for
    any key at all, including the broken one. It did, on the first draft of this
    test - the `assert f(x) == f(x)` shape `test_canonical_ordering` records one
    file over.
    """
    a, b = _adani(509.9), _adani(518.2)
    rows = {
        tuple(
            instance.fields["nameplate_power"][0].value
            for instance in sorted(pair, key=ComponentInstance.ordering_key)
        )
        for pair in permutations([a, b])
    }
    assert len(rows) == 1, f"two arrival orders produced two workbook row orders: {rows}"


def test_the_tiebreak_is_content_derived_and_not_identity() -> None:
    """`id()`, a counter or an insertion index would all break the tie and all
    fail here: two separately constructed instances holding the same values are
    the same row and must key identically, or re-ingesting a document reorders
    the workbook."""
    assert _adani(509.9).ordering_key() == _adani(509.9).ordering_key()
    assert _adani(None).ordering_key() == _adani(None).ordering_key()


def test_two_indistinguishable_instances_still_tie_and_that_is_correct() -> None:
    """The order is total *up to equality*, which is the strongest thing
    available and the only thing AC-7 needs. Two instances agreeing on category,
    identity, nameplate, surrogate and every stored value produce identical rows,
    so their relative order cannot be observed in the output at all."""
    assert _adani(509.9).ordering_key() == _adani(509.9).ordering_key()


def test_the_tiebreak_does_not_reopen_the_entity_split() -> None:
    """D-4 stage 1 exists so `Trina Solar` and `Trina Solar Co.,Ltd` sort
    together. A tie-break that *sorted on* the raw supplier or model - the
    obvious way to make a key unique - would undo that silently.

    **The raw strings are now in the key, and this test is what makes that
    safe.** It asserted complete key equality, which was too strong in the
    precise way that was the defect: `projection._component_row` emits the raw
    supplier, so two spellings tied on every element and rendered different
    rows, and `sorted`'s stability handed the bytes to arrival order. The raw
    strings are now the *last* two elements, so they separate only rows that
    agree on everything the split governs.

    What this checks is therefore position, not equality: the first six elements
    still agree, and a different manufacturer cannot sort between the two
    spellings. Both would fail if the raw strings moved earlier in the tuple.
    `test_identity.test_two_entity_spellings_sort_together` pins the same
    invariant from the other side.
    """

    def built(supplier: str, model: str = "TSM-700NEG21C.20") -> ComponentInstance:
        keys = identity_keys(supplier, model, 700.0)
        return ComponentInstance(
            supplier=supplier,
            model=model,
            component_category=ComponentCategory.PV_MODULES,
            nameplate=700.0,
            manufacturer_key=keys.manufacturer_key,
            model_family=keys.model_family,
            surrogate_id=keys.surrogate_id,
            fields={"nameplate_power": [_value(700.0)]},
        )

    short, long = built("Trina Solar"), built("Trina Solar Co.,Ltd")
    assert short.ordering_key()[:6] == long.ordering_key()[:6]

    other = built("Jinko Solar", "JKM610N-66HL4M-V")
    ordered = sorted([other, long, short], key=ComponentInstance.ordering_key)
    positions = [i for i, c in enumerate(ordered) if c.supplier.startswith("Trina")]
    assert positions in ([0, 1], [1, 2]), (
        f"the entity split reopened: {[c.supplier for c in ordered]}"
    )


def test_a_dict_valued_field_orders_by_content_not_insertion_order() -> None:
    """The contract has three dict-valued parameters, and a dict iterates in
    insertion order - so two extractions that read one cooling table's rows in
    different orders hold equal values and would key differently under `repr`.
    `services.claims._render` records the same hazard for claim identity; this is
    the sort-key half of it."""

    def transformer(rating: dict[str, float]) -> ComponentInstance:
        return ComponentInstance(
            supplier="Siemens Energy",
            model="TR-100",
            component_category=ComponentCategory.TRANSFORMERS,
            fields={"rating_mva_by_cooling": [_value(rating)]},
        )

    forwards = transformer({"ONAN": 30.0, "ONAF": 40.0})
    backwards = transformer({"ONAF": 40.0, "ONAN": 30.0})
    assert forwards.ordering_key() == backwards.ordering_key()


def test_the_stored_values_are_actually_read() -> None:
    """A tie-break that returned a constant would satisfy every equality above.
    Two instances differing *only* in a stored value must differ in the key."""
    empty = _adani(None)
    populated = _adani(509.9)
    assert empty.ordering_key()[:5] == populated.ordering_key()[:5], (
        "the first five elements must be what they always were"
    )
    assert empty.ordering_key() != populated.ordering_key()


def test_the_key_is_in_memory_only_and_says_so() -> None:
    """The documented limit, pinned so it is a decision rather than a surprise.

    An absent nameplate becomes `float('-inf')`, which is totally ordered and
    **not encodable**: `encode_value` refuses non-finite floats because no
    injective encoding of them exists. So the key can order rows and can never
    itself be projected or hashed - anything wanting a canonical byte form of a
    row must build it from the instance, not from this tuple.
    """
    key = ComponentInstance(
        supplier="Adani",
        model="ASB-M10-144-550",
        component_category=ComponentCategory.PV_MODULES,
    ).ordering_key()
    assert key[3] == float("-inf")
    with pytest.raises(UnencodableValueError, match="non-finite"):
        encode_value(list(key))


def test_the_tiebreak_routes_through_the_one_encoding_authority() -> None:
    """Not a second canonical form invented for the sort.

    This replaces a test that recomputed `model_dump(mode="json")` and asserted
    the key equalled it - which is `assert f(x) == f(x)`, true of any
    implementation including the wrong one it was guarding. It passed against
    exactly the defect described below.
    """
    instance = _adani(509.9)
    assert instance.ordering_key()[5] == json.dumps(
        encode_value(instance.fields), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def test_two_instances_differing_only_in_value_type_do_not_tie() -> None:
    """Why the tiebreak may not use `model_dump(mode="json")`.

    `CanonicalField.value` is `object | None` - the polymorphic slot
    `schema/encoding.py` exists for. Pydantic's JSON mode collapses it:
    `Decimal("22.00")` and the string `"22.00"` dump to the same text. The
    projection does *not* collapse them, because it routes values through
    `encode_value` and renders `{"$decimal": "22.00"}` against `"22.00"`.

    So under the old tiebreak these two instances tied while rendering different
    rows, and `sorted`'s stability handed their relative order to arrival order -
    the A-6 class in its mirror form: two artifacts that differ in content, whose
    byte position is not a function of content. This is the case the previous
    test could not see.
    """
    decimal_valued, string_valued = _adani_valued(Decimal("22.00")), _adani_valued("22.00")

    # equal under the encoder pydantic would have used...
    assert decimal_valued.fields["nameplate_power"][0].model_dump(
        mode="json"
    ) == string_valued.fields["nameplate_power"][0].model_dump(mode="json")

    # ...and distinct under the one the projection actually renders with
    assert decimal_valued.ordering_key() != string_valued.ordering_key()
    assert decimal_valued.ordering_key()[:5] == string_valued.ordering_key()[:5]
