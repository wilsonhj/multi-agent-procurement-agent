"""Contract C2 made machine-readable, and the two boundaries that enforce it.

The registry is checked against `contracts/canonical-parameters.md` in **both**
directions, the way `test_condition_grouping` checks the Conditions table. One
direction alone is not enough and the repo has paid for that twice: the tier
table was checked for invented keys only, so `ul_listing` was missing from it and
auto-accepted at 0.99; `MeasurementBasis.SAT` existed in the enum and in no row
of the contract. A subset check catches a typo. It cannot catch an omission.

The comparison is per **row**, not per key. `insulation_type` appears under
transformers with `enum: oil, dry` and under cabling with none, so a key-set
comparison would call the registry correct while it admitted `XLPE` for a
transformer. Rows carry the category, the type, the unit and the enum, and all
four are compared.
"""

from __future__ import annotations

import json
import pathlib
import re
from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from procurement_agent.schema import (
    CanonicalField,
    ComponentCategory,
    ComponentInstance,
    SourceRef,
    SourceTier,
    ToleranceRule,
)
from procurement_agent.schema.registry import (
    CONTRACT_KEYS,
    CONTRACT_UNIT_AMBIGUITIES,
    FIELD_SPECS,
    FieldScope,
    FieldSpec,
    OffContractFieldError,
    Shape,
    ValueType,
    is_contract_key,
    keys_for,
    require_contract_key,
    spec_for,
)
from procurement_agent.services.claims import FieldClaim, ProposalError, commit_claims
from procurement_agent.services.confidence import FIELD_TIERS, CriticalityTier
from procurement_agent.services.conflict_hitl.tolerance import (
    FIELD_TOLERANCES,
    NEVER_COMPARABLE,
    FieldTolerance,
)

CONTRACT = pathlib.Path(__file__).parent.parent / (
    "specs/001-procurement-agent/contracts/canonical-parameters.md"
)

#: `(scope, key, contract type, unit, enum)` - one tuple per table row.
#:
#: `scope` is the category slug for sections 1-8 and the sentinel for the two
#: cross-cutting tables, so a row moving between sections is a difference rather
#: than a no-op.
Row = tuple[str, str, str, str | None, frozenset[str] | None]


def _enum_in(notes: str) -> frozenset[str] | None:
    """The closed vocabulary a notes cell declares, if it declares one.

    Stops at the em dash: `baba_status` writes its four members and then a
    sentence beginning "`not_applicable` when the project is privately financed",
    and a greedy read makes that trailing mention look like a fifth member.

    `filtering_provisions` writes "enum **members**:" because it is `list[str]` -
    the vocabulary constrains the elements, not the value - so both spellings are
    accepted here and the shape is what says which one applies.
    """
    match = re.search(r"enum(?: members)?:\s*([^—]*)", notes)
    if match is None:
        return None
    return frozenset(re.findall(r"`([a-z0-9_]+)`", match.group(1)))


def _contract_rows() -> set[Row]:
    """Every parameter row of the frozen contract, parsed from the markdown.

    Deliberately a second parser rather than an import of the registry's own: a
    test that reads its expectation through the code under test asserts
    `f(x) == f(x)` and passes for any `f`, including a constant.

    A parameter row is one whose first cell is a backticked snake_case key, which
    is what separates it from the Conditions table (first cell a family name) and
    the Declared bands table (first cell a convention name).
    """
    text = CONTRACT.read_text(encoding="utf-8")
    row_re = re.compile(r"^\|\s*`([a-z0-9_]+)`\s*\|(.*)$")
    rows: set[Row] = set()
    section: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            category = re.search(r"`([a-z_]+)`\s*$", heading)
            if category:
                section = category.group(1)
            elif heading == "Cross-category fields":
                section = FieldScope.CROSS_CATEGORY.value
            elif heading == "Compliance and tax fields":
                section = FieldScope.COMPLIANCE.value
            else:
                section = None
            continue
        match = row_re.match(line.strip())
        if section is None or match is None:
            continue
        cells = [cell.strip() for cell in match.group(2).split("|")]
        if section in (FieldScope.CROSS_CATEGORY.value, FieldScope.COMPLIANCE.value):
            # Neither cross-cutting table has a `canonical unit` column, so the
            # notes are cells[1] and there is no unit to read. See
            # CONTRACT_UNIT_AMBIGUITIES for the two rows that print one anyway.
            declared_type, unit, notes = cells[0], None, cells[1]
        else:
            declared_type, notes = cells[0], cells[2]
            unit = None if cells[1] == "—" else cells[1].strip("`")
        rows.add((section, match.group(1), declared_type, unit, _enum_in(notes)))
    return rows


