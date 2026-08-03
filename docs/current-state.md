# Current state

This audit describes `main` at commit `ee1503d` on 2026-08-03. It answers the practical
question a new contributor has first: what can the repository do today?

At that revision, the local verification baseline is 228 passing tests, a clean Ruff check,
and a clean strict-mypy check across `src/` and `tests/`.

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

The most useful summary is the acceptance boundary:

| Acceptance area | State |
|---|---|
| Web cannot overwrite a record value | Unit-level policy passes |
| Every modeled field points to a source | Model-level validation passes |
| Thirteen tab names and four output states | Model/helper level passes |
| Deterministic XLSX archive normalization | Unit-level implementation passes |
| Scanned document to sourced extracted fields | Missing |
| Contradiction through ingestion to queue entry | Missing |
| Complete formatted workbook | Missing |
| Idempotent re-ingestion | Missing |
| Compliance and tax calculations | Missing |
| Retrieval-time access isolation | Missing |
| Byte-identical complete workbook in Excel/LibreOffice | Missing |

See [requirements-traceability.md](requirements-traceability.md) for the detailed mapping.

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

The researched plan and some code comments disagree on lexical retrieval. The current plan
uses PostgreSQL `tsvector` and `pg_trgm`; some port comments still describe embedding-model
sparse output. The traceability record also contains historical statuses that must be kept
in sync as features land.

An implementation should cite the controlling decision and update the deviation register in
the same pull request.

### Contracts are only partially frozen

The task plan marks the database schema, audit event envelope, canonical workbook projection,
ACL model, and stage runner contract as unfinished. These are shared boundaries. Building
multiple adapters before freezing them would create incompatible records and rework.

### No representative corpus

The plan requires a 30–50 document labeled set, deliberately including poor scans and unusual
layouts. Without it, extraction accuracy, review thresholds, retrieval recall, and throughput
claims cannot be validated.

## Recommended delivery sequence

The fastest path to a useful contributor demo is not to implement every service in parallel.
Build one tested vertical slice:

1. settle the license and contributor-governance choices;
2. freeze the database, audit, claim, ACL, runner, and canonical-projection contracts;
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

- Protocol conformance tests and an adapter test kit;
- table-driven tests that close remaining schema and traceability gaps;
- sanitized golden fixtures for the existing conflict policy;
- reconciliation of stale code comments with the specification authority order;
- documentation checks and link validation; and
- proposals for the unresolved shared contracts.

Avoid implementing production database or workbook shapes in isolation. Those formats are
explicitly shared contracts and need an accepted design decision first.
