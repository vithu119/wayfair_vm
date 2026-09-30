"""
Per-workbook inspector: opens a workbook read-only and produces a WorkbookProfile.
"""
from __future__ import annotations
import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

from app.analyser.sheet_classifier import classify_sheet, SheetClassification
from app.analyser.header_detector import detect_headers, HeaderDetectionResult
from app.analyser.column_metadata import extract_column_metadata, ColumnMeta
from app.analyser.valid_values import extract_valid_values, ValidValueTable
from app.analyser.integrity import sha256_file


@dataclass
class SheetProfile:
    name: str
    classification: SheetClassification
    max_row: int
    max_col: int
    detection: HeaderDetectionResult | None = None
    columns: list[ColumnMeta] = field(default_factory=list)
    valid_value_tables: list[ValidValueTable] = field(default_factory=list)
    has_merged_cells: bool = False
    has_formulas: bool = False
    has_data_validation: bool = False
    frozen_pane: str | None = None


@dataclass
class WorkbookProfile:
    source_file: str
    category_name: str
    file_hash: str
    analysis_timestamp: str
    sheets: list[SheetProfile] = field(default_factory=list)
    listing_sheet: SheetProfile | None = None
    valid_value_sheets: list[SheetProfile] = field(default_factory=list)
    image_sheets: list[SheetProfile] = field(default_factory=list)
    document_sheets: list[SheetProfile] = field(default_factory=list)
    instruction_sheets: list[SheetProfile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    analysis_status: str = "ok"   # ok | partial | failed
    # Phase 4A fields — populated by registration_workflow after inspect_workbook
    template_purpose: str = "requires_review"
    template_purpose_confidence: float = 0.0
    template_purpose_reasons: list[str] = field(default_factory=list)
    template_fill_status: str = "requires_review"
    category_resolution_status: str = "unknown"   # resolved | provisional | unknown | requires_review
    blocking_reasons: list[str] = field(default_factory=list)
    safe_write_start_row: int | None = None
    row_classification_summary: dict = field(default_factory=dict)


def _infer_category(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"[-–\s]+(Attribute\s+Instructions?|listing\s+template).*$", "", stem, flags=re.I)
    return stem.strip()


def _category_from_sheet_name(sheet_name: str) -> str | None:
    """Extract human-readable category from a sheet name like '6087 - Pendant Lights'."""
    m = re.match(r"^\d+\s*[-–]\s*(.+)$", sheet_name.strip())
    if m:
        return m.group(1).strip()
    return None


def _safe_sample(ws, max_row: int, max_col: int, sample_rows: int = 5) -> list[str]:
    texts: list[str] = []
    for r in range(1, min(sample_rows + 1, max_row + 1)):
        for c in range(1, min(max_col + 1, 20)):
            v = ws.cell(r, c).value
            if v is not None:
                texts.append(str(v).strip())
    return [t for t in texts if t]


def _check_formulas(ws, max_row: int, max_col: int, sample: int = 20) -> bool:
    for r in range(1, min(sample, max_row) + 1):
        for c in range(1, min(max_col, 30) + 1):
            v = ws.cell(r, c).value
            if isinstance(v, str) and v.startswith("="):
                return True
    return False


def inspect_workbook(path: str | Path) -> WorkbookProfile:
    path = Path(path)
    filename = path.name
    category = _infer_category(filename)
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        file_hash = sha256_file(path)
    except Exception as e:
        file_hash = f"ERROR:{e}"

    profile = WorkbookProfile(
        source_file=filename,
        category_name=category,
        file_hash=file_hash,
        analysis_timestamp=timestamp,
    )

    try:
        wb = openpyxl.load_workbook(str(path), data_only=True)
    except Exception as e:
        profile.errors.append(f"Cannot open workbook: {e}")
        profile.analysis_status = "failed"
        return profile

    try:
        for sheet_name in wb.sheetnames:
            try:
                ws = wb[sheet_name]
                is_hidden = ws.sheet_state != "visible"
                max_row = ws.max_row or 0
                max_col = ws.max_column or 0

                first_row = [
                    str(ws.cell(1, c).value).strip() if ws.cell(1, c).value is not None else ""
                    for c in range(1, min(max_col + 1, 50))
                ]
                sample_text = _safe_sample(ws, max_row, max_col)

                classification = classify_sheet(
                    sheet_name=sheet_name,
                    is_hidden=is_hidden,
                    max_row=max_row,
                    max_col=max_col,
                    first_row_values=first_row,
                    all_sample_text=sample_text,
                )

                sp = SheetProfile(
                    name=sheet_name,
                    classification=classification,
                    max_row=max_row,
                    max_col=max_col,
                )

                # Frozen pane
                try:
                    if ws.freeze_panes:
                        sp.frozen_pane = str(ws.freeze_panes)
                except Exception:
                    pass

                # Merged cells
                try:
                    sp.has_merged_cells = bool(ws.merged_cells.ranges)
                except Exception:
                    pass

                # Data validation
                try:
                    sp.has_data_validation = bool(ws.data_validations and ws.data_validations.dataValidation)
                except Exception:
                    pass

                # Formula presence
                sp.has_formulas = _check_formulas(ws, max_row, max_col)

                # Header detection for tabular sheets
                if classification.sheet_type in ("listing", "valid_values", "image", "video", "document", "carton", "unknown"):
                    detection = detect_headers(ws, max_col)
                    sp.detection = detection

                    if detection.warnings:
                        profile.warnings.extend([
                            f"[{sheet_name}] {w}" for w in detection.warnings
                        ])

                    # Column metadata for listing sheets
                    if classification.sheet_type == "listing":
                        sp.columns = extract_column_metadata(ws, sheet_name, detection, max_col)

                    # Valid values extraction
                    if classification.sheet_type == "valid_values":
                        sp.valid_value_tables = extract_valid_values(ws, sheet_name, max_col, max_row)

                profile.sheets.append(sp)

            except Exception as e:
                profile.warnings.append(f"Sheet {sheet_name!r} error: {e}")

    finally:
        wb.close()

    # Assign role pointers
    listing_candidates = [s for s in profile.sheets if s.classification.sheet_type == "listing"]
    if listing_candidates:
        profile.listing_sheet = max(listing_candidates, key=lambda s: s.classification.confidence)
        # Prefer category derived from listing sheet name (e.g. "6087 - Pendant Lights" → "Pendant Lights")
        cat_from_sheet = _category_from_sheet_name(profile.listing_sheet.name)
        if cat_from_sheet:
            profile.category_name = cat_from_sheet
    else:
        profile.warnings.append("No listing sheet detected")

    profile.valid_value_sheets = [s for s in profile.sheets if s.classification.sheet_type == "valid_values"]
    profile.image_sheets = [s for s in profile.sheets if s.classification.sheet_type == "image"]
    profile.document_sheets = [s for s in profile.sheets if s.classification.sheet_type == "document"]
    profile.instruction_sheets = [s for s in profile.sheets if s.classification.sheet_type == "instruction"]

    # Cross-annotate column metadata with valid values
    if profile.listing_sheet and profile.valid_value_sheets:
        _annotate_controlled_fields(profile)

    if profile.errors:
        profile.analysis_status = "failed"
    elif profile.warnings:
        profile.analysis_status = "partial"

    return profile


def _annotate_controlled_fields(profile: WorkbookProfile) -> None:
    """Match valid-value table headers to listing column normalized headers."""
    vv_map: dict[str, list[str]] = {}
    for vs in profile.valid_value_sheets:
        for vt in vs.valid_value_tables:
            key = vt.normalized_field
            vv_map.setdefault(key, []).extend(vt.values)

    if not profile.listing_sheet:
        return
    for col in profile.listing_sheet.columns:
        if col.normalized_header in vv_map:
            col.is_controlled = True
            col.valid_values = vv_map[col.normalized_header]
