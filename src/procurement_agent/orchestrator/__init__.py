"""Orchestrator.

Owns agent workflow, state, retries, and the provenance/audit trail.

The TRS specifies no state machine, retry policy or inter-service transport -
these are open design decisions. The reference memo recommends LangGraph with a
Postgres checkpointer, and its guidance on interrupts is the load-bearing part:
interrupt only on high-blast-radius or uncertain nodes (detected conflicts,
low-confidence extractions), not on every step, or latency becomes unbounded.

Pipeline:

    ingest -> extract -> index -> enrich_via_web -> detect_conflicts
        -> [interrupt: human approval] -> compose_workbook
"""

from __future__ import annotations

from enum import StrEnum


class Stage(StrEnum):
    """Pipeline stages. Only the last two are expected to interrupt."""

    INGEST = "ingest"
    EXTRACT = "extract"
    INDEX = "index"
    ENRICH_VIA_WEB = "enrich_via_web"
    DETECT_CONFLICTS = "detect_conflicts"
    AWAIT_HUMAN_RESOLUTION = "await_human_resolution"
    COMPOSE_WORKBOOK = "compose_workbook"


#: Stages that may pause for a human. Kept explicit so that adding an interrupt
#: is a deliberate change rather than an emergent property of node code.
INTERRUPTING_STAGES: frozenset[Stage] = frozenset(
    {Stage.DETECT_CONFLICTS, Stage.AWAIT_HUMAN_RESOLUTION}
)


def run(*args: object, **kwargs: object) -> None:
    """Execute the pipeline. Batch/offline per NFR-07."""
    raise NotImplementedError
