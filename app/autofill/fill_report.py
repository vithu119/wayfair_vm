"""
Generate per-fill CSV and Markdown reports, plus row_classification.csv
and write_plan.csv for Phase 3 auditing.
"""
from __future__ import annotations
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from app.autofill.mapper import MappingResult
from app.autofill.validator import ValidationIssue
from app.autofill.writer import WriteResult

if TYPE_CHECKING:
    from app.autofill.write_policy import WritePlan
    from app.autofill.row_detector import RowClassification


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_fill_report(
    write_result: WriteResult,
    all_mapped_rows: list[list[MappingResult]],
    all_issues: list[ValidationIssue],
    source_path: Path,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    safe_cat = write_result.category_name.replace(" ", "_").replace("/", "_")

    # ── Mapping detail CSV ────────────────────────────────────────────────
    mapping_rows = []
    for row_idx, mr_list in enumerate(all_mapped_rows):
        sku = next((mr.final_value for mr in mr_list
                    if mr.wayfair_field == "Supplier Part Number"), f"row_{row_idx}")
        for mr in mr_list:
            mapping_rows.append({
                "Row": row_idx + 1,
                "SKU": sku,
                "Wayfair Field": mr.wayfair_field,
                "Source Field": mr.source_field or "",
                "Source Type": mr.source,
                "Raw Value": (mr.raw_value or "")[:120],
                "Final Value": (mr.final_value or "")[:120],
                "Transform": mr.transform_applied or "",
                "Is Empty": "Yes" if mr.is_empty else "No",
                "Is Required": "Yes" if mr.is_required else "No",
            })

    mapping_csv = output_dir / f"{safe_cat}_mapping_detail_{ts}.csv"
    _write_csv(mapping_csv, mapping_rows)

    # ── Validation issues CSV ─────────────────────────────────────────────
    issue_rows = [
        {
            "Row": issue.row_index + 1,
            "SKU": issue.sku,
            "Wayfair Field": issue.wayfair_field,
            "Issue Type": issue.issue_type,
            "Severity": issue.severity,
            "Detail": issue.detail,
            "Value": (issue.value or "")[:120],
        }
        for issue in all_issues
    ]
    issues_csv = output_dir / f"{safe_cat}_validation_{ts}.csv"
    _write_csv(issues_csv, issue_rows)

    # ── Write plan CSV ────────────────────────────────────────────────────
    wp = write_result.write_plan
    write_plan_rows = [
        {
            "Policy": wp.policy,
            "First Write Row": wp.first_write_row,
            "Target Rows": ";".join(str(r) for r in wp.target_rows),
            "Existing Product Rows": ";".join(str(r) for r in wp.existing_product_rows),
            "Sample Rows": ";".join(str(r) for r in wp.sample_rows),
            "Blank Rows (first 20)": ";".join(str(r) for r in wp.blank_rows[:20]),
            "Is Preview": "Yes" if wp.is_preview else "No",
            "Warnings": " | ".join(wp.warnings),
        }
    ]
    write_plan_csv = output_dir / f"{safe_cat}_write_plan_{ts}.csv"
    _write_csv(write_plan_csv, write_plan_rows)

    # ── Summary statistics ─────────────────────────────────────────────────
    total_fields = sum(len(mr_list) for mr_list in all_mapped_rows)
    mapped = sum(1 for mr_list in all_mapped_rows for mr in mr_list
                 if mr.source in ("source_data", "fixed_value") and not mr.is_empty)
    defaults = sum(1 for mr_list in all_mapped_rows for mr in mr_list
                   if mr.source == "default" and not mr.is_empty)
    unmapped = sum(1 for mr_list in all_mapped_rows for mr in mr_list if mr.is_empty)
    errors = [i for i in all_issues if i.severity == "error"]
    warnings_list = [i for i in all_issues if i.severity == "warning"]

    # ── Markdown report ───────────────────────────────────────────────────
    ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Fill Report -- {write_result.category_name}",
        f"\n_Generated: {ts_str}_\n",
        "## Summary",
        "",
        "| Item | Value |",
        "|------|-------|",
        f"| Category | {write_result.category_name} |",
        f"| Source file | `{source_path.name}` |",
        f"| Output file | `{write_result.output_path.name}` |",
        f"| Products written | {write_result.rows_written} |",
        f"| Total field slots | {total_fields} |",
        f"| Filled from source | {mapped} |",
        f"| Filled from defaults | {defaults} |",
        f"| Empty (unmapped) | {unmapped} |",
        f"| Validation errors | {len(errors)} |",
        f"| Validation warnings | {len(warnings_list)} |",
        "",
    ]

    # ── Write plan section ─────────────────────────────────────────────────
    lines += [
        "## Write Plan",
        "",
        "| Item | Value |",
        "|------|-------|",
        f"| Policy | `{wp.policy}` |",
        f"| First write row | {wp.first_write_row} |",
        f"| Target rows | {', '.join(str(r) for r in wp.target_rows[:10])}"
        + (" ..." if len(wp.target_rows) > 10 else "") + " |",
        f"| Existing product rows found | {len(wp.existing_product_rows)} |",
        f"| Sample/placeholder rows found | {len(wp.sample_rows)} |",
        f"| Blank rows found | {len(wp.blank_rows)} |",
        f"| Preview only | {'Yes' if wp.is_preview else 'No'} |",
        "",
    ]

    if wp.warnings:
        lines += ["### Write Plan Warnings", ""]
        for w in wp.warnings:
            lines.append(f"- {w}")
        lines.append("")

    if errors:
        lines += ["## Errors (must fix before submission)", ""]
        for e in errors:
            lines.append(f"- **Row {e.row_index+1} / {e.sku}** -- `{e.wayfair_field}`: {e.detail}")
        lines.append("")

    if warnings_list:
        lines += ["## Warnings (review recommended)", ""]
        for w in warnings_list[:50]:
            lines.append(f"- Row {w.row_index+1} / {w.sku} -- `{w.wayfair_field}`: {w.detail}")
        if len(warnings_list) > 50:
            lines.append(f"- _...and {len(warnings_list)-50} more warnings (see CSV)_")
        lines.append("")

    if write_result.warnings:
        lines += ["## Writer Warnings", ""]
        for ww in write_result.warnings:
            lines.append(f"- {ww}")
        lines.append("")

    md_path = output_dir / f"{safe_cat}_fill_report_{ts}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "mapping_detail": mapping_csv,
        "validation": issues_csv,
        "write_plan": write_plan_csv,
        "report": md_path,
    }
