"""Whether two values actually disagree — issue #1, clarifications D-2, task E.1.

The global `numeric_conflict_tolerance` is gone. 2% of a 650 W nameplate is 13 W,
which merges three adjacent 5 W SKUs; the same 2% on a −0.29 %/degC temperature
coefficient is far below datasheet precision. One number cannot be right for both.
"""

import pathlib
import re
from decimal import Decimal

import pytest

from procurement_agent.schema import (
    Condition,
    ConflictCandidate,
    ConflictClass,
    DeclaredBand,
    MeasurementBasis,
    SourceRef,
    SourceTier,
    ToleranceCondition,
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
    NEVER_COMPARABLE,
    UNIMPLEMENTED_D2_ROWS,
    FieldTolerance,
)

NAMEPLATE = tolerance_for("nameplate_power")
GAMMA = tolerance_for("temp_coeff_pmax")
AC_POWER = tolerance_for("rated_ac_power")
NO_LOAD_LOSS = tolerance_for("no_load_loss")


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


def test_one_missing_unit_does_not_suppress_the_disagreement() -> None:
    """The gate read `a.unit is not None and b.unit is not None and they differ`,
    so **the permissive branch sat on the suppressing side**.

    A dropped unit is representable — `ConflictCandidate.unit` is `str | None` —
    and with one side missing, the whole check was skipped and the pair fell
    through to a numeric comparison in whatever unit each side happened to be in.
    `0.35` against `0.35 USD/kW` came back "no conflict" on a 1000x price error,
    on a Tier A field, with no queue entry and the compose gate never firing.

    Note the inversion the old form produced: `Wp` vs `W` was *raised* (a false
    positive) while `None` vs `kW` was *silently accepted*. The module's stated
    priority is the other way round — suppression is a spec violation under
    tasks.md E.3a, noise is not.
    """
    verdict = values_conflict(_c(0.35, unit=None), _c(0.35, unit="USD/kW"), tolerance=NAMEPLATE)
    assert verdict.conflicts
    assert verdict.conflict_class is ConflictClass.UNIT_NORMALIZATION
    assert "no unit" in verdict.reason


def test_two_missing_units_are_still_one_unitless_quantity() -> None:
    """The other side of the same change, and the reason it cannot simply
    compare `a.unit != b.unit`: every text-valued contract field carries
    `unit=None` on both sides, and those must keep comparing normally rather
    than becoming a unit conflict apiece."""
    verdict = values_conflict(
        _c("China", unit=None), _c("China", unit=None), tolerance=DEFAULT_TOLERANCE
    )
    assert not verdict.conflicts


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


def test_percent_per_kelvin_is_the_same_unit_as_percent_per_degree_celsius() -> None:
    """FN-5. A temperature *coefficient* is per-degree-*interval*, and one degree
    Celsius is one kelvin as an interval — so `%/degC`, `%/K` and `%/°C` are
    three spellings of one unit needing **no conversion**.

    Three documents say so: the frozen contract's Conditions table
    ("`%/degC` ≡ `%/K`"), tasks.md B.3 (⚠️-marked), and clarifications.md under
    the heading "The unit conversion that must NOT happen".

    `_normalise_text` is NFKC, case and whitespace only, so `'%/degc' != '%/k'`
    and **every** temperature-coefficient comparison between a K-quoting source
    and a degC-quoting one came back a `UNIT_NORMALIZATION` conflict. All three
    coefficients are on contract and every PV datasheet carries them, so this is
    a per-module, per-pair queue item on a field that never disagreed.

    ⚠️ Aliased, never converted. A generic unit library applies the +273.15
    offset and silently destroys the value — `-0.29 %/K` becoming `272.86` is a
    number that passes every plausibility gate B.5 states except the sign.
    """
    for kelvin in ("%/K", "%/k", "% / K"):
        verdict = values_conflict(
            _c(-0.29, unit="%/degC"),
            _c(-0.29, unit=kelvin, doc="doc-b"),
            tolerance=GAMMA,
            field_name="temp_coeff_pmax",
        )
        assert not verdict.conflicts, kelvin
        assert verdict.conflict_class is not ConflictClass.UNIT_NORMALIZATION, kelvin


