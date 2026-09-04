# Phase 2 clarifications — questions the stories could not settle, with recommended defaults

Numbering continues from [phase-1-execution.md](../phase-1-execution.md) (Q-1..Q-4). Each entry
names what it blocks, the options, the recommended default and its confidence, and what would
overturn it. **Nothing here is adopted until it is ratified**; a track builds to the recommended
default and records the assumption in its PR. Adopting means folding the answer into
[clarifications.md](../clarifications.md) as a D-19+ entry and marking the row here.

Format follows [open-decisions.md](../open-decisions.md).

> **Ratification, 2026-09-03.** Q-5 through Q-16 were ratified on their recommended defaults and
> folded into [clarifications.md](../clarifications.md) as **D-19 – D-30**. The entries below are
> kept as the record of the options considered; the D-entry is now the authority. Q-1 stays open.
> Q-6's commercial half (buy storage rights or change provider) stays with the product owner.

| Q | Ratified as | Q | Ratified as |
|---|---|---|---|
| Q-5 | D-19 | Q-11 | D-25 |
| Q-6 | D-20 (engineering rule) | Q-12 | D-26 |
| Q-7 | D-21 | Q-13 | D-27 |
| Q-8 | D-22 | Q-14 | D-28 |
| Q-9 | D-23 | Q-15 | D-29 (amends D-14) |
| Q-10 | D-24 | Q-16 | D-30 |

---

## Q-1 — D-15's two facts (carried)

Unchanged from Phase 1. Owner: a human. Blocks: Story 7's content half only. All three outcomes
are pre-built by Story 7; see [story-7](story-7-access-labels.md). **Open.**

---

## Q-5 — Word documents carry no page number in Docling provenance

> **RATIFIED 2026-09-03 → [D-19](../clarifications.md).** D-19

**Blocks:** Track 1a (FR-ING-05 promises "source, page and caption" for Word tables).

**Fact** (research.md): `DoclingDocument` populates `prov[].page_no` from a page model Word does
not have; `.docx` tables arrive with empty `prov`.

| Option | Cost | Failure direction |
|---|---|---|
| **A. Convert `.docx` → PDF (LibreOffice headless) at ingest, parse the PDF, keep the `.docx` bytes as the stored document** | a system dependency already needed by Story 6's CI gate; ~2–3 s per document | Loud: absent `soffice` declares a `PAGE_NUMBERS` absence in the conformance matrix |
| B. Record `section` (heading path) and `page=None` for Word | none | Silent for a reader who expects a page in the Sources tab |
| C. Estimate pages from character count | none | Wrong pages presented as real — worst of the three |

**Recommended: A**, with `section` recorded for every element in every format regardless.
**Confidence: firm.** Overturned only if the deployment cannot run LibreOffice, in which case B is
the fallback and FR-ING-05's "page" becomes "section" for Word — a spec amendment, made loudly.

---

## Q-6 — Web-result storage rights versus FR-WEB-02

> **RATIFIED 2026-09-03 → [D-20](../clarifications.md).** D-20 (engineering rule; commercial half open)

**Blocks:** Track 3.

**Fact** (research.md): Brave's API terms prohibit storing or caching Search Results beyond
transient operational storage and prohibit using them to evaluate or improve AI models; storage
rights are a bespoke plan. FR-WEB-02 requires the query, URL, page title and retrieval timestamp
to be logged for reproducibility, and NFR-02 makes the log immutable.

| Option | Reading |
|---|---|
| **A. Persist the query string (ours) and the fetched page (the publisher's content, under the publisher's terms); carry only URL, title, `retrieved_at`, authority on the claim; never persist provider rank, snippet or result metadata** | The stored artifacts are our query and a third-party web page; the provider's *result list* is transient. This is the reading most defensible under the general terms |
| B. Subscribe to a plan with storage rights | Cost; removes the question |
| C. Use a provider whose terms permit storage | Tavily and SerpAPI restrict competitive use and resale rather than storage; SerpAPI's Legal Shield covers scraping liability on paid plans. Both remain wrappers over indices we do not control |

**Recommended: A as the engineering rule regardless of provider, and B or C as a commercial
question for the product owner before the first production query.** `WebHit` deliberately has no
snippet or rank field so the rule is structural. **Confidence: firm on A as engineering; the
legal reading needs counsel.** Also: the gold set must not be built from search results (the
"evaluate or improve models" clause).

---

## Q-7 — Reviewer surface stack

> **RATIFIED 2026-09-03 → [D-21](../clarifications.md).** D-21

