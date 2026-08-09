# Phase 1 execution plan — parallel tracks after the Phase 0 decision freeze

**Date:** 2026-08-08 · **Baseline:** `main` at `3b4e271` · **Status:** proposed

> **This is about development-time agents, not runtime fan-out.**
> [agent-topology.md](../../docs/agent-topology.md) governs where the *pipeline* may parallelise
> at run time and opens by warning that three different things get conflated under
> "multi-agent". This document is the third of those: how to divide *building* the remaining work
> across concurrent workers. No runtime constraint changes.

D-13, D-14 and D-15 were ratified on 2026-08-07 and the licence is settled. **No code has moved
since** — contracts remain 3 done / 4 partial / 1 untouched, requirements 10 enforced / 23
partial / 17 declared / 6 open, and ten `NotImplementedError` stubs stand. The decisions *were*
the binding constraint, so this is progress; it is just not implementation. The gate opened and
nobody has walked through it. Two work packages were blocked on judgement rather than effort and
are now free: **WP-H** (audit library, which `tasks.md` says "must land first") and **WP-G**.

## The interface technique, restated

`tasks.md` already specifies how these teams stay decoupled and this plan does not invent a new
mechanism:

> Each team builds against **committed fixture files** matching the frozen schemas. WP-B ships
> golden claim JSON; WP-E consumes it and ships golden conflict JSON; WP-F and WP-G consume that.
> **Nobody waits on anybody's service.**

**A track's deliverable is not "the code works" — it is "the artifact the next track consumes
exists and is asserted."**

---

## Tracks

**This table is the single source for dependencies.** Prose sections below explain *why*; where
prose and table disagree, the table wins. An earlier revision stated edges in three places and
they drifted apart within one commit.

**Needs** means *this track cannot begin until that artifact is committed* — an artifact
dependency, not a scheduling preference. Merge ordering is separate and stated below the table.

| # | Track | Needs | Team | Owns these paths |
|---|---|---|---|---|
| **0** | Reconcile the tracking docs | — | 1 | `sql/07_audit_event.sql` (comments), `sql/README.md`, `specs/001-procurement-agent/tasks.md`, `docs/current-state.md`, `docs/requirements-traceability.md` |
| **1a** | `encode_value()` | 0, **Q-2** | 1 | `src/procurement_agent/schema/encoding.py` (new) |
| **1b** | A-50 convergence | 1a | 5 | `src/procurement_agent/services/conflict_hitl/__init__.py` |
| **2** | WP-H — audit library | 0 (`sql/07` comment only) | 1 | `src/procurement_agent/audit/` (new), `pyproject.toml` |
| **3** | WP-G — C6 projection + T0.5 fixture | 1a | 6 | `src/procurement_agent/services/output/`, `tests/fixtures/workbooks/` |
| **4** | NFR-04 port conformance suite | — | **4?** | `tests/port_contracts/` (new), `src/procurement_agent/adapters/` (new) |
| **5** | C2 field registry | — | **5?** | `src/procurement_agent/schema/registry.py` (new), `schema/component.py`, `services/claims/__init__.py`, `conflict_hitl/tolerance.py`, `services/confidence/`, `tests/fixtures/claims/` |

**Start order** — 0, 4 and 5 begin immediately; 4 and 5 share no path with Track 0 and need not
wait for it.

**Merge order** — `0 → 1a → (1b ∥ 3)`; `2` and `4` merge whenever ready. **`5` should merge before
`3`**, which is a preference rather than a dependency: Track 3's fixture store must be built with
on-contract keys, and landing 5 first means Track 3 finds out at build time rather than at merge.
Track 3 does not consume anything Track 5 produces.

**Two team assignments are unresolved** and need a decision, not a paragraph. `tasks.md:301`'s
allocation covers WP-A..WP-I; Tracks 4 and 5 map onto nobody — **no work package owns `ports/`
at all**, and Track 5 cuts across WP-B's tier table (Team 3) and WP-E's tolerance table (Team 5).
Proposed above: Track 4 → Team 4 (already owns the vector-store surface), Track 5 → Team 5 (owns
the largest consumer) with Team 1 reviewing as contract owner. Note that this leaves **Team 1
holding 0, 1a and 2** — the critical path runs through one team, which is a scheduling fact worth
seeing rather than discovering.

