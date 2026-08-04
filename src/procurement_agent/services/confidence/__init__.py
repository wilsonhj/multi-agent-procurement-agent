"""What produces the confidence a threshold is applied to — D-3, issue #3.

`CanonicalField.confidence` was a float with no defined provenance. Nothing in
the codebase produced it, so the number a review threshold acted on came from
nowhere.

**Deterministic signals first, and they carry most of the value.** On DocILE
(55-field invoices, 26% natural failure rate) logprob-mean scores 0.705 ROC AUC
and self-consistency at k=5 scores 0.744 — about +0.05 for 3-5x the inference
cost. Fusing OCR confidence, image quality, spatial layout and cross-call
disagreement reaches 0.928. The structural reason applies directly here:
extraction errors are caused by things the model cannot observe — OCR noise, an
unreadable scan, an ambiguous layout — so a model confidently transcribing OCR
noise gets high logprobs *and* high self-agreement. Resampling a blind model
cannot reveal its own blind spot.

**What is deliberately not here: the calibration.** D-3 reads the threshold off a
risk-coverage curve computed on a labelled set, wrapped in split conformal
prediction. There is no corpus in this repo, so there is no honest number to
pin. `fuse` returns a *nonconformity score*, not a calibrated probability, and
`requires_review` takes the threshold as an argument rather than inventing one.
The impossibility bound is worth stating while nobody can test it: when base
risk exceeds the target, any distribution-free method must abstain on at least
`(mu - alpha) / (1 - alpha)` of examples — at a 26% base error rate a 5% risk
target forces abstention on ~22% of fields. Conformal makes that price explicit;
it cannot remove it.

**Two defects in the first version are worth keeping in view**, because both
passed a green suite and both were silent:

- `ul_listing` was not in the tier table, so it fell to the default and a 0.99
  score auto-accepted it — while this module's own docstring said a missing
  UL 9540A listing must never reach the workbook as a quiet blank. The table was
  checked in one direction only (no invented keys) and never in the other (no
  missing ones), so a Tier A field simply absent from it was invisible.
- `fuse` renormalised over *observed* weight, so a single cheap positive signal
  scored **1.0** while five corroborating observations scored 0.99. Absence was
  scoring as strength. `UNOBSERVED_PRIOR` replaces that.
"""

from __future__ import annotations

import math
import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CriticalityTier(StrEnum):
    """D-3's three tiers. Adoptable without the calibration, and adopted here."""

    A = "a"
    """**Never auto-accepted.** No confidence score can accept these. A
    sufficiently confident wrong extraction misstates a contractual or tax
    position, and the cost is not symmetric with the review time saved."""

    B = "b"
    """Strict: target 99.5% precision. Pmax, Voc, Isc, quantities, dates."""

    C = "c"
    """Standard: target 99% precision. Descriptive and secondary fields."""


#: The four field categories D-3 names as Tier A, as patterns over contract keys.
#:
#: This exists so the tier table can be checked in the direction that actually
#: fails. Checking that every table key is a contract key catches invented names;
#: it cannot catch a contract field that belongs in Tier A and was never listed,
#: and that is how `ul_listing` became auto-acceptable. `test_no_tier_a_field_is
#: _missing_from_the_table` walks the frozen contract with these patterns and
#: fails on anything unlisted.
#:
#: Patterns rather than a second hand-written list, because a hand-written list
#: has the same failure mode as the one it is checking.
TIER_A_KEY_PATTERNS: tuple[str, ...] = (
    r"price",  # "Pricing"
    # "warranty terms". `degradation_year_1` and `degradation_annual` are the
    # guaranteed degradation curve underwriting the performance warranty - the
    # terms of the guarantee, not performance figures - so they belong here even
    # though neither name contains "warrant".
    r"warrant|degradation_year_1|degradation_annual",
    r"domestic_content|country_of_origin|material_assistance|baba|feoc",  # origin and tax status
    # "certification presence *or absence*". `standards`,
    # `ride_through_standards`, `cybersecurity_standards` and
    # `seismic_qualification` are here on the frozen contract's own definition:
    # its preamble says "Certification fields are `list[str]` of standard
    # identifiers; an empty list means 'we looked and found none stated', which
    # is materially different from `None` meaning 'we have not established
    # this'." That sentence exists precisely to make presence-vs-absence
    # material, which is D-3's Tier A criterion word for word.
    #
    # `ride_through_standards` is the clearest case and the reason this was
    # worth widening: IEEE 1547-2018, IEEE 2800-2022 and NERC PRC-029-1 are
    # ERCOT interconnection requirements, so a silently-absent entry misstates a
    # regulatory position - the exact cost D-3 gives for the tier.
    #
    # `seismic_qualification` is typed `str`, not `list[str]`, so it falls
    # outside the preamble's literal wording. Included anyway, because the
    # failure directions are not symmetric: Tier A costs review time, Tier B
    # risks a wrong compliance attestation reaching the workbook unseen.
    r"cert|listing|standards|seismic_qualification",
)

