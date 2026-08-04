"""Severity assignment for a detected conflict (open-decisions.md section 1).

`Severity` (schema/enums.py) and the compose gate (`orchestrator.blocking_conflicts`,
`orchestrator.compose_gate_blocks`) both already existed; nothing assigned a severity
to a detected conflict, so the gate was inert regardless of what it was fed. This
module is the assignment rule.

**A lookup, not a formula.** AIAG-VDA's 2019 FMEA handbook deleted RPN (severity x
occurrence x detection) because a product collapses distinguishable risk profiles
onto one number and lets a low severity be inflated by detection. So this module
never multiplies criticality by divergence: `CRITICALITY` fixes a base severity per
field from its criticality class, small bounded modifiers adjust it, and floors clamp
the result from below. Magnitude changes the *modifier*, never the base class.

**Keyed on the frozen contract's own `key` column**, exactly like
`tolerance.FIELD_TOLERANCES` and for the identical reason: a table keyed on invented
names falls through to a default and looks like a decision while being unreachable.
`tests/test_severity.py` parses the contract and fails on any key here that is not in
it, and - the direction `tolerance.py`'s own test does not check, added here because
completeness matters more for this table - on any contract key that is not here.

**The load-bearing invariant** (open-decisions.md:49): severity is a **pure function
of `(field_name, conflict_class, condition_group, candidate_set)`** - no clock, no
reviewer identity, no queue state. `assign_severity`'s signature holds exactly these
four and nothing else. `condition_group` and `candidate_set` are both
`Sequence[ConflictCandidate]`; open-decisions.md does not fix their shape, so this is
an interpretation, made explicit rather than left implicit: `candidate_set` is the
pair actually being compared (what a `ConflictQueueEntry.candidates` holds - see
`conflict_groupings`'s "exactly one comparable pair each"), and `condition_group` is
the wider set of candidates sharing the same condition that the pair was drawn from
(what `comparison_groups` partitions into) - needed only for the ">=3 distinct values"
modifier, which is a statement about the group a pair sits in, not about the pair
itself.
"""

from __future__ import annotations

import itertools
import math
import re
from collections.abc import Sequence
from decimal import Decimal

from ...schema import ConflictCandidate, ConflictClass, Severity, SourceTier, ToleranceRule
from .tolerance import FieldTolerance, tolerance_for

# --- the criticality-class lookup ----------------------------------------------
#
# One row per contract key, grouped by the five classes open-decisions.md #1
# defines. Comments are added only where the call is not the obvious reading of
# the class description - most rows follow directly from it.

