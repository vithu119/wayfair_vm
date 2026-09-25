# Wayfair Dynamic Template Auto-Fill System — Final Report

_Generated: 2026-07-15_

---

## A. Project Overview

The Wayfair Dynamic Template Auto-Fill System automates the mapping of internal product data onto Wayfair supplier upload templates (`.xlsx`). The system was built across four phases:

| Phase | Scope |
|-------|-------|
| 1 | Template analyser — workbook inspection, sheet classification, header detection, column metadata extraction |
| 2 | Auto-fill engine — source reader, field mapper, transformer, validator, writer |
| 3 | Dynamic row detection — removed all hardcoded `row 8` logic; introduced write policies and safe-write-start detection |
| 4A | Dynamic template registration — purpose classification, fill-status determination, template registry, registration workflow, CLI commands |

No external database writes are performed. Original template files are never modified. All output goes to `outputs/`.

---

## B. Architecture

```
wayfair_listing/
├── app/
│   ├── analyser/
│   │   ├── inspector.py            # Opens workbook, produces WorkbookProfile
│   │   ├── sheet_classifier.py     # Classifies each sheet (listing/valid_values/image/...)
│   │   ├── header_detector.py      # Detects header row via core:: keys or heuristic scan
│   │   ├── column_metadata.py      # Extracts per-column metadata (type, required, valid values)
│   │   ├── valid_values.py         # Extracts controlled-value tables
│   │   ├── profile_writer.py       # Serialises WorkbookProfile to JSON
│   │   ├── findings.py             # Finding dataclass; severity helpers (Phase 4A)
│   │   ├── purpose_classifier.py   # Multi-signal workbook purpose classification (Phase 4A)
│   │   ├── fill_status.py          # Determines fill_status from purpose + profile (Phase 4A)
│   │   ├── template_registry.py    # Persistent registry of registered templates (Phase 4A)
│   │   ├── registration_workflow.py# Full single/batch registration pipeline (Phase 4A)
│   │   └── integrity.py            # SHA-256 file hashing, snapshot verification
│   ├── autofill/
│   │   ├── engine.py               # Orchestrates fill for one template
│   │   ├── row_detector.py         # Classifies every row below the header
│   │   ├── write_policy.py         # Builds WritePlan from row classifications + policy
│   │   ├── writer.py               # Writes filled workbook using WritePlan
│   │   ├── source_reader.py        # Reads product data from CSV/JSON source
│   │   ├── mapper.py               # Maps source fields to Wayfair columns
│   │   ├── transformer.py          # Value transforms (trim, title-case, unit conversion, ...)
│   │   ├── validator.py            # Validates mapped values against column rules
│   │   └── fill_report.py          # Generates mapping/validation/write-plan reports
│   └── cli.py                      # argparse CLI (6 subcommands)
├── config/                         # Mapping rules (YAML/JSON)
├── outputs/
│   ├── template_profiles/          # Per-template WorkbookProfile JSON
│   ├── template_registry/          # Registry JSON + CSV + registration reports
│   └── filled/                     # Auto-filled output workbooks
└── tests/
    ├── conftest.py
    ├── test_autofill.py            # Phases 2 & 3 (105 tests)
    ├── test_phase4a.py             # Phase 4A (33 tests)
    ├── test_analyser.py
    ├── test_sheet_classification.py
    └── test_valid_values.py
```

---

## C. Key Design Rules (Immutable)

These constraints are enforced throughout and must not be broken in future changes:

1. **Never modify original uploaded template files.** All output is written to `outputs/filled/`.
2. **Never depend on fixed row or column numbers.** Header row, data-start row, and column positions are always detected dynamically.
3. **Never fabricate product values.** Only values from the source data or explicit config rules are written.
4. **Source systems are read-only.** No database writes are performed.
5. **No internal status fields in final exports.** Output files contain only Wayfair-spec columns.
6. **One invalid workbook must not stop the batch.** Errors are captured per-template; processing continues.
7. **Do not auto-delete sample or existing rows** without an explicit write policy.
8. **Do not overwrite real user-entered data** without an explicit `replace-all-products` policy selection.
9. **`replace-all-products` only runs when the user explicitly passes `--write-policy replace-all-products`.**
10. **Fill decisions are never made based on filename, `analysis_status`, or known category names.**

---

## D. Row Classification System (Phase 3)

`app/autofill/row_detector.py` classifies every row below the header before any write occurs.

### Row types

| Status | Description |
|--------|-------------|
| `blank` | All cells empty |
| `formula_only` | Cells contain only Excel formulas, no user data |
| `template_control_row` | "Default Row:" prefix, or all cells are required/optional/additional status keywords |
| `metadata` | All cells are data-type keywords (Text, Select, Number, URL, …) |
| `instruction_or_note` | Long instruction text (> 100 chars) or starts with instruction prefix |
| `sample_candidate` | Placeholder values like "N/A", "Enter …", artificial SKU patterns |
| `existing_product` | Short non-placeholder identifier in a known identifier column (SKU, MPN, EAN, ASIN, …) |
| `separator` | Single non-empty cell in a wide sheet |
| `unknown` | Does not match any above |