_TIER_A_RE = re.compile("|".join(TIER_A_KEY_PATTERNS))


def looks_tier_a(field_name: str) -> bool:
    """Whether a contract key falls in one of D-3's Tier A categories."""
    return _TIER_A_RE.search(field_name) is not None


#: Contract keys that match a Tier A pattern but are deliberately *not* Tier A.
#:
#: Empty, and that is the current finding rather than an oversight: every one of
#: the 22 contract keys matching a D-3 category is genuinely a contractual, tax
#: or certification position. The dict exists so that a future exclusion has to
#: be written down with a reason instead of being achieved by omission - which is
#: exactly how `ul_listing` was excluded the first time.
TIER_A_EXCLUSIONS: dict[str, str] = {}


#: Field-to-tier assignment, keyed by the frozen contract's `key` column.
#:
#: Keyed on contract names deliberately: the tolerance table shipped keyed on
#: invented names and 19 of its 20 rows silently matched nothing, so
#: `test_every_tier_key_is_a_contract_key` checks this one the same way - and
#: `test_no_tier_a_field_is_missing_from_the_table` checks the other direction.
FIELD_TIERS: dict[str, CriticalityTier] = {
    # --- Tier A: pricing ---
    "price_per_watt_ac": CriticalityTier.A,
    "price_per_watt_dc": CriticalityTier.A,
    "price_per_metre": CriticalityTier.A,
    # --- Tier A: warranty terms ---
    "product_warranty_years": CriticalityTier.A,
    "performance_warranty_years": CriticalityTier.A,
    "performance_warranty_end_output": CriticalityTier.A,
    "corrosion_warranty_years": CriticalityTier.A,
    "warranty_years": CriticalityTier.A,
    # The BESS capacity warranty. The first version filed these as Tier B, which
    # read them as performance figures; they are the terms of the guarantee, and
    # a wrong cycle count misstates a contractual position exactly as a wrong
    # warranty term does.
    "degradation_year_1": CriticalityTier.A,
    "degradation_annual": CriticalityTier.A,
    "degradation_warranty_years": CriticalityTier.A,
    "degradation_warranty_cycles": CriticalityTier.A,
    # --- Tier A: domestic content, BABA and FEOC ---
    "domestic_content_percentage": CriticalityTier.A,
    "domestic_content_status": CriticalityTier.A,
    "country_of_origin": CriticalityTier.A,
    "material_assistance_cost_ratio": CriticalityTier.A,
    "baba_status": CriticalityTier.A,
    "baba_certification_ref": CriticalityTier.A,
    "feoc_pfe_status": CriticalityTier.A,
    # --- Tier A: certification presence or absence ---
    "certifications": CriticalityTier.A,
    "cell_certification": CriticalityTier.A,
    "pcs_certification": CriticalityTier.A,
    "fire_safety_certifications": CriticalityTier.A,
    "ul_listing": CriticalityTier.A,
    # Standards compliance is certification presence or absence by the frozen
    # contract's own definition of a certification field - see the note on
    # TIER_A_KEY_PATTERNS. `ride_through_standards` carries IEEE 1547-2018,
    # IEEE 2800-2022 and NERC PRC-029-1, which are ERCOT interconnection
    # requirements for this project's own 500 MW ERCOT plant.
    "standards": CriticalityTier.A,
    "ride_through_standards": CriticalityTier.A,
    "cybersecurity_standards": CriticalityTier.A,
    "seismic_qualification": CriticalityTier.A,
    # --- Tier B: decision-driving performance ---
    "nameplate_power": CriticalityTier.B,
    "stc_rating": CriticalityTier.B,
    "nmot_rating": CriticalityTier.B,
    "module_efficiency": CriticalityTier.B,
    "rated_ac_power": CriticalityTier.B,
    "cec_efficiency": CriticalityTier.B,
    "usable_energy_per_container": CriticalityTier.B,
    "nameplate_energy_per_container": CriticalityTier.B,
    "round_trip_efficiency": CriticalityTier.B,
    "cycle_life": CriticalityTier.B,
    "rating_mva": CriticalityTier.B,
    "no_load_loss": CriticalityTier.B,
    "load_loss": CriticalityTier.B,
    "impedance_percent": CriticalityTier.B,
}

