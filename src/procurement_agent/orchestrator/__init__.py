"""Orchestrator.

Owns agent workflow, state, retries, and the provenance/audit trail.

Implemented as a Postgres-backed stage state machine - no workflow framework.
NFR-02 already forces the audit trail into Postgres and FR-OUT-06 makes
composition a pure function of the canonical store, so a workflow checkpointer
would be a second copy of state we already own. See plan.md Decision 1.

**The runner is a single-process driver, not a leased job queue** (plan.md
Decision 1a, register A-45). Each stage maps over its units of work with the two
pools `config.Settings` already configures - `max_concurrent_parse` for
CPU-bound parse/OCR, `max_concurrent_llm` for extraction calls. There is no
`SELECT ... FOR UPDATE SKIP LOCKED` worker fleet, no lease, no sweeper and no
persisted backoff schedule: Decision 2 detached the human gate, so nothing is
ever parked for days; the store is already idempotent by natural key
(`document.content_hash`, append-only claims), so replay is a no-op; and
concurrency lives in those two pools rather than in a second worker process.
Crash recovery is therefore "re-run the batch" - which is sound *because* the
`content_hash` UNIQUE constraint and `ON CONFLICT DO NOTHING` upsert AC-5 needs
anyway make the database refuse the duplicate.

The `job` table stays, as a progress and quarantine **ledger this driver
writes** rather than a queue it contends on. A document that fails a stage is
recorded `quarantined` with its error and the batch continues (tasks.md I.4,
plan.md Decision 4 tier 3). The lease columns stay unused in the DDL so that
adopting a second worker process later is a runner change, not a migration.

None of this touches the **conflict-claim** leases in `sql/05_conflict.sql`
(tasks.md F.1/F.4): that table has genuine multi-human contention, where two
reviewers must not be handed the same conflict and an abandoned claim must
expire.

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
    return [
        entry
        for entry in unresolved
        # `resolution is None` is the actual unresolved test. The parameter name
        # said "unresolved" and the filter only checked severity, so a CRITICAL
        # conflict a human had already resolved went on blocking composition.
        if entry.resolution is None and entry.severity > threshold
    ]


def compose_gate_blocks(unresolved: Sequence[ConflictQueueEntry], *, threshold: Severity) -> bool:
    """Whether composition should refuse to run.

    The only place a human decision gates the pipeline, and it is a query rather
    than a pause. Overridable by a recorded, audited decision - composition then
    emits a completeness manifest naming every unresolved conflict instead
    (FR-HITL-05), which is why `blocking_conflicts` is the primitive and this is
    the convenience wrapper.
    """
    return bool(blocking_conflicts(unresolved, threshold=threshold))


def run(*args: object, **kwargs: object) -> None:
    """Execute the pipeline. Batch/offline per NFR-07.

    Single-process driver (plan.md Decision 1a, tasks.md I.1): for each `Stage`
    in order, map over that stage's units of work with the two configured pools,
    write progress to the `job` ledger, and continue past a quarantined
    document. Re-running an interrupted batch is the recovery path - completed
    work no-ops on the store's natural keys - so this takes no lease and holds
    no scheduler state between invocations.
    """
    raise NotImplementedError
