# Development guide

This guide covers local setup, repository conventions, validation, and the safest way to
extend Procurement Agent.

## Prerequisites

- Git
- Python 3.12 or 3.13
- [uv](https://docs.astral.sh/uv/)

The project uses a `src/` layout and Hatchling for builds. Core dependencies stay small;
heavy integrations are optional extras.

## Set up the repository

```bash
git clone https://github.com/wilsonhj/multi-agent-procurement-agent.git
cd multi-agent-procurement-agent
uv sync --extra dev
```

Run the same local checks expected for a change — the same four CI runs:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

If the default uv cache is not writable in a container, select a writable cache explicitly:

```bash
UV_CACHE_DIR=/tmp/procurement-agent-uv-cache uv sync --extra dev
```

No endpoint configuration is required for the current unit tests.

## Configuration

Settings use the `PROCUREMENT_` environment prefix and may be loaded from `.env`. Copy the
example only when working on an integration:

```bash
cp .env.example .env
```

Never commit `.env`. Contract and pricing documents must use self-hosted or enterprise model
endpoints that do not train on submitted data. The security controls are not implemented, so
use only synthetic or approved sanitized fixtures today.

## Choose dependency extras deliberately

> [!WARNING]
> `uv sync` is an **exact** sync, not an incremental install: it makes the environment match the
> extras named in *that one command* and uninstalls everything else. Name every extra you want in
> a single command. Running one `uv sync` per extra leaves you with only the last one, having
> silently removed the others.

Besides `dev`, there are four extras. Pick the ones the change actually needs and put them in
one command, always alongside `dev`:

| Extra | Pulls in | Needed when |
|---|---|---|
| `parse` | Docling, pandas | working on document parsing or OCR routing |
| `extract` | Instructor, OpenAI client (for a self-hosted vLLM endpoint) | working on schema-constrained extraction |
| `store` | psycopg, pgvector | working on persistence or retrieval |
| `solar` | pvlib | working on the CEC equipment-list cross-check |

So to work on parsing and extraction together:

```bash
uv sync --extra dev --extra parse --extra extract
```

To go back to the lean environment, name only `dev`, and expect the others to be removed:

```bash
uv sync --extra dev
```

You can see what a command will do before running it — `uv sync --extra dev --extra solar
--dry-run` prints the additions and the removals, and the removals are the part worth reading.

Do not add a heavy adapter dependency to core. Swappability is a packaging property as well
as an interface property. New dependencies must also clear the project’s permissive
dependency-license gate — **Apache-2.0, MIT and BSD only** — recorded with each rejected
component in [`plan.md`](../specs/001-procurement-agent/plan.md).

## Understand the specification before changing code

Read artifacts in this order:

1. `specs/001-procurement-agent/contracts/` for frozen shared data shapes;
2. `spec.md` for functional and non-functional requirements;
3. `clarifications.md` for resolved domain ambiguity;
4. `plan.md` for architecture and technology choices;
5. `tasks.md` for dependencies and verification cases; and
6. `docs/requirements-traceability.md` for implementation status.

`analysis.md` explains known cross-artifact inconsistencies. `open-decisions.md` contains
recommendations that may not all be adopted; check each decision’s status before treating it
as normative.

When artifacts disagree, do not silently select the easiest interpretation. Cite the
controlling artifact in code and register the deviation as a numbered `A-n` finding in
`analysis.md`, which is the register. There is no separate deviation file; see
[architecture.md § Specification authority](architecture.md#specification-authority).

## Package boundaries

### `schema`

Shared, serializable domain objects. Changes here affect every stage and should be treated as
contract changes. Prefer:

- closed vocabularies for values that affect comparison or grouping;
- frozen models for immutable evidence and decisions;
- validators that reject silent ambiguity; and
- deterministic serialization and ordering.

Do not add a second representation of a concept already defined by a frozen contract.

### `ports`

Structural Protocols for third-party integrations. Core code depends on these interfaces,
not on a vendor client. An adapter may wrap an SDK without subclassing a project base class.

### `services`

Domain operations and use-case entry points. Pure functions belong here when possible.
Network and database side effects should be isolated behind ports or repositories.

### `orchestrator`

Pipeline stage policy and, eventually, the PostgreSQL-backed job runner. Human review does
not become a blocking stage.

## Add an adapter

Use this sequence for a parser, OCR, model, or store integration:

1. check the vendor's license against the gate before anything else — Apache-2.0, MIT or BSD,
   read from its own `LICENSE` file, not from a summary. A rejected license is unfixable later,
   and [`plan.md`](../specs/001-procurement-agent/plan.md) already names the components that
   failed;
2. confirm the existing Protocol can express the adapter without vendor-specific fields;
3. add the vendor dependency to an optional extra;
4. implement the adapter in a new module, and **decide where it goes before writing it**;
5. add a reusable Protocol contract test;
6. add sanitized success, empty, malformed, and timeout fixtures;
7. prove that provenance and access labels survive the boundary; and
8. document configuration without including credentials.

> [!NOTE]
> **The adapter layout is now decided: `adapters/<port>/<backend>.py`,** one package per port and
> one module per backend, with `memory.py` the in-memory reference inside each. The reasoning and
> the rejected alternatives are in `adapters/__init__.py`. This note previously said no convention
> and no package existed, which was true until the NFR-04 conformance suite landed. Historical
> caution retained because it explains the shape of that decision:
> `ports/__init__.py` once documented exactly that package, it did not exist, and removing the
> claim is filed as [A-18](../specs/001-procurement-agent/analysis.md). Propose the location in
> the issue — alongside the service that owns the port is the obvious candidate — and get it
> agreed before the code lands, because moving every adapter afterwards is the expensive version
> of this decision.

Do not weaken a Protocol merely because one provider omits required evidence. Add a
translation layer or reject the adapter output.

## Add a canonical field or condition

Canonical parameter keys are governed by
[`contracts/canonical-parameters.md`](../specs/001-procurement-agent/contracts/canonical-parameters.md),
which is FROZEN. Additions are cheap; renames and type changes are not.

For a new key:

1. update or adopt the controlling contract decision;
2. select the value type, canonical unit, condition dimensions, and tolerance rule;
3. **write the tolerance rule down** — in `FIELD_TOLERANCES` in
   `services/conflict_hitl/tolerance.py`, keyed on the contract's `key` exactly as spelled
   there;
4. add the schema or vocabulary change;
5. add table-driven validation, ordering, and conflict tests;
6. update requirements traceability.

### Step 3 is the one that is easy to skip

`tolerance_for()` falls back to `DEFAULT_TOLERANCE`, which is EXACT, for any key the table does
not hold. That fallback is deliberate and safe — a field nobody has measured the spread of gets
compared exactly, which raises a reviewable conflict rather than silently merging two values —
and 100 of the contract's 124 keys rely on it today. Only 24 keys carry a row.

So omitting the row is not a bug, and no test will fail. It is a *decision made by default*: you
are declaring the field has no tolerance, and for a field whose sources genuinely disagree at
the fourth decimal place, that is queue inflation — reviewers learning to ignore the queue,
which D-1 calls the worst possible outcome for a human-in-the-loop tool. Decide it, do not
inherit it.

What the tests do guard is the shape of any row you add:

- `test_every_tolerance_key_is_a_contract_key` (`tests/test_values_conflict.py`) rejects a key
  the frozen contract does not have. This is the check that matters most, and it exists because
  the failure already shipped: 19 of the table's 20 keys were invented names
  (`transformer_no_load_loss_w` where the contract says `no_load_loss`), so every real field
  silently fell through to EXACT — and it *inverted* the transformer loss rule, turning a
  below-guarantee loss that IEC 60076-1 says is never a nonconformity into a queued conflict.
- `test_every_table_row_is_internally_consistent` rejects a magnitude on an EXACT row, and a
  row with no stated basis.
- `test_an_unassigned_field_is_exact_not_permissive` pins the fallback itself.

### Step 4 breaks specific, named tests

A condition that changes whether two measurements are comparable must be a modeled dimension,
not free text in `note`. Acting on that is not additive. Step 5 is not a vague “add tests”:
these named tests will fail, and each has to be updated deliberately rather than relaxed. The
first two apply to a new condition dimension, the third to a new field on `CanonicalField`:

- `test_the_grouping_key_has_a_fixed_layout` (`tests/test_condition_grouping.py`) pins
  `tuple(ConditionDimensions.model_fields)` and a golden ten-`None` grouping key as literals.
  Both change. They are literals on purpose: every other assertion in that file compares one
  `grouping_key()` to another, which is self-consistency with no anchor.
- `test_the_table_accounts_for_every_vocabulary_member` (same file) parses the **Conditions**
  table at the foot of `canonical-parameters.md` and fails if an enum has a member no row of
  that table names. A new vocabulary member means editing the contract document, not just the
  enum — `sat` shipped in exactly that state.
- `test_canonical_field_has_the_eight_spec_keys_plus_condition`
  (`tests/test_schema_invariants.py`) pins `CanonicalField.model_fields` to the TRS's eight keys
  plus `condition`. A ninth field of your own needs that assertion, and A-1's reasoning,
  extended rather than loosened.

### What this recipe does not cover yet

The output-projection step is `tests/fixtures/workbooks/` — C6's projection and its T0.5 golden
hash, regenerated the same way as every other fixture. `write_workbook()` still raises
`NotImplementedError`, so there is no *rendered workbook* to update; when G.2 lands, its
normalised-archive digest belongs here alongside the projection hash. There is likewise no store round-trip step:
C1 has landed as the DDL in `sql/`, but nothing in Python connects to it — there is no
repository layer, so there is no round trip to exercise. Adding one is the step that turns
`sql/` from a schema into a store.

## Extend conflict policy

Conflict detection is intentionally pure and pairwise. A change should test:

- symmetry under argument order;
- invariance under every input permutation;
- source-tier classification;
- mismatched condition rejection;
- source precision and rounding-floor behavior;
- unit mismatch behavior;
- missing-value behavior; and
- a human-readable verdict reason.

Do not:

- introduce a global tolerance;
- fuzzy-match certifications or model identifiers into agreement;
- turn “not compared” into “no conflict”;
- majority-vote conflicts away; or
- group a non-transitive compatibility relation with first-fit buckets or connected
  components.

## Implement a pipeline stage

The planned runner is at-least-once. Every stage therefore needs:

- a stable idempotency key;
- immutable inputs or versioned claims;
- explicit retryable versus terminal errors;
- no hidden wall-clock ordering;
- an audit event in the same transaction as its business write; and
- tests that execute the stage twice and obtain the same durable result.

Workers propose immutable claims. They must not receive a canonical-store write handle.

## Work on workbook output

The canonical JSON projection is the artifact of record; XLSX is a renderer. A writer change
must verify:

- all 13 tabs and their fixed order;
- deterministic component and field ordering;
- source navigation for every value;
- hidden provenance columns included in filter ranges;
- missing, web, low-confidence, and conflict visual channels;
- a completeness manifest for open conflicts;
- byte identity across separate runs; and
- openability in current desktop Excel and LibreOffice.

Call `normalize_archive()` only after the workbook structure is complete. Archive-level
determinism does not prove that workbook content is correct.

## Testing strategy

Tests currently focus on pure policy and regression cases. New production features need four
layers:

1. unit tests for validators and pure functions;
2. Protocol contract tests shared by every adapter;
3. fixture-backed service tests at a real persistence boundary; and
4. acceptance tests that trace a document through a user-visible result.

Use sanitized fixtures committed to the repository. Never commit customer contracts,
credentials, generated workbooks containing supplier data, or licensed standards text.

Useful commands:

```bash
uv run pytest tests/test_values_conflict.py
uv run pytest -k compose_gate
uv run ruff check . --fix
uv run mypy
```

Use Ruff’s automatic fix only for mechanical changes you have reviewed.

## Documentation expectations

Four documents make status claims about the code, and a behavior change goes stale in all four
at once. Update every one that your change falsifies:

| Document | What it claims | Update when |
|---|---|---|
| `docs/requirements-traceability.md` | per-requirement status: enforced / partial / declared / open | a requirement's status moves, in either direction |
| `docs/current-state.md` | what works today, and the acceptance boundary | a feature stops being missing, or the test count changes |
| `README.md` § Current state | the coarse summary table a reader sees first | any row of it stops being true |
| `docs/architecture.md` | design-versus-implementation boundary, and the services table | a service stops being a stub |

The README's table is a **derived summary**, not an independent claim: `docs/current-state.md`
is the source of truth and the README must not disagree with it. It is listed here because it is
the one that gets forgotten — it lives in a different file from the audit that governs it.

Also:

- public functions and non-obvious invariants have useful docstrings;
- the controlling specification decision is cited in the code, by ID; and
- any deviation from it is registered as an `A-n` finding in `analysis.md`.

Prefer explaining why an invariant exists and the failure it prevents. Avoid repeating a
design as “implemented” until a test exercises the production path — the repository already
had a helper described as tested with no assertion anywhere against it.

## Definition of done

This is the **one** checklist for the state of a change before review. `CONTRIBUTING.md` covers
what the pull request *description* should say and points here for the rest; if the two ever
disagree, this list is the one to fix.

Before requesting review:

- all tests pass — `uv run pytest`;
- Ruff and strict mypy pass — `uv run ruff check .`, `uv run ruff format --check .`
  and `uv run mypy`. All four gates run in CI on Python 3.12 and 3.13;
- if you touched `sql/`, the live-schema suite passes — see
  `tests/test_sql_behaviour.py` for how to start a throwaway PostgreSQL. CI runs it
  against a pgvector service container, so a structural-only change still gets checked;
- new behavior has a failure-path test, and the test fails if you break the behavior it names.
  A test that passes against a deliberately broken implementation is not covering it;
- outputs are deterministic under reordered input where required;
- new dependencies clear the license gate and sit in an optional extra;
- no confidential data or secrets are present;
- every document listed under [Documentation expectations](#documentation-expectations) that
  your change falsifies is updated; and
- the change is limited to one reviewable contract or vertical slice.
