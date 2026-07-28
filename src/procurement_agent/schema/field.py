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

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import ConflictClass, ConflictStatus, ResolutionAction, SourceTier


class SourceRef(BaseModel):
    """Where a value came from. NFR-01 permits no unsourced values.

    A document reference carries doc_id plus page and table/section (FR-ING-07).
    A web reference carries url, page_title and retrieved_at (FR-WEB-02).
    """

    model_config = ConfigDict(frozen=True)

    document_id: str | None = None
    page: int | None = None
    section: str | None = Field(default=None, description="Table or section locator")
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


class CanonicalField(BaseModel):
    """One extracted parameter, with provenance and conflict state attached."""

    value: object | None = None
    unit: str | None = Field(default=None, description="Canonical unit per FR-ING-08")
    verbatim_value: str | None = Field(
        default=None, description="Original text as written, retained per FR-ING-08"
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
    source_tier: SourceTier
    source_ref: SourceRef
    confidence: float = Field(ge=0.0, le=1.0)


class ConflictQueueEntry(BaseModel):
    """An item awaiting human resolution.

    FR-HITL-03 fixes the payload: canonical field, component/supplier, all
    candidate values with verbatim source text, source tier, source authority,
    doc/page/URL, timestamps and a generated explanation.
    """

    entry_id: str
    field_name: str
    supplier: str
    model: str
    component_category: str
    conflict_class: ConflictClass
    candidates: list[ConflictCandidate]
    explanation: str = Field(description="Generated rationale shown to the reviewer")
    detected_at: datetime
    resolution: Resolution | None = None
