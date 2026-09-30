"""
Amazon → Wayfair BGCT content converter.

Uses a Qwen-compatible (OpenAI-format) LLM to produce Product Name,
Marketing Copy, and Feature Bullets from Amazon listing content, then
runs the deterministic post-generation validator.

Required .env keys:
    QWEN_API_KEY   — your Qwen/DashScope API key
    QWEN_BASE_URL  — e.g. https://dashscope-intl.aliyuncs.com/compatible-mode/v1
    QWEN_MODEL     — e.g. qwen-plus
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from openai import OpenAI

# Known bulb/socket types that are always variant-specific and must be stripped
_BULB_TYPE_PATTERN = re.compile(
    r"\b(E\d{1,2}|B\d{1,2}|GU\d{1,2}|G\d{1,2}|MR\d{1,2}|PAR\d{1,2}|R\d{1,2}|"
    r"BA\d{1,2}[ds]?|T\d{1,2}|2-pin|bi-pin)\b",
    re.IGNORECASE,
)

# Detects pack/set count phrasings the LLM may generate (e.g. "Set of Three", "Twin Pack")
_PACK_COUNT_PATTERN = re.compile(
    r"\b(\d+\s*-?\s*pack|\d+\s*-?\s*pk|pack\s+of\s+\w+|set\s+of\s+\w+|"
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten)\s*(?:-\s*)?pack|"
    r"(?:single|twin|double|triple|quad)\s*(?:pack)?)\b",
    re.IGNORECASE,
)

_PACK_VARIANT_RE = re.compile(r"\d+\s*-?\s*p(?:ac)?k\b", re.IGNORECASE)

# ── ConversionResult ──────────────────────────────────────────────────────────

@dataclass
class ConversionResult:
    group_ref_id: str
    product_name: str
    marketing_copy: str
    marketing_copy_word_count: int
    feature_bullets: list[str]
    status: str = "pending"          # pending | valid | requires_review | error
    validation_errors: list[str] = field(default_factory=list)
    raw_llm_output: str = ""
    effective_variant_terms: list[str] = field(default_factory=list)


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert Wayfair UK product copywriter. Convert Amazon listing content \
into Wayfair's required Product Name / Marketing Copy / Feature Bullets format.

CRITICAL — NUMBERS AND QUANTITIES:
You MUST NOT invent, guess, round, or change any number, quantity, measurement, \
dimension, or named value (e.g. pack counts like "40 plugs", sizes like "8mm", \
ratings like "IP44", codes like "M6"). Only write a number if it appears VERBATIM \
in the source content below. If the quantity is not in the source, do NOT write \
a bullet about it — omit it entirely. Writing "30" when the source says "40" is \
a critical error.

HARD WORD-COUNT RULES — these are non-negotiable:
• Marketing Copy MUST be between 75 and 95 words. After writing it, COUNT \
the words yourself. If the count is above 95, delete words until it is 95 or \
fewer. If it is below 75, add more detail. Do NOT output until the count is \
in range. 95 words is the absolute ceiling — never exceed it.
• Feature Bullets: you MUST write EXACTLY 5 bullets — no more, no fewer. \
Each bullet MUST be 5–10 words. Short phrases only — NOT full sentences. \
If a bullet exceeds 10 words, cut it. If you have written more than 5 bullets, \
delete the least important ones until exactly 5 remain.

OTHER RULES YOU MUST NEVER BREAK:
1. Never include brand or supplier names anywhere in the output.
2. Never include the specific terms listed under VARIANT ATTRIBUTES TO STRIP — those \
are the only values that differ across product variants. Specs that apply to ALL \
variants of the product (e.g. a socket type shared by every variant) are product \
features, not variant details, and may be included.
3. Feature Bullets must NOT end in a period or any punctuation.
4. Marketing Copy and Feature Bullets must cover DIFFERENT aspects of the product. \
If a specific detail (material, socket type, dimension, feature) appears in a bullet, \
do NOT mention it in the Marketing Copy. Use Marketing Copy for overall style, mood, \
and room suitability; use Bullets for specific product specifications and features.
5. Never fabricate product features not supported by the source content.
6. NEVER change, round, or invent specific numbers, quantities, measurements, or named values \
(e.g. "40 plugs", "8mm", "M6", "IP44", "RAL 9010"). Use the exact figures from the source. \
If a number is not in the source content, do NOT include it — omit the detail entirely rather \
than guessing.

OUTPUT FORMAT — respond with ONLY this block, no extra text:

Product Name:
<title>

Marketing Copy:
<75–95 word paragraph — count words before outputting, must not exceed 95>

Feature Bullets:
- <5–10 word phrase>
- <5–10 word phrase>
- <5–10 word phrase>
- <5–10 word phrase>
- <5–10 word phrase>
"""

