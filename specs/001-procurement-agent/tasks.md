# Tasks: parallel work breakdown

**Spec:** [spec.md](spec.md) · **Plan:** [plan.md](plan.md) · **Decisions:** [clarifications.md](clarifications.md) · **Analysis:** [analysis.md](analysis.md)

Structured for several teams working simultaneously. Read **Phase 0 first** — nothing
parallelises until the contracts are frozen, and the most common way a plan like this fails is
teams shipping seven incompatible versions of the same record.

> **Anti-pattern, named explicitly:** do not assign teams by pipeline stage *and* let them define
> their own interfaces. **The contracts are the deliverable of week one; the stages are the
> deliverable of week two onward.**

---

## Phase 0 — Contract freeze (BLOCKING, ~1 week, 1–2 people)

The only true serialisation point in the plan. Everyone else reviews; nobody implements against
an unfrozen contract.

| ID | Contract | Gates | Status |
|---|---|---|---|
| **C1** | Postgres schema: `document`, `chunk`, `claim`, `conflict`, `resolution`, `audit.event` | Every WP | **done** — all six, plus `job` and `conflict_candidate`, in `sql/00`–`08`; both T0.1 checks recorded live-verified in `sql/README.md`, and CI reapplies all nine files each run |
| **C2** | Claim/extraction record — Pydantic + JSON Schema, including `condition` per D-1 | B, E, G | **partial** — `condition` landed on `FieldClaim` and `CanonicalField`; per-category models still do not exist |
| **C3** | Provenance reference — `(document_id, page, span, extractor_version)` | A, B, D, F, G | **done** — all four elements on `SourceRef`, stamped by `FieldClaim.provenance()` |
| **C4** | Audit event envelope + `event_type` taxonomy + canonicalisation rule | All | **partial** — SQL half only (`audit.event`, the `event_type` CHECK, `payload_canonical`); no Python envelope and no canonicalisation library |
| **C5** | Conflict record + the five resolution action shapes | E, F, G | **done** — `ConflictQueueEntry`, `ResolutionAction` |
| **C6** | Canonical workbook projection — sorted-key JSON, floats via `repr()` | G | ☐ — `write_workbook()` raises `NotImplementedError` and no projection function exists |
| **C7** | Retrieval interface + ACL/labelling model | A, C | **partial** — RLS now enforces the one label the schema has (`access_restricted`); the model itself is still undecided, T0.4 unwritten |
| **C8** | Stage runner contract — job states, claim/lease semantics, idempotency key, **plus the append-only claim invariant below** | A, B, D, E, I | **partial** — the append-only invariant is enforced in both halves; `job` is the DDL's own proposal and `orchestrator.run` raises `NotImplementedError` |

Three of the eight are done, four are partial and one is untouched. Read the four partials
carefully rather than by their marker: **C4 and C8 each have a finished SQL half and an unstarted
Python half**, and they are the pair most likely to be mistaken for finished, because `sql/` is
the visible artifact and what is missing — WP-H's canonicalisation library, WP-I's runner — is a
file nobody has opened yet.

