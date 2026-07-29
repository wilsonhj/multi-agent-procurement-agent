"""Whether two values actually disagree — issue #1, clarifications D-2, task E.1.

The global `numeric_conflict_tolerance` is gone. 2% of a 650 W nameplate is 13 W,
which merges three adjacent 5 W SKUs; the same 2% on a −0.29 %/degC temperature
coefficient is far below datasheet precision. One number cannot be right for both.
"""

import pytest

from procurement_agent.schema import (
    Condition,
    ConflictCandidate,
    ConflictClass,
    DeclaredBand,
    MeasurementBasis,
    SourceRef,
    SourceTier,
    ToleranceKind,
    ToleranceRule,
)
from procurement_agent.services.conflict_hitl import (
    IncomparableCandidatesError,
    tolerance_for,
    values_conflict,
)
from procurement_agent.services.conflict_hitl.tolerance import (
    DEFAULT_TOLERANCE,
    FIELD_TOLERANCES,
    FieldTolerance,
)

NAMEPLATE = tolerance_for("nameplate_power_w")
GAMMA = tolerance_for("gamma_pmax_pct_per_c")
AC_POWER = tolerance_for("inverter_ac_power_kva")
TOTAL_LOSS = tolerance_for("transformer_total_loss_w")


def _c(
    value: object,
    *,
    unit: str | None = "W",
    tier: SourceTier = SourceTier.SYSTEM_OF_RECORD,
    doc: str = "doc-a",
    verbatim: str | None = None,
    condition: Condition | None = None,
) -> ConflictCandidate:
    return ConflictCandidate(
        value=value,
        unit=unit,
        verbatim_value=verbatim,
        condition=condition or Condition(),
        source_tier=tier,
        source_ref=SourceRef(document_id=doc),
        confidence=0.9,
    )


# --- the four questions the stub left open ------------------------------------


def test_a_missing_value_is_a_gap_not_a_conflict() -> None:
    """RECORD_VS_WEB needs both sides to hold a value. A gap flags MISSING_DATA
    and triggers the FR-WEB-01 search instead."""
    verdict = values_conflict(_c(None), _c(650.0), tolerance=NAMEPLATE)
    assert not verdict.conflicts
    assert verdict.conflict_class is None


def test_a_unit_mismatch_is_never_resolved_by_tolerance() -> None:
    """Normalising here would hide an extraction defect behind a successful
    comparison. 650 W and 650 kW are four decimal orders apart."""
    verdict = values_conflict(_c(650.0, unit="W"), _c(650.0, unit="kW"), tolerance=NAMEPLATE)
    assert verdict.conflicts
    assert verdict.conflict_class is ConflictClass.UNIT_NORMALIZATION


def test_an_edition_difference_is_temporal_not_a_string_mismatch() -> None:
    """`IEC 61215:2021` vs `IEC 61215:2016` is the same standard at two editions.
    Dropping the year would equate them — a compliance claim nobody made."""
    verdict = values_conflict(
        _c("IEC 61215:2021", unit=None),
        _c("IEC 61215:2016", unit=None),
        tolerance=DEFAULT_TOLERANCE,
    )
    assert verdict.conflicts
    assert verdict.conflict_class is ConflictClass.TEMPORAL


def test_an_unqualified_standard_matches_a_dated_one() -> None:
    """The common real case: a contract naming `IEC 61215` and a datasheet naming
    `IEC 61215:2021` are not a disagreement."""
    verdict = values_conflict(
        _c("IEC 61215:2021", unit=None), _c("IEC 61215", unit=None), tolerance=DEFAULT_TOLERANCE
    )
    assert not verdict.conflicts


def test_text_is_normalised_but_never_fuzzy_matched() -> None:
    """Case and whitespace fold; a genuinely different certification does not.
    A fuzzy match that equates two certifications is unrecoverable, where a false
    conflict is one extra queue item."""
    assert not values_conflict(
        _c("UL 61730", unit=None), _c("  ul   61730 ", unit=None), tolerance=DEFAULT_TOLERANCE
    ).conflicts
    assert values_conflict(
        _c("IEC 61215", unit=None), _c("IEC 61730", unit=None), tolerance=DEFAULT_TOLERANCE
    ).conflicts


# --- the four rules -----------------------------------------------------------


