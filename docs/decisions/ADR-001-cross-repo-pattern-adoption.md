# ADR-001 — Cross-repo pattern adoption: avalanche and predict-rlm

**Status:** Proposed · **Date:** 2026-08-06 · **CI:** not run on this branch (zero Actions
runs, empty status-check rollup) — a docs-only diff, but not a green build

> **Still `Proposed`, and that is now load-bearing rather than pending paperwork
> (noted 2026-09-02).** [phase-1-execution.md](../../specs/001-procurement-agent/phase-1-execution.md)
> Track 4 is scheduled to *implement* Decision 2 — "a capability-declaring conformance matrix
> plus one in-memory reference adapter per port" — and assigns it to Team 4. A track cannot
> implement a proposal. Either the ADR is ratified, or Track 4 is building against a document
> nobody has agreed to. **Nothing else in the repository cites this file**: it is not in the
> README's map, not in either statement of specification authority, and not referenced from
> `current-state.md`, `architecture.md` or `tasks.md`. That is a governance gap for a maintainer
> to close, not an editorial one, so it is recorded here rather than resolved.
>
> Its **Context** section is also dated: it describes D-13 as "proposed and not ratified", which
> was true on 2026-08-06 and stopped being true the next day — D-13, D-14 and D-15 were all
> adopted on 2026-08-07. The corrected sentence is marked inline below.

This is the first ADR, so the relationship to the existing record needs stating once.
[plan.md](../../specs/001-procurement-agent/plan.md) Decisions 1–10 remain the architectural
record; nothing here amends them, and a reversal of any of them belongs in the plan's own
register, not in an ADR. ADRs record decisions made **after** the plan froze. Where this one
touches a plan decision, it says so by number.

---

## Context

A review of two external repositories — Trampoline AI's **avalanche**, a typed-DAG agent
workflow runtime with an operator control plane, and **predict-rlm**, a DSPy-based
recursive-LM framework with the GEPA text-component optimizer — identified engineering
patterns that fit this repository's measured gaps while leaving plan Decision 1 (Postgres
state machine, no workflow framework) fully intact.

The gaps, verified against the working tree:

- **No runtime.** The repo is a pure-policy domain core plus live-verified Postgres DDL.
  Ten `raise NotImplementedError` stubs sit across the six service entry-point modules and
  the orchestrator (`src/procurement_agent/services/`, `src/procurement_agent/orchestrator/__init__.py:91`).
  Zero LLM call sites and zero prompts exist — no `openai`/`instructor` import anywhere in
  `src/`, and the word "prompt" appears only as `LLMPort.extract`'s parameter and in two
  docstrings.
- **No timeouts, no logging.** No timeout parameter exists anywhere in code or spec — the
  word's single occurrence in application code and specs is a fixture checklist item at
  `docs/development.md:152` (CI configuration separately uses `--health-timeout` for a
  container health check, a different concern). No module in `src/` imports `logging`.
- **Ports with no adapters and no tests.** The six port Protocols in
  `src/procurement_agent/ports/__init__.py` have zero adapters, and no test imports `ports`
  at all (`docs/current-state.md:402`). `docs/development.md:157-163` records the hazard in
  its own words: no adapter layout convention exists, so the first adapter "decides the
  layout for everyone after it".
- **Observability is the emptiest quadrant.** The audit DDL is live-tested — six chain
  tests at `tests/test_sql_behaviour.py:387-429` — but nothing can emit an event:
  `sql/README.md` (design decision 5) records that the Python envelope and canonicalisation
  do not exist, so "nothing may emit an event yet". The canonicalisation half is now
  drafted — D-13, ~~proposed and not ratified~~ **adopted 2026-08-07, the day after this ADR
  was written** — but no code emits an event either way, which is the part that has not
  changed: WP-H's library is still unwritten and `rfc8785` is in neither `pyproject.toml` nor
  `uv.lock`.
- **The gold set is the acknowledged blocker.** The 30–50 labelled-document set
  (tasks.md B.9, clarifications D-11) gates any accuracy claim; every figure in the plan is
  extrapolated from other domains.

External repositories are cited below by repo and module path only; their line numbers are
not stable enough to cite.

---

## Decisions

### 1 — Reaffirm plan Decision 1; avalanche stays on the shelf

**Chosen:** the Postgres job-table state machine stands unchanged; avalanche is not adopted
as pipeline owner in any form. **Confidence: high.**

The argument against LangGraph transfers in spirit but not in its specific mechanism —
avalanche does not durably checkpoint run state the way a LangGraph-style workflow
checkpointer does. Four properties, each independently disqualifying, hold instead:

- **No durable run state or resume.** The operator holds every run, log, and trace in
  plain in-memory dicts (`self._runs`, `self._logs`, `self._trace_bodies`, and siblings in
  avalanche `src/runtime/operator/operator.py`), and avalanche's own docs list "durable
  operator replay/recovery beyond the current implementation" under *What Is Not Supported
  Yet* (avalanche `docs/getting-started.md`). A crash loses every in-flight run —
  disqualifying on its own under NFR-02, which requires durable, resumable state.
