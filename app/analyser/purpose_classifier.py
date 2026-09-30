"""
Classify the primary purpose of a Wayfair workbook.

Supported purposes:
  fillable_template   - primary purpose is product listing upload
  reference_workbook  - primarily reference / example / populated data
  instruction_workbook - instructions or guidance only; no usable listing sheet
  mixed_workbook      - both a usable listing sheet AND substantial instruction content
  unsupported         - structure cannot be safely interpreted
  requires_review     - structurally ambiguous; human confirmation needed

Classification uses multiple signals from the WorkbookProfile:
- Listing sheet presence and confidence
- Header detection confidence
- Column density
- Instruction/reference sheet count
- Estimated populated data rows (from listing sheet max_row vs header_row)
- Sheet names for supplementary signals (not as primary decision)
- Row classification summary (when available from registration workflow)

Does NOT rely on:
- Filename patterns
- Known categories
- analysis_status
- Active worksheet
- Fixed row numbers
"""
from __future__ import annotations
from dataclasses import dataclass, field

from app.analyser.findings import Finding

PURPOSES = frozenset({
    "fillable_template",
    "reference_workbook",
    "instruction_workbook",
    "mixed_workbook",
    "unsupported",
    "requires_review",
})

_REFERENCE_SHEET_NAMES = (
    "read me", "readme", "read_me",
    "how to use", "how to", "guide",
    "attribute instructions", "attribute guide",
    "field guide", "instructions",
)

_ATTR_INSTRUCTION_KEYWORDS = ("attribute", "q&a", "question", "guidance")


@dataclass
class PurposeClassification:
    purpose: str
    confidence: float          # 0.0 – 1.0
    reasons: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    category_resolution_status: str = "unknown"   # resolved | provisional | unknown | requires_review


def _norm(s: str) -> str:
    return s.strip().lower()


def _sheet_is_reference_type(sheet_name: str) -> bool:
    n = _norm(sheet_name)
    return any(kw in n for kw in _REFERENCE_SHEET_NAMES)


def _sheet_has_attr_instruction_signals(sheet_name: str, first_row_values: list[str]) -> bool:
    n = _norm(sheet_name)
    if any(kw in n for kw in _ATTR_INSTRUCTION_KEYWORDS):
        return True
    if first_row_values:
        joined = " ".join(_norm(v) for v in first_row_values[:5] if v)
        return "attribute" in joined or "question" in joined
    return False