CRITICALITY: dict[str, Severity] = {
    # --- Attestation / eligibility -> CRITICAL ---
    # Certifications, BABA/FEOC status, domestic content, country of origin,
    # ERCOT compliance items - a gap here is never inferable as a negative
    # (the CUAD absence-is-the-finding rule the Severity enum itself cites).
    "certifications": Severity.CRITICAL,
    "fire_safety_certifications": Severity.CRITICAL,
    "cell_certification": Severity.CRITICAL,
    "pcs_certification": Severity.CRITICAL,
    # A UL listing is a certification in different clothes - the same
    # presence/absence stakes as the fields named "certifications".
    "ul_listing": Severity.CRITICAL,
    "domestic_content_status": Severity.CRITICAL,
    "domestic_content_percentage": Severity.CRITICAL,
    "baba_status": Severity.CRITICAL,
    "baba_certification_ref": Severity.CRITICAL,
    "feoc_pfe_status": Severity.CRITICAL,
    "country_of_origin": Severity.CRITICAL,
    "ercot_compliance_items": Severity.CRITICAL,
    # --- Commercial -> HIGH ---
    # $/W, price, all warranty terms, material-assistance cost ratio.
    "price_per_watt_dc": Severity.HIGH,
    "price_per_watt_ac": Severity.HIGH,
    "price_per_metre": Severity.HIGH,
    "product_warranty_years": Severity.HIGH,
    "performance_warranty_years": Severity.HIGH,
    "performance_warranty_end_output": Severity.HIGH,
    "warranty_years": Severity.HIGH,
    "corrosion_warranty_years": Severity.HIGH,
    "degradation_warranty_years": Severity.HIGH,
    "degradation_warranty_cycles": Severity.HIGH,
    "material_assistance_cost_ratio": Severity.HIGH,
    # Not named as an example in either bucket. D-2 marks both "Contractual" -
    # they are the guaranteed degradation curve underwriting the performance
    # warranty above, not a free-standing measurement, so they are graded with
    # it rather than with the MEDIUM performance metrics. See the report for
    # this choice flagged as an ambiguity in open-decisions.md #1.
    "degradation_year_1": Severity.HIGH,
    "degradation_annual": Severity.HIGH,
    # The named exception: looks like a descriptive string field, is a
    # buildability field. D-6a: Dyn1 and Dyn11 are 60 degrees apart and cannot
    # be paralleled.
    "vector_group": Severity.HIGH,
    # --- Decision-driving performance -> MEDIUM ---
    # Nameplate power, efficiency, MVA, usable energy, RTE, cycle life,
    # ampacity, TRD - and their direct companions (a declared-band tolerance or
    # a required condition graded with the value it qualifies, not the value it
    # merely labels).
    "nameplate_power": Severity.MEDIUM,
    "power_tolerance": Severity.MEDIUM,  # qualifies nameplate_power directly
    "module_efficiency": Severity.MEDIUM,
    "stc_rating": Severity.MEDIUM,
    "nmot_rating": Severity.MEDIUM,
    # Energy-yield drivers, not label fields: population data spans p5 -0.386
    # to p95 -0.278 (tolerance.py), a real basis for ranking modules.
    "temp_coeff_pmax": Severity.MEDIUM,
    "temp_coeff_voc": Severity.MEDIUM,
    "temp_coeff_isc": Severity.MEDIUM,
    "rated_ac_power": Severity.MEDIUM,
    # Graded with rated_ac_power: a wrong temperature misattributes which of
    # three legitimate "rated" figures is meant (the Sungrow D-1 case).
    "rated_ac_power_temp": Severity.MEDIUM,
    "max_efficiency": Severity.MEDIUM,
    "cec_efficiency": Severity.MEDIUM,
    "trd_percent": Severity.MEDIUM,
    "trd_limit_applied": Severity.MEDIUM,
    # A required grid-interconnection capability, not a certification list -
    # graded as a capability spec that drives the engineering decision.
    "reactive_capability_at_zero_output": Severity.MEDIUM,
    "ride_through_coordination": Severity.MEDIUM,
    "automatic_generation_control": Severity.MEDIUM,
    "ercot_telemetry": Severity.MEDIUM,
    "pmu_support": Severity.MEDIUM,
    "rating_mva": Severity.MEDIUM,
    "rating_mva_by_cooling": Severity.MEDIUM,
    "impedance_percent": Severity.MEDIUM,
    "no_load_loss": Severity.MEDIUM,
    "load_loss": Severity.MEDIUM,
    "efficiency": Severity.MEDIUM,
    "ampacity": Severity.MEDIUM,
    "usable_energy_per_container": Severity.MEDIUM,
    "nameplate_energy_per_container": Severity.MEDIUM,
    "power_rating": Severity.MEDIUM,
    "c_rate": Severity.MEDIUM,
    "round_trip_efficiency": Severity.MEDIUM,
    "cycle_life": Severity.MEDIUM,
    "energy_density": Severity.MEDIUM,  # "footprint driver" per the contract
    "footprint_area": Severity.MEDIUM,
    # Structural/site-suitability specs: getting these wrong means specifying
    # equipment that cannot survive or perform at the site, the same
    # engineering-critical shape as ampacity.
    "design_wind_speed": Severity.MEDIUM,
    "stow_wind_speed": Severity.MEDIUM,
    "ground_coverage_ratio": Severity.MEDIUM,
    "backtracking_yield_gain": Severity.MEDIUM,
    "tracking_range": Severity.MEDIUM,
    "bearing_gear_l10_years": Severity.MEDIUM,  # an L10 design life, cycle_life's analogue
    # --- Secondary comparison -> LOW ---
    # MPPT count, harmonic spectrum, enclosure rating, conductor size,
    # protocols - comparison-relevant, not itself decision-driving.
    "mppt_count": Severity.LOW,
    "mppt_voltage_min": Severity.LOW,
    "mppt_voltage_max": Severity.LOW,
    "harmonic_spectrum": Severity.LOW,
    "thd_percent": Severity.LOW,
    "k_factor": Severity.LOW,
    "filtering_provisions": Severity.LOW,
    "dc_injection": Severity.LOW,
    "flicker_pst": Severity.LOW,
    "flicker_plt": Severity.LOW,
    "communication_protocols": Severity.LOW,
    "protocols": Severity.LOW,
    "cybersecurity_standards": Severity.LOW,
    "inverter_integration": Severity.LOW,
    "bess_integration": Severity.LOW,
    "ride_through_standards": Severity.LOW,
    "enclosure_rating": Severity.LOW,
    "conductor_size": Severity.LOW,
    "conductor_material": Severity.LOW,
    "conductor_area": Severity.LOW,
    "insulation_type": Severity.LOW,
    "shielding": Severity.LOW,
    "standards": Severity.LOW,
    "cooling_classes": Severity.LOW,
    "seismic_qualification": Severity.LOW,
    # Voltage-class/compatibility labels, not graded performance numbers - a
    # "does this fit the design" check rather than a ranked metric.
    "max_system_voltage": Severity.LOW,
    "max_dc_voltage": Severity.LOW,
    "voltage_class": Severity.LOW,
    "voltage_hv": Severity.LOW,
    "voltage_lv": Severity.LOW,
    "load_factor": Severity.LOW,
    "input_count": Severity.LOW,
    "fuse_rating": Severity.LOW,
    "continuous_current": Severity.LOW,
    "string_monitoring": Severity.LOW,
    "surge_protection": Severity.LOW,
    "disconnect_type": Severity.LOW,
    "chemistry": Severity.LOW,
    "thermal_management": Severity.LOW,
    "augmentation_plan": Severity.LOW,
    "cell_technology": Severity.LOW,
    "bifaciality_factor": Severity.LOW,
    "bifaciality_tolerance": Severity.LOW,  # qualifies bifaciality_factor directly
    "topology": Severity.LOW,
    "configuration": Severity.LOW,
    "modules_per_row": Severity.LOW,
    "galvanization_spec": Severity.LOW,
    "foundations_per_mw": Severity.LOW,
    # --- Descriptive -> INFORMATIONAL ---
    # Verbatim names, datasheet revision, stow strategy, support terms.
    "supplier": Severity.INFORMATIONAL,
    "supplier_verbatim": Severity.INFORMATIONAL,
    "model": Severity.INFORMATIONAL,
    "model_verbatim": Severity.INFORMATIONAL,
    "component_category": Severity.INFORMATIONAL,
    "datasheet_revision": Severity.INFORMATIONAL,
    "datasheet_date": Severity.INFORMATIONAL,
    "stow_strategy": Severity.INFORMATIONAL,
    "support_terms": Severity.INFORMATIONAL,
    "plant_controller_model": Severity.INFORMATIONAL,
}

