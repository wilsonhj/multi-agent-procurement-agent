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
import re
import unicodedata
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field

from ...schema import (
    CanonicalField,
    ConflictCandidate,
    ConflictClass,
    DeclaredBand,
    SourceTier,
    StandardsRegime,
    ToleranceCondition,
    ToleranceRule,
    render_value,
)
from .severity import assign_severity as assign_severity  # re-exported: the D-3 lookup
from .tolerance import FieldTolerance
from .tolerance import as_number as as_number  # re-exported: one numeric rule, not two
from .tolerance import tolerance_for as tolerance_for  # re-exported: the table's entry point


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

    Every optional element is `repr`'d rather than folded through `x or ""`, which
    was the same defect wearing different clothes: `None` and `""` are distinct
    candidate states, and mapping both onto the empty string tied two candidates
    that genuinely differ.

    `schema.field._normalise_token` establishes that the substitution is real -
    it exists partly to handle an extractor emitting `""` where `None` is meant -
    but it takes the **opposite** policy, collapsing `""` to `None` so an empty
    token cannot read as a stated dimension. That is right there and wrong here:
    normalising is a choice a vocabulary boundary gets to make, and this key is
    not a boundary. It has to order faithfully whatever the model actually holds,
    and two candidates that differ are two candidates. Nothing normalises a
    candidate's `unit` or `verbatim_value` on the way in, so preserving the
    distinction is the only way the order stays total.

    **The value goes through `render_value`, not `repr`.** Faithful is not the
    same as `repr`: a dict reprs in insertion order, so `{'ONAN': 30, 'ONAF': 40}`
    and `{'ONAF': 40, 'ONAN': 30}` - equal values, and the contract has three
    dict-valued parameters - sorted apart, and which candidate came out `left`
    in `comparison_pairs` changed with the order an extractor happened to read a
    cooling table's rows. That is A-50's class again: a hashed artifact moving
    with no data change. Ordering *between* two genuinely different values is
    unaffected, since the rendering is still total.
    """
    return (
        repr(candidate.condition.grouping_key()),
        render_value(candidate.value),
        repr(candidate.unit),
        candidate.source_tier.value,
        repr(candidate.source_ref.model_dump(mode="json")),
        repr(candidate.verbatim_value),
        repr(candidate.confidence),
        repr(candidate.condition.note),
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


class IncomparableCandidatesError(ValueError):
    """Raised when `values_conflict` is asked to compare a pair that is not a
    comparison at all - mismatched conditions, or a field D-2 marks never-compare.

    A programming error, not a data condition: candidates reach the comparison
    through `comparison_pairs`, which already applies the condition gate. Raising
    rather than returning "no conflict" on purpose - the two are indistinguishable
    to a caller, and "we did not compare these" silently rendered as "these agree"
    is the invisible false negative this module exists to prevent.
    """


class ConflictVerdict(BaseModel):
    """The outcome of comparing two candidates for one field."""

    model_config = ConfigDict(frozen=True)

    conflicts: bool
    conflict_class: ConflictClass | None = Field(
        default=None, description="Which of the five FR-HITL-01 classes; None when no conflict"
    )
    reason: str = Field(description="Why, in the terms FR-HITL-03 requires the queue to explain")


_EDITION = re.compile(r"\s*:\s*(\d{4})\s*$")


def _normalise_text(value: str) -> str:
    """Fold to a comparable form: NFKC, case, and internal whitespace.

    No fuzzy matching, deliberately. A fuzzy match that silently equates two
    certifications is unrecoverable; a false conflict is one extra queue item.
    """
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _split_edition(value: str) -> tuple[str, str | None]:
    """`IEC 61215:2021` -> `("iec 61215", "2021")`.

    The year is stripped so an edition difference is not read as a different
    standard, and *retained* so it becomes a TEMPORAL conflict rather than
    disappearing. Dropping it would silently equate a 2016 certification with a
    2021 one, which is a compliance claim nobody made.
    """
    text = _normalise_text(value)
    match = _EDITION.search(text)
    if match is None:
        return text, None
    return _EDITION.sub("", text), match.group(1)


def _places(text: str) -> int:
    try:
        exponent = Decimal(text).as_tuple().exponent
    except InvalidOperation:
        return 0
    return max(0, -exponent) if isinstance(exponent, int) else 0


#: The two ways a run of digits and commas can be read, because a comma is
#: genuinely ambiguous and neither reading is right on its own.
#:
#: Grouped treats `,\d{3}` as a thousands separator, which bare digit runs get
#: wrong: they split `125,000.50` into `125` and `000.50`, so no token equals the
#: parsed value and the scan falls through to `repr(float)` and its lost trailing
#: zero. Ungrouped stops at every comma, which the grouped reading gets wrong in
#: the other direction: two table cells that lost their separating whitespace
#: render as `650,700.20`, and reading that as one number loses the 700.20 that is
#: actually there.
#:
#: Both are tried. A token only counts when it equals the parsed value, so the
#: extra readings cannot invent a match - `_decimals` is choosing between
#: interpretations of the same text, not trusting either one.
_NUMBER_TOKENS = (
    re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][+-]?\d+)?"),
    re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"),
)


def _decimals(candidate: ConflictCandidate) -> int:
    """Printed decimal places — D-2's `decimals_a` / `decimals_b`.

    `verbatim_value` is the source text, so where it carries a number it is the
    authority and the parsed value is only a fallback. Taking the *maximum* over
    both instead looks conservative and is not: `float(22)` reprs as `22.0`, so
    every integer-printed value would claim one decimal it never had, and a sheet
    printing `22` would be held to a precision it cannot express.

    **The verbatim number has to be the value.** Reading the first numeric token
    unconditionally meant a leading qualifier decided the precision of the whole
    comparison - `"@ 25 degC: 22.35 %"` reported zero places, widening the floor
    to 0.5 and absorbing a 0.45 pp disagreement that is 4.5x the D-2 band. A
    thousands separator did it too, since the regex stopped at the comma. Fewer
    decimals means a *wider* floor, so this direction hides conflicts, and it
    turns on the extractor's formatting rather than on the data. Every candidate
    number in the text is tried, and one that does not equal `value` is not the
    value.

    Trying every token fixed the qualifier but not the separator, and the two
    failures are not the same shape: a leading qualifier offers a *wrong* token,
    while `125,000.50` offers *no* token equal to the value, so the scan found
    nothing and fell back to `repr(float)` - which drops the printed trailing
    zero and reports one decimal place where the source printed two. Under EXACT
    there is no magnitude to mask it, and EXACT is the default rule for every
    contract key D-2's table does not cover.

    A comma cannot be resolved by picking one reading, so `_NUMBER_TOKENS` holds
    both and every match from either is tried. Requiring the token to equal the
    parsed value is what makes that safe.

    An `int` and a `Decimal` report their own precision rather than going through
    `float`: `Decimal("650")` is the natural representation of exactly the
    catalog values D-2 calls EXACT, and `repr(float(...))` would give it a
    decimal place it never had - the `650` vs `650.0` case D-2 names.
    """
    number = as_number(candidate.value)
    if candidate.verbatim_value is not None and number is not None:
        printed: int | None = None
        for pattern in _NUMBER_TOKENS:
            for found in pattern.finditer(candidate.verbatim_value):
                text = found.group().replace(",", "")
                try:
                    matches = float(text) == number
                except ValueError:  # pragma: no cover - the regex only matches numerals
                    continue
                if not matches:
                    continue
                # The most precise reading wins. Under-reporting is the direction
                # that widens the floor and hides conflicts, and if any reading of
                # this text prints n decimals then the source did print them.
                places = _places(text)
                printed = places if printed is None else max(printed, places)
        if printed is not None:
            return printed
    value = candidate.value
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return 0
    if isinstance(value, Decimal):
        return _places(str(value))
    return 0 if number is None else _places(repr(number))


def _rounding_floor(a: ConflictCandidate, b: ConflictCandidate) -> float:
    """D-2: `1/2 x 10^(-min(decimals_a, decimals_b))`.

    Two values are never in conflict by less than the precision the coarser
    source printed. Without it `650` and `650.4` would disagree under a 0.1 pp
    band that the coarser sheet could not have expressed.
    """
    return 0.5 * 10.0 ** (-min(_decimals(a), _decimals(b)))


def _classify(a: ConflictCandidate, b: ConflictCandidate) -> ConflictClass:
    """Which of the five FR-HITL-01 classes a disagreement belongs to.

    Derived from the candidates rather than passed in, so the class cannot drift
    from the evidence it describes.
    """
    if a.source_tier is not b.source_tier:
        return ConflictClass.RECORD_VS_WEB
    a_doc = a.source_ref.document_id or a.source_ref.url
    b_doc = b.source_ref.document_id or b.source_ref.url
    if a_doc == b_doc:
        return ConflictClass.INTRA_DOCUMENT
    return ConflictClass.INTER_DOCUMENT


def values_conflict(
    a: ConflictCandidate,
    b: ConflictCandidate,
    *,
    tolerance: FieldTolerance,
    band_a: DeclaredBand | None = None,
    band_b: DeclaredBand | None = None,
) -> ConflictVerdict:
    """Whether two candidate values for one field actually disagree (FR-WEB-04).

    The TRS says "beyond tolerance" and never defines tolerance; clarifications
    D-2 does, per field and in four kinds, and `tolerance` is a row of that table
    (`tolerance_for(field_name)`). There is no global default parameter here on
    purpose - a single float was the defect D-2 exists to remove, and leaving one
    in the signature would let it come back as a call-site default.

    `band_a`/`band_b` carry the *declared* bands for a DECLARED_BAND field. They
    are parameters rather than attributes of the candidate because the band lives
    on a different canonical field (`power_tolerance`) than the value it
    qualifies (`nameplate_power_w`); only a caller holding the whole component
    can pair them.

    Answers the four questions the stub left open:

    - **Relative or absolute?** Both, per field, plus one-sided and two rules
      that are not thresholds at all. See `ToleranceRule`.
    - **Different units?** Never resolved by tolerance. A unit mismatch is a
      `UNIT_NORMALIZATION` conflict in its own right - normalising here would
      hide an extraction defect behind a successful comparison.
    - **Strings?** Normalise, then exact-match, with the edition year split off
      and kept so `IEC 61215:2021` vs `IEC 61215:2016` is TEMPORAL rather than a
      string mismatch, and `IEC 61215:2021` vs `IEC 61215` is not a conflict.
      No fuzzy matching.
    - **Missing on one side?** Not a conflict - a gap. It flags MISSING_DATA and
      triggers the FR-WEB-01 search; `RECORD_VS_WEB` needs both sides to hold a
      value.
    """
    if tolerance.rule is ToleranceRule.NEVER_COMPARE:
        raise IncomparableCandidatesError(
            "this field names two different physical quantities; comparing them is "
            "not a wide tolerance, it is not a comparison (D-2)"
        )
    if not a.condition.comparable_with(b.condition):
        raise IncomparableCandidatesError(
            f"conditions do not match ({a.condition.grouping_key()} vs "
            f"{b.condition.grouping_key()}); a mismatch is not a conflict, it is "
            "not a comparison (D-1). Use comparison_pairs to select candidates."
        )

    if a.value is None or b.value is None:
        return ConflictVerdict(
            conflicts=False,
            reason="one side has no value; a gap flags MISSING_DATA and triggers the "
            "FR-WEB-01 search rather than raising a conflict",
        )

    if (
        a.unit is not None
        and b.unit is not None
        and _normalise_text(a.unit) != _normalise_text(b.unit)
    ):
        return ConflictVerdict(
            conflicts=True,
            conflict_class=ConflictClass.UNIT_NORMALIZATION,
            reason=f"units differ ({a.unit!r} vs {b.unit!r}); a unit mismatch is never "
            "resolved by tolerance (FR-ING-08)",
        )

    number_a, number_b = as_number(a.value), as_number(b.value)
    if number_a is None or number_b is None:
        if isinstance(a.value, str) and isinstance(b.value, str):
            return _compare_text(a, b)
        if number_a is None and number_b is None and a.value == b.value:
            return ConflictVerdict(conflicts=False, reason="values are equal")
        return ConflictVerdict(
            conflicts=True,
            conflict_class=_classify(a, b),
            reason=f"values are not comparable as numbers or text ({a.value!r} vs {b.value!r})",
        )

    return _compare_numbers(a, b, number_a, number_b, tolerance, band_a, band_b)


def _compare_text(a: ConflictCandidate, b: ConflictCandidate) -> ConflictVerdict:
    assert isinstance(a.value, str) and isinstance(b.value, str)
    base_a, year_a = _split_edition(a.value)
    base_b, year_b = _split_edition(b.value)
    if base_a != base_b:
        return ConflictVerdict(
            conflicts=True,
            conflict_class=_classify(a, b),
            reason=f"text differs after normalisation ({base_a!r} vs {base_b!r}); "
            "no fuzzy matching - a silently equated certification is unrecoverable",
        )
    if year_a is not None and year_b is not None and year_a != year_b:
        return ConflictVerdict(
            conflicts=True,
            conflict_class=ConflictClass.TEMPORAL,
            reason=f"same standard, different edition ({year_a} vs {year_b}); an edition "
            "difference is a temporal conflict, not a string mismatch",
        )
    return ConflictVerdict(conflicts=False, reason="text matches after normalisation")


def _compare_numbers(
    a: ConflictCandidate,
    b: ConflictCandidate,
    number_a: float,
    number_b: float,
    tolerance: FieldTolerance,
    band_a: DeclaredBand | None,
    band_b: DeclaredBand | None,
) -> ConflictVerdict:
    conflict_class = _classify(a, b)
    floor = _rounding_floor(a, b)

    if tolerance.rule is ToleranceRule.DECLARED_BAND:
        if band_a is None and band_b is None:
            return ConflictVerdict(
                conflicts=abs(number_a - number_b) > floor,
                conflict_class=conflict_class if abs(number_a - number_b) > floor else None,
                reason="declared-band field with no band on either side; compared at "
                "printed precision only",
            )
        reference = band_a if band_a is not None else band_b
        assert reference is not None
        agrees = (
            band_a.agrees(number_a, band_b, number_b)
            if band_a is not None
            else reference.agrees(number_b, band_a, number_a)
        )
        return ConflictVerdict(
            conflicts=not agrees,
            conflict_class=None if agrees else conflict_class,
            reason="guaranteed ranges "
            + ("intersect" if agrees else "are disjoint")
            + "; a printed band supersedes the config default for this field",
        )

    if tolerance.rule is ToleranceRule.ONE_SIDED:
        return _compare_one_sided(a, b, number_a, number_b, tolerance, conflict_class, floor)

    magnitude = _effective_magnitude(tolerance, a, b, number_a, number_b)
    if tolerance.rule is ToleranceRule.RELATIVE:
        # Referred to the larger magnitude, so the test does not depend on which
        # candidate is named first. Against the smaller it is asymmetric, and an
        # asymmetric predicate would make the queue depend on argument order -
        # the same defect `_ordering_key` exists to keep out.
        magnitude *= max(abs(number_a), abs(number_b))
    band = max(magnitude, floor)
    difference = abs(number_a - number_b)
    conflicts = difference > band
    return ConflictVerdict(
        conflicts=conflicts,
        conflict_class=conflict_class if conflicts else None,
        reason=f"|{number_a} - {number_b}| = {difference:g} vs band {band:g} "
        f"(max of {tolerance.rule.value} {magnitude:g} and rounding floor {floor:g})",
    )


def _effective_magnitude(
    tolerance: FieldTolerance,
    a: ConflictCandidate,
    b: ConflictCandidate,
    number_a: float,
    number_b: float,
) -> float:
    """The band D-2 gives *for this pair*, not just for this field.

    Four D-2 rows state two bands rather than one, and encoding only the first is
    silent: the comparison then applies a band that is right half the time with
    nothing marking which half. IEC's impedance tolerance widens from 7.5% to 10%
    below Z=10%, and a transformer's total-loss allowance is 6% under IEEE where
    it is 10% under IEC - a wrong branch is a real conflict suppressed or a false
    one raised, either way invisibly.

    Each discriminator is read from data the candidates already carry, so nothing
    has to be threaded in: the compared magnitude, `Condition.standards_regime`
    (which D-6 already makes load-bearing), and `SourceRef.source_authority`.
    """
    magnitude = tolerance.magnitude or 0.0
    if tolerance.alternate_when is None or tolerance.alternate_magnitude is None:
        return magnitude

    if tolerance.alternate_when is ToleranceCondition.IMPEDANCE_BELOW_10_PCT:
        selected = max(abs(number_a), abs(number_b)) < 10.0
    elif tolerance.alternate_when is ToleranceCondition.REGIME_IEEE:
        selected = StandardsRegime.IEEE in {
            a.condition.standards_regime,
            b.condition.standards_regime,
        }
    else:  # AGAINST_CEC_LIST
        selected = any(
            candidate.source_ref.source_authority is not None
            and "cec" in candidate.source_ref.source_authority.casefold()
            for candidate in (a, b)
        )
    return tolerance.alternate_magnitude if selected else magnitude


def _compare_one_sided(
    a: ConflictCandidate,
    b: ConflictCandidate,
    number_a: float,
    number_b: float,
    tolerance: FieldTolerance,
    conflict_class: ConflictClass,
    floor: float,
) -> ConflictVerdict:
    """`conflict <=> (measured - declared) > tolerance` (D-2).

    Both IEC and IEEE state loss and no-load-current limits in one direction
    only, and IEC 60076-1 Table 1 notes that an omitted direction is
    unrestricted: being *under* guarantee is never a nonconformity, so a test
    report below a contract value is not a disagreement.

    Which side is the declared one comes from the source tier - a contract or
    spec sheet is the guarantee, web data is the report against it.

    **The allowance does not apply declared-against-declared.** IEC's +15% is how
    far a *measured* loss may exceed a *guaranteed* one; it says nothing about two
    documents disagreeing on what was guaranteed. Two datasheets stating 100 kW
    and 109 kW of no-load loss are two declarations, and a 9% gap between them is
    an inter-document conflict a reviewer has to see - applying the measurement
    allowance symmetrically silently absorbed it. So when neither side is
    identifiable as the measurement, the comparison falls back to printed
    precision, which is what docs/defaults.md said the rule should be all along.
    """
    if a.source_tier is b.source_tier:
        difference = abs(number_a - number_b)
        conflicts = difference > floor
        return ConflictVerdict(
            conflicts=conflicts,
            conflict_class=conflict_class if conflicts else None,
            reason=f"both candidates are {a.source_tier.value}, so neither is the "
            f"measurement; the one-sided allowance does not apply between two "
            f"declarations and |{number_a} - {number_b}| = {difference:g} is compared "
            f"at printed precision {floor:g}",
        )
    declared, measured = (
        (number_a, number_b)
        if a.source_tier is SourceTier.SYSTEM_OF_RECORD
        else (number_b, number_a)
    )
    band = max(_effective_magnitude(tolerance, a, b, number_a, number_b) * abs(declared), floor)
    excess = measured - declared
    conflicts = excess > band
    return ConflictVerdict(
        conflicts=conflicts,
        conflict_class=conflict_class if conflicts else None,
        reason=f"declared {declared:g}, measured {measured:g}, excess {excess:g} vs "
        f"one-sided limit {band:g}; under guarantee is never a nonconformity",
    )