**Blocks:** Track 5. `plan.md` never chose one; WP-F.5 only says the UI must be built.

Constraints: licence gate (MIT/BSD/Apache); Decision 10 (sync ports; per-process concurrency);
D-15 (clearance from the OIDC subject); D-10 (resolution in the application); a team of agents that
must not spend the story on a front-end toolchain.

| Option | Licences | Notes |
|---|---|---|
| **A. FastAPI + Jinja2 + HTMX, server-rendered, Authlib for OIDC, uvicorn; sync handlers in FastAPI's threadpool; no JS build** | MIT / BSD-3 / BSD-2 / BSD-3 / BSD-3 | Provenance-heavy tables are a server-rendering problem; HTMX gives partial updates without a bundle |
| B. React/Next front end + FastAPI API | MIT | A second toolchain, a build step, and client state of record for a workflow whose record is the database |
| C. Streamlit/Gradio | Apache-2.0 | Fast to start; poor fit for OIDC session semantics and for a five-action form with server-side validation |

**Recommended: A.** **Confidence: reasoned.** Overturned if the product owner requires a design
system the team already runs in React.

---

## Q-8 — Extraction LLM

> **RATIFIED 2026-09-03 → [D-22](../clarifications.md).** D-22

**Blocks:** Track 1c. `plan.md` Decision 7 fixes vLLM, `json_schema` mode and logprobs but names
no model; `.env.example` has `PROCUREMENT_LLM_MODEL=` blank.

Constraints: licence gate; NFR-03 self-hosted; structured outputs with xgrammar; logprobs.

| Option | Licence | Notes |
|---|---|---|
| **A. `Qwen/Qwen3-30B-A3B-Instruct-2507`** | Apache-2.0 | MoE, 3.3 B active, 262 K native context, `vllm>=0.8.5`; known non-termination under `json_schema` fixed by `--structured-outputs-config '{"backend":"xgrammar","disable_any_whitespace":true}'` |
| B. `Qwen/Qwen3-32B` (dense) | Apache-2.0 | Simpler serving; ~5× slower than A on the same card |
| C. Llama family | Llama Community License | **Fails the licence gate** (not Apache/MIT/BSD) |

**Recommended: A**, with B as the documented alternate. Launch flags become part of the adapter's
server contract along with `--logprobs-mode raw_logprobs`. **Confidence: reasoned; re-benchmark
on the gold set** (D-11) before any accuracy claim.

---

## Q-9 — `ParsedElement` shape extension (P2-C1)

> **RATIFIED 2026-09-03 → [D-23](../clarifications.md).** D-23

**Blocks:** Track 0.

