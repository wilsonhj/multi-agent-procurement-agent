# Open questions

Decisions the FRD and TRS leave unresolved, which need an answer before the relevant
stage can be built. Ordered by what blocks earliest.

---

## 1. HITL confidence threshold — blocks Stage 1

FR-ING-10 routes sub-threshold fields to human review but names no number. The TRS's own
baseline is that LLM extraction runs 85–95% on clean documents and lower on poor scans.

Placeholder: `0.80` in `config.hitl_confidence_threshold`.

The real value is a workload trade-off, and it can't be picked honestly until Stage 1's
20–30 datasheet corpus exists to measure against. Too high and reviewers drown; too low and
wrong values reach the workbook flagged as confident.

## 2. Numeric conflict tolerance — blocks Stage 3

FR-WEB-04 raises a conflict when values differ "beyond tolerance". Tolerance is never
defined anywhere in either document.

Placeholder: `0.02` (2%, relative) in `config.numeric_conflict_tolerance`.

A single global tolerance is almost certainly wrong. A 2% band means something very
different on a 650 Wp nameplate than on a −0.29 %/°C temperature coefficient or a 25-year
warranty term. Per-field or per-unit tolerance is the likely answer.

This is where `services/conflict_hitl.values_conflict` is deliberately unimplemented.

## 3. Component count: 7 categories or 8?

The FRD's comparison table (section 6) lists **seven** rows, merging "Cabling & Combiner
Boxes". The FRD's tab list and the TRS both specify **eight** category tabs, splitting them.

Resolved in code as **eight**, following the TRS, which enumerates all 13 tabs explicitly.
Worth confirming with the product owner, since it changes the workbook shape.

## 4. Supplier and model identity resolution — blocks Stage 1

Nothing in either document says how the system knows two datasheets describe the same
`supplier` + `model`. Without a rule, inter-document conflict detection (FR-HITL-01b) has
no way to know which fields to compare.

Needs: a normalization rule for manufacturer names and a model-number matching policy,
including how to treat revision suffixes.

## 5. Authentication and identity model — blocks Stage 5

FR-HITL-06 logs decisions per user and NFR-03 enforces per-document access control at
retrieval time. Neither document specifies an identity provider, a role model, or how
document-level permissions are assigned.

`Resolution.resolved_by` is currently a bare string.

## 6. Orchestrator contract

The TRS names the orchestrator's responsibilities — workflow, state, retries, audit trail —
and specifies none of them. No state machine, no retry policy, no inter-service transport.

The reference memo recommends LangGraph with a Postgres checkpointer. Adopted directionally
in `orchestrator/`, but the retry and failure semantics are still unwritten.

## 7. HITL resolution UI

Stage 3 names a "conflict queue + resolution UI". Nothing anywhere describes it. The five
resolution actions in `schema.ResolutionAction` are the only fixed part of its contract.

## 8. Retrieval tuning

Unspecified: reranker approach, embedding dimensionality, HNSW/IVF index parameters, and
the vector-store product itself. The TRS explicitly defers all of these as design decisions.

---

## Externally dependent — verify, don't assume

These are claims from the source documents that carry their own "confirm before relying on
this" caveats. They are reproduced in code comments and the compliance/tax tabs will
surface them, but none should be treated as settled.

- **IEEE 2800-2022 Clause 8 TRD limits** — the TRS gives ~2.0% above 161 kV, 2.5% for
  69–161 kV, 5.0% at or below 69 kV, and flags the TRD-vs-TDD distinction as the key
  correction from v1. Confirm the exact numbers against the purchased standard.
- **Tax mechanics** — ITC section 48E, the 50% domestic-content adjusted percentage for
  2026 starts, BABA thresholds, and FEOC material-assistance ratios per Notice 2026-15.
  Requires tax counsel against statute and final Treasury guidance.
- **Standards editions and effective dates** — UL 9540A 6th Edition, NFPA 855 2026,
  NERC PRC-029-1 effective October 2026. Confirm for the actual SGIA and AHJ.
- **BABA applicability** — hinges entirely on whether federal funding is in the project.
  Unconfirmed in the FRD. If privately financed, BABA is N/A and tab 13 changes shape.
- **Dependency licences** — the reference memo flags Surya (GPL-3.0), MinerU (AGPL-3.0),
  olmOCR (Rail-M revenue cap) and LayoutLM (research-only history) as unusable or
  uncertain for a commercial product. Re-confirm at integration time; licences change
  per release.
