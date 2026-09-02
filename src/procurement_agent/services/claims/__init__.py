"""Workers propose, they do not commit — contract C8, issue #8.

`assert_no_autonomous_overwrite` is a *value* property: a pure predicate over two
fields. It takes no store handle, performs no write, and **cannot enforce that it
is called**. With one serial writer that suffices. Under fan-out it is an honour
system every branch must remember, and it fails three further ways the guard
cannot see: it permits record-over-record (a lost update under concurrency), it
has no notion of ordering (two workers finishing in different orders give
different last-writer-wins outcomes, so the *store* becomes order-dependent and
FR-OUT-06 fails below composition), and nothing stops a branch skipping it.

C8's answer is structural: **there is no overwrite to guard.** Each extraction
appends an immutable `FieldClaim`, and the canonical values are a *projection*
over claims rather than an in-place update.

**Contract C2: a claim carries its `condition`.** The first version of this
module omitted it, and the cost was measured on D-1's own worked example — the
Sungrow SG350HX's `352 kVA @30 degC / 320 @40 degC / 295 @50 degC`. Every
candidate came out `is_unstated()`, so `comparison_pairs` returned **3 pairs**
where D-1 says zero, and `canonical_claims` raised on the trio because the key
could not tell three conditions apart from three contradictions. A claim record
without `condition` defeats the condition gate on the only path that reaches it.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal, InvalidOperation
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from ...schema import (
    CanonicalField,
    Condition,
    ConflictCandidate,
    ConflictStatus,
    SourceRef,
    SourceTier,
    render_value,
)
from ..conflict_hitl import assert_no_autonomous_overwrite


class FieldClaim(BaseModel):
    """One extractor's assertion about one field of one document, under one
    condition.

    Immutable and never revised: a second look produces a *new* claim under a new
    `extractor_version`, so what was believed when is preserved. That is what
    makes the store append-only, and what makes re-extraction safe to run
    concurrently with anything else.
    """

    model_config = ConfigDict(frozen=True)

    document_id: str
    field_name: str = Field(description="The frozen contract's `key` for this parameter")
    extractor_version: str = Field(
        description=(
            "Identifies the code and prompt that produced the claim. Part of the "
            "key, so re-extraction appends rather than overwrites and a regression "
            "stays visible next to the value that replaced it."
        )
    )
    condition: Condition = Field(
        default_factory=Condition,
        description=(
            "The conditions this value holds under (D-1, contract C2). Part of the "
            "key: one datasheet stating a parameter at three ambients is three "
            "claims, not one extractor contradicting itself."
        ),
    )

    value: object | None
    unit: str | None = None
    verbatim_value: str | None = None
    source_tier: SourceTier
    source_ref: SourceRef
    confidence: float = Field(ge=0.0, le=1.0)

    def claim_key(self) -> tuple[object, ...]:
        """The uniqueness key. Two claims sharing it are the same assertion.

        `condition.grouping_key()` is in it because without it the Sungrow trio -
        one document, one field, one extractor version, three ambients - is
        indistinguishable from an extractor emitting three answers for one field.
        """
        return (
            self.document_id,
            self.field_name,
            self.extractor_version,
            self.condition.grouping_key(),
        )

    def provenance(self) -> SourceRef:
        """This claim's `source_ref` with contract C3's fourth element stamped on.

        C3 is `(document_id, page, span, extractor_version)`, where `span` is
        spelled `section` on `SourceRef`. The first three already lived there
        under those names; the fourth lived only on the claim, so the
        projection dropped it and a stored value could not be traced back to the
        code that produced it. Stamping rather than requiring callers to set it
        twice keeps the claim's own `extractor_version` the single authority.
        """
        return self.source_ref.model_copy(update={"extractor_version": self.extractor_version})

    def as_candidate(self) -> ConflictCandidate:
        """The queue's view of this claim (FR-HITL-03), condition included."""
        return ConflictCandidate(
            value=self.value,
            unit=self.unit,
            verbatim_value=self.verbatim_value,
            condition=self.condition,
            source_tier=self.source_tier,
            source_ref=self.provenance(),
            confidence=self.confidence,
        )


