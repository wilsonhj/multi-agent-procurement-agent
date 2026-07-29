"""What may be compared, and in what order — issue #12.

Comparability is not transitive, so it cannot be a partition. Two attempts to
make it one both failed: first-fit bucketing was order-dependent, and exact-key
grouping stranded values whose conditions were merely less specific, silently
dropping the comparison. `comparison_pairs` carries the relation as pairs.
"""

import itertools

import pytest

from procurement_agent.schema import (
    Condition,
    ConflictCandidate,
    MeasurementBasis,
    SourceRef,
    SourceTier,
)
from procurement_agent.services.conflict_hitl import (
    comparison_groups,
    comparison_pairs,
    conflict_groupings,
)


def _candidate(
    value: float, condition: Condition, tier: SourceTier = SourceTier.WEB_SUPPLEMENT
) -> ConflictCandidate:
    return ConflictCandidate(
        value=value,
        unit="W",
        condition=condition,
        source_tier=tier,
        source_ref=SourceRef(document_id=f"doc-{value}"),
        confidence=0.9,
    )


#: A commercial contract states a number with no test condition; datasheets and
#: listings always state one. The asymmetry is the normal case, not an edge one.
AGREEMENT = _candidate(650.0, Condition(), SourceTier.SYSTEM_OF_RECORD)
DATASHEET = _candidate(700.0, Condition(basis=MeasurementBasis.STC))
CEC = _candidate(645.0, Condition(basis=MeasurementBasis.STC))


def _values(pairs: list[tuple[ConflictCandidate, ConflictCandidate]]) -> list[tuple[float, float]]:
    return [(float(a.value), float(b.value)) for a, b in pairs]  # type: ignore[arg-type]


def test_the_system_of_record_value_is_not_stranded() -> None:
    """A 7.1% gap between a signed agreement and the datasheet changes module
    count and $/W. Exact-key grouping compared the 650 W agreement with nothing."""
    values = _values(comparison_pairs([AGREEMENT, DATASHEET, CEC]))
    assert (650.0, 700.0) in values or (700.0, 650.0) in values
    assert (645.0, 650.0) in values or (650.0, 645.0) in values


def test_a_less_specific_condition_still_compares() -> None:
    """The case the exact-key fold missed: `@stc` vs `@stc, 25 degC`.

    Only wholly-unstated candidates were rescued, so a partially-stated
    system-of-record value stayed invisible."""
    loose = _candidate(650.0, Condition(basis=MeasurementBasis.STC), SourceTier.SYSTEM_OF_RECORD)
    precise = _candidate(700.0, Condition(basis=MeasurementBasis.STC, temperature_c=25.0))
    assert len(comparison_pairs([loose, precise])) == 1


def test_genuinely_different_conditions_never_compare() -> None:
    """The Sungrow case still holds: @30 degC and @40 degC are not a disagreement."""
    eu = _candidate(352.0, Condition(temperature_c=30.0), SourceTier.SYSTEM_OF_RECORD)
    cec = _candidate(320.865, Condition(temperature_c=40.0))
    assert comparison_pairs([eu, cec]) == []


def test_output_is_identical_under_every_permutation() -> None:
    """Not just the same set — the same list, since the queue payload is a list
    and FR-OUT-06 makes composition a pure function of the store."""
    outputs = {
        tuple(_values(comparison_pairs(list(order))))
        for order in itertools.permutations([AGREEMENT, DATASHEET, CEC])
    }
    assert len(outputs) == 1


def test_no_pair_is_raised_twice() -> None:
    """Folding unstated candidates into every stated group double-raised their
    mutual disagreement, once per stated group."""
    stated_a = _candidate(700.0, Condition(basis=MeasurementBasis.STC))
    stated_b = _candidate(690.0, Condition(temperature_c=30.0))
    bare_a = _candidate(650.0, Condition(), SourceTier.SYSTEM_OF_RECORD)
    bare_b = _candidate(655.0, Condition())
    values = _values(comparison_pairs([stated_a, stated_b, bare_a, bare_b]))
    assert len(values) == len(set(values))
    assert sum(1 for pair in values if set(pair) == {650.0, 655.0}) == 1


def test_an_empty_string_condition_does_not_masquerade_as_stated() -> None:
    """An extractor emitting "" rather than None would otherwise strand a value."""
    blank = _candidate(650.0, Condition(basis="   "), SourceTier.SYSTEM_OF_RECORD)  # type: ignore[arg-type]
    assert blank.condition.basis is None
    assert blank.condition.is_unstated()
    assert len(comparison_pairs([blank, DATASHEET])) == 1


