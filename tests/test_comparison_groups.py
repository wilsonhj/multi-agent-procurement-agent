"""Grouping must be deterministic *and* must not lose comparisons.

Issue #12. Partitioning on `grouping_key()` alone fixes order-dependence but is
strictly comparison-losing: a contract stating a bare number would be compared
against nothing, so the system-of-record value FR-HITL-02 exists to protect
would never reach the queue. `comparison_groups` folds wholly-unstated
candidates into every stated group, which keeps both properties.
"""

import itertools

from procurement_agent.schema import Condition, ConflictCandidate, SourceRef, SourceTier
from procurement_agent.services.conflict_hitl import comparison_groups


def _candidate(value: float, condition: Condition, tier: SourceTier) -> ConflictCandidate:
    return ConflictCandidate(
        value=value,
        unit="W",
        condition=condition,
        source_tier=tier,
        source_ref=SourceRef(document_id=f"doc-{value}"),
        confidence=0.9,
    )


#: The realistic corpus: a commercial contract states a number with no test
#: condition; datasheets and listings always state one.
AGREEMENT = _candidate(650.0, Condition(), SourceTier.SYSTEM_OF_RECORD)
DATASHEET = _candidate(700.0, Condition(basis="stc"), SourceTier.WEB_SUPPLEMENT)
CEC = _candidate(645.0, Condition(basis="stc"), SourceTier.WEB_SUPPLEMENT)


def _pairs(groups: list[list[ConflictCandidate]]) -> set[tuple[float, float]]:
    seen: set[tuple[float, float]] = set()
    for group in groups:
        for a, b in itertools.combinations(group, 2):
            seen.add(tuple(sorted((float(a.value), float(b.value)))))  # type: ignore[arg-type]
    return seen


def test_the_system_of_record_value_is_not_stranded() -> None:
    """The defect that made exact-key grouping worse than the bug it replaced.

    A 7.1% disagreement between a signed supply agreement and the manufacturer
    datasheet changes module count and $/W. Grouping on the key alone leaves the
    650 W agreement value alone in its own group, compared against nothing, so no
    queue entry is raised and the compose gate never fires.
    """
    pairs = _pairs(comparison_groups([AGREEMENT, DATASHEET, CEC]))
    assert (650.0, 700.0) in pairs
    assert (645.0, 650.0) in pairs
    assert (645.0, 700.0) in pairs


def test_grouping_is_independent_of_arrival_order() -> None:
    """The property exact-key grouping was adopted for, kept after the fold."""
    partitions = {
        frozenset(_pairs(comparison_groups(list(order))))
        for order in itertools.permutations([AGREEMENT, DATASHEET, CEC])
    }
    assert len(partitions) == 1


def test_values_under_genuinely_different_conditions_are_not_compared() -> None:
    """The Sungrow case still holds: @30 degC and @40 degC never meet."""
    eu = _candidate(352.0, Condition(temperature_c=30.0), SourceTier.SYSTEM_OF_RECORD)
    cec = _candidate(320.865, Condition(temperature_c=40.0), SourceTier.WEB_SUPPLEMENT)
    assert (320.865, 352.0) not in _pairs(comparison_groups([eu, cec]))


def test_an_unstated_candidate_reaches_every_stated_group() -> None:
    """It is a legitimate counterpart to each, so it appears in more than one."""
    eu = _candidate(352.0, Condition(temperature_c=30.0), SourceTier.WEB_SUPPLEMENT)
    cec = _candidate(320.0, Condition(temperature_c=40.0), SourceTier.WEB_SUPPLEMENT)
    bare = _candidate(340.0, Condition(), SourceTier.SYSTEM_OF_RECORD)
    groups = comparison_groups([eu, cec, bare])
    assert len(groups) == 2
    assert all(any(c.value == 340.0 for c in group) for group in groups)


def test_all_unstated_candidates_still_compare_with_each_other() -> None:
    """With nothing stated anywhere there is one group, not N singletons."""
    a = _candidate(650.0, Condition(), SourceTier.SYSTEM_OF_RECORD)
    b = _candidate(700.0, Condition(), SourceTier.WEB_SUPPLEMENT)
    assert _pairs(comparison_groups([a, b])) == {(650.0, 700.0)}


def test_no_candidates_yields_no_groups() -> None:
    assert comparison_groups([]) == []


def test_a_single_candidate_is_not_a_comparison() -> None:
    assert _pairs(comparison_groups([AGREEMENT])) == set()
