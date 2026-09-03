"""Which dimensions gate which field — FN-2.

`Condition.comparable_with` used to iterate *every* `ConditionDimensions` field
for *every* contract key, so a dimension that governs nothing about the field in
hand still refused the comparison. Measured on the shipped code:

    country_of_origin  China@ieee vs Vietnam@iec   -> 0 pairs (untagged: 1)
    warranty_years     25 yr@25 degC vs 10 yr@45 degC -> 0 pairs
    certifications     UL 61730@stc vs UL 1703@noct -> 0 pairs

`country_of_origin` is a CRITICAL, BABA/FEOC-relevant field. Zero pairs is zero
`ConflictQueueEntry`s, so the compose gate never fires and tasks.md E.3a ("100%
of injected conflicts surface") is violated in the one direction a reviewer
cannot see.

The contract already states the rule this file enforces. Its `note` paragraph
says **"A dimension that changes what a number means belongs on
`ConditionDimensions`; only an annotation belongs in `note`"**, and for a field
no Conditions row governs there is no such dimension. So the gate is scoped to
the dimensions the Conditions table names for that field's family, and a field
with no row gates on nothing.

**The scoping is hand-assigned, and that is a decision rather than laziness.**
Deriving it from key patterns (the `confidence.TIER_A_KEY_PATTERNS` shape) was
measured and rejected: a pattern `^imp` written for Imp swallows
`impedance_percent`, handing Transformer %Z the PV `basis` dimension instead of
`{standards_regime, base_mva, tap_position_pct}` — a *new* suppression
introduced by the fix. Tier A is a boolean, so a loose pattern over-includes and
that is safe; this is a mapping, so a loose pattern mis-assigns and suppresses.

The table below is therefore checked against the frozen contract in **both**
directions, the way `test_field_registry` checks the keys and
`test_condition_grouping` checks the vocabularies. One direction cannot see an
omission.
"""

from __future__ import annotations

import itertools
import pathlib
import re

import pytest

from procurement_agent.schema import (
    CONDITION_DIMENSION_NAMES,
    Condition,
    ConditionDimensions,
    ConflictCandidate,
    MeasurementBasis,
    PowerSide,
    RteBoundary,
    SourceRef,
    SourceTier,
    StandardsRegime,
)
from procurement_agent.schema.registry import (
    CONTRACT_KEYS,
    FIELD_SPECS,
    condition_dimensions_for,
)
from procurement_agent.services.conflict_hitl import (
    IncomparableCandidatesError,
    comparison_pairs,
    conflict_groupings,
    tolerance_for,
    values_conflict,
)

CONTRACT = pathlib.Path(__file__).parent.parent / (
    "specs/001-procurement-agent/contracts/canonical-parameters.md"
)


def _c(value: object, condition: Condition, *, unit: str | None = None) -> ConflictCandidate:
    return ConflictCandidate(
        value=value,
        unit=unit,
        condition=condition,
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id=f"doc-{value!r}"),
        confidence=0.9,
    )


# --------------------------------------------------------------------------
# The defect: an irrelevant dimension suppressed a real conflict
# --------------------------------------------------------------------------


def test_a_country_of_origin_conflict_survives_an_irrelevant_standards_regime() -> None:
    """The headline case. No Conditions row governs `country_of_origin`, so no
    dimension changes what "China" means — but `standards_regime` gated it, and
    two sources disagreeing about the country of manufacture produced no pair at
    all. BABA and FEOC both turn on this field."""
    china = _c("China", Condition(standards_regime=StandardsRegime.IEEE))
    vietnam = _c("Vietnam", Condition(standards_regime=StandardsRegime.IEC))
    assert len(comparison_pairs([china, vietnam], field_name="country_of_origin")) == 1


def test_a_warranty_term_is_not_gated_on_an_ambient_temperature() -> None:
    """`temperature_c` is the *inverter rated power* dimension. A warranty term is
    a contractual period; 25 years is 25 years whatever ambient the sheet quoted
    its power at."""
    long_term = _c(25, Condition(temperature_c=25.0), unit="yr")
    short_term = _c(10, Condition(temperature_c=45.0), unit="yr")
    assert len(comparison_pairs([long_term, short_term], field_name="warranty_years")) == 1


