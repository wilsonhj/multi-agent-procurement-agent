"""Where the confidence number comes from — D-3, issue #3.

Cases marked "review" are defects found in the first version of this module.
Each of them passed a green suite, so they are kept as tests rather than as
changelog.
"""

import inspect
import math
import pathlib
import re

import pytest

from procurement_agent.schema import CanonicalField, Condition, SourceRef, SourceTier
from procurement_agent.services.confidence import (
    DEFAULT_TIER,
    FIELD_TIERS,
    SIGNAL_WEIGHTS,
    TIER_A_EXCLUSIONS,
    UNIMPLEMENTED_REVIEW_ROUTING,
    UNOBSERVED_PRIOR,
    ConfidenceSignals,
    CriticalityTier,
    fuse,
    looks_tier_a,
    requires_review,
    tier_for,
)
from procurement_agent.services.output import flags_for


def _contract_keys() -> set[str]:
    contract = pathlib.Path(__file__).parent.parent / (
        "specs/001-procurement-agent/contracts/canonical-parameters.md"
    )
    text = contract.read_text(encoding="utf-8")
    keys = {m.group(1) for m in re.finditer(r"^\|\s*`([a-z0-9_]+)`\s*\|", text, re.MULTILINE)}
    assert len(keys) > 50, "the contract's parameter tables did not parse"
    return keys


# --- the tier table, in both directions -----------------------------------------


def test_every_tier_key_is_a_contract_key() -> None:
    """The tolerance table shipped with 19 of 20 invented keys and every row
    silently inert. This is the same check, one module over."""
    unknown = set(FIELD_TIERS) - _contract_keys()
    assert not unknown, f"tier rows keyed on names the frozen contract does not have: {unknown}"


def test_no_tier_a_field_is_missing_from_the_table() -> None:
    """Review: the table was checked in one direction only.

    `ul_listing` is a contract field carrying certification presence — UL 4703,
    and UL 9540A for storage. It was absent from the table, so it fell to
    `DEFAULT_TIER` (B) and a 0.99 extraction auto-accepted, while this module's
    own docstring said a missing UL 9540A listing must never reach the workbook
    as a quiet blank. `country_of_origin` and `material_assistance_cost_ratio`
    were absent the same way, and both feed the FEOC and domestic-content
    determinations the Tax Incentives tab depends on.

    A no-invented-keys check cannot catch a field that was never listed, and B is
    a threshold where A is a gate — so the default cannot rescue it either.
    """
    missing = {
        key
        for key in _contract_keys()
        if looks_tier_a(key)
        and key not in TIER_A_EXCLUSIONS
        and FIELD_TIERS.get(key) is not CriticalityTier.A
    }
    assert not missing, (
        f"contract fields in a D-3 Tier A category but not gated: {sorted(missing)}. "
        "Add them to FIELD_TIERS, or record a reason in TIER_A_EXCLUSIONS."
    )


def test_the_patterns_actually_recognise_the_gated_fields() -> None:
    """Mutation: replacing `cert|listing` with a pattern matching nothing left
    the whole suite green. The direction check asserts an *empty* set, so
    breaking the detector makes it vacuously pass — the classic way a guard stops
    guarding without anything going red.

    Every field the table gates must also be one the patterns can find, or the
    check is not checking.
    """
    gated = {key for key, tier in FIELD_TIERS.items() if tier is CriticalityTier.A}
    assert gated, "the tier table has no Tier A fields at all"
    unrecognised = {key for key in gated if not looks_tier_a(key)}
    assert not unrecognised, (
        f"gated fields the D-3 category patterns cannot find: {sorted(unrecognised)}. "
        "The direction check silently stops covering them."
    )


def test_the_exclusion_list_is_not_a_way_to_lose_a_field() -> None:
    """An exclusion has to name a real contract field and give a reason, or it is
    the omission it exists to prevent with a dict around it."""
    assert set(TIER_A_EXCLUSIONS) <= _contract_keys()
    assert all(reason.strip() for reason in TIER_A_EXCLUSIONS.values())


@pytest.mark.parametrize(
    "field_name",
    [
        "ul_listing",
        "country_of_origin",
        "material_assistance_cost_ratio",
        "degradation_warranty_years",
        "degradation_warranty_cycles",
        "certifications",
        "baba_status",
        "price_per_watt_dc",
        "ride_through_standards",
        "standards",
        "cybersecurity_standards",
        "seismic_qualification",
    ],
)
def test_the_named_gates_hold_at_any_score(field_name: str) -> None:
    assert tier_for(field_name) is CriticalityTier.A
    assert requires_review(field_name, 1.0, threshold=0.0)


