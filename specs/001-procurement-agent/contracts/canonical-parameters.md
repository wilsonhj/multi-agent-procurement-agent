# Contract: canonical parameters by component category

**Status:** FROZEN — this is a shared contract. Changing a field name or type here breaks
every team downstream. Additions are cheap; renames and type changes are not.

Source: TRS v2 section 7. The TRS preface applies: *"Example values are illustrative for
schema realism, not procurement guidance."*

> **Amended 2026-07-28 by [clarifications.md D-1](../clarifications.md).** Every field also
> carries a `condition`. Most false conflicts in this domain are condition mismatches rather than
> unit errors, and several entries below (`rated_ac_power_temp`, `stc_rating` vs `nmot_rating`,
> `usable_energy_per_container` vs `nameplate_energy_per_container`) are ad-hoc encodings of
> exactly that. See **Conditions** at the foot of this document.

## How to read this

Every parameter becomes a `CanonicalField` (see `src/procurement_agent/schema/field.py`).
The columns below define the field's **key**, its **value type**, and its **canonical unit**.

- `key` — the dict key in `ComponentInstance.fields`. snake_case, stable, never renamed.
- `type` — the Python type of `CanonicalField.value` after normalisation.
- `canonical unit` — what `CanonicalField.unit` holds. `—` means the value is unitless or
  categorical. Notation variants that must normalise to this unit are in
  [clarifications.md](../clarifications.md).
- `enum` — where the value is categorical, the permitted set. Extraction returning a value
  outside the set is a validation failure, not a silent pass-through.

Every field is optional. A missing field is `None` with `CellFlag.MISSING_DATA`, never an
invented default. Certification fields are `list[str]` of standard identifiers; an empty list
means "we looked and found none stated", which is materially different from `None` meaning
"we have not established this".

---

## 1. PV Modules — `pv_modules`

| key | type | canonical unit | notes |
|---|---|---|---|
| `nameplate_power` | float | `Wp` | STC nameplate |
| `power_tolerance_min` | float | `W` | e.g. `0` in a 0/+5 W binning |
| `power_tolerance_max` | float | `W` | e.g. `+5` |
| `cell_technology` | str | — | enum: `n_topcon`, `perc`, `hjt`, `ibc`, `cdte`, `other` |
| `module_efficiency` | float | `%` | |
| `temp_coeff_pmax` | float | `%/degC` | negative; sign convention is load-bearing |
| `temp_coeff_voc` | float | `%/degC` | negative |
| `temp_coeff_isc` | float | `%/degC` | positive |
| `bifaciality_factor` | float | `%` | `None` for monofacial, not `0` |
| `stc_rating` | float | `Wp` | |
| `nmot_rating` | float | `Wp` | |
| `max_system_voltage` | float | `V` | typically 1500 |
| `degradation_year_1` | float | `%` | |
| `degradation_annual` | float | `%/yr` | years 2 onward |
| `product_warranty_years` | int | `yr` | workmanship |
| `performance_warranty_years` | int | `yr` | output guarantee |
| `performance_warranty_end_output` | float | `%` | retained output at end of term |
| `certifications` | list[str] | — | IEC 61215, IEC 61730 / UL 61730, IEC 61701, IEC TS 63209 |
| `domestic_content_status` | str | — | enum: `qualified`, `not_qualified`, `unconfirmed` |
| `price_per_watt_dc` | float | `USD/W` | |

## 2. Inverters / PCS — `inverters_pcs`

| key | type | canonical unit | notes |
|---|---|---|---|
| `topology` | str | — | enum: `central`, `string`, `pcs` |
| `rated_ac_power` | float | `kVA` | see `rated_ac_power_temp` |
| `rated_ac_power_temp` | float | `degC` | ambient the rating is stated at; a rating without its temperature is not comparable |
| `max_dc_voltage` | float | `V` | typically 1500 |
| `mppt_count` | int | — | |
| `mppt_voltage_min` | float | `V` | |
| `mppt_voltage_max` | float | `V` | |
| `max_efficiency` | float | `%` | |
| `cec_efficiency` | float | `%` | weighted; cross-checkable against the CEC list |
| `ride_through_standards` | list[str] | — | IEEE 1547-2018, IEEE 2800-2022, NERC PRC-029-1 |
| `reactive_capability_at_zero_output` | bool | — | required for SGIAs on/after 2024-08-01 |
| `trd_percent` | float | `%` | Total Rated-current Distortion. **Not TDD** — see below |
| `trd_limit_applied` | float | `%` | the IEEE 2800 Cl.8 limit for this plant's voltage class |
| `harmonic_spectrum` | dict[int, float] | `%` | harmonic order → magnitude |
| `thd_percent` | float | `%` | |
| `filtering_provisions` | list[str] | — | enum members: `lcl`, `active`, `passive`, `none` |
| `dc_injection` | float | `%` | of rated output |
| `flicker_pst` | float | — | short-term |
| `flicker_plt` | float | — | long-term |
| `certifications` | list[str] | — | UL 1741 SB, IEC 62109 |
| `communication_protocols` | list[str] | — | |
| `warranty_years` | int | `yr` | |
| `price_per_watt_ac` | float | `USD/W` | |