> **C8 invariant — workers propose, they do not commit.** Each extraction writes an **immutable
> claim row** keyed by `(document_id, field, extractor_version)`; the canonical value is a
> **projection over claims**, never an in-place update. Only the reducer takes a store write
> handle, and it calls `assert_no_autonomous_overwrite` internally.
>
> This is a *structural* property; the guard alone gives only a *value* property. It is a pure
> predicate over two fields — it takes no store handle, performs no write, and **cannot enforce
> that it is called**. It also deliberately permits record-over-record (inter-document conflict is
> the queue's job), which under concurrent writers is a lost update it passes silently. And it has
> no notion of ordering: two workers finishing in different orders yield different
> last-writer-wins outcomes, making the store itself non-deterministic — which defeats FR-OUT-06
> even though composition is a pure function of that store.
>
> With append-only claims there is no overwrite to guard. The unreachability test ("the write API
> is not reachable from worker context") becomes writable once C1 and C8 land, and should gate
> them.

**C1, C2, C3 and C7 are the expensive ones to change.** C1 and C3 have since landed, which makes
them *more* expensive rather than retiring the warning — there is now DDL applied to a live
cluster, a CI suite pinning its behaviour, and a test asserting C3's fourth element survives the
projection. C2 and C7 are the two still open, and they are where the week is best spent.

> ⚠️ **C4 must ship before any stage emits events.** Changing the hashed field set later
> invalidates every existing chain. WP-H ships its library first, even if thin. **The table
> shipped without the library.** `sql/07_audit_event.sql` defines the envelope, the `event_type`
> CHECK and `payload_canonical`, and its own comment says the taxonomy is that file's proposal
> because C4 was unfrozen; H.2's RFC 8785 canonicalisation does not exist in `src/`, so the bytes
> the `hash` column is computed over are still undefined. Nothing may emit an event until it is.

> ⚠️ **C7 is a single decision constraining two work packages at opposite ends of the pipeline**
> (labelling at ingest, enforcement at retrieval). This is the most common place this kind of
> plan breaks. **The enforcement mechanism has now landed ahead of the decision**: `sql/`
> applies `FORCE ROW LEVEL SECURITY` to seven tables, keyed on the single boolean
> `SourceDocument.access_restricted` and gated by an `app.allow_restricted` session GUC, and
> `sql/README.md` says in as many words that this is C7 "implemented at its frozen minimum, not
> guessed at in full". That is the right way to have built it, and it does not close T0.4 —
> anything beyond one boolean (labels, tenants, clearances, and who populates
> `VectorStorePort.search(allowed_document_ids=...)`) is still unchosen.

### Phase 0 tasks

- **T0.1** Write the Postgres DDL for C1, including `audit.event` with hash-chain columns and
  privilege separation per plan Decision 9. → verify: migrations apply cleanly; app role cannot
  `UPDATE`/`DELETE`/`TRUNCATE` `audit.event`.
- **T0.2** Add `condition` to `CanonicalField` and define the condition vocabulary per parameter
  family (D-1). → verify: the Sungrow SG350HX case (four apparent conflicts, zero real) resolves
  to zero conflicts in a fixture test.
- **T0.3** Define the per-field tolerance table from D-2 as data, not code. → verify: a table-driven
  test asserts nameplate Pmax at ±1 W does not merge adjacent 5 W bins.
- **T0.4** Decide the ACL/labelling model (C7). → verify: written decision in `clarifications.md`.
- **T0.5** Freeze the canonical workbook projection format (C6). → verify: a golden JSON fixture.
- **T0.6** Publish fixture sets for every contract (see below).

### The decoupling technique: frozen fixtures, not running code

Each team builds against **committed fixture files** matching the frozen schemas. WP-B ships
golden claim JSON; WP-E consumes it and ships golden conflict JSON; WP-F and WP-G consume that.
**Nobody waits on anybody's service.** The fixtures are the contract made executable, and they
double as the regression suite.

---

## Phase 1 — Parallel work packages

All nine run concurrently once Phase 0 lands.

### WP-A · Ingest & storage
**Depends:** C1, C3, C7

- **A.1** Content-signature router (FR-ING-01). Route by magic bytes, never extension.
- **A.2** Spreadsheet path — openpyxl/pandas direct, bypassing document parsing (plan Decision 4).
  Preserve sheet names, headers, merged cells, numeric typing (FR-ING-02).
- **A.3** Text-layer PDF path — Docling + TableFormer ACCURATE (FR-ING-03).
- **A.4** Scanned/image path — PaddleOCR-VL-1.6 on vLLM, bounding boxes retained (FR-ING-04).
  → **Trina datasheets are image-only PDFs with no text layer.** This is a tier-1 supplier, not
  an edge case. Use one as the acceptance fixture.
- **A.5** `.docx` path (FR-ING-05).
- **A.6** Per-page audit loop — zero characters, <10% of raw text count, or zero table cells on a
  detected table region → re-run on next engine. `PARSE_FAILED` regions are recorded, never
  dropped.
- **A.7** Dual-parse reconciliation on table-critical pages; emit cell-level disagreement as a
  **confidence feature**, not just a log line.
- **A.8** Document classification into the eight types (FR-ING-06).
- **A.9** Content hashing + stable IDs; re-ingest is a no-op (FR-ING-09, NFR-05). → verify: **AC-5**.
- **A.10** ACL labelling at ingest per C7.
- **A.11** Text normalisation per D-5 — NFKD, ligature folding, `–`→`-`, `℃`→`°C`, and
  **decimal-comma handling for IEC-sourced documents**. → verify: `10,5 kV` parses as 10.5, not
  105. This is the highest-risk lexical trap in the spec.

### WP-B · Extraction & confidence
**Depends:** C2, C3, C4

- **B.1** vLLM structured outputs (xgrammar) with `logprobs` enabled. → ⚠️ **`json_schema` mode,
  never Instructor's `TOOLS` mode** — tool calls do not emit logprobs, and using them throws away
  the entire confidence signal (plan Decision 7).
- **B.2** Per-category Pydantic extraction models from
  [contracts/canonical-parameters.md](contracts/canonical-parameters.md).
- **B.3** Unit normalisation per D-5. → ⚠️ **`%/°C` ≡ `%/K` requires NO conversion.** Hard-code as
  aliases; routing through a temperature converter applies +273.15 and silently destroys the value.
- **B.4** Condition extraction (D-1) — STC vs NOCT, `@30°C` vs `@40°C`, AC vs DC side, BOL vs EOL.
- **B.5** Domain plausibility rules as both feature and hard gate: `Voc > Vmp`, `Isc > Imp`,
  `Pmax ≈ Vmp × Imp ± 0.5%`, `PTC/STC ∈ [87%, 96%]`, `|γPmax| ∈ [0.15, 0.70]`, γPmax and βVoc
  negative, αIsc positive.
- **B.6** Cross-read disagreement — two structurally asymmetric extractions (field-guided and
  document-guided), scored for agreement.
- **B.7** Rule-based cold-start confidence score (D-3). **Do not implement self-reported
  confidence** (0.692 AUC, banned) **or self-consistency N=5** (0.744 AUC at 5× cost).
- **B.8** Log every human correction as a training label.
- **B.9** ⚠️ **Build the 30–50 document labelled gold set. This is task one of week one**, ahead of
  any optimisation. No public benchmark exists for this task (D-11); every accuracy figure in the
  plan is extrapolated. Seed deliberately with poor scans and unusual layouts.
- **B.10** Define `threshold_for(field_name)` — the tiered τ that WP-G consumes (see A-11).

### WP-C · Index, retrieval & access control
**Depends:** C1, C7

- **C.1** Structure-aware chunking (D/plan Decision 6). **Tables are never token-chunked.**
- **C.2** Triple table indexing — `table_full`, `table_row` (column names inlined per row),
  `table_summary`. → verify: "what is the Voc of module X" retrieves the right row.
- **C.3** Contextual retrieval — prepend document/section context before embedding, into
  `chunk.context_prefix`, citing `chunk_text` verbatim. ⚠️ **Built deterministically from the
  chunk's own metadata, never LLM-generated** (A-44, revising Decision 6):
  `"Jinko Solar JKM610N-66HL4M-V spec sheet - Electrical Characteristics (p. 4): "`. The prefix is
  baked into every embedding, so a later change of strategy is a full re-embed. `table_summary`
  (C.2) stays generated and is the only generated text in this path.
- **C.4** Qwen3-Embedding-4B at 1024 dims via MRL truncation + renormalisation.
- **C.5** Hybrid retrieval: dense + `tsvector` + `pg_trgm`, as **one SQL statement** in the
  pgvector adapter — one shared CTE carrying the metadata/ACL filter, three legs ranked over it at
  `budget // 3` each, union and dedup by `chunk_id` in SQL (A-43). **No RRF stage**; the reranker
  alone orders results. `VectorStorePort.search` takes `query_text` beside the vector — the lexical
  legs match text, and without it they have no interface to reach.
  → verify: `"JKM610N-66HL4M-V"` retrieves `"JKM610N 66HL4M V"`.
- **C.6** bge-reranker-v2-m3 over the whole candidate union (budget 50) → top-5–8. ⚠️ If the
  reranker is unavailable, fall back to **dense-score order** for that request — not to RRF.
- **C.7** `FORCE ROW LEVEL SECURITY`; app connects as non-owner, non-superuser. → verify: **AC-8**.
- **C.8** ⚠️ **No ANN index** (plan Decision 3a). Set `hnsw.iterative_scan = relaxed_order` in
  `postgresql.conf` anyway, so a future index isn't silently wrong.
- **C.9** ⚠️ **Regression test asserting `len(results) == k`** on a filtered query. Every pgvector
  filtered-search failure mode presents as a short result set — measured, a top-10 request
  returned 5 rows with no error, and 0 rows with an ACL array. **Nothing else catches this.**

### WP-D · Web enrichment
**Depends:** C2, C3, C4

- **D.1** Gap-triggered query planning (FR-WEB-01).
- **D.2** Tag every result `web_supplement` with URL, title, timestamp; log the query (FR-WEB-02).
- **D.3** Source-authority capture and ordering (FR-WEB-05).
- **D.4** ⚠️ Route every write through `assert_no_autonomous_overwrite`. → verify: **AC-2**.
- **D.5** CEC cross-check integration (D-8) — weekly pull of the four XLSX exports, surrogate ID,
  alias seeding from the `Notes` column. → ⚠️ CEC is **not** an authority for utility-scale BESS.
  → ⚠️ Do **not** use pvlib's bundled CEC data: frozen at 2019, **zero modules ≥600 W** (D-8a).

### WP-E · Conflict detection
**Depends:** C2, C5 · *Most parallelisable — a pure function, fully fixture-testable.*

- **E.1** `values_conflict()` per the D-2 three-kind model with the rounding floor.
- **E.2** Condition-matching gate — **mismatched conditions are not a conflict, they are not a
  comparison** (D-1). This gate runs before any tolerance check.
- **E.3** The five conflict classes (FR-HITL-01).
- **E.3a** ⚠️ **If any ensemble is ever used here, aggregate by UNION, never by vote.** Stage 3's
  exit threshold is *100% of injected conflicts surfaced*. A 2-of-3 vote that suppresses a real
  conflict is a spec violation, not a false positive saved. Written down now because the verifier
  pattern is a natural thing to reach for later.
- **E.4** Identity resolution per D-4 — four stages, `(manufacturer, token)`-keyed suffix rules,
  electrical corroboration. → ⚠️ verify with the **Trina split-entity case**: bins 635–725 W under
  `Trina Solar Co.,Ltd`, bins 730/735/740 under `Trina Solar`. Looking up
  (`Trina Solar`, `TSM-700NEG21C.20`) must not return empty.
- **E.5** Generated conflict explanations (FR-HITL-03).
- **E.6** Transformer-specific gates per D-6: standards-regime detection (IEEE vs IEC) before any
  comparison of MVA, %Z or losses; `Dyn1` vs `Dyn11` treated as **incompatible, not equivalent**.
- **E.7** BESS boundary gate per D-7 — RTE and energy comparisons across differing boundaries are
  *"requires boundary normalisation"*, not a numeric conflict.

### WP-F · HITL queue service & review UI
**Depends:** C5, C8

- **F.1** Conflict table with lease-based claiming (`FOR UPDATE SKIP LOCKED`, 15-min lease).
- **F.2** The five resolution actions. `keep_sor` writes an explicit resolution — *not* a no-op, so
  "we looked and chose the contract value" stays distinguishable from "nobody looked".
- **F.3** `request_more_web_search` reopen cap at 3, then force a terminal decision.
- **F.4** Lease sweeper. **Conflicts themselves never expire** (D-12c) — they age, and age is a
  reported metric.
- **F.5** Review UI. ⚠️ **You will build this regardless** — no generic approval page serves
  provenance-carrying extracted-value review. This removes the "free UI" argument for every
  orchestration framework considered.
- **F.6** Implement D-10: Excel is read-only output; resolution happens in the application.

### WP-G · Workbook composition & determinism
**Depends:** C6 · *Fully decoupled — build against the golden projection from day one.*

- **G.1** Canonical sorted-key JSON projection; floats via `repr()`. **This is the hashed artifact
  of record**, not the xlsx — `%.16g` maps `0.1+0.2` and `0.3` to identical bytes, so a workbook
  hash cannot distinguish two genuinely different stored numbers. → **AC-7 (a)** now says this in
  spec.md rather than only here ([A-46](analysis.md)).
- **G.1a** The **generated-on timestamp is store-derived, never `now()`** (FR-OUT-06): the
  high-water mark of `document.ingested_at`, `claim.extracted_at` and `resolution.resolved_at`
  over the rows composition reads. It is a *projection* field, so **C6 freezes its derivation**
  (T0.5) and both layers inherit it. A wall-clock stamp violates AC-7 by construction.
- **G.2** All 13 tabs (FR-OUT-02). → verify: **AC-3**.
- **G.3** Hidden parallel state columns for provenance. → ⚠️ **no blank column between value and
  state blocks**, and `auto_filter.ref` **must span the hidden columns**. Both fail silently on
  first sort. Assert both in the generator.
- **G.4** Three orthogonal visual channels — fill=origin, font=confidence, border=conflict
  (plan Decision 8b). → verify: greyscale separation and WCAG AA contrast.
- **G.5** Deterministic render — `workbook.save()` followed by
  `services/output.normalize_archive()`, which is the **single normalization point**: zip
  normalisation at epoch 1980-01-01 **12:00**, `[Content_Types].xml` first, pinned compression,
  fixed `create_system`/`external_attr`, *and* the `docProps/core.xml` and `docProps/app.xml`
  rewrites that undo `save_workbook`'s unconditional `modified = now()` re-stamp and its embedded
  library version. → ⚠️ `ZipFile(compresslevel=)` is **silently ignored** with a hand-built
  `ZipInfo`; set `zi._compresslevel`. → verify: **AC-7 (b)**, with `sleep(1.1)` between the two
  runs; **AC-7 (a)** is verified on the G.1 projection and needs no sleep.
  → **The `ExcelWriter`-direct requirement is deleted** ([A-46](analysis.md)): the normalizer must
  rewrite the whole ZIP container regardless — mtimes, member order, compression, platform bits —
  so the `core.xml` fix rides along free, while `ExcelWriter`-direct is a second mechanism doing
  half the same job that would *still* need the container pass after it. Its five normalizations
  are essential and none of them is being removed.
- **G.6** ⚠️ **GATING: open the generated workbook in real desktop Excel and LibreOffice.** The
  determinism recipe was validated only by openpyxl round-trip and OPC structural checks. Test
  `[Content_Types].xml`-first ordering and the 1980 timestamps before this ships. The verified
  fallback for ordering is A-9's other stream — preserve `namelist()` order
  ([analysis.md A-9](analysis.md)); A-9's midnight epoch is *not* a free swap, since DOS
  timestamps are local and midnight underflows the 1980 floor in negative UTC offsets, so a
  timestamp failure needs a new value rather than that one. → Under the amended AC-7 this gates
  the **renderer** layer only: taking a fallback is a recorded golden-hash refresh of AC-7 (b),
  not a failure of the criterion.
- **G.7** Conflicts and Sources tab layouts with bidirectional `MATCH`-based navigation.
- **G.8** Completeness manifest listing every unresolved conflict.

### WP-H · Audit log
**Depends:** C1, C4 · *Ships a library the other packages call. Must land first.*

- **H.1** DDL + privilege separation (`NOLOGIN` owner role, app gets `INSERT, SELECT` only).
- **H.2** RFC 8785 canonicalisation **in Python, not SQL** — `jsonb` normalises key order but
  preserves numeric formatting, so `1.0` and `1.00` stay textually distinct.
- **H.3** Per-document hash chaining (`stream = 'doc:1234'`).
- **H.4** ⚠️ **Advisory lock as its own statement before the INSERT** — a lock *inside* the trigger
  does not work, because the statement snapshot is taken before the trigger acquires it. Measured:
  8 concurrent writers produced **42 silent forks** without this. Add `UNIQUE(stream, prev_hash)`
  so any remaining fork is loud.
- **H.5** Chain verification CLI.
- **H.6** `BEFORE TRUNCATE` statement-level trigger as a secondary tripwire — **not** the boundary.
  Document that `session_replication_role='replica'` bypasses triggers entirely and leaves no DDL
  trace.

### WP-I · Runner & stage driver
**Depends:** C8, and on `document_content_hash_unique` (`sql/02_document.sql:50`) — see I.1a

> **Rescoped 2026-08-04 — [A-45](analysis.md), plan Decision 1a.** This package previously
> specified a leased job queue: a `FOR UPDATE SKIP LOCKED` worker loop, 15-minute leases plus a
> sweeper, backoff scheduling, poison quarantine as a job-row lifecycle, and
> `idempotency_key UNIQUE` as a second idempotency mechanism. Decision 2 detached the human gate,
> the store is already idempotent by natural key, and concurrency already lives in
> `Settings.max_concurrent_parse` / `max_concurrent_llm` — so the queue's remaining unique
> purchase was crash-resume that skips completed documents, on a single-node tool run
> occasionally over a corpus NFR-06 caps at hundreds. Leases, sweeper and backoff are **deferred
> until a second worker process actually exists**; the `job` columns stay in the DDL so adopting
> them later is a runner change, not a migration.
>
> ⚠️ **This does not touch WP-F.** F.1's and F.4's conflict-claim leases are a different table
> with genuine multi-human contention and are unaffected — see plan Decision 1a's closing
> paragraph.

- **I.1** Single-process stage driver: for each stage, map over its units of work with the two
  configured pools — `ProcessPoolExecutor` at `max_concurrent_parse` for parse/OCR (CPU-bound),
  `ThreadPoolExecutor` at `max_concurrent_llm` for extraction calls. No worker fleet, no lease, no
  scheduler. `orchestrator.run` is the entry point. The `job` table is retained as a **progress
  and quarantine ledger the driver writes** — it answers "what has been done, what failed, and
  why" for a re-run and for I.5 — not a queue workers contend on. Nothing SELECTs it
  `FOR UPDATE`.
- **I.1a** ⚠️ **Precondition, not a nicety.** "Crash recovery = re-run the batch" is sound only
  because `document_content_hash_unique` + `INSERT … ON CONFLICT (content_hash) DO NOTHING` makes
  the *database* refuse a duplicate. AC-5/NFR-05 require that constraint anyway; WP-I **consumes**
  it. If it is ever relaxed, the driver becomes unsound before AC-5 visibly fails.
- **I.2** Stage idempotency from the store's natural keys — `document.content_hash`,
  append-only claims under `claim_natural_key` (`sql/04_claim.sql:94-96`), composition a pure
  function of the store (FR-OUT-06). **Every stage must still be independently idempotent**: that
  requirement is unchanged by the rescope, because a driver that re-runs needs it exactly as much
  as at-least-once delivery did. In-stage retry for transient faults stays; the *scheduled* retry
  with persisted backoff goes.
- **I.3** Compose-time gate: query for unresolved conflicts above severity, overridable with a
  recorded `--accept-incomplete` decision (plan Decision 2). **No blocking interrupt.**
  → `orchestrator.compose_gate_blocks` / `blocking_conflicts` already implement the predicate.
- **I.4** Poison handling as a recorded **per-document status**, not a job-row lifecycle: a
  document that fails a stage after its in-stage retries is written to the `job` ledger as
  `status = 'quarantined'` with `last_error`, and the batch continues. This is the job-table
  expression of plan Decision 4's tier-3 rule — a page failing every engine is recorded with its
  page reference, never silently dropped.
- **I.5** Observability; verify NFR-06 and NFR-07 against a real corpus. → also the measurement
  that would justify revisiting Decision 1a: if a crashed batch's re-run cost ever stops being
  acceptable, the deferred lease columns are already in the schema.

**IDs are unchanged.** I.1–I.5 keep their numbers and their subjects; I.1a is added rather than
renumbering, because `sql/08_job.sql`, `sql/README.md`, `orchestrator/__init__.py` and
`tests/test_sql_schema.py` all cite these IDs, and [A-36](analysis.md) is the register's standing
lesson about what renumbering a cited ID costs.

---

## Genuine sequential dependencies

These cannot be parallelised away. Plan for them rather than discovering them.

1. **Phase 0 precedes all implementation.** The only true serialisation point.
2. **C7 (ACL model) blocks both WP-A and WP-C** — opposite ends of the pipeline, one decision.
3. **WP-H ships its library before any stage emits events.** Changing the hashed field set later
   invalidates every existing chain.
4. **Real extraction output is needed to *tune* conflict detection, not to *build* it.** WP-E
   builds against fixtures on day one; only its thresholds wait on WP-B. **Sequence the tuning,
   not the build.**
5. **Real conflicts are needed to *validate* the review UI**, same shape. WP-F builds against
   synthetic conflicts; usability review waits on WP-E.
6. **The determinism golden hash can only be locked once the workbook's shape settles.** WP-G's
   normalisation layer is buildable immediately; G.6 is the gate.

---

## Acceptance criteria ownership

| AC | Owner | Status |
|---|---|---|
| AC-1 scanned spec sheet → fields with provenance, low confidence to review | WP-A + WP-B | ☐ needs corpus |
| AC-2 web contradiction raises conflict, record unchanged | WP-D + WP-E | **passing** |
| AC-3 all 13 tabs with conditional formatting | WP-G | partial |
| AC-4 every cell resolves to a source | WP-G | **passing** (schema level) |
| AC-5 re-ingest creates no duplicates | WP-A | ☐ |
| AC-6 TRD against correct voltage-class limit; tax status per supplier | WP-B + WP-G | ☐ |
| AC-7 byte-identical regeneration | WP-G | ☐ gated on G.6 |
| AC-8 unclear user cannot influence retrieved results | WP-C | ☐ |

---

## Suggested team allocation

| Team | Packages | Rationale |
|---|---|---|
| 1 | Phase 0, then WP-H, WP-I | Owns the contracts, so owns the substrate everyone builds on |
| 2 | WP-A | Largest surface; parser router is core IP |
| 3 | WP-B | Deepest domain work; owns the gold set |
| 4 | WP-C | Self-contained; owns the pgvector findings |
| 5 | WP-D + WP-E | Both pure-ish functions over claims; share the tolerance table |
| 6 | WP-F + WP-G | Both consume the canonical projection; share the reviewer's mental model |
