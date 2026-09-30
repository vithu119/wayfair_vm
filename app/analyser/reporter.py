"""
Generate CSV and Markdown reports from analysed profiles.
"""
from __future__ import annotations
import csv
import re
from pathlib import Path
from datetime import datetime, timezone

from app.analyser.inspector import WorkbookProfile
from app.analyser.comparator import ComparisonResult


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_category_summary(profiles: list[WorkbookProfile], output_dir: Path) -> Path:
    rows = []
    for p in profiles:
        ls = p.listing_sheet
        rows.append({
            "Category": p.category_name,
            "Workbook": p.source_file,
            "Status": p.analysis_status,
            "Sheet Count": len(p.sheets),
            "Listing Sheet": ls.name if ls else "",
            "Header Count": len(ls.columns) if ls else 0,
            "Header Row": ls.detection.header_row if ls and ls.detection else "",
            "Required Fields": sum(1 for c in ls.columns if c.required_status.lower() == "required") if ls else 0,
            "Controlled Fields": sum(1 for c in ls.columns if c.is_controlled) if ls else 0,
            "Valid Value Sheets": "; ".join(s.name for s in p.valid_value_sheets),
            "Image Sheets": "; ".join(s.name for s in p.image_sheets),
            "Document Sheets": "; ".join(s.name for s in p.document_sheets),
            "Instruction Sheets": "; ".join(s.name for s in p.instruction_sheets),
            "Warning Count": len(p.warnings),
            "Error Count": len(p.errors),
            "File Hash (SHA-256)": p.file_hash,
        })
    path = output_dir / "category_template_summary.csv"
    _write_csv(path, rows)
    return path


def write_field_comparison(profiles: list[WorkbookProfile], comparison: ComparisonResult, output_dir: Path) -> Path:
    rows = []
    # Shared by all
    for h in comparison.shared_by_all:
        rows.append({
            "Field (normalized)": h,
            "Scope": "shared_by_all",
            "Categories": "ALL",
            "Category Count": len(profiles),
        })
    # Shared by some
    for h, cats in sorted(comparison.shared_by_some.items()):
        rows.append({
            "Field (normalized)": h,
            "Scope": "shared_by_some",
            "Categories": "; ".join(sorted(cats)),
            "Category Count": len(cats),
        })
    # Unique per category
    for cat, headers in sorted(comparison.unique_per_category.items()):
        for h in headers:
            rows.append({
                "Field (normalized)": h,
                "Scope": "unique",
                "Categories": cat,
                "Category Count": 1,
            })

    path = output_dir / "category_field_comparison.csv"
    _write_csv(path, rows)
    return path


def write_unmapped_fields(profiles: list[WorkbookProfile], output_dir: Path) -> Path:
    rows = []
    for p in profiles:
        if not p.listing_sheet:
            continue
        for col in p.listing_sheet.columns:
            if col.mapping_status == "unmapped":
                rows.append({
                    "Category": p.category_name,
                    "Workbook": p.source_file,
                    "Sheet": col.sheet_name,
                    "Column Position": col.column_position,
                    "Original Header": col.original_header,
                    "Normalized Header": col.normalized_header,
                    "Required Status": col.required_status,
                    "Is Controlled": col.is_controlled,
                    "Data Type": col.data_type,
                    "Recommended Action": (
                        "manual_review" if not col.original_header
                        else "map_or_skip"
                    ),
                })
    path = output_dir / "unmapped_fields.csv"
    _write_csv(path, rows)
    return path


def write_validation_findings(profiles: list[WorkbookProfile], output_dir: Path) -> Path:
    rows = []
    for p in profiles:
        for w in p.warnings:
            rows.append({
                "Category": p.category_name,
                "Workbook": p.source_file,
                "Sheet": "",
                "Finding Type": "warning",
                "Detail": w,
                "Confidence": "",
                "Recommended Action": "review",
            })
        for e in p.errors:
            rows.append({
                "Category": p.category_name,
                "Workbook": p.source_file,
                "Sheet": "",
                "Finding Type": "error",
                "Detail": e,
                "Confidence": "",
                "Recommended Action": "investigate",
            })
        # Low-confidence sheets
        for s in p.sheets:
            if s.classification.confidence < 0.5:
                rows.append({
                    "Category": p.category_name,
                    "Workbook": p.source_file,
                    "Sheet": s.name,
                    "Finding Type": "low_confidence_classification",
                    "Detail": f"type={s.classification.sheet_type} conf={s.classification.confidence}",
                    "Confidence": s.classification.confidence,
                    "Recommended Action": "manual_review",
                })
        # Duplicate headers
        if p.listing_sheet:
            for col in p.listing_sheet.columns:
                if col.is_duplicate_header:
                    rows.append({
                        "Category": p.category_name,
                        "Workbook": p.source_file,
                        "Sheet": col.sheet_name,
                        "Finding Type": "duplicate_header",
                        "Detail": f"col {col.column_position}: {col.original_header!r}",
                        "Confidence": 1.0,
                        "Recommended Action": "review_template",
                    })

    path = output_dir / "validation_findings.csv"
    _write_csv(path, rows)
    return path


