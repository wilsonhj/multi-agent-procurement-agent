# Clarifications: resolved ambiguities

**Spec:** [spec.md](spec.md) · **Plan:** [plan.md](plan.md) · **Date:** 2026-07-28

Every ambiguity in the FRD and TRS is resolved here with a researched default rather than left
as a blocking question. Each decision states what it is, why, and how confident it is. **Any of
these can be overruled** — they are defaults, not conclusions.

Findings marked **[V]** were verified against primary artifacts (downloaded CEC XLSX exports,
manufacturer datasheet PDFs, IEC standard text, a live PostgreSQL 18.4 + pgvector 0.8.5
container, a real openpyxl venv). Findings marked **[S]** come from secondary sources.

---

## D-1 — The canonical field needs a third dimension: `condition` ⚠️ SCHEMA CHANGE

**Decision:** add `condition` to the canonical field object alongside `value` and `unit`.
**Confidence: high [V].**

This is the most consequential finding in the research and it changes a frozen contract.

> **Most false conflicts in this domain are not unit errors. They are condition errors.**

A worked example, same product, Sungrow SG350HX **[V]**:

| | EU datasheet | US datasheet | CEC list |
|---|---|---|---|
| AC output | `352 kVA @30℃ / 320 @40℃ / 295 @50℃` | `352 kVA @30℃ / 320 @40℃` | **320.865 kW** |
| MPPT window | `500–1500 V` | `500–1500 V` + `860–1330` full-power | **860 / 1180 / 1330** |
| Efficiency | `99.02% / 98.8% European` | `99.02% / 98.5% CEC` | **98.5** |
| THD | `<1%` | `<3%` | — |

Four *apparent* conflicts and **zero real ones**. CEC anchors on the 40 °C rating and the
full-power MPPT window. Without `condition`, the conflict engine raises four spurious items per
inverter and reviewers learn to ignore the queue — the worst possible outcome for a
human-in-the-loop tool.

The same applies to PV (STC vs NOCT columns sit side by side on Trina sheets; a naive table grab
returns the NOCT figure) and to BESS (AC vs DC side, BOL vs EOL life-point).

**Rule: two values are only comparable when their conditions match. Mismatched conditions are
not a conflict — they are not a comparison at all.**

---

## D-2 — Conflict tolerance: three kinds, per field, never one global band

**Decision:** replace the single `numeric_conflict_tolerance` float with a per-field tolerance
table using three kinds. **Confidence: high [V].**

```
conflict  ⟺  |a − b| > max( field_tolerance , rounding_floor(a, b) )
rounding_floor = ½ × 10^(−min(decimals_a, decimals_b))
```

| Kind | When | Why |
|---|---|---|
| **EXACT** | Catalog/label fields — nameplate power, max system voltage, voltage class | A difference *is* a different product. Nobody measured it; it was chosen. |
| **ABSOLUTE** | Small-magnitude quantities — temperature coefficients, efficiencies in percentage points | Relative bands are meaningless at these magnitudes. |
| **RELATIVE** | Large-magnitude measured quantities — energy, power | Measurement uncertainty scales with the value. |
| **ONE_SIDED** | Transformer losses, no-load current | Both IEC and IEEE state these as upper limits only. A symmetric band is wrong in both regimes. |

`ONE_SIDED` changes the comparison, not just the number:

```
symmetric kinds:  conflict ⟺ |a − b| > max(field_tolerance, rounding_floor)
ONE_SIDED:        conflict ⟺ (b − a) > tolerance          # a = declared, b = measured
```

IEC 60076-1 Table 1 carries the note that where a tolerance in one direction is omitted, that
direction is unrestricted. Writing these as `±` — as an earlier draft of the table below did —
contradicts both the standard and the prose two paragraphs down.

**Declared bands are a separate object.** Where a source prints its own tolerance
(`Power Tolerance 0 ~ +10 W`), that band is data about the product and supersedes any config
default for that field. See
[contracts/canonical-parameters.md § Declared bands](contracts/canonical-parameters.md).

### Why nameplate power is EXACT, not ±3% [V]

**21,797 of 21,989 CEC PV rows (99.1%) have a nameplate Pmax that is an exact multiple of 5 W.**
Bins are 5 W. A ±3% band on a 650 W module is ±19.5 W — it would silently merge **eight adjacent
SKUs**.

The ±3% that Trina prints is *"Measuring tolerance: ±3%"* — flash-test uncertainty on a physical
module, not label tolerance. Importing it into label comparison is a category error.

### Starting tolerance table

| Field | Tolerance | Kind | Basis | Conf |
|---|---|---|---|---|
| PV nameplate Pmax | **±1 W** | abs | 5 W bins; ±1 W absorbs `650` vs `650.0` only | High [V] |
| Module efficiency | ±0.1 pp | abs | Quoted to 1 dp | High [V] |
| γPmax (temp coeff) | **±0.01 %/°C** | abs | Whole modern population spans p5 −0.386 … p95 −0.278 (n=4,749). ±0.01 ≈ 9% of the entire discriminating range | High [V] |
| βVoc | ±0.01 %/°C | abs | median −0.278 | High [V] |
| αIsc | ±0.005 %/°C | abs | median 0.0454, quoted to 2–3 dp | High [V] |
| Degradation yr1 / annual | ±0.05 pp | abs | Contractual, quoted to 2 dp | High |
| Max system voltage | **exact** | — | Discrete (1000/1500); IEC and UL values stored separately | High [V] |
| Inverter AC power | ±1% **within same temperature**, else **no comparison** | rel | 352/320/295 kVA are all "rated" | High [V] |
| Inverter kVA vs kW | **never compare** | — | Different physical quantities | High |
| Max efficiency | ±0.05 pp | abs | Quoted to 2 dp (`99.02`) | High [V] |
| CEC weighted efficiency | ±0.1 pp datasheet↔datasheet; **±0.25 pp vs CEC list** | abs | CEC's headline column is **quantized to 0.5 pp** — only 21 distinct values across 2,104 rows | High [V] |
| BESS energy | ±0.5% within same (side, life-point), else **no comparison** | rel | BOL vs EOL differ ~26% | High |
| BESS RTE | ±0.2 pp same boundary; **no comparison across boundaries** | abs | Boundary shift is worth 2–7 pp | High |
| Transformer MVA | exact, **per cooling class** | — | See D-6 | High |
| PV declared power tolerance | compare as declared bands, never as watts | — | Three conventions in use: `0~+5 W`, `0~+10 W`, `0~+3%`. See contract § Declared bands | High [V] |
| Transformer %Z | ±7.5% if Z≥10%, ±10% if Z<10% (IEC) | rel | IEC 60076-1 Table 1 item 3a, verbatim | High [V] |
| Transformer total losses | **+10% (IEC)** / **+6% (IEEE)** | **one-sided** | IEC Table 1 item 1a reads `+10 %`, not `±10 %` | High [V] / Med [S] |
| Transformer component losses | **+15% (IEC)**, conditional on total not being exceeded | **one-sided** | IEC Table 1 item 1b. `no_load_loss` and `load_loss` are separate contract fields and need their own row | High [V] |
| Transformer no-load current | **+30% (IEC)** | **one-sided** | IEC Table 1 item 5 | High [V] |

### Free cross-validation rules — cheaper and sharper than tolerance bands [V]

These catch extraction errors outright, measured across all 21,989 CEC rows:

| Rule | Empirical band |
|---|---|
| `Pmax ≈ Vmp × Imp` | p5 −0.07%, p95 +0.22% → flag at ±0.5% |
| `PTC / STC` | p5 89.1%, p95 95.1% → sanity band 87–96% |
| `warranty_end = 100 − yr1 − annual×(N−1)` | Reproduces Trina's printed 87.4% exactly |
| `\|γPmax\|` plausible range | 0.15–0.70 %/°C covers 99.94% |
| Sign convention | γPmax and βVoc negative in **100.00%** of rows; αIsc positive in 99.8% |

---

## D-3 — Human-review threshold: a precision target, not a fixed float

**Decision:** delete `hitl_confidence_threshold: 0.80`. Specify a **target precision on
auto-accepted fields** and read τ off a risk–coverage curve computed on a labelled set.
**Confidence: high.**

A hardcoded float is indefensible because it is not derived from anything. The defensible
construction:

- **Target ≥99% precision on auto-accepted fields.** Published work achieves 99.1% automated
  accuracy at 80% coverage against a 73.3% base rate — deferring 20% buys near-perfect
  automation on the rest.
- **Budget 15–25% of field instances to review in year one.** Falling below that means accepting
  <99% precision — that must be an explicit signed-off decision, not an emergent one.
- **Tier τ by field criticality**, in three tiers:

| Tier | Fields | Policy |
|---|---|---|
| **A — never auto-accepted** | Pricing; warranty terms; domestic-content, BABA and FEOC status; certification presence *or absence* | **No confidence score can auto-accept these.** A sufficiently confident wrong extraction here misstates a contractual or tax position, and the cost is not symmetric with the review time saved. |
| **B — strict** | Pmax, Voc, Isc, quantities, dates | Target 99.5% precision |
| **C — standard** | Descriptive and secondary fields | Target 99% precision |

Tier A is a policy gate, not a threshold. The spec already represents *absence* correctly —
empty list versus `None`, and `baba_status` defaulting to `unconfirmed` — but representation
alone does not stop a confident wrong value from being accepted without a human ever seeing it.

**Hard gates that bypass the score entirely and always route to review:**
value not found verbatim or near-verbatim in the parsed source · the two parsers disagree on the
source cell · any domain plausibility check fails · the source page was a low-quality scan ·
the field is null while a sibling in the same table row is populated.

**Banned: LLM self-reported confidence** (0.692 AUC — worse than raw logprobs and dangerously
plausible-looking). **Not built: self-consistency at N=5** (0.744 AUC at 5× cost, only 6 distinct
score values).

**Realistic accuracy to plan for** (extrapolated — see D-11):

| Field class | Expected exact match |
|---|---|
| Headline numerics from clean text-layer datasheet tables | 92–97% |
| Same from scanned/photographed datasheets | 80–90% |
| Conditional fields (temp coeffs with conditions, cert lists) | 70–85% |
| Contract atomic fields (parties, dates, amounts) | 85–95% |
| Contract fields needing clause interpretation (LDs, caps) | 60–80% |