def test_nameplate_absorbs_650_versus_650_point_0_and_nothing_more() -> None:
    """D-2's stated intent for the ±1 W row. 655 is the next SKU, not a rounding."""
    assert not values_conflict(_c(650), _c(650.0), tolerance=NAMEPLATE).conflicts
    assert values_conflict(_c(650.0), _c(655.0), tolerance=NAMEPLATE).conflicts


def test_a_two_percent_relative_band_would_have_merged_three_skus() -> None:
    """The defect this table replaces, stated as a test so it cannot come back."""
    two_percent = FieldTolerance(rule=ToleranceRule.RELATIVE, magnitude=0.02)
    assert not values_conflict(_c(650.0), _c(660.0), tolerance=two_percent).conflicts
    assert values_conflict(_c(650.0), _c(660.0), tolerance=NAMEPLATE).conflicts


def test_the_rounding_floor_protects_the_coarser_source() -> None:
    """D-2: `1/2 x 10^(-min(decimals))`. Two values are never in conflict by less
    than the precision the coarser sheet could express."""
    coarse = _c(-0.29, unit="%/degC", verbatim="-0.29 %/degC")
    fine = _c(-0.294, unit="%/degC", doc="doc-b", verbatim="-0.294 %/degC")
    assert not values_conflict(coarse, fine, tolerance=GAMMA).conflicts
    # Beyond the floor and beyond the band, it is a real disagreement.
    assert values_conflict(coarse, _c(-0.33, unit="%/degC", doc="doc-b"), tolerance=GAMMA).conflicts


def test_an_exact_rule_still_honours_the_rounding_floor() -> None:
    """Otherwise `1500` vs `1500.0` on max system voltage would be a conflict."""
    exact = tolerance_for("max_system_voltage_v")
    assert exact.rule is ToleranceRule.EXACT
    assert not values_conflict(_c(1500, unit="V"), _c(1500.0, unit="V"), tolerance=exact).conflicts
    assert values_conflict(_c(1000, unit="V"), _c(1500, unit="V"), tolerance=exact).conflicts


def test_the_band_is_exclusive_a_difference_exactly_at_it_is_not_a_conflict() -> None:
    """D-2 writes `conflict <=> |a-b| > band`, strictly. Mutating `>` to `>=`
    survived every other test here: nothing pinned the boundary, and the two
    differ on precisely the values a tolerance is chosen to sit on."""
    assert not values_conflict(_c(650.0), _c(651.0), tolerance=NAMEPLATE).conflicts
    assert values_conflict(_c(650.0), _c(651.01), tolerance=NAMEPLATE).conflicts


def test_the_rounding_floor_overrides_a_band_finer_than_the_printed_value() -> None:
    """The case the floor exists for, and the one a band-only test misses: a sheet
    printing `22` for module efficiency cannot express 22.4, so a 0.1 pp band
    would raise a conflict against a precision the source never claimed.

    Dropping the floor entirely survived a test whose band already exceeded it."""
    coarse = _c(22, unit="pp", verbatim="22")
    fine = _c(22.4, unit="pp", doc="doc-b", verbatim="22.4")
    efficiency = tolerance_for("module_efficiency_pct")
    assert efficiency.magnitude == pytest.approx(0.1)
    assert not values_conflict(coarse, fine, tolerance=efficiency).conflicts
    # Two sources that both print a decimal get the tight band they earned.
    assert values_conflict(
        _c(22.0, unit="pp", verbatim="22.0"),
        _c(22.4, unit="pp", doc="doc-b", verbatim="22.4"),
        tolerance=efficiency,
    ).conflicts


def test_an_integer_value_claims_no_decimals_it_never_had() -> None:
    """`float(22)` reprs as `22.0`, so reading precision off the parsed value
    would hold a sheet printing `22` to one decimal place it never printed —
    tightening the floor from 0.5 to 0.05 on every integer in the corpus."""
    efficiency = tolerance_for("module_efficiency_pct")
    assert not values_conflict(
        _c(22, unit="pp"), _c(22.4, unit="pp", doc="doc-b"), tolerance=efficiency
    ).conflicts


