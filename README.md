# Procurement Agent

An agentic, human-in-the-loop RAG pipeline for **solar-plus-storage component procurement**.

It ingests multi-format supplier documentation, extracts structured facts into a canonical
component schema, supplements gaps from public web sources, detects cross-source conflicts,
and emits a 13-tab Excel supplier comparison in which **every value traces to a source**.

Built for a 500 MW solar-plus-storage project interconnecting to **ERCOT** in Texas.

> **The tool supports decisions; it does not make them.** Final procurement authority
> remains human. The agent takes no autonomous procurement action, and it never picks a
> winner when sources disagree — it surfaces both, with provenance, for a person to resolve.

---

## Status

**Scaffolding.** The canonical schema, the swap-point interfaces, the source-of-record
guard and the acceptance-criteria tests are real and tested. The seven services are
declared with their contracts and raise `NotImplementedError`. Nothing ingests a document
yet. See [Build plan](#build-plan) for the staged path to a working pipeline.

---

## Why this exists

Supplier documentation for a utility-scale project arrives as contracts, spec sheets,
scans, photographs and spreadsheets. It is incomplete, it changes with product revisions,
and it has to be judged against Texas/ERCOT grid rules, storage fire codes, and the 2026
federal tax-credit regime. Comparing eight component categories across suppliers
like-for-like is slow and error-prone by hand.

This tool does the collection, normalization and cross-checking. A human does the deciding.

---

## The hard rule

Everything in the design follows from one constraint:

| Tier | Source | Authority |
|---|---|---|
| `system_of_record` | Ingested contracts and spec sheets | Authoritative. Never overwritten. |
| `web_supplement` | Public datasheets, certification listings | May fill an **empty** field only. |

A web value may populate a gap. It may **never** overwrite a system-of-record value, and a
disagreement between the two is **never** auto-arbitrated — it goes to a human queue.

This is enforced in code at a single chokepoint, `assert_no_autonomous_overwrite`, and
tested directly in `tests/test_source_of_record_rule.py`.

---

## Pipeline

```
ingest → extract → index → enrich_via_web → detect_conflicts
                                                  ↓
                                     [interrupt: human approval]
                                                  ↓
                                          compose_workbook
```

Interrupts fire only on high-blast-radius or uncertain nodes — detected conflicts and
low-confidence extractions — not on every step, or latency becomes unbounded.

## Services

Seven services coordinated by an orchestrator:

| Service | Responsibility |
|---|---|
| **Ingestion & Extraction** | File-type detection by content signature → parsers → OCR fallback → layout-aware text/tables → schema-constrained field extraction |
| **Indexing** | Structure-aware chunking, embeddings, ANN index (HNSW/IVF, cosine) + BM25, metadata store |
| **Retrieval** | Hybrid vector + BM25 with reranking and metadata filtering by category, supplier, doc type and source tier |
| **Web Search** | Gap-triggered query generation, supplement-only tagging, source-authority capture |
| **Conflict & HITL** | Field-level reconciliation across five conflict classes, conflict queue, decision logging |
| **Comparison / Output** | Canonical store → 13-tab workbook with per-cell provenance and conditional formatting |
| **Orchestrator** | Workflow, state, retries, provenance and audit trail |

---

## Canonical data model

Every extracted parameter is a field object carrying its own provenance and conflict state:

```python
{
    "value": 650,
    "unit": "Wp",
    "verbatim_value": "650 W",  # original text, always retained
    "source_tier": "system_of_record",
    "source_ref": {"document_id": "...", "page": 3},
    "confidence": 0.95,
    "conflict_status": "none",
    "resolution": None,
}
```

The canonical store built from these is the **single** source for Excel regeneration and
for the audit trail, which is what makes the workbook deterministically regenerable.

---

## Output workbook

One `.xlsx`, thirteen tabs:

**Component categories (1–8)** — PV Modules · Inverters/PCS · Trackers & Mounting ·
Transformers · Cabling & Wiring · Combiner Boxes · BESS · EMS/SCADA & Controls

**Summary (9–13)** — Executive Summary · Conflicts & Open Items · Sources & Provenance ·
Compliance Matrix (Texas/ERCOT) · Tax Incentives (BABA, ITC & domestic content)

Four cell states are visually flagged: unresolved conflicts, web-supplemented values,
low-confidence values, and missing data.

---

## Getting started

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
```

```bash
uv run pytest
```

Copy `.env.example` to `.env` before wiring any endpoints. For contract and pricing
documents the LLM and embedding endpoints must be self-hosted or enterprise, with no
third-party training on contract data.

Optional extras keep heavy dependencies out of the core: `--extra parse` (Docling,
pandas), `--extra agent` (LangGraph, Instructor), `--extra solar` (pvlib).

---

## Layout

```
src/procurement_agent/
├── schema/          Canonical field object, component instances, closed vocabularies
├── ports/           The six swappable interfaces: parser, OCR, embedder,
│                    vector store, reranker, LLM
├── services/        The seven services above, one package each
└── orchestrator/    Pipeline stages and interrupt policy

docs/
├── requirements-traceability.md   Every FR/NFR/AC mapped to where it lives
└── open-questions.md              Decisions the specs leave open

tests/              Acceptance criteria that the scaffolding can already enforce
```

Nothing under `docs/source/` is committed — the source requirements documents are marked
confidential. See `.gitignore`.

---

## Design decisions and where they came from

The Technical Requirements Spec deliberately defers stack selection: *"vector DB, OCR
engine, LLM, and framework selection are design decisions."* Those choices come from a
companion technology-landscape review, and the ones adopted here are:

- **Python**, because the whole relevant ecosystem is Python — Docling, pvlib, openpyxl,
  Instructor, LangGraph.
- **Pydantic** for the canonical schema, so schema-constrained extraction, validation and
  per-field confidence come from one place.
- **openpyxl** for the workbook — multi-sheet, formatting, cell comments for provenance.
- **Protocol interfaces over concrete adapters**, because the spec requires parsers, OCR,
  embedders, vector store, reranker and LLM to be swappable. Heavy dependencies sit behind
  optional extras so this is enforced by packaging, not just convention.
- **A parser router rather than one engine**, because no single parser wins across
  text PDFs, scans, and spreadsheets.

Licence posture: Apache-2.0 and MIT components only. Several strong OCR options are
excluded on licence grounds. Confirm the exact licence of every component at integration
time.

---

## Build plan

| Stage | Scope | Exit threshold |
|---|---|---|
| 1 | Ingestion + OCR for all formats; lock canonical schema for PV, inverters, BESS | ≥90% field-level extraction on 20–30 real datasheets, with provenance |
| 2 | Chunking, hybrid retrieval + reranker; Excel writer for first 3 categories | Deterministic regeneration; no unsourced cells |
| 3 | Supplement-only web search; conflict detection; queue + resolution UI | 100% of injected web-vs-spec conflicts surfaced; zero auto-overwrites |
| 4 | Remaining categories; Compliance Matrix and Tax Incentives tabs | All 13 tabs present |
| 5 | Retrieval-time access control, immutable audit log, dedup, self-hosted endpoints | Audit, security and idempotency requirements verified |

LLM extraction is imperfect — roughly 85–95% on clean documents, lower on poor scans.
Human review of flagged fields is mandatory, not optional.

---

## Scope boundaries

Not in phase 1: placing orders, ERP posting, price negotiation, engineering or yield
modeling, legal review. The tool informs these; it does not perform them.

Regulatory and tax content reflects rules as understood in mid-2026 and is reported as
status, not advice. Confirm against primary sources and with tax and legal counsel before
relying on any of it for filings.