### Identifier recognition rules

A cell is treated as a real product identifier only when:
- It appears in a known identifier column (Supplier Part Number, SKU, MPN, EAN, ASIN, …)
- Its value is ≤ 100 characters (real identifiers are short; instructions are not)
- It does not match sample-text patterns (`N/A`, `Enter …`, `Example …`, `Sample …`, `_ARTIFICIAL_…`)
- It does not match instruction prefixes (`enter`, `must`, `please`, `the`, …)

---

## E. Write Policy System (Phase 3)

`app/autofill/write_policy.py` converts row classifications into a `WritePlan` before any cells are touched.

| Policy | Behaviour |
|--------|-----------|
| `append` _(default)_ | Find last `existing_product` row; append after it. If none, use first blank after the last non-blank template row. |
| `fill-first-blank` | Write starting at the first `blank` row found. |
| `replace-samples` | Overwrite `sample_candidate` rows; append overflow after them. |
| `replace-all-products` | Overwrite `existing_product` rows; append overflow. **Requires explicit user selection.** |
| `preview-only` | Compute the plan but write nothing; produces a preview CSV only. |

`WritePlan` carries: `policy`, `target_rows`, `first_write_row`, `existing_product_rows`, `sample_rows`, `blank_rows`, `is_preview`, `warnings`.

---

## F. Template Registration System (Phase 4A)

### Purpose classification

`app/analyser/purpose_classifier.py` classifies each workbook using multi-signal scoring — never from filename alone.

| Purpose | Meaning |
|---------|---------|
| `fillable_template` | Blank upload template; safe to auto-fill |
| `reference_workbook` | Populated data file; blocking — not for auto-fill |
| `instruction_workbook` | Guidance-only; no usable listing sheet |
| `mixed_workbook` | Both listing structure and reference content; requires human confirmation |
| `unsupported` | No recognisable structure |
| `requires_review` | Structurally ambiguous; human confirmation needed |

Key signals used: listing-sheet confidence, header-detection confidence, column count, rows-below-header (data density proxy), instruction/reference sheet count, row classification summary (existing_product_count, sample_count, metadata_row_count, template_control_count).

### Fill status

`app/analyser/fill_status.py` determines the final fill decision. Only specific blocking reasons prevent filling:

| Blocking condition | Finding code |
|--------------------|--------------|
| Purpose is reference/instruction/unsupported | `PURPOSE_NOT_FILLABLE` |
| No listing sheet detected | `NO_LISTING_SHEET` |
| Header row not detected | `NO_HEADER_DETECTION` |
| Header confidence < 0.40 | `LOW_HEADER_CONFIDENCE` |
| No columns extracted | `NO_COLUMNS_DETECTED` |
| Duplicate headers present | `DUPLICATE_HEADERS` |

Non-blocking findings (warnings/review_required): provisional category, partial `analysis_status`, unknown sheet types, mixed_workbook purpose. A `partial` analysis_status is **never** a blocking reason.

### Finding severity levels

`info` → `warning` → `review_required` → `blocking`

Only `blocking` findings produce `not_fillable`. Only `review_required` findings produce `requires_review`.

### Template registry

`app/analyser/template_registry.py` persists all registered templates at `outputs/template_registry/`.

- **Idempotent by SHA-256 hash** — re-uploading the same file returns the existing entry without duplication.
- **Supersession by filename** — uploading a new version of a file marks the previous entry `is_superseded=True`, `is_active=False`.
- Persisted as both `template_registry.json` (full detail) and `template_registry.csv` (tabular summary).

---

## G. Integration Results — All 11 Templates

Registration run: 2026-07-15

| Template ID | Filename | Listing Sheet | Header Row | Safe Write Row | Purpose | Fill Status |
|-------------|----------|---------------|-----------|----------------|---------|-------------|
| tpl_7d54ede76698 | Chandeliers.xlsx | 6085 - Chandeliers | 4 | 8 | fillable_template | fillable_with_warnings |
| tpl_3c78a5836df8 | Flush Mount Lighting.xlsx | 6086 - Flush Mount Lighting | 4 | 8 | fillable_template | fillable_with_warnings |
| tpl_1178015fc3f4 | Lampshades.xlsx | 180 - Lamp Shades | 4 | 8 | fillable_template | fillable_with_warnings |
| tpl_4c73938ac8d3 | Light Bulbs.xlsx | 338 - Light Bulbs | 4 | 8 | fillable_template | fillable_with_warnings |
| tpl_3a2846bc63af | Lighting Accessories.xlsx | 269 - Lighting Accessories | 4 | 8 | fillable_template | fillable_with_warnings |
| tpl_e05b3494b3c6 | Pendant Light Listing – Attribute Instructions.xlsx | listing template | 1 | 10 | mixed_workbook | requires_review |
| tpl_ee60db9ddb63 | Pendant Lightt.xlsx | 6087 - Pendant Lights | 4 | 8 | fillable_template | fillable_with_warnings |
| tpl_5d4476340ccc | Switches, Dimmers & Outlets.xlsx | 3719 - Switches, Dimmers & Outlets | 4 | 8 | fillable_template | fillable_with_warnings |
| tpl_ce29a4de06d4 | Table Lamps.xlsx | 6449 - Table Lamps | 4 | 8 | fillable_template | fillable_with_warnings |
| tpl_9df34746483e | Transformers.xlsx | 1245 - Transformers | 4 | 8 | fillable_template | fillable_with_warnings |
| tpl_439c6642e760 | Wall Sconces.xlsx | 6117 - Wall Sconces | 4 | 8 | fillable_template | fillable_with_warnings |

