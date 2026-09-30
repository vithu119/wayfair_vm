from __future__ import annotations
import logging
import re as _re
from fastapi import APIRouter, Depends, HTTPException
from app.sources.configurator_sot_source import (
    get_connection_status, resolve_asin, get_sot_attributes,
    get_image_urls, get_title, get_bullet_points, get_description,
)
from app.sources.sot_value_parser import parse_sot_value, convert_unit
from app.sources.postgres_guard import assert_read_only
from app.api.auth import get_current_user
import yaml
from pathlib import Path

router = APIRouter(prefix="/sot", tags=["sot"], dependencies=[Depends(get_current_user)])
logger = logging.getLogger(__name__)

_status_cache: dict = {}
_status_cache_until: float = 0.0

_CONFIG_DIR = Path("config")


def _load_sot_mappings() -> list[dict]:
    p = _CONFIG_DIR / "configurator_sot_mappings.yaml"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("mappings", [])


def _extract_numeric(raw_value: str) -> str:
    """Strip unit suffix from measurements like '25mm' → '25'"""
    m = _re.match(r'^([\d.]+)', raw_value.strip())
    if m:
        return m.group(1)
    return raw_value


@router.get("/status")
async def sot_status():
    """Return safe connection status — cached for 30 s to avoid pool exhaustion."""
    import time
    from app.sources.postgres_guard import approved_tables
    global _status_cache, _status_cache_until
    now = time.monotonic()
    if now < _status_cache_until and _status_cache:
        return _status_cache
    status = get_connection_status()
    _status_cache = {
        "source": "Configurator SOT",
        "connected": status["connected"],
        "read_only": status.get("read_only", False),
        "error": status.get("error"),
        "approved_tables": sorted(approved_tables()),
    }
    _status_cache_until = now + 30.0
    return _status_cache




@router.post("/resolve")
async def resolve_asins_sot(body: dict):
    """Resolve one or more ASINs. One failure does not stop others."""
    asins = body.get("asins", [])
    if not asins:
        raise HTTPException(status_code=422, detail="No ASINs provided")

    results = []
    for asin in asins:
        asin_clean = asin.strip().upper()
        identity = resolve_asin(asin_clean)
        results.append({
            "input_asin": identity.input_asin,
            "asin": identity.asin,
            "internal_sku": identity.internal_sku,
            "primary_sku": identity.primary_sku,
            "component_skus": identity.component_skus,
            "child_asins": identity.child_asins,
            "source_tab": identity.source_tab,
            "product_subtype": identity.product_subtype,
            "wayfair_category": identity.wayfair_category,
            "channel": identity.channel,
            "validation_status": identity.validation_status,
            "status": identity.status,
            "evidence": identity.evidence,
            "warnings": identity.warnings,
        })
    return {"results": results}


@router.post("/attributes")
async def get_attributes_sot(body: dict):
    """Get SOT attributes for a resolved SKU."""
    sku = body.get("sku", "").strip()
    if not sku:
        raise HTTPException(status_code=422, detail="No SKU provided")

    attribute_keys = body.get("attribute_keys")  # optional filter
    attrs = get_sot_attributes(sku, attribute_keys)

    return {
        "sku": sku,
        "attribute_count": len(attrs),
        "attributes": [
            {
                "attribute_id": a.attribute_id,
                "attribute_key": a.attribute_key,
                "attribute_label": a.attribute_label,
                "value": a.value,
                "display_order": a.display_order,
                "source_tab": a.source_tab,
            }
            for a in attrs
        ],
    }


