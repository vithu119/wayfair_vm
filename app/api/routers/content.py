"""
Content conversion endpoints — single and batch Amazon → Wayfair BGCT.
"""
from __future__ import annotations

import asyncio
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/content", tags=["content"], dependencies=[Depends(get_current_user)])


# ── Shared models ─────────────────────────────────────────────────────────────

class ConvertRequest(BaseModel):
    group_ref_id: str = ""
    amazon_title: str
    amazon_bullets: list[str] = Field(default_factory=list)
    amazon_description: str = ""
    variant_terms: list[str] = Field(default_factory=list)


class ConvertResponse(BaseModel):
    group_ref_id: str
    product_name: str
    marketing_copy: str
    marketing_copy_word_count: int
    feature_bullets: list[str]
    status: str
    validation_errors: list[str]
    qc_pass: bool


# ── Single convert ────────────────────────────────────────────────────────────

@router.post("/convert", response_model=ConvertResponse)
async def convert_content(body: ConvertRequest):
    try:
        from app.services.amazon_to_wayfair_converter import convert
        result = await asyncio.to_thread(
            convert,
            amazon_title=body.amazon_title,
            amazon_bullets=body.amazon_bullets,
            amazon_description=body.amazon_description,
            group_ref_id=body.group_ref_id,
            variant_terms=body.variant_terms or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Conversion failed: {exc}")

    return ConvertResponse(
        group_ref_id=result.group_ref_id,
        product_name=result.product_name,
        marketing_copy=result.marketing_copy,
        marketing_copy_word_count=result.marketing_copy_word_count,
        feature_bullets=result.feature_bullets,
        status=result.status,
        validation_errors=result.validation_errors,
        qc_pass=result.status == "valid",
    )


# ── Batch models ──────────────────────────────────────────────────────────────

class BatchRequest(BaseModel):
    asins: list[str]


class BatchItemResult(BaseModel):
    asin: str
    sku: str | None = None
    group_ref_id: str
    product_name: str
    marketing_copy: str
    marketing_copy_word_count: int
    feature_bullets: list[str]
    status: str          # valid | requires_review | error | no_sot_data
    validation_errors: list[str]
    variant_terms: list[str] = Field(default_factory=list)
    qc_pass: bool
    error: str | None = None


class BatchResponse(BaseModel):
    total: int
    converted: int
    errors: int
    results: list[BatchItemResult]


# ── Batch convert ─────────────────────────────────────────────────────────────

def _fetch_amazon_content(asin: str) -> tuple[str | None, list[str], str, str | None, str | None, list[str], str | None]:
    """
    Resolve ASIN via SOT and return (title, bullets, description, primary_sku, listing_sku, variant_terms, parent_sku).
    listing_sku is the full SKU from listing_data (e.g. PLTYBC+ICST64E27).
    primary_sku is the first component (used for SOT lookups).
    Returns (None, [], '', None, None, [], None) if the ASIN cannot be resolved.
    """
    try:
        from app.sources.configurator_sot_source import (
            resolve_asin, get_title, get_bullet_points, get_description,
            get_all_group_variant_values, get_parent_sku_for_asin, get_sibling_titles,
            get_variation_attributes,
        )
    except Exception:
        return None, [], "", None, None, [], None

    identity = resolve_asin(asin)
    if identity.status != "resolved" or not identity.primary_sku:
        return None, [], "", None, None, [], None

    primary_sku = identity.primary_sku
    listing_sku = identity.internal_sku or primary_sku
    title = get_title(primary_sku, asin=asin) or ""
    bullets = get_bullet_points(listing_sku, asin=asin) or []
    description = get_description(primary_sku, asin=asin) or ""

    # Style variants and non-child products are treated as standalone — no variant stripping or grouping.
    # Check via get_variation_attributes first; fall back to listing_data direct query.
    variation_attrs = get_variation_attributes(asin, sku=primary_sku)
    is_style = any(
        v.get("name", "").lower() == "style" or "style" in v.get("value", "").lower()
        for v in variation_attrs
    )
    if not is_style:
        # Direct fallback: query listing_data selected_variations for 'style' keyword
        try:
            from app.sources.postgres_connection import readonly_cursor
            with readonly_cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM public.listing_data WHERE ref_id=%s"
                    " AND selected_variations ILIKE '%%style%%' LIMIT 1",
                    (asin,),
                )
                if cur.fetchone():
                    is_style = True
        except Exception:
            pass

    variant_terms = [] if is_style else get_all_group_variant_values(asin, sku=primary_sku)
    # get_parent_sku_for_asin also excludes style-value ASINs at SQL level
    parent_sku = None if is_style else get_parent_sku_for_asin(asin, sku=primary_sku)
    return title, bullets, description, primary_sku, listing_sku, variant_terms, parent_sku


