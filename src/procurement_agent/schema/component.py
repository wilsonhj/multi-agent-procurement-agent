"""Component instances and source documents held in the canonical store.

TRS section 5: "Per component instance: supplier, model, component_category, and
a field set (section 7)." The per-category parameter sets from TRS section 7 are
not yet enumerated here; locking them for PV modules, inverters and BESS is the
Stage 1 exit condition, so they belong in a follow-up rather than in scaffolding.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .enums import ComponentCategory, DocumentType
from .field import CanonicalField


class SourceDocument(BaseModel):
    """An ingested file. Identity is content-addressed so re-ingest is a no-op.

    FR-ING-09 requires stable IDs with timestamps and source URI; NFR-05 and AC-5
    require that re-ingesting an unchanged document creates no duplicates.
    """

    model_config = ConfigDict(frozen=True)

    document_id: str
    content_hash: str = Field(description="Dedup key per FR-ING-09 / NFR-05")
    source_uri: str
    document_type: DocumentType
    ingested_at: datetime
    data_vintage: datetime | None = Field(
        default=None,
        description="Publication or revision date of the source, reported per FR-OUT-06",
    )
    access_restricted: bool = Field(
        default=False,
        description=(
            "NFR-03: contract and pricing documents are confidential. Enforced at "
            "retrieval time via metadata filtering, not only at the API edge."
        ),
    )


class ComponentInstance(BaseModel):
    """One supplier's offering in one category, as a set of canonical fields."""

    supplier: str
    model: str
    component_category: ComponentCategory
    fields: dict[str, CanonicalField] = Field(default_factory=dict)

    def unresolved_conflicts(self) -> list[str]:
        """Field names still awaiting a human decision.

        FR-HITL-05: unresolved conflicts and insufficient-evidence fields are
        flagged in the output, never silently resolved or omitted.
        """
        from .enums import ConflictStatus

        blocking = {ConflictStatus.OPEN, ConflictStatus.INSUFFICIENT_EVIDENCE}
        return [name for name, f in self.fields.items() if f.conflict_status in blocking]
