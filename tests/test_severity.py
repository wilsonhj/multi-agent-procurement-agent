"""Whether a detected conflict is worth holding the workbook for — open-decisions.md
section 1.

`Severity` (schema/enums.py) and the compose gate (`orchestrator.compose_gate_blocks`)
both already existed; nothing assigned a severity to a detected conflict, so the gate
was inert regardless of what it was fed. This is the assignment rule closing that gap.

The load-bearing invariant (open-decisions.md:49): severity is a **pure function of
`(field_name, conflict_class, condition_group, candidate_set)`** — no clock, no
reviewer identity, no queue state. `test_module_source_never_touches_a_clock_random_
source_or_reviewer_identity` below is the test that actually enforces it, rather than
one that merely fails to violate it by omission.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import re

import pytest

from procurement_agent.schema import (
    Condition,
    ConflictCandidate,
    ConflictClass,
    Severity,
    SourceRef,
    SourceTier,
)
from procurement_agent.services.conflict_hitl import severity as severity_module
from procurement_agent.services.conflict_hitl.severity import (
    CRITICALITY,
    DEFAULT_CRITICALITY,
    TIER_A_FIELDS,
    _unit_mismatch_reconciles,
    assign_severity,
    criticality_for,
)


def _c(
    value: object,
    *,
    unit: str | None = "Wp",
    tier: SourceTier = SourceTier.SYSTEM_OF_RECORD,
    doc: str = "doc-a",
    condition: Condition | None = None,
) -> ConflictCandidate:
    return ConflictCandidate(
        value=value,
        unit=unit,
        condition=condition or Condition(),
        source_tier=tier,
        source_ref=SourceRef(document_id=doc),
        confidence=0.9,
    )


def _contract_keys() -> set[str]:
    """Mirrors `test_values_conflict._contract_keys` exactly: the criticality
    table has to be keyed the same way the tolerance table is, on pain of
    repeating the invented-name defect `test_every_tolerance_key_is_a_contract_key`
    exists to catch (19 of 20 rows silently unreachable)."""
    contract = pathlib.Path(__file__).parent.parent / (
        "specs/001-procurement-agent/contracts/canonical-parameters.md"
    )
    text = contract.read_text(encoding="utf-8")
    keys = {m.group(1) for m in re.finditer(r"^\|\s*`([a-z0-9_]+)`\s*\|", text, re.MULTILINE)}
    assert len(keys) > 50, "the contract's parameter tables did not parse"
    return keys


# --- keyed on the frozen contract, checked in both directions -----------------


def test_every_criticality_key_is_a_contract_key() -> None:
    """The defect this exists to prevent: a table keyed on invented names falls
    through to a default for every real field and nobody notices, because the
    fallback still returns *a* severity."""
    unknown = set(CRITICALITY) - _contract_keys()
    assert not unknown, (
        f"criticality rows keyed on names the frozen contract does not have: {unknown}"
    )


def test_every_contract_key_has_a_criticality() -> None:
    """The reverse direction. A tolerance row that is merely absent falls back to
    `DEFAULT_TOLERANCE`, which is a safe direction (exact, not lenient) - but a
    forgotten criticality row falls back to `DEFAULT_CRITICALITY`, and the only
    way to know a field was actually classified rather than caught by the
    fallback is to check every contract key is present here explicitly."""
    missing = _contract_keys() - set(CRITICALITY)
    assert not missing, f"contract keys with no assigned criticality: {missing}"


def test_tier_a_fields_are_contract_keys() -> None:
    unknown = TIER_A_FIELDS - _contract_keys()
    assert not unknown, f"TIER_A_FIELDS names a field the contract does not have: {unknown}"


# --- base severity: the criticality-class lookup -------------------------------


@pytest.mark.parametrize(
    "key,expected",
    [
        # Attestation / eligibility -> CRITICAL
        ("certifications", Severity.CRITICAL),
        ("fire_safety_certifications", Severity.CRITICAL),
        ("cell_certification", Severity.CRITICAL),
        ("pcs_certification", Severity.CRITICAL),
        ("ul_listing", Severity.CRITICAL),
        ("domestic_content_status", Severity.CRITICAL),
        ("domestic_content_percentage", Severity.CRITICAL),
        ("baba_status", Severity.CRITICAL),
        ("feoc_pfe_status", Severity.CRITICAL),
        ("country_of_origin", Severity.CRITICAL),
        ("ercot_compliance_items", Severity.CRITICAL),
        # Commercial -> HIGH
        ("price_per_watt_dc", Severity.HIGH),
        ("price_per_watt_ac", Severity.HIGH),
        ("price_per_metre", Severity.HIGH),
        ("warranty_years", Severity.HIGH),
        ("product_warranty_years", Severity.HIGH),
        ("material_assistance_cost_ratio", Severity.HIGH),
        # The named exception: looks descriptive, is a buildability field.
        ("vector_group", Severity.HIGH),
        # Decision-driving performance -> MEDIUM
        ("nameplate_power", Severity.MEDIUM),
        ("module_efficiency", Severity.MEDIUM),
        ("rating_mva", Severity.MEDIUM),
        ("usable_energy_per_container", Severity.MEDIUM),
        ("round_trip_efficiency", Severity.MEDIUM),
        ("cycle_life", Severity.MEDIUM),
        ("ampacity", Severity.MEDIUM),
        ("trd_percent", Severity.MEDIUM),
        # Secondary comparison -> LOW
        ("mppt_count", Severity.LOW),
        ("harmonic_spectrum", Severity.LOW),
        ("enclosure_rating", Severity.LOW),
        ("conductor_size", Severity.LOW),
        ("protocols", Severity.LOW),
        # Descriptive -> INFORMATIONAL
        ("supplier_verbatim", Severity.INFORMATIONAL),
        ("model_verbatim", Severity.INFORMATIONAL),
        ("datasheet_revision", Severity.INFORMATIONAL),
        ("stow_strategy", Severity.INFORMATIONAL),
        ("support_terms", Severity.INFORMATIONAL),
    ],
)
def test_base_severity_matches_criticality_class(key: str, expected: Severity) -> None:
    assert criticality_for(key) is expected


def test_vector_group_is_high_not_descriptive() -> None:
    """D-6a: Dyn1 and Dyn11 are 60 degrees apart and cannot be paralleled - a
    buildability field, not the string label it resembles (open-decisions.md #1)."""
    assert criticality_for("vector_group") is Severity.HIGH


def test_unmapped_field_defaults_to_critical_not_low() -> None:
    """`ConflictQueueEntry.severity` is required specifically because a default
    at or below the gate threshold would make a forgotten severity silently
    unable to block. The same reasoning applies one level down: a criticality
    row nobody has written yet must not silently produce a severity the gate
    would wave through."""
    assert criticality_for("a_field_nobody_has_classified_yet") is Severity.CRITICAL
    assert DEFAULT_CRITICALITY is Severity.CRITICAL


# --- assign_severity: the base class carries through with no modifiers --------


def test_assign_severity_returns_the_base_class_with_no_modifiers() -> None:
    pair = [_c(650.0, doc="doc-a"), _c(651.0, doc="doc-b")]
    result = assign_severity("nameplate_power", ConflictClass.INTRA_DOCUMENT, pair, pair)
    assert result is Severity.MEDIUM


# --- the four bounded modifiers -------------------------------------------------


def test_gross_divergence_adds_one() -> None:
    """+1: divergence >= 10x the D-2 tolerance - usually a decimal-comma error,
    D-5's highest-risk trap (open-decisions.md #1). nameplate_power's tolerance
    is +/-1 W; 650 vs 6.5 is two orders of magnitude apart."""
    pair = [_c(650.0, doc="doc-a"), _c(6.5, doc="doc-b")]
    result = assign_severity("nameplate_power", ConflictClass.INTRA_DOCUMENT, pair, pair)
    assert result is Severity.HIGH  # MEDIUM(2) + 1


def test_small_divergence_does_not_add() -> None:
    pair = [_c(650.0, doc="doc-a"), _c(651.0, doc="doc-b")]
    result = assign_severity("nameplate_power", ConflictClass.INTRA_DOCUMENT, pair, pair)
    assert result is Severity.MEDIUM


def test_gross_divergence_boundary_is_at_exactly_ten_times_tolerance() -> None:
    """Pinned at the boundary, not deep in the middle of it: a divergence of
    exactly 10 W against nameplate_power's +/-1 W band must trigger (`>=`, not
    `>`), and 9.9 W must not - catching an off-by-one on the threshold or the
    comparison operator that a grossly-oversized example would not notice."""
    at_boundary = [_c(650.0, doc="doc-a"), _c(660.0, doc="doc-b")]
    just_under = [_c(650.0, doc="doc-a"), _c(659.9, doc="doc-b")]
    assert (
        assign_severity("nameplate_power", ConflictClass.INTRA_DOCUMENT, at_boundary, at_boundary)
        is Severity.HIGH
    )
    assert (
        assign_severity("nameplate_power", ConflictClass.INTRA_DOCUMENT, just_under, just_under)
        is Severity.MEDIUM
    )


def test_gross_divergence_scales_a_relative_band_by_magnitude() -> None:
    """rated_ac_power's D-2 tolerance is RELATIVE (0.01), so the check has to
    scale that fraction by the compared magnitude before multiplying by ten -
    not apply the bare 0.01 as if it were an absolute band in kVA. 10050 vs
    10000 is 0.5%, nowhere near even the field's own 1% band, let alone ten
    times it; an implementation that forgot to scale would see a fixed 0.01 kVA
    band and misread this as grossly divergent."""
    pair = [_c(10000.0, unit="kVA", doc="doc-a"), _c(10050.0, unit="kVA", doc="doc-b")]
    result = assign_severity("rated_ac_power", ConflictClass.INTRA_DOCUMENT, pair, pair)
    assert result is Severity.MEDIUM


def test_inter_document_both_system_of_record_adds_one() -> None:
    """+1: inter-document where BOTH sides are system_of_record - two ingested
    authorities disagreeing is worse than a contract disagreeing with a web
    supplement, which FR-WEB-03 already treats as lower-tier."""
    pair = [
        _c(650.0, tier=SourceTier.SYSTEM_OF_RECORD, doc="doc-a"),
        _c(651.0, tier=SourceTier.SYSTEM_OF_RECORD, doc="doc-b"),
    ]
    result = assign_severity("nameplate_power", ConflictClass.INTER_DOCUMENT, pair, pair)
    assert result is Severity.HIGH


def test_record_vs_web_does_not_get_the_inter_document_modifier() -> None:
    pair = [
        _c(650.0, tier=SourceTier.SYSTEM_OF_RECORD, doc="doc-a"),
        _c(651.0, tier=SourceTier.WEB_SUPPLEMENT, doc="doc-b"),
    ]
    result = assign_severity("nameplate_power", ConflictClass.RECORD_VS_WEB, pair, pair)
    assert result is Severity.MEDIUM


def test_inter_document_with_one_web_supplement_does_not_add() -> None:
    """Both sides have to be system_of_record; INTER_DOCUMENT alone is not enough."""
    pair = [
        _c(650.0, tier=SourceTier.SYSTEM_OF_RECORD, doc="doc-a"),
        _c(651.0, tier=SourceTier.WEB_SUPPLEMENT, doc="doc-b"),
    ]
    result = assign_severity("nameplate_power", ConflictClass.INTER_DOCUMENT, pair, pair)
    assert result is Severity.MEDIUM


def test_three_distinct_values_in_a_group_adds_one_matcher_failure() -> None:
    """+1: >=3 distinct values in one group is a matcher failure, not a data
    disagreement. `condition_group` carries the wider comparable set the pair
    was drawn from; `candidate_set` is the pair itself."""
    group = [_c(650.0, doc="doc-a"), _c(651.0, doc="doc-b"), _c(700.0, doc="doc-c")]
    pair = group[:2]
    result = assign_severity("nameplate_power", ConflictClass.INTRA_DOCUMENT, group, pair)
    assert result is Severity.HIGH


def test_two_distinct_values_in_a_group_does_not_add() -> None:
    group = [_c(650.0, doc="doc-a"), _c(651.0, doc="doc-b")]
    result = assign_severity("nameplate_power", ConflictClass.INTRA_DOCUMENT, group, group)
    assert result is Severity.MEDIUM


def test_repeated_values_in_a_group_do_not_inflate_the_distinct_count() -> None:
    """Three candidates, two of which agree, is two distinct values - not three -
    so the matcher-failure modifier must not fire. 652 is close enough to 650
    that it also does not trip the separate gross-divergence modifier, so this
    test isolates the distinct-value count."""
    group = [_c(650.0, doc="doc-a"), _c(650.0, doc="doc-b"), _c(652.0, doc="doc-c")]
    pair = [group[0], group[2]]
    result = assign_severity("nameplate_power", ConflictClass.INTRA_DOCUMENT, group, pair)
    assert result is Severity.MEDIUM


def test_unit_mismatch_that_reconciles_after_conversion_subtracts_two() -> None:
    """-2: a unit mismatch that reconciles after conversion is an extraction
    defect - fix the normaliser, do not hold the workbook. 650 W and 0.65 kW are
    the same value."""
    pair = [_c(650.0, unit="W", doc="doc-a"), _c(0.65, unit="kW", doc="doc-b")]
    result = assign_severity("nameplate_power", ConflictClass.UNIT_NORMALIZATION, pair, pair)
    assert result is Severity.INFORMATIONAL  # MEDIUM(2) - 2 = 0


def test_unit_mismatch_that_does_not_reconcile_keeps_full_severity() -> None:
    """652 W != 650 W once converted: the units differ *and*, even accounting
    for that, the physical quantity still differs by more than nameplate_power's
    own +/-1 W band - a real disagreement wearing a unit-mismatch conflict_class,
    not an extraction defect - so no discount. Chosen close enough that it also
    does not trip the separate gross-divergence modifier, to isolate this one."""
    pair = [_c(650.0, unit="W", doc="doc-a"), _c(0.652, unit="kW", doc="doc-b")]
    result = assign_severity("nameplate_power", ConflictClass.UNIT_NORMALIZATION, pair, pair)
    assert result is Severity.MEDIUM


def test_unit_mismatch_reconciles_for_an_exact_tolerance_field_via_the_epsilon_fallback() -> None:
    """`max_system_voltage`'s D-2 rule is EXACT - discrete 1000/1500 V, no D-2
    magnitude - which is also true of *every* Tier A and CRITICAL field: none of
    pricing, warranty-term counts, domestic content, BABA/FEOC or certifications
    has a D-2 numeric row, so all of them fall back to EXACT too. Pinned on a
    non-floored EXACT field so this reconciliation path is verified on its own,
    not masked by a floor that would hold the result at the same value whether
    or not the discount actually fired. 1500 V and 1.5 kV are the same value."""
    pair = [_c(1500.0, unit="V", doc="doc-a"), _c(1.5, unit="kV", doc="doc-b")]
    result = assign_severity("max_system_voltage", ConflictClass.UNIT_NORMALIZATION, pair, pair)
    assert result is Severity.INFORMATIONAL  # LOW(1) - 2, clamped to 0


def test_unit_mismatch_reconciles_requires_every_pair_not_just_one() -> None:
    """White-box, on the internal helper directly: a three-candidate set where
    two pairs reconcile after conversion but the third genuinely disagrees must
    not read as reconciled as a whole - a mixed signal is not evidence the
    entire conflict is just a units artefact, and this policy has no clean
    black-box angle through `assign_severity` alone, since a third distinct
    candidate also trips the separate matcher-failure modifier."""
    reconciling = [_c(650.0, unit="W", doc="doc-a"), _c(0.65, unit="kW", doc="doc-b")]
    disagreeing = _c(700.0, unit="W", doc="doc-c")
    assert not _unit_mismatch_reconciles(
        "nameplate_power", ConflictClass.UNIT_NORMALIZATION, [*reconciling, disagreeing]
    )
    assert _unit_mismatch_reconciles(
        "nameplate_power", ConflictClass.UNIT_NORMALIZATION, reconciling
    )


def test_a_bool_is_not_read_as_a_number() -> None:
    """`True == 1` in Python, so an unguarded numeric reader would treat a
    stray boolean as a nameplate_power reading of 1.0 and misread the 649 W
    gap against a real 650 W candidate as a gross divergence. `ConflictCandidate
    .value` is untyped (`object | None`), so nothing upstream of this module
    guarantees a numeric field's candidates are never a bool."""
    pair = [_c(650.0, doc="doc-a"), _c(True, unit=None, doc="doc-b")]
    result = assign_severity("nameplate_power", ConflictClass.INTRA_DOCUMENT, pair, pair)
    assert result is Severity.MEDIUM


def test_modifiers_sum_and_clamp_rather_than_multiply() -> None:
    """Stacking every +1 modifier must not overshoot the enum - summed and
    clamped, per open-decisions.md #1, not multiplied (the deleted-RPN lesson)."""
    group = [
        _c(650.0, tier=SourceTier.SYSTEM_OF_RECORD, doc="doc-a"),
        _c(6.5, tier=SourceTier.SYSTEM_OF_RECORD, doc="doc-b"),  # gross divergence
        _c(700.0, tier=SourceTier.SYSTEM_OF_RECORD, doc="doc-c"),  # 3rd distinct value
    ]
    pair = group[:2]
    result = assign_severity("nameplate_power", ConflictClass.INTER_DOCUMENT, group, pair)
    # base MEDIUM(2) + gross(1) + inter-doc-record(1) + matcher(1) = 5, clamped to 4
    assert result is Severity.CRITICAL


# --- floors nothing can lower ---------------------------------------------------


def test_tier_a_floor_holds_price_at_high_despite_the_unit_discount() -> None:
    """Any D-3 Tier A field floors at HIGH. Without the floor, HIGH(3) - 2 would
    be LOW(1); a pricing conflict must never read as merely comparison-relevant."""
    pair = [_c(0.35, unit="USD/W", doc="doc-a"), _c(350.0, unit="USD/kW", doc="doc-b")]
    result = assign_severity("price_per_watt_dc", ConflictClass.UNIT_NORMALIZATION, pair, pair)
    assert result is Severity.HIGH


def test_certification_floor_holds_domestic_content_at_critical() -> None:
    """Certification presence-vs-absence is CRITICAL, always: 'not extracted' is
    not 'not certified'. Without the floor, CRITICAL(4) - 2 would be MEDIUM(2)."""
    pair = [_c(55.0, unit="%", doc="doc-a"), _c(0.55, unit="fraction", doc="doc-b")]
    result = assign_severity(
        "domestic_content_percentage", ConflictClass.UNIT_NORMALIZATION, pair, pair
    )
    assert result is Severity.CRITICAL


def test_floors_do_not_lower_a_field_that_already_exceeds_them() -> None:
    """A floor is a minimum, not a reset: stacking positive modifiers on a
    Tier A field must still reach CRITICAL, not stick at the HIGH floor."""
    group = [
        _c(0.35, unit="USD/W", tier=SourceTier.SYSTEM_OF_RECORD, doc="doc-a"),
        _c(35.0, unit="USD/W", tier=SourceTier.SYSTEM_OF_RECORD, doc="doc-b"),  # 100x gross
        _c(9.0, unit="USD/W", tier=SourceTier.SYSTEM_OF_RECORD, doc="doc-c"),  # 3rd distinct
    ]
    pair = group[:2]
    result = assign_severity("price_per_watt_dc", ConflictClass.INTER_DOCUMENT, group, pair)
    assert result is Severity.CRITICAL


# --- the load-bearing invariant: a pure function of exactly these four --------


def test_signature_admits_no_hidden_inputs() -> None:
    """A fifth parameter - `resolved_by`, `now`, a settings object - would let a
    reviewer or the moment of computation change severity, which is exactly what
    open-decisions.md:49 forbids: the same store must produce the same workbook.
    A defaultable parameter is equally dangerous, because nobody has to pass it
    for it to exist."""
    params = inspect.signature(assign_severity).parameters
    assert list(params) == ["field_name", "conflict_class", "condition_group", "candidate_set"]
    for parameter in params.values():
        assert parameter.default is inspect.Parameter.empty, (
            f"{parameter.name} has a default, which is how a hidden fifth input "
            "is smuggled in unnoticed"
        )


def test_module_never_imports_a_clock_random_source_or_reads_reviewer_state() -> None:
    """Static, not behavioural, and deliberately so.

    A runtime monkeypatch of `time.time` cannot catch `from time import time as
    _now` bound at import time, and open-decisions.md:49's ban is on the
    *capability* to read these, not on whether today's implementation happens to
    exercise it on the inputs a particular test constructs. Walking the parsed
    AST for actual `import`/`from` statements and attribute accesses - rather
    than grepping the raw source text, which would also trip on this module's
    own docstring explaining the invariant in prose - closes that gap without
    that false positive: a future edit that adds `import time` to weight a
    recent divergence more heavily, or that reads `.resolved_by` /
    `.resolved_at` off a queue entry, fails this test the moment it is written,
    regardless of whether any test remembers to patch the right symbol
    afterward.
    """
    tree = ast.parse(inspect.getsource(severity_module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden_modules = {"time", "datetime", "random", "uuid"}
    hit_modules = imported & forbidden_modules
    assert not hit_modules, (
        f"severity.py imports {hit_modules} - a clock or randomness source a "
        "pure severity function must never touch"
    )

    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    forbidden_attrs = {"resolution", "resolved_by", "resolved_at"}
    hit_attrs = attrs & forbidden_attrs
    assert not hit_attrs, (
        f"severity.py reads {hit_attrs} - a reviewer-identity or queue-state "
        "field a pure severity function must never see"
    )


def test_repeated_calls_with_equal_but_distinct_objects_agree() -> None:
    """Two calls built from freshly-constructed, merely-equal (not
    identical-by-id) objects must agree - ruling out any dependency on object
    identity or a hidden cache keyed on it."""

    def build() -> tuple[str, ConflictClass, list[ConflictCandidate], list[ConflictCandidate]]:
        pair = [_c(650.0, doc="doc-a"), _c(6.5, doc="doc-b")]
        return ("nameplate_power", ConflictClass.INTER_DOCUMENT, pair, pair)

    first = assign_severity(*build())
    second = assign_severity(*build())
    assert first == second


def test_result_does_not_depend_on_candidate_order() -> None:
    """Order is arrival order. FR-OUT-06 requires composition - and therefore the
    severity it reads - to be a pure function of the store's *content*, not the
    order candidates happened to arrive in; the same reasoning `_ordering_key`
    exists for elsewhere in this package."""
    a = _c(650.0, tier=SourceTier.SYSTEM_OF_RECORD, doc="doc-a")
    b = _c(6.5, tier=SourceTier.SYSTEM_OF_RECORD, doc="doc-b")
    forward = assign_severity("nameplate_power", ConflictClass.INTER_DOCUMENT, [a, b], [a, b])
    backward = assign_severity("nameplate_power", ConflictClass.INTER_DOCUMENT, [b, a], [b, a])
    assert forward == backward
