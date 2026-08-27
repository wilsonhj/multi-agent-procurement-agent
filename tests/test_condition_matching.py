"""Two values are only comparable when their conditions match.

clarifications.md D-1. Mismatched conditions are not a conflict - they are not a
comparison. This is the gate that runs before any tolerance check.

**Which dimensions gate is now part of the question** (FN-2). Applying every
dimension to every field made an irrelevant one suppress a real disagreement, so
`comparable_with` takes the set it is being asked about. Each case below is
therefore scoped to the field whose family the frozen contract's Conditions table
names for that dimension - which is what makes the case a real one rather than an
assertion about a tuple. `CONDITION_DIMENSION_NAMES` is the unqualified relation,
used where the case is about the relation itself.
"""

from procurement_agent.schema import (
    CONDITION_DIMENSION_NAMES,
    Condition,
    EfficiencyWeighting,
    MeasurementBasis,
    PowerSide,
    StandardsRegime,
)
from procurement_agent.schema.registry import condition_dimensions_for


def test_empty_conditions_are_comparable() -> None:
    """Unknown conditions on both sides means we have no reason to refuse."""
    assert Condition().comparable_with(Condition(), dimensions=CONDITION_DIMENSION_NAMES)


def test_matching_conditions_are_comparable() -> None:
    a = Condition(temperature_c=40.0)
    b = Condition(temperature_c=40.0)
    assert a.comparable_with(b, dimensions=condition_dimensions_for("rated_ac_power"))


def test_differing_temperature_is_not_comparable() -> None:
    """The Sungrow SG350HX case.

    The EU datasheet says 352 kVA @30 degC, CEC says 320.865 kW @40 degC. These
    are the same product agreeing with itself, not a 10% discrepancy. Comparing
    them would raise a conflict that wastes a reviewer's time and teaches them
    to distrust the queue.
    """
    eu = Condition(temperature_c=30.0)
    cec = Condition(temperature_c=40.0)
    assert not eu.comparable_with(cec, dimensions=condition_dimensions_for("rated_ac_power"))


def test_differing_efficiency_weighting_is_not_comparable() -> None:
    """98.8% European and 98.5% CEC are the same inverter, differently weighted."""
    assert not Condition(weighting=EfficiencyWeighting.EUROPEAN).comparable_with(
        Condition(weighting=EfficiencyWeighting.CEC),
        dimensions=condition_dimensions_for("cec_efficiency"),
    )


def test_bess_ac_dc_side_is_not_comparable() -> None:
    """A DC nameplate against an AC deliverable is not a 28% advantage."""
    assert not Condition(side=PowerSide.DC).comparable_with(
        Condition(side=PowerSide.AC),
        dimensions=condition_dimensions_for("usable_energy_per_container"),
    )


def test_bess_life_point_is_not_comparable() -> None:
    """BOL vs EOL differ by ~26% on real projects - 50.5 MWh vs 40 MWh."""
    assert not Condition(basis=MeasurementBasis.BOL).comparable_with(
        Condition(basis=MeasurementBasis.EOL),
        dimensions=condition_dimensions_for("usable_energy_per_container"),
    )


def test_bess_duration_is_not_comparable() -> None:
    """RTE is duration-dependent even at a fixed boundary: 91.7% @2h vs 93.7% @4h."""
    assert not Condition(duration_h=2.0).comparable_with(
        Condition(duration_h=4.0), dimensions=condition_dimensions_for("round_trip_efficiency")
    )


def test_pv_stc_vs_noct_is_not_comparable() -> None:
    """Trina prints STC 695 W and NOCT 531 W side by side in one table."""
    assert not Condition(basis=MeasurementBasis.STC).comparable_with(
        Condition(basis=MeasurementBasis.NOCT),
        dimensions=condition_dimensions_for("nameplate_power"),
    )


def test_transformer_standards_regime_is_not_comparable() -> None:
    """IEEE anchors multi-cooling ratings and %Z at the base rating, IEC at the top.

    Comparing across regimes without normalising is wrong by up to 1.67x on
    impedance - far larger than the +/-7.5% tolerance. See D-6.
    """
    assert not Condition(standards_regime=StandardsRegime.IEEE).comparable_with(
        Condition(standards_regime=StandardsRegime.IEC),
        dimensions=condition_dimensions_for("impedance_percent"),
    )


def test_a_dimension_that_governs_another_family_does_not_gate_this_one() -> None:
    """FN-2 at the primitive. Every case above pairs a dimension with a field its
    own row names; this is the same two conditions asked about a field no row
    governs, and there the answer has to be *comparable*.

    `country_of_origin` decides a BABA and a FEOC position, and two sources
    naming different countries produced no comparison at all because one sheet
    was IEEE and the other IEC.
    """
    ieee = Condition(standards_regime=StandardsRegime.IEEE)
    iec = Condition(standards_regime=StandardsRegime.IEC)
    assert not ieee.comparable_with(iec, dimensions=condition_dimensions_for("impedance_percent"))
    assert ieee.comparable_with(iec, dimensions=condition_dimensions_for("country_of_origin"))


def test_unknown_on_one_side_does_not_block_comparison() -> None:
    """Absent is unknown, not contradictory.

    Refusing to compare whenever one side omits a condition would make the tool
    useless on real datasheets, most of which state conditions incompletely.
    The cost of this choice is some false conflicts; the alternative is no
    comparisons at all.
    """
    stated = Condition(temperature_c=40.0)
    silent = Condition()
    dimensions = condition_dimensions_for("rated_ac_power")
    assert stated.comparable_with(silent, dimensions=dimensions)
    assert silent.comparable_with(stated, dimensions=dimensions)


def test_note_is_ignored_for_comparability() -> None:
    """Free text is provenance for a human, not a machine-comparable condition.

    Now enforced rather than merely unread: `note` is not a `ConditionDimensions`
    field, so asking to gate on it raises instead of quietly gating on it."""
    a = Condition(temperature_c=40.0, note="from page 3 table")
    b = Condition(temperature_c=40.0, note="from the summary block")
    assert a.comparable_with(b, dimensions=CONDITION_DIMENSION_NAMES)
    assert "note" not in CONDITION_DIMENSION_NAMES


def test_comparability_is_symmetric() -> None:
    """Both directions *and* both outcomes.

    Symmetry alone is satisfied by a predicate that always returns False, which
    is how `comparable_with -> False` passed this test: the pair below disagrees,
    so a second pair that must agree is what makes the assertion bite."""
    a = Condition(basis=MeasurementBasis.STC, temperature_c=25.0)
    b = Condition(basis=MeasurementBasis.NOCT, temperature_c=25.0)
    names = CONDITION_DIMENSION_NAMES
    assert a.comparable_with(b, dimensions=names) == b.comparable_with(a, dimensions=names) is False
    c = Condition(temperature_c=25.0)
    assert a.comparable_with(c, dimensions=names) == c.comparable_with(a, dimensions=names) is True