async def _convert_one(asin: str) -> BatchItemResult:
    from app.services.amazon_to_wayfair_converter import convert

    title, bullets, description, primary_sku, listing_sku, variant_terms, _parent_sku = await asyncio.to_thread(_fetch_amazon_content, asin)

    if not title:
        reason = "No title found in SOT" if listing_sku else "ASIN not found in SOT database"
        logger.warning("No data for ASIN %s: sku=%s primary_sku=%s", asin, listing_sku, primary_sku)
        return BatchItemResult(
            asin=asin,
            sku=listing_sku,
            group_ref_id=asin,
            product_name="",
            marketing_copy="",
            marketing_copy_word_count=0,
            feature_bullets=[],
            status="no_sot_data",
            validation_errors=[],
            qc_pass=False,
            error=reason,
        )

    try:
        result = await asyncio.to_thread(
            convert,
            amazon_title=title,
            amazon_bullets=bullets,
            amazon_description=description,
            group_ref_id=asin,
            variant_terms=variant_terms or None,
        )
        return BatchItemResult(
            asin=asin,
            sku=listing_sku,
            group_ref_id=result.group_ref_id,
            product_name=result.product_name,
            marketing_copy=result.marketing_copy,
            marketing_copy_word_count=result.marketing_copy_word_count,
            feature_bullets=result.feature_bullets,
            status=result.status,
            validation_errors=result.validation_errors,
            variant_terms=result.effective_variant_terms,
            qc_pass=result.status == "valid",
        )
    except Exception as exc:
        import traceback
        logger.error("Batch convert failed for ASIN %s: %s | type=%s | trace=%s",
                     asin, exc, type(exc).__name__, traceback.format_exc())
        return BatchItemResult(
            asin=asin,
            sku=listing_sku,
            group_ref_id=asin,
            product_name="",
            marketing_copy="",
            marketing_copy_word_count=0,
            feature_bullets=[],
            status="error",
            validation_errors=[],
            qc_pass=False,
            error=f"{type(exc).__name__}: {exc}",
        )


def _make_sibling_result(asin: str, sku: str | None, canonical: BatchItemResult) -> BatchItemResult:
    """Copy canonical group content to a sibling ASIN."""
    return BatchItemResult(
        asin=asin,
        sku=sku,
        group_ref_id=canonical.group_ref_id,
        product_name=canonical.product_name,
        marketing_copy=canonical.marketing_copy,
        marketing_copy_word_count=canonical.marketing_copy_word_count,
        feature_bullets=canonical.feature_bullets,
        status=canonical.status,
        validation_errors=canonical.validation_errors,
        variant_terms=canonical.variant_terms,
        qc_pass=canonical.qc_pass,
        error=canonical.error,
    )


