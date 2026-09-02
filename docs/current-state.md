# Current state

This audit describes the repository at the head of branch
`claude/repo-status-docs-verify-eyma9p` on 2026-09-02, which is `main` at `a119d19` plus the
implementation review below and the three decisions it forced. It was first written against `ee1503d`; the [database schema](#database-schema),
[persistence](#persistence), [security](#security) and
[contract status](#contracts-are-only-partially-frozen) sections were rewritten when the Phase 0
substrate landed, and the contract section was rewritten again when D-13, D-14 and D-15 were
adopted on 2026-08-07. It answers the practical question a new contributor has first: what can
the repository do today?

The local verification baseline is 524 passing tests and 24 skipped, a clean Ruff check, a clean
`ruff format --check`, and a clean strict-mypy check across `src/` and `tests/`. Every one of the
24 skips is in `tests/test_sql_behaviour.py`, which needs `PROCUREMENT_TEST_DSN` pointed at a
disposable PostgreSQL; CI supplies one, so they are skipped locally and run there. The baseline
was 229 passing when this audit was first written, then 470, then 481 before the implementation
review added 19 and the three decisions it forced added 24 more.

> **What the 2026-08-07 decisions did and did not change.** They closed the *decision* half of
> C4, C6 and C7. No implementation number moved: contracts remain 3 done / 4 partial / 1
> untouched, requirements 10 enforced / 23 partial / 17 declared / 6 open, and the same ten
> `NotImplementedError` stubs stand. The decisions were the binding constraint, so this is
> progress — it is just not implementation. See
> [phase-1-execution.md](../specs/001-procurement-agent/phase-1-execution.md).

> **What the 2026-09-02 implementation review changed, and did not.** The first pass over `src/`
> since the policy core landed found ten defects, all reproduced by running the code
> ([analysis.md Round 7](../specs/001-procurement-agent/analysis.md)). **All ten are now fixed.**
> Seven were patches; three needed a contract choice and were adopted the same day, on the
> instruction to fix every verified defect, as [D-16, D-17 and
> D-18](../specs/001-procurement-agent/clarifications.md):
>
> - **D-16 (was A-51, Critical).** A reviewer's decision is a `human:` claim carrying its
>   `Resolution`; the reducer ranks it first, returns RESOLVED, and copies the decision onto the
>   stored field. The idempotent re-run that used to erase a decision is now the regression
>   test. See [Source authority](#source-authority).
> - **D-17 (was A-53, High).** `ToleranceRule.SET_EQUAL` and a row for every `list[str]` key,
>   so a reordered certification list is no longer a CRITICAL conflict.
> - **D-18 (was A-56).** RESOLVED is now derived from `resolution` rather than stored, so a
>   resolved field with no decision has no representation; five pydantic overrides are gone and
>   the wire shape is unchanged. Adopted in full on the maintainer's instruction.
>
> **No status word in this document moved because of it.** Nothing new is implemented end to
> end and nothing was withdrawn; the counts below are unchanged.

## Executive assessment

The project is a well-researched, test-heavy policy core inside an application scaffold.
Its strongest work is the domain reasoning around provenance, conditions, tolerance,
determinism, and human authority. It is not yet a usable procurement tool because no
document can travel through the complete pipeline.

The repository should currently be evaluated as:

- a reference implementation of several procurement comparison invariants;
- a detailed implementation specification for a larger system; and
- a starting point for fixture-driven vertical slices.

It should not yet be evaluated as:

- an installable end-user product;
- a document ingestion or RAG service; or
- a secure store for confidential procurement data.

It *is* an open-source release: Apache-2.0 was adopted in `a2fe390` on 2026-08-07 and merged in
`3b4e271` the next day. This document said otherwise for the following three and a half weeks,
in two places, while `pyproject.toml`, `LICENSE`, `NOTICE` and the README all said the opposite —
see [Public repository, licensed](#public-repository-licensed).

## Implemented and tested

### Canonical domain models

Pydantic models cover source documents, component instances, canonical fields, structured
conditions, declared tolerance bands, conflict candidates, queue entries, and resolutions.
Closed enums cover component categories, document types, source tiers, conflict classes,
conditions, severity, resolution actions, workbook tabs, and cell flags.

Important validators already reject unsourced values, invalid confidence values,
non-finite conditions and bands, and malformed declared bands. A “resolved” field without a
resolution is not rejected but *unrepresentable*: RESOLVED derives from the decision (D-18).

### Deterministic identity and ordering

`ComponentInstance.ordering_key()`, condition grouping keys, candidate ordering, and conflict
pair generation are deterministic under input permutations. This is necessary for
byte-identical output later.

### Condition-aware conflict policy

The current implementation:

- compares every compatible unordered candidate pair;
- avoids treating a non-transitive relation as a partition;
- rejects incompatible conditions as a programming error;
- recognizes missing values as gaps rather than conflicts;
- detects unit mismatches before numeric tolerance;
- preserves standard editions as temporal conflicts;
- normalizes text without fuzzy-matching compliance claims;
- applies per-field exact, absolute, relative, one-sided, declared-band and set-equality
  rules (D-17); and
- honors the precision of the source’s printed value.

### Source authority

`assert_no_autonomous_overwrite()` prevents a web supplement from replacing a populated
system-of-record field. This is a useful safety predicate, although the future store must
make bypassing it structurally impossible.

**The other half of source authority — a human's decision — is now preserved through the
reducer** ([D-16](../specs/001-procurement-agent/clarifications.md), 2026-09-02). Until then
`services.claims.project()` never read or wrote `resolution`, `_preferred()` had no human tier,
and `_status_for()` reopened any group holding more than one distinct answer, so re-committing
the identical claim set for a resolved field stored `OPEN` / `resolution=None` (A-51). A
reviewer's decision is now a `human:` claim carrying its `Resolution`, enforced by the claim's
own validator in both directions; it outranks every tier, settles its group, and a later
extraction does not reopen it — reopening is a human action. Twelve tests in
`tests/test_propose_commit.py` pin this, led by `test_an_idempotent_rerun_keeps_the_decision`.
`sql/04_claim.sql` does not yet carry the column that record needs; the Python is ahead of the
DDL, and that migration is WP-F's.

### Composition policy

`blocking_conflicts()` and `compose_gate_blocks()` implement the compose-time severity
decision. Only unresolved conflicts strictly above the threshold block. The threshold cannot
be configured to disable the gate.

### Output primitives

`flags_for()` computes missing-data, web-supplemented, low-confidence, and unresolved states.
`expected_tabs()` exposes the fixed 13-tab order. `normalize_archive()` makes an already
created XLSX archive deterministic across time and platforms.

`expected_tabs()` had no test when this audit was first written, which put it under this
heading falsely. Truncating its body to `list(WorkbookTab)[:3]` left all 228 tests green, so a
writer emitting three tabs would have contradicted nothing in the suite. It is now pinned
against the thirteen literal tab names by `test_expected_tabs_returns_all_thirteen_in_order`
(`tests/test_schema_invariants.py`) — the test that takes the count from 228 to 229. Truncating
or reordering the helper now fails. The two tests above it in that file check the `WorkbookTab`
enum, which is a different thing from the helper that returns it.

### Database schema

Nine numbered DDL files in `sql/` create `document`, `chunk`, `claim`, `conflict`,
`conflict_candidate`, `resolution`, `job` and `audit.event`. They carry
`FORCE ROW LEVEL SECURITY` on the seven tables that hold document content, owner/application
privilege separation across four roles, append-only triggers on `claim`, `resolution` and
`audit.event`, and `audit.event`'s per-document hash chain with its fork, parent-exists and
loop constraints.

Two suites cover them, and the split is the point. `tests/test_sql_schema.py` asserts the DDL
*text* and needs no server. `tests/test_sql_behaviour.py` re-runs the attacks each defence
descends from against a real PostgreSQL — a role declassifying rows it cannot read, a chunk not
inheriting its document's restriction, a `TRUNCATE` taking the decision log with it, a chain that
was constrained but not walkable — and the `sql` job in `.github/workflows/ci.yml` supplies one
from a `pgvector/pgvector` container. Those are the 24 tests that skip locally.

## Declared but not operational

### Integration ports

Six Protocol interfaces define the intended parser, OCR, embedder, vector-store, reranker,
and LLM boundaries. No concrete adapter exists and the Protocols are not currently covered
by adapter contract tests.

### Service entry points

The ingestion, indexing, retrieval, web-search, workbook-writing, and runner entry points
raise `NotImplementedError`. Their signatures communicate design intent but cannot be used
as a pipeline.

### Persistence

The tables exist (see [Database schema](#database-schema)); nothing in Python reaches them.
There is no repository layer, no connection or session management, and no store adapter, so no
code path in `src/` reads or writes a row. `psycopg` is an optional `store` extra that only the
live-schema test suite imports.

`sql/` is also not a migration tool. It is a numbered, forward-only file set applied by `psql` in
lexical order, with no version tracking: re-running `02`–`08` against a database that already has
the tables is *expected* to fail with `relation already exists` rather than no-op. That is
deliberate and documented in `sql/README.md`; it is not the same thing as having migrations, and
a project that wants rollback or a schema-version table still has to choose one.

### Human review

The conflict and resolution data shapes exist. There is no queue lease service, reviewer
API, authentication, or UI.

### Security

The design calls for access labels, retrieval-time filtering, forced PostgreSQL RLS, a
non-owner application role, and self-hosted or enterprise inference. Two of the five now hold at
the database: `FORCE ROW LEVEL SECURITY` is applied to all seven content-bearing tables, and
`procurement_app` is a non-owner, non-superuser `LOGIN` role with `NOBYPASSRLS` re-asserted on
every apply. Both are exercised against a live server in CI.

The other three do not. Access *labels* are one boolean —
`SourceDocument.access_restricted`, derived through `public.document_is_restricted()` and gated
by an `app.allow_restricted` session GUC the caller must `SET LOCAL` — which is C7's minimum, not
C7's model. Retrieval-time filtering has no code, because no retrieval path exists to filter.
Inference hosting is a deployment choice nothing in the repository makes.

The distinction that matters: a defence enforced in the schema is only reached by a caller that
connects, and no application code connects yet.

## Acceptance status

The most useful summary is the acceptance boundary. There are eight acceptance criteria, listed
at [`spec.md` § Acceptance criteria](../specs/001-procurement-agent/spec.md); this table carries
one row per ID, and its status words are the ones
[requirements-traceability.md](requirements-traceability.md) defines — **enforced** means a test
covers the behaviour, **partial** means some of the cited artifact is tested, **declared** means
a signature exists, **open** means there is no home in the code yet.

| ID | Criterion | What holds today | Status |
|---|---|---|---|
| AC-1 | Scanned spec sheet yields sourced fields; low confidence routes to review | Nothing. No document reaches an extractor | open |
| AC-2 | A web value contradicting a record value raises a conflict, record unchanged | `assert_no_autonomous_overwrite()` at unit level. Nothing drives a contradiction from ingestion through to a queue entry | partial |
| AC-3 | All 13 tabs, with conditional formatting for the four cell states | Tab identity and order (`expected_tabs()`), and the four states (`flags_for()`). No workbook is generated, so no formatting is applied | partial |
| AC-4 | Every output cell resolves to a source | The `SourceRef` validator, at model level | enforced |
| AC-5 | Re-ingesting an unchanged document creates no duplicates | `sql/02_document.sql`'s `UNIQUE (content_hash)`, exercised against a live server by `test_a_duplicate_content_hash_is_refused`. The store half only: `services/ingestion.ingest`, the thing that would re-ingest, raises `NotImplementedError` | partial |
| AC-6 | Inverter TRD against the IEEE 2800 limit; tax status per supplier | Nothing | open |
| AC-7 | Two generations from an unchanged store are byte-identical | `normalize_archive()`, at archive level only. Without a writer there is no complete workbook to regenerate, and the desktop Excel/LibreOffice gate is unrun | partial |
| AC-8 | An uncleared user cannot influence any retrieved result | RLS on seven tables with `FORCE`, an entitlement GUC and a separate ingest role, live-tested by eight assertions in `tests/test_sql_behaviour.py` — the load-bearing one is `test_claims_do_not_leak_a_restricted_documents_values`. `VectorStorePort.search(allowed_document_ids=...)` only declares its parameter, and no test imports `ports` | partial |

Read that table as three groups, because they fail differently. AC-4 is genuinely covered.
AC-2, AC-3, AC-5, AC-7 and AC-8 each have a tested *half* and an unbuilt one — that split is the
pattern to distrust in any status claim about this repository, because the tested half is the
one that gets quoted. AC-5 and AC-8 are the variants worth naming separately: for both, the
tested half is the *store* rather than a policy function, so the thing under test is a live
database defence and the missing half is the caller. Only AC-1 and AC-6 have no test at all.

> **Corrected 2026-08-05 (AC-5).** This row read "Nothing. `content_hash` exists but carries no
> uniqueness constraint / **open**". The constraint had landed in `e7da9ad`, an ancestor of this
> audit's own stated baseline, so the row was wrong when written rather than merely stale — and
> [requirements-traceability.md](requirements-traceability.md) already carried the correct
> `partial`. Two status documents disagreeing about one criterion is worse than either being
> wrong alone, because the disagreement is invisible unless someone reads both.

> **Corrected 2026-09-02 (AC-8), and it is the same correction again.** This row read
> "`VectorStorePort.search(allowed_document_ids=...)` declares the parameter. No adapter, no
> enforcement, no test imports `ports` / **declared**", and the paragraph above it counted AC-8
> among the criteria with "no test at all". Both were false in the same direction as the AC-5 row
> above: `requirements-traceability.md` already carried `partial`, citing eight live assertions
> and naming `test_claims_do_not_leak_a_restricted_documents_values` as the one that fails when
> and only when `claim`'s confidentiality policy is widened to `USING (true)`.
>
> The AC-5 note called a disagreement between two status documents "worse than either being
> wrong alone". It then stood four weeks beside a second instance of itself, in the same table,
> because the correction was applied to the row it was about rather than to the table it was
> about. The counts in this document's own header — 10 enforced / 23 partial / 17 declared /
> 6 open — are computed from the traceability table, so they were right while this row was wrong;
> that is what let the disagreement hide.

See [requirements-traceability.md](requirements-traceability.md) for the requirement-level
mapping behind these.

## Design and documentation debt

### Public repository, licensed

**Settled, and this section was wrong about it for three and a half weeks.** `pyproject.toml`
declares `license = "Apache-2.0"` with `license-files = ["LICENSE", "NOTICE"]`, both files
exist, and [README.md](../README.md#license) records why Apache-2.0 rather than MIT: the express
patent grant in section 3.

The stale text read "`pyproject.toml` declares `UNLICENSED` and no `LICENSE` file exists" and
called it "the largest non-code blocker to outside adoption". It is recorded rather than quietly
deleted because of *how* it survived: this file was edited twice after the licence landed
(`79f0084`, `f18eb59`), both times to reconcile it with the 2026-08-07 decisions, and both times
the sweep covered the sections those decisions named. The licence was not one of them. That is
the same failure `phase-1-execution.md` records for Track 0 — **scoping a reconciliation by
section or filename rather than by meaning** — on its third occurrence.

### No contributor governance

Before a broad public launch, maintainers should still add:

- a code of conduct;
- a security reporting policy;
- an issue and pull-request template;
- a release and compatibility policy; and
- a decision on DCO versus CLA for external contributions.

The licence is no longer on this list. Nothing else on it exists: `.github/` holds
`workflows/ci.yml` and nothing else, and there is no `CODE_OF_CONDUCT.md`, `SECURITY.md` or
template directory. This documentation adds a contribution workflow but intentionally does not
invent legal or governance choices for the maintainers.

### Specification drift

**Closed, and this paragraph outlived it.** The plan and the code disagreed on lexical retrieval
in both directions at once. Plan Decision 3b chooses PostgreSQL `tsvector` and `pg_trgm`;
`services/retrieval` and `services/indexing` still advertised the TRS's BM25 (and
`services/indexing`, an HNSW/IVF index that Decision 3a also reverses), while `ports` described
the embedding model's sparse output, which is a Decision 5 contingency rather than Decision 3b's
choice. All three docstrings were corrected, and **`spec.md`'s own deviation note was corrected
too** — in `d2dd02d` on 2026-08-04, before this paragraph's own stated baseline. It now names
`tsvector`/GIN plus `pg_trgm` fused with RRF, which is what
[architecture.md](architecture.md#the-fr-rag-03-lexical-drift-and-exactly-what-is-left-of-it)
and [A-40](../specs/001-procurement-agent/analysis.md) both record as fixed. The sentence that
stood here — "the remaining mismatch is inside `spec.md`'s own deviation note, which needs a
spec edit" — described work already done, which is the drift-report's own version of the defect
it reports. What remains is only the deliberate part: FR-RAG-03's requirement body still says
"vector + BM25", because A-24 restored the TRS wording on purpose and marked the reversal
inline rather than paraphrasing a `shall` away.

The traceability record also contains historical statuses that must be kept in sync as
features land.

An implementation should cite the controlling decision and register the deviation in the same
pull request. The register is
[`specs/001-procurement-agent/analysis.md`](../specs/001-procurement-agent/analysis.md) — a
numbered `A-n` finding list with a status column, not a separate file. FR-RAG-03's own reversal
is filed there as A-24.

### Contracts are only partially frozen

[`tasks.md` Phase 0](../specs/001-procurement-agent/tasks.md) enumerates eight shared contracts,
C1–C8. **Five of the eight are unfinished**: C1, C3 and C5 are done, four are partial, and one is
untouched. The distinction matters — a *partial* contract is the more dangerous kind, because
there is enough of it to build against and not enough to be stable:

| ID | Contract | Status in `tasks.md` |
|---|---|---|
| C1 | Postgres schema (`document`, `chunk`, `claim`, `conflict`, `resolution`, `audit.event`) | **done** — all six, plus `job` and `conflict_candidate`, in `sql/00`–`08` |
| C2 | Claim/extraction record | partial — `condition` has landed; per-category models still do not exist |
| C3 | Provenance reference `(document_id, page, span, extractor_version)` | **done** — all four on `SourceRef`; `span` is the `section` field |
| C4 | Audit event envelope and `event_type` taxonomy | partial — decision closed by **D-13** (2026-08-07); SQL half only, no Python envelope or canonicalisation *code* library |
| C5 | Conflict record and the five resolution action shapes | **done** |
| C6 | Canonical workbook projection | ☐ not started — format frozen by **D-14** (2026-08-07); no projection function, no golden fixture |
| C7 | Retrieval interface and ACL/labelling model | partial — RLS enforces the one label that exists; **D-15** (2026-08-07) adopts that model *provisionally*, contingent on two outstanding facts |
| C8 | Stage runner contract, including the append-only claim invariant | partial — append-only enforced; job states are the DDL's own proposal, no runner |

The evidence behind each, since “done” is the word this repository has most often been wrong
about:

- **C1** — `sql/02`–`08` create every table C1 names. Both of T0.1's checks were run against a
  live cluster and are recorded in `sql/README.md`. The first — the files apply cleanly — is now
  continuous: `test_sql_behaviour.py`'s `schema` fixture reapplies all nine into a freshly
  dropped database on every CI run, so a file that stops applying fails the job. The second —
  `procurement_app` cannot `UPDATE`, `DELETE` or `TRUNCATE` `audit.event` — is guarded rather
  than re-run: `test_sql_schema.py` asserts the narrow grant, and `test_truncate_is_refused`
  exercises the tripwire as the owner, not as `procurement_app`. The absence of Alembic is not a
  gap in C1: C1 asks for the schema, and T0.1 asks that migrations apply, which they do.
- **C3** — `SourceRef` carries `document_id`, `page`, `section` (C3's span) and
  `extractor_version`; `FieldClaim.provenance()` stamps the fourth on, and
  `test_the_extractor_version_reaches_the_store` fails if the projection drops it again.
- **C2** — `condition` is on `FieldClaim`, on `CanonicalField` and on the `claim` table, and
  `test_the_sungrow_trio_raises_no_conflict` covers D-1's worked example. What is left is
  per-category models: `ComponentInstance.fields` is a generic
  `dict[str, list[CanonicalField]]`, and `schema/component.py`'s own docstring says the TRS
  section 7 field sets “are not yet enumerated here”.
- **C4** — `sql/07_audit_event.sql` has the envelope columns, the seven-value `event_type`
  CHECK and `payload_canonical`. Nothing in `src/` does. The file itself records that the
  taxonomy is “this file's own proposal”. **D-13 (2026-08-07) closed the decision half**: the
  scheme is RFC 8785, the preimage is one JCS object carrying `"v": 1`, and the digest is
  SHA-256 — so the `hash` column now has a defined input. The taxonomy is version 1 with
  additive-only amendment rather than frozen. What is missing is code, not a decision: WP-H's
  envelope and canonicalisation library are unwritten, so nothing emits an event.
- **C7** — argued at length in `tasks.md`. RLS on seven tables, an `app.allow_restricted`
  entitlement, a `procurement_ingest` write role and a chunk-inheritance trigger are real
  enforcement, and they enforce exactly one boolean. `sql/README.md` states that this is C7 “at
  its frozen minimum, not guessed at in full”. **T0.4's deliverable now exists as D-15
  (2026-08-07)**, which ratifies that minimum *provisionally* — the model is adopted, but it is
  contingent on two outstanding facts about NDA scope and evaluator conflicts, which are facts to
  look up rather than preferences to choose.
- **C8** — `sql/04_claim.sql` refuses `UPDATE`/`DELETE`/`TRUNCATE` on `claim` and
  `services/claims` projects canonical values over appended claims, so the append-only invariant
  holds in both halves. The rest does not: `job` carries the five statuses, the lease pair and a
  `UNIQUE` idempotency key, but its own `COMMENT` says it is “this file's own C8-consistent
  design, not a mapping of an existing frozen type”, there is no Pydantic model for it, and
  `orchestrator.run()` raises `NotImplementedError`.
- **C6** — **format frozen by D-14 (2026-08-07)**, nothing built. `write_workbook()` still
  raises `NotImplementedError` and no *workbook* projection function exists. Note the wording:
  `services.claims.project` does exist, but it is C8's claims-to-canonical-fields projection, a
  different thing from C6's whole-store-to-hashed-artifact projection. The T0.5 golden fixture
  does not exist either.

An earlier version of this section named only five contracts and omitted C2 and C3, on the
reasoning that `schema/` and `SourceRef` already existed and so were the ones most likely to be
mistaken for finished. **C4 and C8 are now that pair**, for the mirror-image reason: each has a
finished, live-verified SQL half and an unstarted Python half, and `sql/` is the visible artifact.
It is the same split this document already flags in the acceptance table — a tested half that
gets quoted and an unbuilt half that does not.

These are shared boundaries. Building multiple adapters before freezing them would create
incompatible records and rework.

### No representative corpus

The plan requires a 30–50 document labeled set, deliberately including poor scans and unusual
layouts. Without it, extraction accuracy, review thresholds, retrieval recall, and throughput
claims cannot be validated.

## Recommended delivery sequence

The fastest path to a useful contributor demo is not to implement every service in parallel.
Build one tested vertical slice:

1. settle the remaining contributor-governance choices (the licence is done — Apache-2.0);
2. finish the five contracts still open above — C2, C4, C6, C7 and C8. **The *decision* half of
   C4, C6 and C7 closed on 2026-08-07** (D-13, D-14, D-15); what is left there is code. C2 and
   C7 are the two still genuinely open; the C5/C8 question A-51 raised — how a human decision
   survives a projection — is answered by D-16;
3. commit sanitized fixtures for one PV module document and its expected claims — the claim and
   conflict fixture sets already exist in `tests/fixtures/`, so this is a *document* fixture and
   the format constraints in `tests/fixtures/README.md` apply;
4. implement content detection and one format-native parser;
5. persist immutable claims and reduce them to canonical fields;
6. run implemented conflict policy and create queue records;
7. expose a minimal review API for those records;
8. render the PV tab plus provenance/conflict tabs; and
9. validate idempotency, access isolation, audit integrity, and deterministic output.

After that slice is stable, add document formats and component families behind the same
contracts.

## Good first contributions

Changes that are useful without depending on unfinished storage contracts include:

- Protocol conformance tests and an adapter test kit — no test imports `ports` at all today;
- table-driven tests that close remaining schema and traceability gaps;
- sanitized golden fixtures for the existing conflict policy;
- documentation checks and link validation; and
- proposals for the unresolved shared contracts.

Avoid inventing a production workbook shape in isolation: C6's *format* is frozen by D-14 but
no projection exists, and it is
explicitly a shared contract that needs an accepted design decision first. The database shape is
no longer in that category — C1 has landed — but the same rule applies from the other side: build
against `sql/` rather than beside it, and changing what is there is a contract change under
[CONTRIBUTING.md](../CONTRIBUTING.md).
