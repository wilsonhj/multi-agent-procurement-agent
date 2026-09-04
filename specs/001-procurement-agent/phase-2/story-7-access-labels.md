# Story 7 — Access-label facts (C7, D-15, Phase 1 Q-1)

**Track:** 7 · **Owners:** a human who can read the executed NDAs and the evaluation roster;
Team 6 for code readiness · **Needs:** nothing for the facts; Track 4a for readiness code ·
**Status:** proposed 2026-09-03

**Story.** Before the first confidential document is ingested into a store real reviewers use,
somebody establishes two facts: whether any executed supplier NDA goes beyond "Representatives
with a need to know", and whether any evaluator is conflicted with a specific bidder. The answer
selects one of three label models, all of which the code is already able to adopt without a
redesign. The answer is recorded as an artifact and re-armed every time a new NDA or evaluator
arrives.

**Done means.** `docs/decisions/ADR-002-access-label-facts.md` exists with the two answers, the
list of NDAs read (title, date, hash of the PDF) and the roster date; the selected outcome is
configured; `docs/access-review.md` is the living register; the readiness code for all three
outcomes is merged and tested regardless of which outcome is chosen.

---

## Why this is a story and not a checklist

D-15 says the label model is contingent on **two questions of fact**, not preferences, and that
the retrofit if the fact arrives late is ~40 RLS policies. Phase 1 recorded Q-1 as "open, and not
answerable here". Two things follow. First, nobody in an agent team can close it — the deliverable
has a human owner. Second, the *cost* of a late answer is entirely a function of how ready the
code is, and that part is agent work that can be done now. This story specifies both halves so the
content half arriving after the first ingest costs a configuration change.

## Controlling decisions

| ID | Rule |
|---|---|
| D-15 | Boolean document-level label; clearance from the OIDC subject via `SET LOCAL app.allow_restricted`; label at ingest from classification, fail closed; the two facts; the **three** outcomes (both no → boolean; NDA yes → `restricted_group`; recusal only → per-person deny-list keeping the boolean); record the answer as an artifact; re-arms with each new NDA or evaluator |
| Decision 3c | `FORCE ROW LEVEL SECURITY`; non-owner app role; RLS is the boundary |
| D-12a | Principal identity is the OIDC `sub` |
| C-6 (spec) | Access control enforced at retrieval, not display |
| P2-C5 | `PrincipalContext(subject, cleared_for_restricted, denied_suppliers)` — the deny-list hook already exists in the type |

## Code surface today

- `access_restricted` boolean on `document` and `chunk` (stored) and derived on five tables via `document_is_restricted()` / `conflict_is_restricted()`; 40 `CREATE POLICY` statements; RESTRICTIVE policy stops `procurement_app` from self-entitling; GUC `app.allow_restricted`.
- `SourceDocument.access_restricted: bool = False`.
- `VectorStorePort.search(allowed_document_ids=...)` — scoping within an entitlement.
- No principal type, no deny-list, no group column, no register, no ADR-002.

---

## 1 · The facts — human half

Two document checks, per D-15:

1. For every executed supplier NDA: does it name individuals, require access logs, or require
   segregation from personnel who work with competing suppliers? Record title, execution date,
   SHA-256 of the PDF, and yes/no per trigger.