@router.post("/batch", response_model=BatchResponse)
async def batch_convert(body: BatchRequest):
    if not body.asins:
        raise HTTPException(status_code=400, detail="No ASINs provided")
    if len(body.asins) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 ASINs per batch")

    asins = [a.strip().upper() for a in body.asins if a.strip()]

    # Fetch SOT data sequentially to avoid exhausting the DB connection pool
    # Each entry: (title, bullets, description, primary_sku, listing_sku, variant_terms, parent_sku)
    sot_data: list[tuple] = []
    for asin in asins:
        sot_data.append(await asyncio.to_thread(_fetch_amazon_content, asin))

    # Group siblings by parent_sku — siblings share identical converted content.
    # ASINs without a parent_sku are treated as standalone (converted independently).
    group_canonical: dict[str, str] = {}   # parent_sku → canonical ASIN
    for asin, (_, _, _, _, _, _, parent_sku) in zip(asins, sot_data):  # noqa: E501
        if parent_sku and parent_sku not in group_canonical:
            group_canonical[parent_sku] = asin

    canonical_asins = {
        asin for asin, (_, _, _, _, _, _, parent_sku) in zip(asins, sot_data)
        if parent_sku is None or group_canonical.get(parent_sku) == asin
    }

    # Build group_titles: for each parent_sku group, collect all submitted ASINs' own titles
    # so the LLM can derive one common Product Name from the titles the user actually provided.
    group_titles: dict[str, list[str]] = {}  # parent_sku → [title, ...]
    for asin, (title, _, _, _, _, _, parent_sku) in zip(asins, sot_data):
        if parent_sku and title:
            group_titles.setdefault(parent_sku, [])
            if title not in group_titles[parent_sku]:
                group_titles[parent_sku].append(title)

    async def _convert_canonical(asin: str) -> tuple[str, BatchItemResult]:
        from app.services.amazon_to_wayfair_converter import convert
        title, bullets, description, _primary_sku, listing_sku, variant_terms, parent_sku = \
            next(d for a, d in zip(asins, sot_data) if a == asin)
        titles_for_group = group_titles.get(parent_sku, [title] if title else []) if parent_sku else ([title] if title else [])
        if not titles_for_group:
            reason = "No title found in SOT" if listing_sku else "ASIN not found in SOT database"
            logger.warning("No data for ASIN %s: sku=%s", asin, listing_sku)
            return asin, BatchItemResult(
                asin=asin, sku=listing_sku, group_ref_id=asin,
                product_name="", marketing_copy="", marketing_copy_word_count=0,
                feature_bullets=[], status="no_sot_data", validation_errors=[],
                qc_pass=False, error=reason,
            )
        try:
            result = await asyncio.to_thread(
                convert,
                amazon_title=titles_for_group if len(titles_for_group) > 1 else titles_for_group[0],
                amazon_bullets=bullets,
                amazon_description=description,
                group_ref_id=asin,
                variant_terms=variant_terms or None,
            )
            return asin, BatchItemResult(
                asin=asin, sku=listing_sku, group_ref_id=result.group_ref_id,
                product_name=result.product_name, marketing_copy=result.marketing_copy,
                marketing_copy_word_count=result.marketing_copy_word_count,
                feature_bullets=result.feature_bullets, status=result.status,
                validation_errors=result.validation_errors,
                variant_terms=result.effective_variant_terms, qc_pass=result.status == "valid",
            )
        except Exception as exc:
            import traceback
            logger.error("Batch convert failed for ASIN %s: %s | type=%s | trace=%s",
                         asin, exc, type(exc).__name__, traceback.format_exc())
            return asin, BatchItemResult(
                asin=asin, sku=listing_sku, group_ref_id=asin,
                product_name="", marketing_copy="", marketing_copy_word_count=0,
                feature_bullets=[], status="error", validation_errors=[],
                qc_pass=False, error=f"{type(exc).__name__}: {exc}",
            )

    canonical_pairs = await asyncio.gather(
        *[_convert_canonical(asin) for asin in asins if asin in canonical_asins]
    )
    canonical_results: dict[str, BatchItemResult] = dict(canonical_pairs)

    # Build final results in original order; siblings reuse canonical content
    results: list[BatchItemResult] = []
    for asin, (_, _, _, _, listing_sku, _, parent_sku) in zip(asins, sot_data):  # noqa
        if asin in canonical_results:
            results.append(canonical_results[asin])
        else:
            canonical_asin = group_canonical[parent_sku]
            results.append(_make_sibling_result(asin, listing_sku, canonical_results[canonical_asin]))

    converted = sum(1 for r in results if r.status in ("valid", "requires_review"))
    errors = sum(1 for r in results if r.status in ("error", "no_sot_data"))

    return BatchResponse(
        total=len(results),
        converted=converted,
        errors=errors,
        results=list(results),
    )


# ── Streaming batch (SSE) ─────────────────────────────────────────────────────

