# Story 6 — Workbook finish (WP-G G.3–G.8, alternate orientation, tabs 12–13 layout)

**Track:** 6 · **Team:** 8 · **Needs:** Track 0 (P2-C2 for the Sources tab shape); consumes
Story 1c's `threshold_for()` when it lands, works without it · **Status:** proposed 2026-09-03

**Story.** The lead opens the workbook and reads state without a legend: origin by fill,
confidence by font, conflict by border, missing as literal text — all four states distinguishable
when they co-occur, on screen, in greyscale and to a colour-blind reader. A sort does not detach a
value from its provenance. The Conflicts tab lists every open item with its severity, age and a
link into the review queue; the Sources tab lets a reader walk from any cell to the document and
page. The completeness manifest says what is missing. Two generations from one store are
byte-identical, and the file opens in LibreOffice in CI and in desktop Excel on a checklist.

**Done means.** G.3, G.4, G.7, G.8 asserted in the generator **and** in tests; the LibreOffice
half of G.6 runs in CI; the desktop-Excel half is a signed checklist in
`docs/current-state.md`; `suppliers_as_rows=False` renders; AC-3 moves to `enforced` for the
formatting half. **AC-7 keeps its "gated on G.6" caveat until both halves are recorded**
(LibreOffice CI gate **and** the signed desktop-Excel checklist). Landing the LibreOffice job
alone does not move AC-7.

---

## Controlling decisions

| ID | Rule |
|---|---|
| Decision 8 / 8a / 8b / 8c | `openpyxl==3.1.5` exact; provenance in **hidden parallel columns**, no blank column, `auto_filter.ref` spans them; comments decorative only; `=HYPERLINK()` formulas never `cell.hyperlink`; three orthogonal channels with the pinned ARGB values, italic, medium border, `numFmt` glyph; 8-digit ARGB always; `ExcelWriter` direct, 1980-01-01 **12:00**, `[Content_Types].xml` first, `zi._compresslevel`; hash the projection, keep the xlsx hash as a renderer test |
| D-14 | Projection bytes frozen; policy and flags inside the hash; `generated_on` from the store; no enum `repr()` in hashed order |
| D-10 | Conflicts tab read-only except three annotation columns (unlocked, non-persisting); protection is a signpost |
| D-9 | Eight category tabs; thirteen total |
| D-12f, open-decisions §5 | `baba_status` stays `unconfirmed`; suppress BABA from the Executive Summary scorecard; populate evidence columns regardless |
| A-11, A-51, D-29 | `threshold_for(field_name)` replaces the single float; τ table embedded in `ProjectionPolicy` by value |
| FR-OUT-01, FR-OUT-04..06 | Orientation configurable; four states co-occurring and distinguishable; certification columns per category; canonical units with verbatim available; generated-on and source vintages |
| AC-6 | TRD (not TDD) against the IEEE 2800 voltage-class limit with a harmonic spectrum; tax status across three frameworks |

## Code surface today

- `services/output/__init__.py`: `write_workbook(components, destination, *, suppliers_as_rows=True, confidence_threshold) -> Path`; `suppliers_as_rows=False` raises `NotImplementedError` (L172–175); all 13 tabs created; category sheets carry Supplier/Model/Field/Condition/Value/Unit/Confidence/Flags/Provenance as **visible** columns; fill by flag precedence via `_FLAG_FILLS` only; provenance also as a cell comment; Summary/Open Items/Sources/Compliance/Tax are stubs; `normalize_archive` (1980 12:00, Content_Types first, Unix attrs, compresslevel 6, `Application` pin).
- `services/output/projection.py`: `project_store(..., policy)` → D-14 bytes; `ProjectionPolicy(policy_version, confidence_threshold)`; per-field `flags` from `flags_for`; `fold_generated_on`.
- `flags_for(field, *, confidence_threshold)`; `expected_tabs()`; `CellFlag` four values; `WorkbookTab` thirteen.
- Fixtures: `two-supplier-pv-store.json` + canonical-bytes sha256 (`7f2ff579…`); `test_workbook_determinism.py` pins archive metadata and cross-second byte identity; the slice pins two byte-identical writes.
- **Absent:** hidden state columns, font/border channels, `numFmt` glyph, MATCH/HYPERLINK navigation, completeness manifest, protection, alternate orientation, any desktop or LibreOffice run.

---

## 1 · G.3 — hidden parallel state columns (Decision 8a)

Decision 8a's comparison-tab layout is **suppliers as columns**:

`A: Parameter`, `B..(B+n-1): one column per supplier`, then immediately `n` hidden `_state`
columns, one per supplier, cell text `"<flags>|<claim_id>|<document_id>#p<page>|<confidence>"`
— e.g. `"web,low|CLM-00012003|ds_3.pdf#p47|0.62"`.