**Do not plan for >97% unassisted on any class.**

---

## D-4 — Supplier and model identity resolution

**Decision:** four-stage matcher with per-manufacturer suffix rules and electrical corroboration.
**Confidence: high [V].**

### The five facts that force the design [V]

1. **One datasheet ≠ one product.** The Trina `TSM-NEG21C.20` PDF covers 6 bins; CEC has **22
   rows** for the family. Jinko's `JKM605-630N-66HL4M-BDV` sheet is titled only
   "66HL4M-BDV / 605-630 Watt" — **the per-bin model number appears nowhere on the sheet.**
2. **97.5% of CEC rows embed their own Pmax** in the model string.
3. **Families split across manufacturer entity strings.** Trina bins 635–725 W are under
   `Trina Solar Co.,Ltd`; bins 730/735/740 under `Trina Solar`. **Looking up
   (`Trina Solar`, `TSM-700NEG21C.20`) returns nothing.** Make this the matcher's regression test.
4. **157 model numbers appear under more than one manufacturer name.** CEC flags this via *blue
   cell formatting*, which any value-level parse discards. Recompute it.
5. **100% of CEC inverter rows carry a `{Vac}` suffix**; the same base model at different voltages
   can carry different kW.

### Stage 1 — Manufacturer normalisation

NFKD-fold, casefold, strip legal suffixes **token-wise**, collapse whitespace.

The `Co./Ltd` cluster has **20 distinct spellings** in CEC data, including one ending in
U+2002 EN SPACE. Measured: stripping legal suffixes only takes 408 names → 394 keys with **14
collisions, all true positives**. Adding descriptive tokens (solar/energy/power/technology) →
382 keys **with false merges**, and drives `POWER ELECTRONICS`, `Solar Power (SPI)` and
`Energy America, LLC` all to the **empty string**.

→ **Strip legal suffixes only. Never descriptive tokens. Assert non-empty keys.**

**Seed the alias table from CEC's `Notes` column** — it is a machine-readable alias map:
`Formerly listed under Hanwha Q CELLS` (627 rows), `…Canadian Solar Inc.` (316),
`…CSI Solar Co., Ltd.` (82, bidirectional), `Formerly Neo Solar Power Corp` (184). Parse it
rather than hand-authoring.

### Stage 2 — Model decomposition into `(family, bin, variant_tokens)`

Mask **only the token equal to nameplate Pmax (±1 W)** — not all 3–4 digit runs, which would
collide First Solar `FS-267` with `FS-367`.

### Stage 3 — Suffix handling: keyed on `(manufacturer, token)`, never globally

Measured across every base/suffixed pair within a manufacturer, comparing six electrical
parameters (counts = identical / different) [V]:

| Never strip | Safe | Manufacturer-dependent |
|---|---|---|
| `-TV` 0/83 · `-Q` 0/62 · `-R` 0/36 · `-P` 0/35 · `-BLK` 0/27 | `-I` 27/0 · ` XV` 27/0 · ` BLK` 22/0 · `-3BB` 13/0 | `-V` 72/189 · `-BB` 264/15 · `-BW` 412/9 |

> **`BLK` is electrically identical for REC (22/0) and always different for Maxeon (0/27).**
> A global suffix strip-list is provably wrong.

**Case/punctuation folding is for candidate retrieval only, never the final decision.** 108
within-manufacturer fold-collisions exist and **6 are genuinely different products** —
`SIL-380HC` vs `SIL-380HC+` differ at Isc 11.36 vs 10.28 and Voc 42.17 vs 45.35. `+` is
significant; `*` is a legitimate model character (wafer size), not a footnote marker.

### Stage 4 — Score and threshold

| Signal | Weight |
|---|---|
| Manufacturer key equal or alias-linked | 0.35 |
| Family key equal after bin masking | 0.30 |
| Bin equal (±1 W) | 0.15 |
| Variant tokens equal, or differing only by a `(mfr, token)`-safe token | 0.10 |
| Electrical corroboration: Pmax, Voc, Isc all within D-2 tolerance | 0.10 |

**≥0.90** same product (auto-merge) · **0.70–0.90** same family, different variant → surface as
*variant mismatch*, **not** a spec conflict · **<0.70** distinct, no comparison.

**Never auto-merge on manufacturer + model alone without electrical corroboration.** Identical
model strings under two entity names are usually the same product, but `ASB-M10-144-550` under
the two Adani entities has PTC 509.9 vs 518.2 — genuinely different.

### Stage 5 — Canonical ordering (required by AC-7)

Identity resolution must also yield a **total order** over component instances, or the workbook
cannot be byte-reproducible. "Sorted-key JSON" orders keys *within* an object and says nothing
about row order *across* instances.

```
(component_category, manufacturer_key, model_key, nameplate, surrogate_id, field_name)
surrogate_id = hash(normalised_manufacturer, normalised_model, nameplate)
```

`surrogate_id` is a **tie-break, not the primary key** — leading with a hash would make the
workbook's row order meaningless to a reader. It is required because
`(category, supplier, model)` is provably not unique on real data: 36 duplicated
`(Manufacturer, Model Number)` pairs and 157 model numbers appearing under more than one
manufacturer. A key without it sorts unstably exactly where the data is most ambiguous.

`nameplate` precedes it because one datasheet routinely covers several SKUs, so bin is part of
identity rather than an attribute of it.

### D-4a — Inverters and BESS follow different rules from modules ⚠️ [V]

The stage 1–4 algorithm above was derived from PV modules. Inverters break it in a specific way,
verified across six independent manufacturers:

> **The number in a utility inverter's model name is usually kVA at one specific AC voltage tap,
> on identical hardware.** Changing the AC voltage changes the model number without changing the
> box.

| Vendor | Same chassis, different AC voltage → different model |
|---|---|
| SMA | `SC 4000 UP-US` (600 V) / `4200` (630 V) / `4400` (660 V) / `4600` (690 V) — **all 3850 A** |
| GE Vernova | LV5+ `1560`/`1563`/`1566`/`1569` — **all 3263 A**; digits 3–4 are AC volts ÷ 10 |
| TMEIC | `PVU-L0800GR-2` / `L0840` / `L0880` — **all 702 A** |
| Sungrow | `SG3425UD-MV` (0.6 kV) / `SG3600UD-MV` (0.63 kV) |

**Consequence: power-number equality is not identity, and power-number inequality is not
difference.** The module-oriented "mask the bin token" heuristic actively misleads here.

**The power token is frequently not the rated power at all.** Huawei publishes its own decoder
table: `SUN2000-330KTL-H1` is rated **300 kW** and `330KTL-H2` is rated **275 kW** — same power
token, same chassis, different products. CPS `SCH275KTL` is selectable 250/275 kW. Power
Electronics `FS3510M` is kVA at 50 °C, not kW at 25 °C.

**Suffix semantics are vendor-scoped, and a generic rule is actively wrong:**

| Suffix | Sungrow | SMA |
|---|---|---|
| `-20` | **different DC front-end** (6 MPPT × 75 A vs 12 × 40 A) | hardware generation |
| `-US` | **real electrical change** — nominal PV 1080→1180 V, 50/60 Hz→60 Hz only, AC window 640–920→704–880 V | mostly certification package |

**The cleanest "same product, different SKU" case in the whole corpus is Enphase `-DOM-`**
(`IQ8PLUS-72-M-DOM-US`): electrically identical to the non-DOM part, differing only in
domestic-content origin. This is exactly the distinction the Tax Incentives tab depends on, so
the matcher must call it *same product* while the compliance fields stay different.

**Recommended identity key for inverters** — the model string alone is insufficient for every
vendor examined:

```
(manufacturer, family, dc_voltage_class, ac_nominal_voltage,
 ac_nominal_current, mppt_count, certification_set)
```

**BESS splits into three groups, and only one is parseable:**

- **Group A — real structured model strings.** Sungrow PowerTitan (`ST5015UX-4H-US`; the `-2H`
  and `-4H` variants are identical 5015 kWh cells differing only in PCS count), BYD, HiTHIUM, EVE,
  LG. Tesla has real part numbers but with literal wildcards (`1848844-XX-Y`) and the duration and
  voltage discriminators live **outside** the part number.