def classify_purpose(
    profile,                          # WorkbookProfile
    row_summary: dict | None = None,  # from registration_workflow
) -> PurposeClassification:
    """
    Classify the workbook's primary purpose using multiple signals.

    row_summary keys (all optional):
      existing_product_count  int
      sample_count            int
      metadata_row_count      int
      template_control_count  int
      instruction_row_count   int
      blank_count             int
    """
    reasons: list[str] = []
    findings: list[Finding] = []

    rs = row_summary or {}
    existing_product_count = rs.get("existing_product_count", 0)
    sample_count = rs.get("sample_count", 0)
    metadata_row_count = rs.get("metadata_row_count", 0)
    template_control_count = rs.get("template_control_count", 0)
    blank_count = rs.get("blank_count", 0)

    # ── Signal: listing sheet ──────────────────────────────────────────────
    listing = getattr(profile, "listing_sheet", None)
    listing_confidence = listing.classification.confidence if listing else 0.0
    has_reliable_listing = listing is not None and listing_confidence >= 0.5

    det = (listing.detection if listing else None)
    header_confidence = det.confidence if det else 0.0
    has_reliable_header = header_confidence >= 0.45

    col_count = len(listing.columns) if listing else 0
    has_good_columns = col_count >= 5

    # ── Signal: listing sheet data density ────────────────────────────────
    # Estimate how many data rows are below the header in the listing sheet
    listing_max_row = listing.max_row if listing else 0
    header_row = det.header_row if det else 1
    rows_below_header = max(0, listing_max_row - header_row)
    # For standard blank templates: rows_below_header = 3 (rows 5,6,7)
    # For populated sheets: much larger
    has_substantial_data = rows_below_header > 30 or existing_product_count > 5

    # ── Signal: instruction / reference sheets ────────────────────────────
    instruction_sheets = getattr(profile, "instruction_sheets", [])
    all_sheets = getattr(profile, "sheets", [])
    instruction_count = len(instruction_sheets)
    reference_sheet_count = sum(
        1 for s in all_sheets if _sheet_is_reference_type(s.name)
    )
    attr_instruction_count = sum(
        1 for s in all_sheets
        if _sheet_has_attr_instruction_signals(
            s.name,
            [s.name],   # first_row_values not available in profile, use sheet name
        )
    )
    total_reference_signals = instruction_count + reference_sheet_count + attr_instruction_count

    # ── Derive multiple listing sheet candidates ───────────────────────────
    candidate_listing_sheets = [
        s for s in all_sheets
        if s.classification.sheet_type == "listing"
    ]
    sorted_candidates = sorted(
        candidate_listing_sheets,
        key=lambda s: s.classification.confidence,
        reverse=True,
    )
    best_conf = sorted_candidates[0].classification.confidence if sorted_candidates else 0.0
    second_conf = sorted_candidates[1].classification.confidence if len(sorted_candidates) > 1 else 0.0
    # Only flag ambiguous if no clear winner (best < 0.90) and top two are nearly tied
    ambiguous_listing = (
        len(candidate_listing_sheets) >= 2
        and best_conf < 0.90
        and (best_conf - second_conf) < 0.15
    )

    # ── Category resolution ────────────────────────────────────────────────
    # Resolved: listing sheet name has a numeric category-ID prefix like "6085 - Chandeliers"
    import re
    cat_resolved = False
    cat_status = "unknown"
    if listing:
        if re.match(r"^\d+\s*[-–]\s*.+", listing.name):
            cat_resolved = True
            cat_status = "resolved"
            reasons.append(f"category resolved from listing sheet name: {listing.name!r}")
        elif profile.category_name and profile.category_name != "unknown":
            cat_status = "provisional"
            reasons.append(f"category provisionally derived from filename: {profile.category_name!r}")
    if not listing or not profile.category_name:
        cat_status = "unknown"

    # ── Scoring ────────────────────────────────────────────────────────────
    fillable_score = 0.0
    reference_score = 0.0
    instruction_score = 0.0
    mixed_score = 0.0

    # Fillable signals
    if has_reliable_listing:
        fillable_score += listing_confidence * 0.35
        reasons.append(f"listing sheet detected with confidence {listing_confidence:.2f}")
    if has_reliable_header:
        fillable_score += 0.25
        reasons.append(f"header detected with confidence {header_confidence:.2f}")
    if has_good_columns:
        fillable_score += 0.20
        reasons.append(f"listing sheet has {col_count} columns")
    if not has_substantial_data:
        fillable_score += 0.15
        reasons.append("listing sheet appears to be blank/template (low data density)")
    if template_control_count > 0 or metadata_row_count > 0:
        fillable_score += 0.05
        reasons.append("template control or metadata rows detected (standard template format)")

    # Reference signals
    if has_substantial_data:
        reference_score += 0.35
        reasons.append(
            f"listing sheet has substantial existing data "
            f"({rows_below_header} rows below header)"
        )
    if existing_product_count > 5:
        reference_score += 0.25
        reasons.append(f"{existing_product_count} existing product rows detected")
    if total_reference_signals >= 2:
        reference_score += 0.20
        reasons.append(
            f"{total_reference_signals} reference/instruction sheet signals "
            f"(instruction_sheets={instruction_count}, "
            f"reference_sheet_names={reference_sheet_count})"
        )

    # Instruction signals
    if not has_reliable_listing:
        instruction_score += 0.5
        reasons.append("no reliable listing sheet found")
    if instruction_count >= 2:
        instruction_score += 0.3

    # Mixed signals (listing + reference content)
    if has_reliable_listing and has_reliable_header and total_reference_signals >= 2:
        mixed_score = (fillable_score + reference_score) * 0.5
        reasons.append("workbook has both listing structure and substantial reference content")

    # ── Determine purpose ──────────────────────────────────────────────────
    if not listing:
        if instruction_count > 0:
            purpose = "instruction_workbook"
            confidence = min(0.8, 0.5 + instruction_score * 0.3)
            reasons.append("no listing sheet; instruction sheets present")
        else:
            purpose = "unsupported"
            confidence = 0.5
            reasons.append("no listing sheet and no recognisable structure")
            findings.append(Finding(
                severity="blocking",
                code="NO_LISTING_SHEET",
                message="No listing sheet could be detected in this workbook",
            ))

    elif ambiguous_listing:
        purpose = "requires_review"
        confidence = 0.55
        reasons.append(
            f"{len(candidate_listing_sheets)} equally likely listing sheet candidates; "
            "human selection required"
        )
        findings.append(Finding(
            severity="review_required",
            code="AMBIGUOUS_LISTING_SHEET",
            message=f"Multiple listing sheet candidates with similar confidence: "
                    f"{[s.name for s in candidate_listing_sheets]}",
        ))

    elif mixed_score > 0.35 and reference_score > 0.25 and fillable_score > 0.30:
        purpose = "mixed_workbook"
        confidence = round(min(mixed_score, 0.90), 2)
        findings.append(Finding(
            severity="review_required",
            code="MIXED_WORKBOOK",
            message="Workbook contains both a listing sheet and substantial reference/instruction content; "
                    "confirm the production listing sheet before filling",
        ))

    elif reference_score > fillable_score and reference_score > 0.30:
        purpose = "reference_workbook"
        confidence = round(min(reference_score, 0.95), 2)
        findings.append(Finding(
            severity="blocking",
            code="REFERENCE_WORKBOOK",
            message="Workbook appears to be a reference or populated data file, not a blank upload template; "
                    "explicit approval required before filling",
        ))

    elif fillable_score >= 0.45:
        purpose = "fillable_template"
        confidence = round(min(fillable_score, 0.98), 2)
    else:
        purpose = "requires_review"
        confidence = round(fillable_score, 2)
        reasons.append(f"classification scores inconclusive (fillable={fillable_score:.2f}, "
                       f"reference={reference_score:.2f})")
        findings.append(Finding(
            severity="review_required",
            code="INCONCLUSIVE_PURPOSE",
            message="Workbook purpose could not be determined with confidence; review required",
        ))

    return PurposeClassification(
        purpose=purpose,
        confidence=confidence,
        reasons=reasons,
        findings=findings,
        category_resolution_status=cat_status,
    )
