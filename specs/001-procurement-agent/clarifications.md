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
| **RELATIVE** | Large-magnitude measured quantities — losses, energy, power | Measurement uncertainty scales with the value. |

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
| Transformer %Z | ±7.5% if Z≥10%, ±10% if Z<10% (IEC) | rel | IEC 60076-1 Table 1 item 3a, verbatim | High [V] |
| Transformer total losses | ±10% (IEC) / **+6% (IEEE)** | rel | Standards differ materially — see D-6 | High [V] / Med [S] |

**Loss tolerances are one-sided (upper only) in both IEC and IEEE.** A symmetric band is wrong
for losses in both regimes.

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
- **Tier τ by field criticality.** Price, quantity, dates, and Pmax/Voc/Isc get a stricter τ
  (target 99.5%); descriptive fields get a looser one.

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
| D-12a | Identity/auth model for `resolved_by` | Application-level user identity; a bare string until an IdP is chosen. Audit log records the string verbatim. | Medium |
| D-12b | Gate granularity | **Per-document-per-field.** Per-batch would give one review session but loses the ability to ship a partial workbook. | Medium |
| D-12c | Conflict expiry | **Conflicts never expire.** Expiry would silently discard a known data-quality problem. They age, and age is a reported metric. | High |
| D-12d | `request_more_web_search` looping | Reject at `reopen_count >= 3` and force a terminal decision. It is the only action that can cycle. | High |
| D-12e | Claim lease duration | 15 minutes, swept back to `pending` on expiry. | Medium |
| D-12f | BABA applicability | `unconfirmed` until project funding status is established — never `not_applicable`, which would silently assert a funding fact. | High |

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
