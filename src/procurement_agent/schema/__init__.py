"""Canonical data model. TRS sections 5 and 7."""

from .component import ComponentInstance, SourceDocument
from .enums import (
    CATEGORY_TO_TAB,
    CellFlag,
    ComponentCategory,
    ConflictClass,
    ConflictStatus,
    DocumentType,
    ResolutionAction,
    Severity,
    SourceTier,
    WorkbookTab,
)
from .field import (
    CanonicalField,
    Condition,
    ConditionDimensions,
    ConflictCandidate,
    ConflictQueueEntry,
    Resolution,
    SourceRef,
)

__all__ = [
    "CATEGORY_TO_TAB",
    "CanonicalField",
    "CellFlag",
    "ComponentCategory",
    "ComponentInstance",
    "Condition",
    "ConditionDimensions",
    "ConflictCandidate",
    "ConflictClass",
    "ConflictQueueEntry",
    "ConflictStatus",
    "DocumentType",
    "Resolution",
    "ResolutionAction",
    "Severity",
    "SourceDocument",
    "SourceRef",
    "SourceTier",
    "WorkbookTab",
]
