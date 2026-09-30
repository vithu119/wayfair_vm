from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class SotAttribute:
    attribute_id: int
    attribute_key: str
    attribute_label: str
    value: str
    display_order: int
    source_tab: str

@dataclass
class ProductIdentity:
    input_asin: str
    asin: str | None = None
    internal_sku: str | None = None   # raw composite from bridge
    primary_sku: str | None = None    # first component SKU
    component_skus: list[str] = field(default_factory=list)  # all components
    source_tab: str | None = None
    product_subtype: str | None = None
    wayfair_category: str | None = None
    channel: str | None = None
    validation_status: str | None = None
    child_asins: list[str] = field(default_factory=list)  # populated when input is a parent ASIN
    status: str = "asin_not_found"    # resolved | parent_asin | asin_not_found | duplicate_match | ambiguous_match | sku_not_found | inactive_product
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

@dataclass
class ParsedSotValue:
    raw_value: str
    parsed_value: object
    unit: str | None = None
    value_type: str = "text"   # text | integer | decimal | boolean | measurement | measurement_range | colour_hex | ip_rating | list | unknown
    range_min: float | None = None
    range_max: float | None = None
    numeric: float | None = None
    warnings: list[str] = field(default_factory=list)
