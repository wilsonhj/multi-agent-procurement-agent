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

A **contract change** is anything touching the eight shared contracts that
[`tasks.md` Phase 0](specs/001-procurement-agent/tasks.md) enumerates as C1–C8:

| ID | Contract |
|---|---|
| C1 | Postgres schema |
| C2 | Claim/extraction record |
| C3 | Provenance reference — `(document_id, page, span, extractor_version)` |
| C4 | Audit event envelope and `event_type` taxonomy |
| C5 | Conflict record and the five resolution action shapes |
| C6 | Canonical workbook projection |
| C7 | Retrieval interface and ACL/labelling model |
| C8 | Stage runner contract, including the append-only claim invariant |

Changing the **condition vocabulary** counts too, even though it is not a C-item: it lives in
[`contracts/canonical-parameters.md`](specs/001-procurement-agent/contracts/canonical-parameters.md),
which is marked FROZEN, and rank 1 of the authority order.

Note that this list is *not* the list of contracts still needing to be frozen. C5 is done and
the other seven are not; [docs/current-state.md](docs/current-state.md) holds that status and is
the one to check before claiming work. Changing a frozen contract is a contract change too — it
is the case this rule most exists for.

## Good contribution shapes

- one adapter plus its reusable contract tests;
- one canonical field family plus golden fixtures;
- one database migration plus privilege and idempotency tests;
- one end-to-end path for a sanitized source document;
- a focused policy bug with a regression test; or
- documentation that reconciles a specific implementation/specification mismatch.

Avoid combining formatting cleanup, dependency upgrades, schema changes, and new behavior in
one pull request.

> [!IMPORTANT]
> **An adapter is only acceptable if its dependencies pass the license gate.** The project takes
> **Apache-2.0, MIT and BSD only**; copyleft and revenue-capped licenses are disqualifying. This
> is not a preference — a rejected license in a required dependency is unfixable after the fact.
>
> Several of the components most likely to be proposed have already been evaluated and rejected,
> and are named so nobody spends a weekend on one: **Marker** (weights RAIL-M, free only under
> $5M revenue), **Surya** (GPL-3.0), **MinerU** (AGPL-3.0), **olmOCR** (Rail-M revenue cap),
> **PyMuPDF** (AGPL-3.0 or Artifex commercial), **ParadeDB/`pg_search`** and
> **VectorChord-bm25** (AGPL-3.0), **Jina embeddings v5** and **NV-Embed-v2** (non-commercial).
>
> The full gate, with the verified license of each, is in
> [`plan.md`](specs/001-procurement-agent/plan.md). Verify a license at the dependency's own
> `LICENSE` file, not from a summary — that is how this list was built.

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

See the [development guide](docs/development.md) for optional extras, the adapter sequence, and
feature-specific test expectations. Note that `uv sync` is an exact sync: name every extra you
want in one command, or the previous ones are uninstalled.

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

This section covers what the pull request **description** should say. What the *change itself*
must satisfy before you request review is one list, kept in
[Definition of done](docs/development.md#definition-of-done) — do not re-derive it here.

A pull request description should include:

- the problem and the controlling requirement or issue;
- the implementation approach;
- tests added and commands run;
- effects on provenance, determinism, access control, and human review;
- any specification deviation, with the `A-n` register ID; and
- sanitized before/after output when behavior is visible.

Documents that go stale when a requirement moves status are listed under
[Documentation expectations](docs/development.md#documentation-expectations); there are four of
them and the README is one, which an earlier version of this section left out. “Enforced” means
a test covers the actual behavior, not merely that a type or function signature exists.

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
- Every dependency clears the permissive license gate, and swappability is enforced by
  packaging: a heavy integration goes in an optional extra, never in core.

## Documentation-only contributions

Documentation is part of the product. A useful documentation pull request should cite the
code or controlling specification, state whether behavior is implemented or planned, and
avoid copying confidential source requirements.

If documentation and code disagree, open an issue or include the reconciliation in the pull
request rather than silently editing one side.