#: The rule for a contract key nobody has classified yet. CRITICAL, not
#: INFORMATIONAL or a mid-scale guess: `ConflictQueueEntry.severity` is required
#: specifically because a default at or below the gate threshold would make a
#: forgotten severity silently unable to block, and only the maximum defends
#: that regardless of where a caller sets the threshold. Never actually needed
#: if `test_every_contract_key_has_a_criticality` stays green - the safety net
#: is for the gap between a contract addition and this table catching up.
DEFAULT_CRITICALITY = Severity.CRITICAL

#: The D-3 Tier A categories, as patterns over contract keys.
#:
#: This exists so `TIER_A_FIELDS` can be checked in the direction that actually
#: fails. `test_tier_a_fields_are_contract_keys` asserts the set contains no
#: invented names, which catches a typo and cannot catch an omission - and the
#: omission is the one that costs something, because a field absent from the set
#: simply does not get the floor. Three were missing on that basis; see the note
#: on `TIER_A_FIELDS`.
TIER_A_KEY_PATTERNS: tuple[str, ...] = (
    r"price",  # "Pricing"
    r"warrant|degradation_year_1|degradation_annual",  # "warranty terms"
    r"domestic_content|country_of_origin|material_assistance|baba|feoc",
    r"cert|listing",  # "certification presence *or absence*"
)

