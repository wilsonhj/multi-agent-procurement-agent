# Phase 1 execution plan — parallel tracks after the Phase 0 decision freeze

**Date:** 2026-08-08 · **Baseline:** `main` at `3b4e271` · **Status:** proposed

> **This is about development-time agents, not runtime fan-out.**
> [agent-topology.md](../../docs/agent-topology.md) governs where the *pipeline* may parallelise
> at run time and opens by warning that three different things get conflated under
> "multi-agent". This document is the third of those: how to divide *building* the remaining work
> across concurrent workers. Nothing here changes a runtime constraint, and in particular the
> single-reducer and audit-append-order rules in that document are untouched.

---

## Why now

Phase 0's decision half is complete. D-13 (C4 canonicalisation), D-14 (C6 projection) and D-15
(C7 labelling, provisional) were ratified on 2026-08-07, and the licence is settled.

**No implementation number moved.** Verified against the tree at `3b4e271`:

| Measure | Before the decisions | After |
|---|---|---|
| Contracts | 3 done · 4 partial · 1 untouched | **unchanged** |
| Requirements | 10 enforced · 23 partial · 17 declared · 6 open | **unchanged** |
| `raise NotImplementedError` in `src/` | 10 | **unchanged** |

That is the correct reading of the situation and the reason this plan exists: the gate opened and
nobody has walked through it. Two work packages were blocked on decisions rather than on code, and
both are now unblocked — **WP-H** (audit library, which `tasks.md` says "must land first") and
**WP-G** (workbook composition).

---

## The interface technique, restated

`tasks.md` already specifies how these teams stay decoupled, and this plan does not invent a new
mechanism:

> Each team builds against **committed fixture files** matching the frozen schemas. WP-B ships
> golden claim JSON; WP-E consumes it and ships golden conflict JSON; WP-F and WP-G consume that.
> **Nobody waits on anybody's service.**

`tests/fixtures/` now exists with claim and conflict sets, validated three ways
(see [`tests/fixtures/README.md`](../../tests/fixtures/README.md)). **A track's deliverable is not
"the code works" — it is "the fixture the next track consumes exists and is asserted."**

---

## Tracks

Dependencies are on **artifacts**, not on teams finishing. A track may start as soon as the
artifact it consumes is committed.

| # | Track | Depends on | Owns these paths | Parallel? |
|---|---|---|---|---|
| **0** | Reconcile the tracking docs | — | `sql/07_audit_event.sql` (comments), `sql/README.md`, `tasks.md`, `docs/current-state.md`, `docs/requirements-traceability.md` | **must land first** |
| **1** | `encode_value()` + A-50 convergence | 0 | `src/procurement_agent/schema/encoding.py` (new), `services/conflict_hitl/__init__.py` | after 0 |
| **2** | WP-H — audit library | 0 | `src/procurement_agent/audit/` (new), `pyproject.toml` | after 0, ∥ 1 |
| **3** | WP-G — C6 projection + T0.5 fixture | 1 | `services/output/__init__.py`, `tests/fixtures/workbooks/` | after 1 |
| **4** | NFR-04 port conformance suite | — | `tests/port_contracts/` (new), `src/procurement_agent/adapters/` (new) | fully ∥ |
| **5** | C2 field registry | — | `schema/registry.py` (new), `conflict_hitl/tolerance.py`, `services/confidence/` | fully ∥ |

Tracks **4** and **5** share no path with anything and can start immediately.

---

### Track 0 — Reconcile the tracking docs · *serial prerequisite, ~1 hour*

**Why it blocks.** `sql/07_audit_event.sql`'s caller-sequence comment still sketches
`hash := sha256(prev_hash || canonical_payload || ...)`. D-13 replaced that with a single JCS
object. **An implementer who starts from the DDL rather than from the decision builds the wrong
preimage**, and a wrong preimage is the failure mode D-13 names as worst: chains that verify under
the buggy implementation and fail under any correct one.

Verified gap — all four tracking documents mention D-13, D-14 and D-15 **zero** times:
`tasks.md`, `sql/README.md`, `docs/current-state.md`, `docs/requirements-traceability.md`.

**Scope:** update `sql/07`'s comment to the JCS object form; mark `sql/README.md` decisions 5–7
settled by D-13; update the C1–C8 table and T0.4/T0.5 in `tasks.md`; refresh `current-state.md`
and the traceability rows for C4/C6/C7.

**Verify:** `grep -c "D-1[345]"` returns non-zero in each of the four files, and `sql/07` contains
no `||`-concatenation hash sketch.