def test_a_certification_list_is_not_gated_on_a_measurement_basis() -> None:
    """`basis` governs PV power and efficiency. Which standard a module is listed
    to is not measured at STC or NOCT, and UL 61730 against UL 1703 is a real
    compliance disagreement."""
    modern = _c("UL 61730", Condition(basis=MeasurementBasis.STC))
    legacy = _c("UL 1703", Condition(basis=MeasurementBasis.NOCT))
    assert len(comparison_pairs([modern, legacy], field_name="certifications")) == 1


def test_an_unassigned_key_gates_on_nothing() -> None:
    """The backstop direction is noise, not suppression. A key with no row — and
    a key the contract does not have at all — compares, and a false conflict is
    one queue item a reviewer dismisses. tasks.md E.3a makes the other direction
    a spec violation."""
    left = _c(1.0, Condition(basis=MeasurementBasis.STC, side=PowerSide.AC))
    right = _c(2.0, Condition(basis=MeasurementBasis.NOCT, side=PowerSide.DC))
    assert len(comparison_pairs([left, right], field_name="k_factor")) == 1
    assert len(comparison_pairs([left, right], field_name="not_a_contract_key")) == 1
    assert condition_dimensions_for("not_a_contract_key") == frozenset()


# --------------------------------------------------------------------------
# Regression: the suppressions that are real must stay
# --------------------------------------------------------------------------


def test_the_sungrow_derating_curve_is_still_three_incomparable_ratings() -> None:
    """D-1's opening case. `352 kVA @30 degC`, `320 @40` and `295 @50` are all
    "rated"; comparing any two of them manufactures a conflict out of a
    derating curve."""
    curve = [
        _c(v, Condition(temperature_c=t), unit="kVA")
        for v, t in ((352.0, 30.0), (320.0, 40.0), (295.0, 50.0))
    ]
    assert comparison_pairs(curve, field_name="rated_ac_power") == []


def test_stc_and_noct_nameplates_are_still_not_a_disagreement() -> None:
    """Trina prints STC 695 W and NOCT 531 W side by side. A 24% "conflict" out
    of two correct numbers is exactly what `Condition` exists to stop."""
    stc = _c(695.0, Condition(basis=MeasurementBasis.STC), unit="Wp")
    noct = _c(531.0, Condition(basis=MeasurementBasis.NOCT), unit="Wp")
    assert comparison_pairs([stc, noct], field_name="nameplate_power") == []


def test_impedance_across_two_regimes_is_still_not_a_disagreement() -> None:
    """%Z scales with the MVA base, and IEEE refers it to the ONAN base where IEC
    refers it to the top rating — 1.25-1.67x apart, far beyond the +/-7.5%
    tolerance. This is the case the rejected regex approach broke."""
    ieee = _c(8.0, Condition(standards_regime=StandardsRegime.IEEE), unit="%")
    iec = _c(10.0, Condition(standards_regime=StandardsRegime.IEC), unit="%")
    assert comparison_pairs([ieee, iec], field_name="impedance_percent") == []


def test_impedance_is_gated_on_all_three_of_its_dimensions() -> None:
    """The %Z row names three, and each of the three was promoted out of `note`
    under issue #16 precisely because leaving it there merged measurements."""
    assert condition_dimensions_for("impedance_percent") == frozenset(
        {"standards_regime", "base_mva", "tap_position_pct"}
    )
    nominal = _c(8.0, Condition(tap_position_pct=0.0), unit="%")
    raised = _c(8.6, Condition(tap_position_pct=5.0), unit="%")
    assert comparison_pairs([nominal, raised], field_name="impedance_percent") == []


def test_a_round_trip_efficiency_is_gated_on_its_boundary_side_and_duration() -> None:
    """Four boundaries all called "round-trip efficiency", worth 2-7 pp, and RTE
    is duration-dependent even at one boundary."""
    assert condition_dimensions_for("round_trip_efficiency") == frozenset(
        {"side", "duration_h", "rte_boundary"}
    )
    dc = _c(92.0, Condition(rte_boundary=RteBoundary.DC_DC_TERMINALS), unit="%")
    ac = _c(86.0, Condition(rte_boundary=RteBoundary.AC_AC_MV_INCL_AUX), unit="%")
    assert comparison_pairs([dc, ac], field_name="round_trip_efficiency") == []


