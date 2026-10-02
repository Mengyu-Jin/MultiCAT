# Schema Field Design

This file documents the field design for the XML-first biomass catalysis extraction project. All machine-readable field names, JSON keys, CSV/TSV/Excel headers, schema properties, and status enum values use English.

## 1. Trace / Index Fields

Purpose: traceability, deduplication, and debugging — not used as ML features.

```text
paper_id
reaction_id
catalyst_id
record_id
doi
source_file
source_type
evidence
```

Rules:

- `record_id = paper_id + "_" + reaction_id`, e.g. `P000001_rxn_001`.
- `paper_id`, `reaction_id`, `catalyst_id` are retained in the audit table.
- The ML-ready table retains only `record_id` and `doi` as minimal trace columns; modeling scripts exclude these from X by default.

`source_type`:

```text
table
text
caption
mixed
unknown
```

## 2. Paper Metadata

```text
title
journal
year
publisher
xml_source
```

Field purpose:

```text
title             not_for_ml
journal           not_for_ml
year              optional_for_ml
publisher         not_for_ml
xml_source        not_for_ml
```

`xml_source`:

```text
elsevier
pmc
springer
unknown
```

## 3. Catalyst Identity / Class

Core principle: first split into supported / unsupported. Supported catalysts are classified by platform/support; unsupported catalysts are classified by the catalyst body itself.

```text
catalyst_name
support_status
support_class
unsupported_class
```

`support_status`:

```text
supported
unsupported
unknown
```

`supported` definition: a metal, metal oxide, acid site, functional group, or other active component is hosted on a material platform. This includes framework doping, heteroatom substitution, impregnation, deposition, anchoring, grafting, ion exchange, and functionalization.

Examples:

```text
Sn-Beta
Zr-Beta
Cr-MCM-41
Sn-SBA-15
Pt/C
Ru/Al2O3
Nb2O5-gamma-Al2O3
La(OTf)3/SiO2
SO3H-carbon
sulfonated carbon
H3PW12O40/SiO2
```

`unsupported` definition: the catalyst body itself is the active material, with no clear "active component + material platform" relationship.

Examples:

```text
ZrO2
TiO2
Nb2O5
CaO
MgO
Amberlyst-15
bulk MOF
bulk solid H3PW12O40
kaolin
montmorillonite
```

`support_class` is used only when `support_status = supported`:

```text
oxide
zeolite_silica
carbon
polymer_resin
mof
mineral_clay
others
none
```

Examples:

```text
Sn-Beta                  zeolite_silica
Zr-Beta                  zeolite_silica
Sn-SBA-15                zeolite_silica
La(OTf)3/SiO2            zeolite_silica
Pt/C                     carbon
SO3H-carbon              carbon
sulfonated carbon        carbon
Ru/Al2O3                 oxide
Nb2O5-gamma-Al2O3        oxide
Pt/UiO-66                mof
metal/montmorillonite    mineral_clay
unsupported catalyst     none
```

`unsupported_class` is used only when `support_status = unsupported`:

```text
metal_oxide
zeolite_silica
carbon
polymer_resin
mof
heteropoly_acid_solid
mineral_clay
others
none
```

Examples:

```text
ZrO2                     metal_oxide
TiO2                     metal_oxide
CaO                      metal_oxide
H-Beta                   zeolite_silica
activated carbon         carbon
Amberlyst-15             polymer_resin
bulk MOF catalyst        mof
bulk solid H3PW12O40     heteropoly_acid_solid
kaolin                   mineral_clay
supported catalyst       none
```

Hard rules:

- `support_status = supported`: `support_class` is set to the platform/support type; `unsupported_class = none`.
- `support_status = unsupported`: `support_class = none`; `unsupported_class` is set to the catalyst-body type.
- `support_status = unknown`: `support_class = others`; `unsupported_class = others`.
- Homogeneous acids, soluble salts, and molecular catalysts do not enter the final ML table; they should be flagged `out_of_scope` by the Screening agent or the Validator.

## 4. Metal / Composition Fields

The raw extraction JSON supports an arbitrary number of `metals[]` entries, to avoid losing information for tri-metallic or multi-metallic catalysts.

```text
composition_raw
metals[]
```

Each `metals[]` object:

```text
element
content_value
content_unit
content_label
role
evidence
```

`role`:

```text
active
promoter
support_framework
unknown
```

The ML flat table expands the first three metals:

```text
composition_raw
num_metals
metal_1
metal_2
metal_3
metal_1_content_value
metal_1_content_unit
metal_2_content_value
metal_2_content_unit
metal_3_content_value
metal_3_content_unit
has_more_than_3_metals
metals_all
total_metal_content_value
total_metal_content_unit
```

Rules:

- No metals: `num_metals = 0`, `metal_1/2/3 = none`, `metals_all = none`.
- One metal: fill `metal_1`.
- Two metals: fill `metal_1`, `metal_2`.
- Three metals: fill `metal_1`, `metal_2`, `metal_3`.
- More than three metals: the first three go into the fixed columns, `has_more_than_3_metals = true`, and `metals_all` retains the complete list.
- Ordering priority: primary metal explicitly stated in the source text > higher content under the same unit > order of appearance in the source text.

`Al/Si/C/O` rule:

- When acting only as a support or framework element, these are not counted as an active metal. For example, `Sn-Beta` counts only `Sn`; `Pt/C` counts only `Pt`.
- When the catalyst body itself is a metal oxide, these elements are counted. For example, `ZrO2` counts `Zr`; `Nb2O5` counts `Nb`.
- A mixed-oxide active catalyst may count multiple metals, e.g. `Cu-Zn-Al mixed oxide` counts `Cu;Zn;Al`.

## 5. Catalyst Synthesis

Records the catalyst preparation method and key thermal-treatment conditions.

```text
synthesis_method
modification_method
calcination_temp
calcination_temp_unit
calcination_time
calcination_time_unit
hydrothermal_temp
hydrothermal_temp_unit
hydrothermal_time
hydrothermal_time_unit
drying_temp
drying_temp_unit
drying_time
drying_time_unit
synthesis_text
```

`synthesis_method`:

```text
impregnation
hydrothermal
sol_gel
precipitation
co_precipitation
ion_exchange
grafting
sulfonation
carbonization
calcination
commercial
mechanical_mixing
others
unknown
```

`modification_method`:

```text
impregnation
ion_exchange
grafting
sulfonation
acid_treatment
base_treatment
metal_doping
calcination
reduction
oxidation
carbonization
others
none
unknown
```

`synthesis_text` holds the original synthesis evidence or a summary, for traceability only — not used as an ML feature.

## 6. Catalyst Characterization

```text
bet_area
bet_area_unit
total_pore_volume
total_pore_volume_unit
micropore_volume
micropore_volume_unit
bronsted_acidity
bronsted_acidity_unit
lewis_acidity
lewis_acidity_unit
strong_acidity
strong_acidity_unit
weak_acidity
weak_acidity_unit
total_acidity
total_acidity_unit
characterization_text
```

Field purpose:

```text
bet_area                    optional_for_ml
total_pore_volume           optional_for_ml
micropore_volume            optional_for_ml
bronsted_acidity            optional_for_ml
lewis_acidity                optional_for_ml
strong_acidity               optional_for_ml
weak_acidity                 optional_for_ml
total_acidity                optional_for_ml
characterization_text       trace
```

## 7. Substrate

Records only substrate identity and substrate features — not reaction feed quantities.

```text
substrate_name
substrate_class
substrate_origin
substrate_c_num
substrate_h_num
substrate_o_num
substrate_o_c_ratio
substrate_h_c_ratio
substrate_atom_count
is_polymeric
substrate_feature_source
```

`substrate_class`:

```text
c5_sugar
c6_sugar
disaccharide
polysaccharide
real_biomass
mixed_sugar
others
unknown
```

Examples:

```text
xylose, arabinose                  c5_sugar
glucose, fructose                  c6_sugar
sucrose, cellobiose, maltose       disaccharide
cellulose, microcrystalline cellulose, hemicellulose, xylan, starch    polysaccharide
corn stover, wheat straw, rice husk, bagasse, wood sawdust             real_biomass
glucose + xylose, mixed C5/C6 sugars                                   mixed_sugar
```

`substrate_origin`:

```text
model_compound
biomass_derived_fraction
raw_biomass
others
unknown
```

Examples:

```text
microcrystalline cellulose              model_compound
hemicellulose extracted from corn cob    biomass_derived_fraction
corn stover                              raw_biomass
```