def test_the_degree_sign_spelling_is_the_same_unit_too() -> None:
    """`%/°C` is what a datasheet actually prints, and `℃` (U+2103) is what OCR
    leaves behind. The second folds to the first under NFKC already; the first
    has to reach `%/degC` through the alias, or a sheet printing the symbol and
    one printing the word are a unit conflict."""
    for printed in ("%/°C", "%/℃", "%/degC", "%/K"):
        assert not values_conflict(
            _c(-0.29, unit="%/degC"),
            _c(-0.29, unit=printed, doc="doc-b"),
            tolerance=GAMMA,
            field_name="temp_coeff_pmax",
        ).conflicts, printed


def test_the_alias_is_not_a_licence_to_normalise_other_units() -> None:
    """The alias closes one documented equivalence. It must not widen into
    "units that look similar are the same": `W` against `kW` is a 1000x
    extraction error and D-2 is explicit that a unit mismatch is never resolved
    by tolerance. Kelvin *alone* is a temperature, not an interval — a value in
    `K` is not a value in `%/K`, and `300 K` is not `300 degC`.

    That last pair is the one that matters most, and it is the case a folding
    rule reaches by accident: an implementation that rewrites `k` to `degc`
    wherever it occurs, rather than looking up two whole spellings, makes `K`
    and `degC` one unit - and the +273.15 those two really are apart is the
    exact error the alias exists to keep out of this codebase. Verified against
    that mutation: without this assertion it survives the whole suite."""
    ambient = tolerance_for("rated_ac_power_temp")
    assert values_conflict(
        _c(300.0, unit="K"), _c(300.0, unit="degC", doc="doc-b"), tolerance=ambient
    ).conflicts
    assert values_conflict(
        _c(-0.29, unit="%/degC"), _c(-0.29, unit="K", doc="doc-b"), tolerance=GAMMA
    ).conflicts
    assert values_conflict(
        _c(-0.29, unit="%/degC"), _c(-0.29, unit="degC", doc="doc-b"), tolerance=GAMMA
    ).conflicts
    assert values_conflict(
        _c(650.0, unit="W"), _c(650.0, unit="kW", doc="doc-b"), tolerance=NAMEPLATE
    ).conflicts
    assert values_conflict(
        _c(0.35, unit="USD / W"), _c(0.35, unit="USD/kW", doc="doc-b"), tolerance=NAMEPLATE
    ).conflicts


def test_a_real_coefficient_disagreement_still_survives_the_alias() -> None:
    """The direction the alias must not swallow. Folding the unit removes the
    unit conflict and *hands the pair to the numeric comparison*, which is the
    point — two sheets quoting -0.29 and -0.33 %/K still disagree."""
    verdict = values_conflict(
        _c(-0.29, unit="%/degC"),
        _c(-0.33, unit="%/K", doc="doc-b"),
        tolerance=GAMMA,
        field_name="temp_coeff_pmax",
    )
    assert verdict.conflicts
    assert verdict.conflict_class is ConflictClass.INTER_DOCUMENT


def test_an_exact_rule_still_honours_the_rounding_floor() -> None:
    """Otherwise `1500` vs `1500.0` on max system voltage would be a conflict."""
    exact = tolerance_for("max_system_voltage")
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
    efficiency = tolerance_for("module_efficiency")
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
    efficiency = tolerance_for("module_efficiency")
    assert not values_conflict(
        _c(22, unit="pp"), _c(22.4, unit="pp", doc="doc-b"), tolerance=efficiency
    ).conflicts


def test_the_verbatim_text_outranks_the_parsed_value_for_precision() -> None:
    """The real extraction shape: `22` on the page becomes the float 22.0 in the
    store, and `verbatim_value` is then the only surviving record that the source
    printed no decimal. Ignoring it applies a band the sheet cannot express."""
    efficiency = tolerance_for("module_efficiency")
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
    assert not values_conflict(declared, measured_low, tolerance=NO_LOAD_LOSS).conflicts


def test_over_guarantee_beyond_the_limit_is_a_conflict() -> None:
    """IEC Table 1 item 1b: +15% on a component loss. 5700 passes, 5800 does not."""
    assert NO_LOAD_LOSS.magnitude == pytest.approx(0.15)
    declared = _c(5000.0, tier=SourceTier.SYSTEM_OF_RECORD)
    assert not values_conflict(
        declared, _c(5700.0, tier=SourceTier.WEB_SUPPLEMENT, doc="doc-b"), tolerance=NO_LOAD_LOSS
    ).conflicts
    assert values_conflict(
        declared, _c(5800.0, tier=SourceTier.WEB_SUPPLEMENT, doc="doc-b"), tolerance=NO_LOAD_LOSS
    ).conflicts


