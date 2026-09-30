"""
Auto-fill engine: orchestrates read -> map -> validate -> write -> report.

Row positions are detected dynamically from the actual template file.
No row numbers are hardcoded anywhere in this module.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from app.autofill.source_reader import read_source
from app.autofill.mapper import load_mappings, resolve_row, MappingResult, _norm
from app.autofill.validator import validate_row, ValidationIssue
from app.autofill.writer import write_filled_template, WriteResult
from app.autofill.fill_report import write_fill_report
from app.autofill.row_detector import classify_data_area
from app.autofill.write_policy import build_write_plan, WritePlan, DEFAULT_POLICY


@dataclass
class FillEngineResult:
    write_result: WriteResult | None
    all_issues: list[ValidationIssue]
    report_paths: dict[str, Path]
    error: str | None = None


def _load_profile(profile_path: Path) -> dict:
    return json.loads(profile_path.read_text(encoding="utf-8"))


def _get_valid_values_map(profile: dict) -> dict[str, list[str]]:
    """Build norm_field -> [values] from the profile's valid_value_tables."""
    vv: dict[str, list[str]] = {}
    for sheet in profile.get("sheets", []):
        for vt in sheet.get("valid_value_tables", []):
            key = _norm(vt["field_name"])
            vv.setdefault(key, []).extend(vt.get("values", []))
    return vv


def _get_char_limits(profile: dict) -> dict[str, int]:
    """Build norm_field -> char_limit from listing sheet column metadata."""
    limits: dict[str, int] = {}
    listing = profile.get("listing_sheet")
    if not listing:
        return limits
    for sheet in profile.get("sheets", []):
        if sheet["name"] == listing:
            for col in sheet.get("columns", []):
                if col.get("char_limit"):
                    limits[_norm(col["original_header"])] = col["char_limit"]
    return limits


def _detect_write_plan(
    template_path: Path,
    listing_sheet_name: str,
    header_row: int,
    max_col: int,
    incoming_count: int,
    policy: str,
) -> WritePlan:
    """
    Open the template read-only, classify all rows below the header, and
    return a WritePlan. Never modifies the original file.
    """
    wb = openpyxl.load_workbook(str(template_path), read_only=True, data_only=True)
    try:
        if listing_sheet_name not in wb.sheetnames:
            raise ValueError(f"Sheet {listing_sheet_name!r} not found in {template_path.name}")
        ws = wb[listing_sheet_name]

        # Build col_map from the header row
        col_map: dict[str, int] = {}
        for c in range(1, max_col + 1):
            cell = ws.cell(header_row, c)
            if cell.value is not None:
                h = str(cell.value).strip()
                if h and h not in col_map:
                    col_map[h] = c

        # ws.max_row is None in read_only mode; pass None so classify_data_area
        # uses its own scan-limit fallback instead of clamping to row 0.
        ws_max_row = ws.max_row if (ws.max_row and ws.max_row > header_row) else None
        classifications = classify_data_area(
            ws=ws,
            header_row=header_row,
            col_map=col_map,
            max_row=ws_max_row,
        )
    finally:
        wb.close()

    return build_write_plan(classifications, policy, incoming_count)


def run_fill(
    template_path: Path,
    source_path: Path,
    profile_path: Path,
    output_dir: Path,
    report_dir: Path,
    config_dir: Path,
    write_policy: str = DEFAULT_POLICY,
) -> FillEngineResult:
    """
    Full pipeline for one template + one source file.
    """
    # ── Load profile ──────────────────────────────────────────────────────
    try:
        profile = _load_profile(profile_path)
    except Exception as e:
        return FillEngineResult(None, [], {}, error=f"Cannot load profile: {e}")

    category_name = profile.get("category_name", template_path.stem)
    listing_sheet = profile.get("listing_sheet")
    if not listing_sheet:
        return FillEngineResult(None, [], {}, error="No listing sheet in profile")

    # Find listing sheet details
    listing_max_col = 0
    listing_header_row = 4
    wayfair_headers: list[str] = []

    for sheet in profile.get("sheets", []):
        if sheet["name"] == listing_sheet:
            listing_max_col = sheet.get("max_col", 0)
            det = sheet.get("header_detection") or {}
            listing_header_row = det.get("header_row", 4)
            wayfair_headers = profile.get("exact_headers", [])
            break

    if not wayfair_headers:
        return FillEngineResult(None, [], {}, error="No headers found in profile")

    valid_values_map = _get_valid_values_map(profile)
    char_limits = _get_char_limits(profile)

    # ── Load mapping rules ─────────────────────────────────────────────────
    try:
        rules, fixed_rules = load_mappings(config_dir)
    except Exception as e:
        return FillEngineResult(None, [], {}, error=f"Cannot load mappings: {e}")

    # ── Read source ───────────────────────────────────────────────────────
    try:
        source_rows = read_source(source_path)
    except Exception as e:
        return FillEngineResult(None, [], {}, error=f"Cannot read source: {e}")

    if not source_rows:
        return FillEngineResult(None, [], {}, error="Source file is empty")

    # ── Map + Validate ────────────────────────────────────────────────────
    all_mapped: list[list[MappingResult]] = []
    all_issues: list[ValidationIssue] = []

    for row_idx, src_row in enumerate(source_rows):
        mapped = resolve_row(src_row, rules, fixed_rules, category_name, wayfair_headers)
        all_mapped.append(mapped)

        sku = next((mr.final_value for mr in mapped
                    if mr.wayfair_field == "Supplier Part Number"), f"row_{row_idx+1}")
        issues = validate_row(mapped, row_idx, sku, valid_values_map, char_limits)
        all_issues.extend(issues)

    # ── Detect row positions dynamically ─────────────────────────────────
    try:
        write_plan = _detect_write_plan(
            template_path=template_path,
            listing_sheet_name=listing_sheet,
            header_row=listing_header_row,
            max_col=listing_max_col,
            incoming_count=len(all_mapped),
            policy=write_policy,
        )
    except Exception as e:
        return FillEngineResult(None, all_issues, {}, error=f"Row detection failed: {e}")

    # ── Write template ────────────────────────────────────────────────────
    try:
        write_result = write_filled_template(
            template_path=template_path,
            output_dir=output_dir,
            category_name=category_name,
            listing_sheet_name=listing_sheet,
            header_row=listing_header_row,
            write_plan=write_plan,
            max_col=listing_max_col,
            mapped_rows=all_mapped,
        )
    except Exception as e:
        return FillEngineResult(None, all_issues, {}, error=f"Write failed: {e}")

    # ── Report ────────────────────────────────────────────────────────────
    report_paths = write_fill_report(
        write_result=write_result,
        all_mapped_rows=all_mapped,
        all_issues=all_issues,
        source_path=source_path,
        output_dir=report_dir,
    )

    return FillEngineResult(
        write_result=write_result,
        all_issues=all_issues,
        report_paths=report_paths,
    )