#: The tier for a field nobody has classified. **B, not C.**
#:
#: An unclassified field is one nobody has thought about, and the failure
#: directions are not symmetric: defaulting to C auto-accepts it at the loosest
#: target, defaulting to B merely costs review time. Same reasoning as the
#: tolerance table's exact-by-default.
#:
#: Note what this default does *not* do: it cannot rescue a Tier A field that is
#: missing from the table, because B is a threshold and A is a gate. That is the
#: whole reason the direction check exists.
DEFAULT_TIER = CriticalityTier.B


def tier_for(field_name: str) -> CriticalityTier:
    """The criticality tier for a canonical field."""
    return FIELD_TIERS.get(field_name, DEFAULT_TIER)


#: Where the tier decision cannot yet reach, recorded rather than left to silence.
#:
#: Same remedy as `identity.UNIMPLEMENTED_D4A`, for the same reason: the
#: tolerance table's invented keys were invisible for four commits because
#: nothing said what was missing.
UNIMPLEMENTED_REVIEW_ROUTING: dict[str, str] = {
    "flags_for has no tier notion": (
        "`services.output.flags_for` takes a `CanonicalField` and a threshold, "
        "not a field *name*, so it cannot ask `tier_for` anything. A Tier A field "
        "extracted at 0.99 therefore carries no `CellFlag` at all: the workbook "
        "would show it as clean while `requires_review` says no score can accept "
        "it. Nothing is broken today because `write_workbook` raises "
        "NotImplementedError and `flags_for` has no live caller - the hazard is "
        "the next author wiring it up and believing the gate is enforced. "
        "Closing it needs either a fifth `CellFlag` meaning 'gated, not scored' "
        "or the field name threaded through, and which of those is right is the "
        "workbook writer's decision rather than this module's."
    ),
}


class ConfidenceSignals(BaseModel):
    """The deterministic signals available before any model is asked twice.

    Every one is free or nearly free at extraction time, and together they are
    what moves 0.7 to 0.93 in the published fusion result. `None` means *not
    observed* rather than zero: a text-layer PDF has no OCR confidence, and
    scoring its absence as failure would penalise the cleanest input.
    """

    model_config = ConfigDict(frozen=True)

    ocr_confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Per-cell OCR confidence, where OCR ran"
    )
    had_text_layer: bool = Field(
        default=False, description="A born-digital page is materially more reliable than a scan"
    )
    schema_valid: bool = Field(
        default=True, description="The extracted value satisfied its declared type and enum"
    )
    unit_normalised: bool = Field(
        default=True, description="FR-ING-08 normalisation succeeded without a fallback"
    )
    cross_field_consistent: bool | None = Field(
        default=None,
        description=(
            "The free cross-validation rules held - `Pmax ~ Vmp x Imp`, `PTC/STC` "
            "in 87-96%, sign conventions. None where no rule applies to the field."
        ),
    )
    second_read_agrees: bool | None = Field(
        default=None,
        description=(
            "A structurally *different* second pass agreed - field-guided against "
            "document-guided, not k temperature samples. 2x cost with errors "
            "decorrelated by construction, rather than 5x for resampling a blind "
            "model."
        ),
    )

    @model_validator(mode="after")
    def _reject_non_finite(self) -> ConfidenceSignals:
        if self.ocr_confidence is not None and not math.isfinite(self.ocr_confidence):
            raise ValueError("ocr_confidence must be finite")
        return self