**Summary:**
- Analysed: 11 / 11
- Fillable with warnings: 10
- Requires review: 1
- Not fillable: 0
- Failed: 0

**Notes:**
- All 10 blank listing templates have `fillable_with_warnings` because their category names are derived from filenames (provisional), not confirmed category IDs. This is a warning, not a block.
- Category resolution is `resolved` for templates whose listing sheet name carries a Wayfair numeric prefix (e.g. `6085 - Chandeliers`). The provisional-category warning exists because the registry does not yet have a category-ID confirmation step — it is safe to suppress per-template once the category is confirmed.
- Pendant Light Listing – Attribute Instructions is correctly classified as `mixed_workbook` / `requires_review`. It contains a listing-structured sheet with 141 columns alongside instruction sheets, and its header is at row 1 (no standard core:: key rows), consistent with it being a reference document rather than a blank upload template.
- Total listing columns across all 11 profiles: **1,342**.

---

## H. Test Suite

| Test file | Tests | Coverage area |
|-----------|-------|---------------|
| `test_autofill.py` | 55 | Source reader, transformer, mapper, validator, writer, row detector, write policy, engine row detection |
| `test_phase4a.py` | 33 | Finding helpers, purpose classifier, fill status, template registry CRUD/persistence, row detector Phase 4A types, registration workflow end-to-end |
| `test_analyser.py` | 22 | Header detection, column metadata extraction |
| `test_sheet_classification.py` | 14 | Sheet type classification |
| `test_valid_values.py` | 5 | Valid value table extraction |
| `test_header_detection.py` | 9 | Header detection edge cases |

**Total: 138 / 138 passing.**

Run: `python -m pytest`

---

## I. CLI Reference

```
# Register a single template
python -m app.cli register-template \
  --template path/to/template.xlsx \
  --profile-dir outputs/template_profiles \
  --registry-dir outputs/template_registry

# Register all templates in a directory
python -m app.cli register-templates \
  --input-dir path/to/templates/ \
  --profile-dir outputs/template_profiles \
  --registry-dir outputs/template_registry

# Fill templates (registry-aware)
python -m app.cli fill-templates \
  --template-dir path/to/templates/ \
  --source source_data.csv \
  --profile-dir outputs/template_profiles \
  --output-dir outputs/filled/ \
  --write-policy append \
  --registry outputs/template_registry/template_registry.json \
  [--include-template-id tpl_abc123 tpl_def456] \
  [--exclude-template-id tpl_xyz789] \
  [--allow-review-required]

# Analyse a single template (no fill)
python -m app.cli analyse-template --template path/to/template.xlsx --output-dir outputs/

# Fill a single template
python -m app.cli fill-template \
  --template path/to/template.xlsx \
  --source source_data.csv \
  --profile outputs/template_profiles/category.json \
  --output-dir outputs/filled/ \
  --write-policy append
```

**Write policy values:** `append` (default), `fill-first-blank`, `replace-samples`, `replace-all-products`, `preview-only`

**Registry-based fill filtering:**
- Templates with `fill_status=not_fillable` are always skipped.
- Templates with `fill_status=requires_review` are skipped unless `--allow-review-required` is passed.
- Templates with `fill_status=fillable` or `fillable_with_warnings` are included by default.

---

## J. Known Limitations and Future Work

| Item | Note |
|------|------|
| Category confirmation | All 10 fillable templates carry a `PROVISIONAL_CATEGORY` warning. A category-confirmation step (mapping filename/sheet-name prefix to a confirmed Wayfair category ID) would promote these to `fillable` and eliminate the warnings. |
| Pendant Light Attribute Instructions | Classified correctly as `requires_review`. If this workbook has a valid blank listing sheet inside it that should be filled, it needs a manual `--allow-review-required` override or the listing sheet name needs to be explicitly configured. |
| Sheet-type misclassification of auxiliary sheets | Sheets named "Additional Images", "Additional Cartons", etc. are classified as `listing` type by the sheet classifier because they have a tabular structure. This does not affect fill correctness (the inspector always selects the highest-confidence listing sheet), but it inflates the listing-candidate count. A name-based override in the sheet classifier would clean this up. |
| `analysis_status = partial` on all templates | Every template has one or more non-critical warnings (e.g. sheet classification edge cases), resulting in `partial` status. Per design, `partial` is informational and does not block filling. |