@router.post("/fill")
async def fill_from_sot(body: dict):
    """
    Resolve ASIN → SKU → SOT attributes → map to Wayfair template fields.
    Returns filled fields with evidence for preview.
    """
    asin = body.get("asin", "").strip().upper()
    template_headers = body.get("template_headers", [])  # exact Wayfair headers from profile

    if not asin:
        raise HTTPException(status_code=422, detail="No ASIN provided")

    # Resolve ASIN — if parent, expand to children and fill each
    identity = resolve_asin(asin)
    if identity.status == "parent_asin":
        return {
            "asin": asin,
            "status": "parent_asin",
            "child_asins": identity.child_asins,
            "evidence": identity.evidence,
            "warnings": identity.warnings,
            "message": f"{asin} is a parent ASIN with {len(identity.child_asins)} variants. Submit child ASINs individually.",
        }
    if identity.status != "resolved":
        return {
            "asin": asin,
            "status": identity.status,
            "warnings": identity.warnings,
            "fields": {},
            "evidence": {},
            "findings": [{"type": identity.status, "message": f"ASIN resolution failed: {identity.status}"}],
        }

    sku = identity.primary_sku

    # Load mappings
    mappings = _load_sot_mappings()
    approved = [m for m in mappings if m.get("mapping_status") == "approved"]

    # Build SOT key set needed (exclude synthetic __ keys)
    _SYNTHETIC_KEYS = frozenset({
        "__sku__", "__image_url_1__", "__image_url_2__", "__image_url_3__",
        "__image_url_4__", "__image_url_5__", "__video_url_1__",
        "__bullet_1__", "__bullet_2__", "__bullet_3__", "__bullet_4__", "__bullet_5__",
        "__description__", "__base_cost__",
    })
    needed_keys = [m["sot_key"] for m in approved if m["sot_key"] not in _SYNTHETIC_KEYS]

    # Lazy-load expensive lookups only when needed
    _image_urls: list[str] | None = None
    _bullet_points: list[str] | None = None

    def _get_image_urls() -> list[str]:
        nonlocal _image_urls
        if _image_urls is None:
            _image_urls = get_image_urls(sku)
        return _image_urls

    def _get_bullet_points() -> list[str]:
        nonlocal _bullet_points
        if _bullet_points is None:
            _bullet_points = get_bullet_points(sku, asin=asin)
        return _bullet_points

    # Retrieve SOT attributes
    attrs = get_sot_attributes(sku, needed_keys if needed_keys else None)
    attr_by_key: dict[str, str] = {}
    for a in attrs:
        if a.attribute_key not in attr_by_key:
            attr_by_key[a.attribute_key] = a.value

    # Determine category
    wayfair_category = identity.wayfair_category or ""

    # Map fields
    fields: dict[str, str] = {}
    evidence: dict[str, dict] = {}
    findings: list[dict] = []

    def norm(s: str) -> str:
        s = s.strip().lower()
        s = _re.sub(r"[\s\-/]+", "_", s)
        s = _re.sub(r"[^\w]", "", s)
        return s

    # Build a map of normalized header → original header for template headers
    header_norm_map = {norm(h): h for h in template_headers} if template_headers else {}

    for mapping in approved:
        wayfair_header = mapping["wayfair_header"]
        sot_key = mapping["sot_key"]
        cats = mapping.get("categories", ["all"])
        transformation = mapping.get("transformation")

        # Category filter
        if "all" not in cats and wayfair_category not in cats:
            continue

        # Check if header exists in template
        target_header = None
        if template_headers:
            # Try exact match first
            if wayfair_header in template_headers:
                target_header = wayfair_header
            else:
                # Try alias match
                for alias in mapping.get("wayfair_aliases", []):
                    if norm(alias) in header_norm_map:
                        target_header = header_norm_map[norm(alias)]
                        break
            if target_header is None:
                continue  # skip — not in template
        else:
            target_header = wayfair_header

        # Get value — synthetic keys resolved here
        raw_value = None
        transform_applied = None

        if sot_key == "__sku__":
            raw_value = sku
        elif sot_key.startswith("__image_url_"):
            idx = int(sot_key.replace("__image_url_", "").replace("__", "")) - 1
            urls = _get_image_urls()
            raw_value = urls[idx] if idx < len(urls) else None
        elif sot_key == "__video_url_1__":
            raw_value = None  # no video source implemented yet
        elif sot_key == "__description__":
            raw_value = get_description(sku, asin=asin)
        elif sot_key.startswith("__bullet_"):
            idx = int(sot_key.replace("__bullet_", "").replace("__", "")) - 1
            bullets = _get_bullet_points()
            raw_value = bullets[idx] if idx < len(bullets) else None
        elif sot_key == "__base_cost__":
            from app.sources.postgres_connection import readonly_cursor
            _bc_unverified = False
            try:
                with readonly_cursor() as cur:
                    cur.execute("""
                        SELECT COALESCE(price, 0), COALESCE(price_per_order, 0)
                        FROM public.listing_data
                        WHERE ref_id = %s AND wrong_sku = 0
                          AND status ILIKE 'active' OR status IN ('DISCOVERABLE', 'BUYABLE', '1')
                          AND which_channel_name ILIKE '%%amazon%%'
                          AND price IS NOT NULL
                        ORDER BY (CASE WHEN market_place = 'UK' THEN 0 ELSE 1 END), id
                        LIMIT 1
                    """, (asin,))
                    row = cur.fetchone()
                if not row:
                    with readonly_cursor() as cur:
                        cur.execute("""
                            SELECT COALESCE(price, 0), COALESCE(price_per_order, 0)
                            FROM public.listing_data
                            WHERE ref_id = %s AND status ILIKE 'active' OR status IN ('DISCOVERABLE', 'BUYABLE', '1')
                              AND which_channel_name ILIKE '%%amazon%%'
                              AND price IS NOT NULL
                            ORDER BY (CASE WHEN market_place = 'UK' THEN 0 ELSE 1 END), id
                            LIMIT 1
                        """, (asin,))
                        row = cur.fetchone()
                    _bc_unverified = row is not None
                raw_value = str(round((float(row[0]) + float(row[1])) * 0.60, 2)) if row else None
                if raw_value and _bc_unverified:
                    findings.append({
                        "type": "warning",
                        "field": target_header,
                        "message": "Base Cost calculated from unverified SKU (wrong_sku=1). Please verify the SKU is correct.",
                    })
            except Exception:
                raw_value = None
        else:
            raw_value = attr_by_key.get(sot_key)

        if raw_value is None:
            findings.append({
                "type": "sot_attribute_missing",
                "field": target_header,
                "sot_key": sot_key,
                "message": f"SOT attribute '{sot_key}' not found for SKU {sku}",
            })
            continue

        # Parse and transform value
        parsed = parse_sot_value(raw_value)
        final_value = raw_value

        if transformation == "mm_to_numeric":
            final_value = _extract_numeric(raw_value)
            transform_applied = "strip_mm_unit"
        elif transformation == "mm_to_cm":
            if parsed.value_type == "measurement" and parsed.numeric is not None:
                converted = convert_unit(parsed, "cm")
                final_value = str(converted.parsed_value)
                transform_applied = "mm_to_cm"
            else:
                try:
                    final_value = str(round(float(_extract_numeric(raw_value)) * 0.1, 4))
                    transform_applied = "mm_to_cm_numeric"
                except ValueError:
                    final_value = _extract_numeric(raw_value)
                    transform_applied = "strip_unit"
        elif transformation == "g_to_kg":
            if parsed.value_type == "measurement" and parsed.numeric is not None:
                converted = convert_unit(parsed, "kg")
                final_value = str(converted.parsed_value)
                transform_applied = "g_to_kg"
            else:
                final_value = _extract_numeric(raw_value)
                transform_applied = "strip_unit"
        elif transformation == "marketing_copy":
            final_value = _re.sub(r'[™©®℠†‡•·°]', '', final_value)
            final_value = _re.sub(r'[\U0001D400-\U0001D7FF]', '', final_value)
            final_value = _re.sub(r'<[^>]+>', ' ', final_value)
            final_value = _re.sub(r'[\r\n\t]+', ' ', final_value)
            final_value = _re.sub(r' {2,}', ' ', final_value).strip()[:4000]
            transform_applied = "marketing_copy"

        fields[target_header] = final_value
        evidence[target_header] = {
            "wayfair_field": target_header,
            "selected_value": final_value,
            "sot_attribute_key": sot_key,
            "raw_value": raw_value,
            "parsed_value": str(parsed.parsed_value),
            "unit": parsed.unit,
            "transformation": transform_applied,
            "mapping_status": mapping["mapping_status"],
            "source_tab": identity.source_tab,
            "sku": sku,
        }

    return {
        "asin": asin,
        "sku": sku,
        "primary_sku": identity.primary_sku,
        "component_skus": identity.component_skus,
        "source_tab": identity.source_tab,
        "product_subtype": identity.product_subtype,
        "wayfair_category": identity.wayfair_category,
        "status": "filled",
        "fields": fields,
        "evidence": evidence,
        "findings": findings,
        "identity_evidence": identity.evidence,
        "warnings": identity.warnings,
    }