def write_markdown_report(
    profiles: list[WorkbookProfile],
    comparison: ComparisonResult,
    integrity_results: dict[str, str],
    output_dir: Path,
) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Wayfair Template Analysis Report",
        f"\n_Generated: {ts}_\n",
        "## Summary",
        "",
        f"| Item | Count |",
        f"|------|-------|",
        f"| Workbooks analysed | {len(profiles)} |",
        f"| Successful | {sum(1 for p in profiles if p.analysis_status == 'ok')} |",
        f"| Partial (warnings) | {sum(1 for p in profiles if p.analysis_status == 'partial')} |",
        f"| Failed | {sum(1 for p in profiles if p.analysis_status == 'failed')} |",
        f"| Total unique (exact) headers | {_count_unique_exact(profiles)} |",
        f"| Shared by all categories | {len(comparison.shared_by_all)} |",
        f"| Unique to one category (total) | {sum(len(v) for v in comparison.unique_per_category.values())} |",
        f"| Required fields detected | {_count_required(profiles)} |",
        f"| Controlled fields detected | {_count_controlled(profiles)} |",
        f"| Fuzzy match suggestions | {len(comparison.fuzzy_suggestions)} |",
        "",
    ]

    # Per-workbook
    lines += ["## Per-Workbook Results", ""]
    for p in profiles:
        ls = p.listing_sheet
        lines += [
            f"### {p.category_name}",
            f"- **File:** `{p.source_file}`",
            f"- **Status:** {p.analysis_status}",
            f"- **Sheets:** {len(p.sheets)}",
            f"- **Listing sheet:** {ls.name if ls else 'NOT DETECTED'}",
            f"- **Header row:** {ls.detection.header_row if ls and ls.detection else 'n/a'}",
            f"- **Header count:** {len(ls.columns) if ls else 0}",
            f"- **Required fields:** {sum(1 for c in ls.columns if c.required_status.lower() == 'required') if ls else 0}",
            f"- **Controlled fields:** {sum(1 for c in ls.columns if c.is_controlled) if ls else 0}",
            f"- **Valid value sheets:** {', '.join(s.name for s in p.valid_value_sheets) or 'none'}",
            f"- **Image sheets:** {', '.join(s.name for s in p.image_sheets) or 'none'}",
            f"- **Document sheets:** {', '.join(s.name for s in p.document_sheets) or 'none'}",
            f"- **Warnings:** {len(p.warnings)}",
            "",
        ]
        if ls:
            lines.append("<details><summary>Exact listing headers (in order)</summary>")
            lines.append("")
            lines.append("| # | Header | Required | Controlled | Data Type |")
            lines.append("|---|--------|----------|------------|-----------|")
            for col in ls.columns:
                if col.original_header:
                    lines.append(
                        f"| {col.column_position} | {col.original_header} | {col.required_status} "
                        f"| {'Yes' if col.is_controlled else 'No'} | {col.data_type} |"
                    )
            lines.append("</details>")
            lines.append("")

    # Shared fields
    lines += [
        "## Fields Shared by All Categories",
        "",
        f"Total: {len(comparison.shared_by_all)}",
        "",
    ]
    if comparison.shared_by_all:
        lines += ["| Field |", "|-------|"]
        for h in comparison.shared_by_all[:50]:
            lines.append(f"| {h} |")
        if len(comparison.shared_by_all) > 50:
            lines.append(f"| _…and {len(comparison.shared_by_all) - 50} more_ |")
        lines.append("")

    # Fuzzy suggestions
    lines += [
        "## Fuzzy Header Match Suggestions",
        "",
        "> **These are suggestions only. Do not accept automatically. Human review required.**",
        "",
    ]
    if comparison.fuzzy_suggestions:
        lines += ["| Category A | Header A | Category B | Header B | Similarity |",
                  "|------------|----------|------------|----------|------------|"]
        for fm in comparison.fuzzy_suggestions[:50]:
            lines.append(f"| {fm.category_a} | {fm.header_a} | {fm.category_b} | {fm.header_b} | {fm.similarity} |")
        lines.append("")

    # Integrity
    lines += ["## Original File Integrity (SHA-256)", ""]
    lines += ["| File | Status |", "|------|--------|"]
    for fname, status in sorted(integrity_results.items()):
        icon = "✓" if status == "unchanged" else "✗"
        lines.append(f"| {fname} | {icon} {status} |")
    lines.append("")

    path = output_dir / "template_analysis_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _count_unique_exact(profiles: list[WorkbookProfile]) -> int:
    seen: set[str] = set()
    for p in profiles:
        if p.listing_sheet:
            for col in p.listing_sheet.columns:
                if col.original_header:
                    seen.add(col.original_header)
    return len(seen)


def _count_required(profiles: list[WorkbookProfile]) -> int:
    return sum(
        sum(1 for c in p.listing_sheet.columns if c.required_status.lower() == "required")
        for p in profiles if p.listing_sheet
    )


def _count_controlled(profiles: list[WorkbookProfile]) -> int:
    return sum(
        sum(1 for c in p.listing_sheet.columns if c.is_controlled)
        for p in profiles if p.listing_sheet
    )
