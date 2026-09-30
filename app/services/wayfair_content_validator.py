"""
Deterministic post-generation validator for Amazon-to-Wayfair converted content.

Validates ConversionResult objects against content rules without calling any AI.
Never mutates the original result — returns a new instance with updated status
and validation_errors.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.amazon_to_wayfair_converter import ConversionResult


def _word_count(text: str) -> int:
    return len(text.split()) if text.strip() else 0


def _ends_with_punctuation(text: str) -> bool:
    return bool(text.strip()) and text.strip()[-1] in ".!?;:,"


def _contains_term(text: str, term: str) -> bool:
    pattern = r"(?<!\w)" + re.escape(term.strip()) + r"(?!\w)"
    return bool(re.search(pattern, text, re.IGNORECASE))


def validate_conversion(
    result: "ConversionResult",
    brand: str = "",
    supplier: str = "",
    variant_values: list[str] | None = None,
) -> "ConversionResult":
    """
    Run all deterministic validation rules against a ConversionResult.

    Returns a new ConversionResult with status set to 'valid' or 'requires_review'
    and validation_errors populated.  The original object is not modified.
    """
    errors: list[str] = list(result.validation_errors)

    # ── Brand / supplier term checks ─────────────────────────────────────────
    brand_terms = [t for t in [brand, supplier] if t and t.strip()]
    # Always-strip legal suffixes
    legal_suffixes = ["LLC", "Inc", "Ltd", "Corp", "GmbH", "Co."]
    all_brand_terms = brand_terms + [s for s in legal_suffixes if s not in brand_terms]

    content_fields = {
        "Product Name": result.product_name,
        "Marketing Copy": result.marketing_copy,
    }
    for i, b in enumerate(result.feature_bullets, 1):
        content_fields[f"Feature Bullet {i}"] = b

    for field_name, text in content_fields.items():
        if not text:
            continue
        for term in all_brand_terms:
            if term and _contains_term(text, term):
                errors.append(f"{field_name}: contains brand/supplier term '{term}'")

    # ── Variant term checks ───────────────────────────────────────────────────
    if variant_values:
        for field_name, text in content_fields.items():
            if not text:
                continue
            for val in variant_values:
                if val and len(val) >= 2 and _contains_term(text, val):
                    errors.append(f"{field_name}: contains variant-specific term '{val}'")

    # ── Product Name ─────────────────────────────────────────────────────────
    if not result.product_name or not result.product_name.strip():
        errors.append("Product Name: empty or missing")
    elif len(result.product_name.strip()) < 5:
        errors.append("Product Name: too short (< 5 characters)")

    # ── Marketing Copy word count ─────────────────────────────────────────────
    mc_words = _word_count(result.marketing_copy)
    if mc_words < 75:
        errors.append(f"Marketing Copy: {mc_words} words, minimum is 75")
    elif mc_words > 100:
        errors.append(f"Marketing Copy: {mc_words} words, maximum is 100")

    if not result.marketing_copy.strip():
        errors.append("Marketing Copy: empty or missing")

    # ── Marketing Copy no HTML ────────────────────────────────────────────────
    if re.search(r"<[^>]+>", result.marketing_copy):
        errors.append("Marketing Copy: contains HTML tags")

    # ── Feature Bullet count ─────────────────────────────────────────────────
    bullet_count = len(result.feature_bullets)
    if bullet_count < 3:
        errors.append(f"Feature Bullets: only {bullet_count} bullet(s), minimum is 3")
    elif bullet_count > 5:
        errors.append(f"Feature Bullets: {bullet_count} bullets, maximum is 5")

    # ── Per-bullet checks ─────────────────────────────────────────────────────
    seen_bullets: list[str] = []
    for i, bullet in enumerate(result.feature_bullets, 1):
        stripped = bullet.strip()

        if _ends_with_punctuation(stripped):
            errors.append(f"Feature Bullet {i}: ends with punctuation")

        word_ct = _word_count(stripped)
        if word_ct > 10:
            errors.append(f"Feature Bullet {i}: {word_ct} words, preferred maximum is 10")

        # Duplicate detection (case-insensitive, normalised whitespace)
        normalised = re.sub(r"\s+", " ", stripped.lower())
        if normalised in [re.sub(r"\s+", " ", s.strip().lower()) for s in seen_bullets]:
            errors.append(f"Feature Bullet {i}: duplicate of an earlier bullet")
        seen_bullets.append(stripped)

    status = "valid" if not errors else "requires_review"

    from app.services.amazon_to_wayfair_converter import ConversionResult as CR
    return CR(
        group_ref_id=result.group_ref_id,
        product_name=result.product_name,
        marketing_copy=result.marketing_copy,
        marketing_copy_word_count=_word_count(result.marketing_copy),
        feature_bullets=result.feature_bullets,
        status=status,
        validation_errors=errors,
    )
