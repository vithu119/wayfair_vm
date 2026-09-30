from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends

from app.api.auth import get_current_user
from app.api.models import AsinValidateRequest, AsinValidateResponse, AsinValidationItem

router = APIRouter(prefix="/asins", tags=["asins"], dependencies=[Depends(get_current_user)])

_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")


def _validate_asin(raw: str) -> AsinValidationItem:
    normalized = raw.strip().upper()
    if not normalized:
        return AsinValidationItem(
            input=raw, normalized=normalized, valid=False, reason="Empty value"
        )
    if not _ASIN_RE.match(normalized):
        return AsinValidationItem(
            input=raw,
            normalized=normalized,
            valid=False,
            reason=f"Must be exactly 10 uppercase alphanumeric characters, got {len(normalized)}",
        )
    return AsinValidationItem(input=raw, normalized=normalized, valid=True)


def _has_style_variation(selected_variations: str | None) -> bool:
    """Return True if any variation entry has name=='style' or value contains 'style' (case-insensitive)."""
    if not selected_variations:
        return False
    try:
        variations = json.loads(selected_variations)
        for v in variations:
            if not isinstance(v, dict):
                continue
            if v.get("name", "").lower() == "style":
                return True
            if "style" in v.get("value", "").lower():
                return True
        return False
    except Exception:
        return False


def _batch_fetch_listing_data(asins: list[str]) -> dict[str, dict]:
    """Return {asin: {sku, parent_sku}} from listing_data. Never raises.
    primary_sku is the first component of a composite SKU (e.g. A+B+C → A).
    """
    if not asins:
        return {}
    try:
        from app.sources.postgres_connection import readonly_cursor
        sql = """
            SELECT DISTINCT ON (ref_id) ref_id,
                   COALESCE(mapped_sku, sku) AS resolved_sku,
                   parent_sku
            FROM public.listing_data
            WHERE ref_id = ANY(%s)
              AND COALESCE(mapped_sku, sku) IS NOT NULL
              AND COALESCE(mapped_sku, sku) != ''
              AND (which_channel_name ILIKE '%%amazon%%' OR which_channel_name IS NULL)
            ORDER BY ref_id, (CASE WHEN market_place = 'UK' THEN 0 ELSE 1 END)
        """
        with readonly_cursor() as cur:
            cur.execute(sql, (asins,))
            result = {}
            for ref_id, resolved_sku, parent_sku in cur.fetchall():
                result[ref_id] = {
                    "sku": resolved_sku.strip(),
                    "parent_sku": parent_sku or None,
                }
            return result
    except Exception:
        return {}


@router.post("/validate", response_model=AsinValidateResponse)
async def validate_asins(body: AsinValidateRequest):
    items: list[AsinValidationItem] = []
    seen: dict[str, int] = {}

    for raw in body.asins:
        item = _validate_asin(raw)
        if item.valid:
            if item.normalized in seen:
                item.duplicate = True
            else:
                seen[item.normalized] = 1
        items.append(item)

    # Batch-fetch SKU + parent_sku for valid, non-duplicate ASINs
    valid_asins = [i.normalized for i in items if i.valid and not i.duplicate]
    listing_map = _batch_fetch_listing_data(valid_asins)
    for item in items:
        if item.valid and not item.duplicate:
            data = listing_map.get(item.normalized, {})
            item.sku = data.get("sku")
            item.parent_sku = data.get("parent_sku")

    valid_count = sum(1 for i in items if i.valid and not i.duplicate)
    invalid_count = sum(1 for i in items if not i.valid)
    duplicate_count = sum(1 for i in items if i.duplicate)

    return AsinValidateResponse(
        items=items,
        valid_count=valid_count,
        invalid_count=invalid_count,
        duplicate_count=duplicate_count,
    )