def test_the_capacity_warranty_is_a_warranty_term() -> None:
    """Review: `degradation_warranty_years` and `_cycles` were filed Tier B,
    reading them as performance figures. They are the terms of the BESS capacity
    guarantee — a wrong cycle count misstates a contractual position."""
    assert tier_for("degradation_warranty_cycles") is CriticalityTier.A


def test_an_unclassified_field_defaults_strict_not_standard() -> None:
    assert DEFAULT_TIER is CriticalityTier.B
    assert tier_for("a_field_nobody_has_classified") is CriticalityTier.B


def test_the_tier_a_patterns_do_not_swallow_the_performance_fields() -> None:
    """A pattern list that matched everything would make the direction check
    vacuous and gate the whole contract."""
    for key in ("nameplate_power", "rated_ac_power", "cycle_life", "module_efficiency"):
        assert not looks_tier_a(key)
        assert tier_for(key) is CriticalityTier.B


# --- fusing the signals ---------------------------------------------------------


def test_one_cheap_signal_does_not_beat_five_observations() -> None:
    """Review: `fuse` renormalised over *observed* weight, so a page whose only
    recorded signal was `had_text_layer` scored 1.0 while five corroborating
    observations scored 0.99. Absence outscored evidence, and the ranking the
    score exists to produce was inverted at the top."""
    one_weak_signal = fuse(ConfidenceSignals(had_text_layer=True, schema_valid=False))
    five_observations = fuse(
        ConfidenceSignals(
            had_text_layer=True,
            schema_valid=True,
            unit_normalised=True,
            cross_field_consistent=True,
            second_read_agrees=True,
            ocr_confidence=0.95,
        )
    )
    assert one_weak_signal < five_observations


def test_a_perfect_score_requires_every_signal_to_have_been_checked() -> None:
    everything = ConfidenceSignals(
        ocr_confidence=1.0,
        had_text_layer=True,
        schema_valid=True,
        unit_normalised=True,
        cross_field_consistent=True,
        second_read_agrees=True,
    )
    assert fuse(everything) == 1.0
    assert fuse(everything.model_copy(update={"second_read_agrees": None})) < 1.0


def test_not_looking_is_evidence_in_neither_direction() -> None:
    """An unobserved signal sits between its two observed outcomes, which is what
    makes the score monotone in evidence."""
    base = ConfidenceSignals(schema_valid=True)
    unobserved = fuse(base)
    agreed = fuse(base.model_copy(update={"second_read_agrees": True}))
    disagreed = fuse(base.model_copy(update={"second_read_agrees": False}))
    assert disagreed < unobserved < agreed
    assert unobserved == pytest.approx((agreed + disagreed) / 2), (
        "the midpoint is the claim UNOBSERVED_PRIOR makes"
    )


def test_the_prior_is_the_midpoint() -> None:
    assert UNOBSERVED_PRIOR == 0.5


def test_a_failed_check_is_worse_than_an_unrun_one() -> None:
    """A broken cross-field rule is an observation. Not having a rule is not."""
    broken = fuse(ConfidenceSignals(cross_field_consistent=False))
    no_rule = fuse(ConfidenceSignals(cross_field_consistent=None))
    assert broken < no_rule


def test_ocr_confidence_is_scaled_not_thresholded() -> None:
    """Review: nothing pinned that a float signal enters at its magnitude. A
    version that read it as `bool` would score 0.01 and 0.99 identically and stay
    green."""
    scores = [fuse(ConfidenceSignals(ocr_confidence=c)) for c in (0.0, 0.25, 0.5, 0.75, 1.0)]
    # Strictly increasing, not merely non-decreasing. A `bool` reading gives
    # [0, w, w, w, w], which is sorted, has the right endpoints and the right
    # span — it survived the first version of this test on all three counts.
    assert all(lo < hi for lo, hi in zip(scores, scores[1:], strict=False)), scores
    span = scores[-1] - scores[0]
    assert span == pytest.approx(SIGNAL_WEIGHTS["ocr_confidence"]), (
        "the full range of an OCR confidence must move the score by its full weight"
    )


def test_the_weight_ordering_is_the_claim() -> None:
    """The magnitudes are round and untuned; the ordering is the content. A
    reshuffle is a behaviour change even though no number looks arbitrary."""
    assert (
        SIGNAL_WEIGHTS["schema_valid"]
        > SIGNAL_WEIGHTS["cross_field_consistent"]
        > SIGNAL_WEIGHTS["ocr_confidence"]
        > SIGNAL_WEIGHTS["second_read_agrees"]
        > SIGNAL_WEIGHTS["unit_normalised"]
    )
    assert SIGNAL_WEIGHTS["unit_normalised"] == SIGNAL_WEIGHTS["had_text_layer"]


