"""Grouping candidate values must not depend on the order they arrive.

Issue #12. `comparable_with` is not transitive, so it cannot partition a
candidate set; `grouping_key()` can, because equality is an equivalence
relation. FR-OUT-06 requires composition to be a pure function of the store,
which fails the moment the conflict queue depends on ingest order.
"""

import itertools
import pathlib
import re
from enum import StrEnum
from typing import get_args

import pytest
from pydantic import ValidationError

from procurement_agent.schema import (
    Condition,
    ConditionDimensions,
    EfficiencyWeighting,
    MeasurementBasis,
    PowerSide,
    StandardsRegime,
)

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
    assert (
        Condition(basis=MeasurementBasis.STC).grouping_key()
        == Condition(basis=MeasurementBasis.STC).grouping_key()
    )
    assert (
        len(
            {
                Condition(basis=MeasurementBasis.STC).grouping_key(),
                Condition(basis=MeasurementBasis.STC).grouping_key(),
            }
        )
        == 1
    )


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
    original = Condition(basis=MeasurementBasis.STC, temperature_c=25.0, base_mva=10.0)
    revived = Condition.model_validate_json(original.model_dump_json())
    assert revived.grouping_key() == original.grouping_key()


def test_vocabulary_case_does_not_split_a_group() -> None:
    """Under exact-key grouping an unnormalised variant does not raise a false
    conflict - it silently suppresses the comparison, which cannot be reviewed."""
    upper = Condition(basis="STC").grouping_key()  # type: ignore[arg-type]
    padded = Condition(basis=" stc ").grouping_key()  # type: ignore[arg-type]
    assert upper == padded
    upper_side = Condition(side="DC").grouping_key()  # type: ignore[arg-type]
    assert upper_side == Condition(side=PowerSide.DC).grouping_key()


def test_base_mva_is_a_grouping_dimension_not_a_note() -> None:
    """IEEE refers %Z to the ONAN base and IEC to the top rating, so two figures
    on different bases differ by 1.25-1.67x - far beyond the +/-7.5% tolerance.
    Left in `note` they would have grouped together and been compared."""
    assert Condition(base_mva=10.0).grouping_key() != Condition(base_mva=12.5).grouping_key()


def test_derived_does_not_split_a_group() -> None:
    """A defaulted STC value and a stated STC value are the same measurement."""
    stated = Condition(basis=MeasurementBasis.STC)
    defaulted = Condition(basis=MeasurementBasis.STC, derived=frozenset({"basis"}))
    assert stated.grouping_key() == defaulted.grouping_key()
    assert defaulted.derived == frozenset({"basis"})


def test_an_unrecognised_vocabulary_token_is_rejected() -> None:
    """Issue #16. The frozen contract's own rule: "Extraction returning a value
    outside the set is a validation failure, not a silent pass-through." With a
    bare `str` it was exactly that pass-through — and under exact-key grouping a
    junk token does not raise a false conflict, it silently forms its own group
    and suppresses the comparison, which nothing surfaces."""
    for field, junk in [
        ("basis", "not_a_real_basis"),
        ("side", "middle"),
        ("weighting", "japanese"),
        ("standards_regime", "ansi"),
    ]:
        with pytest.raises(ValidationError):
            Condition(**{field: junk})  # type: ignore[arg-type]


def test_vocabulary_normalisation_runs_before_enum_coercion() -> None:
    """`"  STC "` has to fold to `stc` and *then* coerce, or closing the
    vocabulary would break every datasheet that prints conditions in caps."""
    # Raw strings on purpose: this is the coercion path, so the arguments are
    # deliberately not enum members.
    assert Condition(basis="  STC ").basis is MeasurementBasis.STC  # type: ignore[arg-type]
    assert Condition(side="DC").side is PowerSide.DC  # type: ignore[arg-type]
    weighting = Condition(weighting=" European").weighting  # type: ignore[arg-type]
    assert weighting is EfficiencyWeighting.EUROPEAN
    regime = Condition(standards_regime="IEC").standards_regime  # type: ignore[arg-type]
    assert regime is StandardsRegime.IEC


