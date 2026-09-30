"""
Template registration workflow.

Full pipeline for a single workbook upload:
  hash workbook
  → inspect (analyse sheet structure, detect headers, extract column metadata)
  → classify rows below the header (detect safe write area)
  → classify workbook purpose
  → determine fill status
  → enrich profile with Phase 4A fields
  → write profile JSON
  → register in template registry

Does not modify the original workbook.
Does not depend on filename patterns, known categories, or fixed row numbers.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import openpyxl

from app.analyser.inspector import inspect_workbook, WorkbookProfile
from app.analyser.profile_writer import write_profile
from app.analyser.integrity import sha256_file
from app.analyser.purpose_classifier import classify_purpose, PurposeClassification
from app.analyser.fill_status import determine_fill_status
from app.analyser.findings import Finding, blocking_messages, warning_messages
from app.analyser.template_registry import (
    TemplateRegistry, RegistryEntry, make_template_id,
)
from app.autofill.row_detector import classify_data_area
from app.autofill.write_policy import build_write_plan


@dataclass
class RegistrationResult:
    template_id: str
    filename: str
    registry_entry: RegistryEntry | None
    profile: WorkbookProfile | None
    purpose: PurposeClassification | None
    fill_status: str
    blocking_reasons: list[str]
    warnings: list[str]
    safe_write_start_row: int | None = None
    row_summary: dict = field(default_factory=dict)
    error: str | None = None


def _classify_rows_for_profile(
    path: Path,
    listing_sheet_name: str,
    header_row: int,
    max_col: int,
) -> tuple[dict, int | None]:
    """
    Open the workbook read-only, classify all rows below the header,
    return (row_summary_dict, safe_write_start_row).
    """
    summary = {
        "existing_product_count": 0,
        "sample_count": 0,
        "metadata_row_count": 0,
        "template_control_count": 0,
        "instruction_row_count": 0,
        "blank_count": 0,
        "unknown_count": 0,
        "total_scanned": 0,
    }
    safe_write_start: int | None = None

    try:
        wb = openpyxl.load_workbook(str(path), data_only=True)
        if listing_sheet_name not in wb.sheetnames:
            wb.close()
            return summary, None
        ws = wb[listing_sheet_name]

        # Build col_map from header row
        col_map: dict[str, int] = {}
        for c in range(1, max_col + 1):
            cell = ws.cell(header_row, c)
            if cell.value is not None:
                h = str(cell.value).strip()
                if h and h not in col_map:
                    col_map[h] = c

        if not col_map:
            wb.close()
            return summary, None

        # Use actual max_row (works in non-read-only mode)
        max_row = ws.max_row or header_row
        classifications = classify_data_area(
            ws=ws,
            header_row=header_row,
            col_map=col_map,
            max_row=max_row if max_row > header_row else None,
        )
        wb.close()

        for rc in classifications:
            summary["total_scanned"] += 1
            if rc.status == "existing_product":
                summary["existing_product_count"] += 1
            elif rc.status == "sample_candidate":
                summary["sample_count"] += 1
            elif rc.status == "metadata":
                summary["metadata_row_count"] += 1
            elif rc.status == "template_control_row":
                summary["template_control_count"] += 1
            elif rc.status == "instruction_or_note":
                summary["instruction_row_count"] += 1
            elif rc.status == "blank":
                summary["blank_count"] += 1
            else:
                summary["unknown_count"] += 1

        # Compute safe_write_start_row using append logic
        if classifications:
            try:
                plan = build_write_plan(classifications, "append", 1)
                safe_write_start = plan.first_write_row
            except Exception:
                pass

    except Exception:
        pass

    return summary, safe_write_start


def register_workbook(
    template_path: Path,
    profile_dir: Path,
    registry: TemplateRegistry,
) -> RegistrationResult:
    """
    Full registration pipeline for one workbook.
    Modifies registry in-place; caller must call registry.save().
    """
    filename = template_path.name

    # ── Hash ───────────────────────────────────────────────────────────────
    try:
        file_hash = sha256_file(template_path)
    except Exception as e:
        return RegistrationResult(
            template_id="",
            filename=filename,
            registry_entry=None,
            profile=None,
            purpose=None,
            fill_status="not_fillable",
            blocking_reasons=[f"Cannot hash file: {e}"],
            warnings=[],
            error=str(e),
        )

    template_id = make_template_id(file_hash)

    # ── Duplicate hash check ───────────────────────────────────────────────
    existing = registry.find_by_hash(file_hash)
    if existing is not None:
        return RegistrationResult(
            template_id=existing.template_id,
            filename=filename,
            registry_entry=existing,
            profile=None,
            purpose=None,
            fill_status=existing.fill_status,
            blocking_reasons=existing.blocking_reasons,
            warnings=existing.warnings,
        )

    # ── Inspect ────────────────────────────────────────────────────────────
    try:
        profile = inspect_workbook(template_path)
    except Exception as e:
        return RegistrationResult(
            template_id=template_id,
            filename=filename,
            registry_entry=None,
            profile=None,
            purpose=None,
            fill_status="not_fillable",
            blocking_reasons=[f"Workbook inspection failed: {e}"],
            warnings=[],
            error=str(e),
        )

    # ── Row classification ─────────────────────────────────────────────────
    row_summary: dict = {}
    safe_write_start: int | None = None

    if profile.listing_sheet and profile.listing_sheet.detection:
        det = profile.listing_sheet.detection
        listing_name = profile.listing_sheet.name
        header_row = det.header_row
        max_col = profile.listing_sheet.max_col

        row_summary, safe_write_start = _classify_rows_for_profile(
            template_path, listing_name, header_row, max_col
        )

    # ── Purpose classification ─────────────────────────────────────────────
    purpose_cls = classify_purpose(profile, row_summary)

    # ── Fill status ────────────────────────────────────────────────────────
    fill_status, findings = determine_fill_status(profile, purpose_cls)

    # ── Enrich profile ─────────────────────────────────────────────────────
    profile.template_purpose = purpose_cls.purpose
    profile.template_purpose_confidence = purpose_cls.confidence
    profile.template_purpose_reasons = purpose_cls.reasons
    profile.template_fill_status = fill_status
    profile.category_resolution_status = purpose_cls.category_resolution_status
    profile.blocking_reasons = blocking_messages(findings)
    profile.row_classification_summary = row_summary
    profile.safe_write_start_row = safe_write_start

    # ── Write profile ──────────────────────────────────────────────────────
    profile_dir.mkdir(parents=True, exist_ok=True)
    try:
        profile_path = write_profile(profile, profile_dir)
    except Exception as e:
        profile_path = profile_dir / "unknown_profile.json"
        profile.warnings.append(f"Profile write failed: {e}")

    # ── Build registry entry ───────────────────────────────────────────────
    entry = RegistryEntry(
        template_id=template_id,
        filename=filename,
        file_hash=file_hash,
        category=profile.category_name or "unknown",
        category_status=purpose_cls.category_resolution_status,
        template_purpose=purpose_cls.purpose,
        template_purpose_confidence=purpose_cls.confidence,
        fill_status=fill_status,
        listing_sheet=profile.listing_sheet.name if profile.listing_sheet else None,
        header_row=(
            profile.listing_sheet.detection.header_row
            if profile.listing_sheet and profile.listing_sheet.detection else None
        ),
        safe_write_start_row=safe_write_start,
        profile_path=str(profile_path.relative_to(profile_dir.parent))
        if profile_path.exists() else str(profile_path),
        analysis_timestamp=profile.analysis_timestamp,
        registration_timestamp=datetime.now(timezone.utc).isoformat(),
        warnings=warning_messages(findings) + profile.warnings,
        blocking_reasons=blocking_messages(findings),
    )

    registry.register(entry)

    return RegistrationResult(
        template_id=template_id,
        filename=filename,
        registry_entry=entry,
        profile=profile,
        purpose=purpose_cls,
        fill_status=fill_status,
        blocking_reasons=entry.blocking_reasons,
        warnings=entry.warnings,
        safe_write_start_row=safe_write_start,
        row_summary=row_summary,
    )


def register_bulk(
    template_paths: list[Path],
    profile_dir: Path,
    registry_dir: Path,
) -> tuple[list[RegistrationResult], TemplateRegistry]:
    """
    Register multiple workbooks.  One failure does not stop the batch.
    Saves the registry after all registrations complete.
    """
    registry_json = registry_dir / "template_registry.json"
    registry_csv = registry_dir / "template_registry.csv"
    registry = TemplateRegistry.load(registry_json)
    results: list[RegistrationResult] = []

    for path in template_paths:
        if path.suffix.lower() not in (".xlsx", ".csv"):
            results.append(RegistrationResult(
                template_id="",
                filename=path.name,
                registry_entry=None,
                profile=None,
                purpose=None,
                fill_status="not_fillable",
                blocking_reasons=[f"Unsupported file extension: {path.suffix}"],
                warnings=[],
                error="unsupported_extension",
            ))
            continue

        try:
            result = register_workbook(path, profile_dir, registry)
        except Exception as exc:
            result = RegistrationResult(
                template_id="",
                filename=path.name,
                registry_entry=None,
                profile=None,
                purpose=None,
                fill_status="not_fillable",
                blocking_reasons=[str(exc)],
                warnings=[],
                error=str(exc),
            )
        results.append(result)

    registry.save(registry_json, registry_csv)
    return results, registry
