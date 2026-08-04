# Current state

This audit describes `main` at commit `ee1503d` on 2026-08-03, plus the one regression test
added alongside it (see [Output primitives](#output-primitives)). It answers the practical
question a new contributor has first: what can the repository do today?

The local verification baseline is 229 passing tests, a clean Ruff check, and a clean
strict-mypy check across `src/` and `tests/`. It was 228 at `ee1503d`.

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
- a document ingestion or RAG service;
- a secure store for confidential procurement data; or
- an open-source release, because no license has been granted.

## Implemented and tested

### Canonical domain models

Pydantic models cover source documents, component instances, canonical fields, structured
conditions, declared tolerance bands, conflict candidates, queue entries, and resolutions.
Closed enums cover component categories, document types, source tiers, conflict classes,
conditions, severity, resolution actions, workbook tabs, and cell flags.

Important validators already reject unsourced values, invalid confidence values,
non-finite conditions and bands, malformed declared bands, and “resolved” fields without a
resolution.

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
- applies per-field exact, absolute, relative, one-sided, and declared-band rules; and
- honors the precision of the source’s printed value.

### Source authority

`assert_no_autonomous_overwrite()` prevents a web supplement from replacing a populated
system-of-record field. This is a useful safety predicate, although the future store must
make bypassing it structurally impossible.

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

There are no database migrations or repositories. The planned document, claim, canonical,
chunk, conflict, resolution, job, and audit tables do not exist.

### Human review

The conflict and resolution data shapes exist. There is no queue lease service, reviewer
API, authentication, or UI.

### Security

The design calls for access labels, retrieval-time filtering, forced PostgreSQL RLS, a
non-owner application role, and self-hosted or enterprise inference. None is enforced by
running code.

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
| AC-5 | Re-ingesting an unchanged document creates no duplicates | Nothing. `content_hash` exists but carries no uniqueness constraint | open |
| AC-6 | Inverter TRD against the IEEE 2800 limit; tax status per supplier | Nothing | open |
| AC-7 | Two generations from an unchanged store are byte-identical | `normalize_archive()`, at archive level only. Without a writer there is no complete workbook to regenerate, and the desktop Excel/LibreOffice gate is unrun | partial |
| AC-8 | An uncleared user cannot influence any retrieved result | `VectorStorePort.search(allowed_document_ids=...)` declares the parameter. No adapter, no enforcement, no test imports `ports` | declared |

Read that table as three groups, because they fail differently. AC-4 is genuinely covered.
AC-2, AC-3 and AC-7 each have a tested *policy half* and an unbuilt *pipeline half* — that
split is the pattern to distrust in any status claim about this repository, because the tested
half is the one that gets quoted. AC-1, AC-5, AC-6 and AC-8 have no test at all; of those, only
AC-8 has so much as a signature.

See [requirements-traceability.md](requirements-traceability.md) for the requirement-level
mapping behind these.

## Design and documentation debt

### Public repository without a license

`pyproject.toml` declares `UNLICENSED` and no `LICENSE` file exists. Public visibility alone
does not permit reuse or redistribution. Selecting and adding an OSI-approved license is the
largest non-code blocker to outside adoption.

### No contributor governance

Before a broad public launch, maintainers should add:

- a selected license;
- a code of conduct;
- a security reporting policy;
- an issue and pull-request template;
- a release and compatibility policy; and
- a decision on DCO versus CLA for external contributions.

This documentation adds a contribution workflow but intentionally does not invent legal or
governance choices for the maintainers.

### Specification drift

The plan and the code disagreed on lexical retrieval in both directions at once. Plan Decision
3b chooses PostgreSQL `tsvector` and `pg_trgm`; `services/retrieval` and `services/indexing`
still advertised the TRS's BM25 (and `services/indexing`, an HNSW/IVF index that Decision 3a
also reverses), while `ports` described the embedding model's sparse output, which is a
Decision 5 contingency rather than Decision 3b's choice. All three docstrings are corrected as
part of this documentation change. The remaining mismatch is inside `spec.md`'s own deviation
note, which needs a spec edit; [architecture.md](architecture.md#the-fr-rag-03-lexical-drift-and-exactly-what-is-left-of-it)
lays out all three positions and which one to build to.

The traceability record also contains historical statuses that must be kept in sync as
features land.

An implementation should cite the controlling decision and register the deviation in the same
pull request. The register is
[`specs/001-procurement-agent/analysis.md`](../specs/001-procurement-agent/analysis.md) — a
numbered `A-n` finding list with a status column, not a separate file. FR-RAG-03's own reversal
is filed there as A-24.

### Contracts are only partially frozen

[`tasks.md` Phase 0](../specs/001-procurement-agent/tasks.md) enumerates eight shared contracts,
C1–C8. **Seven of the eight are unfinished**; only C5 is done. Four are untouched and three are
started but not settled, and the distinction matters — a *partial* contract is the more
dangerous kind, because there is enough of it to build against and not enough to be stable:

| ID | Contract | Status in `tasks.md` |
|---|---|---|
| C1 | Postgres schema (`document`, `chunk`, `claim`, `conflict`, `resolution`, `audit.event`) | ☐ not started |
| C2 | Claim/extraction record | partial — `schema/` exists, needs `condition` and per-category models |
| C3 | Provenance reference `(document_id, page, span, extractor_version)` | partial — `SourceRef` exists |
| C4 | Audit event envelope and `event_type` taxonomy | ☐ not started |
| C5 | Conflict record and the five resolution action shapes | **done** |
| C6 | Canonical workbook projection | ☐ not started |
| C7 | Retrieval interface and ACL/labelling model | partial — `VectorStorePort` exists, ACL model undecided |
| C8 | Stage runner contract, including the append-only claim invariant | ☐ not started |

An earlier version of this section named five of these and omitted C2 and C3. That was the
wrong five to shorten to: `tasks.md` singles out **C1, C2, C3 and C7** as “the expensive ones to
change”, so two of the four costliest were the ones missing. C2 and C3 are also the two most
likely to be mistaken for finished, because `schema/` and `SourceRef` already exist.

These are shared boundaries. Building multiple adapters before freezing them would create
incompatible records and rework.

### No representative corpus

The plan requires a 30–50 document labeled set, deliberately including poor scans and unusual
layouts. Without it, extraction accuracy, review thresholds, retrieval recall, and throughput
claims cannot be validated.

## Recommended delivery sequence

The fastest path to a useful contributor demo is not to implement every service in parallel.
Build one tested vertical slice:

1. settle the license and contributor-governance choices;
2. freeze the seven contracts still open above — C1–C4 and C6–C8;
3. commit sanitized fixtures for one PV module document and its expected claims;
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
- correcting the deviation note beside FR-RAG-03 in `spec.md`, which names a design plan
  Decision 3b did not choose. This is a well-bounded first change with a real specification
  question in it: it edits a rank-2 artifact, so it needs its own `A-n` entry in `analysis.md`;
- documentation checks and link validation; and
- proposals for the unresolved shared contracts.

Avoid implementing production database or workbook shapes in isolation. Those formats are
explicitly shared contracts and need an accepted design decision first.