---

### Track 0 — Reconcile the tracking docs · *~1 hour*

**Why it blocks.** `sql/07_audit_event.sql:34` still sketches
`hash := sha256(prev_hash || canonical_payload || ...)`. D-13 replaced that with a single JCS
object. An implementer starting from the DDL rather than the decision builds the wrong preimage —
D-13's own worst case: chains that verify under the buggy implementation and fail under any
correct one.

Verified: all four tracking documents mention D-13/14/15 **zero** times.

**Land the `sql/07` comment as the first commit**, separately. That single edit is all Track 2
actually waits on; the rest of Track 0 can follow without holding anyone.

**Scope:** the `sql/07` comment; `sql/README.md` decisions 5–7 marked settled by D-13; the C1–C8
table and T0.4/T0.5 in `tasks.md`; `current-state.md` and the C4/C6/C7 traceability rows.

**Verify:** `grep -c "D-1[345]"` non-zero in each of the four files, and no `||`-concatenation
hash sketch remains in `sql/07`.

---

### Track 1a — `encode_value()` · *small, gates Track 3*

**Placement is decided by an existing rule.** `schema/component.py:74` states **`schema` sits
below `services` and cannot import it**. `encode_value()` encodes schema types, so `schema/` is
the only placement letting both consumers — `services/output` (Track 3) and
`services/conflict_hitl` (Track 1b) — use it without either depending on the other.

**Scope:** implement it exactly as D-14 freezes it — `DeclaredBand` via `model_dump`, datetimes
as RFC 3339 UTC with microseconds always printed, enums via `.value`, frozensets sorted.

> ⚠️ **D-14's `encode_value()` has no `Decimal` rule, and it needs one before this is written.**
> `conflict_hitl/__init__.py:332` records that "`Decimal("650")` is the natural representation"
> of D-2's EXACT catalog values, so `Decimal` is genuinely in the value domain. Under `repr()`,
> `Decimal("650")`, `650` and `650.0` are three distinct keys. A naive encoder collapses them.
>
> **A collapse is worse than a wrong order.** `sorted()` is stable, so a tie does not reorder —
> it leaks *arrival* order, which is the exact defect `_ordering_key`'s docstring records
> shipping twice. Amend D-14 with a `Decimal` rule, then require the encoder be **injective over
> the candidate value domain**, or compose a type tag into the key.

**Verify:** no encoded output contains a `repr()` artifact — concretely `"<" not in encoded` for
every enum-bearing field, which is what would have caught A-50; plus an injectivity test over
`{Decimal("650"), 650, 650.0, "650"}` and the datetime/string pair.

---

### Track 1b — the A-50 convergence · *blocks nobody*

Route `_ordering_key` and `comparison_groups` (`conflict_hitl/__init__.py:175`) through
`encode_value()` instead of `repr()`. This is the A-50 residual. It gates no other track, and
carries all of this plan's re-baselining risk — which is why it is separated from 1a.

**Pair membership cannot change, and this is provable rather than open.** `comparison_pairs` is
`itertools.combinations(sorted(candidates, key=_ordering_key), 2)` filtered by
`condition.comparable_with`. Combinations over a fixed input set is invariant under permutation,
and this track does not touch `comparable_with`. So a sort-key change alters list order and
within-pair orientation only.

**Therefore:** `test_comparison_pairs.py` and `test_condition_grouping.py` may need re-baselining,
and **the diff must be reviewed as permutation-only** — same multiset of unordered pairs,
orientation flips allowed, nothing else. Anything more is a defect, not a re-baseline.

> Pre-announcing "expect re-baselining" disarms the golden test during exactly the change most
> likely to smuggle in an encoding defect. The permutation-only check is what keeps the safety net
> up while the floor moves.

---

### Track 2 — WP-H, the audit library · *highest risk*

**Scope:** H.2 canonicalisation, H.3 the envelope and preimage per D-13 §2, H.4 the pre-`INSERT`
advisory lock (see `tasks.md` H.4 for the measured failure), H.5 the chain-verification CLI.