@router.get("/debug-bullets")
async def debug_bullets(asin: str, sku: str | None = None):
    """Debug endpoint — tests listing_data join by ref_id (ASIN) and by sku column."""
    from app.sources.postgres_connection import readonly_cursor
    result: dict = {"asin": asin, "sku": sku}

    # Path 1: listing_data.ref_id = ASIN
    sql_by_asin = """
        SELECT bp.points, bp.view_order
        FROM public.bullet_points bp
        JOIN public.listing_data ld ON ld.id = bp.product_id
        WHERE ld.ref_id = %s AND bp.points IS NOT NULL AND bp.points != ''
        ORDER BY bp.view_order
    """
    try:
        with readonly_cursor() as cur:
            cur.execute(sql_by_asin, (asin.strip().upper(),))
            rows = cur.fetchall()
        result["by_ref_id"] = {"count": len(rows), "bullets": [r[0] for r in rows], "error": None}
    except Exception as exc:
        result["by_ref_id"] = {"count": 0, "bullets": [], "error": f"{type(exc).__name__}: {exc}"}

    # Path 2: listing_data.sku = SKU (when ref_id is not ASIN-based)
    if sku:
        sql_by_sku = """
            SELECT bp.points, bp.view_order
            FROM public.bullet_points bp
            JOIN public.listing_data ld ON ld.id = bp.product_id
            WHERE ld.sku = %s AND bp.points IS NOT NULL AND bp.points != ''
            ORDER BY bp.view_order
        """
        try:
            with readonly_cursor() as cur:
                cur.execute(sql_by_sku, (sku.strip(),))
                rows = cur.fetchall()
            result["by_sku"] = {"count": len(rows), "bullets": [r[0] for r in rows], "error": None}
        except Exception as exc:
            result["by_sku"] = {"count": 0, "bullets": [], "error": f"{type(exc).__name__}: {exc}"}

    # Path 3: batch ANY(%s) test — same query pattern used in batch_get_sot_rows
    sql_batch = """
        SELECT DISTINCT ON (ld.ref_id, bp.view_order) ld.ref_id, bp.points, bp.view_order
        FROM public.bullet_points bp
        JOIN public.listing_data ld ON ld.id = bp.product_id
        WHERE ld.ref_id = ANY(%s) AND bp.points IS NOT NULL AND bp.points != ''
        ORDER BY ld.ref_id, bp.view_order, bp.id
    """
    try:
        with readonly_cursor() as cur:
            cur.execute(sql_batch, ([asin.strip().upper()],))
            rows = cur.fetchall()
        result["batch_any"] = {"count": len(rows), "bullets": [r[1] for r in rows], "error": None}
    except Exception as exc:
        result["batch_any"] = {"count": 0, "bullets": [], "error": f"{type(exc).__name__}: {exc}"}

    return result