_TIER_A_RE = re.compile("|".join(TIER_A_KEY_PATTERNS))


def looks_tier_a(field_name: str) -> bool:
    """Whether a contract key falls in one of D-3's Tier A categories."""
    return _TIER_A_RE.search(field_name) is not None


#: Contract keys matching a Tier A pattern that are deliberately *not* Tier A.
#:
#: Empty. It exists so a future exclusion has to be written down with a reason
#: instead of achieved by omission - which is how the three below went missing.
TIER_A_EXCLUSIONS: dict[str, str] = {}

#: D-3's Tier A, verbatim: "Pricing; warranty terms; domestic-content, BABA and
#: FEOC status; certification presence or absence." A floor, not a derived set -
#: hand-keyed from clarifications.md D-3 rather than computed from `CRITICALITY`
#: above, because Tier A is D-3's classification and independent of this
#: module's own criticality-class choices for the same fields.
#:
#: **Three fields were missing, and each one shipped a contractual conflict past
#: the compose gate.** `material_assistance_cost_ratio` (the 45X
#: material-assistance metric, i.e. FEOC status), `degradation_year_1` and
#: `degradation_annual` (warranty terms - the criticality table's own comment
#: eighteen lines up calls them "the guaranteed degradation curve underwriting
#: the performance warranty"). All three carry base `HIGH`, so with no Tier A
#: floor a `%`-vs-`fraction` extraction artefact takes `_unit_mismatch_reconciles`'
#: -2 straight down to `LOW`:
#:
#:     assign_severity("degradation_year_1", UNIT_NORMALIZATION,
#:                     [2.0 "%", 0.02 "fraction"], ...)  ->  Severity.LOW
#:
#: `config.compose_gate_threshold` defaults to `MEDIUM` and the gate blocks
#: *strictly above* it, so `LOW` means the workbook ships with an unresolved
#: contractual-degradation or FEOC-eligibility conflict. `HIGH` would have
#: blocked it. `country_of_origin` was missing too and was rescued only
#: incidentally, by the separate `CRITICAL` floor below it.
TIER_A_FIELDS: frozenset[str] = frozenset(
    {
        "price_per_watt_dc",
        "price_per_watt_ac",
        "price_per_metre",
        "product_warranty_years",
        "performance_warranty_years",
        "performance_warranty_end_output",
        "warranty_years",
        "corrosion_warranty_years",
        "degradation_warranty_years",
        "degradation_warranty_cycles",
        "degradation_year_1",
        "degradation_annual",
        "domestic_content_status",
        "domestic_content_percentage",
        "country_of_origin",
        "material_assistance_cost_ratio",
        "baba_status",
        "baba_certification_ref",
        "feoc_pfe_status",
        "certifications",
        "fire_safety_certifications",
        "cell_certification",
        "pcs_certification",
        "ul_listing",
    }
)