> **TRD, not TDD.** The TRS flags this as the key correction from v1: for a
> transmission-connected 500 MW plant the binding limit is IEEE 2800-2022 Clause 8 TRD.
> The commonly cited 1.5% figure is an *individual harmonic* limit, not a total limit.
> Getting this wrong produces a compliance matrix that passes suppliers it should fail.
> AC-6 tests it. Exact numeric limits require confirmation against the purchased standard —
> see [clarifications.md](../clarifications.md).

## 3. Trackers & Mounting — `trackers_mounting`

| key | type | canonical unit | notes |
|---|---|---|---|
| `configuration` | str | — | enum: `1p_tracker`, `2p_tracker`, `fixed_tilt` |
| `tracking_range` | float | `deg` | total travel |
| `modules_per_row` | int | — | |
| `backtracking_yield_gain` | float | `%` | |
| `design_wind_speed` | float | `m/s` | per ASCE 7 |
| `stow_wind_speed` | float | `m/s` | |
| `stow_strategy` | str | — | |
| `ground_coverage_ratio` | float | — | dimensionless ratio, not a percentage |
| `foundations_per_mw` | float | `1/MW` | |
| `galvanization_spec` | str | — | |
| `corrosion_warranty_years` | int | `yr` | |
| `bearing_gear_l10_years` | float | `yr` | L10 design life |
| `communication_protocols` | list[str] | — | |
| `enclosure_rating` | str | — | NEMA class |
| `warranty_years` | int | `yr` | |

## 4. Transformers — `transformers`

| key | type | canonical unit | notes |
|---|---|---|---|
| `insulation_type` | str | — | enum: `oil`, `dry` |
| `rating_mva` | float | `MVA` | base rating |
| `cooling_classes` | list[str] | — | e.g. ONAN, ONAF |
| `rating_mva_by_cooling` | dict[str, float] | `MVA` | rating per cooling stage |
| `voltage_hv` | float | `kV` | |
| `voltage_lv` | float | `kV` | |
| `vector_group` | str | — | |
| `impedance_percent` | float | `%` | |
| `k_factor` | float | — | harmonic capability |
| `no_load_loss` | float | `kW` | drives loss economics |
| `load_loss` | float | `kW` | |
| `efficiency` | float | `%` | |
| `standards` | list[str] | — | IEEE C57, IEC 60076, DOE |
| `warranty_years` | int | `yr` | |

## 5. Cabling & Wiring — `cabling_wiring`

| key | type | canonical unit | notes |
|---|---|---|---|
| `conductor_material` | str | — | enum: `copper`, `aluminium` |
| `conductor_size` | str | — | AWG or kcmil, retained as written |
| `conductor_area` | float | `mm2` | normalised for comparison |
| `voltage_class` | float | `V` | 1500 DC, or MV 15/25/35 kV |
| `insulation_type` | str | — | XLPE, PV wire, USE-2 |
| `ampacity` | float | `A` | |
| `load_factor` | float | — | |
| `ul_listing` | list[str] | — | e.g. UL 4703 |
| `shielding` | str | — | |
| `standards` | list[str] | — | ICEA, ASTM |
| `price_per_metre` | float | `USD/m` | |

## 6. Combiner Boxes — `combiner_boxes`

| key | type | canonical unit | notes |
|---|---|---|---|
| `input_count` | int | — | strings accepted |
| `fuse_rating` | float | `A` | |
| `max_system_voltage` | float | `V` | 1500 DC |
| `continuous_current` | float | `A` | |
| `string_monitoring` | bool | — | |
| `enclosure_rating` | str | — | NEMA 3R, NEMA 4 |
| `surge_protection` | bool | — | SPD present |
| `disconnect_type` | str | — | |
| `certifications` | list[str] | — | UL 1741, UL 98 |
| `warranty_years` | int | `yr` | |

## 7. BESS — `bess`

| key | type | canonical unit | notes |
|---|---|---|---|
| `chemistry` | str | — | enum: `lfp`, `nmc`, `other` |
| `usable_energy_per_container` | float | `MWh` | usable, not nameplate |
| `nameplate_energy_per_container` | float | `MWh` | stated separately — conflating the two is a common and expensive error |
| `power_rating` | float | `MW` | |
| `c_rate` | float | — | |
| `round_trip_efficiency` | float | `%` | state measurement basis where given |
| `cycle_life` | int | — | cycles to end-of-warranty capacity |
| `augmentation_plan` | str | — | |
| `degradation_warranty_years` | int | `yr` | |
| `degradation_warranty_cycles` | int | — | |
| `thermal_management` | str | — | enum: `air`, `liquid`, `other` |
| `fire_safety_certifications` | list[str] | — | UL 9540, UL 9540A 6th Ed., NFPA 855 (2026), NFPA 68, NFPA 69 |
| `cell_certification` | list[str] | — | UL 1973 |
| `pcs_certification` | list[str] | — | UL 1741, IEEE 2800 |
| `seismic_qualification` | str | — | IEEE 693 |
| `energy_density` | float | `MWh/m2` | footprint driver |
| `footprint_area` | float | `m2` | per container |

