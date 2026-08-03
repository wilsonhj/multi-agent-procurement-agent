"""The canonical field object.

TRS section 5 specifies this exactly:

    Each field is an object:
    { value, unit, verbatim_value, source_tier, source_ref, confidence,
      conflict_status, resolution }

Those eight keys are reproduced verbatim. The canonical store built from them is
the single source for Excel regeneration and the audit trail, so FR-OUT-06's
determinism requirement rests on this type being stable.
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime
from enum import StrEnum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from .enums import (
    ComponentCategory,
    ConflictClass,
    ConflictStatus,
    EfficiencyWeighting,
    MeasurementBasis,
    PowerSide,
    ResolutionAction,
    RteBoundary,
    Severity,
    SourceTier,
    StandardsRegime,
    ToleranceKind,
)


class SourceRef(BaseModel):
    """Where a value came from. NFR-01 permits no unsourced values.

    A document reference carries doc_id plus page and table/section (FR-ING-07).
    A web reference carries url, page_title and retrieved_at (FR-WEB-02).
    """

    model_config = ConfigDict(frozen=True)

    document_id: str | None = None
    page: int | None = None
    section: str | None = Field(default=None, description="Table or section locator")
    extractor_version: str | None = Field(
        default=None,
        description=(
            "The code and prompt that produced the value. Contract C3 is "
            "`(document_id, page, span, extractor_version)` and this was the "
            "missing quarter: `FieldClaim` carried it, and the projection to a "
            "`CanonicalField` dropped it, so a stored value could not be traced "
            "to the extractor that produced it. A regression is then invisible "
            "in the store even though the claim recording it is still there."
        ),
    )
    bounding_box: tuple[float, float, float, float] | None = Field(
        default=None, description="OCR bbox retained per FR-ING-04"
    )

    url: str | None = None
    page_title: str | None = None
    retrieved_at: datetime | None = None
    source_authority: str | None = Field(
        default=None,
        description=(
            "FR-WEB-05 authority tier, e.g. manufacturer datasheet, UL/TUV/Intertek, "
            "IEEE/NFPA, ERCOT/PUCT/TCEQ, IRS/Treasury"
        ),
    )

    @model_validator(mode="after")
    def _must_identify_a_source(self) -> SourceRef:
        """NFR-01: every value traces to a source. An empty ref is never valid."""
        if self.document_id is None and self.url is None:
            raise ValueError("SourceRef requires either document_id or url (NFR-01)")
        return self


class Resolution(BaseModel):
    """A human decision on a queued conflict. Logged immutably per FR-HITL-06."""

    model_config = ConfigDict(frozen=True)

    action: ResolutionAction
    resolved_by: str
    resolved_at: datetime
    rationale: str
    value_before: object | None = None
    value_after: object | None = None


class DeclaredBand(BaseModel):
    """A tolerance the source itself prints, stored as written.

    Shape fixed by the frozen contract's *Declared bands* section:
    `{ low, high, kind, unit }`. A declared band is **not** the conflict tolerance
    of clarifications.md D-2, which governs how far two independently extracted
    values may diverge before a human is asked; conflating the two was the
    original error. This one says how tightly the supplier guarantees a single
    number.

    Note on placement: issue #2 proposed a `declared_tolerance` key on
    `CanonicalField`. The contract instead types `power_tolerance` and
    `bifaciality_tolerance` *as* `DeclaredBand`, so a band is a field value like
    any other and carries its own provenance, conditions and conflict state for
    free. The contract outranks the issue (open-decisions rule 1), and a second
    home for the same object would be a second thing to keep in sync.
    """

    model_config = ConfigDict(frozen=True)

    low: float = Field(description="Lower offset from nominal. `0` for a one-sided `0 ~ +5 W`.")
    high: float = Field(description="Upper offset from nominal.")
    kind: ToleranceKind
    unit: str | None = Field(
        default=None,
        description=(
            "The unit `low`/`high` are expressed in. Required when kind is "
            "absolute and absent when it is relative, where percentage points of "
            "the nominal are implied - which is what makes the contract's "
            "`str | None` two states rather than an optional extra."
        ),
    )

    @field_validator("low", "high")
    @classmethod
    def _reject_non_finite(cls, value: float) -> float:
        """Same reasoning as `ConditionDimensions`: a NaN bound compares false
        against everything, so a band containing one would silently declare every
        value in agreement. `-0.0` is folded for the same repr-stability reason."""
        if not math.isfinite(value):
            raise ValueError("a declared band must have finite bounds (no NaN or infinity)")
        return value + 0.0

    @field_validator("unit", mode="before")
    @classmethod
    def _normalise_unit(cls, value: str | None) -> str | None:
        if value is None or not isinstance(value, str):
            return value
        return value.strip() or None

    @model_validator(mode="after")
    def _check_shape(self) -> DeclaredBand:
        if self.low > self.high:
            raise ValueError(f"declared band is inverted: low={self.low} > high={self.high}")
        if self.kind is ToleranceKind.ABSOLUTE and self.unit is None:
            raise ValueError(
                "an absolute declared band needs a unit; `0 ~ +5` alone is not a quantity"
            )
        if self.kind is ToleranceKind.RELATIVE and self.unit not in (None, "%"):
            raise ValueError(f"a relative declared band is in percentage points, not {self.unit!r}")
        return self

    def resolve(self, nominal: float) -> tuple[float, float]:
        """The guaranteed range around `nominal`, in the parameter's own unit.

        This is the only place a relative band is multiplied out, per the
        contract: doing it at extraction fabricates a disagreement between the
        605 W and 625 W rows of a Jinko sheet that print one identical tolerance,
        and it is circular when the disputed field *is* the nominal.

        Returned lowest-first. A relative band on a negative nominal - a Pmax
        temperature coefficient of `-0.29 %/degC` is the real case - maps `low` to
        the *upper* bound, so returning `(low_offset, high_offset)` unswapped
        would hand the caller an inverted interval that intersects nothing.
        """
        if self.kind is ToleranceKind.RELATIVE:
            bounds = (nominal + nominal * self.low / 100.0, nominal + nominal * self.high / 100.0)
        else:
            bounds = (nominal + self.low, nominal + self.high)
        if not all(math.isfinite(bound) for bound in bounds):
            # `_reject_non_finite` guards the stored bounds because a non-finite
            # band "agrees" with everything; the arithmetic here can manufacture
            # one from finite inputs at absurd magnitudes, which would reach the
            # same place by another route.
            raise ValueError(
                f"resolving this band against {nominal!r} overflows to a non-finite range"
            )
        return (min(bounds), max(bounds))

    def agrees(self, nominal: float, other: DeclaredBand | None, other_nominal: float) -> bool:
        """Whether two nominals can denote the same physical part.

        True when their guaranteed ranges intersect. Closed intervals on purpose:
        a 650 W module declared `0 ~ +5 W` guarantees `[650, 655]` and a 655 W one
        guarantees `[655, 660]`, and a part measuring exactly 655 W satisfies both
        labels, so touching is agreement rather than the narrowest possible
        conflict.

        `other=None` means the other source printed no band, not that it has none:
        its nominal is treated as the exact point `[v, v]`. That is deliberately
        the strict reading - it can raise a conflict a shared band would have
        absorbed, which is one extra queue item, where the permissive reading
        silently merges two different SKUs.
        """
        low, high = self.resolve(nominal)
        other_low, other_high = (
            other.resolve(other_nominal) if other is not None else (other_nominal, other_nominal)
        )
        return low <= other_high and other_low <= high


class ConditionDimensions(BaseModel):
    """The machine-comparable dimensions of a measurement condition.

    Membership of this model *is* the definition of what gates comparison, so a
    new dimension participates automatically and a new human-readable annotation
    automatically does not. See clarifications.md D-1.

    Not intended as a field annotation anywhere: annotate with `Condition`. A
    field typed as this class accepts a `Condition` but serialises through the
    parent schema and silently drops `note`.
    """

    model_config = ConfigDict(frozen=True)

    basis: MeasurementBasis | None = Field(
        default=None,
        description=(
            "What the rating is measured against. Which tokens are legal depends "
            "on the parameter family - see the Conditions table in "
            "contracts/canonical-parameters.md rather than restating it here."
        ),
    )
    temperature_c: float | None = Field(
        default=None, description="Ambient the rating is stated at, e.g. 30 / 40 / 50"
    )
    side: PowerSide | None = Field(default=None, description="Load-bearing for BESS")
    duration_h: float | None = Field(
        default=None, description="Rated duration; BESS RTE is duration-dependent"
    )
    weighting: EfficiencyWeighting | None = None
    standards_regime: StandardsRegime | None = Field(
        default=None,
        description=(
            "Determines which multi-cooling rating is canonical, the loss reference "
            "temperature, and the vector-group phase convention. clarifications.md D-6."
        ),
    )
    reference_temperature_c: float | None = Field(
        default=None, description="Loss reference temperature: 20 + rise (IEEE) or 75 (IEC)"
    )
    rte_boundary: RteBoundary | None = Field(
        default=None,
        description=(
            "Where a BESS round-trip efficiency is measured. A dimension, not a "
            "note: four distinct boundaries are all called 'round-trip efficiency' "
            "and they are worth 2-7 percentage points. Closed rather than free "
            "text, because five spellings of one boundary form five groups and "
            "stop comparing - silent suppression one level below the `note` "
            "routing this replaced."
        ),
    )
    tap_position_pct: float | None = Field(
        default=None,
        description=(
            "Transformer tap a %Z or loss figure is stated at, as a percentage "
            "deviation from the principal tap: `0.0` is nominal, `5.0` is the +5% "
            "tap. A number rather than a name for the same reason `rte_boundary` "
            "is an enum - 'nominal', 'principal tap' and 'Nominal Tap' are one "
            "measurement, and as free text they were three groups that never met."
        ),
    )
    base_mva: float | None = Field(
        default=None,
        description=(
            "Rating the transformer's %Z and losses are referred to. A grouping "
            "dimension, not a note: IEEE refers impedance to the ONAN base and IEC "
            "to the top rating, so two %Z figures on different bases differ by "
            "1.25-1.67x - far beyond the +/-7.5% tolerance. See clarifications.md D-6."
        ),
    )

    @field_validator(
        "temperature_c",
        "duration_h",
        "reference_temperature_c",
        "base_mva",
        "tap_position_pct",
    )
    @classmethod
    def _reject_non_finite(cls, value: float | None) -> float | None:
        """NaN would break the equivalence relation `grouping_key` depends on.

        `NaN != NaN`, so two identically-conditioned values would land in separate
        groups and never compare - and pydantic serialises NaN to JSON `null`, so
        the same record would group differently before and after a store
        round-trip. That is precisely the FR-OUT-06 purity `grouping_key` exists to
        guarantee, so a non-finite condition is rejected at the boundary instead.
        """
        if value is None:
            return None
        if not math.isfinite(value):
            raise ValueError("condition dimensions must be finite (no NaN or infinity)")
        # -0.0 == 0.0 and hashes alike, so they are one dict key - but they have
        # different reprs, which flipped the order of a repr-sorted partition.
        return value + 0.0

    @field_validator(
        "basis", "side", "weighting", "standards_regime", "rte_boundary", mode="before"
    )
    @classmethod
    def _normalise_vocabulary(cls, value: object) -> object:
        """Fold a printed spelling to its member, then let pydantic coerce.

        `mode="before"`, so `"  STC "` becomes `"stc"` and *then* coerces to
        `MeasurementBasis.STC` rather than failing validation. With the
        vocabularies closed an unrecognised token now raises instead of silently
        forming its own group - the failure direction that cannot be reviewed,
        because nothing surfaces a comparison that never happened.
        """
        return _normalise_token(value)


#: Printed spellings that denote a vocabulary member rather than a new value.
#:
#: Not convenience. Closing the vocabularies turned every unlisted spelling into
#: a hard validation failure, and these are the forms real sources print: this
#: repo's own text writes "ANSI/IEEE (C57.12.00 5.4)" and "ANSI submittals
#: declare `Dyn1`", while Fronius- and SMA-family sheets print "Euro efficiency".
#: Rejecting them would drop the document, which is a worse outcome than folding
#: a synonym whose meaning nothing disputes.
#:
#: Deliberately only exact synonyms. `gb` (GB 1094), `is` (IS 2026) and `csa` are
#: *derived* from one regime rather than names for it, and asserting which would
#: be a technical claim about a standard nobody here has read - see
#: open-decisions.md.
VOCABULARY_ALIASES: dict[str, str] = {
    "ansi": "ieee",
    "ansi/ieee": "ieee",
    "ieee/ansi": "ieee",
    "euro": "european",
    "eu": "european",
}

#: Characters PDF and XLSX extraction inserts that carry no meaning. `str.strip`
#: removes NBSP but none of these, so `﻿stc` was a hard validation failure
#: on a document whose only sin was a byte-order mark.
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍﻿­⁠"))


class VocabularyError(ValueError):
    """A condition dimension arrived as something other than text or a member."""


def _normalise_token(value: object) -> object:
    """Fold a printed token to its canonical member name.

    NFKC first, then case, then the invisible characters extraction leaves
    behind. A `StrEnum` member passes through untouched: folding it would work
    only by accident today, because all four vocabularies happen to be
    lowercase, and would silently break the first mixed-case member anyone adds.
    """
    if value is None or isinstance(value, StrEnum):
        return value
    if isinstance(value, bytes | bytearray):
        # pydantic decodes bytes for a str field, so `b"stc"` validated while
        # `b"STC"` raised - the same input, case-dependent, on the one path this
        # validator exists to make case-insensitive.
        raise VocabularyError(
            "condition vocabularies take text, not bytes; decode at the "
            "extraction boundary where the encoding is known"
        )
    if not isinstance(value, str):
        return value
    folded = unicodedata.normalize("NFKC", value).translate(_INVISIBLE).strip().casefold()
    # `dc-dc-terminals`, `DC DC terminals` and `dc_dc_terminals` are one token.
    # No member contains a hyphen or a space, so this cannot collide two distinct
    # members. Folding hyphens but not spaces split the difference in the
    # direction that drops documents: no datasheet prints `full_power`, they
    # print "Full power", and closing the vocabularies made that a hard failure.
    # Whitespace is collapsed first so `ANSI / IEEE` reaches its alias.
    # A slash separates alternatives rather than words, so whitespace around it
    # collapses away first: `ANSI / IEEE` has to reach the `ansi/ieee` alias,
    # not become `ansi_/_ieee`.
    folded = re.sub(r"\s*/\s*", "/", folded)
    folded = "_".join(folded.replace("-", " ").replace("_", " ").split())
    # An extractor emitting "" rather than None would otherwise read as a stated
    # dimension and strand the value in its own group.
    if not folded:
        return None
    return VOCABULARY_ALIASES.get(folded, folded)


class Condition(ConditionDimensions):
    """The measurement conditions a value holds under.

    A ninth key beyond the eight TRS section 5 fixes. Two values are comparable
    only when their conditions match; a mismatch is not a conflict, it is not a
    comparison. Rationale and the Sungrow SG350HX worked case: clarifications.md
    D-1. Which dimensions each parameter family requires: the Conditions table in
    contracts/canonical-parameters.md.
    """

    note: str | None = Field(default=None, description="Any condition not captured above")
    derived: frozenset[str] = Field(
        default=frozenset(),
        description=(
            "Dimensions filled by convention rather than read from the source. "
            "Lives on this subclass, not on ConditionDimensions, so it is excluded "
            "from grouping by construction: a defaulted STC value and a stated STC "
            "value group together while the provenance stays honest for a reviewer."
        ),
    )

    @field_serializer("derived")
    def _sort_derived(self, value: frozenset[str]) -> list[str]:
        """Sorted on the way out: a frozenset serialises in hash order, which is
        randomised per process, so the same record would produce different JSON
        bytes every run - defeating the FR-OUT-06 purity this model exists for."""
        return sorted(value)

    def is_unstated(self) -> bool:
        """Whether no comparable dimension is known at all.

        Detection does not partition, so nothing needs rescuing: see
        `services.conflict_hitl.comparison_pairs`, which compares an unstated
        condition against every condition it does not contradict.
        """
        return all(value is None for value in self.grouping_key())

    def grouping_key(self) -> tuple[object, ...]:
        """A canonical key for *displaying* candidates grouped by condition.

        Equality over this tuple is an equivalence relation - reflexive because
        non-finite floats are rejected at construction, and transitive because it
        is plain tuple equality - so partitioning by it does not depend on the
        order candidates arrive in. FR-OUT-06 requires that, since composition
        must be a pure function of the store.

        Grouping by this key alone is *comparison-losing*, though: a value whose
        conditions are merely less specific strands in its own group and is
        compared against nothing. That is why detection uses
        `services.conflict_hitl.comparison_pairs` and this key is for display.

        `note` and `derived` are excluded: free text is provenance for a human,
        and how a dimension came to be filled does not change what it says.
        """
        return tuple(getattr(self, name) for name in ConditionDimensions.model_fields)

    def comparable_with(self, other: Condition) -> bool:
        """Whether these two specific values may be compared.

        Any dimension set on both sides must agree; a dimension absent on one side
        is unknown rather than contradictory.

        **This relation is deliberately not transitive, so it must never be used to
        partition a candidate set.** `@30 degC` and `@40 degC` are both comparable
        with an unstated condition but not with each other, so first-fit bucketing
        over the same three values yields different groups depending on the order
        they arrive - and therefore a different conflict queue from the same store.
        This is the detection predicate - `services.conflict_hitl.comparison_pairs`
        applies it to every unordered pair. Do not use it to bucket candidates;
        first-fit bucketing over a non-transitive relation gives a different
        conflict queue per document order. See issue #12.
        """
        for name in ConditionDimensions.model_fields:
            mine, theirs = getattr(self, name), getattr(other, name)
            if mine is not None and theirs is not None and mine != theirs:
                return False
        return True


class CanonicalField(BaseModel):
    """One extracted parameter, with provenance, conditions and conflict state.

    Nine keys: the eight fixed by TRS section 5, plus `condition`. The deviation
    is recorded in analysis.md A-1.

    Mutable, because a field is a working record that gains a resolution as the
    pipeline runs - but `validate_assignment`, because `_resolution_matches_status`
    ran only in the constructor and the state FR-HITL-06 forbids was therefore one
    attribute assignment away.

    **This closes assignment, not every route.** `model_copy(update=...)` re-runs
    no validators in pydantic, so it still produces a RESOLVED field carrying no
    `Resolution`, and that copy serialises to the audit trail without complaint.
    Freezing would not have helped - it makes `model_copy` the only way to update
    a field, so the same hole becomes the sole path rather than the second one.
    Closing it needs an explicit revalidating constructor for updates, which
    nothing owns yet; until then the guarantee here is "no invalid state by
    assignment", not "no invalid state".

    Note also that the two-step update has an order: setting `conflict_status` to
    RESOLVED before attaching the `Resolution` raises, because that intermediate
    state is exactly the forbidden one. Attach the resolution first.
    """

    model_config = ConfigDict(validate_assignment=True)

    value: object | None = None
    unit: str | None = Field(default=None, description="Canonical unit per FR-ING-08")
    verbatim_value: str | None = Field(
        default=None, description="Original text as written, retained per FR-ING-08"
    )
    condition: Condition = Field(
        default_factory=Condition, description="Conditions the value holds under - see D-1"
    )
    source_tier: SourceTier
    source_ref: SourceRef
    confidence: float = Field(ge=0.0, le=1.0)
    conflict_status: ConflictStatus = ConflictStatus.NONE
    resolution: Resolution | None = None

    @model_validator(mode="after")
    def _resolution_matches_status(self) -> CanonicalField:
        if self.conflict_status is ConflictStatus.RESOLVED and self.resolution is None:
            raise ValueError("a resolved field must carry its Resolution (FR-HITL-06)")
        return self

    def is_missing(self) -> bool:
        """FR-OUT-04 missing-data flag."""
        return self.value is None

    def is_web_supplemented(self) -> bool:
        """FR-OUT-04 web-supplemented flag."""
        return self.source_tier is SourceTier.WEB_SUPPLEMENT


class ConflictCandidate(BaseModel):
    """One competing value for a field, as presented in the queue (FR-HITL-03)."""

    model_config = ConfigDict(frozen=True)

    value: object | None
    unit: str | None
    verbatim_value: str | None = Field(
        default=None, description="FR-HITL-03 requires the verbatim source text"
    )
    condition: Condition = Field(
        default_factory=Condition,
        description=(
            "The conditions this candidate holds under. Required for the queue to "
            "explain itself (FR-HITL-03): '352 kVA vs 320.865 kW' is unreadable "
            "without @30 degC / @40 degC attached. Also what "
            "services.conflict_hitl.comparison_groups partitions on."
        ),
    )
    source_tier: SourceTier
    source_ref: SourceRef
    confidence: float = Field(ge=0.0, le=1.0)


class ConflictQueueEntry(BaseModel):
    """An item awaiting human resolution.

    FR-HITL-03 fixes the payload: canonical field, component/supplier, all
    candidate values with verbatim source text, source tier, source authority,
    doc/page/URL, timestamps and a generated explanation.

    Frozen, because FR-HITL-06's log is immutable and freezing `Resolution` alone
    did not deliver that: the *pointer* was assignable, so a second write replaced
    a reviewer's decision with no trace the first had ever existed. Attaching a
    resolution is `model_copy(update=...)`, which produces a new record rather
    than editing one - the shape an append-only audit log wants anyway.

    Frozen is shallow, as it always is in pydantic: `candidates` is a list, and
    nothing stops a caller mutating it in place. So the guarantee this buys is
    narrow and worth stating as such - a recorded `resolution` cannot be silently
    swapped. That is one part of FR-HITL-06, not the whole of it: the requirement
    also wants a persisted, tamper-evident log, which is NFR-02 and plan Decision
    9 and does not exist yet.
    """

    model_config = ConfigDict(frozen=True)

    entry_id: str
    field_name: str
    supplier: str
    model: str
    #: The closed vocabulary, not a bare `str`: the frozen contract types this
    #: `ComponentCategory` (contracts/canonical-parameters.md), and
    #: `ComponentInstance` already did. The bare `str` here accepted a plausible
    #: label like "PV Modules" that is not a member, and `CATEGORY_TO_TAB` is keyed
    #: on the enum - so once composition reads this field, such a value routes to
    #: no tab. Closing it now makes that a construction-time error instead.
    component_category: ComponentCategory
    conflict_class: ConflictClass
    severity: Severity = Field(
        description=(
            "Drives the compose gate (issue #14). Assigned from the field's "
            "criticality tier, not from the size of the divergence - see D-3. "
            "Deliberately REQUIRED: this is a safety interlock, and any default "
            "at or below the gate threshold would make a forgotten severity "
            "silently unable to block."
        ),
    )
    candidates: list[ConflictCandidate]
    explanation: str = Field(description="Generated rationale shown to the reviewer")
    detected_at: datetime
    resolution: Resolution | None = None