def test_an_undated_sat_is_legal_and_never_aliased() -> None:
    """Closing the vocabulary turns a missing member into a validation failure, so
    a datasheet printing "SAT" with no epoch needs one of its own (decision 6).
    It must not alias onto either dated member: `basis` is a grouping dimension,
    so aliasing would silently merge one-month and three-month measurements."""
    undated = Condition(basis=MeasurementBasis.SAT)
    assert undated.basis is MeasurementBasis.SAT
    assert undated.grouping_key() != Condition(basis=MeasurementBasis.SAT_1MO).grouping_key()
    assert undated.grouping_key() != Condition(basis=MeasurementBasis.SAT_3MO).grouping_key()


def test_the_contract_conditions_table_names_only_real_fields() -> None:
    """The table routed three real dimensions through `note`, which comparison
    ignores. Amending it is part of #16, so the amendment is checked here rather
    than trusted: every backticked name in the Conditions table is either a field
    that actually gates comparison, or - inside an `in {...}` clause - a member of
    that field's closed vocabulary. Otherwise the contract describes a rule the
    code does not implement, which is how the `note` routing survived in the first
    place.
    """
    contract = pathlib.Path(__file__).parent.parent / (
        "specs/001-procurement-agent/contracts/canonical-parameters.md"
    )
    table = contract.read_text(encoding="utf-8").split("## Conditions", 1)[1]
    rows = [line for line in table.splitlines() if line.startswith("| ") and " | " in line]

    fields: set[str] = set()
    for row in rows:
        required = row.split("|")[2]
        # `basis` in {`stc`, ...}: the head is a field, the braces hold its vocabulary.
        for head, listed in re.findall(r"`([a-z_]+)`\s*∈\s*\{([^}]*)\}", required):
            annotation = ConditionDimensions.model_fields[head].annotation
            # Resolved from the annotation rather than a hand-kept mapping, so a
            # new closed-vocabulary dimension is covered without registering it.
            enums = [
                arg
                for arg in get_args(annotation)
                if isinstance(arg, type) and issubclass(arg, StrEnum)
            ]
            assert enums, f"the table gives `{head}` a vocabulary but its type is open"
            vocabulary = {member.value for member in enums[0]}
            named = set(re.findall(r"`([a-z_0-9]+)`", listed))
            assert named <= vocabulary, f"`{head}` in the table admits {named - vocabulary}"
            fields.add(head)
            required = required.replace(f"{{{listed}}}", "")
        fields |= set(re.findall(r"`([a-z_]+)`", required))

    unknown = fields - set(ConditionDimensions.model_fields)
    assert not unknown, f"the Conditions table names {unknown}, which gate nothing"
    assert {"rte_boundary", "tap_position", "base_mva"} <= fields, (
        "the three dimensions promoted out of `note` must appear in the table"
    )

    # The cycle-life row is the one place the table wrote a `basis` vocabulary as
    # prose - "EOL SOH threshold (60/70/80%)" - where every other row writes
    # tokens. Prose passes the check above vacuously, because it backticks no
    # member for the check to reject, so pin the tokens it must now name.
    cycle_life = next(row for row in rows if "cycle life" in row)
    assert re.search(r"`soh_60`.*`soh_70`.*`soh_80`", cycle_life), (
        "cycle life must name its `basis` vocabulary as tokens, not as a percentage"
    )


def test_rte_boundary_gates_comparison() -> None:
    """Four distinct boundaries are all called "round-trip efficiency", worth 2-7
    percentage points. The contract routes this through `note`, which comparison
    ignores, so an 88% including-auxiliaries figure compared as like-for-like with
    a 93% excluding-auxiliaries one and fabricated a 5 pp conflict."""
    including = Condition(duration_h=4.0, rte_boundary="includes_auxiliaries")
    excluding = Condition(duration_h=4.0, rte_boundary="excludes_auxiliaries")
    assert not including.comparable_with(excluding)
    assert including.grouping_key() != excluding.grouping_key()


def test_tap_position_gates_comparison() -> None:
    """Nominal-tap and +5%-tap impedance are not the same measurement."""
    assert not Condition(tap_position="nominal").comparable_with(Condition(tap_position="+5"))