def _registry_rows() -> set[Row]:
    """The registry expanded to one tuple per contract row.

    A spec carries every category admitting it, because `warranty_years` is one
    field on four categories rather than four fields. Expanding here is what makes
    the comparison row-for-row against a document that repeats it.
    """
    rows: set[Row] = set()
    for spec in FIELD_SPECS:
        if spec.scope is FieldScope.CATEGORY:
            for category in spec.categories:
                rows.add((category.value, spec.key, spec.contract_type, spec.unit, spec.enum))
        else:
            rows.add((spec.scope.value, spec.key, spec.contract_type, spec.unit, spec.enum))
    return rows


# --- the parse itself, before anything is compared through it -------------------


def test_the_contract_parse_is_not_vacuous() -> None:
    """Every check below is `set == set`, which a parser returning nothing
    satisfies against a registry that also returns nothing - the vacuous-pass
    shape this repo has recorded three times. The counts are the contract's own:
    eight category sections plus two cross-cutting tables, 134 rows over 124
    distinct keys, 18 of those rows declared `list[str]`.
    """
    rows = _contract_rows()
    assert len(rows) == 134, "the contract's parameter tables did not parse as expected"
    assert len({row[0] for row in rows}) == 10
    assert len({row[1] for row in rows}) == 124
    assert sum(1 for row in rows if row[2] == "list[str]") == 18
    assert sum(1 for row in rows if row[4]) == 11, "the enum rows did not parse"


# --- the registry against the contract, in both directions ----------------------


def test_no_contract_row_is_missing_from_the_registry() -> None:
    """The direction an extractor feels. A parameter the contract defines and the
    registry lacks is a key both boundaries reject, so an extractor doing exactly
    what the contract says has its claim refused."""
    missing = _contract_rows() - _registry_rows()
    assert not missing, f"contract rows with no FieldSpec: {sorted(missing)}"


def test_no_registry_row_is_invented() -> None:
    """The reverse, which the check above cannot see: a spec nobody wrote into the
    contract admits a key the contract does not define, and by this repo's own
    rule the contract is what governs. `MeasurementBasis.SAT` shipped in exactly
    that state one module over - in the enum, in no row of the table."""
    invented = _registry_rows() - _contract_rows()
    assert not invented, f"FieldSpecs the frozen contract does not have: {sorted(invented)}"


def test_the_unit_ambiguity_is_recorded_rather_than_conformed_away() -> None:
    """The contract is the source of truth, so a disagreement is reported rather
    than quietly fixed in the code. Two compliance rows print a unit in a table
    that has no unit column; the registry follows the column that exists (there is
    none) and names the two rows here instead of inventing the column."""
    assert set(CONTRACT_UNIT_AMBIGUITIES) == {
        "domestic_content_percentage",
        "material_assistance_cost_ratio",
    }
    for key, why in CONTRACT_UNIT_AMBIGUITIES.items():
        spec = spec_for(key, ComponentCategory.BESS)
        assert spec is not None and spec.unit is None
        assert spec.scope is FieldScope.COMPLIANCE
        assert len(why) > 40, f"{key} has no stated reason"


# --- what the registry models that a key set cannot -----------------------------


def test_the_eighteen_list_valued_rows_are_modelled_as_lists() -> None:
    """The contract declares `list[str]` on 18 rows and its preamble makes the
    distinction material: an empty list means "we looked and found none stated",
    which is not `None` meaning "we have not established this". A registry that
    flattened every type to `str` would erase the difference the preamble spends a
    paragraph on."""
    listed = [
        (spec, category)
        for spec in FIELD_SPECS
        if spec.shape is Shape.LIST
        for category in (spec.categories if spec.scope is FieldScope.CATEGORY else [None])
    ]
    assert len(listed) == 18
    assert {spec.value_type for spec, _ in listed} == {ValueType.STR}
    assert all(spec.contract_type == "list[str]" for spec, _ in listed)


