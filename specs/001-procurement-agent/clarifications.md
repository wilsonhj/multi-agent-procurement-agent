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

## D-13 — Audit canonicalisation and the hash preimage (contract C4) ⚠️ PROPOSED, NOT RATIFIED

> **Status.** Drafted 2026-08-06 to close C4's decision half; a default, not a conclusion.
> **The deadline is real:** §3's version marker must exist before the first event is ever
> emitted, so this needs ratifying before WP-H writes anything.
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

**The package has not been installed, locked, or executed against this repo's data** — it is not
in `pyproject.toml` or `uv.lock`. Ratifying this decision should be paired with adding the
dependency and a conformance test against RFC 8785's own published test vectors, because the
whole argument for using a library rather than hand-rolling is that its conformance is somebody
else's problem *only once you have checked it*.

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

**Where the run-scoped events live — recommended, and the maintainer's to confirm.**
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

## D-14 — The canonical workbook projection (contract C6) ⚠️ PROPOSED, NOT RATIFIED

> **Status.** Drafted 2026-08-06 to close T0.5. C6 is the only contract at zero — `write_workbook()`
> raises and no *workbook* projection function exists — and it blocks WP-G entirely, including
> the gating G.6 desktop-Excel test. (`services.claims.project` is a different projection: claims
> to canonical fields, contract C8. C6 is the projection of the whole store to the hashed
> artifact.) A default, not a conclusion.

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
`{projection_version: 1, policy: {...}, components: [...], conflicts: [...], sources: [...]}`.
Arrays wherever order is meaning: components by `ComponentInstance.ordering_key()` (D-4 stage 5),
fields by name, then:

- **Candidates sort by `conflict_hitl._ordering_key`, never by arrival.** An earlier draft said
  "existing candidate order", which this repo's own rule forbids: that function's docstring
  states FR-OUT-06 "makes composition a pure function of the store: any list the queue payload is
  built from has to be arranged by what a candidate *is*, never by when it arrived." Regeneration
  re-reads `conflict_candidate` rows, and without an explicit sort there is no "existing order"
  to preserve.
- **Condition groups sort by their `encode_value()` form, not `repr(grouping_key())`.** Those
  tuples contain enum members, and `repr(MeasurementBasis.STC)` is `<MeasurementBasis.STC: 'stc'>`
  — CPython's enum repr, an implementation detail the stdlib reworked as recently as 3.11. Baked
  into a hashed artifact, a routine Python upgrade would re-baseline every golden hash with zero
  data change. `repr()` remains fine as `project()`'s in-memory key; it must not reach the bytes.

**One frozen `encode_value()`** for `value: object` — `DeclaredBand` via `model_dump`, datetimes
as RFC 3339 UTC with microseconds **always** printed (`isoformat()` omits `.000000` when zero, so
pin a formatter rather than relying on it), enums via `.value`, frozensets sorted as `derived`
already is.

**Two decisions here are judgement calls, not mechanics:**

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

   **Two consequences that must land with it.** Hashing policy makes the B.10 τ table
   **versioned, append-only data** — otherwise historical projections become unrecomputable the
   first time τ moves. And golden fixtures must pin their own τ so production re-tuning never
   re-baselines them; `tasks.md` sequences τ tuning after WP-B, which is exactly when fixture
   churn would otherwise be worst.
2. **`generated_on` must be store-derived, not wall clock.** FR-OUT-06 demands the stamp; AC-7 and
   G.5's `sleep(1.1)` re-run demand byte-identity; a store-derived stamp satisfies both with no
   normative edit. The rule already exists at `services/output/__init__.py:151-153`; what is new
   is promoting it out of a docstring on an unimplemented function. See [A-48](analysis.md).

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

   **Still open:** the zero-document sentinel. An empty store has no maximum, and the value must
   be an explicit null or "no sources" — never an epoch-like date that reads as data. This must
   be settled before the golden fixture is written.

**Two hashes stored**, per plan 8c: `sha256(projection)` is the artifact of record;
`sha256(normalized xlsx)` is a renderer-regression check only, never the integrity claim.

**Golden fixture (T0.5):** one committed projection plus its hash for a synthetic two-supplier PV
store containing D-1's Sungrow trio, so the fixture exercises list-valued fields rather than the
easy one-value-per-key case. Note `tests/fixtures/` deliberately ships **no** projection fixture
until this decision is ratified — see `tests/fixtures/README.md`.

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