- **A second durable data plane.** Avalanche's Iceberg table writer attaches nine
  framework-owned row-lineage columns (`_ava_run_id`, `_ava_node_id`,
  `_ava_lineage_vector`, and six more) to every written row by default
  (`row_lineage=True`, avalanche `src/avalanche/lineage.py`). This is not workflow
  checkpointing, but it is exactly the duplicate-source-of-truth problem plan Decision 1
  rejects: run and node identity would live in both Postgres-owned tables and
  avalanche-owned Iceberg tables — the same objection NFR-02 and FR-OUT-06 already raise
  against a LangGraph checkpointer, now landing on a different mechanism.
- **Sequential default executor.** `executor_backend` defaults to `"local"`
  (avalanche `src/runtime/operator/operator.py`), which resolves to `LocalExecutor` —
  "sequential local executor... executes tasks synchronously in the current process"
  (avalanche `src/runtime/executor.py`). Adopting avalanche would not even buy
  parallelism, the one thing a DAG runtime is assumed to provide.
- **No node-level retry, no partial-DAG resume.** Neither exists in the operator or DAG
  execution paths.

Avalanche is therefore a *weaker* candidate than LangGraph, the one already litigated, not
a stronger one under a new name.

> Scale check, stated plainly: hundreds of documents, batch, offline, one approval gate.
> Nothing has changed since the plan measured every framework against that shape.

The existing escape hatch stands as written (plan.md, Decision 1 closing paragraph): a
workflow library may later be adopted *inside* the extract stage, never as pipeline owner.

### 2 — A capability-declaring conformance matrix for the six ports, before the first adapter lands

**Chosen:** adopt predict-rlm's runtime-contract pattern (`predict-rlm`
`tests/runtime_contracts/`) for `ports` before any adapter exists. **Confidence: high.**

The pattern: each backend declares a `frozenset` of capabilities plus an `xfail_contracts`
mapping with reasons; contract tests `require(capability)` and xfail/skip/run accordingly.
An unimplemented capability is therefore **declared, not silently absent** — the test suite
is the conformance matrix.

This directly answers the recorded hazard that the first adapter "decides the layout for
everyone after it" (`docs/development.md:157-163`): the contract suite exists *before* the
first adapter, so the adapter conforms to the tests rather than the tests to the adapter.
It also gives `ports` its first importing tests, closing the gap `docs/current-state.md:402`
names as a good first contribution, and it converts AC-8's `declared` status
(`docs/current-state.md:211`) into something an adapter can be held to.

### 3 — Producer-side bounding and explicit timeouts

**Chosen:** every collection and retention path is bounded at the producer, and every
external call carries an explicit timeout, following the avalanche operator's
constructor-time containment checks (outer limits must contain inner ones).
**Confidence: high.**

There is currently no timeout anywhere — not in code, not in the spec. The substrate for
wall-clock budgets already half-exists: `job` carries the lease pair
(`sql/08_job.sql:56-57`) and retry backoff (`sql/08_job.sql:43-48`), but no Python setting
bounds anything. Concretely:

- timeout fields on the configuration of every port Protocol *implementation* (the
  Protocols themselves stay signature-stable);
- limits wired into `config.Settings` with validated bounds, following the existing
  `compose_gate_threshold` pattern (`src/procurement_agent/config.py:100-110`) under the
  already-set `validate_assignment=True` (`src/procurement_agent/config.py:25`), so a bound
  holds under attribute assignment and not only at construction;
- constructor-time checks that an outer budget contains its inner ones — a stage budget
  smaller than one LLM-call timeout is a configuration error, raised at load, not a runtime
  surprise.

### 4 — A failure taxonomy with fixed precedence, for the future runner and eval harness

**Chosen:** adopt predict-rlm's failure-classification pattern (`predict-rlm`
`telemetry.py`): a closed set of failure classes — twelve there — with a **strict
precedence ranking harness failures above model failures**, applied before any evidence
reaches a report or an optimizer. **Confidence: medium-high.**

The reason precedence matters: a harness bug scored as a model failure poisons every
downstream number, and the mistake is invisible without a rule that fixes which
classification wins. Map the taxonomy onto what the DDL already commits to — the
seven-value `audit.event` `event_type` CHECK (`sql/07_audit_event.sql:80`) and the `job`
`quarantined` status (`sql/08_job.sql:30-31`) — and extend it when the contract C8 runner
is actually written. Medium-high rather than high because the runner does not exist yet;
the taxonomy is adopted ahead of its main consumer.

### 5 — The metric-result validation contract for the gold-set eval harness

**Chosen:** the B.9 eval harness adopts predict-rlm's metric-result contract
(`predict-rlm` `rlm_gepa/schema.py`): a **finite score is required; non-empty feedback is
required whenever score < 1.0; errors go in an explicit error field**, never in the score.
**Confidence: medium-high.**

Also adopted: the soft/hard dual-acceptance test for comparing two extraction
configurations (`predict-rlm` `rlm_gepa/runtime/acceptance.py`) — roughly sixty
dependency-free lines, **reimplemented locally, not imported** (see Rejected alternatives
for why the package dependency is refused). Usable only once the gold set exists, which is
the point of sequencing it here rather than building it speculatively.