---

### Track 1 — `encode_value()` and the A-50 convergence · *small, unblocks Track 3*

**Where it lives is decided by an existing rule.** `schema/component.py:74` states that
**`schema` sits below `services` and cannot import it**. `encode_value()` encodes schema types —
`DeclaredBand`, datetimes, enums, frozensets — so it belongs in `schema/`, where both
`services/output` (projection) and `services/conflict_hitl` (ordering) can use it without either
depending on the other.

**Scope:** implement `encode_value()` exactly as D-14 freezes it — `DeclaredBand` via
`model_dump`, datetimes as RFC 3339 UTC with microseconds always printed, enums via `.value`,
frozensets sorted. Then close A-50's residual by routing `_ordering_key` and
`conflict_groupings` (`conflict_hitl/__init__.py:175`) through it instead of `repr()`.

**Verify:** a test asserting no encoded output contains a Python `repr()` artifact — concretely,
that `"<" not in encoded` for every enum-bearing field, which is what would have caught A-50. Plus
the existing `_ordering_key` totality tests, which must still pass: convergence must not
reintroduce a tie.

> ⚠️ **This changes sort order.** `comparison_pairs` and `conflict_groupings` currently order by
> `repr()`. Encoded ordering may differ. Expect `test_comparison_pairs.py` and
> `test_condition_grouping.py` to need re-baselining, and treat any change in *pair membership*
> (as against pair order) as a defect, not a re-baseline.

---

### Track 2 — WP-H, the audit library · *largest track, "must land first" per tasks.md*

**Deadline that expires by being ignored:** D-13's version marker must exist **before the first
audit event is ever emitted**. Nothing has been emitted, so the window is open — it closes the
moment this track writes a row.

**Scope:** H.2 canonicalisation (add `rfc8785`, pinned; Apache-2.0, zero runtime deps — verified
at PyPI), H.3 the envelope and preimage exactly as D-13 §2 specifies, H.4 the pre-`INSERT`
advisory lock, H.5 the chain-verification CLI.

**Two things this track must not get wrong**, both already written down and both easy to miss:

- The preimage is **one JCS object**, and `payload` embeds as the **parsed JSON object**, not the
  `payload_canonical` string. Both readings are "obvious" and they hash differently.
- The advisory lock is **its own statement before the `INSERT`**, never inside a trigger. `sql/07`
  records the measurement: 8 concurrent writers produced **42 silent forks** without it.

**Verify:** the six existing live chain tests pass **unchanged** — named, so this is checkable
rather than countable: `test_a_valid_chain_appends`, `test_a_fabricated_parent_is_refused`,
`test_a_second_disconnected_root_is_refused`, `test_a_chain_loop_is_refused`,
`test_a_fork_is_still_refused`, `test_a_duplicate_genesis_is_still_refused`
(`tests/test_sql_behaviour.py:387-423`, all taking the `chain` fixture). A new conformance test
runs `rfc8785` against RFC 8785's own published vectors — the whole argument for a library over
hand-rolling is that its conformance is somebody else's problem *only once you have checked it*.
And a written concurrency load test for the advisory lock, the property `sql/README.md` names as
still unproven.

---

### Track 3 — WP-G, the C6 projection and the T0.5 golden fixture · *consumes Track 1*

**Scope:** G.1's projection function emitting D-14's canonical bytes, and the golden fixture T0.5
asks for — one committed projection plus its hash for a synthetic two-supplier PV store containing
D-1's Sungrow trio, so it exercises list-valued fields rather than the easy one-value-per-key case.

**Verify:** the fixture passes the three checks in `tests/fixtures/README.md`; two generations from
an unchanged store are byte-identical; `generated_on` folds from timestamps **inside the
projection**, not from a parallel query — a separate query drifts silently the day someone adds a
row type and forgets it.

> This track ships the projection, **not the xlsx writer**. G.2–G.8 and the gating G.6
> desktop-Excel test follow once the hashed artifact of record exists.

---

### Track 4 — NFR-04 port conformance suite · *fully independent*

**The weakest requirement in the repo.** Six Protocols, zero adapters, and **no test imports
`ports` at all** — which is why NFR-04 sits at `declared`.

Both external repos reviewed in [ADR-001](../../docs/decisions/ADR-001-cross-repo-pattern-adoption.md)
independently invented the same answer, and ADR-001 decision 2 already adopts it: **one contract
suite parametrised over implementations**, not per-adapter tests. `predict-rlm` runs one suite
across three execution backends; `avalanche` runs ~58 storage cases across two.

