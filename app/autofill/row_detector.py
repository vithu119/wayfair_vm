"""
Dynamic row classification for Wayfair listing sheets.

Scans every row below the detected header row and classifies it as one of:
  blank               - no content in any listing column
  sample_candidate    - high confidence this is a template example/default row
  existing_product    - contains credible product identifiers
  formula_only        - every non-empty cell is a formula
  instruction_or_note - contains instruction/metadata text (not a real product)
  separator           - thin divider row (1-2 populated cells, no identifiers)
  unknown             - ambiguous; requires human review before writing
  writable            - explicitly safe (used for blank rows after product scan)

Classification uses evidence, never position alone.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

# Identifier column aliases – if any of these headers is populated with a
# non-sample value, the row is likely an existing product.
IDENTIFIER_ALIASES: set[str] = {
    "supplier part number",
    "amazon seller sku",
    "amazon standard identification number",
    "manufacturer part number",
    "european article number",
    "group reference id",
    "sku",
    "mpn",
    "ean",
    "asin",
    "part number",
    "item number",
}

# Patterns that signal placeholder / template-provided content
_SAMPLE_TEXT = re.compile(
    r"^\s*(n/a|n\.a\.?|default\s*row|example|sample|test\s*product|"
    r"placeholder|tbc|todo|demo|dummy|enter\s+your|your\s+product|"
    r"see\s+instructions?|required|additional|recommended|conditional|"
    r"must\s+be|please\s+(enter|choose|select|provide)|"
    r"text|select|whole\s+number|yes\s+or\s+no|number)\s*$",
    re.I,
)

# Specific Wayfair template markers
_DEFAULT_ROW_MARKER = re.compile(r"default\s*row\s*:?", re.I)

# Data-type / format descriptor keywords that appear in metadata rows
# e.g. row 6 in standard Wayfair templates: "Text", "Select", "Number", ...
_METADATA_KEYWORDS = re.compile(
    r"^\s*(text|select|number|integer|whole\s+number|date|dropdown|"
    r"yes\s*[/or]*\s*no|yes\s+or\s+no|decimal|boolean|multi-?select|"
    r"free\s*text|alphanumeric|url|image\s*url|currency|percentage|"
    r"select\s+from\s+list|pick\s+list|lookup)\s*$",
    re.I,
)

# Required/optional status keywords that appear in template control rows
_REQUIRED_STATUS_KEYWORDS = re.compile(
    r"^\s*(required|additional|recommended|optional|conditional)\s*$",
    re.I,
)

# Dropdown option lists — "Please choose one or more from the following..."
_DROPDOWN_OPTIONS = re.compile(
    r"^\s*please\s+choose\s+one\s+or\s+more\s+from\s+the\s+following",
    re.I,
)

# Patterns that suggest instruction-like text (long sentences, not product values)
_INSTRUCTION_TEXT = re.compile(
    r"\b(must\s+be|please\s+(enter|choose|select)|"
    r"the\s+amazon|if\s+the\s+product|enter\s+your|"
    r"must\s+follow|this\s+field|note\s*:|tip\s*:|instructions?)\b",
    re.I,
)

# Common instruction verb prefixes — a real identifier never starts with these
_INSTRUCTION_PREFIX = re.compile(
    r"^\s*(enter|choose|select|see|provide|use|add|fill|type|leave|"
    r"required|conditional|optional|recommended|example|this\s+field|"
    r"please|must|for\s+example)\b",
    re.I,
)

# Patterns that strongly indicate an artificial / fake SKU
_ARTIFICIAL_ID = re.compile(
    r"^(sku[-_\s]?\d{3}|item[-_\s]?\d+|test[-_\s]?\d*|sample|demo|"
    r"dummy|placeholder|abcde|12345|xxxxx|aaa+|000+)\s*$",
    re.I,
)

MAX_SCAN_ROWS = 2000          # never scan more than this many rows below header
MAX_CONSECUTIVE_BLANK = 30    # stop scanning after this many consecutive blank rows


@dataclass
class RowClassification:
    row_number: int            # 1-based Excel row number
    status: str                # see module docstring
    confidence: float          # 0.0 – 1.0
    reasons: list[str] = field(default_factory=list)
    populated_headers: list[str] = field(default_factory=list)
    existing_identifiers: dict[str, str] = field(default_factory=dict)
    has_formula: bool = False


def _norm_header(h: str) -> str:
    return h.strip().lower() if h else ""


def _cell_str(ws, row: int, col: int) -> str:
    v = ws.cell(row, col).value
    return str(v).strip() if v is not None else ""


def _is_formula(ws, row: int, col: int) -> bool:
    v = ws.cell(row, col).value
    return isinstance(v, str) and v.startswith("=")


def classify_data_area(
    ws,
    header_row: int,
    col_map: dict[str, int],     # {exact_header: col_1based} from header row
    max_row: int | None = None,
) -> list[RowClassification]:
    """
    Classify all rows from header_row+1 down to max_row (or scan limit).
    Returns one RowClassification per scanned row.
    """
    if max_row is None:
        # ws.max_row returns None in read_only mode; fall back to scan limit
        ws_max = getattr(ws, "max_row", None)
        max_row = ws_max if (ws_max and ws_max > header_row) else header_row + MAX_SCAN_ROWS

    scan_end = min(max_row, header_row + MAX_SCAN_ROWS)

    # Build identifier column positions
    id_cols: dict[str, int] = {}   # norm_header -> col
    for h, c in col_map.items():
        if _norm_header(h) in IDENTIFIER_ALIASES:
            id_cols[h] = c

    classifications: list[RowClassification] = []
    consecutive_blank = 0

    for row_num in range(header_row + 1, scan_end + 1):
        rc = _classify_single_row(ws, row_num, col_map, id_cols)
        classifications.append(rc)

        if rc.status == "blank":
            consecutive_blank += 1
            if consecutive_blank >= MAX_CONSECUTIVE_BLANK:
                break
        else:
            consecutive_blank = 0

    return classifications


def _classify_single_row(
    ws,
    row_num: int,
    col_map: dict[str, int],
    id_cols: dict[str, int],
) -> RowClassification:
    reasons: list[str] = []
    populated: dict[str, str] = {}   # header -> value
    formula_cells: list[str] = []

    for header, col in col_map.items():
        raw = _cell_str(ws, row_num, col)
        if raw:
            populated[header] = raw
        if _is_formula(ws, row_num, col):
            formula_cells.append(header)

    has_formula = bool(formula_cells)

    # ── BLANK ──────────────────────────────────────────────────────────────
    if not populated:
        return RowClassification(
            row_number=row_num,
            status="blank",
            confidence=1.0,
            reasons=["all listing columns are empty"],
            has_formula=has_formula,
        )

    populated_headers = list(populated.keys())

    # ── FORMULA ONLY ────────────────────────────────────────────────────────
    non_formula_vals = {h: v for h, v in populated.items()
                        if not (isinstance(ws.cell(row_num, col_map[h]).value, str)
                                and ws.cell(row_num, col_map[h]).value.startswith("="))}
    if not non_formula_vals and formula_cells:
        return RowClassification(
            row_number=row_num,
            status="formula_only",
            confidence=0.9,
            reasons=[f"all {len(formula_cells)} populated cells contain formulas"],
            populated_headers=populated_headers,
            has_formula=True,
        )

    # ── Check identifier columns ───────────────────────────────────────────
    existing_ids: dict[str, str] = {}
    for h, col in id_cols.items():
        v = populated.get(h, "")
        if (v
                and len(v) <= 100          # real identifiers are short
                and not _ARTIFICIAL_ID.match(v)
                and not _SAMPLE_TEXT.match(v)
                and not _INSTRUCTION_PREFIX.match(v)):
            existing_ids[h] = v

    all_vals = list(populated.values())
    first_val = all_vals[0] if all_vals else ""

    # ── TEMPLATE CONTROL ROW ──────────────────────────────────────────────
    # "Default Row:" marker — a Wayfair template control row, not a sample
    if _DEFAULT_ROW_MARKER.match(first_val):
        reasons.append(f"first cell matches 'Default Row:' pattern: {first_val!r}")
        return RowClassification(
            row_number=row_num,
            status="template_control_row",
            confidence=0.98,
            reasons=reasons,
            populated_headers=populated_headers,
            has_formula=has_formula,
        )

    # All cells are required/optional status markers → template control row
    req_matching = [v for v in all_vals if _REQUIRED_STATUS_KEYWORDS.match(v)]
    if len(req_matching) == len(all_vals) and len(all_vals) >= 2:
        reasons.append(
            f"all {len(all_vals)} cells are required/optional status markers "
            f"(e.g. {all_vals[0]!r})"
        )
        return RowClassification(
            row_number=row_num,
            status="template_control_row",
            confidence=0.92,
            reasons=reasons,
            populated_headers=populated_headers,
            has_formula=has_formula,
        )

    # ── METADATA ─────────────────────────────────────────────────────────
    # All cells are data-type descriptor keywords → metadata row (e.g. row 6)
    meta_matching = [v for v in all_vals if _METADATA_KEYWORDS.match(v)]
    if len(meta_matching) == len(all_vals) and len(all_vals) >= 2:
        reasons.append(
            f"all {len(all_vals)} cells are data-type descriptors "
            f"(e.g. {all_vals[0]!r})"
        )
        return RowClassification(
            row_number=row_num,
            status="metadata",
            confidence=0.92,
            reasons=reasons,
            populated_headers=populated_headers,
            has_formula=has_formula,
        )

    # ── INSTRUCTION / NOTE ─────────────────────────────────────────────────
    # Long instruction text — either in few columns, OR majority of cells match
    long_instruction_cells = [
        v for v in all_vals if len(v) > 60 and _INSTRUCTION_TEXT.search(v)
    ]
    # Dropdown option rows: "Please choose one or more from the following..."
    dropdown_cells = [v for v in all_vals if _DROPDOWN_OPTIONS.match(v)]
    instruction_fraction = len(long_instruction_cells) / max(len(all_vals), 1)
    if (long_instruction_cells and len(populated) <= 3) or \
       dropdown_cells or \
       instruction_fraction >= 0.4:
        reasons.append(f"row contains instruction-like text in {len(long_instruction_cells)} cell(s)")
        return RowClassification(
            row_number=row_num,
            status="instruction_or_note",
            confidence=0.85,
            reasons=reasons,
            populated_headers=populated_headers,
            has_formula=has_formula,
        )

    # ── SAMPLE CANDIDATE ──────────────────────────────────────────────────
    # All populated cells match placeholder patterns AND no real identifier
    # Do NOT classify template_control_row or metadata rows as sample_candidate
    sample_matching = [v for v in all_vals if _SAMPLE_TEXT.match(v)]
    all_sample = len(sample_matching) == len(all_vals) and len(all_vals) >= 2

    if all_sample and not existing_ids:
        reasons.append(
            f"all {len(all_vals)} populated cells match placeholder patterns "
            f"(e.g. {all_vals[0]!r})"
        )
        reasons.append("no credible product identifier found")
        return RowClassification(
            row_number=row_num,
            status="sample_candidate",
            confidence=0.88,
            reasons=reasons,
            populated_headers=populated_headers,
            has_formula=has_formula,
        )

    # Majority sample AND no real identifier (lower confidence)
    if not existing_ids and len(sample_matching) / max(len(all_vals), 1) >= 0.7:
        reasons.append(f"{len(sample_matching)}/{len(all_vals)} cells match placeholder patterns")
        reasons.append("no credible identifier present")
        return RowClassification(
            row_number=row_num,
            status="sample_candidate",
            confidence=0.65,
            reasons=reasons,
            populated_headers=populated_headers,
            has_formula=has_formula,
        )

    # ── EXISTING PRODUCT ───────────────────────────────────────────────────
    if existing_ids:
        id_display = ", ".join(f"{k}={v!r}" for k, v in list(existing_ids.items())[:3])
        reasons.append(f"credible product identifier(s) found: {id_display}")
        return RowClassification(
            row_number=row_num,
            status="existing_product",
            confidence=0.90,
            reasons=reasons,
            populated_headers=populated_headers,
            existing_identifiers=existing_ids,
            has_formula=has_formula,
        )

    # ── SEPARATOR ──────────────────────────────────────────────────────────
    if len(populated) == 1:
        reasons.append("only one cell populated, no identifier — likely separator")
        return RowClassification(
            row_number=row_num,
            status="separator",
            confidence=0.6,
            reasons=reasons,
            populated_headers=populated_headers,
            has_formula=has_formula,
        )

    # ── UNKNOWN ────────────────────────────────────────────────────────────
    reasons.append(
        f"{len(populated)} populated cells but could not confidently classify"
    )
    return RowClassification(
        row_number=row_num,
        status="unknown",
        confidence=0.3,
        reasons=reasons,
        populated_headers=populated_headers,
        has_formula=has_formula,
    )
