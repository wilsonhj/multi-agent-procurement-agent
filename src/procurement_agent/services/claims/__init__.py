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
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from ...schema import (
    CanonicalField,
    Condition,
    ConflictCandidate,
    ConflictStatus,
    SourceRef,
    SourceTier,
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

    def as_candidate(self) -> ConflictCandidate:
        """The queue's view of this claim (FR-HITL-03), condition included."""
        return ConflictCandidate(
            value=self.value,
            unit=self.unit,
            verbatim_value=self.verbatim_value,
            condition=self.condition,
            source_tier=self.source_tier,
            source_ref=self.source_ref,
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


def _identity(claim: FieldClaim) -> tuple[str, ...]:
    """A hashable, total rendering of a claim's content.

    `repr` rather than the object, because `FieldClaim.value` is typed
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
        repr(claim.value),
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
    rather than a defect. Only a difference in the **asserted value** - the value,
    its unit, or its verbatim text - is a genuine same-key contradiction.
    """
    ordered = sorted({_identity(c): c for c in claims}.values(), key=_identity)
    asserted: dict[tuple[object, ...], tuple[str, str, str]] = {}
    for claim in ordered:
        signature = (repr(claim.value), claim.unit or "", claim.verbatim_value or "")
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
    """
    answers = {repr(claim.value) for claim in group}
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
    """
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
                source_ref=chosen.source_ref,
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
    """
    projected = project(claims)
    if not projected:
        return []
    existing = {field.condition.grouping_key(): field for field in writer.current(field_name)}
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