def test_bess_energy_is_gated_on_both_side_and_basis() -> None:
    """BOL and EOL differ ~26% on real projects, and AC vs DC straddles the PCS."""
    for key in ("usable_energy_per_container", "nameplate_energy_per_container"):
        assert condition_dimensions_for(key) == frozenset({"side", "basis"}), key
    bol = _c(20.0, Condition(basis=MeasurementBasis.BOL), unit="MWh")
    eol = _c(14.8, Condition(basis=MeasurementBasis.EOL), unit="MWh")
    assert comparison_pairs([bol, eol], field_name="usable_energy_per_container") == []


def test_inverter_efficiency_is_gated_on_its_weighting() -> None:
    """99.02% max, 98.5% CEC and 98.8% European are one product."""
    for key in ("max_efficiency", "cec_efficiency"):
        assert condition_dimensions_for(key) == frozenset({"weighting"}), key


def test_the_mppt_window_is_gated_on_its_basis() -> None:
    """`500-1500 V` and `860-1330 V` are different fields, not a discrepancy."""
    for key in ("mppt_voltage_min", "mppt_voltage_max"):
        assert condition_dimensions_for(key) == frozenset({"basis"}), key


# --------------------------------------------------------------------------
# The two judgement calls, written down where the code can be read against them
# --------------------------------------------------------------------------


def test_no_load_loss_is_not_gated_on_the_loss_reference_temperature() -> None:
    """The contract's own carve-out, stated in the losses row: "No-load loss is
    **not** temperature-corrected." Load loss is; no-load loss is not, so gating
    both on `reference_temperature_c` would suppress a real disagreement between
    an IEEE and an IEC no-load figure that are genuinely comparable."""
    assert condition_dimensions_for("load_loss") == frozenset({"reference_temperature_c"})
    assert condition_dimensions_for("no_load_loss") == frozenset()
    ieee = _c(12.0, Condition(reference_temperature_c=85.0), unit="kW")
    iec = _c(19.0, Condition(reference_temperature_c=75.0), unit="kW")
    # Two *load* loss figures at different references are not a disagreement...
    assert comparison_pairs([ieee, iec], field_name="load_loss") == []
    # ... while the same two references on a no-load figure are an annotation,
    # not a dimension, so the 58% gap between them still reaches a reviewer.
    assert len(comparison_pairs([ieee, iec], field_name="no_load_loss")) == 1


def test_max_system_voltage_gates_on_nothing_and_why() -> None:
    """`max_system_voltage` is one key on two tabs — `pv_modules`, where the
    contract's "PV power, efficiency, all electrical" row names `basis`, and
    `combiner_boxes`, which has no Conditions row at all. `FieldSpec.categories`
    is a set, so one key gets one answer, and the answer has to be safe on both.

    It gates on nothing, for three reasons kept together here and in the
    registry:

    1. On `combiner_boxes` any gate is a suppression the contract never
       authorised, because that tab has no row to authorise one.
    2. The governing rule is "a dimension that changes what a number *means*".
       `basis` names a test condition — an irradiance and a cell temperature.
       Maximum system voltage is an insulation-coordination limit from IEC/UL
       61730; there is no "NOCT maximum system voltage" to be different from the
       STC one.
    3. The costs are not symmetric. A wrong `frozenset()` raises one extra queue
       item. A wrong `{basis}` silently absorbs 1000 V against 1500 V — a
       CRITICAL safety parameter, and the exact pair `test_values_conflict`
       already pins as a conflict."""
    assert condition_dimensions_for("max_system_voltage") == frozenset()
    thousand = _c(1000.0, Condition(basis=MeasurementBasis.STC), unit="V")
    fifteen_hundred = _c(1500.0, Condition(basis=MeasurementBasis.NOCT), unit="V")
    pairs = comparison_pairs([thousand, fifteen_hundred], field_name="max_system_voltage")
    assert len(pairs) == 1
    assert values_conflict(
        *pairs[0], tolerance=tolerance_for("max_system_voltage"), field_name="max_system_voltage"
    ).conflicts


