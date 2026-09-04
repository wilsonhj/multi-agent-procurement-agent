# Story 5 — Review service and reviewer UI (WP-F)

**Track:** 5 · **Team:** 7 · **Needs:** Track 0 (P2-C5, P2-C6, P2-C8), Track 4a (repositories)
· **Status:** proposed 2026-09-03

**Story.** A reviewer signs in, sees the conflict queue ordered by severity and age, leases an
entry, sees every candidate with its verbatim source text, page, tier and authority plus the
generated explanation, and resolves it with exactly one of five actions — select a value, enter an
override with a cited source, keep the system-of-record value, request more web search, or defer.
The decision and rationale persist as a human claim and an immutable audit event; the next workbook
regeneration reflects it; nothing in Excel is a resolution surface.

**Done means.** All five `ResolutionAction`s have a success path through a live PostgreSQL;
two reviewers cannot lease one entry; `REQUEST_MORE_WEB_SEARCH` is refused at the third reopen;
a decision made in the UI appears as `RESOLVED` in the projection and in the regenerated
workbook; the UI passes its HTTP tests under an OIDC test issuer.

---

## Controlling decisions

| ID | Rule |
|---|---|
| FR-HITL-03..06 | Queue entry content; exactly five actions; same queue for conflicts, low-confidence and insufficient-evidence; every decision logged immutably with user, timestamp, before/after, rationale |
| D-10, open-decisions §3 | Excel read-only; resolution in the application; deep link per conflict row; optional `diff_workbook` worklist |
| D-12a | `resolved_by` is the OIDC `sub` |
| D-12c, D-12d, D-12e | Conflicts never expire (age is a metric); reopen cap 3; 15-minute lease |
| D-16 | `SELECT_VALUE`, `ENTER_OVERRIDE`, `KEEP_SYSTEM_OF_RECORD` become human claims with a `Resolution`; `DEFER` and `REQUEST_MORE_WEB_SEARCH` are events against the conflict only; `value_after` equals the claim value; provenance rules per action; settled groups stay settled |
| D-18 | RESOLVED is derived from the presence of a `Resolution` |
| D-15 | Reviewer clearance from the OIDC subject; restricted entries invisible to uncleared reviewers by RLS, not by UI filtering |
| Decision 10 | Sync handlers; FastAPI runs them in its threadpool |
| Licence gate | MIT/BSD/Apache only: FastAPI (MIT), Jinja2 (BSD-3), HTMX (BSD-2 / 0BSD), Authlib (BSD-3), httpx (BSD-3) |

## Code surface today

- `services/vertical_slice.review_conflict(result, *, entry_id, resolution)` supports **only** `SELECT_VALUE` and `KEEP_SYSTEM_OF_RECORD`; refuses the other three ("need sourced persistence paths"); requires `value_after` to match exactly one candidate; stamps remaining sibling pairs OPEN; emits a `resolution` audit intent. In-memory only; no leases.
- `ConflictQueueEntry(entry_id, field_name, supplier, model, component_category, conflict_class, severity, candidates, explanation, detected_at, resolution)`; `ConflictCandidate` carries `verbatim_value`, `source_tier`, `source_ref`.
- `Resolution(action, resolved_by, resolved_at, rationale, value_before, value_after)`; `ResolutionAction.asserts_a_value`.
- `FieldClaim` human rule; `services.claims.project()` prefers the latest human claim by `resolved_at`.
- `sql/05_conflict.sql`: `status`, `lease_owner`, `lease_expires_at`, `reopen_count ≤ 3`; `sql/06_resolution.sql`: five actions, `selected_claim_id`, append-only.
- Story 4's `ConflictRepository.lease/release/mark_resolved/reopen/sweep_expired`, `ResolutionRepository.append`, `PostgresClaimStore.append`, `PrincipalContext`.
- No HTTP app, no auth, no templates anywhere in the tree.

---

## 1 · Review service — `services/review/__init__.py`

