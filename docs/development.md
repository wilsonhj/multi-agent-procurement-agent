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

Run the same local checks expected for a change:

```bash
uv run pytest
uv run ruff check .
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

```bash
uv sync --extra dev --extra parse
uv sync --extra dev --extra extract
uv sync --extra dev --extra store
uv sync --extra dev --extra solar
```

Do not add a heavy adapter dependency to core. Swappability is a packaging property as well
as an interface property. New dependencies must also respect the project’s permissive
dependency-license policy recorded in `plan.md`.

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
controlling artifact in code and record the deviation.

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

1. confirm the existing Protocol can express the adapter without vendor-specific fields;
2. add the vendor dependency to an optional extra;
3. implement the adapter in a provider-specific module;
4. add a reusable Protocol contract test;
5. add sanitized success, empty, malformed, and timeout fixtures;
6. prove that provenance and access labels survive the boundary; and
7. document configuration without including credentials.

Do not weaken a Protocol merely because one provider omits required evidence. Add a
translation layer or reject the adapter output.

## Add a canonical field or condition

Canonical parameter keys are governed by
`specs/001-procurement-agent/contracts/canonical-parameters.md`.

For a new key:

1. update or adopt the controlling contract decision;
2. select the value type, canonical unit, condition dimensions, and tolerance rule;
3. add the schema or vocabulary change;
4. add table-driven validation, ordering, store-round-trip, and conflict tests;
5. update output projection fixtures; and
6. update requirements traceability.

A condition that changes whether two measurements are comparable must be a modeled
dimension, not free text in `note`.

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

A behavior change is complete when:

- public functions and non-obvious invariants have useful docstrings;
- README claims still match runnable behavior;
- `docs/current-state.md` no longer describes the feature as missing;
- requirements traceability is updated; and
- the relevant specification decision is linked.

Prefer explaining why an invariant exists and the failure it prevents. Avoid repeating a
design as “implemented” until a test exercises the production path.

## Definition of done

Before requesting review:

- all tests pass;
- Ruff and strict mypy pass;
- new behavior has a failure-path test;
- outputs are deterministic under reordered input where required;
- no confidential data or secrets are present;
- traceability and current-state docs are accurate; and
- the change is limited to one reviewable contract or vertical slice.
