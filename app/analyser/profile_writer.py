"""
Serialise a WorkbookProfile to JSON and write to outputs/template_profiles/.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

from app.analyser.inspector import WorkbookProfile, SheetProfile
from app.analyser.header_detector import HeaderDetectionResult
from app.analyser.column_metadata import ColumnMeta
from app.analyser.valid_values import ValidValueTable
from app.analyser.sheet_classifier import SheetClassification


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name).strip("_")


def _cls_to_dict(c: SheetClassification) -> dict:
    return {
        "sheet_name": c.sheet_name,
        "type": c.sheet_type,
        "confidence": c.confidence,
        "is_hidden": c.is_hidden,
        "reasons": c.reasons,
    }


def _det_to_dict(d: HeaderDetectionResult | None) -> dict | None:
    if d is None:
        return None
    return {
        "header_row": d.header_row,
        "method": d.method,
        "confidence": d.confidence,
        "warnings": d.warnings,
        "internal_key_row": d.internal_key_row,
        "group_row": d.group_row,
        "required_row": d.required_row,
        "instructions_row": d.instructions_row,
        "data_type_row": d.data_type_row,
        "default_row": d.default_row,
    }


def _col_to_dict(col: ColumnMeta) -> dict:
    return {
        "original_header": col.original_header,
        "normalized_header": col.normalized_header,
        "column_position": col.column_position,
        "internal_key": col.internal_key,
        "group": col.group,
        "required_status": col.required_status,
        "instructions": col.instructions[:200] if col.instructions else "",
        "data_type": col.data_type,
        "default_value": col.default_value,
        "char_limit": col.char_limit,
        "unit_required": col.unit_required,
        "is_controlled": col.is_controlled,
        "valid_values": col.valid_values[:20],  # cap for readability
        "has_formula": col.has_formula,
        "is_duplicate_header": col.is_duplicate_header,
        "mapping_status": col.mapping_status,
    }


def _vt_to_dict(vt: ValidValueTable) -> dict:
    return {
        "field_name": vt.field_name,
        "normalized_field": vt.normalized_field,
        "column_position": vt.column_position,
        "cell_range": vt.cell_range,
        "value_count": len(vt.values),
        "values": vt.values[:50],  # cap for readability
        "ambiguous": vt.ambiguous,
    }


def _sheet_to_dict(sp: SheetProfile) -> dict:
    return {
        "name": sp.name,
        "classification": _cls_to_dict(sp.classification),
        "max_row": sp.max_row,
        "max_col": sp.max_col,
        "has_merged_cells": sp.has_merged_cells,
        "has_formulas": sp.has_formulas,
        "has_data_validation": sp.has_data_validation,
        "frozen_pane": sp.frozen_pane,
        "header_detection": _det_to_dict(sp.detection),
        "column_count": len(sp.columns),
        "columns": [_col_to_dict(c) for c in sp.columns],
        "valid_value_tables": [_vt_to_dict(vt) for vt in sp.valid_value_tables],
    }


def write_profile(profile: WorkbookProfile, output_dir: str | Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "source_file": profile.source_file,
        "category_name": profile.category_name,
        "file_hash_sha256": profile.file_hash,
        "analysis_timestamp": profile.analysis_timestamp,
        "analysis_status": profile.analysis_status,
        # Phase 4A fields
        "template_purpose": profile.template_purpose,
        "template_purpose_confidence": profile.template_purpose_confidence,
        "template_purpose_reasons": profile.template_purpose_reasons,
        "template_fill_status": profile.template_fill_status,
        "category_resolution_status": profile.category_resolution_status,
        "blocking_reasons": profile.blocking_reasons,
        "safe_write_start_row": profile.safe_write_start_row,
        "row_classification_summary": profile.row_classification_summary,
        # Existing fields
        "sheet_count": len(profile.sheets),
        "listing_sheet": profile.listing_sheet.name if profile.listing_sheet else None,
        "listing_header_count": len(profile.listing_sheet.columns) if profile.listing_sheet else 0,
        "listing_header_row": (
            profile.listing_sheet.detection.header_row
            if profile.listing_sheet and profile.listing_sheet.detection else None
        ),
        "exact_headers": (
            [c.original_header for c in profile.listing_sheet.columns]
            if profile.listing_sheet else []
        ),
        "valid_value_sheets": [s.name for s in profile.valid_value_sheets],
        "image_sheets": [s.name for s in profile.image_sheets],
        "document_sheets": [s.name for s in profile.document_sheets],
        "instruction_sheets": [s.name for s in profile.instruction_sheets],
        "warnings": profile.warnings,
        "errors": profile.errors,
        "sheets": [_sheet_to_dict(s) for s in profile.sheets],
    }

    out_path = output_dir / f"{_safe_name(profile.category_name)}.json"
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path