def criticality_for(field_name: str) -> Severity:
    """The base severity for a canonical field, falling back to `CRITICAL`.

    Mirrors `tolerance.tolerance_for`: `field_name` is the frozen contract's
    `key`, not a descriptive name, and a key this table does not hold falls back
    - here to the maximum rather than the minimum, because an unassigned
    severity must never be the reason the gate fails to block (see
    `DEFAULT_CRITICALITY`).
    """
    return CRITICALITY.get(field_name, DEFAULT_CRITICALITY)


# --- the coarse numeric helpers the modifiers share -----------------------------


def _numeric_value(value: object) -> float | None:
    """A numeric reading of a candidate value.

    Deliberately not imported from `conflict_hitl._as_number`: that name is
    underscore-prefixed in this package's `__init__.py`, and reaching past the
    mark that it is not for reuse - rather than adding a second, smaller
    computation this module actually needs - is how a "helper" import quietly
    becomes a second copy of the parent's comparison semantics. `bool` is
    excluded for the same reason it is there: `True` would compare equal to a
    1.0 candidate value under no tolerance at all.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def _band(tolerance: FieldTolerance, numbers: Sequence[float]) -> float | None:
    """A coarse tolerance band in the compared quantity's own unit.

    Deliberately simpler than `conflict_hitl._effective_magnitude`: it never
    selects between a D-2 row's two conditional bands (impedance below 10%,
    IEEE vs IEC, against the CEC list), because both callers below only need
    the right answer to within a factor of a few - an order-of-magnitude
    overshoot, or a coarse units-only reconciliation - and no D-2 conditional
    branch differs by enough to flip either verdict. `None` for EXACT,
    DECLARED_BAND and NEVER_COMPARE, which have no per-field magnitude to scale:
    those rules are out of scope for these modifiers rather than guessed at.
    """
    if tolerance.magnitude is None:
        return None
    magnitude = tolerance.magnitude
    if tolerance.rule in (ToleranceRule.RELATIVE, ToleranceRule.ONE_SIDED):
        magnitude *= max(abs(n) for n in numbers)
    return magnitude


#: Units that differ only by a known scale factor, mapped to a common family
#: name and the multiplier that converts a value in this unit to that family's
#: base unit. Not a general unit-conversion engine - a small, explicit table in
#: the same spirit as `tolerance.py`'s per-field rows: an invented general
#: parser would apply confidently to a unit pair nobody here has verified means
#: what the parser assumes. Covers the SI-prefixed pairs the contract's own
#: canonical units produce (W/kW/MW, VA/kVA/MVA, Wh/kWh/MWh, V/kV, A/kA), a
#: realistic price-quoting pair (`USD/W` vs `USD/kW`), and percent-vs-fraction,
#: which several fields in `CRITICALITY` above use `%` for.
_BASE_UNIT: dict[str, tuple[str, float]] = {
    "w": ("w", 1.0),
    "kw": ("w", 1e3),
    "mw": ("w", 1e6),
    "gw": ("w", 1e9),
    "va": ("va", 1.0),
    "kva": ("va", 1e3),
    "mva": ("va", 1e6),
    "wh": ("wh", 1.0),
    "kwh": ("wh", 1e3),
    "mwh": ("wh", 1e6),
    "gwh": ("wh", 1e9),
    "v": ("v", 1.0),
    "kv": ("v", 1e3),
    "a": ("a", 1.0),
    "ka": ("a", 1e3),
    "usd/w": ("usd/w", 1.0),
    "usd/kw": ("usd/w", 1e-3),
    "%": ("%", 1.0),
    "fraction": ("%", 100.0),
}


def _scaled_numbers(candidates: Sequence[ConflictCandidate]) -> list[float] | None:
    """Numeric values, converted to a common unit when every candidate's unit
    resolves to the same `_BASE_UNIT` family; otherwise the raw values as
    printed. `None` if fewer than two candidates carry a number at all.

    The raw fallback is correct whenever both sides already share one unit -
    the ordinary case, e.g. two `Wp` candidates need no conversion - and a
    deliberate best-effort otherwise: reconciling an unrecognised unit pair is
    out of scope for this module's coarse checks (see `_band`), not something
    to guess a conversion for. Used by `_gross_divergence`, so that a candidate
    pair which merely *looks* far apart in unconverted units - 650 W against
    0.65, unit kW - is not read as a data error on top of the unit mismatch
    `_unit_mismatch_reconciles` already accounts for separately.
    """
    numbers: list[float] = []
    for candidate in candidates:
        number = _numeric_value(candidate.value)
        if number is None:
            return None
        numbers.append(number)
    if len(numbers) < 2:
        return None
    units = [c.unit for c in candidates]
    if all(unit is not None for unit in units):
        bases = [_BASE_UNIT.get(unit.strip().casefold()) for unit in units if unit is not None]
        if len(bases) == len(units) and all(base is not None for base in bases):
            families = {base[0] for base in bases if base is not None}
            if len(families) == 1:
                return [
                    number * base[1]
                    for number, base in zip(numbers, bases, strict=True)
                    if base is not None
                ]
    return numbers


def _reconciles(a: ConflictCandidate, b: ConflictCandidate, tolerance: FieldTolerance) -> bool:
    """Whether `a` and `b` agree once converted to a common unit.

    Requires both units to be individually recognised in `_BASE_UNIT` and to
    share a family - unlike `_scaled_numbers`'s raw fallback, an unrecognised
    unit pair here must read as "not shown to reconcile", not as "reconciles by
    default", because this result feeds a severity *discount*.

    EXACT-rule fields (`tolerance.py`'s default for every field D-2 does not
    cover - which is every Tier A and CRITICAL field: none of pricing,
    warranty-term counts, domestic content, BABA/FEOC or certifications carries
    a D-2 numeric row) have no `_band` to compare against, but "reconciles
    after conversion" is a narrower question than D-2's disagreement tolerance:
    it asks whether this is the *same number* printed in a different unit, not
    whether two independent measurements are close enough to agree. So EXACT
    falls back to numeric equality up to floating-point representation noise
    from the conversion arithmetic itself, rather than reading "no D-2 band" as
    "cannot reconcile" - which would leave this modifier permanently unreachable
    for the fields the Tier A / CRITICAL floors below exist to protect, the
    same shape of defect as `NEVER_COMPARABLE`'s formerly-invented key.
    """
    if a.value is None or b.value is None or a.unit is None or b.unit is None:
        return False
    base_a = _BASE_UNIT.get(a.unit.strip().casefold())
    base_b = _BASE_UNIT.get(b.unit.strip().casefold())
    if base_a is None or base_b is None or base_a[0] != base_b[0]:
        return False
    number_a, number_b = _numeric_value(a.value), _numeric_value(b.value)
    if number_a is None or number_b is None:
        return False
    common_a, common_b = number_a * base_a[1], number_b * base_b[1]
    band = _band(tolerance, (common_a, common_b))
    if band is not None:
        return abs(common_a - common_b) <= band
    if tolerance.rule is ToleranceRule.EXACT:
        return math.isclose(common_a, common_b, rel_tol=1e-9, abs_tol=1e-9)
    return False


# --- the four bounded modifiers, open-decisions.md #1 --------------------------


def _gross_divergence(field_name: str, candidate_set: Sequence[ConflictCandidate]) -> bool:
    """+1: divergence >= 10x the D-2 tolerance - usually a decimal-comma error,
    D-5's highest-risk trap."""
    numbers = _scaled_numbers(candidate_set)
    if numbers is None:
        return False
    band = _band(tolerance_for(field_name), numbers)
    if band is None or band <= 0:
        return False
    return (max(numbers) - min(numbers)) >= 10 * band