```python
class ReviewService:
    def __init__(self, settings, repositories, clock): ...
    def queue(self, principal, *, severity_at_least=None, category=None, supplier=None,
              include_leased=False) -> list[QueueRow]          # ordered severity desc, detected_at asc
    def lease(self, principal, entry_id) -> LeasedEntry           # 15 min; refuses if leased by another
    def release(self, principal, entry_id) -> None
    def resolve(self, principal, entry_id, decision: Decision) -> ReviewOutcome
```

`Decision` is a tagged union over the five actions:

| Action | Input | Effect (one transaction) | Human claim? |
|---|---|---|---|
| `SELECT_VALUE` | `candidate_id`, rationale | `ResolutionRepository.append` → `PostgresClaimStore.append` human claim with the candidate's value and `source_ref` → `mark_resolved` → `resolution` event | yes |
| `KEEP_SYSTEM_OF_RECORD` | rationale | same, candidate = the system-of-record candidate (refused if none exists) | yes |
| `ENTER_OVERRIDE` | `value`, `unit`, `condition`, **`source_ref` cited by the reviewer** (document+page or URL; `SourceRef` validator enforces), rationale | same, with the override value and the reviewer's `source_ref`; `verbatim_value` = the reviewer's typed text | yes |
| `REQUEST_MORE_WEB_SEARCH` | rationale | `ConflictRepository.reopen` (refuses at 3) → enqueue `enrich_via_web` job for the field (Story 4 `JobRepository`) → `resolution` event with `value_after=None` → entry back to `pending`, lease released | no |
| `DEFER` | rationale | `resolution` event with `value_after=None`; entry stays `pending`; lease released; `deferred_count` on the queue row for the age metric | no |