_USER_TEMPLATE = """\
Convert the following Amazon listing into Wayfair BGCT format.

Group / Product Reference: {group_ref_id}

AMAZON TITLES (one per variant — derive one common Product Name for the family):
{amazon_title}

AMAZON BULLET POINTS:
{amazon_bullets}

AMAZON DESCRIPTION:
{amazon_description}

VARIANT ATTRIBUTES TO STRIP (do not include any of these terms):
{variant_terms}

REMINDER: Only use numbers/quantities that appear verbatim in the source above. \
Do NOT guess or invent pack counts, sizes, or measurements. If unsure, omit the number.

Follow the rules exactly. Return only the structured block described.
"""


# ── Retry prompt (marketing copy too short) ──────────────────────────────────

_RETRY_SHORT_TEMPLATE = """\
The Marketing Copy you wrote is only {word_count} words. It MUST be 75–95 words.

Here is what you wrote:
\"\"\"{copy}\"\"\"

Rewrite ONLY the Marketing Copy to reach 75–95 words by:
- Expanding on how the product looks and feels
- Adding a sentence about where it works best in the home
- Describing the benefit to the customer more fully
Do NOT change the Product Name or Feature Bullets.
Do NOT add variant-specific details (colour, size, finish).
Do NOT mention brand or supplier names.

Return the full structured block again:

Product Name:
{product_name}

Marketing Copy:
<expanded 75–95 word paragraph>

Feature Bullets:
{bullets_block}
"""

_RETRY_LONG_TEMPLATE = """\
The Marketing Copy you wrote is {word_count} words. The hard maximum is 95 words — you MUST trim it.

Here is what you wrote:
\"\"\"{copy}\"\"\"

Rewrite ONLY the Marketing Copy to reach exactly 75–95 words by:
- Removing redundant or filler phrases
- Combining short sentences where possible
- Keeping the most distinctive product details
Do NOT change the Product Name or Feature Bullets.
Do NOT add variant-specific details (colour, size, finish).
Do NOT mention brand or supplier names.

Return the full structured block again:

Product Name:
{product_name}

Marketing Copy:
<trimmed 75–95 word paragraph>

Feature Bullets:
{bullets_block}
"""


def _extract_bulb_types(text: str) -> list[str]:
    """Return any bulb/socket type codes found in text (e.g. ['E27', 'B22'])."""
    return list({m.group(0).upper() for m in _BULB_TYPE_PATTERN.finditer(text)})


def _has_pack_variants(variant_terms: list[str]) -> bool:
    """True when any variant term looks like a pack count (e.g. '1Pack', '2Pack')."""
    return any(_PACK_VARIANT_RE.search(t) for t in variant_terms)


def _strip_variant_terms_from_name(name: str, variant_terms: list[str]) -> str:
    """Remove variant-specific terms from a product name, then clean up whitespace/punctuation."""
    result = name
    for term in variant_terms:
        if not term:
            continue
        pattern = r"(?<!\w)" + re.escape(term.strip()) + r"(?!\w)"
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)
    # If pack count is a variant, also strip any pack/set phrasing the LLM may have generated
    if _has_pack_variants(variant_terms):
        result = _PACK_COUNT_PATTERN.sub("", result)
    # Collapse multiple spaces and strip trailing separators
    result = re.sub(r"\s{2,}", " ", result).strip().strip("-–,;").strip()
    return result