def test_the_verbatim_text_outranks_the_parsed_value_for_precision() -> None:
    """The real extraction shape: `22` on the page becomes the float 22.0 in the
    store, and `verbatim_value` is then the only surviving record that the source
    printed no decimal. Ignoring it applies a band the sheet cannot express."""
    efficiency = tolerance_for("module_efficiency_pct")
    coarse = _c(22.0, unit="pp", verbatim="22")
    fine = _c(22.4, unit="pp", doc="doc-b", verbatim="22.4")
    assert not values_conflict(coarse, fine, tolerance=efficiency).conflicts


def test_a_relative_band_is_referred_to_the_larger_magnitude() -> None:
    """Not just symmetric — which magnitude. Referring to the smaller value gives
    a tighter band, and the two verdicts differ on a real window: at 1% of ~100,
    a gap of 1.005 conflicts against the smaller and agrees against the larger.

    Symmetry alone does not catch this, because min and max are both symmetric."""
    a = _c(100.0, unit="kVA", verbatim="100.0")
    b = _c(101.005, unit="kVA", doc="doc-b", verbatim="101.005")
    assert not values_conflict(a, b, tolerance=AC_POWER).conflicts
    assert values_conflict(
        a, _c(101.02, unit="kVA", doc="doc-b", verbatim="101.02"), tolerance=AC_POWER
    ).conflicts


def test_a_relative_band_does_not_depend_on_argument_order() -> None:
    """Referred to the larger magnitude. Against the smaller, the predicate is
    asymmetric and the queue would depend on which candidate came first."""
    a = _c(352.0, unit="kVA")
    b = _c(355.0, unit="kVA", doc="doc-b")
    assert (
        values_conflict(a, b, tolerance=AC_POWER).conflicts
        == values_conflict(b, a, tolerance=AC_POWER).conflicts
    )


# --- one-sided ----------------------------------------------------------------


def test_under_guarantee_is_never_a_nonconformity() -> None:
    """IEC 60076-1 Table 1: an omitted direction is unrestricted. A measured loss
    below the declared one is not a disagreement, however far below."""
    declared = _c(5000.0, tier=SourceTier.SYSTEM_OF_RECORD)
    measured_low = _c(3000.0, tier=SourceTier.WEB_SUPPLEMENT, doc="doc-b")
    assert not values_conflict(declared, measured_low, tolerance=TOTAL_LOSS).conflicts


def test_over_guarantee_beyond_the_limit_is_a_conflict() -> None:
    """+10% on 5000 W is 500 W. 5400 passes, 5600 does not."""
    declared = _c(5000.0, tier=SourceTier.SYSTEM_OF_RECORD)
    assert not values_conflict(
        declared, _c(5400.0, tier=SourceTier.WEB_SUPPLEMENT, doc="doc-b"), tolerance=TOTAL_LOSS
    ).conflicts
    assert values_conflict(
        declared, _c(5600.0, tier=SourceTier.WEB_SUPPLEMENT, doc="doc-b"), tolerance=TOTAL_LOSS
    ).conflicts


def test_the_one_sided_test_is_not_orientation_dependent() -> None:
    """The declared side comes from the tier, not from argument position, or the
    same pair would give opposite verdicts depending on how it was passed."""
    declared = _c(5000.0, tier=SourceTier.SYSTEM_OF_RECORD)
    measured = _c(5600.0, tier=SourceTier.WEB_SUPPLEMENT, doc="doc-b")
    assert (
        values_conflict(declared, measured, tolerance=TOTAL_LOSS).conflicts
        == values_conflict(measured, declared, tolerance=TOTAL_LOSS).conflicts
    )


def test_the_one_sided_allowance_does_not_apply_between_two_declarations() -> None:
    """IEC's +15% is how far a *measured* loss may exceed a *guaranteed* one. It
    says nothing about two documents disagreeing on what was guaranteed.

    Two datasheets stating 100 kW and 109 kW of no-load loss are two
    declarations, and 9% is exactly the disagreement a reviewer needs to see.
    Applying the measurement allowance symmetrically absorbed it silently — the
    band came out at 16.35 and the conflict never reached the queue."""
    component = tolerance_for("transformer_no_load_loss_w")
    assert component.rule is ToleranceRule.ONE_SIDED
    sheet_a = _c(100.0, unit="kW", verbatim="100 kW")
    sheet_b = _c(109.0, unit="kW", doc="doc-b", verbatim="109 kW")
    verdict = values_conflict(sheet_a, sheet_b, tolerance=component)
    assert verdict.conflicts
    assert verdict.conflict_class is ConflictClass.INTER_DOCUMENT

    # Still no conflict where the measurement genuinely is within the allowance.
    report = _c(109.0, unit="kW", tier=SourceTier.WEB_SUPPLEMENT, doc="doc-b", verbatim="109 kW")
    assert not values_conflict(sheet_a, report, tolerance=component).conflicts