@runtime_checkable
class ClaimWriter(Protocol):
    """The only handle that can put canonical values in the store.

    Deliberately not passed to anything a worker calls.
    """

    def commit(self, field_name: str, values: Sequence[CanonicalField]) -> None: ...

    def current(self, field_name: str) -> Sequence[CanonicalField]: ...


class ProposalError(RuntimeError):
    """Raised when a claim set cannot be projected to canonical values."""


class StoredValueLossError(ProposalError):
    """Raised when committing a projection would delete a value already stored.

    A subclass rather than a separate hierarchy, because it is the same
    programming error as the rest: the reducer was handed something other than
    the complete claim set for the field.
    """


def _numeric_answer(value: object) -> str | None:
    """One rendering for every spelling of the same number, or None.

    `650`, `650.0` and `Decimal("650")` are one answer about the world in three
    Python types, and `repr` gives three strings. That split reached two places
    at once: `_status_for` reported OPEN for a pair `values_conflict` calls no
    conflict at all (`test_nameplate_absorbs_650_versus_650_point_0_and_nothing_more`
    pins the tolerance side), and `canonical_claims` raised `ProposalError` and
    lost the whole field when one extractor read `650` from a table cell and
    `650.0` from parsed text under the same claim key.

    **This is not the encoder D-14 asks to be injective.** That one hashes the
    artifact of record and must keep the three apart, because `_decimals` reads
    precision from the printed value and that precision sets D-2's rounding
    floor. Here the question is only "did these two claims say the same thing",
    and the rounding floor is computed downstream from `verbatim_value`, which
    this signature deliberately excludes. Agreeing with `values_conflict` is the
    requirement; injectivity is the other function's.

    `bool` is excluded for the reason `as_number` excludes it: `True` is an
    `int`, and a `True` that read as `1` would agree with a 1.0 claim.
    """
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:  # pragma: no cover - str() of a real number parses
        return None
    if not number.is_finite():
        return None
    # `normalize()` folds the trailing zero `:f` would keep, so `650.0` and `650`
    # render alike; `:f` then keeps the result out of exponent form, so a
    # normalize() that returns `6.5E+2` does not reintroduce a second spelling.
    return f"num:{number.normalize():f}"


def _asserted(claim: FieldClaim) -> tuple[str, str]:
    """What the claim actually *says*: a value, in a unit.

    The unit belongs here because `650 W` and `650 kW` are two different answers.
    `values_conflict` classes exactly that as a `UNIT_NORMALIZATION` conflict
    which "is never resolved by tolerance (FR-ING-08)", so a projection that
    compared values alone reported two claims a unit apart as agreement and then
    stored one of the two units.

    `verbatim_value` is deliberately **not** part of it. It is the source text at
    a location, which is provenance in exactly the way `source_ref.page` is: a
    datasheet printing `650 W` in a summary table and `650` in the electrical
    table has stated one figure twice, not contradicted itself.

    Numbers go through `_numeric_answer` so that one figure in three Python
    types is one answer; everything else through `render_value`, so a dict's
    insertion order is not an answer either.
    """
    return (_numeric_answer(claim.value) or render_value(claim.value), claim.unit or "")


def _identity(claim: FieldClaim) -> tuple[str, ...]:
    """A hashable, total rendering of a claim's content.

    Rendered rather than the object itself, because `FieldClaim.value` is typed
    `object | None` and the contract has at least nine list- and dict-valued
    parameters - `certifications`, `ul_listing`, `standards`,
    `rating_mva_by_cooling`, `ercot_compliance_items`. An earlier version used
    `set(claims)` and raised `TypeError: unhashable type: 'list'` on
    `certifications`, which this module's own tier table calls Tier A. The
    projection crashed on the fields it classifies as most critical.
    """
    return (
        claim.document_id,
        claim.field_name,
        claim.extractor_version,
        repr(claim.condition.grouping_key()),
        render_value(claim.value),
        claim.unit or "",
        claim.verbatim_value or "",
        claim.source_tier.value,
        repr(claim.source_ref.model_dump(mode="json")),
        repr(claim.confidence),
    )


