# Agent topology and parallel dispatch

Where this pipeline should fan out, where it must stay serial, and what a "team" of
differentiated agents actually buys.

Scope note: the implementation spec under `specs/001-procurement-agent/` decides the
*runner* — a Postgres stage state machine with a `SELECT … FOR UPDATE SKIP LOCKED`
worker loop (Decision 1), synchronous ports (Decision 10). This document is about
what to hand that runner: which stages are worth parallelising, which must not be,
and where differentiated agents earn their keep rather than being personas wrapped
around function calls.

---

## Three things get conflated under "multi-agent"

Separating them is most of the analysis.

| | Shape | What it buys | Cost |
|---|---|---|---|
| **Fan-out** | Same code, many items | Throughput | Ordering, retries, rate limits |
| **Team** | Different roles, different corpora and tools | Domain separation | Roster maintenance, handoff schema |
| **Ensemble** | Several agents on the *same* item | Confidence | Tokens, and a correctness trap (below) |

This pipeline wants a lot of the first, a little of the second, and needs the third
handled with care because of FR-HITL-02.

---

## Stage-by-stage

| Stage | Unit of work | Kind | Verdict |
|---|---|---|---|
| `ingest` | one document | fan-out | **The dominant win.** NFR-06 says hundreds of documents; parse and OCR are the expensive steps, averaging 3.1 s/page on CPU with a 16 s p95 tail. `content_hash` is the intended dedup key (NFR-05), but it is an unconstrained field today — NFR-05 is `declared` and AC-5 `open`, so a retry after a partial commit can still duplicate. Transactional hash uniqueness is a prerequisite for calling retries free, not a consequence of the field existing. Process pool — CPU-bound, so threads buy nothing. |
| `extract` | document × category field set | fan-out, some team | Yes. TRS §7 field sets differ enough per category that the extractors are naturally role-shaped. Branches return **claims** keyed by contract C8's immutable claim identity — `ordering_key()` orders workbook rows and cannot distinguish two extractors' competing values for the same component field. |
| `index` | chunk batch | fan-out | Yes, but the parallelism is already *inside* the payload — embedding and reranking take batches, so the call boundary rarely needs widening. |
| `retrieve` | one query | fan-out | Low priority. Latency-bound, and NFR-07 allows seconds-to-minutes. |
| `enrich_via_web` | one gap field | fan-out | Yes, capped hardest. Rate-limit bound, least idempotent, and every query must be logged for reproducibility (FR-WEB-02) regardless of outcome. |
| `detect_conflicts` | one field's candidate set | fan-out + ensemble | Yes, with the recall constraint below. Use `comparison_pairs` — comparability is genuinely not transitive, so it cannot be a partition, and exact-key grouping strands a less-specific system-of-record claim so it never reaches a queue entry. `grouping_key()` is for display. See #12. |
| `compose_workbook` | 13 tabs | none | **No.** FR-OUT-06 requires deterministic regeneration. openpyxl composition is cheap; parallelising it buys nothing and risks exactly the ordering nondeterminism the requirement forbids. |

---

## Where a genuine team earns its keep

Only two places, and neither is Stage 1.

**The parser router.** `ports/` anticipates several `ParserPort` implementations
selected by content signature. The reference memo goes one step further — fall back
to a second engine and reconcile. That is a two-engine race with a reconcile step on
documents where the router is uncertain, and on table-heavy spec sheets the fidelity
difference is the whole point.

**Tabs 12 and 13.** TRS §8.2 is explicit that the tax rules are *three distinct
frameworks (keep separate)*: ITC §48E, BABA (2 CFR 184), and FEOC material
assistance (Notice 2026-15). Different source corpora, different clocks (solar
begin-construction ≤ Jul 4 2026 versus storage through 2033), and different
applicability gates — BABA is N/A outright if the project is privately financed.
Add ERCOT/PUCT/TCEQ compliance for tab 12 and there are four specialists with
disjoint authorities and no shared state. The cleanest team boundary in the spec,
and it is Stage 4 work.

Everywhere else, "agent" would be a persona wrapped around a function call.

---

## The constraints that govern all of it

### An ensemble may decide *whether to surface*, never *which value wins*

The easiest point here to get backwards. Since first written it has gained a
home in the spec: `tasks.md` E.3a says the same thing in near-identical terms.

FR-HITL-02 forbids auto-arbitration between web and an ingested contract or spec
sheet. The adversarial-verify pattern — spawn N skeptics, kill the finding if a
majority refute it — is directly hazardous: a 2-of-3 vote that suppresses a real
conflict is a spec violation, not a false positive saved.

Invert it. **Union, not vote:** any single detector raising a conflict surfaces it;
additional agents only improve the generated explanation (FR-HITL-03) and the
classification (FR-HITL-01). Stage 3's exit threshold confirms the bias — *100% of
injected conflicts surfaced* is a recall target, and recall targets do
not survive majority voting.

### Parallel workers propose; a single reducer commits

`assert_no_autonomous_overwrite` is a single chokepoint, and AC-2 tests the guard
*function* — not that every writer calls it. With one serial writer that is
academic; with N `SKIP LOCKED` workers it is the difference between an enforced
invariant and an honour system N code paths must remember. Adopted as contract C8;
the test that a branch cannot bypass the guard is still owed (#8).

### The audit log needs an append order

FR-HITL-06 and NFR-02 require an immutable log of every web query, extraction,
conflict and resolution, and concurrent appenders have no total order without one.

Governed by **plan Decision 9**, not by this document. An earlier draft here
proposed a `BIGSERIAL` sequence "scoped by `run_id`", which is not a thing a
`BIGSERIAL` does — it is one table-level sequence, it is allocation order rather
than commit order, and it carries no tamper evidence. Decision 9 specifies
privilege separation as the boundary, per-document-stream hash chaining, and
audit insertion in the same transaction as the business write. Follow that.

### Deterministic merge

Fan-out results arrive in completion order and must be sorted before composition or
FR-OUT-06 fails. Settled: `ComponentInstance.ordering_key()`, with `surrogate_id` as
the tie-break because `(category, supplier, model)` is provably not unique on real
CEC data.

---

## Sequencing

| Stage | Concurrency to add | Prerequisite |
|---|---|---|
| 1 | Fan-out on `ingest` | Concurrency caps in `Settings` (land #10) + transactional dedup |
| 2 | None beyond batch-internal. Composition stays serial | — |
| 3 | Fan-out on web gaps and conflict detection, union-aggregated | Tolerance table (D-2) |
| 4 | The compliance and tax specialist team | Tabs 12–13 field sets |

Highest payoff and lowest risk agree: ingestion fan-out has no shared state and
addresses the requirement (NFR-06) that most obviously needs it. It is not yet
idempotent — see the `ingest` row above and item 2 below; that is a prerequisite
for the stage, not a property of it.

---

## Still open

1. **A test that fan-out branches cannot write to the canonical store** (#8). The
   contract exists; the enforcement does not.
2. **Transactional dedup** — a unique constraint and upsert on `content_hash`,
   plus per-stage idempotency, before retry-is-free holds (NFR-05, AC-5).
3. **Severity assignment rule.** `Severity` and the compose gate land with #10;
   what assigns a severity to a detected conflict is still a judgement call, and
   `specs/001-procurement-agent/open-decisions.md` §1 proposes the lookup.