def test_the_temperature_coefficients_gate_on_nothing() -> None:
    """The Conditions table says so in as many words: "PV temperature
    coefficients | none". `%/degC` and `%/K` are the same unit, and the row's
    whole point is that nothing about the measurement needs qualifying."""
    for key in ("temp_coeff_pmax", "temp_coeff_voc", "temp_coeff_isc"):
        assert condition_dimensions_for(key) == frozenset(), key


def test_the_ad_hoc_condition_encodings_do_not_gate_on_themselves() -> None:
    """`rated_ac_power_temp` *is* the ambient a rating is stated at — the contract
    calls it one of the "ad-hoc encodings" `Condition` replaces. Gating a
    temperature on `temperature_c` would compare a value only against values
    that already agree with it, which is not a comparison."""
    assert condition_dimensions_for("rated_ac_power_temp") == frozenset()
    thirty = _c(30.0, Condition(temperature_c=30.0), unit="degC")
    forty = _c(40.0, Condition(temperature_c=40.0), unit="degC")
    assert len(comparison_pairs([thirty, forty], field_name="rated_ac_power_temp")) == 1


# --------------------------------------------------------------------------
# Bidirectional against the frozen Conditions table
# --------------------------------------------------------------------------


def _conditions_table() -> list[tuple[str, str]]:
    """`(family, required-fields cell)` for every row of the Conditions table.

    Same parse as `test_condition_grouping._conditions_table`, deliberately
    duplicated rather than imported: a test importing another test module makes
    a change in one silently re-baseline the other, and this file is checking a
    different property of the same rows.
    """
    table = CONTRACT.read_text(encoding="utf-8").split("## Conditions", 1)[1]
    rows = []
    for line in table.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.count("|") < 4:
            continue
        cells = stripped.split("|")
        if set(cells[1].strip()) <= {"-", ":"}:  # the header separator
            continue
        rows.append((cells[1].strip(), cells[2]))
    assert len(rows) > 5, "the Conditions table did not parse; the checks below would be vacuous"
    return rows


def _required_of(cell: str) -> frozenset[str]:
    """The `ConditionDimensions` names a row requires.

    An `∈ {...}` clause names its head and then its vocabulary, so the braces
    are removed before the remaining backticked names are read — otherwise
    `{`ieee`, `iec`}` reads as two more dimensions.
    """
    remaining = cell
    heads = set()
    for head, listed in re.findall(r"`([a-z_]+)`\s*∈\s*\{([^}]*)\}", cell):
        heads.add(head)
        remaining = remaining.replace(f"{{{listed}}}", "")
    names = heads | set(re.findall(r"`([a-z_]+)`", remaining))
    return frozenset(names & set(ConditionDimensions.model_fields))


def _assigned_sets() -> set[frozenset[str]]:
    return {spec.condition_dimensions for spec in FIELD_SPECS if spec.condition_dimensions}


def test_the_conditions_table_parse_is_not_vacuous() -> None:
    """Every check below rests on this parse, and a parse that silently returns
    nothing turns all of them green. Pinned against the rows whose dimension
    sets are the most specific in the table."""
    required = {_required_of(cell) for _family, cell in _conditions_table()}
    assert frozenset({"standards_regime", "base_mva", "tap_position_pct"}) in required
    assert frozenset({"side", "duration_h", "rte_boundary"}) in required
    assert frozenset({"temperature_c"}) in required
    assert frozenset() in required, "the temperature-coefficient row requires nothing"


def test_every_row_of_the_conditions_table_governs_at_least_one_key() -> None:
    """Forward direction. A row nobody implements is a rule the contract states
    and the code does not — how the `note` routing survived three releases.

    The `none` row is covered by `test_the_temperature_coefficients_gate_on_
    nothing`; an empty requirement is satisfied by every unassigned key, so
    asserting it here would be vacuous."""
    assigned = _assigned_sets()
    for family, cell in _conditions_table():
        required = _required_of(cell)
        if not required:
            continue
        assert required in assigned, (
            f"the Conditions table's {family!r} row requires {sorted(required)}, "
            "and no contract key is gated on exactly that set"
        )