Invariants enforced in the service and asserted by tests: `resolved_by == principal.subject`;
`resolved_at` from the service clock (tz-aware) and shared by the claim, the resolution row and the
event; `value_before` = the projected value at lease time; `value_after` = the claim value for
asserting actions; a second asserting decision on an entry already resolved is refused
(`review_conflict`'s rule, kept); sibling pairs of a non-transitive D-1 group stay `OPEN` with
`resolution=None` while remaining pairs exist (the Phase 1 fix, kept). The human claim's
`extractor_version` is `f"human:{principal.subject}"` (P2-C8).

`queue()` includes low-confidence and insufficient-evidence fields as rows of kind
`review_required` (FR-HITL-05) sourced from the projection's flags, not only conflict entries;
they resolve with the same five actions. `queue()` also drops rows whose supplier is in
`principal.denied_suppliers` (Story 7 outcome C; a no-op while the set is empty). That filter is
an exclusion within an entitlement, not a substitute for RLS.

Age metric: `now - detected_at` per row; `oldest_open_by_severity` on the dashboard. Nothing
expires.

## 2 · Reviewer UI — `ui/` (D-21)

FastAPI app, Jinja2 templates, HTMX for partial updates, no JS build step; `uvicorn` for serving.
Routes:

| Route | Purpose |
|---|---|
| `GET /` | dashboard: counts by severity, oldest open, review budget used vs `Settings.review_budget_fraction` |
| `GET /queue` | queue table with filters; each row deep-links to `/conflicts/{entry_id}` (D-10's mitigation; the workbook's Conflicts tab links here, Story 6) |
| `GET /conflicts/{entry_id}` | candidates side by side: value, unit, condition, verbatim text, page, tier, authority, source link; explanation; age; lease state |
| `POST /conflicts/{entry_id}/lease`, `/release` | HTMX |
| `POST /conflicts/{entry_id}/resolve` | one form per action; server-side validation mirrors the service |
| `GET /documents/{document_id}/page/{n}` | source viewer (rendered page image if Story 1 stored one; else the chunk text) |
| `GET /healthz` | |

Auth: Authlib OIDC (authorization code + PKCE) against `Settings.oidc_issuer`, `oidc_client_id`,
`oidc_client_secret: SecretStr` (new). The session carries `sub` and the clearance claim; the app
builds `PrincipalContext(subject=sub, cleared_for_restricted=<claim>)` per request and every
repository call goes through `open_transaction(principal)`. **The UI never filters restricted rows
itself** — an uncleared reviewer's queue is what RLS returns. `denied_suppliers` is passed through
from the session for Story 7 outcome 2 and is empty today.

Accessibility and safety: server-rendered forms, no client-side state of record; CSRF token on
every POST; rationale required for every action (FR-HITL-06); the "you are resolving in the
application, not in Excel" note per D-10.

`diff_workbook(returned, regenerated)` (open-decisions §3) is **optional** in this story: if
built, it produces a worklist of cells whose values differ, each linking to its queue row, and
imports nothing.

## 3 · Lease sweeper (F.4)

`ConflictRepository.sweep_expired()` runs from the worker loop (Story 4) and from a
`procurement-agent queue sweep` subcommand; expired leases return to `pending`. Tested live with a
patched clock.

## Verify

Minimum new tests: 50. Named:

- Service, live: `test_lease_exclusive_two_reviewers` · `test_lease_expires_and_is_reclaimable` · `test_release_by_non_owner_refused`
- One per action: `test_select_value_creates_human_claim_resolution_and_event` · `test_keep_sor_refused_when_no_sor_candidate` · `test_enter_override_requires_cited_source` · `test_enter_override_value_after_equals_claim_value` · `test_request_more_web_search_enqueues_job_and_reopens` · `test_request_more_web_search_refused_at_three` · `test_defer_releases_lease_and_keeps_pending`
- `test_resolved_by_is_oidc_subject_not_email` · `test_resolved_at_shared_by_claim_resolution_event`
- `test_second_asserting_decision_refused` · `test_sibling_pairs_stay_open` (ported from the slice)
- `test_projection_is_resolved_after_decision` · `test_regenerated_workbook_shows_resolution` (with Story 6's writer; Open Items row disappears)
- `test_low_confidence_fields_appear_in_queue` (FR-HITL-05)
- `test_uncleared_reviewer_queue_excludes_restricted_via_rls` (live; asserts the service issued no supplier/document filter — the exclusion is RLS)
- UI (httpx `TestClient`, mocked OIDC issuer): `test_unauthenticated_redirects_to_issuer` · `test_queue_renders_rows` · `test_conflict_page_shows_every_candidate_with_source` · `test_resolve_requires_rationale` · `test_resolve_posts_through_service` · `test_csrf_required`
- `test_licences_of_ui_dependencies` (reads installed metadata; MIT/BSD/Apache only)

**Gates at merge:** four local gates; `sql` job green; `ui` extra added to `pyproject.toml`
(`fastapi`, `jinja2`, `authlib`, `uvicorn`, `httpx` in dev).

## Traps

- `ENTER_OVERRIDE` without a source is exactly the case the slice refused; the answer is a
  required `SourceRef`, not a relaxed validator.
- `KEEP_SYSTEM_OF_RECORD` must write a resolution and a human claim — "we looked and chose the
  contract value" is distinguishable from "nobody looked" only if it is a row (F.2).
- `REQUEST_MORE_WEB_SEARCH` is the only action that can cycle; the cap lives in the repository
  (`reopen_count ≤ 3` CHECK) **and** the service, so the UI cannot bypass it.
- Do not order the queue by `severity × age`; severity is a lookup (open-decisions §1) and
  priority folds in age separately.
- The human claim's `condition` is the candidate's for `SELECT_VALUE`/`KEEP`, the reviewer's for
  `ENTER_OVERRIDE`; never `None` — `commit_claims` would refuse a dropped condition group.

## Out of scope

Annotations on the Executive Summary (open-decisions §3's `annotation` table — add the table only
if the product owner asks); mobile layout; any Excel round-trip import (D-10 option 2, rejected).

---

*Clarifications Q-5 – Q-16 cited by this story were ratified on 2026-09-03 as D-19 – D-30 in [clarifications.md](../clarifications.md); the D-entries are the authority.*