**The one trap not already written down elsewhere:** the preimage is one JCS object, and
`payload` embeds as the **parsed JSON object**, not the `payload_canonical` string. Both readings
are "obvious" and they hash differently.

**Deferred, and stated so "must not edit `sql/07`" is not read as permanent:** D-13 also assigns
WP-H the `audit.run_event` table and the taxonomy amendment removing the unreachable `web_search`
value (A-49). Both need `sql/` changes and neither is in this track, because no emitter exists in
this plan's horizon. They land when WP-H writes its first emitter.

**Verify:** the six existing live chain tests pass **unchanged** — `test_a_valid_chain_appends`,
`test_a_fabricated_parent_is_refused`, `test_a_second_disconnected_root_is_refused`,
`test_a_chain_loop_is_refused`, `test_a_fork_is_still_refused`,
`test_a_duplicate_genesis_is_still_refused` (`tests/test_sql_behaviour.py:387-423`, all taking the
`chain` fixture). A conformance test runs `rfc8785` against RFC 8785's published vectors — the
argument for a library over hand-rolling is that its conformance is somebody else's problem *only
once you have checked it*. And **a concurrency load test for the advisory lock is a merge
blocker**, not a bullet: it is the one property `sql/README.md` names as still unproven, and
everything else in this track's verify already exists.

> ⚠️ **Pin `rfc8785` as hash-stability-critical.** It is 0.1.4 and not yet in `uv.lock`. A
> behaviour change in a 0.x canonicalisation library is A-6's class wearing a dependency hat —
> the same reasoning that pinned `openpyxl==3.1.5` exactly.

---

### Track 3 — WP-G, the C6 projection and the T0.5 golden fixture

**Needs only Track 1a — it does not consume anything Track 5 produces**, though 5 should merge
first (see the merge-order note). D-14 specifies the projection sorts by `_ordering_key`'s *field
sequence* with components routed through `encode_value()` — **not** by `_ordering_key` itself — so
this track never imports `conflict_hitl` and does not wait on 1b.

**Scope:** G.1's projection emitting D-14's canonical bytes, plus the T0.5 golden fixture — one
committed projection and hash for a synthetic two-supplier PV store containing D-1's Sungrow trio,
so it exercises list-valued fields rather than the easy one-value-per-key case.

**Build the fixture store with on-contract keys**, or Track 5's landing breaks it.

**Verify:** the fixture passes the three checks in `tests/fixtures/README.md`; two generations from
an unchanged store are byte-identical; `generated_on` folds from timestamps **inside the
projection**, not from a parallel query — a separate query drifts silently the day someone adds a
row type and forgets it.

> Ships the projection, **not** the xlsx writer. G.2–G.8 and the gating G.6 desktop-Excel test
> follow once the hashed artifact of record exists.

---

### Track 4 — NFR-04 port conformance suite · *fully independent*

Implements [ADR-001](../../docs/decisions/ADR-001-cross-repo-pattern-adoption.md) decision 2: a
capability-declaring conformance matrix plus one in-memory reference adapter per port.

**The six ports are enumerated at `src/procurement_agent/ports/__init__.py`** — `ParserPort`,
`OCRPort`, `EmbedderPort`, `VectorStorePort`, `RerankerPort`, `LLMPort`. ADR-001 flags this as
the highest-stakes convention call in the repo, quoting `development.md`: the first adapter
"decides the layout for everyone after it." **Choosing `adapters/`'s layout is part of this
track's deliverable**, not a side effect of it.

**Verify:** the first tests that import `ports`; NFR-04 moves off `declared`. State honestly that
a suite passing against an in-memory reference proves the *contract is expressible*, not that any
real adapter satisfies it.

---

### Track 5 — C2 field registry · *largest remaining contract*

**Scope:** a machine-readable `FieldSpec` registry in `schema/`, bidirectionally tested against
`contracts/canonical-parameters.md` the way the Conditions table already is; then consolidate the
three places contract keys are duplicated as data — the frozen markdown, `FIELD_TOLERANCES`, and
`services/confidence`'s tier table — into one authority.