def test_signed_zero_does_not_reorder_groups() -> None:
    """-0.0 and 0.0 are one dict key but have different reprs, which flipped the
    order of a repr-sorted partition."""
    a = _candidate(1.0, Condition(temperature_c=-0.0))
    b = _candidate(2.0, Condition(temperature_c=0.0))
    assert a.condition.grouping_key() == b.condition.grouping_key()
    assert comparison_groups([a, b]) == comparison_groups([b, a])


def test_derived_serialises_deterministically() -> None:
    """A frozenset serialises in hash order, randomised per process — the one
    thing a store justified by byte-determinism must not do."""
    condition = Condition(
        basis=MeasurementBasis.STC, derived=frozenset({"basis", "temperature_c", "side"})
    )
    assert '"derived":["basis","side","temperature_c"]' in condition.model_dump_json(
        exclude_defaults=False
    ).replace(", ", ",")


@pytest.mark.parametrize("candidates", [[], [AGREEMENT]])
def test_fewer_than_two_candidates_is_not_a_comparison(
    candidates: list[ConflictCandidate],
) -> None:
    assert comparison_pairs(candidates) == []


def test_groups_are_display_only_and_still_deterministic() -> None:
    groups = comparison_groups([CEC, AGREEMENT, DATASHEET])
    assert groups == comparison_groups([DATASHEET, CEC, AGREEMENT])
    assert sum(len(group) for group in groups) == 3


def test_output_is_a_golden_ordered_list() -> None:
    """Permutation self-consistency is not enough — it passes under a mutation
    that reverses every pair's orientation, because the reversal is consistent.
    Verified: flipping `(left, right)` to `(right, left)` kept all 79 tests green.
    A canonical order needs a literal expected list.

    Both stated candidates carry `basis=MeasurementBasis.STC`, so they are comparable with each
    other as well as with the unstated agreement - three pairs, not two. Writing
    this expectation is what surfaced that; the permutation test could not.
    """
    pairs = comparison_pairs([CEC, AGREEMENT, DATASHEET])
    assert [(float(a.value), float(b.value)) for a, b in pairs] == [  # type: ignore[arg-type]
        (645.0, 700.0),
        (645.0, 650.0),
        (700.0, 650.0),
    ]


def test_candidates_differing_only_in_verbatim_value_still_order_canonically() -> None:
    """`_ordering_key` once omitted `verbatim_value`, `confidence` and the
    condition's `note`/`derived`. Candidates differing only in those tied, and
    `sorted` being stable then leaked arrival order into both the list and each
    pair's orientation — while `verbatim_value` is FR-HITL-03-mandated payload."""
    a = ConflictCandidate(
        value=650.0,
        unit="W",
        verbatim_value="650 W",
        condition=Condition(),
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="doc-same"),
        confidence=0.9,
    )
    b = a.model_copy(update={"verbatim_value": "650Wp"})
    forward = comparison_pairs([a, b])
    backward = comparison_pairs([b, a])
    assert [(x.verbatim_value, y.verbatim_value) for x, y in forward] == [
        (x.verbatim_value, y.verbatim_value) for x, y in backward
    ]


def test_a_queue_entry_never_holds_two_incomparable_candidates() -> None:
    """The P0. Pairs correctly omit (352, 320.865), but the *union* of pair
    members is {352, 320, 320.865} — folding that into one entry puts @30 degC
    and @40 degC in the same payload, recreating the exact false conflict
    `Condition` exists to prevent. `conflict_groupings` is one pair per entry."""
    eu = _candidate(352.0, Condition(temperature_c=30.0), SourceTier.SYSTEM_OF_RECORD)
    bare = _candidate(320.0, Condition(), SourceTier.SYSTEM_OF_RECORD)
    cec = _candidate(320.865, Condition(temperature_c=40.0))

    union = {c.condition.temperature_c for pair in comparison_pairs([eu, bare, cec]) for c in pair}
    assert union == {None, 30.0, 40.0}, "the naive fold really does mix both temperatures"

    for group in conflict_groupings([eu, bare, cec]):
        assert len(group) == 2
        assert group[0].condition.comparable_with(group[1].condition)


def test_the_bridging_candidate_appears_in_two_entries() -> None:
    """Duplication is forced by the structure, not chosen. No partition of a
    non-transitive relation both avoids asserting an uncompared pair and keeps
    every real comparison — so the 320 W agreement value must appear twice."""
    eu = _candidate(352.0, Condition(temperature_c=30.0), SourceTier.SYSTEM_OF_RECORD)
    bare = _candidate(320.0, Condition(), SourceTier.SYSTEM_OF_RECORD)
    cec = _candidate(320.865, Condition(temperature_c=40.0))
    groups = conflict_groupings([eu, bare, cec])
    assert len(groups) == 2
    assert sum(1 for g in groups if any(c.value == 320.0 for c in g)) == 2