- **Group B — marketing names only, no published model number.** Fluence, Wärtsilä, CATL,
  Samsung SDI. These also have **zero CEC entries**, so there is no fallback identity authority
  for them (consistent with D-8's warning).
- **Group C — only the PCS is modelled.** For these, the PCS model string is often the sole
  reliable structured identifier in the document.

**Normalisation requirements this adds:** delete spaces *inside* tokens (`STP 50-US-41` ≡
`STP50-US-41`, both real CEC strings); treat `/` and `-` as equivalent separators; case-insensitive
throughout — Sungrow's own CEC filings mix `KWH`/`kWh` and `2H`/`2h` within one manufacturer;
strip decorative vendor prefixes (`CPS `); and strip CEC `{…}` braces but **retain the contents as
an attribute**, since they usually carry the AC voltage or duration the model string omits.

---

## D-5 — Text normalisation: the lexical traps

**Decision:** NFKD-normalise all extracted text before field matching; treat `,` as a decimal
separator in IEC/EU-sourced documents. **Confidence: high [V].**

Non-ASCII characters actually measured in real datasheets:

| Source | Characters present |
|---|---|
| Jinko datasheet | `±` `㎡`(U+33A1) `ﬁ`(U+FB01) `ﬃ` `ﬀ` `°` `·` `×` `φ` `（` |
| Sungrow datasheet | `–`(U+2013, **the range separator**) `℃`(U+2103, single char) `≥` `≤` `²` `：` |
| IEC 60076-1 | decimal **comma** (`±7,5 %`, `10,5 kV`) |

**Without ligature folding, `Efficiency`, `Coefficient` and `Specifications` never match your
field regexes** — they contain `ﬁ`, `ﬃ` and `ﬁ` respectively.

> ⚠️ **Highest-risk lexical trap in the whole spec: `10,5 kV` means 10.5 kV, not 105 kV.**
> A parser treating `,` as a thousands separator is off by 10× on every IEC-sourced document.

### The unit conversion that must NOT happen

**`%/°C ≡ %/K ≡ %/degC` are aliases requiring no conversion.** A temperature *coefficient* is
per-degree-*interval*, and 1 °C ≡ 1 K as an interval. **The trap is a generic unit library
applying the +273.15 offset, which silently destroys the value.** Hard-code these as aliases;
never route them through a temperature converter.

### The conversion that IS required [V]

SAM/pvlib store α and β in **absolute** units (A/K, V/K); CEC and datasheets use **relative**
%/°C. Verified numerically:
- `0.00486614 A/K ÷ 9.34 A = 0.0521 %/K` = CEC's `αIsc 5.21E-2` ✓
- `−0.12118231 V/K ÷ 38.63 V = −0.3137 %/K` = CEC's `βVoc −0.3137` ✓
- **`gamma_pmp` is already %/°C in both — do not divide it.**

---

## D-6 — Transformer multi-rating: IEEE and IEC order them oppositely

**Decision:** never collapse a multi-cooling rating to a scalar at extraction. Store every rating
with its cooling class **and which standard governs**. **Confidence: high [V].**

> **ANSI/IEEE** (C57.12.00 §5.4): several rated powers; impedance and load losses at the **base**
> (self-cooled, ONAN) rating — **base first**.
> **IEC** (60076-1 §4.1): the **top** kVA is *the* rated kVA; impedance and losses at **top**
> rating — **base last**. Rating-plate item (m) verbatim: *"ONAN/ONAF 70/100 %."*

So `2.5/3.125 MVA ONAN/ONAF` (IEEE) and `ONAN/ONAF 70/100 %` (IEC) order the ratings
**oppositely**. **"Take the first number" is right for IEEE and wrong for IEC.**

If a scalar is required downstream, use the **ONAN / self-cooled** rating and label it as such —
it is the only rating available under all cooling conditions and it is the IEEE impedance base.

**%Z is meaningless without its base.** IEC 60076-1 clause 6.5: impedance is expressed *"in
percentage terms z referred to the rated power and rated voltage."* %Z scales linearly with the
MVA base, so the same physical transformer quoted IEEE-style vs IEC-style differs by
**1.25×–1.67×** — dwarfing the ±7.5% tolerance. Always capture (base MVA, tapping).

**No-load loss is NOT temperature-corrected; load loss IS.** IEC clause 11.1 verbatim: *"The no
load losses shall not be corrected for any effect of temperature."* Two load-loss figures at
different reference temperatures are not comparable without conversion — the standard itself
flags this.

Reference temperatures, now **primary-verified [V]** (IEEE C57.12.00 clause 5.9 — load loss at
`20 °C + rated average winding rise`, no-load loss at `20 °C`; IEC 60076-1 clause 10.1 — `75 °C`
for oil-immersed regardless of rise):

| Rise class | IEEE load-loss ref | IEC |
|---|---|---|
| 55 °C | 75 °C | 75 °C |
| 65 °C | **85 °C** | 75 °C |
| 75 °C | 95 °C | 75 °C |
| 55/65 °C dual | **75 °C** (resolves to the lower rise, confirmed on four real submittals) | 75 °C |

The same physical transformer therefore reports a **higher** load loss on an IEEE sheet than an
IEC one. `load_loss_ref_temp_c` is a required field, defaulted from the rise class with a
`derived` flag when not stated.

### D-6a — Dyn1 vs Dyn11: a 60° trap that makes transformers un-parallelable ⚠️ [V]

Both primary texts were read, and they disagree by default:

- **IEEE C57.12.00 clause 5.7.2:** for Y-Δ and Δ-Y, angular displacement is 30° **with the low
  voltage lagging** — which is clock hour **1**, i.e. **`Dyn1`**.
- **IEC 60076-1 clause 6**, its own worked example: 20 kV delta HV, 400 V star LV, LV lags by
  330° → symbol **`Dyn11`**.

> **An ANSI "Delta-Wye, standard 30° displacement" transformer is `Dyn1`, not `Dyn11`.**
> A `Dyn1` and a `Dyn11` of identical ratings are **60° apart and cannot be paralleled.**

Confirmed in the field: ANSI submittals declare `Dyn1`; an IEC/Indian inverter-duty spec declares
`Dyn11yn11`. A comparison tool that treats these as equivalent would recommend a supplier whose
transformer physically cannot be connected alongside the others.

### D-6b — Cooling-class legacy codes are ambiguous [V]

IEEE C57.12.00 Annex A Table A.1 maps old to new: `OA`→`ONAN`, `FA`→`ONAF`, `OA/FA/FA`→
`ONAN/ONAF/ONAF`, `FOA`→`OFAF` **or** `ODAF`. The old code **cannot distinguish forced (F) from
forced-and-directed (D)** flow. Flag the ambiguity; never silently canonicalise `FOA`.

### D-6c — Temperature rise is a second, independent rating axis, and its ordering is not stable [V]

Real strings for the same product family:

- `10/11.2/12.5/14 MVA … ONAN/ONAF, 55/65°C` — rise varies fastest
- `10/12.5/11.2/14.0 MVA … OA/FA, 55/65°C` — **cooling stage varies fastest**

Never assume ordering. Disambiguate by ratio: `r[1]/r[0] ≈ 1.12` means rise-fastest (the 65 °C
rating is 1.12× the 55 °C rating, verified by exact arithmetic on three independent nameplates);
`≈ 1.33` means stage-fastest. Also: stage count ≠ number count — `15000 KVA … OA/FA/FA/FA` gives
one number and four stages.

### D-6d — "Meets DOE 2016" is marketing boilerplate on utility-scale units [V]

10 CFR 431.192 scopes distribution transformers at ≤34.5 kV in, **≤600 V out**, 60 Hz,
10–2500 kVA, excluding autotransformers and special-impedance units. A utility-scale collector
step-up almost always falls **outside** — LV is 630/690/800 V or MV, or the rating exceeds
2500 kVA. Yet real datasheets still print `Meets/Exceeds DOE 2016 Efficiency Ratings`. Evaluate
the scope gate before treating such a string as a parseable guarantee.

**IEEE vs IEC tolerances are not interchangeable:**

| Parameter | IEEE §9 | IEC §10 T1 |
|---|---|---|
| Total loss | **+6%** | **+10%** |
| Impedance breakpoint | **2.5%** | **10%** |
| Ratio | ±0.5% flat | lesser of ±0.5% or ±(Z%/10) — **tighter whenever Z < 5%** |

---

## D-7 — BESS: no standardised tolerance exists. Say so explicitly.

**Decision:** classify BESS energy and RTE comparisons as *"requires boundary normalisation — no
standard tolerance exists"* and route to the contractual guarantee. **Confidence: high [V].**

EPRI ESIC Energy Storage Test Manual §2.4, verbatim: *"Aside for measurement inaccuracy, it is
recommended that there be **no test tolerance** applied to the results."* IEC 62933-2-1 defines
declarable parameters and test methods but **contains no tolerances clause**. UL 9540/9540A are
safety only.

**Round-trip efficiency has four distinct boundaries, all called "round-trip efficiency":**

| Boundary | Value | Vendor |
|---|---|---|
| DC-DC at container terminals | 95% | CATL EnerC+ |
| DC round trip | 93/94/95% (2h/3h/4h) | Powin |
| AC-AC at 480 V, incl. thermal | 91.7% (2h) / 93.7% (4h) | Tesla MP2XL |
| AC-AC at medium voltage, incl. aux | 91% | Tesla Megablock |
| **No boundary stated at all** | `>87%` | Fluence |

> **"CATL 95% beats Tesla 93.7%" is meaningless** — DC-DC versus AC-AC-including-auxiliaries.
> Bridging costs ≈2–4 pp (PCS) + 1–2 pp (aux) + ≈1 pp (MV transformer).

RTE is also **duration-dependent** at a fixed boundary. Two RTE numbers are incomparable unless
six things match: location, auxiliary treatment, power level, SOC window, temperature, and
BOL-vs-year-N.

**The BOL/EOL spread is 26%, verified from a CPUC decision:** the same SDG&E projects are listed
at `Beginning-of-Life 10 MW / 50.5 MWh` and `End-of-Life 10 MW / 40 MWh`.

**Parser heuristic:** within one vendor's frame `Energy ≈ Power × Duration` holds exactly
(Tesla 979 × 4 = 3916; CATL 2036.73 × 2 = 4073.47). **If stated energy ≫ power × duration, you
are comparing a DC nameplate against an AC power rating.**

Also required: **multiplicative strings must be evaluated** — `210 kVA * 12`, `2×1253kW`,
`2500x2`. Parsing `210 kVA * 12` as `210` understates by 12×.

---

## D-8 — CEC data: authority for PV and inverters, NOT for utility-scale BESS

**Decision:** weekly pull of four CEC XLSX exports as identity authority and value cross-check;
build a surrogate ID. **Confidence: high [V].**

```
https://solarequipment.energy.ca.gov/Home/DownloadtoExcel?filename=PVModuleList    21,989 rows
https://solarequipment.energy.ca.gov/Home/DownloadtoExcel?filename=InvertersList    2,104 rows
https://solarequipment.energy.ca.gov/Home/DownloadtoExcel?filename=EnergyStorage    6,585 rows
https://solarequipment.energy.ca.gov/Home/DownloadtoExcel?filename=BatteryList        965 rows
```

No API, no auth, no CSV. **`/Home/InverterSolarList` 404s** — the working path is
`/Home/InvertersList`. Updated ~3×/month; each file self-stamps *"Data has not changed since
…"* — use that cell as the version key.

**Parsing gotchas [V]:** header at row **17** (PV), **15–16** merged (inverters), **16–17**
(ESS), **11** (battery); the row below the header carries units; dates arrive as Excel serials
in some columns and text in others; embedded newlines and U+2002/U+00A0 in both manufacturer and
model fields.

**No stable ID column exists, and `(Manufacturer, Model Number)` is not unique** — 36 duplicated
pairs. Build a surrogate `hash(normalised_mfr, normalised_model, nameplate)`.

> ⚠️ **CEC is not an authority for utility-scale BESS.** Fluence, HiTHIUM, Samsung SDI, Wärtsilä,
> Powin, Envision and Tesla Megapack are **all absent**. Median ESS duration in the list is
> 2.56 h — it is a behind-the-meter list. Tesla's entries are part numbers with literal wildcards
> (`1707000-XX-Y`).

### D-8a — Do not use pvlib's bundled CEC data ⚠️

`pvlib` v0.15.2 is current, but `sam-library-cec-modules-2019-03-05.csv` is **frozen at March
2019**. The decisive measurement [V]:

| | pvlib bundled | live SAM |
|---|---|---|
| Modules ≥600 W | **0** | 1,461 |
| Max nameplate | 510 W | 755 W |

**For a 2026 utility-scale project where modules are 600–740 W, `retrieve_sam('CECMod')` returns
a library containing not one candidate product.** pvlib's normaliser is also currently broken —
its `BAD_CHARS` covers `[` `]` but not `{` `}`, and SAM switched to curly braces, so 0 of 2,343
inverter names are valid identifiers.

→ Pull the **live SAM CSVs** from the NREL/SAM repo for single-diode coefficients; if pvlib is
used at all, pass `path=` pointing at a pinned local copy. Never rely on `retrieve_sam()`
defaults.

---

## D-9 — Component count: eight categories

**Decision:** eight. The FRD's comparison table merges cabling and combiner boxes into seven
rows; the FRD's own tab list and the TRS both specify eight. Following the TRS, which enumerates
all thirteen tabs explicitly. **Confidence: high.** Worth confirming with the product owner since
it changes the workbook shape.

---

## D-10 — Reviewer edits are destroyed by regeneration ⚠️ WORKFLOW DECISION

**Decision:** the Conflicts tab is **read-only except for three columns**, protected via
`ws.protection`, and edits there do **not** round-trip. Resolution happens in the application,
not in Excel. **Confidence: medium — this is a product decision, flagged for the product owner.**

The workbook is deterministically regenerated from the canonical store (FR-OUT-06). Therefore
**anything a reviewer types into the spreadsheet is silently destroyed on the next
generation.** This is a workflow gap, not a code bug, and it must be decided before
implementation rather than discovered after the first lost review session.

Three options, in order of preference:

1. **Resolve in the application only** (recommended). Excel is read-only output. Simplest, and
   preserves determinism absolutely.
2. **Round-trip three columns** (Status, Owner, Resolution note) by re-importing the workbook.
   Requires stable row identity and an import path; weakens determinism.
3. **Accept the loss** and document it loudly. Not recommended — reviewers will lose work.

Under option 1, put the three human-relevant columns adjacent with an unlocked style anyway, so
a reviewer can annotate a working copy without believing it will persist.

---

## D-11 — There is no benchmark for this task. Build the gold set first.

**Decision:** building a 30–50 document labelled gold set is **task one of week one**, ahead of
optimisation work. **Confidence: high.**

**No public benchmark exists for PV/inverter/BESS datasheet extraction.** Every accuracy figure
in D-3 is extrapolated from invoice and general-document benchmarks. Stating this plainly in the
spec is more useful than a confident number would be.

Seed the gold set deliberately with hard documents — poor scans, unusual layouts. Negative-sample
quality dominates dataset size for the confidence model.

> Note: **Trina datasheets are image-only PDFs with no text layer** [V]. Any production extractor
> needs OCR fallback from day one — this is not an edge case, it is a tier-1 supplier.

---

## D-12 — Remaining decisions with no research dependency

| # | Question | Default | Confidence |
|---|---|---|---|
| D-12a | Identity/auth model for `resolved_by` | Store the **OIDC subject claim**, not an email. Emails change; the audit log is immutable, so an email recorded today may not identify anyone in five years — and NFR-02 forbids rewriting it to fix that. Display names resolve at read time. | Medium |
| D-12b | Gate granularity | **Per-document-per-field.** Per-batch would give one review session but loses the ability to ship a partial workbook. | Medium |
| D-12c | Conflict expiry | **Conflicts never expire.** Expiry would silently discard a known data-quality problem. They age, and age is a reported metric. | High |
| D-12d | `request_more_web_search` looping | Reject at `reopen_count >= 3` and force a terminal decision. It is the only action that can cycle. | High |
| D-12e | Claim lease duration | 15 minutes, swept back to `pending` on expiry. | Medium |
| D-12f | BABA applicability | `unconfirmed` until project funding status is established — never `not_applicable`, which would silently assert a funding fact. | High |

---

## D-13 — Audit canonicalisation and the hash preimage (contract C4)

> **Status: ADOPTED 2026-08-07** by the lead architect, as recommended. Drafted 2026-08-06 to
> close C4's decision half. Like every decision in this file it can still be overruled, but WP-H
> should now be written against it rather than waiting on it.
>
> **The deadline it carried is now discharged in one direction only:** §3's version marker must
> exist before the first event is ever emitted. Nothing has been emitted yet, so the window is
> still open — it closes the moment WP-H writes its first row.
>
> It adopts the scheme `sql/07_audit_event.sql` already names (RFC 8785), **changes** its
> `sha256(prev_hash || canonical_payload || ...)` sketch (§2), and adds four pins the DDL leaves
> open: digest, version marker, who supplies `recorded_at`, taxonomy. On ratification, update
> `sql/07`'s caller-sequence comment and `sql/README.md` decisions 5–7, which will otherwise keep
> reading as unsettled.

**Scheme: RFC 8785 (JCS), via the `rfc8785` PyPI package** — adopting the scheme `sql/07` already
names, with a concrete implementation. [V] for the package metadata only — read from the PyPI
JSON API on 2026-08-06: version 0.1.4, Apache-2.0 (so it clears the dependency licence gate),
**zero runtime dependencies** (everything in `requires_dist` is an extra).

**Installed, locked and conformance-tested as of 2026-08-12** — `rfc8785==0.1.4` is pinned exactly
in `pyproject.toml` (exactly, not `~=`: this library decides the bytes every chain is hashed over,
so an output change would re-base all history while the data stands still, which is the A-6 class).
`tests/test_audit_canonicalisation.py` runs it against RFC 8785's own published vectors - section
3.2.4's hex byte dump, section 3.2.3's UTF-16 sorting vector, and all 26 rows of Appendix B
Table 1 including the two that must raise. That pairing was this decision's own condition for
ratification, because the whole argument for using a library rather than hand-rolling is that its
conformance is somebody else's problem *only once you have checked it*.

**Do not hand-roll this with `json.dumps(sort_keys=True)`.** [V] — the two disagree in at least
two ways that matter, both verified in this repo's own venv: JCS sorts keys by **UTF-16 code
units** where Python sorts by code point, and JCS serialises numbers by ECMAScript rules
(shortest round-trip, so `10.0` → `10`) where Python emits `float.__repr__` (`10.0` → `10.0`).
A hand-rolled near-JCS produces chains that verify under the local implementation and fail under
any conformant one — the worst available outcome, because it is silent until someone else audits.

1. **Digest: SHA-256**, frozen by name. The two `octet_length = 32` CHECKs in `sql/07` already
   assume it; this states it rather than leaving it inferred from a column width.
2. **Preimage: one JCS object, never a concatenation.** ⚠️ **This changes `sql/07`'s sketch.**
   `hash = SHA-256(JCS({"v": 1, "stream", "seq", "event_type", "actor", "recorded_at",
   "prev_hash": lowercase-hex or null, "payload": {…}}))`.

   The sketched `sha256(prev_hash || canonical_payload || ...)` has two problems. The trailing
   `...` leaves the field set unenumerated, so two implementations can disagree about what is
   covered while both believing they follow the comment. And concatenation without a delimiter
   is ambiguous by construction: distinct field values can produce identical bytes, which is the
   classic length-extension-adjacent framing bug. Wrapping the whole envelope in one canonical
   object removes both — JCS gives unambiguous framing for free, and the object's keys *are* the
   enumeration. `payload_canonical` stores JCS of the payload alone; a verifier recomputes the
   envelope object around it.

   **`payload` is embedded as the parsed JSON object, not as the `payload_canonical` string.**
   Both are "obvious" readings and they hash differently — one nests an object, the other nests
   a quoted string.
3. **`"v": 1` is inside the preimage, and this is the load-bearing part.** Without a version
   marker, changing the hashed field set later invalidates **every existing chain**, because a
   verifier can no longer recompute historical hashes — [tasks.md](tasks.md) already warns that
   changing the hashed field set "invalidates every existing chain". With the marker, evolution
   is additive: the verifier dispatches per event version, and chains still link across the
   boundary because `prev_hash` is only bytes.
4. **The caller supplies `recorded_at`**, formatted RFC 3339 UTC with the `Z` offset and fixed
   microsecond precision (`2026-08-06T15:04:05.000000Z`). RFC 3339 permits both `Z` and
   `+00:00`, and `datetime.isoformat()` emits the latter — pin one or two conformant callers
   produce different hashes for the same instant. A hashed timestamp is tamper-evident; a
   defaulted one cannot be pre-computed by the caller, and a superuser could edit it without
   breaking the chain. **Drop the `DEFAULT clock_timestamp()` on ratification** rather than
   leaving it unused: a forgotten caller should fail on `NOT NULL` at insert, not silently
   record an unhashable timestamp that surfaces at first chain verification.
5. **Taxonomy: the seven values are v1, and additions are additive-only** via an amendment to
   this decision — not an absolute freeze. The DDL chose a CHECK over a native enum precisely so
   values could be added, this table has never been reviewed against a full event inventory, and
   an absolute freeze would be violated the day a `workbook_composed` event is needed. Removing
   or renaming a value is what the chain cannot tolerate, and that stays forbidden.

   Two NFR-02 events have no document-scoped home and are registered as deviations in
   [analysis.md](analysis.md) rather than by widening this constraint: gap-triggered web searches
   (A-49) and the compose-gate `--accept-incomplete` override. **Do not widen `audit.event`'s
   stream CHECK** — it was made structural deliberately. Where those events should live is the
   maintainer's call, below.

**Confidence: High** on the scheme and preimage; **Medium** on the taxonomy, which is the DDL's
own proposal and has never been reviewed against a full event inventory.

**On the two canonicalisation schemes** in one codebase — JCS here, repr-JSON in D-14 — see
D-14's *Why not JCS here*, which owns that boundary. Restate it in WP-H's module docstring, not
in this document.

**Cost of getting it wrong.** C4 gates every stage's side effects, and a wrong preimage is the
worst kind of wrong: chains that verify today under the buggy implementation and fail under any
correct one, converting the audit log's only superuser-surviving property into noise.

**Where the run-scoped events live — ADOPTED 2026-08-07.**
NFR-02's judged-by criterion is "log entries cannot be altered or deleted after write", so an
*unchained* append-only table with the same NOLOGIN-owner grants and TRUNCATE tripwires already
satisfies it — plan Decision 9's own attack matrix shows privilege separation is the enforcing
mechanism and the chain adds tamper-*evidence* beyond the requirement's letter.

**Chain it anyway**, as `audit.run_event` with stream `run:<run_id>`, reusing WP-H's envelope and
lock discipline verbatim. The marginal cost is near zero once that library exists, and the
`--accept-incomplete` override is the highest-repudiation-risk record in the system: the name of
the human who shipped a workbook past unresolved conflicts. Unchained, it would be the only human
decision lacking the tamper-evidence every resolution gets — and FR-HITL-06, not NFR-02, is the
binding requirement for it.

Rejected: folding run events into `audit.event` under a synthetic stream. That spends the
structural stream CHECK and the document FK — the DDL's two strongest guarantees — to avoid one
`CREATE TABLE`.

**Note on wording, and it changes the question.** `spec.md:153` says "**web** queries,
extractions, conflicts and resolutions"; `plan.md:66` paraphrases it as "every extraction,
**query**, conflict and resolution", dropping *web*, and `sql/README.md` inherited the plan's
reading. Cross-document *retrieval* queries are not web queries and are plausibly not NFR-02
events at all under the normative text. `spec.md` governs. See A-49.

---

## D-14 — The canonical workbook projection (contract C6)

> **Status: ADOPTED 2026-08-07** by the lead architect, as recommended, including both calls in
> §Two decisions below. Drafted 2026-08-06 to close T0.5. C6 was the only contract at zero at that
> point - `write_workbook()` raised and no *workbook* projection function existed - and it blocked
> WP-G entirely. The projection and T0.5 landed 2026-08-12; `write_workbook()` and the gating G.6
> desktop-Excel test remain. (`services.claims.project` is a
> different projection: claims to canonical fields, contract C8. C6 is the projection of the
> whole store to the hashed artifact.)
>
> **Amended 2026-09-03 by D-29:**
> the `policy` object gains `thresholds`, the per-field τ table embedded by value. A reader of the
> shape below alone would omit it and hash differently — the same "table alone" trap Track 1a
> recorded. One structural re-baseline of the golden fixture follows; field rows are unchanged.

**Bytes:** UTF-8 output of
`json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)`.

This **is** the "sorted-key JSON, floats via `repr()`" already frozen in tasks.md and plan
Decision 8c — Python's JSON encoder uses `float.__repr__` — so it needs no new serialisation
code. [V] — verified in this repo's venv:

| Check | Result |
|---|---|
| `'%.16g'` collides `0.1+0.2` with `0.3` | **yes** — both print `0.3`; this is plan 8c's own motivating case |
| `repr` distinguishes them | yes — `0.30000000000000004` vs `0.3` |
| `json.dumps` uses `float.__repr__` | yes |
| values round-trip exactly | yes |
| `allow_nan=False` rejects NaN | yes, raises `ValueError` — a stray NaN is loud, not silently `NaN` |

**Why not JCS here**, when [D-13](#d-13) mandates it for audit: ECMAScript number rules collapse
`650.0` → `650`, erasing the int/float distinction the store's `value: object` genuinely carries.
repr-JSON keeps it. The two contracts want different things — cross-language verifiability there,
lossless Python round-trip here.

**Shape.** Top level
`{projection_version: 1, policy: {policy_version, confidence_threshold, thresholds}, components: [...], conflicts: [...], sources: [...]}`.
`thresholds` is the per-field τ map embedded **by value** (D-29). Arrays wherever order is meaning: components by `ComponentInstance.ordering_key()` (D-4 stage 5),
fields by name, then:

- **Nothing that decides hashed array order may contain `repr()` of an enum.** This is one rule,
  and it governs both bullets below. `repr(MeasurementBasis.STC)` is `<MeasurementBasis.STC:
  'stc'>` — CPython's enum repr, an implementation detail the stdlib reworked as recently as
  3.11. Reaching the bytes, a routine Python upgrade re-baselines every golden hash with zero
  data change. `repr()` stays fine as an in-memory sort key; the projection must encode instead.
- **Candidates sort by the field sequence `conflict_hitl._ordering_key` uses, with every
  component routed through `encode_value()`** — not by `_ordering_key` itself, and never by
  arrival. Arrival order is forbidden by that function's own docstring: FR-OUT-06 "makes
  composition a pure function of the store: any list the queue payload is built from has to be
  arranged by what a candidate *is*, never by when it arrived." But `_ordering_key`'s **first
  component is `repr(candidate.condition.grouping_key())`**, so prescribing it verbatim would
  reintroduce the exact hazard the rule above closes. See [A-50](analysis.md).
- **Condition groups sort by their `encode_value()` form**, for the same reason.

**One frozen `encode_value()`** for `value: object`, **closed-world** — it raises on any type not
listed here rather than falling back, so a new value type is a loud decision instead of a silent
encoding:

| Type | Encoding |
|---|---|
| `Decimal` | `{"$decimal": str(v)}` — **added 2026-08-11** |
| `date` | `{"$date": v.isoformat()}` — **added 2026-08-11** |
| `datetime` | `{"$datetime": …}`, RFC 3339 UTC, microseconds **always** printed (`isoformat()` omits `.000000` when zero, so pin a formatter). Aware only — **amended 2026-08-12** |
| `DeclaredBand` | `model_dump`, then **every leaf back through `encode_value`** — **amended 2026-08-12** |
| enums | `.value` |
| `frozenset` | sorted, as `derived` already is |
| `tuple` | list — needed for condition grouping keys on the sort path, never for a stored value |
| `list` | list, elementwise — **added 2026-08-12** |
| `str`, `int`, `float`, `bool`, `None` | bare (finite floats only) |

**Three amendments, all found by implementing this table in Track 1a and all required by the
property below rather than by preference.** Recorded here because the code now differs from what
this table said, and a table that lies is worse than one that is silent:

1. **`list` was absent, and `list[str]` is the declared type of 18 contract rows** — so a
   closed-world encoder raised on real data. Encoded elementwise; order is content, never sorted.
   It shares the JSON array with `tuple` and `frozenset`, which is sound only because neither of
   those ever reaches the polymorphic `CanonicalField.value` slot: `derived` is a frozenset at a
   fixed key, and tuples exist solely on the sort path. **Injectivity is required over the
   polymorphic value domain**, which is the domain that needs it — `value` is typed
   `object | None`, so one key path carries a `Decimal` for one field and a `str` for another and
   position cannot disambiguate. That is the whole reason the tagged types are tagged. Adding
   `$tuple`/`$frozenset` sigils would buy nothing and put sigils into sort keys.
2. **`model_dump` alone leaks raw enum members.** Plain `model_dump()` runs in *python mode* and
   returns `kind` as the `ToleranceKind` member, which is not JSON and is one `repr()` away from
   `<ToleranceKind.ABSOLUTE: 'absolute'>` — the A-6 class, where a hash moves because a member was
   renamed. `mode="json"` fixes that one case and creates a worse one: a `Decimal` field added to
   the model later would be serialised by pydantic's rules instead of earning its `$decimal` tag,
   so two distinct precisions would collide. Recursing keeps one encoding authority per leaf.

   ⚠️ **This defect is invisible under equality assertions.** A `StrEnum` member equals its own
   value and `json.dumps` writes it as a plain string, so the leak passes every `==` test and
   surfaces only when a non-`str`/`int` field is added. It is caught by a structural check that
   every leaf is *exactly* a JSON type — `type(x) is str`, not `isinstance`.
3. **`datetime` pinned a format but no tag**, so an encoded datetime would collide with the equal
   plain string — precisely the argument that earned `date` its tag one row above. Tagged
   `$datetime`. Naive datetimes are **refused**: a naive datetime names no instant, and assuming
   UTC would encode it identically to an aware noon-UTC that it is *not equal to*, breaking
   injectivity in the silent direction. Aware datetimes are converted to UTC before formatting,
   which is what makes `14:00+02:00` and `12:00Z` — one value, two spellings — encode once.

Non-finite floats are refused for the same reason: JSON cannot represent them, and `NaN != NaN`
means no injective map can place a value that is not equal to itself. The schema already rejects
these at construction (`_reject_non_finite`); the encoder declines to be the hole in that.

Two Python equalities are deliberately **not** honoured, both warts rather than semantics:
`True == 1` and `1 == 1.0` encode distinctly, which this decision already implied by calling
`22`, `22.0`, `"22"`, `true` and `null` "five different tokens" below. `Severity.INFORMATIONAL == 0`
*is* honoured, because an `IntEnum` member is the integer. Over-separating a coincidence is safe;
under-separating a precision is not.

Implemented at `src/procurement_agent/schema/encoding.py`, with the property tests at
`tests/test_encoding.py`. Placement follows that module's own rule — `schema` sits below
`services` and cannot import it, and both consumers live in `services`.

**The requirement is a property, not the table: `encode_value()` must be injective over the
value domain, enforced by test.** The table is one implementation of it. Two consequences that
are easy to get backwards:

- **Equal values must encode identically.** Every enum in `schema/enums.py` is a `StrEnum`
  (`Severity` is an `IntEnum`), so `MeasurementBasis.STC == "stc"` is `True` — one value, not
  two. Tagging enums would make a single value encode two ways and *break* injectivity rather
  than protect it. Bare `.value` is correct.
- **Distinct values must encode distinctly**, which is why `Decimal` and `date` need tags and
  nothing else does. Bare JSON primitives already distinguish themselves in *text* — `22`,
  `22.0`, `"22"`, `true`, `null` are five different tokens — but `Decimal("22")` and the string
  `"22"` both want to become `"22"`, and `date(2026,8,11)` collides with `"2026-08-11"` the same
  way. `DeclaredBand` encodes to a dict and cannot collide with a scalar.

**Why `Decimal` earns a tag at all.** `Decimal("22")` and `Decimal("22.0")` are `==` in Python
and hash identically, but `conflict_hitl._decimals` reads precision from `str(value)`, and that
precision sets D-2's rounding floor:

```
Decimal("22")   vs 22.4  ->  no conflict   (0 places -> floor 0.5)
Decimal("22.0") vs 22.4  ->  CONFLICT      (1 place  -> floor 0.05)
```

The trailing zero decides whether a human is asked to review, so collapsing the two is a
behaviour change, not a formatting one. ⚠️ **Never call `Decimal.normalize()`** — it strips
trailing zeros and destroys exactly the precision the tag exists to carry.

**Why `$` as the sigil.** `list[str]` is a real contract type on 18 fields, so a positional
`["decimal", …]` tag would live inside a legitimate value domain; bare dicts are not a value type
at all. And `$` cannot collide with a `model_dump` key by construction: pydantic field names are
Python identifiers, so only a deliberate alias could mint one. Assert no dumped key begins with
`$` if a backstop is wanted.

**Two judgement calls, both decided 2026-08-07 as recommended:**

1. **Policy version and the computed `CellFlag`s both go inside the projection.** The workbook is
   a function of *(store, policy)*; hashing only the store certifies AC-7 while the artifact
   silently varies with configuration — the false-integrity claim C6 exists to prevent. Hash the
   *flags*, not merely the τ version: `flags_for`'s code is policy too, and a change to it would
   otherwise alter the rendered workbook under an unchanged hash.

   This follows established practice rather than inventing one. Bazel's action key covers the
   command line and whitelisted environment; Nix hashes all build inputs, so a config change
   yields a new output path rather than "invalidating" the old one; SLSA v1 records the artifact
   digest as `subject` and the configuration separately as `externalParameters`. The
   counter-argument — that re-tuning τ should not invalidate historical hashes — is a category
   error: each hash certifies the artifact that carried it. What re-tuning breaks is using the
   projection hash as a cross-policy *store* identity, which is a job for the separately recorded
   inputs, not for this hash.

   **Two consequences that must land with it.** Hashing policy means the B.10 τ table is
   carried **by value inside `policy.thresholds`** (D-29) — historical bytes include the τ that
   produced them, so a later retune cannot share a hash. Golden fixtures must pin their own τ
   map so production re-tuning never re-baselines them; `tasks.md` sequences τ tuning after WP-B,
   which is exactly when fixture churn would otherwise be worst.
2. **`generated_on` must be store-derived, not wall clock.** FR-OUT-06 demands the stamp; AC-7 and
   G.5's `sleep(1.1)` re-run demand byte-identity; a store-derived stamp satisfies both with no
   normative edit. The store-only wording lives on `write_workbook` (the docstring that says no
   timestamps derived from anything but the store). See [A-48](analysis.md).

   **Recommended derivation: the maximum store write-timestamp over the rows the projection
   actually reflects** — `max(document.ingested_at, claim.extracted_at, conflict.detected_at,
   resolution.resolved_at)`. All four columns exist today (`sql/02:32`, `04:65`, `05:37`,
   `06:19`). Computed as a fold over timestamps *already inside the projection*, which makes
   AC-7-safety structural rather than a rule someone must remember. Render it as "data as of".

   The two named alternatives both fail a case this one survives:

   | | `max(ingested_at)` | latest audit `seq` | **reflected rows** |
   |---|---|---|---|
   | no-op re-ingest (NFR-05) | ✓ | fragile | ✓ |
   | **a conflict is resolved** | **✗ does not move** | ✓ | ✓ |
   | two workbooks, different scopes, same day | ✓ if scoped | ✗ identical stamps | ✓ |

   A human resolution changes the workbook's content — FR-HITL-04 persists it into field
   provenance — so `max(ingested_at)` would date the artifact by an ingest that is no longer its
   newest fact. The audit tip is worse: it is **self-invalidating**, because plan Decision 2
   requires the `--accept-incomplete` override to be "recorded, audited", so composing writes an
   event, so the stamp changes on every override-bearing generation — breaking AC-7 in precisely
   the scenario the override exists for. `seq` is also per-stream and therefore globally
   ill-defined.

   **Two costs, stated so nobody "fixes" them later.** The stamp moves *backwards* when scope
   shrinks — acceptable, because its job is vintage and the projection hash is the change
   detector. And reclassification (`UPDATE access_restricted`) has no store timestamp at all, so
   no derivation captures it; that is a known limit, not a defect in this choice.

   **Zero-document sentinel — decided:** an empty store has no maximum, so `generated_on`
   renders as an explicit null, which the workbook shows as *no sources*. Never a placeholder
   date. An epoch-like value would be indistinguishable from a real vintage to a reader, and the
   whole point of the field is that a reader can trust what it says.

**Two hashes stored**, per plan 8c: `sha256(projection)` is the artifact of record;
`sha256(normalized xlsx)` is a renderer-regression check only, never the integrity claim.

**Golden fixture (T0.5):** one committed projection plus its hash for a synthetic two-supplier PV
store containing D-1's Sungrow trio, so the fixture exercises list-valued fields rather than the
easy one-value-per-key case. Landed 2026-08-12 as
`tests/fixtures/workbooks/two-supplier-pv-store.json` and
`two-supplier-pv-store.canonical-bytes.sha256`. Story 6 re-baselines it once when `thresholds`
is added (D-29).

**Confidence: High** on the byte format; **Medium** on the shape; the two items above are
explicitly the maintainer's call.

**Strongest objection.** A Python-repr format is unverifiable from any other language, which is
the problem JCS was standardised to solve. Counter: the projection's only consumers are this
repo's renderer and its CI, injectivity on float64 is the property that actually matters and it
holds, and `projection_version` exists precisely so a second-language consumer can force the
question later.

**Cost of getting it wrong.** Lowest of the five unfinished contracts *if* wrong in shape —
projections are regenerable, so a format change re-baselines golden hashes rather than losing
data. The expensive mistake is decision 1 above: leave policy outside the hash and the artifact
procurement decisions are cited from carries a false integrity claim.

---

## D-15 — The confidentiality label model (contract C7, task T0.4) ⚠️ PROVISIONAL

> **Status: ADOPTED PROVISIONALLY 2026-08-07.** The model below is ratified and is what the
> schema already enforces. It is marked provisional because **two facts, not two preferences,
> are outstanding** — see *What would overturn this*. A decision-maker cannot settle them by
> choosing; somebody has to read the NDAs and check the evaluation roster.

**Adopted: one document-level label, two values**, stored as the existing `access_restricted`
boolean, with a per-principal clearance resolved from the OIDC subject (D-12a) and applied as
`SET LOCAL app.allow_restricted` per transaction. Labelling happens at ingest (task A.10),
derived from FR-ING-06's classification: contract/TOS, purchase order, pricing, terms and
warranty are restricted; spec sheets, technical documentation and environmental regulation are
general. **Classification below its confidence threshold labels restricted** — the failure
direction has to be closed, not open.

`allowed_document_ids` on the retrieval port is **scoping within** an entitlement, never the
boundary. RLS is the boundary. AC-8's test is the RLS path, never the allowlist alone.

**Why one boolean and not per-supplier groups.** Systematic evaluator separation by supplier is
not standard practice in utility-scale equipment procurement, and it cannot be, because
side-by-side comparison is the deliverable — FR-OUT-01 puts eight suppliers on one tab. The
separations that *are* standard run along axes this model already covers:

| Axis | Practice | Covered? |
|---|---|---|
| Document type | technical scored without sight of pricing — the two-envelope convention | yes, via the classification map above |
| Time | pricing sealed until technical scoring closes | yes, a policy on the same label |
| Person | conflict-of-interest recusal from one named bidder | **no** |

ERCOT is the permissive regulatory case: Texas restructured in 1999, so a private merchant buyer
faces no commission-mandated process and no independent-evaluator requirement. The binding
constraints here are contractual — NDAs and trade-secret exposure — not statutory.

**What would overturn this, and it is two questions of fact:**

1. Do any executed supplier NDAs go beyond "Representatives with a need to know" — naming
   individuals, requiring access logs, or requiring segregation from personnel who work with
   competing suppliers? If any single one does, this model is insufficient as a compliance
   mechanism.
2. Will anyone on the evaluation hold a conflict with a specific bidder — an external
   consultant, the owner's engineer, a prior relationship — such that they must be walled off
   from *one* supplier rather than from all pricing?

**The two answers do not lead to the same place**, and an earlier summary of this decision
wrongly collapsed them into "either yes → `restricted_group`":

| Answers | Adopt |
|---|---|
| Both no | The boolean, as built. Restrict by document type; that is standard practice. |
| **1 yes** (an NDA exceeds "need to know") | `restricted_group text NULL` (NULL = general); the boolean becomes the degenerate single-group case. |
| **2 only** (recusal, no NDA trigger) | **A per-person deny-list, keeping the boolean.** Question 2 asks who may *not* see one supplier — that is an exclusion, not a clearance matrix, and it is much cheaper than groups. |

**Both are document checks, not opinions.** Question 1 means reading each executed NDA for three
concrete triggers — named individuals, access-log requirements, segregation from personnel who
work with competing suppliers. Question 2 means reading the evaluation roster, external
consultants and the owner's engineer included.

**Record the answer as an artifact** — which NDAs were read, and the roster as of a date. The
model hardens at first ingest, but new NDAs and new evaluators arrive afterwards, so the question
re-arms with each one rather than being settled once.

**Cost of the retrofit, stated honestly because it has been mis-quoted in both directions.**
`access_restricted` appears 34 times across three SQL files, against 40 `CREATE POLICY`
statements. The work is not relabelling rows: it is rewriting those policies from boolean to
group semantics and re-verifying the grant and attack matrices, which is this project's central
discipline. It is centralised — five of the seven tables derive restriction through
`document_is_restricted()` / `conflict_is_restricted()` and only `document` and `chunk` store
the flag — but it is not cheap.

**Deferring is still correct**, because a wrong model built on a guess costs more than a late
one built on an answer, and because the boolean is already enforced and already fails closed.
The cost of being wrong is asymmetric in the safe direction: too-restrictive blocks a reviewer,
too-permissive leaks commercial terms.

**Confidence: High** on the model given negative answers; the confidence is entirely contingent
on the two questions.

---

## D-16 — A reviewer's decision is a claim, and it settles its group (contracts C5, C8)

> **Status: ADOPTED 2026-09-02**, on the instruction to fix every verified defect. Closes
> [A-53](analysis.md). Recommended shape **A** of what was `open-decisions.md` item 8, as
> `sql/06_resolution.sql:29-38` proposed.

**The defect.** `services.claims.project()` never read or wrote `resolution`, `_preferred()` had no
human tier, and `_status_for()` reopened any group holding more than one distinct answer. So a
recorded decision was discarded by the next reducer run, and a human's value recorded as a claim
*reopened* the conflict it settled. Reproduced: re-committing the identical, complete claim set
for a resolved field stored `OPEN` / `resolution=None`.

**Adopted.**

1. **A human claim is a `FieldClaim` whose `extractor_version` starts with `human:`** and which
   carries its `Resolution`. The validator enforces both directions: a `human:` claim without a
   `Resolution` is "a decision with nobody behind it"; a `Resolution` on a machine claim is "a
   person's name on a machine value". `sql/06` recommended the convention and said it could not
   enforce it; `FieldClaim._human_claims_carry_their_decision` is the enforcement.
2. **Only value-asserting actions may be claims**: `SELECT_VALUE`, `ENTER_OVERRIDE`,
   `KEEP_SYSTEM_OF_RECORD`. `DEFER` and `REQUEST_MORE_WEB_SEARCH` assert nothing about the
   world; they are events against the *conflict*, recorded in `resolution` and `audit.event`.
3. **`value_after`, when recorded, must equal the claim's value.** A decision logged against one
   number and a claim asserting another is the drift the reducer exists to make impossible.
4. **The reducer:** `_preferred` ranks a human claim above every tier and confidence, and among
   human claims the latest `resolved_at` — stored data, not the clock — wins; `_status_for`
   returns `RESOLVED` whenever a human claim is in the group; `project()` copies the decision
   onto `CanonicalField.resolution`, so RESOLVED-with-resolution is produced by construction.
5. **A settled group stays settled.** A later extraction that disagrees does not reopen it;
   reopening is a human action (`REQUEST_MORE_WEB_SEARCH`, capped at 3 by task F.3). The
   alternative — any new answer reopens — makes every re-extraction a silent appeal.
6. **`claim_key` carries `resolved_at` for a human claim**, so one reviewer's second decision on
   a field is a new assertion rather than a same-key contradiction that raises `ProposalError`.
7. **`assert_no_autonomous_overwrite` passes a field carrying a `Resolution`.** The rule is against
   *autonomous* overwrite; a reviewer choosing the web candidate is FR-HITL-04's `SELECT_VALUE`.
   A web value with no decision behind it is still refused.
8. **Provenance of a human claim** is the selected candidate's `source_ref` for `SELECT_VALUE`
   and `KEEP_SYSTEM_OF_RECORD`, and the reviewer-cited source for `ENTER_OVERRIDE`. NFR-01's
   "no value without a source" holds unchanged; `SourceRef` still requires a document or URL.

**What it costs.** `FieldClaim` gains a key, so the two committed claim fixtures were
regenerated with the canonical options (`tests/fixtures/README.md` § Regenerating);
their behavioural assertions are unchanged. `sql/04_claim.sql` still has no `resolution`
column — the Python record is ahead of the DDL. **D-27 assigns the link to Story 4a** in
`sql/10_claim_resolution_link.sql` (`claim.resolution_id` plus a CHECK mirroring the validator).

**Rejected: `project(claims, resolutions)`.** A second input keeps the reducer pure but breaks
the sentence C8 is built on — "the canonical value is a projection over claims, never an
in-place update" — and gives the store two write paths to keep consistent.

## D-17 — List-valued fields are sets (amends D-2)

> **Status: ADOPTED 2026-09-02**, on the same instruction. Closes [A-55](analysis.md).

**The defect.** `values_conflict` compared numbers, then text, then fell through to
`a.value == b.value` — order-sensitive — with the reason "values are not comparable as numbers or
text". The contract's `list[str]` fields had no tolerance row and reached that fallback, so
two datasheets listing identical certifications in a different order raised a conflict.
`certifications` floors at `CRITICAL`, so `compose_gate_blocks()` refused the workbook over
typography.

**Adopted.**

1. **`ToleranceRule.SET_EQUAL`**, a seventh member. D-2's table gains one rule, not a general
   "unordered" flag on the others, because a set comparison changes the comparison rather than
   its threshold — the same reason D-2's six were kept distinct.
2. **Every `list[str]` key has a `SET_EQUAL` row** in `FIELD_TOLERANCES` (via `_set_equal`),
   pinned bidirectionally against the contract by
   `test_every_list_field_in_the_contract_has_a_set_rule`. None reaches `DEFAULT_TOLERANCE`.
3. **Per-element normalisation is the single-string one**: `_normalise_text` and
   `_editions_by_base`, so `IEC 61215:2016` against `:2021` is a `TEMPORAL` conflict on that
   element rather than a set mismatch.
4. **Containment is a conflict, not a gap.** For an attestation, absence is the finding
   (FR-HITL-01): `{UL 1741}` against `{UL 1741, IEC 61215}` is one source claiming a
   certification the other does not.
5. **A scalar in a set field is a conflict that says so** — an extractor emitted a string where
   the contract types a list — rather than a silent element-wise compare.
6. The off-contract fallback still compares lists as written, and its reason now says that
   element order counts because no `SET_EQUAL` row exists, instead of calling two lists
   "not comparable".
7. **`project()` status for SET_EQUAL is pairwise `values_conflict`**, not a
   canonical string of years. A missing edition is unknown (`IEC 61215` vs
   `:2021` is NONE); two dated editions still OPEN. `_asserted` still uses a set
   rendering so same-key duplicates collapse; lists are not sorted in `_render`.

## D-18 — The RESOLVED invariant is structural: RESOLVED is derived, not stored

> **Status: ADOPTED IN FULL 2026-09-02.** Closes [A-58](analysis.md).

**The defect.** `CanonicalField` forbids `conflict_status=RESOLVED` with `resolution=None` by
overriding five pydantic entry points, and the inventory was already incomplete. A stored
`ConflictStatus` that included RESOLVED also left `evolve(conflict_status=OPEN)` able to rewrite
the enum while leaving the decision in place, so Open Items hid remaining queue hits.

**Adopted, structural:** `RESOLVED` is *derived*, not stored.

1. `CanonicalField` stores `unresolved_status: UnresolvedStatus` — NONE, OPEN or
   INSUFFICIENT_EVIDENCE, with no RESOLVED member — and `resolution: Resolution | None`.
2. `conflict_status` is a computed field: RESOLVED exactly when a resolution is present,
   otherwise the stored state. It serialises under the TRS's key; `unresolved_status` is
   excluded from serialisation. **The wire shape is unchanged**: eight TRS keys plus
   `condition`, and `model_validate(model_dump())` round-trips both states.
3. The contract's name is still accepted everywhere it was: a before-validator maps
   `conflict_status=` onto the stored field for the constructor, `evolve` and
   `model_validate`, refusing RESOLVED-with-no-resolution at the door **and refusing to move a
   resolved field off RESOLVED** (the hole `evolve(conflict_status=OPEN)` used to take).
   `model_construct` maps the contract name rather than dropping it silently; the property
   setter shares the same two refusals.
4. **Deleted:** `_assert_resolution_matches_status`, the after-validator, and the
   `__setstate__` / `__deepcopy__` overrides — the forbidden combination has no representation.
   The `model_copy(update=)` refusal stays, because it is about the *other* invariant: an
   unvalidated `update` could replace a recorded `Resolution` unseen. `extra="forbid"` stays.
5. **What a raw `__dict__` write can still do** is clear `resolution`, which un-resolves the
   field consistently; it can no longer fabricate a resolved one. That residual is recorded in
   `tests/test_resolution_immutability.py` as a fact rather than an oversight.

**Cost, measured.** Zero fixture change — neither committed fixture serialises a
`CanonicalField`. The wire and `evolve` keep `conflict_status=`. The reducer copies the human
claim's `Resolution` onto the field and lets the decision derive RESOLVED.

---

## D-19 — Word documents are paged by conversion to PDF at ingest (Phase 2 Q-5)

> **Status: RATIFIED 2026-09-03.** Ratifies [phase-2/clarifications.md](phase-2/clarifications.md) Q-5
> option A. Owner: Story 1a.

**The fact.** Docling populates `prov[].page_no` from a page model that Word does not have, so
`.docx` tables arrive with empty provenance. FR-ING-05 promises "source, page and caption".

**Adopted.** At ingest, `.docx` is converted to PDF with LibreOffice headless
(`soffice --headless -env:UserInstallation=file:///tmp/<uuid> --convert-to pdf`) and the PDF is
parsed, so `page` is real. The stored document and its `content_hash` remain the **original
`.docx` bytes**. `section` (heading path) is recorded on every element in every format. If
`soffice` is absent the Docling adapter declares `PAGE_NUMBERS` as an `UNIMPLEMENTED` absence for
Word in the conformance matrix and elements carry `page=None` — loud, never estimated.

**Rejected:** estimating pages from character count (wrong pages presented as real).

## D-20 — Web search results are transient; the query and the fetched page are the record (Phase 2 Q-6)

> **Status: RATIFIED 2026-09-03 as the engineering rule.** The commercial half — whether to buy
> storage rights or change provider — remains a product-owner question and is tracked in
> [phase-2/clarifications.md](phase-2/clarifications.md) Q-6. Owner: Story 3.

**The fact.** The default provider's API terms (Brave) forbid storing or caching Search Results
beyond transient operational storage and forbid using them to evaluate or improve models.
FR-WEB-02 requires the query, URL, title and retrieval timestamp logged; NFR-02 makes that log
immutable.

**Adopted.**

1. What is persisted: the **query string** (ours) on `audit.run_event`; the **fetched page** as a
   `SourceDocument(source_uri=url, document_type=technical_documentation)` content-hashed like any
   upload; URL, title, `retrieved_at` and `source_authority` on the claim's `SourceRef`.
2. What is never persisted: provider rank, snippet, or any result metadata. `WebHit` has no field
   for them, so the rule is structural.
3. The gold set (D-11) is never built from search results.

## D-21 — The reviewer surface is server-rendered FastAPI + Jinja2 + HTMX with Authlib OIDC (Phase 2 Q-7)

> **Status: RATIFIED 2026-09-03.** Owner: Story 5.

FastAPI (MIT), Jinja2 (BSD-3), HTMX (BSD-2 / 0BSD), Authlib (BSD-3), uvicorn (BSD-3), httpx
(BSD-3, dev). Sync handlers run in FastAPI's threadpool — Decision 10 stands. No JavaScript build
step; no client-side state of record. The session carries the OIDC `sub` and clearance claim;
every request builds a `PrincipalContext` and every repository call goes through it. The UI never
filters restricted rows itself; RLS does (D-15).

**Rejected:** a React/Next front end (second toolchain for a workflow whose record is the
database); Streamlit/Gradio (poor fit for OIDC sessions and a five-action validated form).

## D-22 — The extraction model is Qwen3-30B-A3B-Instruct-2507 on vLLM (Phase 2 Q-8)

> **Status: RATIFIED 2026-09-03.** Owner: Story 1c. Re-benchmark on the gold set before any
> accuracy claim (D-11).

Apache-2.0 (passes the licence gate; Llama's community licence does not). MoE, 3.3 B active,
262 K native context. Alternate: dense `Qwen3-32B`, same licence.

**Server contract, part of the adapter's documentation:**
`vllm serve <model> --structured-outputs-config '{"backend":"xgrammar","disable_any_whitespace":true}'
--logprobs-mode raw_logprobs`. The first flag fixes the Instruct-2507 checkpoints' non-termination
under `json_schema`; the second returns logprobs **before** the grammar mask — `processed_logprobs`
saturates every token whose alternatives were masked, which is the naive-logprob failure D-3 names.
Requests use `response_format={"type":"json_schema", …}`; `guided_json` was removed in vLLM 0.12.
Instructor `Mode.JSON_SCHEMA` via `create_with_completion` only; a response without `logprobs`
raises.

## D-23 — `ParsedElement` is extended additively (Phase 2 Q-9; contract P2-C1)

> **Status: RATIFIED 2026-09-03.** Owner: Track 0.

`ParsedElement` gains four optional fields with `None`/default values: `bbox` (axis-aligned
envelope, page points, origin top-left), `table: TableData | None` (present iff `kind == "table"`;
`TableData(rows, header_rows, caption, merged)` with numbers rendered by `repr()`),
`page_quality: float | None` (0–1; D-3's "low-quality scan" gate reads it), and
`role: body | furniture | footnote | caption` (FR-ING-05). **Kinds stay `heading | body | table |
figure`.** The conformance pin on `__annotations__` is updated in the same PR. No `TableElement`
subclass; one carrier so every `isinstance` stays valid. OCR polygons are reduced to their envelope
on the element; the polygon itself lives on the OCR adapter's `recognize()` payload, not in `SourceRef`.

## D-24 — Gold labels are `gold:` claims that never enter a store (Phase 2 Q-10)

> **Status: RATIFIED 2026-09-03.** Owner: Story 1d harness.

A label is a `FieldClaim` with `extractor_version="gold:<annotator>"`, `source_tier=
system_of_record`. `commit_claims` refuses the `gold:` prefix (asserted), so the store cannot be
polluted. Documents are **not** committed; they live under `PROCUREMENT_GOLD_CORPUS_DIR` and a
committed `tests/fixtures/gold/manifest.json` keys label files by `content_hash`. The gold suite
skips without the corpus (the `PROCUREMENT_TEST_DSN` pattern) and fails on silent skip on the
self-hosted runner. D-16's `human:` rule is untouched: a gold label is not a decision about a
conflict.

## D-25 — The lexical leg is a seventh port, `LexicalSearchPort` (Phase 2 Q-11; contract P2-C3)

> **Status: RATIFIED 2026-09-03.** Owner: Track 0 (type, reference, capability row), Story 2
> (Postgres adapter). Adds the seventh synchronous Protocol. D-26 adds the eighth; the docs
> sweep pins **eight**.

```python
class LexicalSearchPort(Protocol):
    def search_lexical(
        self,
        query: str,
        *,
        limit: int,
        category: ComponentCategory | None = None,
        supplier: str | None = None,
        source_tier: SourceTier | None = None,
        allowed_document_ids: set[str] | None = None,
    ) -> list[RetrievedChunk]: ...
```

`allowed_document_ids=None` returns nothing — the `VectorStorePort` rule, unchanged. Capabilities
`DETERMINISTIC_OUTPUT, METADATA_FILTERING, ACCESS_FILTERING, TRIGRAM_TOLERANCE`;
`ACCESS_FILTERING` remains un-xfailable. Hybrid retrieval fuses dense and lexical with RRF k=60 in
`services.retrieval`. **Rejected:** a `search_lexical` method on `VectorStorePort` (forces every
vector backend to implement or disclaim lexical search); fusion hidden inside the pgvector adapter
(the part-number test becomes inexpressible against the reference).

**Sweep owed with the Track 0 PR:** every document that says "six ports" — `plan.md` Decision 10,
`ADR-001`, `docs/current-state.md`, `docs/requirements-traceability.md` NFR-04, `ports/__init__.py`,
`phase-1-execution.md`, `analysis.md` A-20, the docstrings of `adapters/registry.py`,
`adapters/__init__.py`, `tests/port_contracts/*` — is corrected to eight (D-25's seventh plus
D-26's `WebSearchPort`). The grep test in P2-A-24 is the pin, not this list.

## D-26 — `WebSearchPort` is an eighth port; the CEC pull is a CLI job, not a stage (Phase 2 Q-12; contract P2-C4)

> **Status: RATIFIED 2026-09-03.** Owner: Track 0 (port), Story 3 (adapters, CEC).

`WebSearchPort.search(query, *, limit) -> list[WebHit]`; `WebHit(url, title, retrieved_at,
provider)` — no snippet, no rank (D-20). Reference adapter is deterministic from a fixture map;
the Brave adapter enforces `Settings.web_search_rate_limit_per_minute` with a token bucket and an
explicit timeout (ADR-001 §3).

The weekly CEC pull (D-8) is `procurement-agent cec-refresh` driven by an external scheduler and
audited on a `run:` stream. **`Stage` gains no member** — the six values are pinned by
`sql/08_job.sql`'s CHECK and by the runtime rule that the reducer is `detect_conflicts`.

## D-27 — A human claim row links to its resolution by `claim.resolution_id` (Phase 2 Q-13; contract P2-C6)

> **Status: RATIFIED 2026-09-03.** Closes the "Python ahead of DDL" note in D-16. Owner: Story 4a.

`sql/10_claim_resolution_link.sql` (forward-only, the `sql/09` pattern):

```sql
ALTER TABLE public.claim ADD COLUMN resolution_id text NULL REFERENCES public.resolution(resolution_id);
ALTER TABLE public.claim ADD CONSTRAINT claim_human_carries_resolution
  CHECK ((extractor_version LIKE 'human:%') = (resolution_id IS NOT NULL));
```

Mirrors `FieldClaim._human_claims_carry_their_decision` exactly. Insert order is resolution, then
the human claim. `resolution.selected_claim_id` keeps pointing at the *candidate* claim; the new
column points from the *human* claim to its decision. **Rejected:** a JSON copy of the
`Resolution` on the claim row (two copies of an append-only fact); deriving the link by
`resolved_by` and time (collides within a second).

## D-28 — The CLI is stdlib `argparse` (Phase 2 Q-14)

> **Status: RATIFIED 2026-09-03.** Owner: Story 4b.

`[project.scripts] procurement-agent`. Core dependencies stay thin, per the `pyproject` rule that
every heavy dependency sits behind an extra. Typer/Click are acceptable licences and add nothing the
subcommand set needs.

## D-29 — `ProjectionPolicy` embeds the τ table by value (Phase 2 Q-15; amends D-14; closes A-51)

> **Status: RATIFIED 2026-09-03.** Owner: Story 6 (writer), Story 1c (table). **Amends D-14**: the
> projection's `policy` object gains one key.

`ProjectionPolicy(policy_version, confidence_threshold, thresholds: Mapping[str, float])`. The
per-field τ that `threshold_for(field_name)` returns is embedded **by value**, so the D-14 hash
changes exactly when a threshold changes — the hash exists to change when the workbook would. By
name would let two different threshold tables share one hash.

**Cost, stated before it is paid.** One structural re-baseline of
`tests/fixtures/workbooks/two-supplier-pv-store.json` and its digest: `policy` gains `thresholds`
mapping every field to the fixture's existing 0.80; every field row is byte-identical. The PR must
show the diff as **one added key, identical field rows** — the permutation-only discipline of
Phase 1 Track 1b applied to a key addition. `policy_version` stays `fixture-2026-08-12`.

## D-30 — A stale access-review register warns at ingest and never blocks (Phase 2 Q-16)

> **Status: RATIFIED 2026-09-03.** Owner: Story 7 (register), Story 1a (check).

`docs/access-review.md` is the register (date · NDA hash or roster date · outcome · reviewer);
`Settings.access_review_max_age_days` (default 90). When a document classified into a restricted
type arrives and the register is older than that, `ingest()` emits a warning in the structured log
and on the run event and labels the document restricted as usual. It never blocks: D-15 already
states the asymmetry — too-restrictive blocks a reviewer, too-permissive leaks — and the default
label is the safe direction, so blocking buys nothing.

## Carried forward as genuinely unresolved

These could not be settled and are assigned in [tasks.md](tasks.md):

1. **The deterministic xlsx has never been opened in desktop Excel or LibreOffice.** Validation is
   openpyxl round-trip and OPC structural checks only. **Gating.**
2. **IEEE C57.12.00 clause text is paywalled.** The +6% total-loss and 2.5% impedance-split
   figures are corroborated three times but never read from the standard. Verify before
   hard-coding. IEC figures are primary-verified.
3. **CEC's exact weighted-efficiency derivation is not reproducible** from the published matrix.
   The 0.5 pp quantisation is verified fact; the formula is not. Treat the headline column as
   lossy and use the full-precision per-voltage columns.
4. **Inverter/BESS suffix semantics — mostly resolved in D-4a.** Still open, all low-confidence:
   Power Electronics `FS____K`, CPS `-DO` literal expansion, TMEIC `GR` vs `URN`, SolarEdge's
   positional ordering part number, Sineng entirely (no CEC entries, site unreachable), CATL and
   Samsung SDI model numbers, Tesla Megapack 3 / Megablock part numbers.
5. **Reranker latency** figures are secondary-source with unstated batch size.
6. **Iterative-scan recall under RLS** — row count verified, true nearest neighbours not. Moot
   while the no-ANN-index decision holds.
