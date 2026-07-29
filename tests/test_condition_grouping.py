"""Grouping candidate values must not depend on the order they arrive.

Issue #12. `comparable_with` is not transitive, so it cannot partition a
candidate set; `grouping_key()` can, because equality is an equivalence
relation. FR-OUT-06 requires composition to be a pure function of the store,
which fails the moment the conflict queue depends on ingest order.
"""

import itertools

import pytest
from pydantic import ValidationError

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
    """A new dimension must participate in grouping without anyone remembering.

    Asserted against `Condition`'s own fields, not against `ConditionDimensions`.
    The obvious form - comparing `len(grouping_key())` to
    `len(ConditionDimensions.model_fields)` - is a tautology, since the key is
    built by iterating exactly that. It passes even when a genuinely comparable
    dimension is added to `Condition`, which is the case it exists to catch.
    """
    annotations = set(Condition.model_fields) - set(ConditionDimensions.model_fields)
    assert annotations == {"note", "derived"}, (
        "A field added to Condition rather than ConditionDimensions is excluded "
        "from grouping and comparison. If it is a measurement condition it belongs "
        "on ConditionDimensions; if it is an annotation, list it here."
    )


def test_non_finite_conditions_are_rejected() -> None:
    """NaN would break reflexivity: NaN != NaN, so two identically-conditioned
    values would never group together, and pydantic serialises NaN to JSON null
    so the same record would group differently after a store round-trip."""
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            Condition(temperature_c=bad)


def test_grouping_is_stable_across_a_store_round_trip() -> None:
    """FR-OUT-06 purity: persisting and reloading must not move a value's group."""
    original = Condition(basis="stc", temperature_c=25.0, base_mva=10.0)
    revived = Condition.model_validate_json(original.model_dump_json())
    assert revived.grouping_key() == original.grouping_key()


def test_vocabulary_case_does_not_split_a_group() -> None:
    """Under exact-key grouping an unnormalised variant does not raise a false
    conflict - it silently suppresses the comparison, which cannot be reviewed."""
    assert Condition(basis="STC").grouping_key() == Condition(basis=" stc ").grouping_key()
    assert Condition(side="DC").grouping_key() == Condition(side="dc").grouping_key()


def test_base_mva_is_a_grouping_dimension_not_a_note() -> None:
    """IEEE refers %Z to the ONAN base and IEC to the top rating, so two figures
    on different bases differ by 1.25-1.67x - far beyond the +/-7.5% tolerance.
    Left in `note` they would have grouped together and been compared."""
    assert Condition(base_mva=10.0).grouping_key() != Condition(base_mva=12.5).grouping_key()


def test_derived_does_not_split_a_group() -> None:
    """A defaulted STC value and a stated STC value are the same measurement."""
    stated = Condition(basis="stc")
    defaulted = Condition(basis="stc", derived=frozenset({"basis"}))
    assert stated.grouping_key() == defaulted.grouping_key()
    assert defaulted.derived == frozenset({"basis"})
