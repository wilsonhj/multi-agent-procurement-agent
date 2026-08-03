# Contributing

Thank you for helping build Procurement Agent. The project welcomes issue reports, design
reviews, documentation improvements, test fixtures, adapters, and implementation work.

The repository is pre-alpha and several shared contracts are unfinished. Small,
fixture-backed vertical slices are easier to review and safer to merge than broad pipeline
implementations.

> [!NOTE]
> The repository does not yet have an open-source license, DCO, or CLA policy. Before accepting
> external code contributions, maintainers should settle those governance choices. Opening an
> issue or discussing a design does not require transferring code rights.

## Before you start

1. Read the [current-state audit](docs/current-state.md).
2. Read the [architecture](docs/architecture.md).
3. Check the relevant requirement and its prerequisites in
   [tasks.md](specs/001-procurement-agent/tasks.md).
4. Search existing issues and pull requests.
5. Open or claim an issue before changing a shared contract.

Contract changes include the database schema, claim format, audit envelope, ACL model,
condition vocabulary, conflict record, runner state, and canonical workbook projection.

## Good contribution shapes

- one adapter plus its reusable contract tests;
- one canonical field family plus golden fixtures;
- one database migration plus privilege and idempotency tests;
- one end-to-end path for a sanitized source document;
- a focused policy bug with a regression test; or
- documentation that reconciles a specific implementation/specification mismatch.

Avoid combining formatting cleanup, dependency upgrades, schema changes, and new behavior in
one pull request.

## Local validation

Set up the development environment:

```bash
uv sync --extra dev
```

Run:

```bash
uv run pytest
uv run ruff check .
uv run mypy
```

See the [development guide](docs/development.md) for optional extras, adapter conventions,
and feature-specific test expectations.

## Branches and commits

Use a short branch name that communicates the change, for example:

```text
feature/pdf-signature-router
fix/condition-comparison
docs/contributor-guide
```

Keep commits reviewable and describe the invariant or user-visible behavior, not only the
files changed.

## Pull requests

A pull request should include:

- the problem and the controlling requirement or issue;
- the implementation approach;
- tests added and commands run;
- effects on provenance, determinism, access control, and human review;
- any specification deviation; and
- sanitized before/after output when behavior is visible.

Update `docs/requirements-traceability.md` and `docs/current-state.md` when a requirement moves
from open or declared to partial or enforced. “Enforced” means a test covers the actual
behavior, not merely that a type or function signature exists.

## Data and security

Do not commit:

- contracts, price files, supplier-confidential documents, or derived workbooks;
- API keys, tokens, endpoint credentials, or `.env`;
- licensed standards text; or
- public-source data whose license does not permit redistribution.

Use minimal, synthetic fixtures or data explicitly approved for open publication. Preserve
the shape of difficult cases without preserving identifying commercial content.

If you discover a vulnerability, do not include exploitable details in a public issue. The
project still needs a private security-reporting policy; contact the repository maintainer
directly until one is published.

## Design principles reviewers enforce

- Web evidence supplements gaps and never overwrites the system of record.
- Every value has provenance.
- Conditions are matched before tolerances are applied.
- Human decisions are explicit and immutable.
- Access control is enforced before restricted content reaches retrieval or a model.
- Workers append claims; a reducer projects canonical state.
- The same canonical state produces the same ordered output.
- Missing or incomparable evidence stays visible.

## Documentation-only contributions

Documentation is part of the product. A useful documentation pull request should cite the
code or controlling specification, state whether behavior is implemented or planned, and
avoid copying confidential source requirements.

If documentation and code disagree, open an issue or include the reconciliation in the pull
request rather than silently editing one side.
