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

from collections.abc import Sequence

from ...schema import CanonicalField, ConflictCandidate, SourceTier


def comparison_groups(candidates: Sequence[ConflictCandidate]) -> list[list[ConflictCandidate]]:
    """Partition candidates into sets that may be compared like for like.

    Two rules, and the second is what makes this correct rather than merely
    deterministic.

    **Partition by `Condition.grouping_key()`, never by `comparable_with`.** That
    predicate is not transitive - `@30 degC` and `@40 degC` are each comparable
    with an unstated condition but not with each other - so first-fit bucketing
    over it yields different groups depending on arrival order, and therefore a
    different conflict queue from an unchanged store. FR-OUT-06 forbids that.

    **Fold wholly-unstated candidates into every stated group.** Grouping on the
    key alone is strictly comparison-losing: a supply agreement stating `650 W`
    with no test condition would strand in its own group while the datasheet and
    the CEC listing, both marked STC, compare only with each other. The
    system-of-record value - the one FR-HITL-02 exists to protect - would be
    compared against nothing, no queue entry would be raised, and the compose gate
    would never fire. That trades a *visible* false positive for an *invisible*
    false negative, which is the worse failure for a tool whose premise is that a
    human decides.

    Folding stays order-independent because the unstated group is identified
    canonically - by its all-`None` key - rather than by which candidate happened
    to arrive first. Groups are returned in sorted key order for the same reason.

    A candidate may therefore appear in more than one group: that is deliberate,
    since an unqualified value is a legitimate counterpart to several stated ones.
    """
    grouped: dict[tuple[object, ...], list[ConflictCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.condition.grouping_key(), []).append(candidate)

    unstated_key = tuple(None for _ in range(len(next(iter(grouped), ()))))
    unstated = grouped.pop(unstated_key, []) if grouped else []

    if not grouped:
        return [unstated] if unstated else []

    return [grouped[key] + unstated for key in sorted(grouped, key=repr)]


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
