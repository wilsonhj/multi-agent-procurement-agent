"""Conflict & HITL (FR-HITL-01 .. FR-HITL-06).

Field-level reconciliation, conflict queue, human-resolution interface,
decision logging.

This module owns the spec's hardest invariant, so it is the one place in the
scaffolding where behaviour is implemented rather than stubbed: FR-HITL-02 says
the system shall NOT auto-arbitrate web against an ingested contract or spec
sheet. `assert_no_autonomous_overwrite` is the chokepoint that enforces it, and
AC-2 tests it directly.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence

from ...schema import CanonicalField, ConflictCandidate, SourceTier


def _ordering_key(candidate: ConflictCandidate) -> tuple[str, ...]:
    """A total order over candidates that depends only on their content.

    Needed because FR-OUT-06 makes composition a pure function of the store: any
    list the queue payload is built from has to be arranged by what a candidate
    *is*, never by when it arrived.

    Every field of the candidate participates. An earlier version keyed on only
    five of them, so two candidates differing solely in `verbatim_value` - which
    FR-HITL-03 *requires* the queue to carry - tied, and `sorted` being stable
    then preserved arrival order in both the list and each pair's orientation.
    A key that is not total is not a canonical order.
    """
    return (
        repr(candidate.condition.grouping_key()),
        repr(candidate.value),
        candidate.unit or "",
        candidate.source_tier.value,
        repr(candidate.source_ref.model_dump(mode="json")),
        candidate.verbatim_value or "",
        repr(candidate.confidence),
        candidate.condition.note or "",
        repr(sorted(candidate.condition.derived)),
    )


def comparison_pairs(
    candidates: Sequence[ConflictCandidate],
) -> list[tuple[ConflictCandidate, ConflictCandidate]]:
    """Every pair of candidates that may be compared like for like.

    **Pairs, not groups.** Comparability is genuinely not transitive - `@30 degC`
    and `@40 degC` are each comparable with an unstated condition but not with
    each other - and that is a fact about the domain, not a defect to design
    around. A partition has to be transitive, so any attempt to express this as
    groups must either bucket by arrival order (nondeterministic) or partition on
    exact condition equality (which strands values whose conditions are merely
    *less* specific, and silently drops the comparison). Pairs carry the relation
    exactly as it is.

    Both failures were shipped here before, so they are worth naming. First-fit
    bucketing over `comparable_with` gave a different conflict queue depending on
    document order. Exact-key grouping then made it worse: a supply agreement
    stating `650 W` with no test condition stranded alone while the datasheet and
    CEC listing, both marked STC, compared only with each other - so the
    system-of-record value FR-HITL-02 exists to protect reached no queue entry and
    the compose gate never fired. A visible false positive had become an invisible
    false negative, and a reviewer cannot dismiss what they never see.

    Deterministic because the result is a function of the candidate *set*: every
    unordered pair is generated once, each pair is internally ordered by
    `_ordering_key`, and the list is sorted by the same key. No pair is emitted
    twice, so a disagreement between two unstated values is raised once no matter
    how many stated conditions sit alongside it.

    `Condition.grouping_key()` remains the right tool for *displaying* candidates
    grouped by condition; it is not the right tool for deciding what to compare.
    """
    ordered = sorted(candidates, key=_ordering_key)
    return [
        (left, right)
        for left, right in itertools.combinations(ordered, 2)
        if left.condition.comparable_with(right.condition)
    ]


def conflict_groupings(
    candidates: Sequence[ConflictCandidate],
) -> list[tuple[ConflictCandidate, ConflictCandidate]]:
    """The candidate sets a `ConflictQueueEntry` may be built from: **exactly one
    comparable pair each**.

    A contract, not an implementation detail, because the alternative is provably
    impossible. Take the Sungrow trio - `352 W @30 degC`, an unqualified `320 W`
    from a supply agreement, `320.865 W @40 degC`. Comparability has edges A-B and
    B-C but not A-C. Enumerate every partition of three elements:

        {A,B,C}        asserts A-C   - the false conflict Condition exists to stop
        {A,B} {C}      loses B-C
        {B,C} {A}      loses A-B
        {A,C} {B}      asserts A-C
        {A} {B} {C}    loses both

    **No partition works.** An entry whose `candidates` list has length n asserts
    that all C(n,2) members are like-for-like - that is what asking a human to
    choose among them means - so a non-transitive relation cannot be covered by
    disjoint sets. Duplication is forced by the structure, not chosen: B must
    appear in two entries.

    Connected-component folding is the trap, because it looks like the natural
    answer and collapses to `{A,B,C}` here - identical to the union, identical to
    the forbidden case. Grouping by exact condition is the opposite trap: three
    singletons and no conflict raised at all.

    This does not breach FR-HITL-03, whose "all candidate values" is scoped to *a
    conflict*; it redefines what a conflict is. Two consequences it does not
    solve, which contract C5 still owes a rule for:

    - **Cross-entry resolution coherence.** With B in two entries a reviewer can
      select A in one and C in the other, leaving one field with two contradictory
      canonical values. Nothing constrains that today.
    - **Queue inflation.** n mutually comparable candidates yield C(n,2) entries
      rather than one, against a review budget `Settings.review_budget_fraction`
      explicitly meters.
    """
    return comparison_pairs(candidates)


def comparison_groups(candidates: Sequence[ConflictCandidate]) -> list[list[ConflictCandidate]]:
    """Candidates partitioned by exact condition, for display only.

    Deterministic - the partition is by `grouping_key()` equality and both the
    groups and their members are canonically sorted. Use `comparison_pairs` to
    decide what to compare: this partition strands a candidate whose condition is
    merely less specific than its neighbours', which is a presentation choice, not
    a comparison rule.
    """
    grouped: dict[tuple[object, ...], list[ConflictCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.condition.grouping_key(), []).append(candidate)
    return [
        sorted(grouped[key], key=_ordering_key) for key in sorted(grouped, key=lambda k: repr(k))
    ]


class AutonomousOverwriteError(RuntimeError):
    """Raised when something tries to overwrite a system-of-record value with web data.

    This is a programming error, not a data condition. Reaching it means a code
    path bypassed the conflict queue, which FR-WEB-03 and FR-HITL-02 forbid.
    """


def assert_no_autonomous_overwrite(
    existing: CanonicalField | None, incoming: CanonicalField
) -> None:
    """Guard the hard rule from TRS section 1.

    Web data may populate an empty field, but may never replace a value that
    came from an ingested contract or spec sheet. A disagreement between the two
    is queued for a human instead (FR-WEB-04).
    """
    if existing is None or existing.value is None:
        return
    if (
        existing.source_tier is SourceTier.SYSTEM_OF_RECORD
        and incoming.source_tier is SourceTier.WEB_SUPPLEMENT
    ):
        raise AutonomousOverwriteError(
            "web_supplement may not overwrite a system_of_record value; "
            "raise a conflict instead (FR-WEB-03, FR-HITL-02)"
        )


def values_conflict(
    a: ConflictCandidate, b: ConflictCandidate, *, numeric_tolerance: float
) -> bool:
    """Decide whether two candidate values for the same field actually disagree.

    FR-WEB-04 says a conflict is raised when values differ "beyond tolerance",
    but the TRS never defines tolerance, and the right rule is a procurement
    judgement rather than a technical default. See docs/open-questions.md.

    TODO(human): implement the comparison. Points worth deciding:
      - Numeric values: relative or absolute tolerance? A 2% relative band
        behaves very differently on 0.35 %/degC than on 650 Wp.
      - Values in different units: normalize first, or treat a unit mismatch as
        a UNIT_NORMALIZATION conflict in its own right?
      - Strings: exact match, case-folded, or fuzzy? Certification lists like
        "IEC 61215:2021" vs "IEC 61215" are the common real case.
      - A missing value on one side: not a conflict, or an open item?
    """
    raise NotImplementedError("see TODO(human) above")