def canonical_claims(claims: Iterable[FieldClaim]) -> list[FieldClaim]:
    """Claims in canonical order, with exact duplicates collapsed.

    Two workers producing byte-identical claims is one assertion twice - what an
    idempotency key is for. Two claims sharing a `claim_key` and differing *only*
    in provenance or confidence are also one assertion: a datasheet printing the
    same figure in a summary table and again in the electrical-characteristics
    table yields two claims differing in `source_ref.page`, and that is normal
    rather than a defect. Only a difference in the **asserted value** - see
    `_asserted`: the value and the unit it is in - is a genuine same-key
    contradiction.
    """
    ordered = sorted({_identity(c): c for c in claims}.values(), key=_identity)
    asserted: dict[tuple[object, ...], tuple[str, str]] = {}
    for claim in ordered:
        signature = _asserted(claim)
        previous = asserted.get(claim.claim_key())
        if previous is not None and previous != signature:
            raise ProposalError(
                f"two different values share the claim key {claim.claim_key()}: "
                f"{previous} vs {signature}. One extractor version produced two "
                "answers for one field under one condition."
            )
        asserted[claim.claim_key()] = signature
    return ordered


def _status_for(group: Sequence[FieldClaim]) -> ConflictStatus:
    """Whether a set of like-for-like claims disagrees.

    Computed over **every** claim, not over the winning tier. Restricting it to
    the system-of-record subset meant a web value contradicting the record came
    back `NONE` - the projection arbitrated in one direction and then reported no
    conflict, which is exactly what FR-WEB-04 says must be queued for a human.

    A claim with no value counts as a distinct answer rather than being filtered
    out. "Extractor A found nothing, extractor B found 650 W" is the commonest
    real disagreement in this domain, and dropping the `None` first made it
    invisible.

    Over `_asserted`, the same signature `canonical_claims` uses. Comparing
    `repr(value)` alone read `650 W` and `650 kW` as one answer and stored the
    pair as agreement, which is the unit conflict FR-ING-08 says tolerance may
    never absorb.
    """
    answers = {_asserted(claim) for claim in group}
    return ConflictStatus.OPEN if len(answers) > 1 else ConflictStatus.NONE


def _preferred(group: Sequence[FieldClaim]) -> FieldClaim:
    """Which claim supplies the canonical value for a condition group.

    The source-of-record rule first (TRS section 1), then *a stated value beats a
    missing one*, then confidence, then the canonical order as a last resort. The
    first version took `winners[0]` straight from an order led by `document_id`,
    which meant a populated value lost to a `None` from an alphabetically earlier
    filename - and renaming a file changed the canonical answer.

    This does not arbitrate a genuine disagreement: `_status_for` has already
    marked the group OPEN, so a human still decides. It only picks what to show
    beside the conflict.
    """
    return sorted(
        group,
        key=lambda c: (
            c.source_tier is not SourceTier.SYSTEM_OF_RECORD,
            c.value is None,
            -c.confidence,
            _identity(c),
        ),
    )[0]


def project(claims: Sequence[FieldClaim]) -> list[CanonicalField]:
    """The canonical values implied by a set of claims. A pure function.

    Returns **one `CanonicalField` per condition group**, matching
    `ComponentInstance.fields` being list-valued: the Sungrow trio is three
    stored values, not one value and two discarded.

    No store handle, no write, no clock - given the same claims it returns the
    same list, which is the half of FR-OUT-06 that lives below composition.

    Claims are grouped by `condition.grouping_key()`, which is the display
    partition and *not* the comparison relation. Deciding which stored values
    disagree is `comparison_pairs`' job; this only decides what is stored.

    **One field per call, and it is checked.** The grouping key is the condition
    and nothing else, so claims about two different parameters with the same
    condition - and the commonest condition by far is the empty one - landed in
    one group: one of the two values was discarded and the survivor came back
    OPEN, reporting a conflict between a nameplate and an efficiency. That is not
    a comparison, and it was silent.
    """
    fields = sorted({claim.field_name for claim in claims})
    if len(fields) > 1:
        raise ProposalError(
            f"a projection covers one field, not {fields}. Claims are grouped by "
            "condition alone, so mixing fields silently discards values and "
            "reports a conflict between two different parameters."
        )
    ordered = canonical_claims(claims)
    if not ordered:
        return []

    groups: dict[object, list[FieldClaim]] = {}
    for claim in ordered:
        groups.setdefault(claim.condition.grouping_key(), []).append(claim)

    projected: list[CanonicalField] = []
    for key in sorted(groups, key=repr):
        group = groups[key]
        chosen = _preferred(group)
        projected.append(
            CanonicalField(
                value=chosen.value,
                unit=chosen.unit,
                verbatim_value=chosen.verbatim_value,
                condition=chosen.condition,
                source_tier=chosen.source_tier,
                source_ref=chosen.provenance(),
                confidence=chosen.confidence,
                conflict_status=_status_for(group),
            )
        )
    return projected