`ParsedElement(kind, text, page)` cannot carry a bounding box (FR-ING-04; the `OCRPort` docstring
promises one), table structure (FR-ING-02), page quality (D-3's "low-quality scan" hard gate) or
role (FR-ING-05 headers/footers/footnotes). The conformance matrix pins `__annotations__`.

| Option | Consequence |
|---|---|
| **A. Additive optional fields on `ParsedElement` (`bbox`, `table`, `page_quality`, `role`), kinds unchanged, pin updated in the same PR** | Every `isinstance` and every existing adapter stays valid; the pin becomes the new shape |
| B. A `TableElement` subclass | Two carriers; every consumer grows an `isinstance` branch |
| C. Side-channel dict on the adapter | Invisible to the contract; the Phase 1 lesson about equality assertions applies |

**Recommended: A. Confidence: firm.**

---

## Q-10 — Gold-label representation

> **RATIFIED 2026-09-03 → [D-24](../clarifications.md).** D-24

**Blocks:** Track 1d harness.

D-16 makes `human:` claims carry a `Resolution`; gold labels are not decisions about a conflict.

| Option | Consequence |
|---|---|
| **A. `FieldClaim` with `extractor_version="gold:<annotator>"`, `source_tier=system_of_record`, never committed to any claim store; documents outside the repo under `PROCUREMENT_GOLD_CORPUS_DIR`, keyed by `content_hash` in a committed manifest** | Reuses the frozen record and its validators; the store cannot be polluted because nothing writes `gold:` claims to it (a test asserts `commit_claims` refuses the prefix) |
| B. A separate label schema | A second vocabulary to keep aligned with the contract |
| C. Commit the documents | Confidential and copyrighted material in a public repository |

**Recommended: A. Confidence: firm.**

---

## Q-11 — Where the lexical leg lives (P2-C3)

> **RATIFIED 2026-09-03 → [D-25](../clarifications.md).** D-25

**Blocks:** Track 0, Track 2.

Decision 3b requires dense + `tsvector` + `pg_trgm` fused by RRF. No port can serve the lexical
side.

| Option | Consequence |
|---|---|
| **A. New `LexicalSearchPort` beside the six** | Additive; the memory reference is trivial; conformance matrix gains one row; `VectorStorePort` unchanged |
| B. `search_lexical()` added to `VectorStorePort` | Every vector adapter must implement lexical search or declare an absence, including vendors that have none |
| C. Fuse inside the pgvector adapter only | Hides hybrid retrieval from the contract; the memory reference cannot express the part-number test |

**Recommended: A. Confidence: firm.**

---

## Q-12 — Scheduling the CEC weekly pull

> **RATIFIED 2026-09-03 → [D-26](../clarifications.md).** D-26

**Blocks:** Track 3, Track 4b.

`Stage` has six members matching `sql/08`'s CHECK; a CEC refresh is not a document job.

**Recommended:** a CLI subcommand (`procurement-agent cec-refresh`) driven by an external
scheduler (cron, systemd timer, the platform's scheduler); its run is a `run:` audit stream. Not a
`Stage`; no seventh job kind. **Confidence: firm.**

---

## Q-13 — Linking a human claim row to its resolution (P2-C6)

> **RATIFIED 2026-09-03 → [D-27](../clarifications.md).** D-27

**Blocks:** Track 4a, Track 5.

`sql/04_claim.sql` has no `resolution` column; D-16 acknowledges the Python record is ahead of the
DDL.

| Option | Consequence |
|---|---|
| **A. `claim.resolution_id text NULL REFERENCES resolution` + `CHECK ((extractor_version LIKE 'human:%') = (resolution_id IS NOT NULL))`; insert resolution first** | Mirrors the Python validator exactly; `resolution.selected_claim_id` keeps pointing at the *candidate* claim, the new column points from the *human* claim to its decision |
| B. Store the `Resolution` JSON on the claim row | Two copies of the decision; append-only rows cannot be reconciled |
| C. Derive by joining `resolution.resolved_by` and time | Fragile; `human:` claims from the same reviewer at the same second collide |

**Recommended: A. Confidence: firm.** Forward-only file `sql/10_claim_resolution_link.sql`, the
Phase 1 `sql/09` pattern.

---

## Q-14 — CLI framework

> **RATIFIED 2026-09-03 → [D-28](../clarifications.md).** D-28

**Blocks:** Track 4b. **Recommended:** stdlib `argparse`; core dependencies stay thin (the
`pyproject` comment's rule). Typer/Click are fine licences but add nothing the CLI needs.
**Confidence: reasoned.**

---

## Q-15 — A-51: `ProjectionPolicy` and the τ table

> **RATIFIED 2026-09-03 → [D-29](../clarifications.md).** D-29 (amends D-14)

**Blocks:** Track 6, Track 1c.

`policy_version` labels a τ table that did not exist. When `threshold_for(field_name)` lands, does
the policy embed the table by value or reference it by name?

**Recommended: by value** (`thresholds: Mapping[str, float]` inside `ProjectionPolicy`), so the
D-14 hash changes whenever τ changes — the hash exists to change exactly when the workbook would.
By name would let two different thresholds share one hash. Cost: one structural re-baseline of the
golden fixture, reviewed as "one added key, identical field rows". **Confidence: firm.**

---

## Q-16 — A stale access-review register at ingest

> **RATIFIED 2026-09-03 → [D-30](../clarifications.md).** D-30

**Blocks:** Track 7, Track 1a.

When the D-15 register (`docs/access-review.md`) is older than `access_review_max_age_days` and a
restricted-type document arrives: block, warn, or ignore?

**Recommended: warn** (structured log + run event) and label restricted as usual. D-15 already
states the asymmetry — too-restrictive blocks a reviewer, too-permissive leaks — and the default
label is the safe direction, so blocking ingest buys nothing. **Confidence: firm.**

---

## Not questions

Raised during research and answered by existing decisions, listed so they are not re-asked:

- *Should `Stage` gain a `reduce` member?* No — the reducer is `detect_conflicts` (runtime constraint 1; P2-A-5).
- *Should ports become async for the UI?* No — Decision 10; FastAPI runs sync handlers in a threadpool.
- *Should `openpyxl` be upgraded?* No newer release exists (research.md).
- *Should an HNSW index be added now that pgvector 0.8.6 has iterative scans?* No — Decision 3a; the migration trigger is ~5 M chunks.