2. For the evaluation roster as of a date (owner's engineer and external consultants included):
   does anyone hold a conflict with a specific bidder? Record the roster date and the count of
   recusals (names stay out of the repository; they live in the deny-list table, which is data).

Write `docs/decisions/ADR-002-access-label-facts.md` from the template in §4 with the outcome.

## 2 · Code readiness — agent half, ships regardless of outcome

### Outcome A — both no: the boolean, as built

Nothing changes. The readiness deliverable is the **register check** (§3) and the ADR.

### Outcome B — an NDA exceeds "need to know": `restricted_group`

Prepared, **not applied**: `sql/proposals/restricted_group.sql` — `ALTER TABLE document ADD COLUMN
restricted_group text NULL` (NULL = general), `chunk` likewise via the inheritance trigger, and the
rewritten policy set: `document_is_visible(p_document_id)` replaces `document_is_restricted()` and
reads `current_setting('app.groups', true)` (a comma-separated list the principal context sets)
instead of the boolean GUC; the RESTRICTIVE policy keeps the app role from setting it. The proposal
directory is **outside** the lexical apply order so CI does not apply it; a test asserts the
proposal parses (`psql --dry-run` is not a thing — apply it to a throwaway database in the `sql`
job and run the existing attack matrix against it, then drop). `PrincipalContext` gains
`groups: frozenset[str]` (empty today). Adopting outcome B is: move the file to `sql/13_…`, flip the
principal to populate `groups`, re-run the grant and attack matrices. D-15's estimate of ~40
policies is what the proposal file contains, so the cost is known before it is paid.

### Outcome C — recusal only: per-person deny-list, keeping the boolean

Prepared and **applied** (it is additive and harmless when empty): `sql/13_access_denylist.sql` —
`public.access_denylist(subject text, supplier text, recorded_at timestamptz, recorded_by text,
PRIMARY KEY (subject, supplier))`, append-only like `resolution`, owner-writable only.
`PrincipalContext.denied_suppliers` is populated from it at connection time (Story 4's
`open_transaction`), and:

- `DocumentRepository.visible_ids(principal)` excludes documents whose claims name a denied
  supplier;
- Story 2's `retrieve()` passes that set as `allowed_document_ids` (scoping within the
  entitlement — RLS still governs restricted documents);
- Story 5's queue excludes entries for denied suppliers **in the service**, since a recusal is an
  exclusion, not a clearance (D-15's own words), and the UI never sees them.

A test seeds one recusal and asserts all three exclusions hold for that principal and none for
another.

## 3 · Re-arming — the register

`docs/access-review.md`: a table of (date, what was reviewed — NDA hash or roster date, outcome,
reviewer). `Settings.access_review_max_age_days` (new, default 90). At ingest of any document
classified into a restricted type, Story 1's `ingest()` checks the register's latest date; if older
than the setting, it **warns** in the structured log and the run event and labels the document
restricted as usual — it never blocks ingest (D-30; D-15 says too-restrictive blocks a reviewer,
too-permissive leaks, so the safe failure is already the default label). The UI dashboard shows
the register age.

## 4 · ADR-002 template

```
# ADR-002 — Access-label model: the D-15 facts

Status: Accepted <date> · Supersedes: D-15's provisional status

## Facts
1. NDA scope: <n> executed NDAs read (table: title · date · sha256 · named-individuals · access-log · segregation). Outcome: yes/no.
2. Evaluator recusal: roster as of <date>; <k> recusals recorded in access_denylist. Outcome: yes/no.

## Decision
Outcome A | B | C per D-15's table, with the configuration applied.

## Re-arming
Register at docs/access-review.md; next review due <date>; triggers: new NDA, new evaluator, new supplier.
```

## Verify

Minimum new tests: 15.

- `test_denylist_excludes_documents_retrieval_and_queue_for_denied_principal_only` (live)
- `test_denylist_is_append_only` (live attack)
- `test_principal_context_populates_denied_suppliers` · `test_empty_denylist_changes_nothing`
- `test_restricted_group_proposal_applies_and_passes_attack_matrix` (throwaway database in the `sql` job; dropped after)
- `test_proposal_directory_is_not_in_apply_order` (reads `sql/README.md` apply glob)
- `test_stale_register_warns_and_labels_restricted_never_blocks`
- `test_adr_002_exists_or_status_says_provisional` — until the human half lands, `docs/current-state.md` must still say "provisional"; this test keeps the two documents from disagreeing.

**Gates at merge:** four local gates; `sql` job green with `13` applied.

## Traps

- Outcome C is cheaper than B by an order of magnitude; do not build B "while we are at it".
- The deny-list is data with names in it; it lives in the database, never in a fixture or in the ADR.
- Retrieval scoping through `allowed_document_ids` is **not** how restricted documents are protected — RLS is. A recusal exclusion in the allow-list is correct because it is an exclusion within an entitlement, which is exactly the port's documented role.

## Out of scope

Choosing the outcome. Per-supplier clearance matrices (rejected in D-15 as contrary to the
side-by-side deliverable). Time-based sealing of pricing until technical scoring closes — D-15 lists
it as a policy on the same label; it is a Story 5 dashboard feature if the product owner asks.

---

*Clarifications Q-5 – Q-16 cited by this story were ratified on 2026-09-03 as D-19 – D-30 in [clarifications.md](../clarifications.md); the D-entries are the authority.*