def test_two_declarations_are_compared_at_printed_precision() -> None:
    """Falling back to the rounding floor, not to zero: two sheets printing `100`
    and `100.4` differ by less than either could express."""
    component = tolerance_for("transformer_no_load_loss_w")
    coarse = _c(100.0, unit="kW", verbatim="100")
    fine = _c(100.4, unit="kW", doc="doc-b", verbatim="100.4")
    assert not values_conflict(coarse, fine, tolerance=component).conflicts
    assert values_conflict(
        _c(100.0, unit="kW", verbatim="100.0"),
        _c(100.4, unit="kW", doc="doc-b", verbatim="100.4"),
        tolerance=component,
    ).conflicts


def test_a_same_tier_gap_beyond_precision_is_still_a_conflict() -> None:
    a = _c(5000.0, tier=SourceTier.SYSTEM_OF_RECORD)
    b = _c(3000.0, tier=SourceTier.SYSTEM_OF_RECORD, doc="doc-b")
    assert values_conflict(a, b, tolerance=TOTAL_LOSS).conflicts
    assert values_conflict(b, a, tolerance=TOTAL_LOSS).conflicts


# --- declared bands -----------------------------------------------------------


def test_a_printed_band_supersedes_the_config_default() -> None:
    """Canadian Solar's `0~+10W` is two bin steps, so 650 and 655 have overlapping
    guaranteed ranges as printed — even though ±1 W would call them a conflict."""
    band = DeclaredBand(low=0.0, high=10.0, kind=ToleranceKind.ABSOLUTE, unit="W")
    declared_field = FIELD_TOLERANCES["power_tolerance"]
    verdict = values_conflict(
        _c(650.0), _c(655.0, doc="doc-b"), tolerance=declared_field, band_a=band, band_b=band
    )
    assert not verdict.conflicts
    assert values_conflict(_c(650.0), _c(655.0, doc="doc-b"), tolerance=NAMEPLATE).conflicts


def test_a_declared_band_field_with_no_bands_falls_back_to_precision() -> None:
    """An honest extractor that found no printed tolerance must not be treated as
    having found an infinitely wide one."""
    declared_field = FIELD_TOLERANCES["power_tolerance"]
    assert values_conflict(_c(650.0), _c(700.0, doc="doc-b"), tolerance=declared_field).conflicts


def test_a_band_on_only_one_side_is_still_applied() -> None:
    """The datasheet prints a band, the supply agreement does not. Ignoring the
    one band available would raise a conflict the datasheet itself resolves."""
    band = DeclaredBand(low=0.0, high=10.0, kind=ToleranceKind.ABSOLUTE, unit="W")
    declared_field = FIELD_TOLERANCES["power_tolerance"]
    assert not values_conflict(
        _c(650.0), _c(655.0, doc="doc-b"), tolerance=declared_field, band_a=band
    ).conflicts
    assert not values_conflict(
        _c(655.0), _c(650.0, doc="doc-b"), tolerance=declared_field, band_b=band
    ).conflicts


# --- refusals -----------------------------------------------------------------


def test_mismatched_conditions_raise_rather_than_returning_no_conflict() -> None:
    """'We did not compare these' rendered as 'these agree' is the invisible false
    negative this module exists to prevent."""
    with pytest.raises(IncomparableCandidatesError):
        values_conflict(
            _c(352.0, condition=Condition(temperature_c=30.0)),
            _c(320.865, condition=Condition(temperature_c=40.0), doc="doc-b"),
            tolerance=AC_POWER,
        )


def test_a_never_compare_field_raises() -> None:
    """kVA against kW is not a wide tolerance; it is not a comparison."""
    with pytest.raises(IncomparableCandidatesError):
        values_conflict(
            _c(352.0), _c(320.0, doc="doc-b"), tolerance=tolerance_for("inverter_power_kva_vs_kw")
        )


