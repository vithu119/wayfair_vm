"""
Write-policy engine: given row classifications and a chosen policy, compute
the exact target rows where product data will be written.

Policies
--------
append              (default) - append after the last existing product row;
                               fall back to first blank row if none exist.
fill-first-blank    - write into the first blank row and continue sequentially.
replace-samples     - overwrite sample/placeholder rows; append if more incoming
                     than sample rows.
replace-all-products - overwrite every existing-product row; append if more
                     incoming than existing rows. MUST be explicitly requested.
preview-only        - compute the write plan but signal the writer NOT to
                     change any cells.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from app.autofill.row_detector import RowClassification

VALID_POLICIES = frozenset({
    "append",
    "fill-first-blank",
    "replace-samples",
    "replace-all-products",
    "preview-only",
})

DEFAULT_POLICY = "append"


@dataclass
class WritePlan:
    policy: str
    target_rows: list[int]          # 1-based Excel row numbers to write to
    first_write_row: int            # first target row (convenience alias)
    existing_product_rows: list[int]
    sample_rows: list[int]
    blank_rows: list[int]
    is_preview: bool = False
    warnings: list[str] = field(default_factory=list)


def build_write_plan(
    classifications: list[RowClassification],
    policy: str,
    incoming_count: int,
) -> WritePlan:
    """
    Build a WritePlan from row classifications.

    Parameters
    ----------
    classifications : output of classify_data_area (ordered by row_number)
    policy          : one of VALID_POLICIES
    incoming_count  : number of product rows we want to write
    """
    if policy not in VALID_POLICIES:
        raise ValueError(
            f"Unknown write policy {policy!r}. "
            f"Valid choices: {sorted(VALID_POLICIES)}"
        )

    existing_rows = [rc.row_number for rc in classifications
                     if rc.status == "existing_product"]
    sample_rows   = [rc.row_number for rc in classifications
                     if rc.status == "sample_candidate"]
    blank_rows    = [rc.row_number for rc in classifications
                     if rc.status == "blank"]

    warnings: list[str] = []
    is_preview = policy == "preview-only"

    # ── APPEND ────────────────────────────────────────────────────────────
    if policy in ("append", "preview-only"):
        if existing_rows:
            first_write = max(existing_rows) + 1
        elif classifications:
            # Find the first blank row that follows all non-blank rows
            last_nonblank = max(
                (rc.row_number for rc in classifications if rc.status != "blank"),
                default=classifications[0].row_number - 1,
            )
            after_nonblank = [r for r in blank_rows if r > last_nonblank]
            if after_nonblank:
                first_write = after_nonblank[0]
            else:
                # All rows are non-blank or no rows scanned – append at the end
                first_write = (
                    max(rc.row_number for rc in classifications) + 1
                    if classifications else 1
                )
        else:
            first_write = 1
        target_rows = list(range(first_write, first_write + incoming_count))

    # ── FILL-FIRST-BLANK ─────────────────────────────────────────────────
    elif policy == "fill-first-blank":
        if blank_rows:
            first_write = blank_rows[0]
        elif classifications:
            first_write = max(rc.row_number for rc in classifications) + 1
            warnings.append(
                "No blank rows found; appending after the last scanned row."
            )
        else:
            first_write = 1
        target_rows = list(range(first_write, first_write + incoming_count))

    # ── REPLACE-SAMPLES ───────────────────────────────────────────────────
    elif policy == "replace-samples":
        if not sample_rows:
            warnings.append("No sample/placeholder rows found; falling back to append mode.")
            return build_write_plan(classifications, "append", incoming_count)

        if incoming_count <= len(sample_rows):
            target_rows = sample_rows[:incoming_count]
        else:
            # Fill sample rows first, then append
            append_start = max(sample_rows[-1], *(existing_rows or [sample_rows[-1]])) + 1
            # Skip any remaining sample rows between append_start and end
            extra = incoming_count - len(sample_rows)
            target_rows = sample_rows + list(range(append_start, append_start + extra))
            warnings.append(
                f"More incoming rows ({incoming_count}) than sample rows "
                f"({len(sample_rows)}); {extra} row(s) will be appended at row {append_start}."
            )
        first_write = target_rows[0] if target_rows else 1

    # ── REPLACE-ALL-PRODUCTS ─────────────────────────────────────────────
    elif policy == "replace-all-products":
        if not existing_rows:
            msg = "No existing-product rows found; falling back to append mode."
            fallback = build_write_plan(classifications, "append", incoming_count)
            fallback.warnings.insert(0, msg)
            return fallback

        if incoming_count <= len(existing_rows):
            target_rows = existing_rows[:incoming_count]
        else:
            append_start = max(existing_rows) + 1
            extra = incoming_count - len(existing_rows)
            target_rows = existing_rows + list(range(append_start, append_start + extra))
            warnings.append(
                f"More incoming rows ({incoming_count}) than existing-product rows "
                f"({len(existing_rows)}); {extra} row(s) will be appended at row {append_start}."
            )
        first_write = target_rows[0] if target_rows else 1

    else:
        raise RuntimeError(f"Unhandled policy {policy!r}")

    return WritePlan(
        policy=policy,
        target_rows=target_rows,
        first_write_row=first_write,
        existing_product_rows=existing_rows,
        sample_rows=sample_rows,
        blank_rows=blank_rows,
        is_preview=is_preview,
        warnings=warnings,
    )