## 8. EMS / SCADA & Controls — `ems_scada`

| key | type | canonical unit | notes |
|---|---|---|---|
| `plant_controller_model` | str | — | |
| `ride_through_coordination` | bool | — | |
| `automatic_generation_control` | bool | — | AGS; required for storage SGIAs on/after 2026-04-01 |
| `protocols` | list[str] | — | Modbus, DNP3, IEC 61850 |
| `ercot_telemetry` | bool | — | |
| `pmu_support` | bool | — | |
| `cybersecurity_standards` | list[str] | — | |
| `inverter_integration` | list[str] | — | vendors supported |
| `bess_integration` | list[str] | — | vendors supported |
| `support_terms` | str | — | |

---

## Cross-category fields

Present on every `ComponentInstance` regardless of category. Owned by the schema team; no
category team defines these.

| key | type | notes |
|---|---|---|
| `supplier` | str | normalised manufacturer name — see identity resolution in clarifications.md |
| `supplier_verbatim` | str | name exactly as it appeared |
| `model` | str | normalised model identifier |
| `model_verbatim` | str | model exactly as it appeared |
| `component_category` | ComponentCategory | |
| `datasheet_revision` | str | drives temporal conflict detection |
| `datasheet_date` | date | data vintage, reported per FR-OUT-06 |

## Compliance and tax fields

These populate tabs 12 and 13 and are cross-category. Owned by the compliance team.

| key | type | notes |
|---|---|---|
| `baba_status` | str | enum: `compliant`, `non_compliant`, `not_applicable`, `unconfirmed` — `not_applicable` when the project is privately financed |
| `baba_certification_ref` | str | supplier certification document reference |
| `country_of_origin` | str | |
| `domestic_content_percentage` | float | `%` |
| `feoc_pfe_status` | str | enum: `qualified`, `not_qualified`, `unconfirmed` |
| `material_assistance_cost_ratio` | float | `%` — threshold differs for solar vs storage |
| `ercot_compliance_items` | dict[str, str] | standard identifier → status |

> **BABA applicability is unresolved.** It applies only if federal funding is in the project,
> and the FRD does not confirm the funding status. Until confirmed, `baba_status` defaults to
> `unconfirmed`, never to `not_applicable`. Defaulting to `not_applicable` would silently
> assert a funding fact nobody has established.

---

## Conditions

Every `CanonicalField` carries a `Condition`. **Two values are comparable only when their
conditions match; a mismatch is not a conflict, it is not a comparison.**

Which condition fields are required, by parameter family:

| Family | Required condition fields | Why |
|---|---|---|
| PV power, efficiency, all electrical | `basis` ∈ {`stc`, `nmot`, `noct`, `bnpi`} | Trina prints STC 695 W and NOCT 531 W side by side. A naive table grab returns 531. The BNPI/bifacial-gain table can read 30% higher again. |
| PV temperature coefficients | none — but see below | `%/degC` ≡ `%/K`. **Never route through a temperature converter**; the +273.15 offset silently destroys the value. |
| Inverter rated power | `temperature_c` | `352 kVA @30°C / 320 @40°C / 295 @50°C` are all "rated". CEC anchors on 40 °C. |
| Inverter efficiency | `weighting` ∈ {`max`, `cec`, `european`} | 99.02% max, 98.5% CEC and 98.8% European are one product. |
| Inverter MPPT window | `basis` ∈ {`full_range`, `full_power`} | `500–1500 V` and `860–1330 V` are different fields, not a discrepancy. |
| BESS energy | `side` ∈ {`ac`, `dc`}, `basis` ∈ {`nameplate`, `bol`, `fat`, `sat_1mo`, `sat_3mo`, `eol`} | BOL vs EOL differ ~26% on real projects. AC vs DC straddles the PCS. |
| BESS RTE | `side`, `duration_h`, plus boundary in `note` | Four distinct boundaries all called "round-trip efficiency", worth 2–7 pp. RTE is duration-dependent even at one boundary. |
| BESS cycle life | `basis` = EOL SOH threshold (60/70/80%) | Frequently omitted entirely, which makes the number uncomparable. |
| Transformer MVA | `standards_regime`, plus cooling class per rating | IEEE lists base-first, IEC top-first. "Take the first number" is right for one and wrong for the other. |
| Transformer %Z | `standards_regime`, base MVA and tapping in `note` | %Z scales linearly with the MVA base — the same unit differs 1.25–1.67× between regimes. |
| Transformer losses | `reference_temperature_c` | IEEE load loss at `20 + rise` (75/85/95 °C); IEC at 75 °C regardless. No-load loss is **not** temperature-corrected. |

**Absent is unknown, not contradictory.** A condition field set on one side and absent on the
other does not block comparison. This admits some false conflicts; refusing to compare whenever a
datasheet states conditions incompletely would block nearly everything.
