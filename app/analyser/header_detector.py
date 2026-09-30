"""
Dynamic header-row detection for Wayfair listing sheets.

Standard Wayfair format (10 of 11 workbooks):
  Row 1 – internal key  (core::supplierPartNumber …)
  Row 2 – group / section label
  Row 3 – required status (Required / Additional / Recommended)
  Row 4 – human-readable header  ← this is the display header
  Row 5 – instructions / description
  Row 6 – data type
  Row 7 – default / example row (first data row starts here)

Legacy format (Pendant Light Listing – Attribute Instructions):
  Row 1 – human-readable header (no internal-key row above it)
  Row 2+ – live product data

Detection strategy:
1. If row 1 contains 'core::' patterns → standard format, header row = 4.
2. Else scan the first 10 rows for the densest non-numeric row ≥ 5 populated
   cells that looks like headers (short strings, title-case or mixed, no
   long sentences) and return that row index.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

CORE_KEY_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*::[a-zA-Z]")
REQUIRED_VALUES = {"required", "additional", "recommended", "optional"}
LONG_TEXT_THRESHOLD = 60   # chars; header cells rarely exceed this
MAX_SCAN_ROWS = 15


@dataclass
class HeaderDetectionResult:
    header_row: int                            # 1-based
    headers: list[str]                         # exact as in the sheet
    method: str                                # "standard_key_row" | "scan_heuristic" | "fallback"
    confidence: float
    warnings: list[str] = field(default_factory=list)
    # Metadata rows (standard format only)
    internal_key_row: int | None = None        # row with core:: keys
    group_row: int | None = None
    required_row: int | None = None
    instructions_row: int | None = None
    data_type_row: int | None = None
    default_row: int | None = None


def _cell_str(ws, row: int, col: int) -> str:
    v = ws.cell(row, col).value
    return str(v).strip() if v is not None else ""


def _row_values(ws, row: int, max_col: int) -> list[str]:
    return [_cell_str(ws, row, c) for c in range(1, max_col + 1)]


def _is_core_key_row(values: list[str]) -> bool:
    populated = [v for v in values if v]
    if not populated:
        return False
    matches = sum(1 for v in populated if CORE_KEY_RE.match(v))
    # At least 1 core:: key, and at least 10% of populated cells match.
    # Category-specific columns don't always have core:: keys so ratio can be low.
    return matches >= 1 and matches / len(populated) >= 0.10


def _is_required_row(values: list[str]) -> bool:
    populated = [v.lower() for v in values if v]
    if not populated:
        return False
    return sum(1 for v in populated if v in REQUIRED_VALUES) / len(populated) >= 0.5


def _header_score(values: list[str]) -> float:
    """Heuristic score for how likely this row contains column headers."""
    populated = [v for v in values if v]
    if len(populated) < 3:
        return 0.0
    short = sum(1 for v in populated if len(v) <= LONG_TEXT_THRESHOLD)
    not_numeric = sum(1 for v in populated if not v.replace(".", "").replace(",", "").isnumeric())
    not_required = sum(1 for v in populated if v.lower() not in REQUIRED_VALUES)
    not_core = sum(1 for v in populated if not CORE_KEY_RE.match(v))
    n = len(populated)
    return (short / n) * 0.3 + (not_numeric / n) * 0.25 + (not_required / n) * 0.25 + (not_core / n) * 0.2


def detect_headers(ws, max_col: int | None = None) -> HeaderDetectionResult:
    if max_col is None:
        max_col = ws.max_column or 1

    scan_rows = min(MAX_SCAN_ROWS, ws.max_row or 1)

    # --- Strategy 1: standard format ---
    row1 = _row_values(ws, 1, max_col)
    if _is_core_key_row(row1):
        # Look for required row around row 3
        for candidate_req in range(2, 6):
            if _is_required_row(_row_values(ws, candidate_req, max_col)):
                header_row = candidate_req + 1
                break
        else:
            header_row = 4  # fallback

        headers = _row_values(ws, header_row, max_col)
        return HeaderDetectionResult(
            header_row=header_row,
            headers=headers,
            method="standard_key_row",
            confidence=0.95,
            internal_key_row=1,
            group_row=2,
            required_row=3,
            instructions_row=5,
            data_type_row=6,
            default_row=7,
        )

    # --- Strategy 2: scan heuristic ---
    best_row = 1
    best_score = -1.0
    for r in range(1, scan_rows + 1):
        vals = _row_values(ws, r, max_col)
        score = _header_score(vals)
        populated = sum(1 for v in vals if v)
        if populated >= 3 and score > best_score:
            best_score = score
            best_row = r

    headers = _row_values(ws, best_row, max_col)
    warnings: list[str] = []
    if best_score < 0.6:
        warnings.append(
            f"Low header-detection confidence ({best_score:.2f}); row {best_row} chosen by heuristic"
        )

    return HeaderDetectionResult(
        header_row=best_row,
        headers=headers,
        method="scan_heuristic",
        confidence=round(min(best_score, 1.0), 2),
        warnings=warnings,
    )