### 6 — Any GEPA-style prompt optimization is sequenced strictly behind the gold set

**Chosen:** no prompt-optimization work of any kind before B.9 delivers labels.
**Confidence: high.**

The substrate is ready: `extractor_version` already gives prompt identity coexisting with
the append-only store — it is part of the claim key, so a re-optimized prompt appends new
claims beside the old rather than overwriting them
(`src/procurement_agent/services/claims/__init__.py:60-64`). The prompts and the labels are
what do not exist.

Constraints any optimizer must respect, restated from decisions already on record:

| Constraint | Source |
|---|---|
| `json_schema` mode, never tool-calling — logprobs are a required confidence signal, and tool calls do not emit them | plan Decision 7 |
| No LLM self-reported confidence (0.692 AUC, banned); no N=5 self-consistency (0.744 AUC at 5× cost) | D-3; plan Decision 7 |
| Ensembles aggregate by union, never by vote | FR-HITL-02; tasks.md E.3a; [agent-topology.md](../agent-topology.md) |

Free head start: the domain-plausibility rules of task B.5 (`Voc > Vmp`, `Isc > Imp`,
`Pmax ≈ Vmp × Imp`, …) are a **label-free metric component** — they can score an extraction
configuration today without a single labelled document.

### 7 — Structured logging and the audit-event emitter are the next infrastructure work, ahead of further domain logic

**Chosen:** the next non-domain work is structured logging plus the Python audit-event
emitter, adopting avalanche's stance that observability is a control-plane concern rather
than an afterthought. **Confidence: medium-high.**

This is the repository's emptiest quadrant — no `logging` import in `src/`, no event
emitter. The *logging* half has no competing decision on record at all. The *audit-emitter*
half now does, and it is a prerequisite rather than a conflict: **D-13** (contract C4,
`specs/001-procurement-agent/clarifications.md`, drafted 2026-08-06, marked ⚠️ PROPOSED, NOT
RATIFIED) settles the canonicalisation scheme and hash preimage this emitter would write
against. Its own deadline is binding on this decision: *"the version marker in §3 must exist
before the first event is ever emitted"* — so **D-13 must be ratified before this work item
writes anything**, not after. Sequencing, restated plainly: ratify D-13 → write the emitter
against its preimage → then the load test below.

The Python advisory-lock statement for the audit hash chain — recorded in `sql/README.md`
("Still unproven by the above") as must-be-written-and-load-tested — belongs to this work
item, not to a later one. D-13 does not cover it; it settles what is hashed, not what
prevents two writers forking the chain.

### 8 — A design-methodology skill encoding a smallest-extension-point ladder

**Chosen:** add a version-controlled methodology file under `.agents/skills/` encoding an
ordered "reach for the smallest extension point first" ladder — configuration before a new
adapter, an adapter before a service change, a service change before a contract change.
**Confidence: medium.**

Both external repos ship exactly this: ordered extension-point methodology files under
version control, so the cheapest correct change is the documented default rather than tribal
knowledge. Medium confidence because the mechanism is social rather than enforced. Named
gap, not a TODO: **`.agents/` does not exist in this repository today**; this decision
creates it.

---

## Rejected alternatives

- **Avalanche as pipeline owner.** Re-argued at decision 1: no durable run state or
  resume, a second durable data plane (Iceberg row-lineage columns duplicating
  NFR-02/FR-OUT-06 state), sequential default executor, no node-level retry or
  partial-DAG resume.
- **LangGraph.** Already litigated in plan Decision 1; nothing observed in either external
  repo reopens it.
- **Depending on the predict-rlm / rlm_gepa packages.** Deep coupling to DSPy private APIs
  under a `<3.3` pin. The pieces worth having are small — the acceptance function is ~60
  dependency-free lines — so they are reimplemented locally (decisions 2, 4, 5), never
  imported.
- **Building an eval harness before the gold set.** Fitting to nothing. The repo's own
  `SIGNAL_WEIGHTS` comment already makes this argument — "Tuning them without a labelled
  set would be fitting to nothing" (`src/procurement_agent/services/confidence/__init__.py:276`)
  — and it applies with equal force to a harness with no labels to score against.

---

## Verification

- **Decision 2:** the conformance matrix lands as the first tests importing `ports`,
  closing the zero-imports gap on the repository's own terms.
- **Decision 3:** timeout settings are validated the way `compose_gate_threshold` already
  is — bounded `Field`s under `validate_assignment=True` — with an added containment check
  that outer budgets hold inner ones, tested at construction and at assignment.
- **Decision 5:** the locally reimplemented acceptance function gets its own unit suite,
  independent of any gold-set data.
- **Decision 7:** the audit emitter must pass the six existing live chain tests
  (`tests/test_sql_behaviour.py:387-429`) unchanged, plus a written load test for the
  pre-INSERT advisory lock — the concurrency property `sql/README.md` explicitly names as
  still unproven.