@router.post("/batch/stream")
async def batch_convert_stream(body: BatchRequest, request: Request):
    """
    SSE endpoint — streams one JSON event per ASIN as it completes.
    Keeps the connection alive for slow LLM backends (e.g. large local models).

    Event format:
      data: {"type": "result", ...BatchItemResult fields...}\n\n
      data: {"type": "done", "total": N, "converted": N, "errors": N}\n\n
    """
    if not body.asins:
        raise HTTPException(status_code=400, detail="No ASINs provided")
    if len(body.asins) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 ASINs per batch")

    asins = [a.strip().upper() for a in body.asins if a.strip()]

    async def event_stream():
        converted = 0
        errors = 0

        # Fetch SOT data sequentially to avoid DB pool exhaustion.
        # Send keepalive comments so Railway/proxies don't close the idle connection.
        sot_data: list[tuple] = []
        for asin in asins:
            yield ": keepalive\n\n"
            sot_data.append(await asyncio.to_thread(_fetch_amazon_content, asin))

        # Build sibling groups (same logic as /batch)
        group_canonical: dict[str, str] = {}
        for asin, (_, _, _, _, _, _, parent_sku) in zip(asins, sot_data):
            if parent_sku and parent_sku not in group_canonical:
                group_canonical[parent_sku] = asin

        canonical_asins = {
            asin for asin, (_, _, _, _, _, _, parent_sku) in zip(asins, sot_data)
            if parent_sku is None or group_canonical.get(parent_sku) == asin
        }

        group_titles: dict[str, list[str]] = {}
        for asin, (title, _, _, _, _, _, parent_sku) in zip(asins, sot_data):
            if parent_sku and title:
                group_titles.setdefault(parent_sku, [])
                if title not in group_titles[parent_sku]:
                    group_titles[parent_sku].append(title)

        # Convert canonical ASINs one at a time, streaming each result immediately
        canonical_results: dict[str, BatchItemResult] = {}
        for asin, data in zip(asins, sot_data):
            if asin not in canonical_asins:
                continue
            if await request.is_disconnected():
                break

            title, bullets, description, _primary_sku, listing_sku, variant_terms, parent_sku = data
            titles_for_group = group_titles.get(parent_sku, [title] if title else []) if parent_sku else ([title] if title else [])

            if not titles_for_group:
                item = BatchItemResult(
                    asin=asin, sku=listing_sku, group_ref_id=asin,
                    product_name="", marketing_copy="", marketing_copy_word_count=0,
                    feature_bullets=[], status="no_sot_data", validation_errors=[],
                    qc_pass=False, error="No title found in SOT" if listing_sku else "ASIN not found in SOT database",
                )
            else:
                # Run conversion in background; send keepalives every 10s so Railway
                # doesn't close the connection while the LLM is generating.
                async def _do_convert(titles=titles_for_group, bull=bullets, desc=description,
                                      gref=asin, vt=variant_terms):
                    from app.services.amazon_to_wayfair_converter import convert
                    return await asyncio.to_thread(
                        convert,
                        amazon_title=titles if len(titles) > 1 else titles[0],
                        amazon_bullets=bull,
                        amazon_description=desc,
                        group_ref_id=gref,
                        variant_terms=vt or None,
                    )

                convert_task = asyncio.ensure_future(_do_convert())
                try:
                    while not convert_task.done():
                        yield ": keepalive\n\n"
                        await asyncio.wait([convert_task], timeout=10)
                    result = convert_task.result()
                    item = BatchItemResult(
                        asin=asin, sku=listing_sku, group_ref_id=result.group_ref_id,
                        product_name=result.product_name, marketing_copy=result.marketing_copy,
                        marketing_copy_word_count=result.marketing_copy_word_count,
                        feature_bullets=result.feature_bullets, status=result.status,
                        validation_errors=result.validation_errors,
                        variant_terms=result.effective_variant_terms, qc_pass=result.status == "valid",
                    )
                except Exception as exc:
                    import traceback
                    logger.error("Stream convert failed for ASIN %s: %s | type=%s | trace=%s",
                                 asin, exc, type(exc).__name__, traceback.format_exc())
                    item = BatchItemResult(
                        asin=asin, sku=listing_sku, group_ref_id=asin,
                        product_name="", marketing_copy="", marketing_copy_word_count=0,
                        feature_bullets=[], status="error", validation_errors=[],
                        qc_pass=False, error=f"{type(exc).__name__}: {exc}",
                    )

            canonical_results[asin] = item
            if item.status in ("valid", "requires_review"):
                converted += 1
            else:
                errors += 1

            payload = {"type": "result", **item.model_dump()}
            yield f"data: {json.dumps(payload)}\n\n"

        # Emit sibling results (copied from canonical)
        for asin, (_, _, _, _, listing_sku, _, parent_sku) in zip(asins, sot_data):
            if asin in canonical_results:
                continue
            canonical_asin = group_canonical.get(parent_sku or "")
            if not canonical_asin or canonical_asin not in canonical_results:
                continue
            item = _make_sibling_result(asin, listing_sku, canonical_results[canonical_asin])
            payload = {"type": "result", **item.model_dump()}
            yield f"data: {json.dumps(payload)}\n\n"

        yield f"data: {json.dumps({'type': 'done', 'total': len(asins), 'converted': converted, 'errors': errors})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})
