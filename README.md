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

This table is a summary derived from [Current state](docs/current-state.md), which is the
source of truth. If the two disagree, that document is right and this one is stale.

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
| PostgreSQL schema, audit hash chain, row-level ACL enforcement | SQL implemented; applied and asserted against a live server in CI |
| Python persistence layer, worker runner | Not implemented; nothing in `src/` opens a connection |
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

Nothing in that diagram runs end to end yet; it is the target, and the boxes between `ingest`
and `13-tab workbook` are stubs. Two things in it are real today and worth stating separately,
because they are the reason the shape is what it is.

Human review is deliberately detached from pipeline execution. There is no
`await_human_resolution` stage and there will not be one: one unresolved conflict on document 7
must not stall documents 8 to 400, and "defer" is a mandated resolution action that a blocking
workflow cannot express. Instead the gate is a *query* at composition time — this part is
implemented and tested, in `orchestrator.compose_gate_blocks()`. It blocks only on unresolved
conflicts strictly above the configured severity, and the threshold cannot be set to a value
that disables it.

The source-of-record rule is the other. `assert_no_autonomous_overwrite()` is implemented and
tested; the planned store makes it structural rather than a guard.

The runtime uses PostgreSQL as the single durable store for documents, claims, chunks, jobs,
conflicts, resolutions, and an append-only audit log. **The schema exists and the Python half
does not**: `sql/00`–`08` define every one of those tables and are applied against a live server
on each CI run, while nothing in `src/` opens a connection to them. Workers will claim jobs with
`FOR UPDATE SKIP LOCKED`; no separate workflow framework is planned.
Heavy integrations sit behind six synchronous Protocol interfaces so an installation can choose
parsers, OCR, models, and storage adapters without changing the domain core. Those six
Protocols are declared; no adapter implements any of them.

Read [Architecture](docs/architecture.md) for the component boundaries, invariants,
storage model, and important design trade-offs.

## The source-of-record rule

| Tier | Examples | Authority |
|---|---|---|
| `system_of_record` | Ingested contracts and supplier specifications | Authoritative; never overwritten by the web |
| `web_supplement` | Manufacturer pages, certification lists, public datasets | May fill a gap; disagreement becomes a conflict |

A public value can fill an empty field. It cannot replace an ingested value. The current core
enforces this rule at one chokepoint, `assert_no_autonomous_overwrite`, tested directly in
[`tests/test_source_of_record_rule.py`](tests/test_source_of_record_rule.py). The planned store
strengthens it structurally by letting workers append immutable claims while a reducer alone
projects canonical state — a guard can detect a bad call but cannot prevent a code path from
bypassing it.

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
uv run ruff format --check .
uv run mypy
```

All four, not three: `ruff format --check` is the one that gets dropped from an informal
retelling, and leaving it off once shipped a file the other three accepted.

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

Copy `.env.example` to `.env` only when developing an adapter. For contract and pricing
documents the LLM **and embedding** endpoints must be self-hosted or enterprise, with no
third-party training on contract data. Both endpoints, not just the generative one: an embedder
receives the same contract text and is the easier of the two to point at a public API by
accident.

Nothing under `docs/source/` is committed — the source requirements documents are marked
"Confidential — internal & supplier use" (FRD) and "Confidential — engineering" (TRS). See
[`.gitignore`](.gitignore), which also excludes ingested supplier material and generated
workbooks per NFR-03.

### Optional dependency groups

The core remains intentionally small. Install integrations only when working on them:

| Extra | Purpose |
|---|---|
| `parse` | Docling and pandas document paths |
| `extract` | Schema-constrained extraction client |
| `store` | PostgreSQL and pgvector |
| `solar` | Live, pinned CEC equipment-list processing |
| `dev` | pytest, Ruff, mypy, and type stubs |

Name every extra you want in one command — `uv sync` is an exact sync and removes anything not
named:

```bash
uv sync --extra dev --extra parse
```

### Dependency license gate

**Apache-2.0, MIT and BSD only.** Copyleft and revenue-capped licenses are disqualifying, and
this constrains what may be proposed as an adapter, not merely what ships in core.

The gate has already rejected several of the components most likely to be suggested for this
problem, each verified at its own `LICENSE` file rather than from a summary:

| Component | License | Verdict |
|---|---|---|
| Marker (marker-pdf) | code Apache-2.0, **weights RAIL-M**, free only under $5M revenue | rejected — revenue-capped |
| Surya | GPL-3.0 | rejected — copyleft |
| MinerU | AGPL-3.0 | rejected — copyleft |
| olmOCR | AI Pubs RAIL-M, revenue cap | rejected |
| PyMuPDF | AGPL-3.0 or Artifex commercial | rejected — was declared as an extra, then removed |
| ParadeDB / `pg_search`, VectorChord-bm25 | AGPL-3.0 (VectorChord also ELv2) | rejected — copyleft |
| Jina embeddings v5, NV-Embed-v2 | non-commercial | rejected |

The consequence to internalize: **there is no permissively licensed true-BM25 for PostgreSQL**,
which is why retrieval uses `tsvector` and `pg_trgm` instead, and why FR-RAG-03's BM25 clause is
registered as a reversal rather than implemented. The full gate with rationale is in
[plan.md](specs/001-procurement-agent/plan.md).

## Repository guide

```text
src/procurement_agent/
├── config.py                Settings, PROCUREMENT_ prefix, bounds enforced
├── schema/                  canonical domain objects and vocabularies
├── ports/                   six swappable integration interfaces
├── services/
│   ├── ingestion/           content routing and extraction entry points
│   ├── indexing/            chunking and index entry points
│   ├── retrieval/           retrieval entry point
│   ├── web_search/          gap-only public-source enrichment
│   ├── claims/              append-only claim record and its projection
│   ├── confidence/          confidence fusion and the Tier A review gate
│   ├── identity/            deterministic supplier and model matching
│   ├── conflict_hitl/       implemented comparison and conflict policy
│   └── output/              flags, archive normalization, workbook stub
└── orchestrator/            stage vocabulary and compose-time gate