def commit_claims(
    field_name: str,
    claims: Sequence[FieldClaim],
    *,
    writer: ClaimWriter,
) -> list[CanonicalField]:
    """The single serial reducer. The only path from a claim to a stored value.

    Calls `assert_no_autonomous_overwrite` once at a chokepoint rather than N
    times by convention. With append-only claims there is usually nothing to
    catch - that is the point - but it stays because the projection can still be
    asked to replace a stored system-of-record value with a web-only one when the
    record claim is dropped from a later run.

    **The claim set has to be complete, and both halves of that are checked.**
    `commit` replaces the whole field, so a projection is a statement about every
    condition group and not only the ones it mentions:

    - A claim naming another field would be stored under this one, so the store
      would hold a percentage labelled as watts.
    - A stored group the projection does not cover is *deleted* by the commit,
      and the guard could not see it: keyed on the condition group, it only ever
      compared groups present in both. A web claim under a new condition
      therefore removed a system-of-record value under the old one - the
      autonomous overwrite FR-WEB-03 and FR-HITL-02 forbid, reached by changing
      the condition instead of the value.

    Raised rather than merged. Claims are append-only and `project` is a pure
    function of them, so a group can only vanish because the caller passed a
    subset; folding the leftovers back in would hide that and make the store a
    function of commit history rather than of the claims.
    """
    foreign = sorted({claim.field_name for claim in claims} - {field_name})
    if foreign:
        raise ProposalError(
            f"claims about {foreign} cannot be committed under {field_name!r}; "
            "the field name is the store key."
        )
    projected = project(claims)
    if not projected:
        return []
    existing = {field.condition.grouping_key(): field for field in writer.current(field_name)}
    covered = {field.condition.grouping_key() for field in projected}
    dropped = sorted((key for key in existing if key not in covered), key=repr)
    if dropped:
        raise StoredValueLossError(
            f"committing this projection would drop {len(dropped)} stored condition "
            f"group(s) of {field_name!r}: {dropped}. The reducer takes the complete "
            "claim set for a field, because `commit` replaces it."
        )
    for field in projected:
        assert_no_autonomous_overwrite(existing.get(field.condition.grouping_key()), field)
    writer.commit(field_name, projected)
    return projected


#: Parameter names that denote a store write handle.
#:
#: Substring matching was the first attempt and it failed both ways: `restore`
#: matched on `store`, while `storage`, `db`, `repo`, `sink`, `session` and
#: `history` did not. Exact names plus the annotation check is narrower and
#: honest about what it can see.
WRITE_HANDLE_NAMES: frozenset[str] = frozenset({"writer", "store", "storage", "claim_writer"})


def takes_a_write_handle(func: Callable[..., object]) -> bool:
    """Whether `func` can reach the store *through its signature*.

    **This is a lint, not a proof, and the difference matters.** A worker can
    still hold a writer as a module global, a closure cell or `self.writer`, and
    no signature check sees any of those. The unreachability property C8 actually
    wants is architectural - workers live in a package that cannot import the
    store - and this catches only the commonest way to break it. Claiming more
    for it than that would be the honour system with extra steps.
    """
    try:
        parameters = inspect.signature(func).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins have no signature
        return False
    return any(
        name in WRITE_HANDLE_NAMES or "ClaimWriter" in str(parameter.annotation)
        for name, parameter in parameters.items()
    )