def test_a_map_row_keeps_both_of_its_types() -> None:
    """`harmonic_spectrum` is `dict[int, float]` - harmonic order to magnitude -
    and `ercot_compliance_items` is `dict[str, str]`. Collapsing the key type
    would make those two the same shape, and the workbook projection reads the
    order back as a number."""
    spectrum = spec_for("harmonic_spectrum", ComponentCategory.INVERTERS_PCS)
    assert spectrum is not None
    assert (spectrum.shape, spectrum.map_key_type, spectrum.value_type) == (
        Shape.MAP,
        ValueType.INT,
        ValueType.FLOAT,
    )
    assert spectrum.contract_type == "dict[int, float]"


def test_a_map_spec_cannot_omit_its_key_type() -> None:
    """The invariant behind the check above, enforced where it cannot be
    forgotten. A `dict[?, float]` is not a type."""
    with pytest.raises(ValidationError):
        FieldSpec(
            key="harmonic_spectrum",
            shape=Shape.MAP,
            value_type=ValueType.FLOAT,
            categories=frozenset({ComponentCategory.INVERTERS_PCS}),
            scope=FieldScope.CATEGORY,
        )


def test_no_two_specs_claim_one_key_for_one_category() -> None:
    """The index `spec_for` reads is a dict, so a duplicate would silently resolve
    to whichever spec was written last - and with `insulation_type` deliberately
    declared twice, "last wins" is a live hazard rather than a hypothetical."""
    seen: set[tuple[str, str]] = set()
    for spec in FIELD_SPECS:
        for category in spec.categories:
            assert (category.value, spec.key) not in seen, (
                f"{spec.key} is declared twice for {category.value}"
            )
            seen.add((category.value, spec.key))


def test_one_key_can_mean_two_things_in_two_categories() -> None:
    """`insulation_type` is the case the whole per-category design exists for: a
    transformer's is `oil` or `dry`, a cable's is XLPE or PV wire or USE-2. One
    spec per key would give the cable the transformer's closed vocabulary and
    reject every real cable datasheet."""
    transformer = spec_for("insulation_type", ComponentCategory.TRANSFORMERS)
    cable = spec_for("insulation_type", ComponentCategory.CABLING_WIRING)
    assert transformer is not None and cable is not None
    assert transformer.enum == frozenset({"oil", "dry"})
    assert cable.enum is None


def test_a_cross_cutting_field_reaches_every_category() -> None:
    """The contract says these are "present on every `ComponentInstance`
    regardless of category". A registry scoping them to one category would reject
    `baba_status` on seven of the eight tabs the Compliance sheet is built from."""
    for key in ("supplier_verbatim", "datasheet_date", "baba_status", "country_of_origin"):
        for category in ComponentCategory:
            assert key in keys_for(category), f"{key} is not admitted for {category.value}"


def test_a_category_admits_its_own_keys_and_not_another_categorys() -> None:
    """The dimension a flat key set cannot express, and the one the track exists
    for: `chemistry` is a BESS field and `topology` an inverter field, so each is
    off-contract for the other's tab even though both are contract keys."""
    assert "chemistry" in keys_for(ComponentCategory.BESS)
    assert "chemistry" not in keys_for(ComponentCategory.INVERTERS_PCS)
    assert "topology" in keys_for(ComponentCategory.INVERTERS_PCS)
    assert "topology" not in keys_for(ComponentCategory.PV_MODULES)
    assert "insulation_type" not in keys_for(ComponentCategory.PV_MODULES)
    assert CONTRACT_KEYS == {spec.key for spec in FIELD_SPECS}


def test_require_contract_key_says_which_of_the_two_failures_it_is() -> None:
    """An error naming only the key reads as "the contract does not have this",
    which for a category mismatch is false and sends the reader to the wrong
    document. The two messages are distinguished, and the one for a real key names
    the categories that do admit it."""
    with pytest.raises(OffContractFieldError, match="is a contract key but not for pv_modules"):
        require_contract_key("chemistry", ComponentCategory.PV_MODULES)
    with pytest.raises(OffContractFieldError, match="'bess'"):
        require_contract_key("chemistry", ComponentCategory.PV_MODULES)
    with pytest.raises(OffContractFieldError, match="not in the frozen contract"):
        require_contract_key("nameplate_power_w")
    require_contract_key("chemistry")
    require_contract_key("chemistry", ComponentCategory.BESS)


def test_the_union_form_is_honest_about_being_weaker() -> None:
    """`is_contract_key` without a category passes `chemistry` on anything, and
    that is not a bug - it is the only question a per-key table such as
    `FIELD_TOLERANCES` can ask, since D-2 assigns a band to a parameter rather
    than to a tab. It is recorded here so nobody reads the union form as the
    category check."""
    assert is_contract_key("chemistry")
    assert not is_contract_key("chemistry", ComponentCategory.PV_MODULES)
    assert not is_contract_key("nameplate_power_w")