def test_no_key_is_gated_on_a_set_the_conditions_table_does_not_state() -> None:
    """Reverse direction, and the one that catches an invented rule. Every gate
    this registry applies has to be a rule the frozen contract wrote down —
    otherwise the fix for a suppression has quietly introduced another."""
    stated = {_required_of(cell) for _family, cell in _conditions_table()}
    for spec in FIELD_SPECS:
        if not spec.condition_dimensions:
            continue
        assert spec.condition_dimensions in stated, (
            f"{spec.key!r} gates on {sorted(spec.condition_dimensions)}, which no row "
            "of the Conditions table requires"
        )


def test_every_dimension_the_table_names_gates_some_key() -> None:
    """The per-dimension form of the forward check. `base_mva`,
    `tap_position_pct` and `rte_boundary` were promoted out of `note` for issue
    #16; a promotion that reaches no key leaves the merge it was meant to stop."""
    gating = frozenset().union(*(spec.condition_dimensions for spec in FIELD_SPECS))
    assert gating == CONDITION_DIMENSION_NAMES, (
        f"these `ConditionDimensions` fields gate nothing: "
        f"{sorted(CONDITION_DIMENSION_NAMES - gating)}"
    )


def test_only_the_four_categories_with_conditions_rows_carry_an_assignment() -> None:
    """The Conditions table has rows for PV modules, inverters, BESS and
    transformers and for nothing else. A gate on a trackers, cabling, combiner,
    EMS, cross-category or compliance key would be invented."""
    governed = {"pv_modules", "inverters_pcs", "bess", "transformers"}
    for spec in FIELD_SPECS:
        if not spec.condition_dimensions:
            continue
        assert {c.value for c in spec.categories} <= governed, spec.key


def test_a_gated_key_is_always_numeric() -> None:
    """Every Conditions row qualifies a *number*: what it means to state a
    measurement basis, an ambient or an impedance base is that the number reads
    differently. A gate on a string or a boolean would be a category error."""
    for spec in FIELD_SPECS:
        if not spec.condition_dimensions:
            continue
        assert spec.value_type.value in {"float", "int"}, spec.key


# --------------------------------------------------------------------------
# The primitive
# --------------------------------------------------------------------------


def test_comparable_with_refuses_a_name_that_gates_nothing() -> None:
    """`note` and `derived` live on `Condition`, not on `ConditionDimensions`, so
    `getattr` would happily read them — and gating on `note` is precisely what
    the contract forbids ("`note` does not gate comparison"). A typo'd
    dimension is the same hazard wearing a different hat: `bassis` reads as
    "nothing to check", which suppresses silently."""
    left, right = Condition(note="a"), Condition(note="b")
    for name in ("note", "derived", "bassis", ""):
        with pytest.raises(ValueError, match="gates comparison|not a condition dimension"):
            left.comparable_with(right, dimensions=frozenset({name}))


def test_comparable_with_still_answers_the_unqualified_question() -> None:
    """Scoping is a property of the *call*, not a change to `Condition`'s shape —
    the contract has already rejected a per-family `Condition` ("the comparison
    logic cannot carry" it). Asked about every dimension, the relation is exactly
    what it was."""
    stc = Condition(basis=MeasurementBasis.STC)
    noct = Condition(basis=MeasurementBasis.NOCT)
    assert not stc.comparable_with(noct, dimensions=CONDITION_DIMENSION_NAMES)
    assert stc.comparable_with(Condition(), dimensions=CONDITION_DIMENSION_NAMES)
    # ... and asked about a dimension neither side states, it is comparable even
    # though they contradict on one it was not asked about.
    assert stc.comparable_with(noct, dimensions=frozenset({"side"}))


def test_absent_is_still_unknown_rather_than_contradictory() -> None:
    """Unchanged by the scoping, and load-bearing: refusing to compare whenever a
    datasheet states its conditions incompletely would block nearly everything."""
    stated = _c(695.0, Condition(basis=MeasurementBasis.STC), unit="Wp")
    silent = _c(650.0, Condition(), unit="Wp")
    assert len(comparison_pairs([stated, silent], field_name="nameplate_power")) == 1


# --------------------------------------------------------------------------
# The two gates agree
# --------------------------------------------------------------------------


