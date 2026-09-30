"""
Extract per-column metadata from a standard Wayfair listing sheet.

Reads the metadata rows (group, required-status, instructions, data-type,
default) when available, and annotates each column.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from app.analyser.header_detector import HeaderDetectionResult

_CHAR_LIMIT_RE = re.compile(r"(\d+)\s*char", re.I)
_UNIT_RE = re.compile(r"\b(inch(?:es)?|cm|mm|lbs?|kg|watts?|volts?|amps?)\b", re.I)


def _norm_header(h: str) -> str:
    """Normalize for internal matching only; original is preserved separately."""
    return re.sub(r"\s+", " ", h.strip()).lower()


@dataclass
class ColumnMeta:
    original_header: str
    normalized_header: str
    sheet_name: str
    column_position: int          # 1-based
    internal_key: str = ""
    group: str = ""
    required_status: str = ""     # Required | Additional | Recommended | unknown
    instructions: str = ""
    data_type: str = ""
    default_value: str = ""
    char_limit: int | None = None
    unit_required: bool = False
    is_controlled: bool = False   # set by valid-value extraction pass
    valid_values: list[str] = field(default_factory=list)
    has_formula: bool = False
    is_duplicate_header: bool = False
    mapping_status: str = "unmapped"   # unmapped | mapped | manual_review


def _cell_str(ws, row: int, col: int) -> str:
    v = ws.cell(row, col).value
    return str(v).strip() if v is not None else ""


def extract_column_metadata(
    ws,
    sheet_name: str,
    detection: HeaderDetectionResult,
    max_col: int,
) -> list[ColumnMeta]:
    cols: list[ColumnMeta] = []
    seen_headers: dict[str, int] = {}

    for c in range(1, max_col + 1):
        orig = detection.headers[c - 1] if c - 1 < len(detection.headers) else ""

        norm = _norm_header(orig)

        # Duplicate detection
        is_dup = False
        if norm in seen_headers:
            is_dup = True
        elif orig:
            seen_headers[norm] = c

        # Read metadata rows if available (standard format)
        internal_key = (
            _cell_str(ws, detection.internal_key_row, c)
            if detection.internal_key_row else ""
        )
        group = (
            _cell_str(ws, detection.group_row, c)
            if detection.group_row else ""
        )
        req_raw = (
            _cell_str(ws, detection.required_row, c)
            if detection.required_row else ""
        )
        required_status = req_raw if req_raw.lower() in {
            "required", "additional", "recommended", "optional"
        } else ("unknown" if not req_raw else req_raw)

        instructions = (
            _cell_str(ws, detection.instructions_row, c)
            if detection.instructions_row else ""
        )
        data_type = (
            _cell_str(ws, detection.data_type_row, c)
            if detection.data_type_row else ""
        )
        default_value = (
            _cell_str(ws, detection.default_row, c)
            if detection.default_row else ""
        )

        # Char limit
        char_limit: int | None = None
        m = _CHAR_LIMIT_RE.search(instructions)
        if m:
            char_limit = int(m.group(1))

        # Unit requirement
        unit_required = bool(_UNIT_RE.search(instructions + " " + data_type))

        cols.append(ColumnMeta(
            original_header=orig,
            normalized_header=norm,
            sheet_name=sheet_name,
            column_position=c,
            internal_key=internal_key,
            group=group,
            required_status=required_status,
            instructions=instructions,
            data_type=data_type,
            default_value=default_value,
            char_limit=char_limit,
            unit_required=unit_required,
            is_duplicate_header=is_dup,
        ))

    return cols
