"""
Cross-category comparison of template profiles.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.analyser.inspector import WorkbookProfile


@dataclass
class FuzzyMatch:
    category_a: str
    header_a: str
    category_b: str
    header_b: str
    similarity: float
    note: str = "fuzzy suggestion only – requires human review before accepting"


@dataclass
class ComparisonResult:
    shared_by_all: list[str]              # normalized headers present in every category
    shared_by_some: dict[str, list[str]]  # normalized header -> list of categories
    unique_per_category: dict[str, list[str]]  # category -> unique normalized headers
    required_diff: dict[str, list[str]]   # category -> required fields
    controlled_diff: dict[str, list[str]] # category -> controlled fields
    fuzzy_suggestions: list[FuzzyMatch]
    warnings: list[str] = field(default_factory=list)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).lower() if s else ""


def _headers_for(profile: WorkbookProfile) -> list[str]:
    if not profile.listing_sheet:
        return []
    return [
        col.normalized_header
        for col in profile.listing_sheet.columns
        if col.normalized_header
    ]


def compare_profiles(profiles: list[WorkbookProfile]) -> ComparisonResult:
    valid = [p for p in profiles if p.listing_sheet]
    if not valid:
        return ComparisonResult([], {}, {}, {}, {}, [])

    # Build per-category header sets
    cat_headers: dict[str, set[str]] = {}
    for p in valid:
        cat_headers[p.category_name] = set(_headers_for(p))

    all_headers: set[str] = set()
    for hs in cat_headers.values():
        all_headers |= hs

    shared_by_all = sorted(h for h in all_headers if all(h in hs for hs in cat_headers.values()))

    shared_by_some: dict[str, list[str]] = {}
    for h in sorted(all_headers):
        cats = [c for c, hs in cat_headers.items() if h in hs]
        if 1 < len(cats) < len(cat_headers):
            shared_by_some[h] = cats

    unique_per_category: dict[str, list[str]] = {}
    for cat, hs in cat_headers.items():
        others = set()
        for other_cat, other_hs in cat_headers.items():
            if other_cat != cat:
                others |= other_hs
        unique_per_category[cat] = sorted(hs - others)

    # Required fields per category
    required_diff: dict[str, list[str]] = {}
    for p in valid:
        if not p.listing_sheet:
            continue
        req = [col.original_header for col in p.listing_sheet.columns
               if col.required_status.lower() == "required"]
        required_diff[p.category_name] = req

    # Controlled fields per category
    controlled_diff: dict[str, list[str]] = {}
    for p in valid:
        if not p.listing_sheet:
            continue
        ctrl = [col.original_header for col in p.listing_sheet.columns if col.is_controlled]
        controlled_diff[p.category_name] = ctrl

    # Fuzzy matching for unique headers
    fuzzy: list[FuzzyMatch] = []
    FUZZY_THRESHOLD = 0.75
    unique_lists = {cat: unique_per_category[cat] for cat in unique_per_category}
    cats = list(unique_lists.keys())
    for i, cat_a in enumerate(cats):
        for cat_b in cats[i + 1:]:
            for ha in unique_lists[cat_a]:
                for hb in unique_lists[cat_b]:
                    ratio = SequenceMatcher(None, ha, hb).ratio()
                    if ratio >= FUZZY_THRESHOLD:
                        fuzzy.append(FuzzyMatch(
                            category_a=cat_a,
                            header_a=ha,
                            category_b=cat_b,
                            header_b=hb,
                            similarity=round(ratio, 3),
                        ))

    return ComparisonResult(
        shared_by_all=shared_by_all,
        shared_by_some=shared_by_some,
        unique_per_category=unique_per_category,
        required_diff=required_diff,
        controlled_diff=controlled_diff,
        fuzzy_suggestions=fuzzy,
    )
