"""The per-field conflict tolerance table (clarifications D-2, task E.1).

There is deliberately no global `numeric_conflict_tolerance`. A 2% band on a
650 Wp nameplate is +/-13 W, which merges three adjacent 5 W SKUs; the same band
on a -0.29 %/degC temperature coefficient is far below datasheet precision. One
number cannot be right for both.

The table below is D-2's "starting tolerance table" transcribed, with D-2's own
confidence markers kept in `basis` so a reviewer can see which rows rest on
measured CEC data ([V]) and which on a standard read through secondary sources.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...schema import ToleranceRule


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
        return self


def _abs(magnitude: float, unit: str, basis: str) -> FieldTolerance:
    return FieldTolerance(rule=ToleranceRule.ABSOLUTE, magnitude=magnitude, unit=unit, basis=basis)


def _rel(magnitude: float, basis: str) -> FieldTolerance:
    return FieldTolerance(rule=ToleranceRule.RELATIVE, magnitude=magnitude, basis=basis)


def _one_sided(magnitude: float, basis: str) -> FieldTolerance:
    return FieldTolerance(rule=ToleranceRule.ONE_SIDED, magnitude=magnitude, basis=basis)


def _exact(basis: str) -> FieldTolerance:
    return FieldTolerance(rule=ToleranceRule.EXACT, basis=basis)


#: D-2's starting table, keyed by canonical field name.
#:
#: Rows D-2 marks "else no comparison" are *not* encoded as a wider band. The
#: condition gate already refuses those pairs (`Condition.comparable_with`), so
#: the tolerance here is the within-condition one and nothing has to restate the
#: cross-condition rule in a second place where it could drift.
FIELD_TOLERANCES: dict[str, FieldTolerance] = {
    "nameplate_power_w": _abs(1.0, "W", "5 W bins; +/-1 W absorbs `650` vs `650.0` only. High [V]"),
    "module_efficiency_pct": _abs(0.1, "pp", "Quoted to 1 dp. High [V]"),
    "gamma_pmax_pct_per_c": _abs(
        0.01,
        "%/degC",
        "Population spans p5 -0.386 .. p95 -0.278 (n=4,749); "
        "+/-0.01 is ~9% of the discriminating range. High [V]",
    ),
    "beta_voc_pct_per_c": _abs(0.01, "%/degC", "median -0.278. High [V]"),
    "alpha_isc_pct_per_c": _abs(0.005, "%/degC", "median 0.0454, quoted to 2-3 dp. High [V]"),
    "degradation_year_1_pct": _abs(0.05, "pp", "Contractual, quoted to 2 dp. High"),
    "degradation_annual_pct": _abs(0.05, "pp", "Contractual, quoted to 2 dp. High"),
    "max_system_voltage_v": _exact("Discrete 1000/1500; IEC and UL stored separately. High [V]"),
    "inverter_ac_power_kva": _rel(
        0.01, "Within one temperature only; 352/320/295 kVA are all 'rated'. High [V]"
    ),
    "inverter_max_efficiency_pct": _abs(0.05, "pp", "Quoted to 2 dp (`99.02`). High [V]"),
    "inverter_cec_efficiency_pct": _abs(
        0.1,
        "pp",
        "datasheet-to-datasheet. Against the CEC list use 0.25 pp: CEC's headline "
        "column is quantized to 0.5 pp, only 21 distinct values across 2,104 rows. High [V]",
    ),
    "bess_energy_mwh": _rel(0.005, "Within one (side, life-point); BOL vs EOL differ ~26%. High"),
    "bess_rte_pct": _abs(0.2, "pp", "Same boundary only; a boundary shift is worth 2-7 pp. High"),
    "power_tolerance": FieldTolerance(
        rule=ToleranceRule.DECLARED_BAND,
        basis="Three conventions in use: `0~+5 W`, `0~+10 W`, `0~+3%`. High [V]",
    ),
    "transformer_impedance_pct": _rel(
        0.075, "IEC 60076-1 Table 1 item 3a: +/-7.5% if Z>=10%, +/-10% if Z<10%. High [V]"
    ),
    "transformer_total_loss_w": _one_sided(0.10, "IEC Table 1 item 1a reads `+10 %`. High [V]"),
    "transformer_no_load_loss_w": _one_sided(
        0.15, "IEC Table 1 item 1b component losses, conditional on total. High [V]"
    ),
    "transformer_load_loss_w": _one_sided(
        0.15, "IEC Table 1 item 1b component losses, conditional on total. High [V]"
    ),
    "transformer_no_load_current_pct": _one_sided(0.30, "IEC Table 1 item 5. High [V]"),
}

#: Fields whose name is shared by genuinely different physical quantities.
NEVER_COMPARABLE: dict[str, FieldTolerance] = {
    "inverter_power_kva_vs_kw": FieldTolerance(
        rule=ToleranceRule.NEVER_COMPARE, basis="Different physical quantities. High"
    ),
}


#: The rule for anything not in the table. Exact, because a field nobody has
#: assigned a tolerance to is one nobody has measured the spread of, and a
#: guessed band silently merges values where exactness merely raises a reviewable
#: conflict. D-2 gives no default; this is the safe direction, recorded here
#: rather than buried in the comparison.
DEFAULT_TOLERANCE = _exact("Unassigned field - exact until D-2 gains a row. See tolerance.py")


def tolerance_for(field_name: str) -> FieldTolerance:
    """The tolerance row for a canonical field, falling back to exact."""
    if field_name in NEVER_COMPARABLE:
        return NEVER_COMPARABLE[field_name]
    return FIELD_TOLERANCES.get(field_name, DEFAULT_TOLERANCE)
