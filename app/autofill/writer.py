"""
Template writer: copies the original Wayfair template, then writes mapped
product rows into the target rows determined by WritePlan.

The original template is never modified. Data rows are written only to the
rows specified by write_plan.target_rows. Row selection is the write-policy
engine's responsibility; this module only writes.
"""
from __future__ import annotations
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
from openpyxl.worksheet.datavalidation import DataValidation

from app.autofill.mapper import MappingResult
from app.autofill.write_policy import WritePlan

VALID_VALUES_SHEET = "Valid Values"


def _read_valid_values(wb: openpyxl.Workbook) -> dict[str, list[str]]:
    """Read the Valid Values sheet and return {column_header: [valid_options]}."""
    if VALID_VALUES_SHEET not in wb.sheetnames:
        return {}
    ws = wb[VALID_VALUES_SHEET]
    result: dict[str, list[str]] = {}
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    for col_idx, header in enumerate(headers, 1):
        if not header:
            continue
        values = [
            str(ws.cell(r, col_idx).value).strip()
            for r in range(2, ws.max_row + 1)
            if ws.cell(r, col_idx).value not in (None, "")
        ]
        if values:
            result[str(header).strip()] = values
    return result


def _col_letter(col: int) -> str:
    """Convert 1-based column index to Excel letter(s)."""
    letters = ""
    while col > 0:
        col, remainder = divmod(col - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _build_value_to_col_map(ws, max_col: int) -> dict[str, int]:
    """Scan every cell in the header area (rows 1–20) and return {cell_value: col_1based}.
    When the same text appears in multiple columns, the first occurrence wins.
    This is row-order agnostic — works regardless of template format."""
    result: dict[str, int] = {}
    for r in range(1, 21):
        for c in range(1, max_col + 1):
            v = ws.cell(r, c).value
            if v and isinstance(v, str):
                key = v.strip()
                if key and key not in result:
                    result[key] = c
    return result


def _apply_dropdowns(
    ws,
    valid_values: dict[str, list[str]],
    col_map: dict[str, int],
    first_row: int,
    last_row: int,
) -> None:
    """Add dropdown DataValidation for each Valid Values column that exists in the listing sheet."""
    # Build a value→col map by scanning all header-area cells — row-order agnostic
    value_col_map = _build_value_to_col_map(ws, ws.max_column)

    for header, options in valid_values.items():
        # Match by exact name anywhere in the header area, fall back to writer's col_map
        col = value_col_map.get(header) or col_map.get(header)
        if col is None:
            continue
        # Excel formula1 for list validation: comma-separated quoted values (max ~255 chars)
        # For long lists, use a quoted comma-separated string truncated to fit
        joined = ",".join(f'"{v}"' for v in options)
        if len(joined) > 255:
            # Too long for inline list — skip (template's own WAYFAIR_USE_ONLY ref still applies)
            continue
        col_l = _col_letter(col)
        sqref = f"{col_l}{first_row}:{col_l}{last_row}"
        dv = DataValidation(
            type="list",
            formula1=joined,
            allow_blank=True,
            showErrorMessage=False,  # warn only, don't block entry
        )
        dv.sqref = sqref
        ws.add_data_validation(dv)


@dataclass
class WriteResult:
    output_path: Path
    category_name: str
    rows_written: int
    write_plan: WritePlan
    warnings: list[str] = field(default_factory=list)


def _find_listing_sheet(
    wb: openpyxl.Workbook,
    listing_sheet_name: str,
) -> openpyxl.worksheet.worksheet.Worksheet:
    if listing_sheet_name in wb.sheetnames:
        return wb[listing_sheet_name]
    raise ValueError(f"Listing sheet {listing_sheet_name!r} not found in workbook")


def _build_header_to_col_map(ws, header_row: int, max_col: int) -> dict[str, int]:
    """Return {exact_header: column_index_1based}."""
    mapping: dict[str, int] = {}
    for c in range(1, max_col + 1):
        v = ws.cell(header_row, c).value
        if v is not None:
            h = str(v).strip()
            if h and h not in mapping:
                mapping[h] = c
    return mapping


def write_filled_template(
    template_path: Path,
    output_dir: Path,
    category_name: str,
    listing_sheet_name: str,
    header_row: int,       # 1-based; detected from profile
    write_plan: WritePlan,
    max_col: int,
    mapped_rows: list[list[MappingResult]],   # one list per product row
) -> WriteResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    safe_cat = category_name.replace(" ", "_").replace("/", "_")
    out_name = f"{safe_cat}_filled_{ts}.xlsx"
    out_path = output_dir / out_name

    # Copy original — never write to the original template
    shutil.copy2(template_path, out_path)

    result = WriteResult(
        output_path=out_path,
        category_name=category_name,
        rows_written=0,
        write_plan=write_plan,
    )

    if write_plan.is_preview:
        # Preview-only: return the result without writing any cells
        result.warnings.append("preview-only mode: no cells were written")
        result.rows_written = 0
        return result

    # Validate we have enough target rows
    if len(write_plan.target_rows) < len(mapped_rows):
        result.warnings.append(
            f"write_plan has {len(write_plan.target_rows)} target rows "
            f"but {len(mapped_rows)} incoming rows; extra rows will be appended."
        )

    # Open copy for writing (not data_only — preserve formulas and styles)
    wb = openpyxl.load_workbook(str(out_path))
    ws = _find_listing_sheet(wb, listing_sheet_name)

    col_map = _build_header_to_col_map(ws, header_row, max_col)
    valid_values = _read_valid_values(wb)

    for row_idx, mr_list in enumerate(mapped_rows):
        # Use the write plan's target row if available; otherwise extend sequentially
        if row_idx < len(write_plan.target_rows):
            excel_row = write_plan.target_rows[row_idx]
        else:
            last_target = write_plan.target_rows[-1] if write_plan.target_rows else write_plan.first_write_row
            excel_row = last_target + (row_idx - len(write_plan.target_rows) + 1)

        for mr in mr_list:
            if mr.is_empty:
                continue
            col = col_map.get(mr.wayfair_field)
            if col is None:
                result.warnings.append(
                    f"Row {excel_row}: header {mr.wayfair_field!r} not found in col map — skipped"
                )
                continue
            ws.cell(excel_row, col).value = mr.final_value

        result.rows_written += 1

    # Apply dropdown validation to all written rows from Valid Values sheet
    if valid_values and write_plan.target_rows:
        first_written = write_plan.target_rows[0]
        last_written = write_plan.target_rows[-1] if len(write_plan.target_rows) <= len(mapped_rows) \
            else write_plan.target_rows[len(mapped_rows) - 1]
        _apply_dropdowns(ws, valid_values, col_map, first_written, last_written)

    wb.save(str(out_path))
    wb.close()

    return result
