"""A total order over component instances, required by AC-7.

Byte-identical regeneration needs deterministic row order. clarifications.md D-4
stage 5. The tie-break exists because (category, supplier, model) is provably not
unique on real CEC data.
"""

from procurement_agent.schema import ComponentCategory, ComponentInstance


def _instance(**kwargs: object) -> ComponentInstance:
    defaults: dict[str, object] = {
        "supplier": "Trina Solar",
        "model": "TSM-NEG21C.20",
        "component_category": ComponentCategory.PV_MODULES,
    }
    return ComponentInstance(**(defaults | kwargs))  # type: ignore[arg-type]


def test_ordering_is_stable_across_runs() -> None:
    """Pinned to a literal, not to a second evaluation of the same expression.

    `first == second` where both sides compute `i.ordering_key()` is
    `assert f(x) == f(x)`: it holds for any deterministic function, including a
    constant, so it passed with `ordering_key` replaced by a fixed tuple."""
    items = [
        _instance(nameplate=720.0),
        _instance(nameplate=695.0),
        _instance(nameplate=705.0),
    ]
    keys = [i.ordering_key() for i in sorted(items, key=ComponentInstance.ordering_key)]
    assert len(set(keys)) == 3, "a constant key would collapse three instances to one"
    assert keys == sorted(keys)
    assert [k[3] for k in keys] == [695.0, 705.0, 720.0]


def test_bins_sort_by_nameplate() -> None:
    """One datasheet covers many bins; they must not interleave arbitrarily."""
    items = [_instance(nameplate=n) for n in (720.0, 695.0, 705.0)]
    ordered = sorted(items, key=ComponentInstance.ordering_key)
    assert [i.nameplate for i in ordered] == [695.0, 705.0, 720.0]


def test_identical_supplier_and_model_are_disambiguated_by_surrogate() -> None:
    """The Adani case: two entities publish `ASB-M10-144-550` with different specs.

    Without the surrogate tie-break these two sort equal, and their relative order
    would depend on input order - which breaks AC-7.
    """
    a = _instance(supplier="Adani", model="ASB-M10-144-550", nameplate=550.0, surrogate_id="aaa")
    b = _instance(supplier="Adani", model="ASB-M10-144-550", nameplate=550.0, surrogate_id="bbb")
    assert a.ordering_key() != b.ordering_key()
    assert sorted([b, a], key=ComponentInstance.ordering_key) == [a, b]


def test_missing_nameplate_sorts_first_and_does_not_raise() -> None:
    """Nameplate is often absent early in extraction. It must still order."""
    known = _instance(nameplate=695.0)
    unknown = _instance(nameplate=None)
    ordered = sorted([known, unknown], key=ComponentInstance.ordering_key)
    assert ordered[0] is unknown


def test_category_dominates_the_sort() -> None:
    """Category tabs are written in workbook order; instances must group by tab."""
    pv = _instance(component_category=ComponentCategory.PV_MODULES)
    bess = _instance(component_category=ComponentCategory.BESS)
    ordered = sorted([pv, bess], key=ComponentInstance.ordering_key)
    assert ordered[0].component_category is ComponentCategory.BESS
    assert ordered[0].ordering_key()[0] < ordered[1].ordering_key()[0]