**Three paths this track must own that are easy to miss.** Rejecting an off-contract key needs
**two** enforcement points, and neither is in `schema/field.py` — `FieldClaim` lives at
`services/claims/__init__.py:44`, and `schema/field.py` holds `CanonicalField`, `SourceRef` and
the condition types instead. The keys are validated where they are *used as keys*:
`ComponentInstance.fields` (`schema/component.py:83`, the `dict[str, list[CanonicalField]]`) and
`commit_claims` (`services/claims/__init__.py:346`). Third, tightening either can break the
**byte-compared** committed fixtures in `tests/fixtures/claims/`, which must be re-validated as
part of this track rather than discovered by Track 3.

**Verify:** the bidirectional test; a claim carrying an off-contract key for its category is
rejected at the boundary; `tests/test_fixtures.py` still passes.

> **Why this is not deferrable:** claims are append-only. An extractor emitting off-contract keys
> fills the claim table with rows that can only be superseded, never fixed, and the B.9 gold set
> gets labelled against wrong keys.

---

## Clarifications needed

| # | Question | Blocks | Who |
|---|---|---|---|
| Q-1 | D-15's two facts: does any executed NDA go beyond "Representatives with a need to know", and is anyone on the evaluation conflicted with a specific bidder? | C7 finalisation; hardens at first ingest | Procurement lead — a fact, not a preference |
| Q-2 | Does D-14 get a `Decimal` rule, and is the encoder required to be injective? | Track 1a — must be answered *before* the encoder is written | Maintainer + Team 1 |
| Q-3 | Team assignment for Tracks 4 and 5 | Both start immediately, so this is the first thing to settle | Maintainer |
| Q-4 | Who holds copyright for `NOTICE`? Currently "The procurement-agent authors" | Nothing; cosmetic but visible | Maintainer |

The **gold set (B.9 / D-11)** is in no track because no agent can produce it.

---

## Cross-artifact analysis

### Path collisions — three, not two

- **Track 0 and Track 2 on `sql/07_audit_event.sql`.** Track 0 owns the comment; Track 2 must not
  edit the file. Resolved by ordering, not coordination.
- **Track 1b and Track 5 on `services/conflict_hitl/`** — different files (`__init__.py` versus
  `tolerance.py`).
- **Track 1a and Track 5 on `schema/`** — different new files (`encoding.py` versus
  `registry.py`), and Track 5 additionally edits the existing `field.py`. Structurally the same as
  the case above, and both tracks touch the module each independently calls foundational.

Use **worktree isolation** for every track that edits code. Agents running `pytest` concurrently
in one tree read each other's half-written files and produce untrustworthy signals — a measured
hazard in this project's history, not a hypothetical.

### Three windows, and only one is irreversible

The plan's tracks can spring only the first, but the other two arm at events these tracks
accelerate, so ranking them matters:

| Window | Arms at | Reversible? |
|---|---|---|
| D-13's `"v"` marker | WP-H's first emitted event — **in this plan** | **No.** Every chain written before a fix becomes unverifiable |
| Off-contract claim keys | WP-B's first claim write | **Not in data.** Claims are append-only; wrong keys can be superseded, never fixed |
| C7's label model | WP-A's first ingest | **Yes, at cost.** `access_restricted` has a narrow UPDATE path and restriction derives on read, so the retrofit is ~40 policies — code, not data |

### Risks specific to this plan

- **Track 1a is small and load-bearing.** Two tracks depend on the encoder being right, and the
  `Decimal` gap above means it is not yet fully specified.
- **A-50's class has recurred three times** — unpinned `openpyxl`, `repr(grouping_key())` in the
  condition-group sort, and `_ordering_key` reintroducing it inside the fix for the second. Assume
  a fourth exists. The question to ask of every value entering a hashed artifact: *could this
  change without the data changing?*
- **Verification hygiene.** Repeatedly in this project's recent history a check reported success
  from a command that never ran — `wc -l` on a failed `git show`, a glob eaten by zsh,
  `ls | head` masking a missing directory, `gh pr checks` reporting a stale commit's status.
  Prefer checks whose output is a **count** over checks whose output is a message, and bind CI
  checks to a head SHA rather than a PR-level summary.

### Not covered

WP-A through WP-F and WP-I. They remain blocked on C2, C7 and C8, and on the gold set. Tracks 4
and 5 chip at those blockers; nothing here starts an ingestion path.