**Scope:** a capability-declaring conformance matrix plus one in-memory reference adapter per
port, sufficient to make the suite non-vacuous.

**Verify:** the first tests that import `ports`; NFR-04 moves off `declared`. Note honestly that a
suite passing against only an in-memory reference proves the *contract is expressible*, not that
any real adapter satisfies it.

---

### Track 5 — C2 field registry · *fully independent, largest remaining contract*

**Scope:** a machine-readable `FieldSpec` registry in `schema/`, bidirectionally tested against
`contracts/canonical-parameters.md` the way the Conditions table already is. Then consolidate the
**three** places contract keys are currently duplicated as data — the frozen markdown,
`FIELD_TOLERANCES`, and `services/confidence`'s tier table — so there is one authority.

**Verify:** the bidirectional test; a claim carrying an off-contract key for its category is
rejected at the boundary.

> **Urgency, since C2 looks deferrable:** claims are append-only. An extractor emitting
> off-contract keys fills the claim table with rows that can only be superseded, never fixed, and
> the B.9 gold set gets labelled against wrong keys.

---

## Clarifications needed

Two are blocking, in the sense that a track will guess if nobody answers.

| # | Question | Blocks | Who |
|---|---|---|---|
| C-1 | D-15's two facts: does any executed NDA go beyond "Representatives with a need to know", and is anyone on the evaluation conflicted with a specific bidder? | C7 / T0.4 finalisation, and it wants settling **before real documents land**, since labelling happens at ingest | Procurement lead — this is a fact, not a preference |
| C-2 | Does Track 1's convergence change *pair membership* anywhere, or only pair order? | Track 1's re-baselining is routine if order-only, a defect if membership | Answerable by the track itself; flag if membership moves |
| C-3 | Should `_ordering_key` converge on `encode_value()` (Track 1's plan) or should the projection define its own sort and leave `_ordering_key` alone? | Track 1 scope | Recommend convergence — one key beats two that must agree |
| C-4 | Who holds copyright for `NOTICE`? Currently "The procurement-agent authors" | Nothing; cosmetic but visible | Maintainer |

Non-blocking but worth stating: the **gold set (B.9 / D-11)** is not in any track because no agent
can produce it. Thirty to fifty labelled documents gate every accuracy claim in the plan, and
every figure currently in `plan.md` is extrapolated from other domains.

---

## Cross-artifact analysis

### Path collisions

Tracks own disjoint paths **except two**, both resolved by ordering rather than coordination:

- **Track 0 and Track 2 both touch `sql/07_audit_event.sql`.** Track 0 owns the comment; Track 2
  must not edit that file. Track 0 lands first, so this is a sequencing rule, not a merge conflict.
- **Track 1 and Track 5 both touch `services/conflict_hitl/`** — but different files
  (`__init__.py` versus `tolerance.py`). Safe in separate worktrees; verify at merge.

Use **worktree isolation** for any track that edits code. Agents running `pytest` concurrently in
one tree read each other's half-written files and produce untrustworthy signals — this is a
measured hazard in this project's history, not a hypothetical.

### Merge order

`0 → (1 ∥ 2 ∥ 4 ∥ 5) → 3`. Track 3 is the only one with a hard predecessor beyond Track 0.

### Risks specific to this plan

- **Track 1 is small and load-bearing.** Three tracks' correctness depends on `encode_value()`
  being right. It should land with its own tests before Track 3 starts, not alongside.
- **Track 2 has the only expiring deadline.** Every other track can slip without consequence; if
  WP-H emits an event without D-13's `"v"` marker, every chain written before the fix becomes
  unverifiable.
- **A-50's class has now recurred three times** — unpinned `openpyxl`, `repr(grouping_key())` in
  the condition-group sort, and `_ordering_key` reintroducing it inside the fix for the second.
  Any track touching hashed bytes should assume a fourth instance exists and look for it: the
  question to ask of every value entering the artifact is *"could this change without the data
  changing?"*
- **Verification hygiene.** Five times in this project's recent history a check reported success
  from a command that never ran — `wc -l` on a failed `git show`, a glob eaten by zsh, `ls | head`
  masking a missing directory, `gh pr checks` reporting a stale commit's status. Prefer checks
  whose output is a *count* over checks whose output is a message, and bind CI checks to a head
  SHA rather than to a PR-level summary.

### What this plan does not cover

WP-A through WP-F and WP-I. They remain blocked on C2, C7 and C8, and on the gold set. Tracks 4
and 5 chip at those blockers; nothing here starts an ingestion path.
