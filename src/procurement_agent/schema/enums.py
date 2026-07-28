"""Closed vocabularies from TRS v2.

Every value here is enumerated explicitly in the spec. Where the spec fixes a
list, it is reproduced verbatim rather than left open, because the Excel output
(FR-OUT-02) and the conflict queue (FR-HITL-01/04) both depend on the exact set.
"""

from enum import StrEnum


class SourceTier(StrEnum):
    """TRS section 1, "hard rule".

    Ingested contracts and spec sheets are the system of record. Web data may
    populate an empty field but must never overwrite a system-of-record value
    (FR-WEB-03), and disagreements between the two are never auto-arbitrated
    (FR-HITL-02).
    """

    SYSTEM_OF_RECORD = "system_of_record"
    WEB_SUPPLEMENT = "web_supplement"


class ComponentCategory(StrEnum):
    """The eight component categories. Tabs 1-8 of the workbook (FR-OUT-02).

    Note: the FRD's comparison table merges cabling and combiner boxes into one
    row, giving seven. The TRS splits them into tabs 5 and 6. This follows the
    TRS. See docs/open-questions.md.
    """

    PV_MODULES = "pv_modules"
    INVERTERS_PCS = "inverters_pcs"
    TRACKERS_MOUNTING = "trackers_mounting"
    TRANSFORMERS = "transformers"
    CABLING_WIRING = "cabling_wiring"
    COMBINER_BOXES = "combiner_boxes"
    BESS = "bess"
    EMS_SCADA = "ems_scada"


class DocumentType(StrEnum):
    """The eight document types each ingested file is classified into (FR-ING-06)."""

    CONTRACT_TOS = "contract_tos"
    PURCHASE_ORDER = "purchase_order"
    ENVIRONMENTAL_REGULATION = "environmental_regulation"
    TERMS_AND_CONDITIONS = "terms_and_conditions"
    WARRANTY = "warranty"
    TECHNICAL_DOCUMENTATION = "technical_documentation"
    PRICING = "pricing"
    SPEC_SHEET = "spec_sheet"


class ConflictClass(StrEnum):
    """The five conflict classes detected at field level (FR-HITL-01)."""

    RECORD_VS_WEB = "record_vs_web"
    INTER_DOCUMENT = "inter_document"
    INTRA_DOCUMENT = "intra_document"
    TEMPORAL = "temporal"
    UNIT_NORMALIZATION = "unit_normalization"


class ConflictStatus(StrEnum):
    """Lifecycle of a field's conflict state.

    NONE and INSUFFICIENT_EVIDENCE are not named as such in the TRS, but the
    field object carries a `conflict_status` for every field, so the
    no-conflict and the FR-RAG-04 "insufficient evidence" states need
    representation alongside the open/resolved states.
    """

    NONE = "none"
    OPEN = "open"
    RESOLVED = "resolved"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ResolutionAction(StrEnum):
    """The five actions a human may take on a queued conflict (FR-HITL-04)."""

    SELECT_VALUE = "select_value"
    ENTER_OVERRIDE = "enter_override"
    KEEP_SYSTEM_OF_RECORD = "keep_system_of_record"
    REQUEST_MORE_WEB_SEARCH = "request_more_web_search"
    DEFER = "defer"


class WorkbookTab(StrEnum):
    """All thirteen tabs, in order (FR-OUT-02). AC-3 checks every one is present."""

    PV_MODULES = "PV Modules"
    INVERTERS_PCS = "Inverters-PCS"
    TRACKERS_MOUNTING = "Trackers & Mounting"
    TRANSFORMERS = "Transformers"
    CABLING_WIRING = "Cabling & Wiring"
    COMBINER_BOXES = "Combiner Boxes"
    BESS = "BESS"
    EMS_SCADA = "EMS-SCADA & Controls"
    EXECUTIVE_SUMMARY = "Executive Summary"
    CONFLICTS_OPEN_ITEMS = "Conflicts & Open Items"
    SOURCES_PROVENANCE = "Sources & Provenance"
    COMPLIANCE_MATRIX = "Compliance Matrix"
    TAX_INCENTIVES = "Tax Incentives"


#: Category tabs in workbook order, so the writer and AC-3 agree on the mapping.
CATEGORY_TO_TAB: dict[ComponentCategory, WorkbookTab] = {
    ComponentCategory.PV_MODULES: WorkbookTab.PV_MODULES,
    ComponentCategory.INVERTERS_PCS: WorkbookTab.INVERTERS_PCS,
    ComponentCategory.TRACKERS_MOUNTING: WorkbookTab.TRACKERS_MOUNTING,
    ComponentCategory.TRANSFORMERS: WorkbookTab.TRANSFORMERS,
    ComponentCategory.CABLING_WIRING: WorkbookTab.CABLING_WIRING,
    ComponentCategory.COMBINER_BOXES: WorkbookTab.COMBINER_BOXES,
    ComponentCategory.BESS: WorkbookTab.BESS,
    ComponentCategory.EMS_SCADA: WorkbookTab.EMS_SCADA,
}


class CellFlag(StrEnum):
    """The four states conditional formatting must distinguish (FR-OUT-04)."""

    UNRESOLVED_CONFLICT = "unresolved_conflict"
    WEB_SUPPLEMENTED = "web_supplemented"
    LOW_CONFIDENCE = "low_confidence"
    MISSING_DATA = "missing_data"