# --- enforcement point 1: ComponentInstance.fields ------------------------------


def _field(value: object) -> CanonicalField:
    return CanonicalField(
        value=value,
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="doc-1"),
        confidence=0.9,
    )


def _instance(category: ComponentCategory, **fields: object) -> ComponentInstance:
    return ComponentInstance(
        supplier="Sungrow",
        model="SG350HX",
        component_category=category,
        fields={key: [_field(value)] for key, value in fields.items()},
    )


def test_a_component_instance_refuses_an_off_contract_key() -> None:
    """`ComponentInstance.fields` is `dict[str, list[CanonicalField]]`, so the key
    is a free string and nothing stopped an extractor writing
    `nameplate_power_w`. The store then holds a parameter under a name no
    downstream table can find, and claims are append-only - the row can only be
    superseded, never fixed."""
    with pytest.raises(ValidationError, match="nameplate_power_w"):
        _instance(ComponentCategory.PV_MODULES, nameplate_power_w=650.0)


def test_a_component_instance_refuses_another_categorys_key() -> None:
    """`chemistry` is a real contract key, so a check against the union of all
    keys passes it - onto a PV module. The category is what makes the key mean
    something, and it is checked."""
    with pytest.raises(ValidationError, match="chemistry"):
        _instance(ComponentCategory.PV_MODULES, chemistry="lfp")
    _instance(ComponentCategory.BESS, chemistry="lfp")


def test_a_component_instance_accepts_the_cross_cutting_keys() -> None:
    """The compliance and cross-category tables are not per-tab, so gating them
    behind a category would reject the fields tabs 12 and 13 are made of."""
    _instance(
        ComponentCategory.TRACKERS_MOUNTING,
        supplier_verbatim="Nextracker Inc.",
        baba_status="unconfirmed",
        stow_strategy="wind stow at 20 m/s",
    )


def test_the_worked_example_still_validates() -> None:
    """D-1's Sungrow trio, which is what `fields` being list-valued exists for.
    A key check that rejected the repo's own worked example would be a defect in
    the check rather than in the example."""
    instance = ComponentInstance(
        supplier="Sungrow",
        model="SG350HX",
        component_category=ComponentCategory.INVERTERS_PCS,
        fields={"rated_ac_power": [_field(352.0), _field(320.0), _field(295.0)]},
    )
    assert len(instance.fields["rated_ac_power"]) == 3


# --- enforcement point 2: commit_claims -----------------------------------------


class _Store:
    """The same in-memory `ClaimWriter` `test_propose_commit` uses."""

    def __init__(self) -> None:
        self.committed: dict[str, list[CanonicalField]] = {}
        self.writes = 0

    def commit(self, field_name: str, values: Sequence[CanonicalField]) -> None:
        self.committed[field_name] = list(values)
        self.writes += 1

    def current(self, field_name: str) -> list[CanonicalField]:
        return self.committed.get(field_name, [])


def _claim(field_name: str, value: object = 650.0) -> FieldClaim:
    return FieldClaim(
        document_id="doc-a",
        field_name=field_name,
        extractor_version="extract@1",
        value=value,
        unit="Wp",
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="doc-a"),
        confidence=0.9,
    )


def test_the_reducer_refuses_an_off_contract_key() -> None:
    """The store key is the field name, so an invented one is written and then
    only ever superseded. This is the append-only cost the track exists to stop:
    the B.9 gold set gets labelled against a key nothing else uses."""
    store = _Store()
    with pytest.raises(ProposalError, match="nameplate_power_w"):
        commit_claims("nameplate_power_w", [_claim("nameplate_power_w")], writer=store)
    assert store.writes == 0


def test_the_reducer_refuses_a_key_off_contract_for_its_category() -> None:
    """The category dimension at the second boundary. `chemistry` is a contract
    key, so only the category makes this a rejection - and without the category
    the reducer cannot tell a BESS chemistry from an inverter one."""
    store = _Store()
    with pytest.raises(ProposalError, match="chemistry"):
        commit_claims(
            "chemistry",
            [_claim("chemistry", "lfp")],
            writer=store,
            category=ComponentCategory.INVERTERS_PCS,
        )
    assert store.writes == 0

    commit_claims(
        "chemistry",
        [_claim("chemistry", "lfp")],
        writer=store,
        category=ComponentCategory.BESS,
    )
    assert store.writes == 1


