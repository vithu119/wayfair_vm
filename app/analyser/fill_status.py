"""
Determine template_fill_status from purpose classification and profile findings.

Supported values:
  fillable              - safe to fill automatically
  fillable_with_warnings - safe to fill; review warnings before submission
  not_fillable          - must not be filled (blocking reason exists)
  requires_review       - may be fillable; human confirmation needed first

This is explicitly separate from analysis_status.

A partial analysis_status does NOT prevent filling if no blocking reason exists.
A successful analysis_status does NOT guarantee fillability (e.g. reference workbook).
"""
from __future__ import annotations

from app.analyser.findings import Finding, has_blocking, has_review_required


# Minimum header confidence to allow auto-fill
HEADER_CONFIDENCE_THRESHOLD = 0.40


def determine_fill_status(
    profile,                           # WorkbookProfile
    purpose_cls,                       # PurposeClassification
) -> tuple[str, list[Finding]]:
    """
    Return (fill_status, additional_findings).
    Merges structural findings from the profile with purpose findings.
    """
    findings: list[Finding] = list(purpose_cls.findings)

    listing = getattr(profile, "listing_sheet", None)
    det = listing.detection if listing else None

    # ── Blocking conditions ────────────────────────────────────────────────

    # 1. Purpose is reference-only or unsupported
    if purpose_cls.purpose in ("reference_workbook", "unsupported", "instruction_workbook"):
        findings.append(Finding(
            severity="blocking",
            code="PURPOSE_NOT_FILLABLE",
            message=f"Workbook purpose '{purpose_cls.purpose}' is not suitable for auto-fill",
        ))

    # 2. No listing sheet
    if not listing:
        findings.append(Finding(
            severity="blocking",
            code="NO_LISTING_SHEET",
            message="No listing sheet detected",
        ))

    # 3. No header detection
    elif det is None:
        findings.append(Finding(
            severity="blocking",
            code="NO_HEADER_DETECTION",
            message="Header row could not be determined for the listing sheet",
        ))

    # 4. Header confidence too low
    elif det.confidence < HEADER_CONFIDENCE_THRESHOLD:
        findings.append(Finding(
            severity="blocking",
            code="LOW_HEADER_CONFIDENCE",
            message=f"Header detection confidence ({det.confidence:.2f}) is below the "
                    f"threshold ({HEADER_CONFIDENCE_THRESHOLD})",
        ))

    # 5. No columns
    if listing and len(getattr(listing, "columns", [])) == 0:
        findings.append(Finding(
            severity="blocking",
            code="NO_COLUMNS_DETECTED",
            message="No listing columns were detected; cannot map product data",
        ))

    # 6. Duplicate headers
    if listing:
        headers = [c.original_header for c in getattr(listing, "columns", [])]
        seen: set[str] = set()
        dupes: list[str] = []
        for h in headers:
            hn = h.strip().lower()
            if hn and hn in seen:
                dupes.append(h)
            elif hn:
                seen.add(hn)
        if dupes:
            findings.append(Finding(
                severity="blocking",
                code="DUPLICATE_HEADERS",
                message=f"Duplicate listing headers prevent deterministic column mapping: "
                        f"{dupes[:3]}",
            ))

    # ── Non-blocking findings ─────────────────────────────────────────────

    # Provisional/unknown category
    cat_status = getattr(profile, "category_resolution_status", "unknown")
    if cat_status in ("provisional", "unknown"):
        findings.append(Finding(
            severity="warning",
            code="PROVISIONAL_CATEGORY",
            message=f"Category '{getattr(profile, 'category_name', '')}' is {cat_status}; "
                    "manual routing approval recommended before filling",
        ))

    # Analysis status partial (informational; not blocking)
    if getattr(profile, "analysis_status", "ok") == "partial":
        findings.append(Finding(
            severity="info",
            code="PARTIAL_ANALYSIS",
            message="Analysis status is 'partial' due to non-critical warnings; "
                    "fill proceeds unless a specific blocking reason is present",
        ))

    # Unknown optional sheet types
    unknown_sheets = [
        s.name for s in getattr(profile, "sheets", [])
        if s.classification.sheet_type == "unknown"
    ]
    for sname in unknown_sheets:
        findings.append(Finding(
            severity="warning",
            code="UNKNOWN_SHEET",
            message=f"Sheet {sname!r} could not be classified; "
                    "it will be preserved but not used for filling",
            sheet=sname,
        ))

    # Mixed workbook — needs explicit confirmation
    if purpose_cls.purpose == "mixed_workbook":
        findings.append(Finding(
            severity="review_required",
            code="MIXED_WORKBOOK_FILL",
            message="Workbook is mixed (listing + reference content); "
                    "confirm the listing sheet is the correct production upload sheet",
        ))

    # ── Determine final status ─────────────────────────────────────────────
    if has_blocking(findings):
        fill_status = "not_fillable"

    elif has_review_required(findings):
        fill_status = "requires_review"

    elif any(f.severity == "warning" for f in findings):
        fill_status = "fillable_with_warnings"

    else:
        fill_status = "fillable"

    return fill_status, findings
