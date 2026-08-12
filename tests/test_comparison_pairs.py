"""What may be compared, and in what order — issue #12.

Comparability is not transitive, so it cannot be a partition. Two attempts to
make it one both failed: first-fit bucketing was order-dependent, and exact-key
grouping stranded values whose conditions were merely less specific, silently
dropping the comparison. `comparison_pairs` carries the relation as pairs.
"""

import itertools
from decimal import Decimal
from enum import StrEnum
from typing import get_args

import pytest

from procurement_agent.schema import (
    Condition,
    ConditionDimensions,
    ConflictCandidate,
    MeasurementBasis,
    PowerSide,
    RteBoundary,
    SourceRef,
    SourceTier,
    UnencodableValueError,
)
from procurement_agent.services.conflict_hitl import (
    _canonical,
    _ordering_key,
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


#: Deliberately all-lowercase and free of `<`, `_` and every vocabulary spelling,
#: so the assertions below about what does *not* appear in the key cannot pass or
#: fail for a reason coming from the fixture rather than from the encoding.
_PLAIN = ConflictCandidate(
    value=650.0,
    unit="w",
    verbatim_value=None,
    condition=Condition(),
    source_tier=SourceTier.WEB_SUPPLEMENT,
    source_ref=SourceRef(document_id="doc-plain"),
    confidence=0.9,
)


def _key_text(candidate: ConflictCandidate) -> str:
    """The whole ordering key as one searchable string.

    Joined on a newline, which no component can contain: `json.dumps` escapes it
    inside a string, so a match below is always a match in one component rather
    than one straddling a boundary.
    """
    return "\n".join(_ordering_key(candidate))


def _vocabulary_members() -> list[tuple[str, StrEnum]]:
    """`(dimension, member)` for every closed vocabulary on a condition.

    Read off the annotations rather than from a hand-kept list, the same way
    `tests/test_condition_grouping._vocabulary_of` does, so a vocabulary added to
    `ConditionDimensions` is covered here without anyone remembering to register
    it - which is the only way this check keeps up with A-50's blast radius.
    """
    pairs: list[tuple[str, StrEnum]] = []
    for name, info in ConditionDimensions.model_fields.items():
        for arg in get_args(info.annotation):
            if isinstance(arg, type) and issubclass(arg, StrEnum):
                pairs.extend((name, member) for member in arg)
    return pairs


_VOCABULARY_MEMBERS = _vocabulary_members()


def test_the_vocabularies_are_actually_reached() -> None:
    """The parametrisation below is generated, so an annotation change that
    yielded nothing would silently turn every case into zero cases."""
    assert len(_VOCABULARY_MEMBERS) > 20
    assert {name for name, _ in _VOCABULARY_MEMBERS} == {
        "basis",
        "side",
        "weighting",
        "standards_regime",
        "rte_boundary",
    }


@pytest.mark.parametrize(
    "dimension,member",
    _VOCABULARY_MEMBERS,
    ids=[f"{name}-{member.name}" for name, member in _VOCABULARY_MEMBERS],
)
def test_a_vocabulary_member_orders_by_its_value_not_its_identity(
    dimension: str, member: StrEnum
) -> None:
    """A-50, stated as the property that makes it impossible rather than as a
    ban on one function.

    `repr()` of an enum member is `<MeasurementBasis.STC: 'stc'>` - it carries
    the class name and the *member name* alongside the value. Both are identity,
    not data: renaming `STC` to `STC_1000` changes the key, therefore the sort
    order, therefore the row order of any artifact composed from it, while every
    measurement in the store is untouched. That is the A-6 class this repo has now
    hit three times (unpinned `openpyxl`, `repr(grouping_key())`, and
    `_ordering_key` reintroducing it inside the fix for the second).

    Asserting the member name is *absent* is a proof rather than a proxy: if the
    name does not appear in the key, no rename of it can move the key.
    """
    # The dimension is chosen at runtime, so mypy sees the kwargs as one dict
    # widened to `StrEnum` rather than as the specific vocabulary each field
    # declares - the same reason the coercion tests in test_condition_grouping.py
    # carry this ignore.
    condition = Condition(**{dimension: member})  # type: ignore[arg-type]
    candidate = _PLAIN.model_copy(update={"condition": condition})
    text = _key_text(candidate)
    assert f'"{member.value}"' in text, "the value has to reach the key, or nothing is ordered"
    assert member.name not in text, f"{member.name} is a rename away from a different sort order"
    assert type(member).__name__ not in text, "the class name is identity, not data"


def test_the_ordering_key_carries_no_repr_artifact() -> None:
    """The cheap tripwire that would have caught A-50 on sight, kept alongside
    the property test because it needs no knowledge of which vocabularies exist.

    `<` cannot occur in a canonically encoded key here - `json.dumps` escapes
    nothing to it and no fixture value contains one - but it opens every enum,
    object and function `repr`, so its absence is exactly "nothing was repr'd".
    """
    rich = _PLAIN.model_copy(
        update={
            "condition": Condition(
                basis=MeasurementBasis.STC,
                side=PowerSide.DC,
                rte_boundary=RteBoundary.DC_DC_TERMINALS,
                temperature_c=25.0,
                derived=frozenset({"basis", "side"}),
            ),
            "source_tier": SourceTier.SYSTEM_OF_RECORD,
        }
    )
    assert "<" not in _key_text(rich)
    assert "0x" not in _key_text(rich), "a memory address in a sort key is not a canonical order"


def test_renaming_a_member_moves_neither_the_candidate_order_nor_the_display_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-50 as the event that must not happen, not as a ban on one function.

    Everything else here checks that `repr`'s artifacts are absent, which is a
    proof only for the artifacts anyone thought to name. This performs the rename
    and asserts the output does not move - the property itself, and the only test
    in this file that catches the display partition's outer sort, since no pair of
    real grouping keys happens to order differently under the two encodings.

    `STC` -> `AAA_RENAMED` is chosen so the *name* order against `NOCT` flips
    while the *value* order (`noct` before `stc`) cannot. Both surfaces are
    asserted against literals rather than against a second evaluation: the
    before-and-after form alone passes for any implementation that is merely
    self-consistent, which is the shape that once kept a whole-suite pair
    reversal green.
    """
    stc = _candidate(1.0, Condition(basis=MeasurementBasis.STC))
    noct = _candidate(2.0, Condition(basis=MeasurementBasis.NOCT))

    assert _values_of(comparison_groups([stc, noct])) == [[2.0], [1.0]]
    assert [c.value for c in sorted([stc, noct], key=_ordering_key)] == [2.0, 1.0]

    monkeypatch.setattr(MeasurementBasis.STC, "_name_", "AAA_RENAMED")
    assert repr(MeasurementBasis.STC) == "<MeasurementBasis.AAA_RENAMED: 'stc'>", (
        "the rename did not take, so the assertions below are vacuous"
    )
    assert MeasurementBasis.STC.value == "stc", "a rename must not touch the data"

    assert _values_of(comparison_groups([stc, noct])) == [[2.0], [1.0]]
    assert [c.value for c in sorted([stc, noct], key=_ordering_key)] == [2.0, 1.0]


def test_the_display_group_order_carries_no_repr_artifact() -> None:
    """The second half of A-50. `comparison_groups` sorted its buckets by
    `repr(grouping_key())`, which is the same defect one level up: the *order of
    the groups* moved on a rename.

    No pair of grouping keys actually reorders between the two encodings - within
    a tuple position the type set is {member, None} or {float, None}, and both
    encodings put the non-`None` first - so this cannot be written as an order
    assertion today. It is written as the property instead, which is the part
    that has to hold when a vocabulary is added.
    """
    key = Condition(
        basis=MeasurementBasis.STC, rte_boundary=RteBoundary.DC_DC_TERMINALS
    ).grouping_key()
    text = _canonical(key)
    assert "<" not in text
    assert "DC_DC_TERMINALS" not in text and "MeasurementBasis" not in text
    assert '"stc"' in text and '"dc_dc_terminals"' in text


def test_the_display_partition_is_ordered_by_that_same_encoding() -> None:
    """Binds `comparison_groups` to `_canonical` rather than leaving the check
    above testing a helper nothing is proven to call."""
    candidates = [
        _candidate(1.0, Condition(basis=MeasurementBasis.STC)),
        _candidate(2.0, Condition()),
        _candidate(3.0, Condition(temperature_c=30.0)),
        _candidate(4.0, Condition(side=PowerSide.DC)),
    ]
    groups = comparison_groups(candidates)
    keys = [group[0].condition.grouping_key() for group in groups]
    assert len(keys) == 4
    assert keys == sorted(keys, key=_canonical)


def test_a_decimal_and_an_absent_value_order_by_the_encoded_form() -> None:
    """The one pair in the realistic value domain where `repr` and the canonical
    encoding disagree, so this is what makes the `_ordering_key` change *visible*
    rather than merely argued.

    `repr(Decimal("650"))` is `Decimal('650')` and sorts before `None`; the
    encoded forms are `{"$decimal":"650"}` and `null`, and `{` sorts after `n`.
    Both candidates are realistic: D-2's EXACT catalog values are naturally
    `Decimal`, and `values_conflict` has a branch for a candidate with no value
    at all.

    The order itself carries no meaning and is not meant to - what it has to be
    is a function of the *content*, which `Decimal('650')` is not.
    """
    priced = _PLAIN.model_copy(update={"value": Decimal("650")})
    absent = _PLAIN.model_copy(update={"value": None})
    pairs = comparison_pairs([priced, absent])
    assert len(pairs) == 1
    assert pairs[0][0].value is None, "the key must follow the encoding, not repr"
    assert comparison_pairs([absent, priced]) == pairs


#: Six values D-2 and the schema all treat as distinct, four of which print `650`
#: in some form. A key that collapses any two of them is *worse* than a wrong
#: order: `sorted` is stable, so a tie does not reorder - it silently readmits
#: arrival order, which is the exact defect `_ordering_key` exists to prevent and
#: the one an encoder can introduce where `repr` could not.
_INJECTIVITY_DOMAIN: list[object] = [Decimal("650"), Decimal("650.0"), 650, 650.0, "650", None]


def test_the_value_domain_does_not_collapse_under_the_encoding() -> None:
    """`repr` separated these by accident of syntax. The encoder has to separate
    them on purpose, which is why `Decimal` carries a tag and `bool` does not."""
    candidates = [_PLAIN.model_copy(update={"value": value}) for value in _INJECTIVITY_DOMAIN]
    keys = [_ordering_key(candidate) for candidate in candidates]
    assert len(set(keys)) == len(_INJECTIVITY_DOMAIN)
    # `Decimal("650")` and `Decimal("650.0")` are `==` and hash alike, so a key
    # built from the value rather than its printed text ties them - and D-2 reads
    # the rounding floor off exactly that text (`_decimals`), so they are two
    # different comparisons, not two spellings of one.
    assert keys[0] != keys[1]


def test_a_value_outside_the_encoding_table_is_refused_rather_than_ordered() -> None:
    """The closed world, at the one place it changes behaviour.

    `ConflictCandidate.value` is `object | None`, so `repr` was happy to order a
    bare object by `<object object at 0x...>` - an address that differs between
    runs, which is a canonical order that silently is not one. Refusing is the
    only honest answer: the same value has to be encodable for the C6 projection
    anyway, so failing at the sort surfaces it at the earliest point instead of
    at artifact time.
    """
    exotic = _PLAIN.model_copy(update={"value": object()})
    with pytest.raises(UnencodableValueError):
        comparison_pairs([exotic, _PLAIN])
    with pytest.raises(UnencodableValueError):
        _ordering_key(exotic)
