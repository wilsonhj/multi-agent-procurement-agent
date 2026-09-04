# Story 3 — Gap-only web enrichment (WP-D)

**Track:** 3 · **Team:** 5 · **Needs:** Track 0 (P2-C4, P2-C8, P2-C9), Track 4a (repositories,
`PrincipalContext`, P2-C7 `audit.run_event`), Track 4b (runner, for AC-2) · **Status:** proposed 2026-09-03

**Story.** When a supplier's documents do not state a value the comparison needs, the tool looks
for it publicly, records exactly what it asked and where the answer came from, marks the value
supplementary, and — when a public value contradicts a record value — raises a conflict and leaves
the record untouched. It never fills a field that already has a system-of-record value.

**Done means.** AC-2 is demonstrated **from ingestion through to a queue entry**, not at the guard
function: a store holding a system-of-record `nameplate_power=650` and a web claim of `655`
produces one `ConflictQueueEntry` of class `RECORD_VS_WEB`, the projected field still shows 650,
and `docs/current-state.md`'s AC-2 row moves from "partial" while `tasks.md`'s "passing" is
corrected to agree (P2-A-13).

---

## Controlling decisions

| ID | Rule |
|---|---|
| FR-WEB-01..05 | Gap-only or explicit request; tag `web_supplement` with URL, title, timestamp; **log the query**; fill empty only; raise conflicts beyond tolerance; record authority |
| C-1, C-2, FR-HITL-02 | Web never overwrites a system-of-record value; no auto-arbitration |
| D-2, D-17 | Divergence judged by the field's tolerance row; sets compared as sets |
| D-8 / D-8a | CEC is an authority for PV modules and inverters, **not** utility-scale BESS; weekly pull of the four CEC **XLSX** exports from `solarequipment.energy.ca.gov` (D-8). D-8a separately: live SAM **CSVs** from the NREL/SAM repo for single-diode coefficients; never pvlib's bundled CEC data |
| D-12d | `request_more_web_search` reopen cap at 3 |
| D-13 | `web_search` is a **run-scoped** event on `audit.run_event`, not on the per-document chain (A-49) |
| D-16 | A human selecting the web value is `SELECT_VALUE`; a web value with no decision is still refused by the overwrite guard |
| agent-topology | Fan-out on gap fields, capped hardest; every query logged regardless of outcome |
| ADR-001 §3 | Producer-side bounds and explicit timeouts |

## Code surface today

- `services/web_search`: `SOURCE_AUTHORITY_ORDER` (manufacturer_datasheet → ul_tuv_intertek → ieee_nfpa → ercot_puct_tceq → irs_treasury); `search_for_gap(field_name, supplier, model) -> list[CanonicalField]` raises. **Returning `CanonicalField` contradicts C8 — extractors emit claims** (P2-A-4).
- `SourceRef` already carries `url`, `page_title`, `retrieved_at` (tz-aware), `source_authority`.
- `SourceDocument` accepts any `source_uri`; `content_hash` UNIQUE dedups fetched pages exactly as it dedups uploads.
- `services.claims.project()` / `_preferred` ranks `system_of_record` above `web_supplement`; `assert_no_autonomous_overwrite` is the chokepoint inside `commit_claims`.
- `audit.EVENT_TYPES_V1` lists `web_search` but it is unreachable on `doc:` streams until `run_event` exists.
- `Settings.web_search_api_key: SecretStr`, `web_search_rate_limit_per_minute=30`. **No provider setting.**

---

## 1 · Gap planning (D.1) — `services/web_search/planner.py`

A **gap** is `(component, field_name, condition)` for which `project()` yields no
system-of-record claim, or for which a reviewer recorded `REQUEST_MORE_WEB_SEARCH`. Planning
reads the registry: each `FieldSpec` gains an optional `web_query_template` (P2-C9, written by
Track 0; this story fills it for the fields worth searching). Fields with no template are never
searched — silence is the default. Tier A fields **may** be searched (a public UL listing is
useful evidence) but their claims always route to review (D-3).

