"""Orchestrator.

Owns agent workflow, state, retries, and the provenance/audit trail.

Implemented as a Postgres-backed stage state machine with a
`SELECT ... FOR UPDATE SKIP LOCKED` worker loop - no workflow framework.
NFR-02 already forces the audit trail into Postgres and FR-OUT-06 makes
composition a pure function of the canonical store, so a workflow checkpointer
would be a second copy of state we already own. See plan.md Decision 1.

**The human gate does not block the pipeline.** Conflict resolution is detached:
the gate is a policy check at compose time - a query, not an interrupt. "Defer"
is one of the five mandated resolution actions (FR-HITL-04), and a blocking
workflow has no coherent semantics for indefinite deferral. See plan.md
Decision 2.

Pipeline:

    ingest -> extract -> index -> enrich_via_web -> detect_conflicts
                                                          |
                    compose_workbook  <- [compose gate: severity query]
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from ..schema import ConflictQueueEntry, Severity


class Stage(StrEnum):
    """Pipeline stages.

    There is deliberately no `await_human_resolution` stage. Resolution happens
    outside the pipeline, and composition re-runs against whatever is resolved
    at the time. Nothing is ever parked waiting for a person.
    """

    INGEST = "ingest"
    EXTRACT = "extract"
    INDEX = "index"
    ENRICH_VIA_WEB = "enrich_via_web"
    DETECT_CONFLICTS = "detect_conflicts"
    COMPOSE_WORKBOOK = "compose_workbook"


def blocking_conflicts(
    unresolved: Sequence[ConflictQueueEntry], *, threshold: Severity
) -> list[ConflictQueueEntry]:
    """The unresolved conflicts severe enough to hold up composition.

    Returns the entries themselves, not a bare verdict, so a caller that refuses
    to compose can name *which* conflicts refused it - which is what the
    FR-HITL-05 completeness manifest has to print, and what an audited override
    has to record.

    Strictly **above** the threshold, matching plan.md Decision 2 and tasks.md I.3
    ("unresolved conflicts above a severity threshold"). The previous `>=` blocked
    at the threshold itself; see issue #14.

    Takes a `Sequence`, not an `Iterable`: the documented pairing is
    `if compose_gate_blocks(q): manifest(blocking_conflicts(q))`, and with a
    generator the second call would return `[]` - reporting zero blockers into
    the very manifest the refusal exists to populate.
    """
    return [entry for entry in unresolved if entry.severity > threshold]


def compose_gate_blocks(
    unresolved: Sequence[ConflictQueueEntry], *, threshold: Severity
) -> bool:
    """Whether composition should refuse to run.

    The only place a human decision gates the pipeline, and it is a query rather
    than a pause. Overridable by a recorded, audited decision - composition then
    emits a completeness manifest naming every unresolved conflict instead
    (FR-HITL-05), which is why `blocking_conflicts` is the primitive and this is
    the convenience wrapper.
    """
    return bool(blocking_conflicts(unresolved, threshold=threshold))


def run(*args: object, **kwargs: object) -> None:
    """Execute the pipeline. Batch/offline per NFR-07."""
    raise NotImplementedError
