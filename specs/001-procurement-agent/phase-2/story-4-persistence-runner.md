# Story 4 — General persistence and the runner (C8, WP-I, WP-H remainder)

**Tracks:** 4a repository layer and `sql/10`–`12` · 4b runner and CLI · **Team:** 6
**Needs:** Track 0 (P2-C5, P2-C6, P2-C7) · 4b needs 4a · **Status:** proposed 2026-09-03

**Story.** Every stage of the pipeline — ingest, extract, index, enrich, detect conflicts,
compose — runs as a job a worker claims with `FOR UPDATE SKIP LOCKED`, is idempotent under
at-least-once retry, writes its business rows and its audit events in one transaction, and can be
driven from a CLI. Workers propose claims; one serial reducer per field commits the projection.
The human gate stays a compose-time query.

**Done means.** `procurement-agent ingest <paths>` enqueues; `procurement-agent worker` drains the
six stages against a live PostgreSQL; killing a worker mid-stage and restarting produces no
duplicate rows and no forked audit chain (asserted by counts and `verify_stream`); the compose
stage refuses above the gate and proceeds with a recorded `--accept-incomplete` run event.

---

## Controlling decisions

| ID | Rule |
|---|---|
| Decision 1 | Postgres stage state machine, `SELECT … FOR UPDATE SKIP LOCKED`; no workflow framework; DBOS listed only as the road not taken |
| Decision 2 | The gate is a compose-time query; no interrupt stage; override is a recorded, audited decision |
| Decision 9 / D-13 | Privilege separation is the boundary; per-document chain; advisory lock as its own statement; same-transaction audit; `attempt_failed` from the exception handler in a new transaction; **run-scoped events on `audit.run_event`** |
| Decision 10 | Sync ports; per-process concurrency; `Settings` caps |
| C8 | Immutable claim rows keyed by natural key; canonical value is a projection over claims; only the reducer takes a write handle |
| D-12b, D-12e | Gate granularity per-document-per-field; lease 15 minutes swept to `pending` |
| D-15, D-12a | Clearance from the OIDC subject → `SET LOCAL app.allow_restricted`; RLS is the boundary |
| D-16 | Human claims carry a `Resolution`; `claim` table needs the link (P2-C6) |
| A-52 | Audit emission originates in the committing worker transaction, never a parent observer |
| agent-topology | Fan-out on ingest (process pool), extract, enrich, detect; composition serial |

## Code surface today

- `sql/00`–`09`: roles `procurement_owner`, `audit_owner` (NOLOGIN), `procurement_app`, `procurement_ingest` (LOGIN); `document` (UNIQUE `content_hash`), `chunk`, `claim` (natural key incl. `condition`, **no `resolution` column**, append-only triggers), `conflict` (`status ∈ pending|leased|resolved`, `lease_owner`, `lease_expires_at`, `reopen_count ≤ 3`), `conflict_candidate`, `resolution` (append-only; five actions; `selected_claim_id`), `audit.event` (seven event types incl. unreachable `web_search`; `recorded_at DEFAULT clock_timestamp()` still present), `job` (six stages = `orchestrator.Stage`; `status ∈ pending|running|succeeded|failed|quarantined`; `idempotency_key` UNIQUE; lease columns; `attempt`, `max_attempts=5`, `next_attempt_at`; documented worker query). Forward-only, `psql` lexical order, no version table.
- `audit/`: `append_event(conn, *, document_id, event_type, actor, payload, recorded_at)` — lock → tip → INSERT, no commit; `verify_stream`; CLI; `EVENT_TYPES_V1`; `stream_for_document`.
- `services/transactional_audit.write_and_append_event()` — one business callback + one event on one caller-owned connection.
- `services/vertical_slice.persist_vertical_slice()` — the only service-owned commit/rollback boundary; its writer's insert order (document → claim → conflict → candidate → resolution) is the reference for the repositories.
- `services/claims.ClaimWriter` Protocol: `commit(field_name, values)` / `current(field_name)`; `commit_claims` is the serial reducer and calls `assert_no_autonomous_overwrite`.
- `orchestrator`: `Stage` (six), `blocking_conflicts`, `compose_gate_blocks`, `run(*args, **kwargs)` raises. **No `reduce` stage** (P2-A-5).
- `Settings`: `database_url: SecretStr`, `compose_gate_threshold: Severity ≤ HIGH`, concurrency caps.

