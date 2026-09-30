"""
Sheet classification using multiple signals.
Returns a classification type, confidence score (0-1), and reasons list.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

LISTING_KEYWORDS = re.compile(
    r"\b(listing|product|item|sku|catalog|template)\b", re.I
)
INSTRUCTION_KEYWORDS = re.compile(
    r"\b(instructions?|read\s*me|guide|how\s*to|notes?|overview|directions?)\b", re.I
)
VALID_VALUE_KEYWORDS = re.compile(
    r"\b(valid\s*values?|picklist|lookup|allowed|dropdown|options?|choices?)\b", re.I
)
IMAGE_KEYWORDS = re.compile(r"\b(image|photo|picture|thumbnail|gallery|visual)\b", re.I)
VIDEO_KEYWORDS = re.compile(r"\b(video|media|clip|film)\b", re.I)
DOCUMENT_KEYWORDS = re.compile(r"\b(document|doc|pdf|manual|spec|certificate)\b", re.I)
CARTON_KEYWORDS = re.compile(r"\b(carton|box|pack(age)?|shipping|freight)\b", re.I)
INTERNAL_KEYWORDS = re.compile(r"\b(wayfair[_\s]use|internal|system|hidden|config)\b", re.I)

# Typical header content seen in standard Wayfair listing sheets
LISTING_HEADER_SIGNALS = {
    "supplier part number", "product name", "brand", "sku",
    "manufacturer part number", "core::supplierpartnumber",
}


@dataclass
class SheetClassification:
    sheet_name: str
    sheet_type: str          # listing | instruction | valid_values | image | video | document | carton | internal | unknown
    confidence: float        # 0.0 – 1.0
    reasons: list[str] = field(default_factory=list)
    is_hidden: bool = False


def _norm(s: str) -> str:
    return s.strip().lower() if s else ""


_ADDITIONAL_SHEET_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"additional\s+image", re.I), "image"),
    (re.compile(r"additional\s+video", re.I), "video"),
    (re.compile(r"additional\s+document", re.I), "document"),
    (re.compile(r"additional\s+carton", re.I), "carton"),
]


def classify_sheet(
    sheet_name: str,
    is_hidden: bool,
    max_row: int,
    max_col: int,
    first_row_values: list[str],     # cell values from first data row (row 1)
    all_sample_text: list[str],      # flat list of sampled cell values from sheet
) -> SheetClassification:
    # Explicit overrides — sheet name unambiguously identifies type
    for pattern, sheet_type in _ADDITIONAL_SHEET_PATTERNS:
        if pattern.search(sheet_name):
            return SheetClassification(
                sheet_name=sheet_name,
                sheet_type=sheet_type,
                confidence=0.95,
                reasons=[f"sheet name explicitly matches {sheet_type} pattern: {sheet_name!r}"],
                is_hidden=is_hidden,
            )

    reasons: list[str] = []
    scores: dict[str, float] = {
        "listing": 0.0,
        "instruction": 0.0,
        "valid_values": 0.0,
        "image": 0.0,
        "video": 0.0,
        "document": 0.0,
        "carton": 0.0,
        "internal": 0.0,
    }

    name_lower = _norm(sheet_name)

    # --- Name-based signals ---
    if INTERNAL_KEYWORDS.search(sheet_name):
        scores["internal"] += 0.8
        reasons.append(f"sheet name matches internal pattern: {sheet_name!r}")
    if is_hidden:
        scores["internal"] += 0.3
        reasons.append("sheet is hidden")

    if INSTRUCTION_KEYWORDS.search(sheet_name):
        scores["instruction"] += 0.7
        reasons.append(f"sheet name matches instruction pattern: {sheet_name!r}")
    if VALID_VALUE_KEYWORDS.search(sheet_name):
        scores["valid_values"] += 0.8
        reasons.append(f"sheet name matches valid-values pattern: {sheet_name!r}")
    if IMAGE_KEYWORDS.search(sheet_name):
        scores["image"] += 0.75
        reasons.append(f"sheet name matches image pattern: {sheet_name!r}")
    if VIDEO_KEYWORDS.search(sheet_name):
        scores["video"] += 0.75
        reasons.append(f"sheet name matches video pattern: {sheet_name!r}")
    if DOCUMENT_KEYWORDS.search(sheet_name):
        scores["document"] += 0.6
        reasons.append(f"sheet name matches document pattern: {sheet_name!r}")
    if CARTON_KEYWORDS.search(sheet_name):
        scores["carton"] += 0.75
        reasons.append(f"sheet name matches carton pattern: {sheet_name!r}")
    if LISTING_KEYWORDS.search(sheet_name):
        scores["listing"] += 0.5
        reasons.append(f"sheet name matches listing pattern: {sheet_name!r}")

    # Numeric prefix pattern like "6085 - Chandeliers"
    if re.match(r"^\d+\s*[-–]\s*.+", sheet_name):
        scores["listing"] += 0.6
        reasons.append(f"sheet name has category-id prefix: {sheet_name!r}")

    # --- Column-count signals ---
    if max_col >= 50:
        scores["listing"] += 0.4
        reasons.append(f"high column count ({max_col}) typical of listing sheet")
    elif max_col <= 10 and max_row >= 100:
        scores["valid_values"] += 0.3
        reasons.append(f"narrow+tall layout ({max_col}c×{max_row}r) typical of valid-values")

    # --- Header-content signals ---
    norm_first_row = {_norm(v) for v in first_row_values if v}
    listing_hits = norm_first_row & LISTING_HEADER_SIGNALS
    if listing_hits:
        scores["listing"] += 0.5
        reasons.append(f"first row contains listing headers: {listing_hits}")
    if any("core::" in _norm(v) for v in first_row_values):
        scores["listing"] += 0.5
        reasons.append("first row contains 'core::' key pattern")

    # --- Sample-text signals (instructions often contain long sentences) ---
    long_texts = [t for t in all_sample_text if len(t) > 80]
    if len(long_texts) >= 3 and max_col <= 6:
        scores["instruction"] += 0.35
        reasons.append("multiple long instructional-looking text cells")

    # --- Additional Images/Videos/Documents specific patterns ---
    if re.search(r"additional\s+image", sheet_name, re.I):
        scores["image"] += 0.9
    if re.search(r"additional\s+video", sheet_name, re.I):
        scores["video"] += 0.9
    if re.search(r"additional\s+document", sheet_name, re.I):
        scores["document"] += 0.9
    if re.search(r"additional\s+carton", sheet_name, re.I):
        scores["carton"] += 0.9

    # --- Pick winner ---
    best_type = max(scores, key=lambda k: scores[k])
    best_score = scores[best_type]

    if best_score < 0.3:
        best_type = "unknown"
        best_score = 0.1
        reasons.append("no strong classification signal found")

    # Cap at 1.0
    best_score = min(best_score, 1.0)

    return SheetClassification(
        sheet_name=sheet_name,
        sheet_type=best_type,
        confidence=round(best_score, 2),
        reasons=reasons,
        is_hidden=is_hidden,
    )
