# Architecture

This document explains the intended production architecture and marks the boundary between
design and implementation. The requirements and frozen contracts under
`specs/001-procurement-agent/` remain normative.

## Design goals

Procurement Agent is an evidence-processing system, not an autonomous buyer. Its architecture
optimizes for:

1. provenance over convenience;
2. visible disagreement over silent arbitration;
3. deterministic outputs over mutable spreadsheets;
4. replaceable integrations over framework lock-in;
5. access control at the data boundary; and
6. human accountability for final decisions.

The design targets hundreds of mixed-format documents in an offline or batch workflow. It is
not a low-latency chat agent.

## System context

Inputs include supplier contracts, purchase orders, terms, warranties, technical
documentation, price files, and specification sheets. Public data is supplementary and may
include manufacturer publications, certification listings, regulatory sources, and current
CEC equipment exports.

The output is a 13-tab Excel comparison covering eight component categories plus executive,
conflict, provenance, compliance, and tax views. Excel is a read-only projection: conflict
resolution happens in the application so reviewer identity, rationale, and before/after values
can be recorded immutably.

## Processing model

```text
                     ┌─────────────────────────────┐
input bytes ────────►│ ingest + classify           │
                     │ content signature, parsing, │
                     │ OCR fallback, page audit    │
                     └──────────────┬──────────────┘
                                    │ parsed elements
                                    ▼
                     ┌─────────────────────────────┐
                     │ extract immutable claims    │
                     │ value, condition, source,   │
                     │ confidence, model version   │
                     └───────┬──────────┬──────────┘
                             │          │
                             │          └──────────────► index + retrieval
                             ▼
                     ┌─────────────────────────────┐
                     │ reducer                     │
                     │ claims → canonical fields  │
                     └───────┬──────────┬──────────┘
                             │          │
              missing fields │          │ competing values
                             ▼          ▼
                     web enrichment   conflict detector
                             │          │
                             └────┬─────┘
                                  ▼
                         human review queue
                                  │ resolutions
                                  ▼
                         canonical projection
                                  │
                         compose severity gate
                                  │
                                  ▼
                           deterministic XLSX
```

The web path is triggered by a gap or an explicit request. It cannot overwrite a
system-of-record claim.

## Domain model

The code under `src/procurement_agent/schema/` establishes the shared language between
stages.

### Source documents

`SourceDocument` is content-addressed and carries a stable ID, content hash, source URI,
document type, timestamps, and an access-restriction marker. The planned ingest store uses
the content hash to make unchanged re-ingestion a no-op.

### Component instances

`ComponentInstance` identifies a supplier offering by category, supplier, model, nameplate,
and a surrogate ID. Supplier and model are not sufficient identifiers: a datasheet may cover
multiple product bins, and upstream public datasets contain duplicate manufacturer/model
pairs. `ordering_key()` provides deterministic row order.

### Canonical fields

`CanonicalField` carries:

- the parsed value and canonical unit;
- the original verbatim value;
- a structured `Condition`;
- the source tier and immutable `SourceRef`;
- confidence;
- conflict state; and
- an optional human `Resolution`.

The extra `condition` dimension is essential. `352 kVA @30 °C` and `320.865 kW @40 °C`
cannot be treated as a numeric disagreement without first accounting for the rating
conditions.

### Claims and canonical state

The intended store uses immutable claims keyed by document, field, and extractor version.
Workers propose claims; they do not write a final canonical value. A reducer projects the
claims into canonical state and is the only component allowed to apply overwrite policy.

This planned structure is stronger than the currently implemented
`assert_no_autonomous_overwrite()` guard. A pure guard can detect a bad call, but it cannot
prevent another code path from bypassing it or prevent last-writer-wins races.

### Conflicts

`ConflictCandidate` preserves each competing value, condition, source, verbatim text, and
confidence. `ConflictQueueEntry` adds field and component identity, the conflict class,
severity, explanation, detection time, and optional resolution.

There are five conflict classes:

- record versus web;
- inter-document;
- intra-document;
- temporal; and
- unit-normalization.

Severity controls composition policy. It is not a confidence score and must not be calculated
by multiplying unrelated risk factors.

## Core invariants

### 1. System-of-record values are never replaced by web values

Public data may populate a gap. If it disagrees with an ingested contract or specification,
both values are retained and a human reviews the conflict.

### 2. No value exists without provenance

`SourceRef` requires either a document ID or URL. Production storage must additionally retain
page, section, bounding box, extractor version, and public-source metadata whenever available.

### 3. Conditions are checked before tolerance

Two values with incompatible test conditions are not “equal” and are not “in conflict.” They
are not comparable until a boundary or condition normalization is defined.

### 4. Candidate comparison is pairwise

Condition compatibility is not transitive: an unstated condition may be comparable with both
`@30 °C` and `@40 °C`, while those two stated conditions are incompatible with each other.
Therefore conflict detection evaluates canonical unordered pairs. Connected components or
first-fit buckets would either introduce false comparisons or lose real ones.

### 5. Tolerance is per field

