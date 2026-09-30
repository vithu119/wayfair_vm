"""
Validate mapped values against template constraints:
  - required field is empty
  - value not in controlled valid-value list
  - value exceeds character limit
"""
from __future__ import annotations
from dataclasses import dataclass
from app.autofill.mapper import MappingResult


@dataclass
class ValidationIssue:
    row_index: int             # 0-based product row index
    sku: str
    wayfair_field: str
    issue_type: str            # "missing_required" | "invalid_value" | "char_limit" | "transform_warning"
    detail: str
    severity: str              # "error" | "warning"
    value: str


def validate_row(
    results: list[MappingResult],
    row_index: int,
    sku: str,
    valid_values_map: dict[str, list[str]],   # norm_field -> allowed values
    char_limits: dict[str, int],              # norm_field -> limit
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for mr in results:
        from app.autofill.mapper import _norm
        norm = _norm(mr.wayfair_field)

        # Missing required field
        if mr.is_required and mr.is_empty:
            issues.append(ValidationIssue(
                row_index=row_index,
                sku=sku,
                wayfair_field=mr.wayfair_field,
                issue_type="missing_required",
                detail=f"Required field is empty (source_field={mr.source_field!r}, source={mr.source})",
                severity="error",
                value="",
            ))

        # Transform warning
        if mr.transform_warning:
            issues.append(ValidationIssue(
                row_index=row_index,
                sku=sku,
                wayfair_field=mr.wayfair_field,
                issue_type="transform_warning",
                detail=mr.transform_warning,
                severity="warning",
                value=mr.final_value,
            ))

        # Valid-value check (only when value is non-empty and field is controlled)
        if mr.final_value and norm in valid_values_map:
            allowed = valid_values_map[norm]
            # Multi-value fields use semicolons
            submitted_vals = [v.strip() for v in mr.final_value.split(";") if v.strip()]
            bad = [v for v in submitted_vals if v not in allowed]
            if bad:
                issues.append(ValidationIssue(
                    row_index=row_index,
                    sku=sku,
                    wayfair_field=mr.wayfair_field,
                    issue_type="invalid_value",
                    detail=f"Value(s) not in valid-value list: {bad!r}",
                    severity="warning",
                    value=mr.final_value,
                ))

        # Character limit check
        if mr.final_value and norm in char_limits:
            limit = char_limits[norm]
            if len(mr.final_value) > limit:
                issues.append(ValidationIssue(
                    row_index=row_index,
                    sku=sku,
                    wayfair_field=mr.wayfair_field,
                    issue_type="char_limit",
                    detail=f"Value length {len(mr.final_value)} exceeds limit of {limit}",
                    severity="warning",
                    value=mr.final_value[:80] + "…",
                ))

    return issues
