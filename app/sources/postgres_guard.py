from __future__ import annotations
import re

_WRITE_KEYWORDS = re.compile(
    r'\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|CREATE|ALTER|DROP|GRANT|REVOKE|COPY|CALL|DO)\b',
    re.IGNORECASE
)
_APPROVED_SCHEMAS = frozenset({"public"})
_APPROVED_TABLES = frozenset({
    "public.components_sot_attributes",
    "public.components_sot_attribute_values",
    "public.components_sot_skus",
    "public.listing_data",
    "public.bullet_points",
    "public.sub_images",
})

def assert_read_only(sql: str) -> None:
    if _WRITE_KEYWORDS.search(sql):
        raise ValueError(f"Blocked: SQL contains write operation keyword")

def approved_tables() -> frozenset[str]:
    return _APPROVED_TABLES