def test_the_weights_are_a_partition_of_one() -> None:
    assert sum(SIGNAL_WEIGHTS.values()) == pytest.approx(1.0)


def test_every_weight_names_a_real_signal() -> None:
    assert set(SIGNAL_WEIGHTS) == set(ConfidenceSignals.model_fields)


def test_the_score_stays_in_the_unit_interval() -> None:
    worst = ConfidenceSignals(
        ocr_confidence=0.0,
        had_text_layer=False,
        schema_valid=False,
        unit_normalised=False,
        cross_field_consistent=False,
        second_read_agrees=False,
    )
    assert fuse(worst) == 0.0
    assert 0.0 <= fuse(ConfidenceSignals()) <= 1.0


def test_the_score_is_deterministic() -> None:
    signals = ConfidenceSignals(ocr_confidence=1 / 3, cross_field_consistent=True)
    assert fuse(signals) == fuse(signals)


def test_a_non_finite_ocr_confidence_is_rejected() -> None:
    with pytest.raises(ValueError, match="finite|less than or equal"):
        ConfidenceSignals(ocr_confidence=math.nan)


# --- the review decision --------------------------------------------------------


def test_the_threshold_boundary_accepts_the_point_itself() -> None:
    """Review: nothing pinned `<` against `<=`. Tau is read off a risk-coverage
    curve as the lowest score meeting the precision target, so the point is
    inside the accepted region."""
    assert not requires_review("nameplate_power", 0.80, threshold=0.80)
    assert requires_review("nameplate_power", 0.7999999, threshold=0.80)


def test_a_low_score_on_a_tier_b_field_is_reviewed() -> None:
    assert requires_review("nameplate_power", 0.4, threshold=0.9)


def test_a_high_score_on_a_tier_b_field_is_accepted() -> None:
    assert not requires_review("nameplate_power", 0.95, threshold=0.9)


def test_the_gap_between_the_gate_and_the_workbook_is_named() -> None:
    """`requires_review` gates Tier A, and `services.output.flags_for` - the only
    thing that decides what a cell looks like - takes no field name and so cannot
    consult the tier at all. It has no live caller yet, which is exactly why the
    gap needs writing down: silence is what made the tolerance table's invented
    keys invisible for four commits."""
    assert "flags_for has no tier notion" in UNIMPLEMENTED_REVIEW_ROUTING
    assert all(reason.strip() for reason in UNIMPLEMENTED_REVIEW_ROUTING.values())
    assert "field_name" not in inspect.signature(flags_for).parameters


def test_tier_a_ignores_the_threshold_entirely() -> None:
    """Not "gated at a high threshold" — gated. A threshold of 0.0 accepts
    everything else and still cannot accept a Tier A field."""
    assert requires_review("certifications", 1.0, threshold=0.0)
    assert not requires_review("nameplate_power", 1.0, threshold=0.0)


def test_the_tier_gap_note_matches_what_the_code_actually_does() -> None:
    """The note above is prose, and prose rots. This pins the *fact* it asserts.

    `test_the_gap_between_the_gate_and_the_workbook_is_named` checks that the
    note **exists**, and that is all it can check - so when the note's claim
    ("`flags_for` has no live caller") became false, the suite stayed green and a
    passing test protected a false statement. That is the failure mode this file
    keeps rediscovering: a test that pins prose pins the prose, not the fact.

    Two halves, both mechanical:

    1. The caller exists. If someone removes it the note is wrong again, in the
       other direction, and this says so.
    2. The consequence is real - a Tier A field that `requires_review` refuses at
       *any* score still carries no flag, and that empty list reaches the hashed
       projection.
    """
    from procurement_agent.services.output import projection

    assert "flags_for(" in inspect.getsource(projection._field_row), (
        "the projection no longer calls flags_for; the note above needs rewriting"
    )

    field = CanonicalField(
        value=["UL 61730"],
        unit=None,
        condition=Condition(),
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="d"),
        confidence=0.99,
    )
    assert tier_for("ul_listing") is CriticalityTier.A
    assert requires_review("ul_listing", 0.99, threshold=0.8)
    assert flags_for(field, confidence_threshold=0.8) == set(), (
        "if this is no longer empty the gap has been closed and the note is stale"
    )