Explicit request path: `search_for_gap(..., requested_by=principal)` bypasses the gap check and
records the requester on the run event.

## 2 · P2-C4 — `WebSearchPort` and adapters

```python
@dataclass(frozen=True)
class WebHit:
    url: str
    title: str | None
    retrieved_at: datetime  # tz-aware
    provider: str


class WebSearchPort(Protocol):
    def search(self, query: str, *, limit: int) -> list[WebHit]: ...
```

**Deliberately absent from `WebHit`: snippet and rank.** Under D-20 the provider's result list is
transient; only the URL is carried forward, and the page at that URL is fetched and stored under
the publisher's terms. Adapters: `adapters/web_search/memory.py` (reference; deterministic hits
from a fixture map), `adapters/web_search/brave.py` (default provider; `X-Subscription-Token`
from `Settings.web_search_api_key`; honours `web_search_rate_limit_per_minute` with a token bucket
**in the adapter**, per ADR-001 §3; explicit `timeout`). `Settings.web_search_provider: str =
"brave"` selects the registry entry. Capabilities: `DETERMINISTIC_OUTPUT` (reference only),
`RATE_LIMITED`.

## 3 · Fetch and persist (FR-WEB-02, NFR-01) — `services/web_search/fetch.py`

Each `WebHit.url` is fetched under **P2-C10**: HTTPS only (`http` is upgraded or refused);
RFC1918, link-local, loopback and cloud-metadata IPs are blocked after DNS **and** after every
redirect (max 3); explicit timeout and size cap; `robots.txt` honoured. A blocked URL is a
logged fetch failure, never a `SourceDocument`. HTML → text via the Story 1 Docling adapter's
HTML backend or a stdlib fallback. Persisted as a
`SourceDocument(source_uri=url, document_type=TECHNICAL_DOCUMENTATION,
access_restricted=<inherited from the gap's source document, else True>,
data_vintage=retrieved_at)` with `content_hash` over the fetched bytes — so the same page fetched
twice is one document (AC-5 applies to web pages too), and every web claim's `SourceRef` names a
document **and** a URL. Public-page unrestricted is a reviewer clearance, not the fetch default.
The fetched text is indexed by Story 2 so the Sources tab can show it.

**What is logged where:**

| Fact | Where | Why |
|---|---|---|
| query string, provider, `limit`, requester, gap key | `audit.run_event` `web_search` (P2-C7) | FR-WEB-02 reproducibility; run-scoped because it is not about one document |
| fetched page | `public.document` + chunks | NFR-01: the value's source is the page, not the SERP |
| URL, title, `retrieved_at`, authority | `SourceRef` on the claim | FR-WEB-02 tagging |
| provider rank, snippet, result metadata | **nowhere** | D-20 |

## 4 · Extraction from web pages → claims (D.2, D.4)