That layout is `suppliers_as_rows=False`. Today's writer implements only
`suppliers_as_rows=True` (long-form: Supplier / Model / Field / … as visible columns, one row
per supplier-field). The default in `Settings` stays `True`; this story implements **both**
orientations. The two load-bearing assertions apply to whichever orientation is being written
and live **in the generator** before save, not only in tests:

- `assert ws.column_dimensions[first_state_col].index == last_value_col + 1` — no blank column;
- `assert ws.auto_filter.ref` spans `A1:<last_state_col><last_row>`.

Hidden columns are `hidden=True`, width 0. The visible Flags/Provenance columns of the current
writer are removed; the comment stays on flagged cells only (Decision 8a: decorative, ~120 per
tab). The state string's fields are `encode_value`-rendered so the same claim renders the same
bytes everywhere. For `True`, there is one hidden `_state` column (the value block is already
one cell per row). For `False`, there are `n` hidden columns, one per supplier.

## 2 · G.4 — three orthogonal visual channels (Decision 8b)

| Channel | State | Encoding (exact) |
|---|---|---|
| Fill (origin) | web-supplemented | fill `FFBDD7EE`, font `FF1F3864`; `number_format = '0.0" ᵂ"'` on numeric cells |
| Fill (origin) | missing | fill `FFD9D9D9`, font `FF595959` italic, literal `n/a` |
| Font (confidence) | low-confidence | font `FF7F6000` italic |
| Border (conflict) | unresolved | `medium` left + right `FFC00000`; font `FF9C0006` bold |

Composition is by construction: each channel sets only its own attribute, so web + low = blue fill
and brown italic; conflict + web + low = all three. A test enumerates all 2⁴ flag combinations and
asserts every pair of distinct combinations differs in at least one of {fill, font colour, italic,
border, literal text}; a second test asserts the WCAG contrast figures from the plan (5.71 / 7.81 /
4.76 / 4.96) from the pinned ARGB values, so a colour edit fails loudly. Icon sets and data bars are
not used (asserted absent).

`low-confidence` is computed with `threshold_for(field_name)` when `services.confidence` provides
it and with `confidence_threshold` otherwise; `ProjectionPolicy` gains `thresholds: Mapping[str,
float]` embedded **by value** (D-29), so the D-14 hash changes when τ changes. The two-supplier
fixture's `policy_version` stays `fixture-2026-08-12` with a `thresholds` map that reproduces the
0.80 float for every field — the committed bytes **do** change once, and the re-baseline is
reviewed as "one added key, identical field rows".

## 3 · G.6 — the desktop gate, split honestly

**LibreOffice half, in CI** (new `workbook` job): `soffice --headless -env:UserInstallation=
file:///tmp/lo_$RANDOM --convert-to pdf --outdir out generated.xlsx`; assert the PDF exists and is
non-empty (**exit codes lie**); assert page count ≥ 13 via a stdlib-free check on `/Type /Page`
occurrences; re-open the xlsx with `openpyxl.load_workbook` and assert the 13 tab names in order,
the hidden state columns still hidden, and `auto_filter.ref` intact after LibreOffice's own
round-trip (`--convert-to xlsx` then reload). This proves the 1980 timestamps and
`[Content_Types].xml`-first ordering do not offend a second implementation.

**Desktop Excel half, human**: a checklist in `docs/current-state.md` (opens without repair
prompt; hidden columns hidden; sort on a category tab keeps state columns aligned — sort by
column B, check `_state` moved with it; HYPERLINK formulas navigate; conditional formats render;
`ᵂ` glyph prints) with Excel version, OS, date and signer. AC-7's caveat is removed only when
both halves are recorded.

## 4 · G.7 — Conflicts and Sources tabs with navigation

**Conflicts & Open Items**: one row per open queue entry and per `review_required` field
(FR-HITL-05): entry id, category, supplier, model, field, condition, conflict class, severity, age
in days, candidate count, explanation, **deep link** `=HYPERLINK("<ui_base>/conflicts/<entry_id>",
"Review")` (D-10 mitigation; `ui_base` from settings, blank → no formula), and a `=HYPERLINK(
"#'<Tab>'!<cell>", "Go to cell")` computed with `MATCH` over the tab's Parameter column so the
link survives a sort. Three trailing annotation columns (Status / Owner / Note) are unlocked;
the sheet is protected with the D-10 note in row 1.

**Sources & Provenance**: one row per `SourceDocument` (id, type, URI, vintage, ingested,
restricted flag, chunk count) and one per distinct `(document, page)` referenced by any cell, with a
back-link to the first referencing cell via the same `MATCH` pattern. For web pages the row shows
URL, title, retrieved-at and authority.

## 5 · G.8 — completeness manifest

`manifest(store, *, threshold) -> Manifest` lists every unresolved conflict (id, field, severity,
status, age), every `review_required` field, every `PARSE_FAILED` page, and whether the compose gate
blocked at this threshold. It is rendered on the Executive Summary (top block) and as
`manifest.json` beside the xlsx, and is what Story 4's compose stage writes when the gate blocks.
Its bytes derive from the projection, so it is deterministic by construction.