#: Weights for `fuse`. Deliberately round numbers, and deliberately not tuned.
#:
#: Tuning them without a labelled set would be fitting to nothing, and would give
#: the output a false air of calibration. They encode an ordering — a schema
#: violation is worse evidence than a missing text layer — and that ordering is
#: the part that does not need a corpus. `test_the_weight_ordering_is_the_claim`
#: pins it, because the ordering being the only load-bearing content means a
#: reshuffle is a behaviour change however round the numbers stay.
SIGNAL_WEIGHTS: dict[str, float] = {
    "schema_valid": 0.30,
    "cross_field_consistent": 0.25,
    "ocr_confidence": 0.20,
    "second_read_agrees": 0.15,
    "unit_normalised": 0.05,
    "had_text_layer": 0.05,
}

#: What an *unobserved* signal contributes, as a fraction of its weight.
#:
#: The midpoint, because not looking is evidence in neither direction. The first
#: version renormalised over observed weight instead, which asserted that the
#: signals you happened to observe are representative of the ones you did not -
#: and the arithmetic said so out loud: a page whose only recorded signal was
#: `had_text_layer` scored **1.0**, beating five corroborating observations at
#: 0.99. Absence was outscoring evidence.
#:
#: Under the midpoint the score is monotone in evidence - observing a signal
#: raises the score exactly when that signal is better than not knowing - and
#: **1.0 requires every signal to have been checked and passed**, which is the
#: property a review-ranking score has to have.
UNOBSERVED_PRIOR = 0.5


def fuse(signals: ConfidenceSignals) -> float:
    """Combine the deterministic signals into a score in [0, 1].

    **A nonconformity score, not a probability.** Nothing here is calibrated, and
    D-3 is explicit that discrimination and calibration are different properties:
    a signal can rank-order well and still be badly calibrated. Treat the output
    as "rank these for review", never as "this is 93% likely correct".

    An unobserved signal contributes `UNOBSERVED_PRIOR` of its weight rather than
    being renormalised away, so a born-digital page is not penalised for having
    no OCR to score and is not *rewarded* for it either. A hard failure — invalid
    schema, a broken cross-field rule — scores zero for its weight, because that
    is an observation and a bad one.
    """
    total = 0.0
    for name, weight in SIGNAL_WEIGHTS.items():
        value = getattr(signals, name)
        if value is None:
            total += weight * UNOBSERVED_PRIOR
        elif name == "ocr_confidence":
            total += weight * float(value)
        else:
            total += weight * float(bool(value))
    return round(total, 10)


def requires_review(
    field_name: str,
    confidence: float,
    *,
    threshold: float,
) -> bool:
    """Whether a field must reach a human (FR-ING-10).

    **Tier A is a policy gate, not a threshold**, so it short-circuits before the
    score is consulted at all. The spec already represents *absence* correctly —
    an empty list rather than `None`, `baba_status` defaulting to `unconfirmed` —
    but representation alone does not stop a confident wrong value being accepted
    without anyone seeing it. This is the CUAD rule: "not extracted" is not "not
    certified", and a missing UL 9540A listing must never reach the workbook as a
    quiet blank. That sentence was already here while `ul_listing` was absent
    from the tier table and auto-accepting at 0.99.

    `threshold` is a parameter rather than a config read, because D-3 deletes the
    hardcoded float and reads tau off a risk-coverage curve on a labelled set.
    Until that set exists there is no defensible value to default to, and a
    plausible-looking one would be worse than an explicit argument.

    The boundary is `confidence < threshold`, so a score exactly *at* tau is
    accepted. That follows from tau being read off a risk-coverage curve as the
    lowest score meeting the precision target: the point itself is inside the
    accepted region, not outside it.
    """
    if tier_for(field_name) is CriticalityTier.A:
        return True
    return confidence < threshold