def test_values_conflict_accepts_every_pair_comparison_pairs_admits() -> None:
    """The gate is applied twice — once to select pairs, once as a guard inside
    `values_conflict` — and the two must apply the same rule. Scoping only the
    first would make `comparison_pairs` hand `values_conflict` a pair it then
    raises `IncomparableCandidatesError` on, turning a fixed suppression into a
    crash on the same field."""
    china = _c("China", Condition(standards_regime=StandardsRegime.IEEE))
    vietnam = _c("Vietnam", Condition(standards_regime=StandardsRegime.IEC))
    (pair,) = comparison_pairs([china, vietnam], field_name="country_of_origin")
    verdict = values_conflict(
        *pair, tolerance=tolerance_for("country_of_origin"), field_name="country_of_origin"
    )
    assert verdict.conflicts


def test_values_conflict_still_refuses_a_pair_the_gate_would_not_have_selected() -> None:
    """The guard is not weakened, only scoped. A caller that skipped
    `comparison_pairs` and hands it two conditions that contradict on a
    dimension that *does* govern the field is still refused."""
    stc = _c(695.0, Condition(basis=MeasurementBasis.STC), unit="Wp")
    noct = _c(531.0, Condition(basis=MeasurementBasis.NOCT), unit="Wp")
    with pytest.raises(IncomparableCandidatesError):
        values_conflict(
            stc, noct, tolerance=tolerance_for("nameplate_power"), field_name="nameplate_power"
        )


def test_the_unscoped_guard_is_the_strict_one() -> None:
    """`field_name` is optional on `values_conflict` because one production
    caller compares corroborating electricals that have no contract field
    (`services.identity`), and the tests construct ad-hoc tolerances. The
    default is deliberately the *strict* reading — every dimension — because
    refusing is loud where admitting would be silent."""
    stc = _c(695.0, Condition(basis=MeasurementBasis.STC), unit="Wp")
    noct = _c(531.0, Condition(basis=MeasurementBasis.NOCT), unit="Wp")
    with pytest.raises(IncomparableCandidatesError):
        values_conflict(stc, noct, tolerance=tolerance_for("nameplate_power"))


# --------------------------------------------------------------------------
# Properties the scoping must not break
# --------------------------------------------------------------------------


def test_the_pair_list_is_still_a_function_of_the_candidate_set() -> None:
    """FR-OUT-06: composition is a pure function of the store, so the pair list
    may not depend on the order candidates arrive in."""
    candidates = [
        _c(650.0, Condition(), unit="Wp"),
        _c(700.0, Condition(basis=MeasurementBasis.STC), unit="Wp"),
        _c(645.0, Condition(basis=MeasurementBasis.STC), unit="Wp"),
    ]
    outputs = {
        tuple(
            (a.value, b.value)
            for a, b in comparison_pairs(list(order), field_name="nameplate_power")
        )
        for order in itertools.permutations(candidates)
    }
    assert len(outputs) == 1


def test_conflict_groupings_carries_the_field_through() -> None:
    """`conflict_groupings` is what a `ConflictQueueEntry` is built from, so a
    field-agnostic gate there is the one that reaches the queue."""
    china = _c("China", Condition(standards_regime=StandardsRegime.IEEE))
    vietnam = _c("Vietnam", Condition(standards_regime=StandardsRegime.IEC))
    assert len(conflict_groupings([china, vietnam], field_name="country_of_origin")) == 1
    stc = _c(695.0, Condition(basis=MeasurementBasis.STC), unit="Wp")
    noct = _c(531.0, Condition(basis=MeasurementBasis.NOCT), unit="Wp")
    assert conflict_groupings([stc, noct], field_name="nameplate_power") == []


def test_the_field_name_is_required_rather_than_defaulted() -> None:
    """A default would preserve the defect: every existing call site would keep
    the field-agnostic gate and nothing would say so."""
    with pytest.raises(TypeError):
        comparison_pairs([])  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        conflict_groupings([])  # type: ignore[call-arg]


def test_every_contract_key_has_an_answer() -> None:
    """`condition_dimensions_for` is total over the contract, so no key falls
    through to an exception at conflict-detection time."""
    for key in CONTRACT_KEYS:
        assert condition_dimensions_for(key) <= CONDITION_DIMENSION_NAMES, key
