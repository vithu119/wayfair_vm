from __future__ import annotations
import logging
import re as _re
import unicodedata as _unicodedata
from app.sources.sot_models import ProductIdentity, SotAttribute
from app.sources.postgres_guard import assert_read_only
from app.sources.postgres_connection import readonly_cursor, test_connection

logger = logging.getLogger(__name__)

# Amazon variation attribute name → (Wayfair Variant Grouping dropdown, on-site display name)
# Based on Variation_Grouping_Instruction doc. Lowercase keys match listing_data.selected_variations[].name.
_VAR_ATTR_MAP: dict[str, tuple[str, str]] = {
    # Colour / Shade
    "color":              ("Colour",                        "Colour"),
    "colour":             ("Colour",                        "Colour"),
    "shade":              ("Shade Color",                   "Shade Colour"),
    "shade_colour":       ("Shade Color",                   "Shade Colour"),
    "shade_color":        ("Shade Color",                   "Shade Colour"),
    "finish_type":        ("Finish",                        "Finish"),
    "pattern":            ("Shade Color",                   "Pattern"),
    # Size / Quantity / Pack
    "size":               ("Size",                         "Size"),
    "diameter":           ("Size",                         "Diameter"),
    "item_shape":         ("Size",                         "Shape"),
    "cable":              ("Size",                         "Cable Length"),
    "special_size_type":  ("Size",                         "Size"),
    "light":              ("Size",                         "Size"),
    "item_package_quantity": ("Pack Size",                 "Pack Size"),
    "number_of_items":    ("Pack Size",                    "Pack Size"),
    "number":             ("Pack Size",                    "Pack Size"),
    "unit_count":         ("Pack Size",                    "Pack Size"),
    # Wattage / Electrical
    "wattage":            ("Maximum Wattage (per Bulb)",   "Wattage"),
    "light_color":        ("Color Temperature",            "Color Temperature"),
    "lens":               ("Bulb Type",                    "Bulb Type"),
    "base":               ("Bulb Base",                    "Bulb Base"),
    # Bulb option — set_name often contains "With Bulb" / "Without Bulb"
    "set_name":           ("Bulb Included",                "Bulb Option"),
    # Material / Fixture
    "material":           ("Fixture Material",             "Material"),
    "mounting_type":      ("Size",                         "Mounting Type"),
    # Misc
    "style":              ("Size",                         "Style"),
    "item":               ("Size",                         "Style"),
    "special":            ("Size",                         "Style"),
}

# Value substrings that indicate a bulb option regardless of which attribute name Amazon used.
# When any of these appear in the value, remap the grouping to Bulb Included.
_BULB_VALUE_KEYWORDS = frozenset({
    "with bulb", "without bulb", "with out bulb", "no bulb",
    "bulb included", "bulb not included", "includes bulb",
    "withbulb", "withoutbulb",
    "with lamp", "without lamp", "with light", "without light",
})

# Regex to strip bulb phrases from a combined colour/bulb value (e.g. "Brushed Copper Without Bulb")
_BULB_PHRASE_RE = _re.compile(
    r"\s*\b(with(?:\s*out)?|without|no)\s*bulb\b"
    r"|\s*\bwith(?:\s*out)?\s+lamp\b"
    r"|\s*\bwithout\s+lamp\b"
    r"|\s*\bwith(?:\s*out)?\s+light\b"
    r"|\s*\bwithout\s+light\b"
    r"|\s*\bbulb\s+(?:included|not\s+included)\b"
    r"|\s*\bincludes?\s+bulb\b",
    _re.IGNORECASE,)

# Slot priority: lower number = filled first (VG1 < VG2 < VG3)
# Colour → slot 1, Size/Pack/Wattage → slot 2, Bulb/Other → slot 3
_VAR_SLOT_PRIORITY: dict[str, int] = {
    "Colour":                      1,
    "Shade Color":                 1,
    "Finish":                      1,
    "Size":                        2,
    "Pack Size":                   2,
    "Maximum Wattage (per Bulb)":  2,
    "Color Temperature":           2,
    "Number of Lights":            2,
    "Fixture Material":            2,
    "Bulb Type":                   3,
    "Bulb Base":                   3,
    "Bulb Included":               3,
}

# Source tab → Wayfair category mapping
_SOURCE_TAB_CATEGORY = {
    "shade": "Lampshades",
    "ceilingrose": "Lighting Accessories",
    "lampholder": "Lighting Accessories",
    "pendantholder": "Pendant Lightt",
    "bulb": "Light Bulbs",
    "wallarm": "Wall Sconces",
}

def get_connection_status() -> dict:
    return test_connection()


def resolve_asin(asin: str) -> ProductIdentity:
    """
    Resolve one ASIN to a ProductIdentity using listing_data.
    Never raises — returns status in result.
    """
    identity = ProductIdentity(input_asin=asin)

    sql_listing = """
        SELECT ref_id, COALESCE(mapped_sku, sku) AS resolved_sku, which_channel_name, parent_sku
        FROM public.listing_data
        WHERE ref_id = %s
          AND COALESCE(mapped_sku, sku) IS NOT NULL
          AND COALESCE(mapped_sku, sku) != ''
          AND which_channel_name ILIKE '%%amazon%%'
        ORDER BY (CASE WHEN market_place = 'UK' THEN 0 ELSE 1 END), id
        LIMIT 2
    """
    assert_read_only(sql_listing)

    try:
        with readonly_cursor() as cur:
            cur.execute(sql_listing, (asin,))
            listing_rows = cur.fetchall()
    except EnvironmentError:
        identity.status = "asin_not_found"
        identity.warnings.append("configurator_sot_not_configured")
        return identity
    except Exception as exc:
        identity.status = "asin_not_found"
        identity.warnings.append(f"configurator_sot_connection_failed: {type(exc).__name__}")
        return identity

    if listing_rows:
        skus = list({r[1] for r in listing_rows})
        if len(skus) > 1:
            # Prefer the UK row — the query already orders UK first, so listing_rows[0]
            # is the UK match if one exists.  Only fall back to ambiguous_match when
            # no single row can be preferred (e.g. multiple non-UK rows with different SKUs).
            uk_rows = [r for r in listing_rows if r[0] == asin]  # ref_id matches exactly
            # Pick UK-market row if present, otherwise first row (already UK-ordered)
            preferred = listing_rows[0]
            preferred_sku = preferred[1]
            # Warn but continue — don't abort on ambiguity when UK data is available
            identity.warnings.append(
                f"ambiguous_identity_match: multiple SKUs {skus} for ASIN {asin}; "
                f"using UK-preferred SKU {preferred_sku!r}"
            )
        ref_id, resolved_sku, channel_name, parent_sku_val = listing_rows[0]
        identity.asin = ref_id
        identity.internal_sku = resolved_sku
        identity.primary_sku = resolved_sku.split("+")[0].strip() if "+" in resolved_sku else resolved_sku.strip()
        identity.component_skus = [s.strip() for s in resolved_sku.split("+") if s.strip()]
        identity.channel = channel_name or "amazon"
        identity.evidence.append(f"listing_data: ASIN {asin} → sku={resolved_sku}")
    else:
        # Parent ASIN fallback — find children that share this as parent_sku
        sql_parent = """
            SELECT DISTINCT ref_id, COALESCE(mapped_sku, sku)
            FROM public.listing_data
            WHERE parent_sku = %s
              AND COALESCE(mapped_sku, sku) IS NOT NULL AND COALESCE(mapped_sku, sku) != ''
              AND which_channel_name ILIKE '%%amazon%%'
              AND market_place IN ('UK', 'US')
              AND is_child = 1
        """
        assert_read_only(sql_parent)
        try:
            with readonly_cursor() as cur:
                cur.execute(sql_parent, (asin,))
                parent_rows = cur.fetchall()
        except Exception:
            parent_rows = []

        if parent_rows:
            child_asins = sorted({r[0] for r in parent_rows if r[0]})
            identity.status = "parent_asin"
            identity.child_asins = child_asins
            identity.evidence.append(f"listing_data: {asin} is parent_sku with {len(child_asins)} children")
            return identity

        identity.status = "asin_not_found"
        return identity

    if not identity.primary_sku:
        identity.status = "sku_not_found"
        return identity

    # Look up source_tab from components_sot_skus
    sot_sql = """
        SELECT sku, source_tab FROM public.components_sot_skus WHERE sku = %s
    """
    assert_read_only(sot_sql)
    try:
        with readonly_cursor() as cur:
            cur.execute(sot_sql, (identity.primary_sku,))
            sot_row = cur.fetchone()
    except Exception:
        sot_row = None

    if sot_row:
        identity.source_tab = sot_row[1]
        identity.wayfair_category = _SOURCE_TAB_CATEGORY.get(identity.source_tab)
        identity.evidence.append(f"components_sot_skus: sku={sot_row[0]}, source_tab={sot_row[1]}")
    else:
        identity.warnings.append(f"sot_product_not_found: SKU {identity.primary_sku} not in components_sot_skus")

    # Get product_subtype
    subtype_sql = """
        SELECT av.value
        FROM public.components_sot_attribute_values av
        JOIN public.components_sot_skus s ON s.id = av.sot_sku_id
        JOIN public.components_sot_attributes a ON a.id = av.attribute_id
        WHERE s.sku = %s AND a.key = 'product_subtype' AND av.value IS NOT NULL
        LIMIT 1
    """
    assert_read_only(subtype_sql)
    try:
        with readonly_cursor() as cur:
            cur.execute(subtype_sql, (identity.primary_sku,))
            subtype_row = cur.fetchone()
        if subtype_row:
            identity.product_subtype = subtype_row[0]
    except Exception:
        pass

    identity.status = "resolved"
    return identity


