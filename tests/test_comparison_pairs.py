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
    PowerSide,
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
    order of a repr-sorted partition.

    A **third** group is essential and the earlier version of this test lacked
    it. `-0.0 == 0.0` and their hashes match, so the two candidates land in one
    group under either implementation and both assertions passed with the
    normalisation removed. The reordering only manifests once there is another
    group for the signed key to sort against."""
    a = _candidate(1.0, Condition(temperature_c=-0.0))
    b = _candidate(2.0, Condition(temperature_c=0.0))
    # The third group has to have a repr that falls *between* `-0.0` and `0.0`,
    # or the flip is invisible: `(None, -0.0, ...)` and `(None, 0.0, ...)` differ
    # at one character, and no float repr sorts between `-` and `0`. Reaching in
    # on a later dimension does - `(None, 0.0, <PowerSide.DC...)` sorts after the
    # signed key and before the unsigned one.
    other = _candidate(3.0, Condition(temperature_c=0.0, side=PowerSide.DC))
    assert a.condition.grouping_key() == b.condition.grouping_key()
    assert comparison_groups([a, b]) == comparison_groups([b, a])
    assert comparison_groups([a, b, other]) == comparison_groups([b, a, other])
    assert _values_of(comparison_groups([a, b, other])) == [[3.0], [1.0, 2.0]]


def _values_of(groups: list[list[ConflictCandidate]]) -> list[list[float]]:
    return [[float(c.value) for c in group] for group in groups]  # type: ignore[arg-type]


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
    """Asserted as a literal partition, not as a total.

    `sum(len(group)) == 3` is satisfied by one group of three, so it passed with
    the grouping key replaced by a constant — every candidate in one bucket,
    which is exactly the false-conflict shape `Condition` exists to prevent."""
    assert _values_of(comparison_groups([CEC, AGREEMENT, DATASHEET])) == [[645.0, 700.0], [650.0]]


@pytest.mark.parametrize("order", list(itertools.permutations([0, 1, 2])))
def test_every_permutation_gives_the_same_display_partition(order: tuple[int, ...]) -> None:
    """All six, not the two an earlier version hand-picked — and both of those
    happened to start with a `basis=stc` candidate, so dict insertion order was
    identical in each and dropping the outer sort survived."""
    candidates = [CEC, AGREEMENT, DATASHEET]
    assert _values_of(comparison_groups([candidates[i] for i in order])) == [
        [645.0, 700.0],
        [650.0],
    ]


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


#: One mutation per element of `_ordering_key`: two candidates that differ in
#: exactly that element and nothing else. Anything the key omits leaves them
#: tied, and `sorted` being stable then leaks arrival order into the pair's
#: orientation — which is the whole failure `_ordering_key` exists to prevent.
_DISTINGUISHING: list[tuple[str, dict[str, object]]] = [
    ("condition", {"condition": Condition(basis=MeasurementBasis.STC)}),
    ("value", {"value": 651.0}),
    ("unit", {"unit": "Wp"}),
    ("source_tier", {"source_tier": SourceTier.WEB_SUPPLEMENT}),
    ("source_ref", {"source_ref": SourceRef(document_id="doc-other")}),
    ("verbatim_value", {"verbatim_value": "650Wp"}),
    ("confidence", {"confidence": 0.8}),
    ("note", {"condition": Condition(note="page 3")}),
    ("derived", {"condition": Condition(derived=frozenset({"basis"}))}),
]


@pytest.mark.parametrize("element,change", _DISTINGUISHING, ids=[n for n, _ in _DISTINGUISHING])
def test_every_ordering_element_is_load_bearing(element: str, change: dict[str, object]) -> None:
    """Each element of `_ordering_key` in turn, because dropping any one of seven
    of them left the whole suite green.

    The base candidate deliberately does *not* derive its `document_id` from its
    value: the older fixture built `SourceRef(document_id=f"doc-{value}")`, so
    `source_ref` was a proxy for `value` and dropping either from the key was
    masked by the other.
    """
    base = ConflictCandidate(
        value=650.0,
        unit="W",
        verbatim_value="650 W",
        condition=Condition(),
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="doc-fixed"),
        confidence=0.9,
    )
    other = base.model_copy(update=change)
    assert other != base, f"the {element} fixture does not actually differ"

    forward = comparison_pairs([base, other])
    backward = comparison_pairs([other, base])
    assert len(forward) == 1 and len(backward) == 1
    assert forward[0][0] == backward[0][0], (
        f"candidates differing only in {element} tie under `_ordering_key`, so the "
        "pair's orientation follows arrival order"
    )


#: The three `_ordering_key` elements that were folded through `x or ""`, which
#: maps `None` and `""` onto the same component. Each case is a pair that differs
#: only in absent-versus-empty.
_ABSENT_VERSUS_EMPTY: list[tuple[str, dict[str, object], dict[str, object]]] = [
    ("verbatim_value", {"verbatim_value": None}, {"verbatim_value": ""}),
    ("unit", {"unit": None}, {"unit": ""}),
    ("note", {"condition": Condition()}, {"condition": Condition(note="")}),
]


@pytest.mark.parametrize(
    "element,absent,empty", _ABSENT_VERSUS_EMPTY, ids=[n for n, _, _ in _ABSENT_VERSUS_EMPTY]
)
def test_absent_and_empty_do_not_tie_the_ordering_key(
    element: str, absent: dict[str, object], empty: dict[str, object]
) -> None:
    """`_ordering_key` promises a total order, and `x or ""` broke it.

    `None` and `""` are distinct candidate states that folded onto one key
    component, so two distinct candidates tied - and `sorted` being stable then
    leaked arrival order back into the pair's orientation. That is the same
    defect the key's own docstring says adding `verbatim_value` fixed, reached
    through a different door.

    `schema.field._normalise_token` guards the condition vocabularies against
    exactly this substitution - an extractor emitting `""` where `None` is meant -
    so the schema already treats it as worth defending against. Nothing normalises
    a candidate's `unit` or `verbatim_value`.
    """
    base = ConflictCandidate(
        value=650.0,
        unit="W",
        verbatim_value="650 W",
        condition=Condition(),
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="doc-fold"),
        confidence=0.9,
    )
    a = base.model_copy(update=absent)
    b = base.model_copy(update=empty)
    assert a != b, f"the {element} fixture does not actually differ"

    forward = comparison_pairs([a, b])
    backward = comparison_pairs([b, a])
    assert len(forward) == 1 and len(backward) == 1
    assert forward[0][0] == backward[0][0], (
        f"an absent {element} and an empty one tie under `_ordering_key`, so the "
        "pair's orientation follows arrival order"
    )


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