def _both_system_of_record_inter_document(
    conflict_class: ConflictClass, candidate_set: Sequence[ConflictCandidate]
) -> bool:
    """+1: inter-document where BOTH sides are system_of_record - two ingested
    authorities disagreeing, not a contract disagreeing with a lower tier."""
    return (
        conflict_class is ConflictClass.INTER_DOCUMENT
        and len(candidate_set) >= 2
        and all(c.source_tier is SourceTier.SYSTEM_OF_RECORD for c in candidate_set)
    )


def _distinct_value_count(candidates: Sequence[ConflictCandidate]) -> int:
    """Distinct non-missing values, without requiring `value` to be hashable
    (some contract fields are `dict`, e.g. `harmonic_spectrum`)."""
    seen: list[object] = []
    for candidate in candidates:
        if candidate.value is None:
            continue
        if candidate.value not in seen:
            seen.append(candidate.value)
    return len(seen)


def _matcher_failure(condition_group: Sequence[ConflictCandidate]) -> bool:
    """+1: >=3 distinct values in one group - a matcher failure, not a data
    disagreement."""
    return _distinct_value_count(condition_group) >= 3


def _unit_mismatch_reconciles(
    field_name: str, conflict_class: ConflictClass, candidate_set: Sequence[ConflictCandidate]
) -> bool:
    """-2: a unit mismatch that reconciles after conversion is an extraction
    defect - fix the normaliser, do not hold the workbook. Requires every pair
    in `candidate_set` to reconcile, not merely one: a mixed signal (some pairs
    explained by units, others not) is not evidence the whole conflict is just
    a units artefact, and understating severity is the unsafe direction here."""
    if conflict_class is not ConflictClass.UNIT_NORMALIZATION or len(candidate_set) < 2:
        return False
    tolerance = tolerance_for(field_name)
    pairs = list(itertools.combinations(candidate_set, 2))
    return all(_reconciles(a, b, tolerance) for a, b in pairs)


