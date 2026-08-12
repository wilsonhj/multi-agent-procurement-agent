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
| **0** | ~~Reconcile the tracking docs~~ **DONE** (#33, merged `b32e04b`) | — | 1 | `sql/07_audit_event.sql` (comments), `sql/README.md`, `specs/001-procurement-agent/tasks.md`, `docs/current-state.md`, `docs/requirements-traceability.md` |
| **1a** | ~~`encode_value()`~~ **DONE** (`3a3af5c`) | 0 ✅ | **6** | `src/procurement_agent/schema/encoding.py` (new), `tests/test_encoding.py` (new) |
| **1b** | A-50 convergence | 1a | 5 | `src/procurement_agent/services/conflict_hitl/__init__.py` |
| **2** | WP-H — audit library | 0 (`sql/07` comment only) | 1 | `src/procurement_agent/audit/` (new), `pyproject.toml` |
| **3** | WP-G — C6 projection + T0.5 fixture | 1a | 6 | `src/procurement_agent/services/output/`, `tests/fixtures/workbooks/` |
| **4** | NFR-04 port conformance suite | — | 4 | `tests/port_contracts/` (new), `src/procurement_agent/adapters/` (new) |
| **5** | C2 field registry | — | 5 | `src/procurement_agent/schema/registry.py` (new), `schema/component.py`, `services/claims/__init__.py`, `conflict_hitl/tolerance.py`, `services/confidence/`, `tests/fixtures/claims/` |

**Start order** — 0, 4 and 5 begin immediately; 4 and 5 share no path with Track 0 and need not
wait for it.

**Merge order** — `0 → 1a → (1b ∥ 3)`; `2` and `4` merge whenever ready. **`5` should merge before
`3`**, which is a preference rather than a dependency: Track 3's fixture store must be built with
on-contract keys, and landing 5 first means Track 3 finds out at build time rather than at merge.
Track 3 does not consume anything Track 5 produces.

**Team assignments settled 2026-08-11.** Track 4 → **Team 4**, which already owns the
vector-store surface. Track 5 → **Team 5**, which owns the registry's largest consumer, with
**Team 1** reviewing as contract owner and **Team 3** reviewing the tier-table consolidation
since that table is theirs.

Track 1a moved from Team 1 to **Team 6**. Team 6 consumes `encode_value()` immediately in Track 3
and cannot start Track 3 without it, so no idle time is created — and it takes the critical path
off Team 1, who would otherwise hold 0, 1a and 2 while three teams waited. The objection worth
naming: `schema/` is Team 1's substrate per `tasks.md:311`, and Team 6 writing `schema/encoding.py`
erodes that. Mitigated because the amended D-14 now fully determines the file — it is the
implementation of a frozen spec, not a judgement call — and Team 1 reviews the PR.

Note `tasks.md:311` still allocates no work package to `ports/` at all, which is a plausible
reason NFR-04 has sat at `declared` since the beginning.

---

### Track 0 — Reconcile the tracking docs · ✅ **DONE** — PR #33, merged `b32e04b`

**Why it blocked.** `sql/07_audit_event.sql`'s caller-sequence comment sketched
`hash := sha256(prev_hash || canonical_payload || ...)`, which D-13 had replaced with a single
JCS object. An implementer starting from the DDL rather than the decision would build the wrong
preimage — D-13's own worst case: chains that verify under the buggy implementation and fail
under any correct one. All four tracking documents mentioned D-13/14/15 **zero** times.

**Landed in two commits**, the `sql/07` comment first and alone, because that single edit was all
Track 2 waited on.

**Outcome, and one lesson worth carrying into the other tracks.** The first pass fixed the files
this section *named* and left every adjacent callout on the pre-decision world — a warning box in
`tasks.md` still said the hash bytes were undefined, four lines from a row saying D-13 defined
them. Review caught eight; sweeping for *meaning* rather than for filenames caught three more, in
two files this section never listed (`docs/development.md`, `sql/02_document.sql`).

The scope was written as four documents. The goal was "no document contradicts the decisions".
**Those are not the same thing, and scoping a reconciliation by filename is what produced
leftovers twice.**

**Verified at merge:** `D-1[345]` appears 7 / 5 / 8 / 3 times across the four tracking documents;
no prescriptive `||`-concatenation sketch remains; both revisions of `sql/` apply to a live
PostgreSQL and produce a byte-identical schema, confirming the changes were comment-only at
runtime rather than only in the diff.

---

### Track 1a — `encode_value()` · ✅ **DONE** — `3a3af5c`, gated Tracks 1b and 3

**Placement was decided by an existing rule.** `schema/component.py:74` states **`schema` sits
below `services` and cannot import it**. `encode_value()` encodes schema types, so `schema/` is
the only placement letting both consumers — `services/output` (Track 3) and
`services/conflict_hitl` (Track 1b) — use it without either depending on the other. Landed at
`src/procurement_agent/schema/encoding.py`, tests at `tests/test_encoding.py`.

The `Decimal` warning this section carried is **resolved**: D-14 gained its `Decimal` rule on
2026-08-11, before implementation started, and the encoder tags it `{"$decimal": str(v)}` with
`normalize()` banned — `conflict_hitl._decimals` reads precision from that exact text and it sets
D-2's rounding floor, so the trailing zero decides whether a human is asked to review.

**Implementing the frozen table found three gaps in it**, all amended into D-14 on 2026-08-12 and
all required by the stated property rather than by preference. Recorded here because two of them
change what a *reader of the table alone* would build:

1. **`list` was absent**, yet `list[str]` is the declared type of 18 contract fields, so a
   closed-world encoder raised on real data. Encoded elementwise. It shares the JSON array with
   `tuple` and `frozenset`, which is sound only because neither reaches the polymorphic
   `CanonicalField.value` slot where injectivity is actually required.
2. **`DeclaredBand | model_dump` leaks raw enum members** — plain `model_dump()` runs in python
   mode; `mode="json"` would bypass the `$decimal` tag for any Decimal field added later. Leaves
   recurse through the same encoder, keeping one authority.
3. **The `datetime` row pinned a format but no tag**, so an encoded datetime would collide with
   the equal plain string — the same argument that earned `date` its tag one row above.

**Verified by mutation, not by a green first run.** Eight mutations — swapped date/datetime order,
`Decimal.normalize()`, an unrecursed `model_dump`, tagged enums, naive datetimes assumed UTC,
`isoformat()` in place of the pinned formatter, non-finite floats admitted, and a `str()` fallback
opening the closed world — each turn the suite red.

> ⚠️ **One of the eight survived the first suite, and the reason generalises.** The unrecursed
> `model_dump` passed every test, because a `StrEnum` member equals its own value and `json.dumps`
> writes it as a plain string. **Equality assertions cannot see a raw-enum leak.** It is caught
> only by a structural check that every leaf is *exactly* a JSON type — `type(x) is str`, not
> `isinstance`. Any track hashing an artifact should assume the same blind spot applies to it.

Gates at merge: 514 passed, 24 skipped (from 481/24 — the 33 new tests run); ruff and mypy clean.

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

| # | Question | Status |
|---|---|---|
| Q-2 | Does D-14 get a `Decimal` rule, and must the encoder be injective? | ✅ **Answered 2026-08-11.** Yes to both, and the shape changed on review: D-14 keeps its enumeration and gains **two** cases — `Decimal` and `date` — rather than a general "tag every non-primitive" rule, which would have tagged `StrEnum` members and broken injectivity by making one value encode two ways. The requirement is the *property*; the table is one implementation |
| Q-3 | Team assignment for Tracks 4 and 5 | ✅ **Answered 2026-08-11.** Track 4 → Team 4, Track 5 → Team 5 (Team 1 contract review, Team 3 reviews the tier table), and Track 1a → Team 6 to take the critical path off Team 1 |
| Q-4 | Who holds copyright for `NOTICE`? | ✅ **Answered 2026-08-11.** Leave "The procurement-agent authors" — the standard collective convention, and `NOTICE` is attribution while `LICENSE` is the grant. Revisit only if the answer to one question is yes: *was any of this authored as work-for-hire, or under an employment IP-assignment agreement?* |
| Q-1 | D-15's two facts — does any executed NDA exceed "Representatives with a need to know", and is any evaluator conflicted with a specific bidder? | ⏳ **Open, and not answerable here.** Someone reads the NDAs and the roster. Three outcomes, not two: both no → keep the boolean; NDA yes → `restricted_group`; recusal only → a per-person **deny-list**, keeping the boolean. See [D-15](clarifications.md). Hardens at first ingest, and re-arms with each new NDA or evaluator |

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