def test_the_key_is_checked_before_the_claim_set_is_looked_at() -> None:
    """`commit_claims` returns early on an empty claim set, so a check placed
    after that early return passes every invented key that arrives with no claims
    - and "no claims" is exactly what a broken extractor produces."""
    store = _Store()
    with pytest.raises(ProposalError, match="not_a_contract_key"):
        commit_claims("not_a_contract_key", [], writer=store)
    assert store.writes == 0


def test_an_on_contract_commit_still_works() -> None:
    """The other half of every rejection test: a check that refused everything
    would satisfy all three above."""
    store = _Store()
    committed = commit_claims("nameplate_power", [_claim("nameplate_power")], writer=store)
    assert [f.value for f in committed] == [650.0]
    assert store.writes == 1


# --- the consolidation: one authority for the key set ---------------------------


def test_a_tolerance_row_carries_a_contract_key_rather_than_being_filed_under_one() -> None:
    """The invented-key defect this repo has already paid for twice: 19 of the
    tolerance table's 20 keys were names the contract does not have, every row
    silently unreachable, and the transformer loss rule inverted.

    A dict key is a free string, so the fix is to move the key onto the row and
    validate it there - a row that cannot be constructed with a wrong key cannot
    be filed under one.
    """
    with pytest.raises(ValidationError, match="no_load_loss_w"):
        FieldTolerance(key="transformer_no_load_loss_w", rule=ToleranceRule.EXACT)


def test_the_tolerance_dict_is_keyed_by_its_rows() -> None:
    """The half the validator cannot see: a validated row filed under a *different*
    string is exactly as unreachable as an invented one."""
    for name, row in (*FIELD_TOLERANCES.items(), *NEVER_COMPARABLE.items()):
        assert row.key == name, f"{name} holds a tolerance whose own key is {row.key!r}"
    assert set(FIELD_TOLERANCES) <= CONTRACT_KEYS


def test_the_tier_table_derives_tier_a_from_the_registry() -> None:
    """The 28 Tier A rows were a third hand-written copy of contract key names,
    and the copy is what let `ul_listing` fall out of it and auto-accept at 0.99.
    They are now derived from the registry, so a key cannot be in a D-3 Tier A
    category and absent from the gate at the same time.
    """
    from procurement_agent.services.confidence import TIER_A_EXCLUSIONS, looks_tier_a

    expected = {key for key in CONTRACT_KEYS if looks_tier_a(key)} - set(TIER_A_EXCLUSIONS)
    assert len(expected) == 28, "the D-3 patterns stopped recognising the gated fields"
    assert {key for key, tier in FIELD_TIERS.items() if tier is CriticalityTier.A} == expected
    assert set(FIELD_TIERS) <= CONTRACT_KEYS


def test_the_two_tables_no_longer_hold_a_key_the_registry_lacks() -> None:
    """The consolidation stated as one assertion: the frozen markdown is the
    authority, the registry is its machine-readable form, and neither downstream
    table carries a name of its own."""
    assert (set(FIELD_TOLERANCES) | set(NEVER_COMPARABLE) | set(FIELD_TIERS)) <= CONTRACT_KEYS


# --- the committed fixtures, re-validated here rather than downstream ------------


def test_the_committed_claim_fixtures_use_on_contract_keys() -> None:
    """Tightening the boundaries can invalidate a byte-compared fixture, and the
    track that finds that out should be this one rather than the track consuming
    them. Each fixture's key is checked against the category its product belongs
    to, not against the union - a fixture keyed `rated_ac_power` under a PV module
    would pass a union check and be wrong.
    """
    fixtures = {
        "trina-tsm-neg21c-nameplate.json": ComponentCategory.PV_MODULES,
        "sungrow-sg350hx-rated-ac-power.json": ComponentCategory.INVERTERS_PCS,
    }
    root = pathlib.Path(__file__).parent / "fixtures" / "claims"
    on_disk = {path.name for path in root.glob("*.json")}
    assert on_disk == set(fixtures), f"a claim fixture is unaccounted for here: {on_disk}"

    for name, category in fixtures.items():
        for claim in json.loads((root / name).read_text()):
            require_contract_key(claim["field_name"], category)
            spec = spec_for(claim["field_name"], category)
            assert spec is not None and spec.unit == claim["unit"], (
                f"{name} states a unit the contract's canonical-unit column does not"
            )
