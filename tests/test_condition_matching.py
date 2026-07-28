"""Two values are only comparable when their conditions match.

clarifications.md D-1. Mismatched conditions are not a conflict - they are not a
comparison. This is the gate that runs before any tolerance check.
"""

from procurement_agent.schema import Condition


def test_empty_conditions_are_comparable() -> None:
    """Unknown conditions on both sides means we have no reason to refuse."""
    assert Condition().comparable_with(Condition())


def test_matching_conditions_are_comparable() -> None:
    a = Condition(temperature_c=40.0)
    b = Condition(temperature_c=40.0)
    assert a.comparable_with(b)


def test_differing_temperature_is_not_comparable() -> None:
    """The Sungrow SG350HX case.

    The EU datasheet says 352 kVA @30 degC, CEC says 320.865 kW @40 degC. These
    are the same product agreeing with itself, not a 10% discrepancy. Comparing
    them would raise a conflict that wastes a reviewer's time and teaches them
    to distrust the queue.
    """
    eu = Condition(temperature_c=30.0)
    cec = Condition(temperature_c=40.0)
    assert not eu.comparable_with(cec)


def test_differing_efficiency_weighting_is_not_comparable() -> None:
    """98.8% European and 98.5% CEC are the same inverter, differently weighted."""
    assert not Condition(weighting="european").comparable_with(Condition(weighting="cec"))


def test_bess_ac_dc_side_is_not_comparable() -> None:
    """A DC nameplate against an AC deliverable is not a 28% advantage."""
    assert not Condition(side="dc").comparable_with(Condition(side="ac"))


def test_bess_life_point_is_not_comparable() -> None:
    """BOL vs EOL differ by ~26% on real projects - 50.5 MWh vs 40 MWh."""
    assert not Condition(basis="bol").comparable_with(Condition(basis="eol"))


def test_bess_duration_is_not_comparable() -> None:
    """RTE is duration-dependent even at a fixed boundary: 91.7% @2h vs 93.7% @4h."""
    assert not Condition(duration_h=2.0).comparable_with(Condition(duration_h=4.0))


def test_pv_stc_vs_noct_is_not_comparable() -> None:
    """Trina prints STC 695 W and NOCT 531 W side by side in one table."""
    assert not Condition(basis="stc").comparable_with(Condition(basis="noct"))


def test_transformer_standards_regime_is_not_comparable() -> None:
    """IEEE anchors multi-cooling ratings and %Z at the base rating, IEC at the top.

    Comparing across regimes without normalising is wrong by up to 1.67x on
    impedance - far larger than the +/-7.5% tolerance. See D-6.
    """
    assert not Condition(standards_regime="ieee").comparable_with(Condition(standards_regime="iec"))


def test_unknown_on_one_side_does_not_block_comparison() -> None:
    """Absent is unknown, not contradictory.

    Refusing to compare whenever one side omits a condition would make the tool
    useless on real datasheets, most of which state conditions incompletely.
    The cost of this choice is some false conflicts; the alternative is no
    comparisons at all.
    """
    stated = Condition(temperature_c=40.0)
    silent = Condition()
    assert stated.comparable_with(silent)
    assert silent.comparable_with(stated)


def test_note_is_ignored_for_comparability() -> None:
    """Free text is provenance for a human, not a machine-comparable condition."""
    a = Condition(temperature_c=40.0, note="from page 3 table")
    b = Condition(temperature_c=40.0, note="from the summary block")
    assert a.comparable_with(b)


def test_comparability_is_symmetric() -> None:
    a = Condition(basis="stc", temperature_c=25.0)
    b = Condition(basis="noct", temperature_c=25.0)
    assert a.comparable_with(b) == b.comparable_with(a)
