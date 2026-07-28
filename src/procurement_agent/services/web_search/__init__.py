"""Web Search - supplement only (FR-WEB-01 .. FR-WEB-05).

Query generation, fetch, extraction, supplement-only tagging, authority capture.

The hard rule from TRS section 1 governs this whole module: web data may fill an
empty field but must never overwrite a system-of-record value, and a
web-vs-record disagreement is surfaced, never arbitrated here.
"""

from __future__ import annotations

from ...schema import CanonicalField

#: FR-WEB-05 authority ordering, most authoritative first. Recorded as metadata
#: on each web value; it informs the reviewer, it does not auto-resolve anything.
SOURCE_AUTHORITY_ORDER: tuple[str, ...] = (
    "manufacturer_datasheet",
    "ul_tuv_intertek",
    "ieee_nfpa",
    "ercot_puct_tceq",
    "irs_treasury",
)


def search_for_gap(field_name: str, supplier: str, model: str) -> list[CanonicalField]:
    """Look for supplementary values for a field that has no record value.

    Triggered only when a required field has no system-of-record value, or on
    explicit user request (FR-WEB-01).

    Every returned field is tagged source_tier=web_supplement with URL, page
    title and retrieval timestamp, and the query itself is logged for
    reproducibility (FR-WEB-02, NFR-02).
    """
    raise NotImplementedError
