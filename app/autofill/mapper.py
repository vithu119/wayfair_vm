"""
Load field_mappings.yaml and fixed_values.yaml, then resolve a source row
to a dict of {wayfair_field: value} for a given category.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml  # PyYAML

from app.autofill.transformer import apply as transform_value


@dataclass
class MappingRule:
    wayfair_field: str
    aliases: list[str]
    categories: list[str]   # ["all"] or specific names
    transform: str | None
    fixed_value: str | None
    default_value: str | None
    required: bool
    notes: str


@dataclass
class FixedValueRule:
    wayfair_field: str
    value: str
    categories: list[str]


@dataclass
class MappingResult:
    wayfair_field: str
    source_field: str | None        # which alias was found, or None
    raw_value: str
    final_value: str
    transform_applied: str | None
    transform_warning: str | None
    source: str                     # "source_data" | "fixed_value" | "default" | "unmapped"
    is_required: bool
    is_empty: bool


def _norm(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[\s\-/]+", "_", s)
    s = re.sub(r"[^\w]", "", s)
    return s


def load_mappings(config_dir: str | Path) -> tuple[list[MappingRule], list[FixedValueRule]]:
    config_dir = Path(config_dir)
    mappings_path = config_dir / "field_mappings.yaml"
    fixed_path = config_dir / "fixed_values.yaml"

    rules: list[MappingRule] = []
    if mappings_path.exists():
        data = yaml.safe_load(mappings_path.read_text(encoding="utf-8")) or {}
        for entry in data.get("mappings", []):
            rules.append(MappingRule(
                wayfair_field=entry["wayfair_field"],
                aliases=[_norm(a) for a in entry.get("aliases", [])],
                categories=entry.get("categories", ["all"]),
                transform=entry.get("transform"),
                fixed_value=entry.get("fixed_value"),
                default_value=entry.get("default_value"),
                required=bool(entry.get("required", False)),
                notes=entry.get("notes", ""),
            ))

    fixed: list[FixedValueRule] = []
    if fixed_path.exists():
        data = yaml.safe_load(fixed_path.read_text(encoding="utf-8")) or {}
        for entry in data.get("fixed_values", []):
            val = entry.get("value", "")
            if val:  # skip empty stubs
                fixed.append(FixedValueRule(
                    wayfair_field=entry["wayfair_field"],
                    value=str(val),
                    categories=entry.get("categories", ["all"]),
                ))

    return rules, fixed


def _category_matches(rule_categories: list[str], category_name: str) -> bool:
    if "all" in [c.lower() for c in rule_categories]:
        return True
    cat_norm = _norm(category_name)
    return any(_norm(c) == cat_norm for c in rule_categories)


def resolve_row(
    source_row: dict[str, str],
    rules: list[MappingRule],
    fixed_rules: list[FixedValueRule],
    category_name: str,
    wayfair_headers: list[str],     # exact headers from the listing sheet, in order
) -> list[MappingResult]:
    """
    For every Wayfair header in the listing sheet, produce one MappingResult.
    """
    # Build normalised alias lookup from source row
    source_norm = source_row  # already normalised keys from source_reader

    # Fixed-value overrides keyed by wayfair_field (normalised)
    fixed_map: dict[str, str] = {}
    for fr in fixed_rules:
        if _category_matches(fr.categories, category_name):
            fixed_map[_norm(fr.wayfair_field)] = fr.value

    # Build rule lookup by normalised wayfair_field
    rule_map: dict[str, MappingRule] = {}
    for rule in rules:
        if _category_matches(rule.categories, category_name):
            rule_map[_norm(rule.wayfair_field)] = rule

    results: list[MappingResult] = []

    for wf_header in wayfair_headers:
        wf_norm = _norm(wf_header)

        # 1. Fixed value takes top priority
        if wf_norm in fixed_map:
            fv = fixed_map[wf_norm]
            results.append(MappingResult(
                wayfair_field=wf_header,
                source_field=None,
                raw_value=fv,
                final_value=fv,
                transform_applied=None,
                transform_warning=None,
                source="fixed_value",
                is_required=False,
                is_empty=(fv == ""),
            ))
            continue

        rule = rule_map.get(wf_norm)

        # 2. Fixed value on the rule itself
        if rule and rule.fixed_value is not None:
            fv = rule.fixed_value
            val, warn = transform_value(fv, rule.transform)
            results.append(MappingResult(
                wayfair_field=wf_header,
                source_field=None,
                raw_value=fv,
                final_value=val,
                transform_applied=rule.transform,
                transform_warning=warn,
                source="fixed_value",
                is_required=rule.required,
                is_empty=(val == ""),
            ))
            continue

        # 3. Try aliases from source
        found_alias: str | None = None
        raw: str = ""
        if rule:
            for alias in rule.aliases:
                if alias in source_norm:
                    found_alias = alias
                    raw = source_norm[alias]
                    break

        # 4. Default value fallback
        if not raw and rule and rule.default_value is not None:
            raw = rule.default_value
            src_label = "default"
        else:
            src_label = "source_data" if found_alias else "unmapped"

        # 5. Apply transform
        if rule and raw:
            val, warn = transform_value(raw, rule.transform)
        else:
            val, warn = raw.strip(), None

        # 6. Strip brand name from Product Name (case-insensitive, anywhere in string)
        if wf_norm == "product_name" and val:
            brand_raw = ""
            for alias in ("brand", "manufacturer", "brand_name"):
                if alias in source_norm:
                    brand_raw = source_norm[alias].strip()
                    break
            if brand_raw:
                pattern = re.compile(re.escape(brand_raw) + r"[\s\-–—,]*", re.IGNORECASE)
                val = pattern.sub("", val).strip()

        results.append(MappingResult(
            wayfair_field=wf_header,
            source_field=found_alias,
            raw_value=raw,
            final_value=val,
            transform_applied=rule.transform if rule else None,
            transform_warning=warn,
            source=src_label,
            is_required=rule.required if rule else False,
            is_empty=(val == ""),
        ))

    return results