---

## A — Track 4a: repository layer and DDL additions

### A.1 · P2-C5 — `PrincipalContext` and connections (`services/store/principal.py`, `connection.py`)

```python
@dataclass(frozen=True)
class PrincipalContext:
    subject: str                          # OIDC `sub` (D-12a); "system:<worker-id>" for workers
    cleared_for_restricted: bool
    denied_suppliers: frozenset[str] = frozenset()   # Story 7 outcome 2 hook; empty today

@contextmanager
def open_transaction(settings, principal) -> Iterator[psycopg.Connection]:
    # connect as procurement_app (or procurement_ingest for the ingest stage), autocommit off,
    # SET LOCAL app.allow_restricted = 'true' iff principal.cleared_for_restricted,
    # yield; commit on success; rollback on any exception.
```

**The GUC is set here and nowhere else.** A grep test asserts `app.allow_restricted` appears in
exactly one Python module. Workers run as `system:` principals with `cleared_for_restricted=True`
— they must see restricted documents to process them; RLS protects *readers*, and workers are not
readers. Reviewer and UI connections come from Story 5 with the reviewer's clearance.

### A.2 · Repositories (`services/store/*.py`) — thin, SQL-explicit, no ORM

| Repository | Methods | Notes |
|---|---|---|
| `DocumentRepository` | `upsert(SourceDocument) -> (document_id, created: bool)`; `get`; `visible_ids(principal) -> set[str]` | `ON CONFLICT (content_hash) DO NOTHING RETURNING`; `created=False` is AC-5's signal |
| `ChunkRepository` | `write_chunks(list[ChunkRecord], embeddings)`; `delete_for_document` | Story 2's rows; trigger inherits the label |
| `PostgresClaimStore` (implements `ClaimWriter`) | `append(list[FieldClaim]) -> list[claim_id]`; `current(field_name)` = `project()` over stored claims; `commit(field_name, values)` | Workers never call `append` directly. The only write path from a claim to the store remains `commit_claims` (guard then INSERT). `append` is the writer's INSERT; `commit` on the Protocol is not a second store. `ON CONFLICT ON CONSTRAINT claim_natural_key DO NOTHING`; human claims insert **after** their resolution (P2-C6) |
| `ConflictRepository` | `upsert_entry(ConflictQueueEntry)`; `lease(principal, *, limit) -> list[entry]` (`FOR UPDATE SKIP LOCKED`, `status='pending' OR lease_expires_at < now()` → `leased`, 15 min); `release`; `mark_resolved`; `reopen` (increments `reopen_count`, refuses at 3); `sweep_expired()` | Story 5 calls; never writes SQL itself |
| `ResolutionRepository` | `append(entry_id, Resolution, selected_claim_id) -> resolution_id` | append-only |
| `JobRepository` | `enqueue(stage, document_id, payload, idempotency_key)` (`ON CONFLICT DO NOTHING`); `claim(worker_id, stages)` (documented `SKIP LOCKED` query); `succeed`; `fail(error, backoff)`; `quarantine`; `sweep_leases()` | only the columns `procurement_app` may UPDATE |

Every write method takes the connection from `open_transaction`; none commits. The pattern is
`persist_vertical_slice`'s, generalised: the stage handler opens the transaction, calls
repositories, appends audit events on the same connection, returns; the context manager commits.

### A.3 · P2-C6 — `sql/10_claim_resolution_link.sql` (D-27)

```sql
ALTER TABLE public.claim ADD COLUMN resolution_id text NULL REFERENCES public.resolution(resolution_id);
ALTER TABLE public.claim ADD CONSTRAINT claim_human_carries_resolution
  CHECK ((extractor_version LIKE 'human:%') = (resolution_id IS NOT NULL));
```

Mirrors `FieldClaim._human_claims_carry_their_decision`. `sql/README.md` gains the row; the
`test_sql_schema.py` text assertions and a live attack test (`human:` claim without
`resolution_id` is refused; machine claim with one is refused) are added.