_SOT_IMAGE_KEYS_ORDERED = [
    "img_link", "img_main", "img_dimension", "img_inbox",
    "img_finish", "img_context", "img_install", "img_lifestyle",
]


def batch_get_sot_rows(
    asins: list[str],
    mappings: list[dict],
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """
    Resolve ASINs (expanding parent ASINs to children automatically) and fill
    all SOT fields in bulk using a single DB connection.

    Returns (rows_by_asin, expanded_asins) where:
      - rows_by_asin: {asin: {wayfair_header: value}}
      - expanded_asins: final list of ASINs after parent expansion
    """
    from app.sources.sot_value_parser import parse_sot_value, convert_unit
    import re as _re

    if not asins:
        return {}, []

    from app.sources.postgres_connection import _open_readonly_conn

    _SYNTHETIC = frozenset({
        "__sku__", "__image_url_1__", "__image_url_2__", "__image_url_3__",
        "__image_url_4__", "__image_url_5__", "__video_url_1__",
        "__bullet_1__", "__bullet_2__", "__bullet_3__", "__bullet_4__", "__bullet_5__",
        "__description__", "__base_cost__", "__amazon_price__",
    })
    needed_keys = [m["sot_key"] for m in mappings if m.get("mapping_status") == "approved" and m["sot_key"] not in _SYNTHETIC]

    # Open ONE connection for the entire batch — single TCP handshake for all queries
    try:
        conn = _open_readonly_conn()
    except Exception as exc:
        logger.error("batch_get_sot_rows: cannot connect: %s", type(exc).__name__)
        return {}, list(asins)

    try:
        asin_to_sku: dict[str, str] = {}
        asin_images: dict[str, list[str]] = {}
        asin_sub_images: dict[str, list[str]] = {}
        asin_bullets: dict[str, list[str]] = {}
        asin_descriptions: dict[str, str] = {}
        asin_titles: dict[str, str] = {}
        asin_variations: dict[str, list[dict]] = {}
        asin_prices: dict[str, tuple[float, float, str]] = {}  # asin → (price, price_per_order, market_place)
        asin_price_unverified: set[str] = set()  # ASINs whose price came from wrong_sku=1 fallback
        asin_is_us: set[str] = set()  # ASINs that have a US listing in listing_data

        # ── 1a. Resolve input ASINs via listing_data (primary source) ───────────
        sql_listing_primary = """
            SELECT DISTINCT ON (ref_id) ref_id, COALESCE(mapped_sku, sku), parent_sku
            FROM public.listing_data
            WHERE ref_id = ANY(%s)
              AND COALESCE(mapped_sku, sku) IS NOT NULL AND COALESCE(mapped_sku, sku) != ''
              AND which_channel_name ILIKE '%%amazon%%'
              AND market_place IN ('UK', 'US')
            ORDER BY ref_id, (CASE WHEN market_place = 'UK' THEN 0 ELSE 1 END), id
        """
        assert_read_only(sql_listing_primary)
        with readonly_cursor(conn) as cur:
            cur.execute(sql_listing_primary, (asins,))
            for ref_id, sku, _parent_sku in cur.fetchall():
                asin_to_sku[ref_id] = sku

        # ── 1a-us. Detect which ASINs have a US listing ──────────────────────
        sql_us_check = """
            SELECT DISTINCT ref_id
            FROM public.listing_data
            WHERE ref_id = ANY(%s)
              AND market_place = 'US'
              AND which_channel_name ILIKE '%%amazon%%'
        """
        assert_read_only(sql_us_check)
        try:
            with readonly_cursor(conn) as cur:
                cur.execute(sql_us_check, (asins,))
                for (ref_id,) in cur.fetchall():
                    asin_is_us.add(ref_id)
        except Exception as _us_exc:
            logger.warning("US marketplace check skipped: %s", type(_us_exc).__name__)

        # ── 1a-fallback. Retry without UK marketplace filter ─────────────────
        # Some ASINs exist in listing_data but without market_place='UK'.
        # Bullets/descriptions are fetched without this filter and return data,
        # so we must also resolve SKUs for these ASINs to avoid skipping all fields.
        non_uk_asins = [a for a in asins if a not in asin_to_sku]
        if non_uk_asins:
            sql_listing_any_market = """
                SELECT DISTINCT ON (ref_id) ref_id, COALESCE(mapped_sku, sku)
                FROM public.listing_data
                WHERE ref_id = ANY(%s)
                  AND COALESCE(mapped_sku, sku) IS NOT NULL AND COALESCE(mapped_sku, sku) != ''
                  AND which_channel_name ILIKE '%%amazon%%'
                ORDER BY ref_id,
                         (CASE WHEN market_place = 'UK' THEN 0 ELSE 1 END),
                         id
            """
            assert_read_only(sql_listing_any_market)
            try:
                with readonly_cursor(conn) as cur:
                    cur.execute(sql_listing_any_market, (non_uk_asins,))
                    for ref_id, sku in cur.fetchall():
                        if sku:
                            asin_to_sku[ref_id] = sku
            except Exception as _fb_exc:
                logger.warning("listing_data non-UK fallback skipped: %s", type(_fb_exc).__name__)

        # ── 1b. Expand any unresolved ASINs as parent SKUs ───────────────────
        still_unresolved = [a for a in asins if a not in asin_to_sku]
        parent_children: dict[str, list[str]] = {}  # input_parent → [child_asins]
        if still_unresolved:
            sql_parent = """
                SELECT DISTINCT ref_id, COALESCE(mapped_sku, sku)
                FROM public.listing_data
                WHERE parent_sku = ANY(%s)
                  AND COALESCE(mapped_sku, sku) IS NOT NULL AND COALESCE(mapped_sku, sku) != ''
                  AND (which_channel_name ILIKE '%%amazon%%' OR which_channel_name IS NULL)
                  AND is_child = 1 AND ref_id IS NOT NULL AND ref_id != ''
            """
            assert_read_only(sql_parent)
            with readonly_cursor(conn) as cur:
                cur.execute(sql_parent, (still_unresolved,))
                for child_ref, sku in cur.fetchall():
                    asin_to_sku[child_ref] = sku
                    for par in still_unresolved:
                        parent_children.setdefault(par, []).append(child_ref)

        # Build final expanded ASIN list (parents replaced by their children)
        expanded_asins: list[str] = []
        seen: set[str] = set()
        for a in asins:
            children = parent_children.get(a)
            if children:
                for c in children:
                    if c not in seen:
                        expanded_asins.append(c)
                        seen.add(c)
            else:
                if a not in seen:
                    expanded_asins.append(a)
                    seen.add(a)

        result: dict[str, dict[str, str]] = {a: {} for a in expanded_asins}

        # display_sku = full raw SKU for template output
        # Priority: mapped_sku from active listing_data → sku from active listing_data → traffic SKU (suffix-stripped)
        def _clean_display_sku(raw: str) -> str:
            return _re.sub(r'\s+(FBA|AM|M|SRM|SM)$', '', raw.strip(), flags=_re.IGNORECASE).strip()

        asin_to_display_sku: dict[str, str] = {asin: _clean_display_sku(sku) for asin, sku in asin_to_sku.items()}

        # Override with mapped_sku (or sku) from active listing_data — most authoritative source
        sql_display_sku = """
            SELECT DISTINCT ON (ref_id) ref_id,
                   COALESCE(NULLIF(mapped_sku, ''), sku)
            FROM public.listing_data
            WHERE ref_id = ANY(%s)
              AND wrong_sku = 0
              AND (status ILIKE 'active' OR status IN ('DISCOVERABLE', 'BUYABLE', '1'))
              AND which_channel_name ILIKE '%%amazon%%'
            ORDER BY ref_id,
                     (CASE WHEN market_place = 'UK' THEN 0 ELSE 1 END),
                     id
        """
        assert_read_only(sql_display_sku)
        try:
            with readonly_cursor(conn) as cur:
                cur.execute(sql_display_sku, (expanded_asins,))
                for ref_id, resolved_sku in cur.fetchall():
                    if resolved_sku:
                        asin_to_display_sku[ref_id] = resolved_sku.strip()
        except Exception as _dsku_exc:
            logger.warning("display_sku query skipped: %s", type(_dsku_exc).__name__)
        # ── 2. Main image from listing_data by ASIN ───────────────────────────
        asins_with_sku = [a for a in expanded_asins if a in asin_to_sku]
        if asins_with_sku:
            sql_asin_img = """
                SELECT DISTINCT ON (ref_id) ref_id, main_image_url
                FROM public.listing_data
                WHERE ref_id = ANY(%s) AND main_image_url IS NOT NULL AND main_image_url != ''
                ORDER BY ref_id, id
            """
            assert_read_only(sql_asin_img)
            with readonly_cursor(conn) as cur:
                cur.execute(sql_asin_img, (asins_with_sku,))
                for ref_id, url in cur.fetchall():
                    if url:
                        asin_images[ref_id] = [url]

        # ── 3b. Sub-images via listing_data → sub_images ─────────────────────
        seen_sub: dict[str, set] = {}
        sql_sub_ld = """
            SELECT ld.ref_id, si.image_url
            FROM public.sub_images si
            JOIN public.listing_data ld ON ld.id = si.product_id
            WHERE ld.ref_id = ANY(%s)
              AND si.image_url IS NOT NULL AND si.image_url != ''
            ORDER BY ld.ref_id, COALESCE(si.view_order, 999999), si.id
        """
        assert_read_only(sql_sub_ld)
        try:
            with readonly_cursor(conn) as cur:
                cur.execute(sql_sub_ld, (expanded_asins,))
                for ref_id, url in cur.fetchall():
                    if url and url.startswith("http"):
                        seen_sub.setdefault(ref_id, set())
                        if url not in seen_sub[ref_id]:
                            asin_sub_images.setdefault(ref_id, []).append(url)
                            seen_sub[ref_id].add(url)
        except Exception as _sub_exc:
            logger.warning("sub_images query skipped: %s", type(_sub_exc).__name__)
            try:
                conn.rollback()  # recover shared connection from aborted-transaction state
            except Exception:
                pass

        # ── 4. Bullets via listing_data ───────────────────────────────────────
        def _normalise_bullet(points: str) -> str:
            # Strip Unicode bold/italic math block (e.g. 𝐖𝐈𝐃𝐄) from entire text
            points = _re.sub(r'[\U0001D400-\U0001D7FF]', '', points)
            points = _re.sub(r'[™©®℠†‡•·°]', '', points)
            if ' : ' in points:
                heading, _, rest = points.partition(' : ')
                heading_norm = _unicodedata.normalize('NFKC', heading)
                if any(ord(c) > 127 for c in heading_norm):
                    heading_norm = ''.join(c for c in heading_norm if ord(c) <= 127)
                heading_norm = heading_norm.strip().title()
                points = f"{heading_norm} : {rest}" if heading_norm else rest
            return _re.sub(r' {2,}', ' ', points).strip()

        # Primary: match by ref_id = ASIN
        sql_bullets_asin = """
            SELECT DISTINCT ON (ld.ref_id, bp.view_order) ld.ref_id, bp.points, bp.view_order
            FROM public.bullet_points bp
            JOIN public.listing_data ld ON ld.id = bp.product_id
            WHERE ld.ref_id = ANY(%s) AND bp.points IS NOT NULL AND bp.points != ''
            ORDER BY ld.ref_id, bp.view_order, bp.id
        """
        assert_read_only(sql_bullets_asin)
        try:
            with readonly_cursor(conn) as cur:
                cur.execute(sql_bullets_asin, (expanded_asins,))
                for ref_id, points, _ in cur.fetchall():
                    p = _normalise_bullet(points)
                    if p:
                        asin_bullets.setdefault(ref_id, []).append(p)
        except Exception as _bullets_exc:
            logger.warning("bullet_points query skipped: %s: %s", type(_bullets_exc).__name__, _bullets_exc)
            try:
                conn.rollback()
            except Exception:
                pass

        # Fallback: match by sku column (when listing_data.ref_id is SKU-based, not ASIN)
        asins_missing_bullets = [a for a in expanded_asins if a not in asin_bullets]
        if asins_missing_bullets:
            missing_skus = list({asin_to_sku[a] for a in asins_missing_bullets if a in asin_to_sku})
            if missing_skus:
                sql_bullets_sku = """
                    SELECT DISTINCT ON (ld.sku, bp.view_order) ld.sku, bp.points, bp.view_order
                    FROM public.bullet_points bp
                    JOIN public.listing_data ld ON ld.id = bp.product_id
                    WHERE ld.sku = ANY(%s) AND bp.points IS NOT NULL AND bp.points != ''
                    ORDER BY ld.sku, bp.view_order, bp.id
                """
                assert_read_only(sql_bullets_sku)
                try:
                    sku_to_bullets: dict[str, list[str]] = {}
                    with readonly_cursor(conn) as cur:
                        cur.execute(sql_bullets_sku, (missing_skus,))
                        for sku, points, _ in cur.fetchall():
                            p = _normalise_bullet(points)
                            if p:
                                sku_to_bullets.setdefault(sku, []).append(p)
                    for asin in asins_missing_bullets:
                        raw = asin_to_sku.get(asin, "")
                        bullets = sku_to_bullets.get(raw, [])
                        if bullets:
                            asin_bullets[asin] = bullets
                except Exception as _bullets_exc2:
                    logger.warning("bullet_points (sku fallback) skipped: %s", type(_bullets_exc2).__name__)
                    try:
                        conn.rollback()
                    except Exception:
                        pass

        # ── 4b. Descriptions from listing_data ───────────────────────────────
        sql_desc = """
            SELECT DISTINCT ON (ref_id) ref_id, product_description
            FROM public.listing_data
            WHERE ref_id = ANY(%s)
              AND product_description IS NOT NULL AND product_description != ''
            ORDER BY ref_id, id
        """
        assert_read_only(sql_desc)
        with readonly_cursor(conn) as cur:
            cur.execute(sql_desc, (expanded_asins,))
            for ref_id, desc in cur.fetchall():
                asin_descriptions[ref_id] = desc

        # ── 4c. Prices from listing_data (US preferred over UK — US price × 0.85, UK × 0.60) ──
        sql_prices = """
            SELECT DISTINCT ON (ref_id) ref_id,
                   COALESCE(price, 0),
                   COALESCE(price_per_order, 0),
                   COALESCE(market_place, 'UK')
            FROM public.listing_data
            WHERE ref_id = ANY(%s)
              AND wrong_sku = 0
              AND (status ILIKE 'active' OR status IN ('DISCOVERABLE', 'BUYABLE', '1'))
              AND which_channel_name ILIKE '%%amazon%%'
              AND price IS NOT NULL
            ORDER BY ref_id,
                     (CASE WHEN market_place = 'US' THEN 0 ELSE 1 END),
                     id
        """
        assert_read_only(sql_prices)
        try:
            with readonly_cursor(conn) as cur:
                cur.execute(sql_prices, (expanded_asins,))
                for ref_id, price, price_per_order, mkt in cur.fetchall():
                    asin_prices[ref_id] = (float(price), float(price_per_order), mkt or 'UK')
        except Exception as _price_exc:
            logger.warning("price query skipped: %s", type(_price_exc).__name__)

        # Fallback: wrong_sku=1 rows when no clean price found
        asins_missing_price = [a for a in expanded_asins if a not in asin_prices]
        if asins_missing_price:
            sql_prices_fallback = """
                SELECT DISTINCT ON (ref_id) ref_id,
                       COALESCE(price, 0),
                       COALESCE(price_per_order, 0),
                       COALESCE(market_place, 'UK')
                FROM public.listing_data
                WHERE ref_id = ANY(%s)
                  AND (status ILIKE 'active' OR status IN ('DISCOVERABLE', 'BUYABLE', '1'))
                  AND which_channel_name ILIKE '%%amazon%%'
                  AND price IS NOT NULL
                ORDER BY ref_id,
                         (CASE WHEN market_place = 'US' THEN 0 ELSE 1 END),
                         id
            """
            assert_read_only(sql_prices_fallback)
            try:
                with readonly_cursor(conn) as cur:
                    cur.execute(sql_prices_fallback, (asins_missing_price,))
                    for ref_id, price, price_per_order, mkt in cur.fetchall():
                        asin_prices[ref_id] = (float(price), float(price_per_order), mkt or 'UK')
                        asin_price_unverified.add(ref_id)
            except Exception as _price_exc2:
                logger.warning("price fallback query skipped: %s", type(_price_exc2).__name__)

        # ── 5. Titles from listing_data ───────────────────────────────────────
        if expanded_asins:
            sql_titles = """
                SELECT DISTINCT ON (ref_id) ref_id, title
                FROM public.listing_data
                WHERE ref_id = ANY(%s) AND title IS NOT NULL AND title != ''
                  AND which_channel_name ILIKE '%%amazon%%'
                ORDER BY ref_id, (CASE WHEN market_place='UK' THEN 0 ELSE 1 END), id
            """
            assert_read_only(sql_titles)
            with readonly_cursor(conn) as cur:
                cur.execute(sql_titles, (expanded_asins,))
                for ref_id, title in cur.fetchall():
                    asin_titles[ref_id] = title

        # ── 5b. Component SOT attributes by SKU ──────────────────────────────────
        unique_skus = list({sku for sku in asin_to_sku.values() if sku})
        sku_component_attrs: dict[str, dict[str, str]] = {}
        if unique_skus:
            sql_csot = """
                SELECT s.sku, a.key, av.value
                FROM public.components_sot_attribute_values av
                JOIN public.components_sot_skus s ON s.id = av.sot_sku_id
                JOIN public.components_sot_attributes a ON a.id = av.attribute_id
                WHERE s.sku = ANY(%s)
                  AND av.value IS NOT NULL AND av.value != ''
            """
            assert_read_only(sql_csot)
            try:
                with readonly_cursor(conn) as cur:
                    cur.execute(sql_csot, (unique_skus,))
                    for sku, key, value in cur.fetchall():
                        sku_component_attrs.setdefault(sku, {})[key] = value
            except Exception as _csot_exc:
                logger.warning("component SOT attrs query skipped: %s", type(_csot_exc).__name__)

        # ── 6. Variation attributes + listing_data parent_sku fallback ──────────
        # Prefer UK marketplace rows (most complete data), then rows with most attributes.
        # Also fetch parent_sku as fallback Group Reference ID for ASINs not in amz_traffic.
        sql_variations = """
            SELECT DISTINCT ON (ref_id) ref_id, selected_variations, parent_sku
            FROM public.listing_data
            WHERE ref_id = ANY(%s)
              AND selected_variations IS NOT NULL
              AND selected_variations NOT IN ('""', '', 'null')
              AND selected_variations LIKE '[%%'
              AND which_channel_name ILIKE '%%amazon%%'
            ORDER BY ref_id,
                     (CASE WHEN market_place = 'UK' THEN 0 ELSE 1 END),
                     jsonb_array_length(selected_variations::jsonb) DESC,
                     id
        """
        assert_read_only(sql_variations)
        asin_parent_sku: dict[str, str] = {}  # fallback Group Reference ID from listing_data
        try:
            with readonly_cursor(conn) as cur:
                cur.execute(sql_variations, (expanded_asins,))
                import json as _json
                for ref_id, sv, parent_sku_val in cur.fetchall():
                    if parent_sku_val:
                        asin_parent_sku[ref_id] = parent_sku_val
                    try:
                        parsed_sv = _json.loads(sv)
                        if isinstance(parsed_sv, list):
                            asin_variations[ref_id] = [
                                {"name": str(e.get("name", "") or "").strip().lower(),
                                 "value": str(e.get("value", "") or "").strip()}
                                for e in parsed_sv
                                if e.get("name") and e.get("value")
                            ]
                    except Exception:
                        pass
        except Exception as _var_exc:
            logger.warning("variation query skipped: %s", type(_var_exc).__name__)

    except Exception as exc:
        logger.error("batch_get_sot_rows query error: %s", type(exc).__name__)
    finally:
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass

    # ── 7. Apply mappings for each ASIN ───────────────────────────────────────
    def _extract_numeric(raw: str) -> str:
        m = _re.match(r'^([\d.]+)', raw.strip())
        return m.group(1) if m else raw

    approved = [m for m in mappings if m.get("mapping_status") == "approved"]

    for asin in expanded_asins:
        raw_sku = asin_to_sku.get(asin)
        if not raw_sku:
            continue
        attrs: dict[str, str] = sku_component_attrs.get(raw_sku, {})
        main_img = asin_images.get(asin, [None])[0]   # slot 1 — main image
        sub_imgs = asin_sub_images.get(asin, [])       # slots 2-5 + additional sheet
        bullets = asin_bullets.get(asin, [])
        description = asin_descriptions.get(asin)
        price_data = asin_prices.get(asin)
        row: dict[str, str] = {}
        # Extra images beyond slot 5 go to the additional images sheet
        extra_imgs = sub_imgs[4:]
        if extra_imgs:
            row["__extra_images__"] = "\n".join(extra_imgs)

        for mapping in approved:
            sot_key = mapping["sot_key"]
            header = mapping["wayfair_header"]
            transform = mapping.get("transformation")

            if sot_key == "__sku__":
                raw = asin_to_display_sku.get(asin, raw_sku)
            elif sot_key == "__image_url_1__":
                raw = main_img
            elif sot_key.startswith("__image_url_"):
                idx = int(sot_key.replace("__image_url_", "").replace("__", "")) - 2  # 2→0, 3→1, 4→2, 5→3
                raw = sub_imgs[idx] if idx < len(sub_imgs) else None
            elif sot_key == "__video_url_1__":
                raw = None
            elif sot_key == "__description__":
                raw = description
            elif sot_key.startswith("__bullet_"):
                idx = int(sot_key.replace("__bullet_", "").replace("__", "")) - 1
                raw = bullets[idx] if idx < len(bullets) else None
            elif sot_key == "__base_cost__":
                if price_data:
                    price_sum = price_data[0] + price_data[1]
                    mkt = price_data[2] if len(price_data) > 2 else "UK"
                    multiplier = 0.85 if mkt == "US" else 0.60
                    raw = str(round(price_sum * multiplier, 2))
                    if asin in asin_price_unverified:
                        row["__base_cost_unverified__"] = "true"
                else:
                    raw = None
            elif sot_key == "__amazon_price__":
                raw = str(round(price_data[0] + price_data[1], 2)) if price_data else None
            else:
                raw = attrs.get(sot_key)
                # For non-SOT products, use title from listing_data for product_name
                if raw is None and sot_key == "product_name":
                    raw = asin_titles.get(asin)

            if raw is None:
                continue

            parsed = parse_sot_value(raw)
            val = raw
            if transform == "mm_to_cm":
                if parsed.value_type == "measurement" and parsed.numeric is not None:
                    val = str(convert_unit(parsed, "cm").parsed_value)
                else:
                    try:
                        n = float(_re.match(r"^([\d.]+)", raw.strip()).group(1))
                        val = str(round(n * 0.1, 4))
                    except Exception:
                        pass
            elif transform == "g_to_kg":
                if parsed.value_type == "measurement" and parsed.numeric is not None:
                    val = str(convert_unit(parsed, "kg").parsed_value)
            elif transform == "mm_to_numeric":
                m2 = _re.match(r"^([\d.]+)", raw.strip())
                val = m2.group(1) if m2 else raw
            elif transform == "marketing_copy":
                val = _re.sub(r'[™©®℠†‡•·°]', '', val)
                val = _re.sub(r'[\U0001D400-\U0001D7FF]', '', val)
                val = _re.sub(r'<[^>]+>', ' ', val)
                val = _re.sub(r'[\r\n\t]+', ' ', val)
                val = _re.sub(r' {2,}', ' ', val).strip()[:4000]

            row[header] = val

        # ── Brand / MPN fixed by marketplace (not sourced from SOT DB) ──────────
        display_sku = asin_to_display_sku.get(asin, raw_sku) or raw_sku or ""
        if asin in asin_is_us:
            row["__is_us__"] = "true"
            row["Brand"] = "Neighbour Market"
            if display_sku:
                row["Manufacturer Part Number"] = f"NM-{display_sku}"
            logger.warning("SOT row brand/mpn set US: asin=%s mpn='NM-%s'", asin, display_sku)
        else:
            row["Brand"] = "LEDSone"
            if display_sku:
                row["Manufacturer Part Number"] = f"WF-{display_sku}"

        result[asin] = row

    # ── 8. Inject variation fields for each ASIN ──────────────────────────────

    # Track the original user-submitted ASINs (before any parent expansion).
    user_submitted: set[str] = set(asins)

    # First pass: resolve Group Reference ID for every ASIN.
    asin_group_ref: dict[str, str] = {}   # asin → group reference id (parent ASIN)
    for asin in expanded_asins:
        parent_asin = asin_parent_sku.get(asin)
        if parent_asin:
            asin_group_ref[asin] = parent_asin

    # Count how many USER-SUBMITTED ASINs belong to each family.
    # Rule:
    #   1 user ASIN in a family  → entire family = Not Variant (standalone)
    #   2+ user ASINs in a family → variant grouping applies
    #   style variation anywhere in family → entire family = Not Variant
    user_count_per_group: dict[str, int] = {}
    for asin in expanded_asins:
        if asin not in user_submitted:
            continue
        grp = asin_group_ref.get(asin)
        if grp:
            user_count_per_group[grp] = user_count_per_group.get(grp, 0) + 1

    style_variant_groups: set[str] = set()
    for asin in expanded_asins:
        var_attrs_pre = asin_variations.get(asin, [])
        has_style = any(
            "style" in v.get("value", "").lower() or v.get("name", "").lower() == "style"
            for v in var_attrs_pre
        )
        if has_style:
            grp = asin_group_ref.get(asin)
            if grp:
                style_variant_groups.add(grp)

    seen_primary: set[str] = set()   # group_ref ids already assigned a Primary

    # Second pass: inject variant type and grouping fields
    for asin in expanded_asins:
        row = result.get(asin)
        if row is None:
            continue

        group_ref = asin_group_ref.get(asin)

        var_attrs_pre = asin_variations.get(asin, [])
        is_style_variant = any(
            "style" in v.get("value", "").lower() or v.get("name", "").lower() == "style"
            for v in var_attrs_pre
        )
        family_has_style = group_ref in style_variant_groups
        # Only 1 user-submitted ASIN from this family → treat as standalone
        only_one_submitted = user_count_per_group.get(group_ref, 0) <= 1

        if not group_ref or is_style_variant or family_has_style or only_one_submitted:
            row["Variant Type"] = "Not Variant"
        else:
            row["Group Reference ID"] = group_ref
            if group_ref not in seen_primary:
                row["Variant Type"] = "Primary Variant"
                seen_primary.add(group_ref)
            else:
                row["Variant Type"] = "Non-Primary Variant"

        # Parse variation attributes from listing_data
        var_attrs = asin_variations.get(asin, [])
        if not var_attrs:
            continue

        # Map each Amazon variation name → (Wayfair Grouping dropdown, per-row value)
        slots: list[tuple[int, str, str]] = []  # (priority, grouping, value)
        for attr in var_attrs:
            name = attr["name"]
            value = attr["value"]
            mapping_result = _VAR_ATTR_MAP.get(name)
            if mapping_result is None:
                continue
            grouping, _ = mapping_result

            value_lower = value.lower()

            # When a colour/finish/style value embeds a bulb phrase (e.g. "Brushed Copper Without Bulb"),
            # split into two slots: one for the colour (phrase stripped) and one for Bulb Included.
            if grouping in ("Colour", "Shade Color", "Finish", "Size") and \
                    any(kw in value_lower for kw in _BULB_VALUE_KEYWORDS):
                colour_value = _BULB_PHRASE_RE.sub("", value).strip(" ,–-")
                _no_kws = {"without", "no bulb", "not included", "with out", "withoutbulb"}
                bulb_value = "No" if any(kw in value_lower for kw in _no_kws) else "Yes"
                if colour_value:
                    slots.append((_VAR_SLOT_PRIORITY.get(grouping, 9), grouping, colour_value))
                slots.append((_VAR_SLOT_PRIORITY.get("Bulb Included", 3), "Bulb Included", bulb_value))
                continue

            # Normalise Bulb Included values to Yes / No
            if grouping == "Bulb Included":
                _no_kws = {"without", "no bulb", "not included", "with out", "withoutbulb"}
                value = "No" if any(kw in value_lower for kw in _no_kws) else "Yes"

            slots.append((_VAR_SLOT_PRIORITY.get(grouping, 9), grouping, value))

        # Sort by priority then assign to VG1/VG2/VG3
        # Skip variant grouping fields for standalone (Not Variant) products
        if row.get("Variant Type") == "Not Variant":
            continue
        slots.sort(key=lambda x: x[0])
        for slot_idx, (_, grouping, value) in enumerate(slots[:3], start=1):
            row[f"Variant Grouping {slot_idx}"] = grouping
            row[f"Variant Attribute Name On Site {slot_idx}"] = value

    return result, expanded_asins


def get_image_urls(sku: str) -> list[str]:
    """Return up to 5 image URLs for a SKU.
    Priority: sub_images → SOT img_* attributes → listing_data fallback.
    """
    # Primary: sub_images ordered by view_order
    sql_sub = """
        SELECT DISTINCT ON (COALESCE(si.view_order, 999999), si.image_url)
            si.image_url, si.view_order
        FROM public.sub_images si
        JOIN public.components_sot_skus s ON s.id = si.product_id
        WHERE s.sku = %s AND si.image_url IS NOT NULL AND si.image_url != ''
        ORDER BY COALESCE(si.view_order, 999999), si.id
    """
    assert_read_only(sql_sub)
    urls: list[str] = []
    seen: set[str] = set()
    try:
        with readonly_cursor() as cur:
            cur.execute(sql_sub, (sku,))
            for url, _ in cur.fetchall():
                if url and url.startswith("http") and url not in seen:
                    urls.append(url)
                    seen.add(url)
                if len(urls) >= 5:
                    break
    except Exception:
        pass

    if not urls:
        # Fallback: SOT attribute images
        img_sql = """
            SELECT a.key, av.value
            FROM public.components_sot_attribute_values av
            JOIN public.components_sot_skus s ON s.id = av.sot_sku_id
            JOIN public.components_sot_attributes a ON a.id = av.attribute_id
            WHERE s.sku = %s AND a.key = ANY(%s)
              AND av.value IS NOT NULL AND av.value != ''
            ORDER BY a.sort_order
        """
        assert_read_only(img_sql)
        try:
            with readonly_cursor() as cur:
                cur.execute(img_sql, (sku, _SOT_IMAGE_KEYS_ORDERED))
                for _, val in cur.fetchall():
                    if val and val.startswith("http"):
                        urls.append(val)
                    if len(urls) >= 5:
                        break
        except Exception:
            pass

    if not urls:
        # Final fallback: listing_data.main_image_url
        fallback_sql = """
            SELECT main_image_url FROM public.listing_data
            WHERE sku = %s AND main_image_url IS NOT NULL AND main_image_url != ''
            ORDER BY id LIMIT 1
        """
        assert_read_only(fallback_sql)
        try:
            with readonly_cursor() as cur:
                cur.execute(fallback_sql, (sku,))
                row = cur.fetchone()
            if row:
                urls.append(row[0])
        except Exception:
            pass

    return urls[:5]


def get_title(sku: str, asin: str | None = None) -> str | None:
    """Return the English product title for a SKU/ASIN.
    Priority: listing_data title for this ASIN → components_sot product_name.
    ASIN's own listing_data row is checked first so bundle ASINs get the
    correct product title, not a component-level title from the SOT table.
    """
    # 1. listing_data by ASIN ref_id — most accurate for the actual Amazon listing
    if asin:
        listing_sql = """
            SELECT title FROM public.listing_data
            WHERE ref_id = %s
              AND title IS NOT NULL AND title != ''
              AND which_channel_name ILIKE '%%amazon%%'
              AND market_place IN ('UK', 'US')
            ORDER BY (CASE WHEN market_place = 'UK' THEN 0 ELSE 1 END), id
            LIMIT 1
        """
        assert_read_only(listing_sql)
        try:
            with readonly_cursor() as cur:
                cur.execute(listing_sql, (asin,))
                row = cur.fetchone()
            if row:
                return row[0]
        except Exception:
            pass

    # 2. components_sot product_name — fallback for standalone (non-bundle) SKUs
    title_sql = """
        SELECT av.value
        FROM public.components_sot_attribute_values av
        JOIN public.components_sot_skus s ON s.id = av.sot_sku_id
        JOIN public.components_sot_attributes a ON a.id = av.attribute_id
        WHERE s.sku = %s AND a.key = 'product_name'
          AND av.value IS NOT NULL AND av.value != ''
        LIMIT 1
    """
    assert_read_only(title_sql)
    try:
        with readonly_cursor() as cur:
            cur.execute(title_sql, (sku,))
            row = cur.fetchone()
        if row:
            return row[0]
    except Exception:
        pass

    return None


def get_description(sku: str, asin: str | None = None) -> str | None:
    """Return product_description from listing_data for an ASIN/SKU."""
    ref = asin or sku
    sql = """
        SELECT product_description
        FROM public.listing_data
        WHERE ref_id = %s
          AND product_description IS NOT NULL
          AND product_description != ''
        LIMIT 1
    """
    assert_read_only(sql)
    try:
        with readonly_cursor() as cur:
            cur.execute(sql, (ref,))
            row = cur.fetchone()
            return row[0] if row else None
    except Exception as exc:
        logger.error("get_description failed for ref=%s: %s: %s", ref, type(exc).__name__, exc)
        return None


def get_variation_attributes(asin: str, sku: str | None = None) -> list[dict]:
    """
    Return the selected_variations list from listing_data for an ASIN (or SKU fallback).

    Each item is {"name": str, "value": str} matching Amazon's variation attribute pairs.
    Returns [] if nothing found or the column is unparseable.
    Prefers the UK marketplace row when multiple rows exist.
    """
    import json as _json

    sql = """
        SELECT selected_variations
        FROM public.listing_data
        WHERE ref_id = %s
          AND selected_variations IS NOT NULL
          AND selected_variations NOT IN ('""', '', 'null')
          AND selected_variations LIKE '[%%'
          AND which_channel_name ILIKE '%%amazon%%'
        ORDER BY (CASE WHEN market_place = 'UK' THEN 0 ELSE 1 END),
                 jsonb_array_length(selected_variations::jsonb) DESC,
                 id
        LIMIT 1
    """
    assert_read_only(sql)

    ref = asin
    try:
        with readonly_cursor() as cur:
            cur.execute(sql, (ref,))
            row = cur.fetchone()
        if row and row[0]:
            parsed = _json.loads(row[0])
            if isinstance(parsed, list):
                return [
                    {"name": str(e.get("name", "") or "").strip().lower(),
                     "value": str(e.get("value", "") or "").strip()}
                    for e in parsed
                    if e.get("value")
                ]
    except Exception as exc:
        logger.warning("get_variation_attributes failed for asin=%s: %s", asin, type(exc).__name__)

    # SKU fallback — look up by sku column
    if sku:
        sql_sku = """
            SELECT selected_variations
            FROM public.listing_data
            WHERE sku = %s
              AND selected_variations IS NOT NULL
              AND selected_variations NOT IN ('""', '', 'null')
              AND selected_variations LIKE '[%%'
              AND which_channel_name ILIKE '%%amazon%%'
            ORDER BY (CASE WHEN market_place = 'UK' THEN 0 ELSE 1 END),
                     jsonb_array_length(selected_variations::jsonb) DESC,
                     id
            LIMIT 1
        """
        assert_read_only(sql_sku)
        try:
            with readonly_cursor() as cur:
                cur.execute(sql_sku, (sku,))
                row = cur.fetchone()
            if row and row[0]:
                parsed = _json.loads(row[0])
                if isinstance(parsed, list):
                    return [
                        {"name": str(e.get("name", "") or "").strip().lower(),
                         "value": str(e.get("value", "") or "").strip()}
                        for e in parsed
                        if e.get("value")
                    ]
        except Exception as exc:
            logger.warning("get_variation_attributes sku fallback failed for sku=%s: %s", sku, type(exc).__name__)

    return []


def get_sibling_titles(asin: str, sku: str | None = None) -> list[str]:
    """Return all UK Amazon titles for siblings in the same parent_sku group (including this ASIN)."""
    parent_sql = """
        SELECT parent_sku FROM public.listing_data
        WHERE ref_id = %s
          AND parent_sku IS NOT NULL AND parent_sku != ''
          AND which_channel_name ILIKE '%%amazon%%'
        ORDER BY (CASE WHEN market_place = 'UK' THEN 0 ELSE 1 END), id
        LIMIT 1
    """
    assert_read_only(parent_sql)
    parent_sku = None
    try:
        with readonly_cursor() as cur:
            cur.execute(parent_sql, (asin,))
            row = cur.fetchone()
        if row:
            parent_sku = row[0]
    except Exception as exc:
        logger.warning("get_sibling_titles parent lookup failed: %s", type(exc).__name__)

    if not parent_sku:
        # Standalone — return just this ASIN's own title
        title_sql = """
            SELECT title FROM public.listing_data
            WHERE ref_id = %s AND title IS NOT NULL AND title != ''
              AND which_channel_name ILIKE '%%amazon%%'
            ORDER BY (CASE WHEN market_place = 'UK' THEN 0 ELSE 1 END), id
            LIMIT 1
        """
        assert_read_only(title_sql)
        try:
            with readonly_cursor() as cur:
                cur.execute(title_sql, (asin,))
                row = cur.fetchone()
            return [row[0]] if row else []
        except Exception:
            return []

    sibling_sql = """
        SELECT DISTINCT ref_id FROM public.listing_data
        WHERE parent_sku = %s
          AND which_channel_name ILIKE '%%amazon%%'
          AND ref_id IS NOT NULL AND ref_id != ''
    """
    assert_read_only(sibling_sql)
    try:
        with readonly_cursor() as cur:
            cur.execute(sibling_sql, (parent_sku,))
            sibling_asins = [r[0] for r in cur.fetchall()]
    except Exception:
        sibling_asins = [asin]

    if not sibling_asins:
        sibling_asins = [asin]

    titles_sql = """
        SELECT DISTINCT title FROM public.listing_data
        WHERE ref_id = ANY(%s)
          AND title IS NOT NULL AND title != ''
          AND which_channel_name ILIKE '%%amazon%%'
          AND (market_place IN ('UK', 'US') OR market_place IS NULL)
        ORDER BY title
    """
    assert_read_only(titles_sql)
    try:
        with readonly_cursor() as cur:
            cur.execute(titles_sql, (sibling_asins,))
            return [r[0] for r in cur.fetchall()]
    except Exception:
        return []


def get_parent_sku_for_asin(asin: str, sku: str | None = None) -> str | None:
    """Return the parent_sku for an ASIN, or None if standalone.
    Queries by ref_id only — SKU-based lookup is intentionally excluded to
    avoid picking up parent_sku from unrelated ASINs sharing a component SKU.
    """
    # Style-value variants (e.g. selected_variations value = "Style 3") are treated
    # as standalone products — exclude them from group lookups.
    sql = """
        SELECT parent_sku
        FROM public.listing_data
        WHERE ref_id = %s
          AND parent_sku IS NOT NULL AND parent_sku != ''
          AND is_child = 1
          AND which_channel_name ILIKE '%%amazon%%'
          AND NOT (
            selected_variations IS NOT NULL
            AND selected_variations ILIKE '%%style%%'
          )
        ORDER BY (CASE WHEN market_place = 'UK' THEN 0 ELSE 1 END), id
        LIMIT 1
    """
    assert_read_only(sql)
    try:
        with readonly_cursor() as cur:
            cur.execute(sql, (asin,))
            row = cur.fetchone()
        return row[0] if row else None
    except Exception as exc:
        logger.warning("get_parent_sku_for_asin failed: %s", type(exc).__name__)
        return None


def get_all_group_variant_values(asin: str, sku: str | None = None) -> list[str]:
    """
    Return variant attribute values that DIFFER across siblings in the same group.

    Only values that vary between siblings are added to the strip list — values
    shared by every sibling are NOT included (they are product-level specs, not
    variant differentiators, and the system prompt's general rules handle them).

    If the ASIN has no siblings / no parent_sku, returns [] so content is
    generated without any forced variant stripping.
    """
    import json as _json

    # Step 1: find the parent_sku for this ASIN
    ref_sql = """
        SELECT parent_sku
        FROM public.listing_data
        WHERE ref_id = %s
          AND parent_sku IS NOT NULL AND parent_sku != ''
          AND which_channel_name ILIKE '%%amazon%%'
        ORDER BY (CASE WHEN market_place = 'UK' THEN 0 ELSE 1 END), id
        LIMIT 1
    """
    assert_read_only(ref_sql)
    parent_sku = None
    try:
        with readonly_cursor() as cur:
            cur.execute(ref_sql, (asin,))
            row = cur.fetchone()
        if row:
            parent_sku = row[0]
    except Exception as exc:
        logger.warning("get_all_group_variant_values parent lookup failed: %s", type(exc).__name__)

    if not parent_sku:
        # No siblings — standalone product, no variant stripping needed
        return []

    # Step 2: collect selected_variations from all UK siblings
    siblings_sql = """
        SELECT selected_variations
        FROM public.listing_data
        WHERE parent_sku = %s
          AND selected_variations IS NOT NULL
          AND selected_variations NOT IN ('""', '', 'null')
          AND selected_variations LIKE '[%%'
          AND which_channel_name ILIKE '%%amazon%%'
          AND market_place IN ('UK', 'US')
    """
    assert_read_only(siblings_sql)

    # attr_name → set of values seen across all siblings
    attr_values: dict[str, set[str]] = {}
    sibling_count = 0

    try:
        with readonly_cursor() as cur:
            cur.execute(siblings_sql, (parent_sku,))
            rows = cur.fetchall()
        for (sv,) in rows:
            try:
                parsed = _json.loads(sv)
                if not isinstance(parsed, list):
                    continue
                sibling_count += 1
                for e in parsed:
                    name = str(e.get("name") or e.get("Name") or "").strip().lower()
                    val = str(e.get("value") or e.get("Value") or "").strip()
                    if name and val:
                        attr_values.setdefault(name, set()).add(val)
            except Exception:
                pass
    except Exception as exc:
        logger.warning("get_all_group_variant_values sibling query failed: %s", type(exc).__name__)

    if sibling_count == 0:
        return []

    # Generic words that appear in compound variant values but are too common
    # to be reliable strip terms (e.g. "Bulb" in "Fits any E27 bulb")
    _GENERIC_SKIP = frozenset({
        "bulb", "bulbs", "pack", "set", "kit", "piece", "pcs", "pc",
        "unit", "units", "pair", "bundle", "yes", "no", "with", "without",
        "and", "or", "the", "a", "an",
    })

    # Step 3: only keep values for attributes that differ across siblings
    strip_values: set[str] = set()
    for name, values in attr_values.items():
        if len(values) > 1:
            # This attribute varies → all its values are variant-specific
            for val in values:
                strip_values.add(val)
                # Split compound values like "Brushed Copper + Cage" into parts,
                # but skip generic single words that could match product descriptions
                for part in val.replace("+", ",").split(","):
                    part = part.strip()
                    if len(part) >= 3 and part.lower() not in _GENERIC_SKIP and " " not in part:
                        # Only add single-word parts that are specific (colour names, etc.)
                        strip_values.add(part)
                    elif " " in part and len(part) >= 4:
                        # Multi-word parts are specific enough to keep
                        strip_values.add(part)

    return sorted(strip_values)


def _clean_bullet(text: str) -> str:
    """Strip Unicode bold/italic math glyphs and common symbols from bullet text."""
    text = _re.sub(r'[\U0001D400-\U0001D7FF]', '', text)
    text = _re.sub(r'[™©®℠†‡•·°]', '', text)
    return _re.sub(r' {2,}', ' ', text).strip()


def get_bullet_points(sku: str, asin: str | None = None) -> list[str]:
    """Return up to 5 bullet points from listing_data.bullet_points join."""
    ref = asin or sku

    # Primary: match by ref_id (ASIN) only — ref_id uniquely identifies the listing row.
    # Do NOT filter by sku here: bundle ASINs store the full bundle SKU in listing_data
    # (e.g. CRSF120CH+WSUSHE27CH+LSGLSC1508CL) which won't match the primary_sku component.
    if asin:
        sql_by_ref = """
            SELECT bp.points, bp.view_order
            FROM public.bullet_points bp
            WHERE bp.product_id = (
                SELECT id FROM public.listing_data
                WHERE ref_id = %s
                  AND which_channel_name ILIKE '%%amazon%%'
                  AND market_place IN ('UK', 'US')
                ORDER BY (CASE WHEN market_place = 'UK' THEN 0 ELSE 1 END), id
                LIMIT 1
            )
              AND bp.points IS NOT NULL AND bp.points != ''
            ORDER BY bp.view_order
        """
        assert_read_only(sql_by_ref)
        try:
            with readonly_cursor() as cur:
                cur.execute(sql_by_ref, (asin,))
                rows = cur.fetchall()
            if rows:
                return [_clean_bullet(r[0]) for r in rows]
        except Exception as exc:
            logger.warning("get_bullet_points (by ref_id) failed for asin=%s: %s", asin, type(exc).__name__)

    # Fallback: match by exact full SKU (listing_data.sku), not primary component
    sql_by_sku = """
        SELECT bp.points, bp.view_order
        FROM public.bullet_points bp
        JOIN public.listing_data ld ON ld.id = bp.product_id
        WHERE ld.sku = %s
          AND bp.points IS NOT NULL AND bp.points != ''
        ORDER BY bp.view_order
    """
    assert_read_only(sql_by_sku)
    try:
        with readonly_cursor() as cur:
            cur.execute(sql_by_sku, (sku,))
            rows = cur.fetchall()
        if rows:
            return [_clean_bullet(r[0]) for r in rows]
    except Exception as exc:
        logger.error("get_bullet_points (by sku) failed for sku=%s: %s", sku, type(exc).__name__)

    return []


def get_sot_attributes(sku: str, attribute_keys: list[str] | None = None) -> list[SotAttribute]:
    """Retrieve SOT attributes for a SKU. If attribute_keys given, filter to those keys only."""

    if attribute_keys is not None:
        sql = """
            SELECT a.id, a.key, a.label, av.value, a.sort_order, s.source_tab
            FROM public.components_sot_attribute_values av
            JOIN public.components_sot_skus s ON s.id = av.sot_sku_id
            JOIN public.components_sot_attributes a ON a.id = av.attribute_id
            WHERE s.sku = %s
              AND av.value IS NOT NULL
              AND av.value != ''
              AND a.key = ANY(%s)
            ORDER BY a.sort_order, a.key
        """
        assert_read_only(sql)
        params = (sku, attribute_keys)
    else:
        sql = """
            SELECT a.id, a.key, a.label, av.value, a.sort_order, s.source_tab
            FROM public.components_sot_attribute_values av
            JOIN public.components_sot_skus s ON s.id = av.sot_sku_id
            JOIN public.components_sot_attributes a ON a.id = av.attribute_id
            WHERE s.sku = %s
              AND av.value IS NOT NULL
              AND av.value != ''
            ORDER BY a.sort_order, a.key
        """
        assert_read_only(sql)
        params = (sku,)

    try:
        with readonly_cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("get_sot_attributes failed: %s", type(exc).__name__)
        return []

    results = []
    for row in rows:
        attr_id, key, label, value, order, source_tab = row
        results.append(SotAttribute(
            attribute_id=attr_id,
            attribute_key=key,
            attribute_label=label,
            value=value,
            display_order=order,
            source_tab=source_tab,
        ))
    return results
