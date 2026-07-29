"""Grouping candidate values must not depend on the order they arrive.

Issue #12. `comparable_with` is not transitive, so it cannot partition a
candidate set; `grouping_key()` can, because equality is an equivalence
relation. FR-OUT-06 requires composition to be a pure function of the store,
which fails the moment the conflict queue depends on ingest order.
"""

import itertools

from procurement_agent.schema import Condition, ConditionDimensions

#: The Sungrow SG350HX case: an EU sheet at 30 degC, a distributor page stating
#: no condition at all, and the CEC listing at 40 degC.
EU = Condition(temperature_c=30.0)
SILENT = Condition()
CEC = Condition(temperature_c=40.0)


def _first_fit_buckets(conditions: list[Condition]) -> list[list[Condition]]:
    """Bucket by pairwise comparability - the natural, and wrong, implementation."""
    buckets: list[list[Condition]] = []
    for candidate in conditions:
        for bucket in buckets:
            if all(candidate.comparable_with(member) for member in bucket):
                bucket.append(candidate)
                break
        else:
            buckets.append([candidate])
    return buckets


def _key_buckets(conditions: list[Condition]) -> list[list[Condition]]:
    """Bucket by grouping key - transitive, so order cannot matter."""
    grouped: dict[tuple[object, ...], list[Condition]] = {}
    for candidate in conditions:
        grouped.setdefault(candidate.grouping_key(), []).append(candidate)
    return [grouped[key] for key in sorted(grouped, key=repr)]


def test_comparable_with_is_not_transitive() -> None:
    """Pinned deliberately: this is why `comparable_with` must not group."""
    assert EU.comparable_with(SILENT)
    assert SILENT.comparable_with(CEC)
    assert not EU.comparable_with(CEC)


def test_pairwise_bucketing_is_order_dependent() -> None:
    """The defect, captured so a future refactor cannot quietly reintroduce it."""
    forward = _first_fit_buckets([EU, SILENT, CEC])
    reverse = _first_fit_buckets([CEC, SILENT, EU])
    assert [len(b) for b in forward] == [2, 1]
    assert [len(b) for b in reverse] == [2, 1]
    assert {id(c) for c in forward[0]} != {id(c) for c in reverse[0]}


def test_grouping_key_is_order_independent() -> None:
    """Every permutation of the same candidates yields the same partition."""
    partitions = {
        tuple(tuple(c.grouping_key() for c in bucket) for bucket in _key_buckets(list(order)))
        for order in itertools.permutations([EU, SILENT, CEC])
    }
    assert len(partitions) == 1


def test_grouping_key_separates_the_three_conditions() -> None:
    """Unstated conditions form their own group rather than bridging two others."""
    assert len(_key_buckets([EU, SILENT, CEC])) == 3


def test_grouping_key_is_hashable_and_equal_for_equal_conditions() -> None:
    assert Condition(basis="stc").grouping_key() == Condition(basis="stc").grouping_key()
    assert len({Condition(basis="stc").grouping_key(), Condition(basis="stc").grouping_key()}) == 1


def test_grouping_key_ignores_note() -> None:
    """Free text is provenance for a human, not a comparison dimension."""
    a = Condition(temperature_c=40.0, note="page 3 table")
    b = Condition(temperature_c=40.0, note="summary block")
    assert a.grouping_key() == b.grouping_key()


def test_grouping_key_covers_every_comparable_dimension() -> None:
    """A new dimension must participate in grouping without anyone remembering."""
    assert len(Condition().grouping_key()) == len(ConditionDimensions.model_fields)
    assert "note" not in ConditionDimensions.model_fields