`is_polymeric`:

```text
true
false
unknown
```

`substrate_feature_source`:

```text
extracted
rule_lookup
manual_reference
unknown
```

## 8. Reaction Conditions

```text
reaction_method
reaction_temperature
reaction_temperature_unit
reaction_time
reaction_time_unit
reaction_pressure
reaction_pressure_unit
reaction_atmosphere
substrate_mass
substrate_mass_unit
substrate_concentration
substrate_concentration_unit
catalyst_amount
catalyst_amount_unit
catalyst_loading
catalyst_loading_unit
catalyst_substrate_ratio
catalyst_substrate_ratio_source
solvent_name
solvent_volume
solvent_volume_unit
reactor_type
condition_text
```

`reaction_method`:

```text
hydrothermal
batch
microwave
continuous_flow
fixed_bed
autoclave
reflux
solvothermal
mechanochemical
others
unknown
```

`reaction_atmosphere` can be standardized during post-processing to:

```text
air
N2
Ar
H2
O2
CO2
vacuum
sealed
others
unknown
```

`catalyst_substrate_ratio_source`:

```text
extracted
calculated
none
unknown
```

Hard rules:

- The Extraction agent does not compute `catalyst_substrate_ratio`.
- When the source text explicitly states the ratio, `catalyst_substrate_ratio_source = extracted`.
- If post-processing computes it from `catalyst_amount / substrate_mass`, `catalyst_substrate_ratio_source = calculated`.
- Metal loading belongs to Metal / Composition, not Reaction Conditions.
- Catalyst loading in the reaction feed belongs to Reaction Conditions.

## 9. Performance Metrics

The raw JSON uses `performance_metrics[]`; the ML table expands this into fixed columns.

Each `performance_metrics[]` object:

```text
metric_name
product_name
value
unit
basis
original_label
evidence
```

`metric_name`:

```text
conversion
yield
selectivity
product_distribution
unknown
```

`product_name`:

```text
lactic_acid
hmf
furfural
levulinic_acid
formic_acid
acetic_acid
glycolic_acid
others
none
unknown
```

Rules:

- conversion: `product_name = none`
- yield/selectivity: `product_name` is set to the target product
- unknown: used when the metric type cannot be determined

`basis`:

```text
carbon_basis
molar_basis
mass_basis
substrate_basis
unknown
```

ML-ready expanded columns:

```text
substrate_conversion
lactic_acid_yield
hmf_yield
furfural_yield
levulinic_acid_yield
formic_acid_yield
acetic_acid_yield
glycolic_acid_yield
others_yield
lactic_acid_selectivity
hmf_selectivity
furfural_selectivity
levulinic_acid_selectivity
formic_acid_selectivity
acetic_acid_selectivity
glycolic_acid_selectivity
others_selectivity
```

## 10. Final Output Tables

### reaction_audit_table_v1.csv

Purpose: quality checking, traceability, repair, and human review — not used directly for ML.

May include:

```text
record_id
paper_id
reaction_id
catalyst_id
doi
title
journal
year
publisher
xml_source
catalyst_name
composition_raw
metals_all
synthesis_text
characterization_text
condition_text
evidence
source_type
original_label
unit fields
raw fields
validation_status
judge_status
```

### ml_ready_table_v1.csv

Purpose: a pool of ML-ready fields — not a fixed X-y split.

Retains minimal trace columns:

```text
record_id
doi
```

Modeling scripts exclude these by default:

```text
exclude_from_X = ["record_id", "doi"]
```

Audit-only fields are dropped:

```text
paper_id
reaction_id
catalyst_id
title
journal
publisher
xml_source
source_file
source_type
evidence
condition_text
synthesis_text
characterization_text
composition_raw
original_label
*_unit
*_label
*_source
validation_status
judge_status
```

All potential modeling fields and target fields are retained, including catalyst, composition, synthesis, characterization, substrate, reaction condition, and performance columns.

## 11. Next Implementation Targets

Implementation order:

```text
1. Update extraction schema to v1.
2. Update extraction prompt to use performance_metrics[] and v1 field names.
3. Update validator rules for support_status, class enums, performance metrics, out_of_scope.
4. Update database builder to emit reaction_audit_table_v1.csv and ml_ready_table_v1.csv.
5. Re-run small batch and compare v0 vs v1 field completeness.
```