def test_the_one_sided_test_is_not_orientation_dependent() -> None:
    """The declared side comes from the tier, not from argument position, or the
    same pair would give opposite verdicts depending on how it was passed."""
    declared = _c(5000.0, tier=SourceTier.SYSTEM_OF_RECORD)
    measured = _c(5600.0, tier=SourceTier.WEB_SUPPLEMENT, doc="doc-b")
    assert (
        values_conflict(declared, measured, tolerance=NO_LOAD_LOSS).conflicts
        == values_conflict(measured, declared, tolerance=NO_LOAD_LOSS).conflicts
    )


def test_the_one_sided_allowance_does_not_apply_between_two_declarations() -> None:
    """IEC's +15% is how far a *measured* loss may exceed a *guaranteed* one. It
    says nothing about two documents disagreeing on what was guaranteed.

    Two datasheets stating 100 kW and 109 kW of no-load loss are two
    declarations, and 9% is exactly the disagreement a reviewer needs to see.
    Applying the measurement allowance symmetrically absorbed it silently — the
    band came out at 16.35 and the conflict never reached the queue."""
    component = tolerance_for("no_load_loss")
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
    component = tolerance_for("no_load_loss")
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
    assert values_conflict(a, b, tolerance=NO_LOAD_LOSS).conflicts
    assert values_conflict(b, a, tolerance=NO_LOAD_LOSS).conflicts


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
    one band available would raise a conflict the datasheet itself resolves.

    The banded nominal must be the *lower* of the two, or the test cannot tell
    which nominal the band was applied to: with `a - b = +/-5` and a `0~+10 W`
    band, applying it to the wrong side gives the same verdict. A 647 W agreement
    against a 650 W module guaranteeing `[650, 655]` is a real disagreement, and
    swapping the arguments in the one-band branch silently absorbed it."""
    band = DeclaredBand(low=0.0, high=5.0, kind=ToleranceKind.ABSOLUTE, unit="W")
    declared_field = FIELD_TOLERANCES["power_tolerance"]
    # 647 is below [650, 655] — the band cannot reach it in either direction.
    assert values_conflict(
        _c(647.0), _c(650.0, doc="doc-b"), tolerance=declared_field, band_b=band
    ).conflicts
    assert values_conflict(
        _c(650.0), _c(647.0, doc="doc-b"), tolerance=declared_field, band_a=band
    ).conflicts
    # 653 is inside [650, 655], so the band resolves it.
    assert not values_conflict(
        _c(653.0), _c(650.0, doc="doc-b"), tolerance=declared_field, band_b=band
    ).conflicts
    assert not values_conflict(
        _c(650.0), _c(653.0, doc="doc-b"), tolerance=declared_field, band_a=band
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
    """kVA against kW is not a wide tolerance; it is not a comparison.

    Built here rather than fetched by name. The row this used to call
    `tolerance_for("inverter_power_kva_vs_kw")` for was keyed on a name the
    frozen contract does not have, so the test drove the guard through a string
    no caller could ever pass - full branch coverage over an unreachable branch.
    """
    with pytest.raises(IncomparableCandidatesError):
        values_conflict(
            _c(352.0),
            _c(320.0, doc="doc-b"),
            tolerance=FieldTolerance(rule=ToleranceRule.NEVER_COMPARE, basis="test"),
        )


def test_the_kva_versus_kw_row_is_accounted_for() -> None:
    """D-2 line 100 says inverter kVA vs kW is never compared, and the contract
    gives no key to hang that on: `rated_ac_power` is defined in kVA and there is
    no kW sibling, so a kW value for it is a unit mismatch, not a second field.

    Recorded rather than invented. The row previously sat in `NEVER_COMPARABLE`
    under a made-up key, which read as an enforced rule while being unreachable.
    """
    assert any("kva" in name.lower() for name in UNIMPLEMENTED_D2_ROWS)
    verdict = values_conflict(
        _c(352.0, unit="kVA"), _c(320.0, unit="kW", doc="doc-b"), tolerance=AC_POWER
    )
    assert verdict.conflicts
    assert verdict.conflict_class is ConflictClass.UNIT_NORMALIZATION


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
    for name in ("no_load_loss", "load_loss"):
        assert FIELD_TOLERANCES[name].rule is ToleranceRule.ONE_SIDED, name


def test_nameplate_is_not_a_relative_band() -> None:
    """99.1% of 21,989 CEC rows have a nameplate that is an exact multiple of
    5 W. The ±3% Trina prints is flash-test uncertainty, not label tolerance."""
    assert FIELD_TOLERANCES["nameplate_power"].rule is ToleranceRule.ABSOLUTE
    assert FIELD_TOLERANCES["nameplate_power"].magnitude == pytest.approx(1.0)


def test_a_verdict_explains_itself() -> None:
    """FR-HITL-03: the queue has to say why, and '650 vs 700' alone is not why."""
    verdict = values_conflict(
        _c(650.0, condition=Condition(basis=MeasurementBasis.STC)),
        _c(700.0, condition=Condition(basis=MeasurementBasis.STC), doc="doc-b"),
        tolerance=NAMEPLATE,
    )
    assert verdict.conflicts
    assert "650" in verdict.reason and "700" in verdict.reason


# --- the table against the frozen contract ------------------------------------


def _contract_keys() -> set[str]:
    contract = pathlib.Path(__file__).parent.parent / (
        "specs/001-procurement-agent/contracts/canonical-parameters.md"
    )
    text = contract.read_text(encoding="utf-8")
    keys = {m.group(1) for m in re.finditer(r"^\|\s*`([a-z0-9_]+)`\s*\|", text, re.MULTILINE)}
    assert len(keys) > 50, "the contract's parameter tables did not parse"
    return keys


def test_every_tolerance_key_is_a_contract_key() -> None:
    """The defect this exists to prevent, and it shipped: 19 of the table's 20
    keys were invented names (`transformer_no_load_loss_w` where the contract says
    `no_load_loss`), so `tolerance_for` fell through to `DEFAULT_TOLERANCE` for
    every real field.

    Silent, and worse than a tighter band — it inverted the transformer loss rule.
    A measured loss *below* the contract guarantee, which IEC 60076-1 Table 1 says
    is never a nonconformity, became a queued conflict; everything else failed
    toward queue inflation, which D-1 names as the worst outcome for a HITL tool.
    """
    unknown = (set(FIELD_TOLERANCES) | set(NEVER_COMPARABLE)) - _contract_keys()
    assert not unknown, (
        f"tolerance rows keyed on names the frozen contract does not have: {unknown}"
    )


def test_every_tolerance_condition_is_wired_or_accounted_for() -> None:
    """A discriminator no row selects is a branch that can never run.

    `_magnitude_matches_rule` already refuses half a conditional row, because
    "one without the other is a branch that can never be selected". The same
    hazard lives one level up: a `ToleranceCondition` member that no
    `FieldTolerance` names is dead in exactly the same way, and silence is what
    let the invented-key defect survive four commits.
    """
    from procurement_agent.services.conflict_hitl.tolerance import UNWIRED_TOLERANCE_CONDITIONS

    wired = {
        row.alternate_when
        for row in (*FIELD_TOLERANCES.values(), *NEVER_COMPARABLE.values())
        if row.alternate_when is not None
    }
    assert wired.isdisjoint(UNWIRED_TOLERANCE_CONDITIONS), (
        "a condition cannot be both wired to a row and recorded as unwired"
    )
    assert wired | set(UNWIRED_TOLERANCE_CONDITIONS) == set(ToleranceCondition)
    for condition, why in UNWIRED_TOLERANCE_CONDITIONS.items():
        assert len(why) > 40, f"{condition} has no stated reason"


def test_no_d2_row_is_dropped_without_saying_so() -> None:
    """D-2 has rows this table cannot express. Silence is what made the
    invented-key defect invisible, so each is named rather than left out.

    `inverter kVA vs kW` joined them: it had been sitting in `NEVER_COMPARABLE`
    under a key the frozen contract does not have, which read as an enforced rule
    while being unreachable.
    """
    assert set(UNIMPLEMENTED_D2_ROWS) == {
        "transformer total losses",
        "transformer no-load current",
        "transformer MVA per cooling class",
        "inverter kVA vs kW",
    }
    for name, why in UNIMPLEMENTED_D2_ROWS.items():
        assert len(why) > 40, f"{name} has no stated reason"


@pytest.mark.parametrize(
    "key,magnitude",
    [
        ("nameplate_power", 1.0),
        ("stc_rating", 1.0),
        ("nmot_rating", 1.0),
        ("module_efficiency", 0.1),
        ("temp_coeff_pmax", 0.01),
        ("temp_coeff_voc", 0.01),
        ("temp_coeff_isc", 0.005),
        ("degradation_year_1", 0.05),
        ("degradation_annual", 0.05),
        ("rated_ac_power", 0.01),
        ("max_efficiency", 0.05),
        ("cec_efficiency", 0.1),
        ("impedance_percent", 0.075),
        ("no_load_loss", 0.15),
        ("load_loss", 0.15),
        ("round_trip_efficiency", 0.2),
        ("usable_energy_per_container", 0.005),
        ("nameplate_energy_per_container", 0.005),
    ],
)
def test_every_magnitude_matches_d2(key: str, magnitude: float) -> None:
    """Twelve of seventeen magnitudes could be corrupted to 9.99 with the whole
    suite still green — and a transcription error lands in exactly that half. The
    rule was asserted; the number was not."""
    assert FIELD_TOLERANCES[key].magnitude == pytest.approx(magnitude)


def test_the_impedance_band_widens_below_ten_percent() -> None:
    """IEC 60076-1 Table 1 item 3a states two bands: ±7.5% at Z≥10%, ±10% below.
    Transcribing only the first is silent — it applies a band that is right half
    the time with nothing marking which half. 6.0 vs 6.5 is inside ±10% of 6.5
    (0.65) and outside ±7.5% (0.4875)."""
    impedance = tolerance_for("impedance_percent")
    assert impedance.alternate_magnitude == pytest.approx(0.10)
    low = values_conflict(
        _c(6.0, unit="%", verbatim="6.0"),
        _c(6.5, unit="%", doc="doc-b", verbatim="6.5"),
        tolerance=impedance,
    )
    assert not low.conflicts
    # At or above 10% the tighter band applies: 10.5 vs 11.4 exceeds 7.5% of 11.4.
    high = values_conflict(
        _c(10.5, unit="%", verbatim="10.5"),
        _c(11.4, unit="%", doc="doc-b", verbatim="11.4"),
        tolerance=impedance,
    )
    assert high.conflicts


def test_the_cec_band_widens_against_the_cec_list() -> None:
    """CEC's headline efficiency column is quantized to 0.5 pp — 21 distinct
    values across 2,104 rows — so datasheet-to-CEC gets 0.25 pp where
    datasheet-to-datasheet gets 0.1 pp."""
    cec = tolerance_for("cec_efficiency")
    sheet = _c(98.5, unit="%", verbatim="98.5")
    other_sheet = _c(98.7, unit="%", doc="doc-b", verbatim="98.7")
    assert values_conflict(sheet, other_sheet, tolerance=cec).conflicts

    listing = ConflictCandidate(
        value=98.7,
        unit="%",
        verbatim_value="98.7",
        condition=Condition(),
        source_tier=SourceTier.WEB_SUPPLEMENT,
        source_ref=SourceRef(url="https://example.invalid/list", source_authority="CEC listing"),
        confidence=0.9,
    )
    assert not values_conflict(sheet, listing, tolerance=cec).conflicts


def test_a_conditional_row_needs_both_halves() -> None:
    """A discriminator with no alternate band is a branch that can never fire."""
    with pytest.raises(ValueError):
        FieldTolerance(
            rule=ToleranceRule.RELATIVE,
            magnitude=0.075,
            alternate_when=ToleranceCondition.IMPEDANCE_BELOW_10_PCT,
        )
    with pytest.raises(ValueError):
        FieldTolerance(rule=ToleranceRule.RELATIVE, magnitude=0.075, alternate_magnitude=0.10)


def test_a_leading_qualifier_in_verbatim_does_not_set_the_precision() -> None:
    """`_decimals` read the first numeric token unconditionally, so a temperature
    or a standard number in front of the value decided the floor for the whole
    comparison: `"@ 25 degC: 22.35 %"` reported zero places, widening the floor to
    0.5 and absorbing a 0.45 pp disagreement — 4.5x the D-2 band.

    Fewer decimals means a *wider* floor, so this hid conflicts, and it turned on
    the extractor's formatting rather than on the data."""
    efficiency = tolerance_for("module_efficiency")
    qualified = _c(22.35, unit="%", verbatim="@ 25 degC: 22.35 %")
    other = _c(22.8, unit="%", doc="doc-b", verbatim="@ 25 degC: 22.8 %")
    assert values_conflict(qualified, other, tolerance=efficiency).conflicts


