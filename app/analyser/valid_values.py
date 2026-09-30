"""
Extract valid-value tables from Wayfair 'Valid Values' sheets.

The Valid Values sheet in standard Wayfair templates is structured as:
  Row 1: column headers (each header = a listing-field name that has controlled values)
  Row 2+: the approved values for each field (different columns may have different lengths)

Rows beyond max valid values in each column are empty.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field


@dataclass
class ValidValueTable:
    source_sheet: str
    field_name: str           # exact header from valid-values sheet
    normalized_field: str
    values: list[str]
    column_position: int
    cell_range: str           # e.g. "C2:C45"
    ambiguous: bool = False
    ambiguity_notes: str = ""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).lower() if s else ""


def _cell_str(ws, row: int, col: int) -> str:
    v = ws.cell(row, col).value
    return str(v).strip() if v is not None else ""


def extract_valid_values(ws, sheet_name: str, max_col: int, max_row: int) -> list[ValidValueTable]:
    """
    Detect the header row dynamically, then extract one ValidValueTable per column.
    """
    if max_col < 1 or max_row < 2:
        return []

    # Find header row: first row where most cells are non-empty short strings
    header_row = 1
    for r in range(1, min(5, max_row + 1)):
        vals = [_cell_str(ws, r, c) for c in range(1, max_col + 1)]
        populated = [v for v in vals if v]
        if len(populated) >= max(1, max_col // 4):
            header_row = r
            break

    tables: list[ValidValueTable] = []
    from openpyxl.utils import get_column_letter

    for c in range(1, max_col + 1):
        field_name = _cell_str(ws, header_row, c)
        if not field_name:
            continue

        values: list[str] = []
        last_data_row = header_row
        for r in range(header_row + 1, max_row + 1):
            v = _cell_str(ws, r, c)
            if v:
                values.append(v)
                last_data_row = r

        if not values:
            continue

        col_letter = get_column_letter(c)
        cell_range = f"{col_letter}{header_row + 1}:{col_letter}{last_data_row}"

        tables.append(ValidValueTable(
            source_sheet=sheet_name,
            field_name=field_name,
            normalized_field=_norm(field_name),
            values=values,
            column_position=c,
            cell_range=cell_range,
        ))

    return tables