def test_a_bool_is_not_a_number() -> None:
    """`True == 1` in Python, so a bool slipping into a numeric field would
    compare equal to a 1.0 nameplate and no tolerance would catch it."""
    verdict = values_conflict(_c(True), _c(1.0, doc="doc-b"), tolerance=NAMEPLATE)
    assert verdict.conflicts


# --- classification -----------------------------------------------------------


def test_the_conflict_class_is_derived_from_the_candidates() -> None:
    """Passing it in would let the class drift from the evidence it describes."""
    same_doc = values_conflict(_c(650.0), _c(700.0), tolerance=NAMEPLATE)
    assert same_doc.conflict_class is ConflictClass.INTRA_DOCUMENT

    cross_doc = values_conflict(_c(650.0), _c(700.0, doc="doc-b"), tolerance=NAMEPLATE)
    assert cross_doc.conflict_class is ConflictClass.INTER_DOCUMENT

    cross_tier = values_conflict(
        _c(650.0), _c(700.0, tier=SourceTier.WEB_SUPPLEMENT, doc="doc-b"), tolerance=NAMEPLATE
    )
    assert cross_tier.conflict_class is ConflictClass.RECORD_VS_WEB


def test_no_conflict_carries_no_class() -> None:
    """A class on an agreement would populate the workbook's Conflicts tab with
    entries nobody has to act on."""
    verdict = values_conflict(_c(650.0), _c(650.0, doc="doc-b"), tolerance=NAMEPLATE)
    assert not verdict.conflicts
    assert verdict.conflict_class is None


# --- the table ----------------------------------------------------------------


def test_an_unassigned_field_is_exact_not_permissive() -> None:
    """A field nobody has assigned a tolerance to is one nobody has measured the
    spread of. A guessed band merges silently; exactness raises a reviewable item."""
    assert tolerance_for("some_field_nobody_has_specified").rule is ToleranceRule.EXACT


def test_every_table_row_is_internally_consistent() -> None:
    """A magnitude on an EXACT row would read as a tolerance and be silently
    ignored — a band nobody sees was never applied."""
    for name, row in FIELD_TOLERANCES.items():
        needs_magnitude = row.rule in (
            ToleranceRule.ABSOLUTE,
            ToleranceRule.RELATIVE,
            ToleranceRule.ONE_SIDED,
        )
        assert (row.magnitude is not None) is needs_magnitude, name
        assert row.basis, f"{name} has no stated basis"


def test_a_magnitude_on_a_non_numeric_rule_is_rejected() -> None:
    with pytest.raises(ValueError):
        FieldTolerance(rule=ToleranceRule.EXACT, magnitude=1.0)
    with pytest.raises(ValueError):
        FieldTolerance(rule=ToleranceRule.ABSOLUTE)


def test_transformer_losses_are_one_sided_in_the_table() -> None:
    """Writing them as `±` contradicts both IEC and IEEE, and an earlier draft
    of D-2's table did exactly that."""
    for name in (
        "transformer_total_loss_w",
        "transformer_no_load_loss_w",
        "transformer_load_loss_w",
        "transformer_no_load_current_pct",
    ):
        assert FIELD_TOLERANCES[name].rule is ToleranceRule.ONE_SIDED, name


def test_nameplate_is_not_a_relative_band() -> None:
    """99.1% of 21,989 CEC rows have a nameplate that is an exact multiple of
    5 W. The ±3% Trina prints is flash-test uncertainty, not label tolerance."""
    assert FIELD_TOLERANCES["nameplate_power_w"].rule is ToleranceRule.ABSOLUTE
    assert FIELD_TOLERANCES["nameplate_power_w"].magnitude == pytest.approx(1.0)


def test_a_verdict_explains_itself() -> None:
    """FR-HITL-03: the queue has to say why, and '650 vs 700' alone is not why."""
    verdict = values_conflict(
        _c(650.0, condition=Condition(basis=MeasurementBasis.STC)),
        _c(700.0, condition=Condition(basis=MeasurementBasis.STC), doc="doc-b"),
        tolerance=NAMEPLATE,
    )
    assert verdict.conflicts
    assert "650" in verdict.reason and "700" in verdict.reason
