"""The per-field conflict tolerance table (clarifications D-2, task E.1).

There is deliberately no global `numeric_conflict_tolerance`. A 2% band on a
650 Wp nameplate is +/-13 W, which merges three adjacent 5 W SKUs; the same band
on a -0.29 %/degC temperature coefficient is far below datasheet precision. One
number cannot be right for both.

D-2's "starting tolerance table" transcribed, with D-2's own confidence markers
kept in `basis` so a reviewer can see which rows rest on measured CEC data ([V])
and which on a standard read through secondary sources.

**Keyed on the frozen contract's own `key` column.** An earlier version of this
table invented names - `transformer_no_load_loss_w` where the contract says
`no_load_loss`, `nameplate_power_w` where it says `nameplate_power` - and 19 of
its 20 keys matched nothing. `tolerance_for` falls back to EXACT, so every one of
those rows silently collapsed to the rounding floor: the transformer loss rule
inverted outright, turning a measured loss *below* guarantee into a queued
conflict. `test_every_tolerance_key_is_a_contract_key` now parses the contract
and fails on any key that is not in it.
"""

from __future__ import annotations

import math
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...schema import ToleranceCondition, ToleranceRule


def as_number(value: object) -> float | None:
    """A numeric reading of a candidate value, or None if it is not a number.

    `bool` is excluded even though it is an `int`: `True` comparing equal to a
    1.0 nameplate is nonsense that no tolerance would catch.

    Public, and here rather than in either caller, because it was two identical
    copies - `conflict_hitl._as_number` and `severity._numeric_value`. The
    second's docstring said it declined to import the first because reaching
    past an underscore "is how a helper import quietly becomes a second copy of
    the parent's comparison semantics", and described itself as "a second,
    smaller computation this module actually needs". It was neither smaller nor
    different: the two bodies matched line for line, so the copy the reasoning
    warned about is the one that existed. Both modules already import this one,
    and what counts as a number *is* tolerance semantics - extending it (a
    `Fraction`, a numpy scalar, a different NaN policy) must move conflict
    detection and severity together or they disagree silently about whether a
    candidate is comparable at all.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


class FieldTolerance(BaseModel):
    """One row of the D-2 table.

    `magnitude` means different things per rule and is deliberately not
    normalised into one unit: ABSOLUTE is in the field's own unit, RELATIVE and
    ONE_SIDED are fractions of the compared value, and the remaining three rules
    have no magnitude at all. Flattening them to a single float is what produced
    the global tolerance this table replaces.
    """

    model_config = ConfigDict(frozen=True)

    rule: ToleranceRule
    magnitude: float | None = Field(
        default=None,
        description=(
            "Absolute half-width in the field's unit (ABSOLUTE), or a fraction of "
            "the compared value (RELATIVE, ONE_SIDED). None for the other rules."
        ),
    )
    unit: str | None = Field(
        default=None, description="Unit `magnitude` is in, for ABSOLUTE rows. Documentation only."
    )
    alternate_when: ToleranceCondition | None = Field(
        default=None,
        description=(
            "Discriminator selecting `alternate_magnitude` instead of `magnitude`. "
            "Four D-2 rows state two bands; encoding only the first is silent, "
            "because the comparison then applies a band right half the time with "
            "nothing marking which half."
        ),
    )
    alternate_magnitude: float | None = Field(
        default=None, description="The band that applies when `alternate_when` holds."
    )
    basis: str = Field(default="", description="D-2's stated justification and confidence marker")

    _NUMERIC = (ToleranceRule.ABSOLUTE, ToleranceRule.RELATIVE, ToleranceRule.ONE_SIDED)

    @model_validator(mode="after")
    def _magnitude_matches_rule(self) -> FieldTolerance:
        if self.rule in self._NUMERIC:
            if self.magnitude is None:
                raise ValueError(f"{self.rule} needs a magnitude")
            if not math.isfinite(self.magnitude) or self.magnitude < 0:
                raise ValueError(f"{self.rule} magnitude must be finite and non-negative")
        elif self.magnitude is not None:
            # A magnitude on EXACT would read as a tolerance and be silently
            # ignored by the comparison, which is the failure that cannot be
            # reviewed: nobody sees a band that was never applied.
            raise ValueError(f"{self.rule} takes no magnitude, got {self.magnitude}")
        if (self.alternate_when is None) != (self.alternate_magnitude is None):
            raise ValueError(
                "a conditional row needs both `alternate_when` and `alternate_magnitude`; "
                "one without the other is a branch that can never be selected"
            )
        if self.alternate_magnitude is not None and (
            not math.isfinite(self.alternate_magnitude) or self.alternate_magnitude < 0
        ):
            raise ValueError("alternate magnitude must be finite and non-negative")
        return self


def _abs(
    magnitude: float,
    unit: str,
    basis: str,
    *,
    alternate_when: ToleranceCondition | None = None,
    alternate_magnitude: float | None = None,
) -> FieldTolerance:
    return FieldTolerance(
        rule=ToleranceRule.ABSOLUTE,
        magnitude=magnitude,
        unit=unit,
        basis=basis,
        alternate_when=alternate_when,
        alternate_magnitude=alternate_magnitude,
    )


def _rel(
    magnitude: float,
    basis: str,
    *,
    alternate_when: ToleranceCondition | None = None,
    alternate_magnitude: float | None = None,
) -> FieldTolerance:
    return FieldTolerance(
        rule=ToleranceRule.RELATIVE,
        magnitude=magnitude,
        basis=basis,
        alternate_when=alternate_when,
        alternate_magnitude=alternate_magnitude,
    )


def _one_sided(
    magnitude: float,
    basis: str,
    *,
    alternate_when: ToleranceCondition | None = None,
    alternate_magnitude: float | None = None,
) -> FieldTolerance:
    return FieldTolerance(
        rule=ToleranceRule.ONE_SIDED,
        magnitude=magnitude,
        basis=basis,
        alternate_when=alternate_when,
        alternate_magnitude=alternate_magnitude,
    )


def _exact(basis: str) -> FieldTolerance:
    return FieldTolerance(rule=ToleranceRule.EXACT, basis=basis)


#: D-2's starting table, keyed by the frozen contract's `key` column.
#:
#: Rows D-2 marks "else no comparison" are *not* encoded as a wider band. The
#: condition gate already refuses those pairs (`Condition.comparable_with`), so
#: the tolerance here is the within-condition one and nothing has to restate the
#: cross-condition rule in a second place where it could drift.
FIELD_TOLERANCES: dict[str, FieldTolerance] = {
    # --- PV modules ---
    "nameplate_power": _abs(1.0, "Wp", "5 W bins; +/-1 W absorbs `650` vs `650.0` only. High [V]"),
    "stc_rating": _abs(1.0, "Wp", "Same ladder as nameplate_power. High [V]"),
    "nmot_rating": _abs(1.0, "Wp", "Same ladder as nameplate_power. High [V]"),
    "module_efficiency": _abs(0.1, "%", "Quoted to 1 dp. High [V]"),
    "temp_coeff_pmax": _abs(
        0.01,
        "%/degC",
        "Population spans p5 -0.386 .. p95 -0.278 (n=4,749); "
        "+/-0.01 is ~9% of the discriminating range. High [V]",
    ),
    "temp_coeff_voc": _abs(0.01, "%/degC", "median -0.278. High [V]"),
    "temp_coeff_isc": _abs(0.005, "%/degC", "median 0.0454, quoted to 2-3 dp. High [V]"),
    "degradation_year_1": _abs(0.05, "%", "Contractual, quoted to 2 dp. High"),
    "degradation_annual": _abs(0.05, "%/yr", "Contractual, quoted to 2 dp. High"),
    "max_system_voltage": _exact("Discrete 1000/1500; IEC and UL stored separately. High [V]"),
    "power_tolerance": FieldTolerance(
        rule=ToleranceRule.DECLARED_BAND,
        basis="Three conventions in use: `0~+5 W`, `0~+10 W`, `0~+3%`. High [V]",
    ),
    "bifaciality_tolerance": FieldTolerance(
        rule=ToleranceRule.DECLARED_BAND,
        basis="Canadian Solar prints bifaciality then `Tolerance: +/- 5 %` on the next line.",
    ),
    # --- Inverters / PCS ---
    "rated_ac_power": _rel(
        0.01, "Within one temperature only; 352/320/295 kVA are all 'rated'. High [V]"
    ),
    "max_efficiency": _abs(0.05, "%", "Quoted to 2 dp (`99.02`). High [V]"),
    "cec_efficiency": _abs(
        0.1,
        "%",
        "0.1 pp datasheet-to-datasheet; 0.25 pp against the CEC list, whose headline "
        "column is quantized to 0.5 pp - only 21 distinct values across 2,104 rows. High [V]",
        alternate_when=ToleranceCondition.AGAINST_CEC_LIST,
        alternate_magnitude=0.25,
    ),
    # --- Transformers ---
    "impedance_percent": _rel(
        0.075,
        "IEC 60076-1 Table 1 item 3a, verbatim: +/-7.5% if Z>=10%, +/-10% if Z<10%. High [V]",
        alternate_when=ToleranceCondition.IMPEDANCE_BELOW_10_PCT,
        alternate_magnitude=0.10,
    ),
    "no_load_loss": _one_sided(
        0.15, "IEC Table 1 item 1b component losses, conditional on total. High [V]"
    ),
    "load_loss": _one_sided(
        0.15, "IEC Table 1 item 1b component losses, conditional on total. High [V]"
    ),
    "efficiency": _abs(0.05, "%", "Transformer efficiency, quoted to 2 dp. Reasoned"),
    "rating_mva": _exact("Exact per cooling class - see D-6 and the note below. High"),
    # --- BESS ---
    "usable_energy_per_container": _rel(
        0.005, "Within one (side, life-point); BOL vs EOL differ ~26%. High"
    ),
    "nameplate_energy_per_container": _rel(
        0.005, "Within one (side, life-point); BOL vs EOL differ ~26%. High"
    ),
    "round_trip_efficiency": _abs(
        0.2, "%", "Same boundary only; a boundary shift is worth 2-7 pp. High"
    ),
    "cycle_life": _exact("An integer count quoted to an SOH threshold; a difference is real. High"),
}

#: Fields whose name is shared by genuinely different physical quantities.
#:
#: Empty, and keyed on the frozen contract when it is not. It previously held one
#: row under `inverter_power_kva_vs_kw`, which is not a contract key - so
#: `tolerance_for` never returned it and the guard it configures was unreachable,
#: the same invented-name defect the table above was corrected for. That row is
#: now in `UNIMPLEMENTED_D2_ROWS`, and
#: `test_every_tolerance_key_is_a_contract_key` covers this dict too.
NEVER_COMPARABLE: dict[str, FieldTolerance] = {}

#: D-2 rows with no home in this table, recorded rather than dropped.
#:
#: Silence is what made the invented-key defect invisible for four commits, so an
#: unimplementable row is named here and asserted by a test rather than left to a
#: reader to notice.
UNIMPLEMENTED_D2_ROWS: dict[str, str] = {
    "transformer total losses": (
        "D-2 gives +10% (IEC) / +6% (IEEE), one-sided. The frozen contract has "
        "`no_load_loss` and `load_loss` as separate fields and no total-loss field, "
        "so there is nothing to key the row on. IEC Table 1 item 1b also makes the "
        "component bands conditional on the total not being exceeded, which is a "
        "cross-field constraint this per-field table cannot express."
    ),
    "transformer no-load current": (
        "D-2 gives +30% (IEC), one-sided. No contract field carries it."
    ),
    "transformer MVA per cooling class": (
        "`rating_mva_by_cooling` is a `dict[str, float]`, so comparing it is a "
        "per-key comparison rather than a scalar band. `rating_mva` above carries "
        "the scalar rule; the dict needs its own comparison path."
    ),
    "inverter kVA vs kW": (
        "D-2 says never compare - different physical quantities. There is no key "
        "to hang it on: the contract defines `rated_ac_power` in kVA and gives it "
        "no kW sibling, so a kW value for that field is a *unit* mismatch, not a "
        "second field. `values_conflict` already refuses to resolve it by "
        "tolerance: it *returns* a verdict classed UNIT_NORMALIZATION rather than "
        "raising `IncomparableCandidatesError`, which is the better outcome anyway "
        "- a reviewer sees the pair, where raising would stop the pipeline on it. "
        "Held here rather than under an invented key in NEVER_COMPARABLE."
    ),
}


#: Discriminators D-2 defines that no row in this table can select yet.
#:
#: `_magnitude_matches_rule` already refuses half a conditional row, because "one
#: without the other is a branch that can never be selected". A
#: `ToleranceCondition` no `FieldTolerance` names is dead the same way, one level
#: up - so it is recorded rather than left for a reader to notice, and
#: `test_every_tolerance_condition_is_wired_or_accounted_for` holds the two sets
#: to a partition of the enum.
UNWIRED_TOLERANCE_CONDITIONS: dict[ToleranceCondition, str] = {
    ToleranceCondition.REGIME_IEEE: (
        "Selects IEEE's +6% total-loss allowance over IEC's +10%. The row it "
        "discriminates is `transformer total losses`, which has no contract field "
        "to key on (see UNIMPLEMENTED_D2_ROWS), so nothing sets it. Kept because "
        "the distinction is D-2's and returns with the field, not dropped."
    ),
}


#: The rule for anything not in the table. Exact, because a field nobody has
#: assigned a tolerance to is one nobody has measured the spread of, and a
#: guessed band silently merges values where exactness merely raises a reviewable
#: conflict. D-2 gives no default; this is the safe direction, recorded here
#: rather than buried in the comparison.
DEFAULT_TOLERANCE = _exact("Unassigned field - exact until D-2 gains a row. See tolerance.py")


def tolerance_for(field_name: str) -> FieldTolerance:
    """The tolerance row for a canonical field, falling back to exact.

    `field_name` is the frozen contract's `key`, not a descriptive name: a key
    this table does not hold falls back silently, so a typo reads as a decision.
    """
    if field_name in NEVER_COMPARABLE:
        return NEVER_COMPARABLE[field_name]
    return FIELD_TOLERANCES.get(field_name, DEFAULT_TOLERANCE)