### A.4 · P2-C7 — `sql/11_audit_run_event.sql`, `sql/12_audit_event_taxonomy.sql`

Per D-13: `audit.run_event` with its own stream `run:<run_id>`, same envelope, same `"v": 1`
preimage, same append-only grants and fork constraints, event types `web_search`,
`compose_override`, `run_started`, `run_finished`. `sql/12` **removes** `web_search` from
`audit.event`'s CHECK (nothing has emitted it; the live suite proves the table is empty of it
first) and **drops** `recorded_at`'s DEFAULT — the caller supplies it (D-13). `audit/writer.py`
gains `append_run_event(conn, *, run_id, event_type, actor, payload, recorded_at)`; `verify.py`
verifies both stream kinds. The stream CHECK on `audit.event` is **not** widened (D-13 line
692–693).

### A.5 · Live tests (extend `tests/test_sql_behaviour.py`, new `tests/test_store_live.py`)

- `test_app_role_cannot_insert_conflict_from_worker_context` (#8 from agent-topology: the
  extract worker's connection lacks the grants the reducer uses — asserted, not assumed).
- `test_lease_is_exclusive_under_skip_locked` — two connections, one entry, one wins.
- `test_expired_lease_is_reclaimable` · `test_reopen_refused_at_three`.
- `test_run_event_chain_verifies` · `test_event_table_refuses_web_search_after_12`.
- `test_recorded_at_has_no_default_after_12`.
- CI `sql` job applies `00`–`12` and fails on silent skip exactly as today.

---

## B — Track 4b: the runner

### B.1 · Stage handlers and idempotency

`orchestrator/handlers.py` registers one handler per `Stage`. Each handler is
`(conn, job) -> list[Enqueue]` — it does its work on the open transaction and returns the jobs to
enqueue next; the runner enqueues them in the **same** transaction so a crash cannot lose the
successor. Idempotency keys, all functions of stored data:

| Stage | `idempotency_key` | Fan-out unit |
|---|---|---|
| `ingest` | `sha256(content_hash)` | one document (process pool, `max_concurrent_parse`) |
| `extract` | `sha256(document_id, category, extractor_version)` | document × category |
| `index` | `sha256(document_id, "index", chunker_version)` | document |
| `enrich_via_web` | `sha256(component_key, field_name, condition_key, reopen_count)` | one gap field, rate-capped |
| `detect_conflicts` | `sha256(component_key, field_name)` | **one field — this is the serial reducer** (P2-A-5) |
| `compose_workbook` | `sha256(run_id)` | none; serial |

`detect_conflicts` for a field: `project()` over its claims → `comparison_pairs` → `values_conflict`
→ `assign_severity` → `ConflictRepository.upsert_entry` with the slice's deterministic
`entry_id` scheme → `stamp_queue_hits` semantics preserved in the projection → `conflict_detected`
events. Re-running it with unchanged claims changes zero rows (asserted).

### B.2 · Worker loop, retry, quarantine, sweeper

`orchestrator.run(settings, *, stages, worker_id, once=False)`: claim → open transaction as
`system:<worker_id>` → handler → commit → loop. On exception: rollback; in a **new** transaction
write `attempt_failed` (Decision 9's "we attempted X and it failed" class) and `JobRepository.fail`
with exponential backoff (`2^attempt` minutes, capped 60); at `max_attempts` → `quarantined`
(I.4). `sweep_leases()` runs each loop iteration for both `job` and `conflict`. Concurrency:
`max_concurrent_parse` processes for `ingest`; a `ThreadPoolExecutor(max_concurrent_llm)` for
`extract`; `web_search_rate_limit_per_minute` enforced in the adapter (Story 3).

### B.3 · Compose stage and the gate (Decision 2, I.3)

`compose_workbook` handler: `unresolved = ConflictRepository.open_entries()`;
`compose_gate_blocks(unresolved, threshold=settings.compose_gate_threshold)` → if it blocks and
the run lacks `accept_incomplete`, the job **succeeds** (`status='succeeded'` — `sql/08` has no
`blocked` value) with `payload.outcome='blocked'` and a completeness manifest (Story 6, G.8)
listing every blocker; if `accept_incomplete` is set, a `compose_override` run event records who,
when, why and the blocker list, then composition proceeds. Threshold `CRITICAL` is unrepresentable
in `Settings` (`le=HIGH`), so the gate cannot be disabled — unchanged.

### B.4 · CLI (`cli/__init__.py`, `[project.scripts] procurement-agent = …`; D-28, argparse)

`ingest <path…> [--restricted]` (hash, enqueue) · `worker [--stages …] [--once]` ·
`compose [--accept-incomplete --rationale …]` · `queue list|lease|release` (thin over Story 5's
service) · `cec-refresh` (Story 3) · `audit verify [--run <id>|--document <id>]` (wraps the existing
CLI). Every subcommand takes `--as <oidc-sub>` for the principal in non-interactive use; the UI
supplies it from the session.

### B.5 · Observability (I.5)

Structured JSON logs (ADR-001 §7) with `run_id`, `job_id`, `stage`, `document_id`, duration;
per-stage counters exposed by `procurement-agent stats`. NFR-06/07 are **measured** against the
gold corpus once Story 1d exists and recorded in `docs/current-state.md`; the traceability rows
move from "open" only then.

---

## Verify

Minimum new tests: 55. Beyond A.5, named:

- `test_guc_is_set_in_exactly_one_module` · `test_worker_principal_is_cleared` · `test_reader_principal_uncleared_sees_no_restricted_documents` (live)
- `test_document_upsert_returns_created_false_on_second_call` (AC-5 store + caller, live)
- `test_claim_store_current_is_projection_over_claims` · `test_human_claim_requires_prior_resolution_row` (live)
- `test_every_idempotency_key_is_a_function_of_stored_data` (property: same inputs → same key; clock patched)
- `test_successor_jobs_enqueued_in_same_transaction` (crash injected after handler, before commit → no successor)
- `test_retry_after_crash_changes_zero_rows` for each stage (live; count rows before/after)
- `test_detect_conflicts_is_serial_per_field` (two workers, same field → one leases, other skips)
- `test_attempt_failed_written_in_new_transaction_after_rollback`
- `test_quarantine_at_max_attempts` · `test_backoff_schedule`
- `test_compose_blocked_writes_manifest_and_no_workbook` · `test_accept_incomplete_records_override_run_event`
- `test_compose_threshold_critical_unrepresentable` (exists; keep)
- `test_cli_ingest_enqueues_with_content_hash_key` · `test_cli_worker_once_drains_one_job`
- `test_audit_chain_verifies_after_full_run` (`verify_stream` on every `doc:` and `run:` stream after the CSV fixture runs through all six stages; live)

**Gates at merge:** four local gates; `sql` job green with `00`–`12` applied and passed count
raised; `docs/development.md` gains the CLI and the server-contract section.

## Traps

- `SKIP LOCKED` on `job` needs the lease **and** the status predicate; a leased-but-running job
  must not be reclaimed before `lease_expires_at`.
- Do not write the audit event and then the business row; the slice's order (business rows, then
  events, one commit) is the tested one, and `append_event` takes the tip under the advisory lock
  as its own statement.
- The ingest worker connects as `procurement_ingest`; every other stage as `procurement_app`. Mixing
  them is how a fan-out branch acquires a write it should not have (#8).
- `Stage` gains **no** member. A seventh value breaks `sql/08`'s CHECK and the runtime constraint
  that the reducer is `detect_conflicts`.
- `recorded_at` must be supplied by the caller from the stage's clock **once** per transaction, so
  every event in one commit shares a timestamp; the DEFAULT is gone after `sql/12`.

## Out of scope

A migration tool or version table for `sql/` (still a decision to take); logical replication of
the audit log to a WORM sink (Decision 9's superuser answer); horizontal scaling beyond one node.

---

*Clarifications Q-5 – Q-16 cited by this story were ratified on 2026-09-03 as D-19 – D-30 in [clarifications.md](../clarifications.md); the D-entries are the authority.*