sql/                         nine numbered DDL files, applied in lexical order,
                             plus a README recording the decisions the specs
                             did not settle. No Python reaches them yet.
.github/workflows/ci.yml     four blocking gates, plus a live-PostgreSQL job

docs/
├── current-state.md         what works today; the source of truth for status
├── architecture.md          intended production design and its invariants
├── development.md           setup, conventions, and change recipes
├── requirements-traceability.md  every FR/NFR/AC mapped to code and tests
├── agent-topology.md        where the pipeline may fan out, and where it must not
├── decisions/               ADRs — decisions taken after plan.md froze; ranked
│                            below plan.md and above tasks.md (see below)
├── defaults.md              proposed values for unresolved decisions
└── open-questions.md        SUPERSEDED by clarifications.md, except for a short
                             carried-forward list at its foot

specs/001-procurement-agent/ normative requirements, decisions, and work plan
tests/                       unit and policy regression tests
```

Start with:

- [Current state](docs/current-state.md) — what works, what is missing, and the highest-risk gaps;
- [Architecture](docs/architecture.md) — intended production design and its invariants;
- [Development guide](docs/development.md) — setup, repository conventions, and change recipes;
- [Contributing](CONTRIBUTING.md) — how to choose and submit work;
- [Requirements traceability](docs/requirements-traceability.md) — requirement-level status;
- [Agent topology](docs/agent-topology.md) — safe fan-out points and required serialization;
- [Researched defaults](docs/defaults.md) — proposed values for unresolved decisions; and
- [Specification index](specs/001-procurement-agent/spec.md) — the normative problem definition.

When two artifacts disagree, they are ranked. Highest first:

1. frozen contracts under `specs/001-procurement-agent/contracts/`;
2. `spec.md`, for externally visible requirements;
3. adopted resolutions in `clarifications.md`;
4. technical decisions in `plan.md`;
5. ratified ADRs under `docs/decisions/` — decisions taken after the plan froze, which by
   their own text never amend a plan decision (a reversal of one belongs in the plan's register);
6. work decomposition in `tasks.md`; and
7. explanatory code comments and contributor docs — including this file.

Rank 5 was added on 2026-09-02, when
[ADR-001](docs/decisions/ADR-001-cross-repo-pattern-adoption.md) was ratified. It had sat at
`Proposed` and unranked for four weeks while `phase-1-execution.md` Track 4 was assigned to
implement its Decision 2 (A-68).

`spec.md` is rank 2 and is the artifact most often left out of an informal retelling of this
order, which is how a plan-level decision ends up quietly overriding a requirement. If following
the higher rank would break a lower-ranked decision, register the deviation in `analysis.md`
rather than picking one silently; see
[Specification authority](docs/architecture.md#specification-authority).

Do not infer completion from a design document — use the current-state and traceability
documents.

## Build plan

Five stages, each with the threshold that has to be met before the next one starts. No stage
below is complete; the current position is "before Stage 1", and Phase 0 of
[tasks.md](specs/001-procurement-agent/tasks.md) gates all of it. Phase 0 is itself part-done —
three of the eight contracts are frozen — so the gate has moved, but it has not opened.

| Stage | Scope | Exit threshold |
|---|---|---|
| 1 | Ingestion + OCR for all formats; lock the canonical schema for PV, inverters, BESS | ≥90% field-level extraction on 20–30 real datasheets, with provenance |
| 2 | Chunking, hybrid retrieval + reranker; Excel writer for the first 3 categories | deterministic regeneration; no unsourced cells |
| 3 | Supplement-only web search; conflict detection; queue + resolution UI | 100% of injected web-vs-spec conflicts surfaced; zero auto-overwrites |
| 4 | Remaining categories; Compliance Matrix and Tax Incentives tabs | all 13 tabs present |
| 5 | Retrieval-time access control, immutable audit log, dedup, self-hosted endpoints | audit, security and idempotency requirements verified |

These stage numbers are load-bearing: [agent-topology.md](docs/agent-topology.md) argues about
concurrency in terms of "Stage 1", "Stage 3's exit threshold" and "Stage 4 work", and this table
is where those resolve. It is a **different axis** from `tasks.md`, which cuts the same work into
Phase 0 (contract freeze) and nine parallel work packages WP-A … WP-I. Stages answer *what is
good enough to move on*; work packages answer *who can build in parallel right now*. Neither
replaces the other, and neither is a schedule.

LLM extraction is imperfect, and the Stage 1 threshold above is the only place that gets
measured. Plan for 92–97% exact match on headline numerics from clean text-layer tables, 80–90%
from scans, and 70–85% on conditional fields — and treat all of those as extrapolations, because
[D-11](specs/001-procurement-agent/clarifications.md) records that no public benchmark exists
for this task and the 30–50 document labelled gold set has not been built. Human review of
flagged fields is mandatory, not optional.

## Contributing

Contributions are welcome, especially small vertical slices that turn a declared interface
into tested behavior. Before starting, read [CONTRIBUTING.md](CONTRIBUTING.md) and choose an
issue whose prerequisite contracts are already settled. Changes that affect a canonical
record, audit envelope, or workbook projection require a written contract decision first, and
a new dependency must clear the license gate above.

The project’s most important near-term milestone is to freeze the remaining shared contracts —
five of the eight are still unfinished (C1, C3 and C5 are done) — and land one end-to-end,
fixture-backed path from document ingestion to a reviewable claim. Read the four partials by
their evidence rather than their marker: C4 and C8 each have a finished SQL half and an
unstarted Python one, which is the pair most easily mistaken for done.

## Security and data handling

The intended workload contains confidential contracts and prices. The production design
requires:

- self-hosted or enterprise inference **and embedding** for confidential material;
- document-level access labels applied at ingest and enforced during retrieval;
- a non-owner, non-superuser application database role;
- immutable, hash-chained audit events; and
- no secrets, source documents, or generated procurement workbooks in git.

Three of those five exist in the database schema and are asserted against a live server on every
CI run: the access labels (row-level security on all seven tables holding document content,
`FORCE`d so the owner is not exempt), the restricted application role, and the audit hash chain.
The last one is in force today and is not conditional on anything shipping — `.gitignore`
excludes `docs/source/`, ingested supplier material, and generated workbooks.

**What does not exist is the Python half.** Nothing in `src/` opens a database connection, so no
application code path is subject to any of it, and `services/retrieval.retrieve` — where the
access labels would be enforced *at retrieval time*, which is what NFR-03 actually asks for —
raises `NotImplementedError`. Self-hosted endpoints remain an `.env.example` convention with no
check. Do not use the current repository with real confidential procurement data.

## Scope boundaries and regulatory disclaimer

Out of scope: placing orders, signing contracts, committing spend, automatically choosing
between conflicting data or recommending a winner, ERP posting, price negotiation, engineering
or yield modelling, and legal review. The tool informs these; it does not perform them.

> [!IMPORTANT]
> **Regulatory and tax content is reported as status, not advice.** Tax, environmental and grid
> rules are evolving through 2026. Confirm against primary sources and with tax and legal
> counsel before relying on any of it for filings.
>
> This is not boilerplate. Two of the thirteen workbook tabs — **Compliance Matrix** and
> **Tax Incentives** — exist to present exactly this material, per-supplier and in a form that
> invites being read as a determination. AC-6 requires the compliance tab to test TRD against
> the correct IEEE 2800 voltage-class limit, where getting the measure wrong "produces a
> compliance matrix that passes suppliers it should fail"; BABA applicability is still recorded
> as `unconfirmed` because it depends on project funding nobody has confirmed. The output is an
> input to a decision made by people who are accountable for it.

## License

**Apache-2.0.** See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Apache-2.0 rather than MIT for one specific reason: its express patent grant (§3). Document
layout analysis, OCR and table extraction are patent-active territory, and this tool is meant
to run inside other companies' infrastructure — MIT would leave every adopter relying on an
implied licence at best. The same clause carries a defensive retaliation trigger, which only
affects a party that sues, and is a large part of why corporate intake processes prefer
Apache-2.0 over MIT rather than merely tolerating it.

The choice is deliberately *permissive*, not reciprocal. Nothing here obliges anyone to
contribute back. MPL-2.0 was the considered alternative — file-level reciprocity, still
OSI-approved, still enterprise-tractable — and was not taken because adoption matters more
here than preventing a fork.

Note that this is independent of the dependency gate above. Permissive licences are
sublicensable, so the inbound rule (Apache-2.0, MIT, BSD only) neither forces nor forbids any
particular outbound choice; they are orthogonal.

Contributions are accepted under a **DCO**, not a CLA — see [CONTRIBUTING.md](CONTRIBUTING.md).