def _is_only_wordcount_error(errors: list[str]) -> bool:
    """True when every validation error is a marketing copy word-count issue."""
    return bool(errors) and all(
        "Marketing Copy:" in e and ("words, minimum" in e or "words, maximum" in e)
        for e in errors
    )


def _wordcount_direction(errors: list[str]) -> str:
    """Return 'short' or 'long' based on the word-count error direction."""
    for e in errors:
        if "words, minimum" in e:
            return "short"
        if "words, maximum" in e:
            return "long"
    return "short"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_client() -> OpenAI:
    import logging as _logging
    _log = _logging.getLogger(__name__)
    api_key = os.environ.get("QWEN_API_KEY", "")
    base_url = os.environ.get("QWEN_BASE_URL", "").strip() or "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    _log.warning("_build_client: base_url=%r api_key_set=%s", base_url, bool(api_key))
    if not api_key:
        raise ValueError("QWEN_API_KEY is not set in the environment / .env file")
    return OpenAI(api_key=api_key, base_url=base_url, timeout=240.0)


def _model() -> str:
    return os.environ.get("QWEN_MODEL", "qwen-plus")


def _parse_llm_output(raw: str) -> tuple[str, str, list[str]]:
    """Extract product_name, marketing_copy, feature_bullets from LLM output."""
    product_name = ""
    marketing_copy = ""
    feature_bullets: list[str] = []

    # Product Name
    m = re.search(r"Product Name:\s*\n(.+?)(?=\n\n|Marketing Copy:|$)", raw, re.DOTALL | re.IGNORECASE)
    if m:
        product_name = m.group(1).strip()

    # Marketing Copy
    m = re.search(r"Marketing Copy:\s*\n(.+?)(?=\n\nFeature Bullets:|$)", raw, re.DOTALL | re.IGNORECASE)
    if m:
        marketing_copy = m.group(1).strip()

    # Feature Bullets
    m = re.search(r"Feature Bullets:\s*\n(.+?)$", raw, re.DOTALL | re.IGNORECASE)
    if m:
        bullets_block = m.group(1).strip()
        for line in bullets_block.splitlines():
            line = line.strip().lstrip("-•*").strip()
            if line:
                feature_bullets.append(line)

    return product_name, marketing_copy, feature_bullets


def _word_count(text: str) -> int:
    return len(text.split()) if text.strip() else 0


def _trim_to_word_limit(text: str, max_words: int = 100) -> str:
    """
    If text exceeds max_words by 1–10 words, trim it down gracefully:
    1. Try to cut at the last sentence boundary (. ! ?) within the word limit.
    2. Fall back to the last comma within the word limit + a period.
    3. Hard-truncate at max_words as a last resort.
    """
    words = text.split()
    if len(words) <= max_words:
        return text
    if len(words) > max_words + 10:
        return text  # too far over — leave for human review / retry

    candidate = " ".join(words[:max_words])

    # 1. Sentence boundary
    for end in (".", "!", "?"):
        idx = candidate.rfind(end)
        if idx != -1:
            return candidate[: idx + 1].strip()

    # 2. Comma boundary — append a period to close the sentence
    idx = candidate.rfind(",")
    if idx != -1:
        return candidate[:idx].strip() + "."

    # 3. Hard truncate
    return candidate.rstrip(",.;:") + "."


# ── Public API ────────────────────────────────────────────────────────────────