There is no global numeric tolerance. The implemented table supports exact, absolute,
relative, one-sided, declared-band, and never-compare policies, plus a rounding floor derived
from source precision.

### 6. Human review is detached

There is no `await_human_resolution` pipeline stage. Conflicts can remain open indefinitely.
Composition queries unresolved entries and applies the severity gate at that point.

### 7. Canonical state, not XLSX, is the artifact of record

The workbook is a deterministic projection. The planned canonical JSON projection is hashed;
XLSX is rendered from it. Human edits to a workbook are not authoritative because they lack
authenticated reviewer identity and immutable rationale.

### 8. Access control is enforced during retrieval

Filtering after retrieval can expose restricted content to a model or reranker. The planned
vector-store adapter accepts the set of allowed document IDs and PostgreSQL uses forced row
level security with a non-owner application role.

## Services and boundaries

| Package | Responsibility | Current implementation |
|---|---|---|
| `services.ingestion` | signature detection, parsing, OCR routing, classification, unit normalization | Stub |
| `services.indexing` | structure-aware chunks and incremental indexing | Stub |
| `services.retrieval` | filtered hybrid retrieval and reranking | Stub |
| `services.web_search` | gap-only public-source lookup and authority ranking | Stub |
| `services.conflict_hitl` | comparison pairs, overwrite guard, tolerance verdicts | Implemented policy core |
| `services.output` | flags, canonical workbook rendering, archive normalization | Flags and normalization only |
| `orchestrator` | jobs, retries, stage state, compose gate | Gate only |

The six external swap points are synchronous structural Protocols:

`ParserPort`, `OCRPort`, `EmbedderPort`, `VectorStorePort`, `RerankerPort`, and `LLMPort`.

Synchronous interfaces are deliberate. The target runner scales with worker processes.
CPU-heavy parse and OCR work can use process pools; remote model calls can use bounded thread
pools; embedding and reranking adapters batch internally.

## Planned persistence and execution

The target deployment uses one PostgreSQL instance, with pgvector, for:

- document metadata and access labels;
- immutable extraction claims;
- canonical projections;
- chunks, vectors, and lexical indexes;
- jobs and stage leases;
- conflicts and resolutions; and
- a privilege-separated audit schema.

Workers claim jobs using `SELECT … FOR UPDATE SKIP LOCKED`. Delivery is at least once, so each
stage must be independently idempotent. Poison messages are quarantined instead of retried
forever.

Audit events are planned as per-document hash chains. The application role receives insert
and select privileges only; an advisory lock is acquired before each insert and a uniqueness
constraint makes a fork loud. This design has not been implemented yet.

## Retrieval design

The current plan specifies:

1. structure-aware prose chunks around 512 tokens;
2. full-table, row, and summary representations instead of token-splitting tables;
3. Qwen3-Embedding-4B truncated to 1024 dimensions;
4. exact pgvector search at the initial corpus size;
5. PostgreSQL `tsvector` and `pg_trgm` lexical candidates;
6. reciprocal-rank fusion; and
7. bge-reranker-v2-m3 over the fused candidate set.

Exact vector search is intentional. Filtered approximate indexes were measured returning
fewer than the requested top-k, while exact search was fast enough at the target scale.

Some code docstrings and the deviation annotation beside FR-RAG-03 in `spec.md` describe lexical
retrieval from a model’s sparse output instead of the `tsvector`/`pg_trgm` design recorded in
`plan.md` and `tasks.md`. Treat the plan as the current implementation baseline and reconcile
that cross-artifact inconsistency before implementing the adapter.

## Parsing and extraction design

No parser is expected to handle every input:

- spreadsheets use format-native openpyxl/pandas paths;
- text PDFs and DOCX use Docling;
- image-only pages use an OCR path;
- each page is audited for missing text and table cells; and
- critical tables are dual-parsed so disagreement can become a confidence feature.

Extraction uses schema-constrained output validated by Pydantic. Confidence is intended to
combine grounding, OCR quality, cross-read agreement, model log probabilities, and domain
plausibility. Self-reported LLM confidence and majority-vote suppression of conflicts are
explicitly rejected.

## Workbook design

The workbook always contains eight component tabs and five cross-cutting tabs. Provenance
state is carried in hidden parallel columns. Visual channels are orthogonal:

- fill communicates origin;
- font communicates confidence; and
- border communicates conflict.

`normalize_archive()` already removes clock, library-version, compression, member-order, and
platform variance from an XLSX archive. `write_workbook()` is not implemented. Desktop Excel
and LibreOffice validation remains a release gate once the writer exists.

## Specification authority

Use this order when artifacts disagree:

1. frozen contracts under `specs/001-procurement-agent/contracts/`;
2. `spec.md` for externally visible requirements;
3. adopted resolutions in `clarifications.md`;
4. technical decisions in `plan.md`;
5. work decomposition in `tasks.md`; and
6. explanatory code comments and contributor docs.

If implementing the higher-ranked artifact would violate a lower-ranked decision, update the
deviation register rather than silently choosing one.