def _clamp(value: int) -> int:
    return max(int(Severity.INFORMATIONAL), min(int(Severity.CRITICAL), value))


# --- the entry point ------------------------------------------------------------


def assign_severity(
    field_name: str,
    conflict_class: ConflictClass,
    condition_group: Sequence[ConflictCandidate],
    candidate_set: Sequence[ConflictCandidate],
) -> Severity:
    """Severity for one detected conflict (open-decisions.md #1).

    A pure function of exactly these four arguments - see the module docstring
    for what `condition_group` and `candidate_set` are read as, and
    `tests/test_severity.py` for the tests enforcing the purity this signature
    only states.

    Base severity comes from `criticality_for(field_name)` - the field's
    criticality class, never the size of the disagreement. Four bounded
    modifiers are summed (not multiplied - the deleted-RPN lesson) and the
    total is clamped to the enum's range. Two floors then apply, and nothing
    computed above can lower a field past them: any D-3 Tier A field floors at
    HIGH, and any field whose base class is CRITICAL (attestation/eligibility -
    certification presence-vs-absence chief among them) floors at CRITICAL.
    Both floors are independent, explicit checks rather than an emergent
    property of the base table, so a future edit that reclassifies a Tier A or
    attestation field cannot silently drop its floor along with it.
    """
    base = criticality_for(field_name)
    modifier = 0
    if _gross_divergence(field_name, candidate_set):
        modifier += 1
    if _both_system_of_record_inter_document(conflict_class, candidate_set):
        modifier += 1
    if _matcher_failure(condition_group):
        modifier += 1
    if _unit_mismatch_reconciles(field_name, conflict_class, candidate_set):
        modifier -= 2

    value = _clamp(int(base) + modifier)
    if field_name in TIER_A_FIELDS:
        value = max(value, int(Severity.HIGH))
    if criticality_for(field_name) is Severity.CRITICAL:
        value = max(value, int(Severity.CRITICAL))
    return Severity(value)