## 6 · Alternate orientation (FR-OUT-01)

`suppliers_as_rows=True` (default, already implemented as long-form) keeps Supplier / Model /
Field as columns and adds the hidden state block per §1. `suppliers_as_rows=False` is Decision
8a's matrix (Parameter in `A`, one supplier per value column) — the `NotImplementedError` at
L172 is removed. The two orientations render from one projection; a test renders both and
asserts identical cell *sets* (value, flags, provenance) under transposition. G.7's `MATCH`
over the Parameter column applies only to the `False` matrix; the `True` long-form matches on
the Field column.

## 7 · Tabs 12–13 layouts (AC-6, open-decisions §5)

Layout only; content arrives with extraction. **Compliance Matrix**: per supplier per category the
compliance keys from the contract's compliance section; for inverters a TRD column with the IEEE
2800 voltage-class limit column beside it and a harmonic-spectrum reference column (the header says
**TRD**; a test asserts no header reads "TDD"). **Tax Incentives**: three separate frameworks
(§48E, BABA, FEOC) as separate blocks; `baba_status` renders `unconfirmed` with a banner when
funding is unconfirmed and is **absent from the Executive Summary scorecard**; evidence columns
render regardless of status.

## 8 · Renderer regression hash

`tests/fixtures/workbooks/two-supplier-pv-store.xlsx.sha256` — the xlsx bytes for the golden store
under a pinned `ui_base=""`. Its purpose is Decision 8c's: catch an accidental openpyxl change or a
formatting drift; it is **not** the integrity artifact (the projection hash is) and a change to it
is expected whenever this story changes layout — the PR must say so.

## Verify

Minimum new tests: 45. Named:

- `test_no_blank_column_between_value_and_state_block` · `test_auto_filter_spans_hidden_columns` · `test_generator_asserts_both_before_save` (mutate the writer, expect `AssertionError`)
- `test_state_cell_format` · `test_state_columns_hidden`
- `test_all_sixteen_flag_combinations_distinguishable` · `test_pinned_argb_contrast_meets_wcag_aa` · `test_missing_renders_literal_na` · `test_web_numeric_carries_glyph_number_format` · `test_no_icon_sets_or_data_bars`
- `test_threshold_for_used_when_available` · `test_policy_embeds_thresholds_by_value_and_changes_hash` · `test_golden_rebaseline_is_one_added_key` (compares old and new fixture JSON structurally)
- `test_hyperlink_formulas_not_cell_hyperlink` · `test_go_to_cell_link_uses_match` · `test_deep_link_uses_entry_id`
- `test_conflicts_tab_lists_every_open_entry_and_review_required_field` · `test_conflicts_tab_protected_except_annotation_columns`
- `test_sources_tab_lists_every_referenced_document_page` · `test_web_source_rows_show_url_title_retrieved_at_authority`
- `test_manifest_lists_blockers_and_matches_gate` · `test_manifest_json_deterministic`
- `test_alternate_orientation_renders` · `test_orientations_are_transposes`
- `test_trd_not_tdd_header` · `test_baba_absent_from_summary_scorecard_when_unconfirmed` · `test_tax_frameworks_are_three_blocks`
- `test_two_generations_byte_identical` (exists; keep) · `test_renderer_hash_matches_sidecar`
- CI `workbook` job: LibreOffice conversion, page count, reload assertions; fails on missing output file.

**Gates at merge:** four local gates; `workbook` job green; both golden sidecars updated with the
structural re-baseline note; `docs/current-state.md` AC-3/AC-7 rows updated with the LibreOffice
evidence and the (still open) desktop checklist.

## Traps

- `openpyxl` serialises `"BDD7EE"` as `rgb="00BDD7EE"` — zero alpha, invisible. 8-digit ARGB always; a test greps every `PatternFill`/`Font`/`Side` for 8-digit values.
- `cell.hyperlink` is address-keyed and breaks on sort; `=HYPERLINK()` formulas move with the cell. The existing formula-escape test (`test_vertical_slice.py` L406–425) must still pass — user text beginning with `=` is escaped, generated formulas are not.
- `save_workbook()` re-stamps `modified`; the writer must keep driving `ExcelWriter` directly.
- A LibreOffice round-trip **changes** the bytes; the byte-identity test is on our writer's output, never on LibreOffice's.
- `MATCH` over a sorted column is exactly the point; do not cache row numbers into the formula.

## Out of scope

Tabs 12–13 *content* extraction (Phase 3); Excel round-trip import (D-10 option 2); any change to
D-14's field-row bytes beyond the `thresholds` key.

---

*Clarifications Q-5 – Q-16 cited by this story were ratified on 2026-09-03 as D-19 – D-30 in [clarifications.md](../clarifications.md); the D-entries are the authority.*
