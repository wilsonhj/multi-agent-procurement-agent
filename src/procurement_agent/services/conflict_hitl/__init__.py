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

from ...schema import CanonicalField, ConflictCandidate, SourceTier


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