def test_a_thousands_separator_does_not_widen_the_rounding_floor() -> None:
    """The comma is the case the fix above did *not* cover, and the old assertion
    could not see it: it used `nameplate_power`, whose ABSOLUTE +/-1.0 W band
    exceeds any floor either reading produces, so `max(magnitude, floor)` returned
    1.0 whether the decimals were counted right or not.

    Under EXACT there is no magnitude, so the floor *is* the comparison - and
    EXACT is `DEFAULT_TOLERANCE`, the rule for every contract key D-2's table
    does not cover. `re.finditer` splits `125,000.50` into `125` and `000.50`,
    neither of which equals the parsed value, so the scan finds nothing and falls
    back to `repr(float)` - which drops the printed trailing zero and reports one
    decimal place instead of two, widening the floor tenfold.

    Pinned against the identical comparison without the separator: same numbers,
    same rule, so any difference in verdict is the formatting alone.
    """
    with_comma = values_conflict(
        _c(125000.50, unit="kWh", verbatim="$125,000.50"),
        _c(125000.48, unit="kWh", doc="doc-b", verbatim="$125,000.48"),
        tolerance=DEFAULT_TOLERANCE,
    )
    without_comma = values_conflict(
        _c(125000.50, unit="kWh", verbatim="$125000.50"),
        _c(125000.48, unit="kWh", doc="doc-b", verbatim="$125000.48"),
        tolerance=DEFAULT_TOLERANCE,
    )
    assert without_comma.conflicts, "0.02 apart at two printed decimals is a real disagreement"
    assert with_comma.conflicts, (
        "the same two values disagree by the same amount; a thousands separator "
        "in the source text must not decide whether the conflict is surfaced"
    )


