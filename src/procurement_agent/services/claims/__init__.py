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
    ComponentCategory,
    Condition,
    ConflictCandidate,
    ConflictStatus,
    SourceRef,
    SourceTier,
)
from ...schema.registry import OffContractFieldError, require_contract_key
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


def _render(value: object, _containers: tuple[int, ...] = ()) -> str:
    """A textual rendering of a claim value that respects equality.

    `repr` does not, and that is not a nicety: a dict reprs in *insertion* order,
    so two extractions that read one cooling table's rows in different orders
    give values that are `==` and reprs that are not. The contract has three
    dict-valued parameters - `rating_mva_by_cooling`, `harmonic_spectrum`,
    `ercot_compliance_items` - and under `repr` such a pair counted as a
    disagreement: an OPEN conflict between two identical values, or a
    `ProposalError` losing the whole field when the two shared a claim key.

    Containers are walked rather than repr'd whole, so the canonicalisation
    reaches a nested dict. The cycle guard is not tidiness: `repr` already
    handles a self-referential value, and a hand-rolled walk that did not would
    trade a false conflict for a `RecursionError`.
    """
    if id(value) in _containers:
        return "..."
    nested = (*_containers, id(value))
    if isinstance(value, dict):
        entries = sorted((_render(k, nested), _render(v, nested)) for k, v in value.items())
        return "{" + ", ".join(f"{key}: {item}" for key, item in entries) + "}"
    if isinstance(value, list | tuple):
        return f"{type(value).__name__}[" + ", ".join(_render(v, nested) for v in value) + "]"
    if isinstance(value, set | frozenset):
        return (
            f"{type(value).__name__}[" + ", ".join(sorted(_render(v, nested) for v in value)) + "]"
        )
    return repr(value)


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
    """
    return (_render(claim.value), claim.unit or "")


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
        _render(claim.value),
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
    category: ComponentCategory | None = None,
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

    **`field_name` has to be a contract key**, and that is checked first - before
    the foreign-field check, before the projection, and before the empty-claim-set
    early return. Order is load-bearing: an invented key arriving with no claims
    is exactly what a broken extractor produces, and a check placed after the
    early return would wave it through. Contract C2, and the reason it is a
    boundary rather than a lint is that claims are append-only: there is no
    correcting a row once it is written under a key nothing looks up.

    `category` is optional because the store is keyed on the field name alone and
    a caller reducing one field does not always have a `ComponentInstance` in
    hand. Passing it is strictly stronger and should be preferred: without it the
    check is membership in the union of all keys, which admits `chemistry` for an
    inverter. The other enforcement point (`ComponentInstance.fields`) always has
    the category and always uses it, so the weaker form here is a narrower window
    rather than an open one.
    """
    try:
        require_contract_key(field_name, category)
    except OffContractFieldError as exc:
        raise ProposalError(str(exc)) from exc
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