The fetched document goes through Story 1's `extract()` with `source_tier=web_supplement` and
`extractor_version=f"web:{provider}@{version}"` (P2-C8). `source_authority` is assigned from the
URL host against a table keyed by `SOURCE_AUTHORITY_ORDER` (manufacturer domains from the
identity module's manufacturer list; UL/TÜV/Intertek; IEEE/NFPA; ERCOT/PUCT/TCEQ; IRS/Treasury);
unknown hosts get `None` and rank last. Claims enter the store only through `commit_claims` — the
reducer — so `assert_no_autonomous_overwrite` runs on every web write by construction (D.4) and a
web claim beside a system-of-record claim yields either agreement (no conflict, field still
system-of-record) or an `OPEN` group → `RECORD_VS_WEB` queue entry (Story 4's `detect_conflicts`).

`search_for_gap` therefore returns `list[FieldClaim]`, not `list[CanonicalField]` (P2-A-4). The
stub is unreferenced; the signature changes in this story with Team 1 review.

## 5 · CEC cross-check (D.5, D-8, D-8a) — `services/web_search/cec.py`

A **separate authority feed**, not a search: weekly pull of the four CEC XLSX exports from
`solarequipment.energy.ca.gov` (D-8; URLs pinned in `cec_source_urls`), parsed with the
Story 1 spreadsheet adapter into claims with `source_tier=web_supplement`,
`source_authority="cec"`, `extractor_version="web:cec@<export-date>"`, surrogate id per D-8,
alias seeding from the `Notes` column into the identity module. D-8a's live SAM CSVs (NREL/SAM
repo, `cec_sam_csv_urls`) are a **second** pull for single-diode coefficients, not the CEC
list location. Never `retrieve_sam()` with defaults — a test asserts the bundled path is not
imported. **Not applied to BESS categories** (D-8) — asserted. Scheduling is a CLI subcommand
(`procurement-agent cec-refresh`) driven by an external scheduler (D-26); it is not a `Stage`.

## 6 · Fan-out and caps

Gap fields are independent; the runner (Story 4) may fan them out. Caps live in the adapter
(token bucket) and in the planner (`max_gap_queries_per_run`, new setting, default 200). Every
query is logged **before** the provider is called, so a crash after the call still leaves the
record FR-WEB-02 requires.

## Verify

Minimum new tests: 30. Named:

- `test_no_query_when_system_of_record_value_exists` · `test_query_when_field_is_a_gap` · `test_explicit_request_bypasses_gap_check_and_records_requester`
- `test_fields_without_template_are_never_searched`
- `test_query_is_logged_before_provider_call` (run event exists even when the provider raises)
- `test_web_hit_carries_no_snippet_or_rank` (dataclass shape pin; D-20)
- `test_fetched_page_becomes_source_document_with_content_hash` · `test_same_page_twice_is_one_document`
- `test_fetch_refuses_internal_url` · `test_fetch_refuses_redirect_to_metadata_ip` ·
  `test_ssrf_response_not_stored` · `test_fetched_page_inherits_gap_restriction`
- `test_web_claim_source_ref_has_document_and_url_and_authority`
- `test_authority_ordering_from_host`
- **`test_ac2_end_to_end`** — SOR 650 + web 655 → one `RECORD_VS_WEB` entry; projected value 650; a second run adds no second entry (idempotent detection). Live variant on the `sql` job.
- `test_web_value_fills_empty_field_as_web_supplement` (flag `WEB_SUPPLEMENTED` appears in the projection)
- `test_web_claim_never_preferred_over_record` (`_preferred` invariant, through `commit_claims`)
- `test_cec_not_applied_to_bess` · `test_cec_bundled_pvlib_data_not_used` · `test_cec_alias_seeding`
- `test_rate_limit_token_bucket` · `test_provider_timeout_is_explicit`
- Conformance: `web_search:memory`, `web_search:brave` registered; `WebSearchPort` added to the matrix.
- Docs: `tasks.md` AC-2 row and `docs/current-state.md` AC-2 row agree after this story (a grep test over both files for the AC-2 row status is acceptable).

**Gates at merge:** four local gates; `sql` job green; `run_event` live tests (Story 4) already
merged.

## Traps

- `CanonicalField` from a web page with no `document_id` **and** no `url` is refused by `SourceRef` — good; do not relax it for "the page vanished" cases, record the fetch failure instead.
- A web claim's `condition` is usually unknown; open-decisions §2's defaults apply the same way as for documents — unqualified PV electrical ⇒ `stc`, inverter temperature **never** defaulted.
- Brave's terms forbid using results to evaluate or improve models: the gold set (Story 1d) must not be built from search results.
- The `web_search` event type must be **removed** from `audit.event`'s CHECK (P2-C7) before this story's first emission, or two chains will disagree about where web queries live.

## Out of scope

Automated selection between a web value and a record value (forbidden); tabs 12–13 regulatory
content fetching (Phase 3 specialist team); any provider other than Brave beyond the port.

---

*Clarifications Q-5 – Q-16 cited by this story were ratified on 2026-09-03 as D-19 – D-30 in [clarifications.md](../clarifications.md); the D-entries are the authority.*