def convert(
    amazon_title: str | list[str],
    amazon_bullets: str | list[str],
    amazon_description: str,
    group_ref_id: str = "",
    variant_terms: list[str] | None = None,
) -> ConversionResult:
    """
    Convert Amazon listing content to Wayfair BGCT format via Qwen LLM,
    then run the deterministic validator.

    amazon_title may be a single title string or a list of sibling titles.
    When multiple titles are provided, the LLM derives one common Product Name
    for the whole sibling family.

    Returns a ConversionResult with status='valid' or 'requires_review'.
    """
    if isinstance(amazon_bullets, list):
        amazon_bullets = "\n".join(f"• {b}" for b in amazon_bullets if b)

    if isinstance(amazon_title, list):
        titles_block = "\n".join(f"- {t.strip()}" for t in amazon_title if t.strip())
        amazon_title_str = titles_block
    else:
        amazon_title_str = amazon_title.strip()

    all_variant_terms: list[str] = list(variant_terms or [])
    variant_str = ", ".join(all_variant_terms) if all_variant_terms else "(none provided)"

    user_msg = _USER_TEMPLATE.format(
        group_ref_id=group_ref_id or "N/A",
        amazon_title=amazon_title_str,
        amazon_bullets=amazon_bullets.strip(),
        amazon_description=amazon_description.strip(),
        variant_terms=variant_str,
    )

    import logging as _logging
    _logging.getLogger(__name__).warning(
        "LLM INPUT for group=%s\n=== USER MSG ===\n%s\n================",
        group_ref_id, user_msg,
    )

    client = _build_client()
    response = client.chat.completions.create(
        model=_model(),
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.4,
        max_tokens=600,
    )

    raw_output = response.choices[0].message.content or ""
    product_name, marketing_copy, feature_bullets = _parse_llm_output(raw_output)

    # Deterministic post-processing
    product_name = _strip_variant_terms_from_name(product_name, all_variant_terms)
    marketing_copy = _trim_to_word_limit(marketing_copy)
    feature_bullets = feature_bullets[:5]  # hard cap — validator requires 3–5

    result = ConversionResult(
        group_ref_id=group_ref_id,
        product_name=product_name,
        marketing_copy=marketing_copy,
        marketing_copy_word_count=_word_count(marketing_copy),
        feature_bullets=feature_bullets,
        status="pending",
        raw_llm_output=raw_output,
    )

    # Run deterministic post-generation validation
    from app.services.wayfair_content_validator import validate_conversion
    validated = validate_conversion(result, variant_values=variant_terms)

    # Auto-retry when the only failure is marketing copy word count
    if _is_only_wordcount_error(validated.validation_errors):
        direction = _wordcount_direction(validated.validation_errors)
        template = _RETRY_SHORT_TEMPLATE if direction == "short" else _RETRY_LONG_TEMPLATE
        bullets_block = "\n".join(f"- {b}" for b in validated.feature_bullets)
        retry_msg = template.format(
            word_count=validated.marketing_copy_word_count,
            copy=validated.marketing_copy,
            product_name=validated.product_name,
            bullets_block=bullets_block,
        )
        retry_response = client.chat.completions.create(
            model=_model(),
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": raw_output},
                {"role": "user", "content": retry_msg},
            ],
            temperature=0.5,
            max_tokens=600,
        )
        retry_raw = retry_response.choices[0].message.content or ""
        retry_name, retry_copy, retry_bullets = _parse_llm_output(retry_raw)
        retry_name = _strip_variant_terms_from_name(retry_name or validated.product_name, all_variant_terms)

        # Only accept retry if it moved in the right direction; keep original bullets
        retry_wc = _word_count(retry_copy)
        improved = (direction == "short" and retry_wc > validated.marketing_copy_word_count) or \
                   (direction == "long" and retry_wc < validated.marketing_copy_word_count)
        if improved:
            # Always trim the retry copy — handles marginal over-limit after expansion
            retry_copy = _trim_to_word_limit(retry_copy)
            retry_result = ConversionResult(
                group_ref_id=group_ref_id,
                product_name=retry_name,
                marketing_copy=retry_copy,
                marketing_copy_word_count=_word_count(retry_copy),
                feature_bullets=validated.feature_bullets,
                raw_llm_output=retry_raw,
            )
            validated = validate_conversion(retry_result, variant_values=variant_terms)
            raw_output = retry_raw

    return ConversionResult(
        group_ref_id=validated.group_ref_id,
        product_name=validated.product_name,
        marketing_copy=validated.marketing_copy,
        marketing_copy_word_count=validated.marketing_copy_word_count,
        feature_bullets=validated.feature_bullets,
        status=validated.status,
        validation_errors=validated.validation_errors,
        raw_llm_output=raw_output,
        effective_variant_terms=all_variant_terms,
    )
