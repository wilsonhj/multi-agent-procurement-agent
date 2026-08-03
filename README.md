# Procurement Agent

Procurement Agent is a human-in-the-loop document intelligence system for comparing
solar and energy-storage equipment. The intended product ingests supplier files, extracts
facts with provenance, supplements missing facts from public sources, surfaces
disagreements for review, and renders a deterministic 13-tab Excel comparison.

The system is designed for a 500 MW solar-plus-storage procurement in ERCOT, but its
source-of-record, provenance, conflict, and review patterns are meant to be reusable in
other evidence-heavy procurement workflows.

> [!IMPORTANT]
> This repository is a **pre-alpha implementation**, not a working end-to-end application.
> The domain model and several policy algorithms are implemented and tested. Document
> ingestion, extraction adapters, persistence, retrieval, web enrichment, the review UI,
> orchestration, and workbook writing are not yet operational.

## Why this project exists

Supplier evidence arrives as contracts, spreadsheets, native PDFs, scans, images, and
Word documents. The same specification can be stated under different test conditions,
units, product revisions, and system boundaries. A useful comparison must therefore do
more than copy values into a table:

- keep every value tied to its source;
- preserve the ingested documents as the system of record;
- compare values only when their conditions are compatible;
- expose disagreement instead of silently choosing a winner;
- let a human make and explain the final decision; and
- regenerate the same artifact from the same canonical state.

The tool supports procurement decisions. It does not place orders, negotiate, select a
supplier, or make an autonomous procurement decision.

## Current state

| Area | State |
|---|---|
| Canonical Pydantic schema, provenance, closed vocabularies | Implemented and tested |
| Condition-aware comparison and canonical ordering | Implemented and tested |
| Per-field conflict tolerance and declared supplier bands | Implemented and tested |
| Source-of-record overwrite guard | Implemented and tested |
| Compose-time severity gate | Implemented and tested |
| Output flag calculation and deterministic XLSX archive normalization | Implemented and tested |
| Parser, OCR, embedder, vector-store, reranker, and LLM interfaces | Declared as Protocols |
| Ingestion, indexing, retrieval, web enrichment | Stubs; raise `NotImplementedError` |
| PostgreSQL schema, audit log, worker runner, ACL enforcement | Designed, not implemented |
| Conflict queue service and review UI | Data model only |
| 13-tab workbook writer | Stub; archive normalizer exists |
| CLI or deployable service | Not implemented |

See [Current state](docs/current-state.md) for the code-to-spec audit and
[Requirements traceability](docs/requirements-traceability.md) for each FR, NFR, and
acceptance criterion.

## System design

The target flow is:

```text
                         append-only claims
                                │
documents ─► ingest ─► extract ─┼─► reduce ─► canonical store
                    │           │                    │
                    └─► index/retrieve               ├─► detect conflicts
                                                     │          │
public sources ─► gap-only web enrichment ───────────┘          ▼
                                                        review queue
                                                             │
                                           compose-time severity gate
                                                             │
                                                             ▼
                                                  13-tab workbook
```

Human review is deliberately detached from pipeline execution. Workers do not pause while
a conflict waits for a reviewer. Composition queries unresolved conflicts and refuses when
one is above the configured severity threshold, unless a future audited override explicitly
accepts an incomplete output.

The planned runtime uses PostgreSQL as the single durable store for documents, claims,
chunks, jobs, conflicts, resolutions, and an append-only audit log. Work is claimed with
`FOR UPDATE SKIP LOCKED`; no separate workflow framework is planned. Heavy integrations sit
behind six synchronous Protocol interfaces so an installation can choose parsers, OCR,
models, and storage adapters without changing the domain core.

Read [Architecture](docs/architecture.md) for the component boundaries, invariants,
storage model, and important design trade-offs.

## The source-of-record rule

| Tier | Examples | Authority |
|---|---|---|
| `system_of_record` | Ingested contracts and supplier specifications | Authoritative; never overwritten by the web |
| `web_supplement` | Manufacturer pages, certification lists, public datasets | May fill a gap; disagreement becomes a conflict |

A public value can fill an empty field. It cannot replace an ingested value. The current
core enforces this rule with `assert_no_autonomous_overwrite`; the planned store strengthens
it structurally by letting workers append immutable claims while a reducer alone projects
canonical state.

## Quick start

Requirements:

- Python 3.12 or 3.13
- [uv](https://docs.astral.sh/uv/)

Clone the repository and install the development environment:

```bash
git clone https://github.com/wilsonhj/multi-agent-procurement-agent.git
cd multi-agent-procurement-agent
uv sync --extra dev
```

Run the validation suite:

```bash
uv run pytest
uv run ruff check .
uv run mypy
```

The package currently exposes domain models and pure policy helpers; there is no working
pipeline command yet. This example exercises the system-of-record guard:

```python
from procurement_agent.schema import CanonicalField, SourceRef, SourceTier
from procurement_agent.services.conflict_hitl import (
    AutonomousOverwriteError,
    assert_no_autonomous_overwrite,
)

contract_value = CanonicalField(
    value=650,
    unit="W",
    verbatim_value="650 W",
    source_tier=SourceTier.SYSTEM_OF_RECORD,
    source_ref=SourceRef(document_id="supplier-spec.pdf", page=3),
    confidence=0.98,
)

web_value = CanonicalField(
    value=655,
    unit="W",
    verbatim_value="655 W",
    source_tier=SourceTier.WEB_SUPPLEMENT,
    source_ref=SourceRef(url="https://manufacturer.example/module"),
    confidence=0.90,
)

try:
    assert_no_autonomous_overwrite(contract_value, web_value)
except AutonomousOverwriteError:
    # A production reducer would create a conflict for human review.
    pass
```

Copy `.env.example` to `.env` only when developing an adapter. Do not send contract,
pricing, or other confidential material to an endpoint that permits third-party training.

### Optional dependency groups

The core remains intentionally small. Install integrations only when working on them:

| Extra | Purpose |
|---|---|
| `parse` | Docling and pandas document paths |
| `extract` | Schema-constrained extraction client |
| `store` | PostgreSQL and pgvector |
| `solar` | Live, pinned CEC equipment-list processing |
| `dev` | pytest, Ruff, mypy, and type stubs |

For example:

```bash
uv sync --extra dev --extra parse
```

## Repository guide

```text
src/procurement_agent/
├── schema/                  canonical domain objects and vocabularies
├── ports/                   six swappable integration interfaces
├── services/
│   ├── ingestion/           content routing and extraction entry points
│   ├── indexing/            chunking and index entry points
│   ├── retrieval/           retrieval entry point
│   ├── web_search/          gap-only public-source enrichment
│   ├── conflict_hitl/       implemented comparison and conflict policy
│   └── output/              flags, archive normalization, workbook stub
└── orchestrator/            stage vocabulary and compose-time gate

docs/                       contributor-facing explanations and traceability
specs/001-procurement-agent/ normative requirements, decisions, and work plan
tests/                       unit and policy regression tests
```

Start with:

- [Current state](docs/current-state.md) — what works, what is missing, and the highest-risk gaps;
- [Architecture](docs/architecture.md) — intended production design and its invariants;
- [Development guide](docs/development.md) — setup, repository conventions, and change recipes;
- [Contributing](CONTRIBUTING.md) — how to choose and submit work;
- [Requirements traceability](docs/requirements-traceability.md) — requirement-level status; and
- [Agent topology](docs/agent-topology.md) — safe fan-out points and required serialization;
- [Researched defaults](docs/defaults.md) — proposed values for unresolved decisions; and
- [Specification index](specs/001-procurement-agent/spec.md) — the normative problem definition.

The specification directory has an authority order: frozen contracts define shared shapes;
`clarifications.md` resolves domain ambiguity; `plan.md` records technical decisions; and
`tasks.md` turns them into work packages. Do not infer completion from a design document—use
the current-state and traceability documents.

## Contributing

Contributions are welcome, especially small vertical slices that turn a declared interface
into tested behavior. Before starting, read [CONTRIBUTING.md](CONTRIBUTING.md) and choose an
issue whose prerequisite contracts are already settled. Changes that affect a canonical
record, audit envelope, or workbook projection require a written contract decision first.

The project’s most important near-term milestone is to freeze the remaining shared contracts
and land one end-to-end, fixture-backed path from document ingestion to a reviewable claim.

## Security and data handling

The intended workload contains confidential contracts and prices. The production design
requires:

- self-hosted or enterprise inference for confidential material;
- document-level access labels applied at ingest and enforced during retrieval;
- a non-owner, non-superuser application database role;
- immutable, hash-chained audit events; and
- no secrets, source documents, or generated procurement workbooks in git.

These controls are **designed but not implemented**. Do not use the current repository with
real confidential procurement data.

## License

No open-source license has been selected: `pyproject.toml` currently declares
`UNLICENSED`. The source is publicly visible, but that does not grant permission to use,
modify, or redistribute it. A project maintainer must add an OSI-approved license before
this can be presented or adopted as an open-source project.