def test_a_comma_joining_two_numbers_does_not_swallow_the_value() -> None:
    """Reading `,\\d{3}` as a thousands group is a guess, and it has to be the
    *second* guess.

    Two adjacent table cells whose separating whitespace was lost render as
    `650,700.20`, and a greedy separator-aware scan reads that as one number -
    650700.20, which is not the value, so nothing matches and the count falls back
    to `repr(float)` and its lost trailing zero. Scanning for bare digit runs, the
    thing the separator fix replaced, gets this one right.

    So both readings are tried. Neither tokenisation is correct on its own, and a
    token only counts when it equals the parsed value, so trying more of them
    cannot invent a match - it can only find the one that was there.
    """
    joined = values_conflict(
        _c(700.20, unit="ft2", verbatim="650,700.20 sqft"),
        _c(700.23, unit="ft2", doc="doc-b", verbatim="700.23 sqft"),
        tolerance=DEFAULT_TOLERANCE,
    )
    assert joined.conflicts, (
        "0.03 apart at two printed decimals; a comma joining the value to its "
        "neighbour must not widen the floor enough to absorb it"
    )


def test_the_most_precise_reading_of_the_value_wins() -> None:
    """When more than one token in the text equals the value, the count is the
    largest, not the first or the smallest.

    Under-reporting is the direction that hides conflicts - fewer decimals is a
    wider floor - so a tie has to break toward precision. If the source printed
    `22.30` anywhere, it expressed two decimals, and the fact that it also wrote
    `22.3` in prose beforehand does not withdraw that.

    Written against `min` first: with the least precise reading the floor widens
    to 0.05 and this 0.04 pp disagreement disappears.
    """
    verdict = values_conflict(
        _c(22.3, unit="%", verbatim="22.3 % (22.30 % as measured)"),
        _c(22.34, unit="%", doc="doc-b", verbatim="22.34 %"),
        tolerance=DEFAULT_TOLERANCE,
    )
    assert verdict.conflicts


def test_a_decimal_value_reports_its_own_precision() -> None:
    """`Decimal("650")` is the natural representation of exactly the catalog
    values D-2 calls EXACT, and routing it through `repr(float(...))` gave it a
    decimal place it never had."""
    # No verbatim, so the Decimal branch is the only thing reporting precision,
    # and a tolerance finer than one printed place is needed for it to matter:
    # nameplate's +/-1 W swamps the difference between a 0.5 and a 0.05 floor.
    efficiency = tolerance_for("module_efficiency")
    assert not values_conflict(
        _c(Decimal("22"), unit="%"), _c(22.4, unit="%", doc="doc-b"), tolerance=efficiency
    ).conflicts
    # Two sources that both printed a decimal still earn the tight band.
    assert values_conflict(
        _c(Decimal("22.0"), unit="%"), _c(22.4, unit="%", doc="doc-b"), tolerance=efficiency
    ).conflicts
