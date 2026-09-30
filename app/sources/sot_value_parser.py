from __future__ import annotations
import re
from app.sources.sot_models import ParsedSotValue

_MEASUREMENT_RE = re.compile(r'^([\d.]+)\s*(mm|cm|m|g|kg|lb|oz|w|v|hz|a|min|°c|°f)$', re.IGNORECASE)
_RANGE_RE = re.compile(r'^([\d.]+)\s*[-–]\s*([\d.]+)\s*(mm|cm|m|g|kg|lb|oz|w|v|hz|a|min)?$', re.IGNORECASE)
_HEX_RE = re.compile(r'^#[0-9a-fA-F]{3,8}$')
_IP_RE = re.compile(r'^IP\d{2}$', re.IGNORECASE)
_BOOL_TRUE = {"yes", "true", "1", "y"}
_BOOL_FALSE = {"no", "false", "0", "n", "none"}

def parse_sot_value(raw: str) -> ParsedSotValue:
    if not raw or not raw.strip():
        return ParsedSotValue(raw_value=raw, parsed_value=raw, value_type="unknown")

    stripped = raw.strip()

    # Hex colour
    if _HEX_RE.match(stripped):
        return ParsedSotValue(raw_value=raw, parsed_value=stripped, value_type="colour_hex")

    # IP rating
    if _IP_RE.match(stripped):
        return ParsedSotValue(raw_value=raw, parsed_value=stripped.upper(), value_type="ip_rating")

    # Boolean
    lower = stripped.lower()
    if lower in _BOOL_TRUE:
        return ParsedSotValue(raw_value=raw, parsed_value=True, value_type="boolean")
    if lower in _BOOL_FALSE:
        return ParsedSotValue(raw_value=raw, parsed_value=False, value_type="boolean")

    # Range like "5-8mm"
    m = _RANGE_RE.match(stripped)
    if m:
        lo, hi, unit = float(m.group(1)), float(m.group(2)), (m.group(3) or "").lower()
        return ParsedSotValue(raw_value=raw, parsed_value=stripped, value_type="measurement_range",
                              unit=unit or None, range_min=lo, range_max=hi)

    # Measurement like "25mm", "5Kg"
    m = _MEASUREMENT_RE.match(stripped)
    if m:
        num, unit = float(m.group(1)), m.group(2).lower()
        return ParsedSotValue(raw_value=raw, parsed_value=num, value_type="measurement", unit=unit, numeric=num)

    # Numeric
    try:
        if "." in stripped:
            return ParsedSotValue(raw_value=raw, parsed_value=float(stripped), value_type="decimal", numeric=float(stripped))
        return ParsedSotValue(raw_value=raw, parsed_value=int(stripped), value_type="integer", numeric=float(stripped))
    except ValueError:
        pass

    # Comma-separated list
    if "," in stripped:
        return ParsedSotValue(raw_value=raw, parsed_value=[x.strip() for x in stripped.split(",")], value_type="list")

    return ParsedSotValue(raw_value=raw, parsed_value=stripped, value_type="text")


def convert_unit(parsed: ParsedSotValue, target_unit: str) -> ParsedSotValue:
    """Convert a measurement to target_unit. Returns new ParsedSotValue with warning on failure."""
    if parsed.value_type not in ("measurement",) or parsed.numeric is None:
        import dataclasses
        w = dataclasses.replace(parsed, warnings=list(parsed.warnings) + ["unit_conversion_failed: not a measurement"])
        return w

    src = (parsed.unit or "").lower()
    tgt = target_unit.lower()

    conversions = {
        ("mm", "cm"): 0.1, ("mm", "m"): 0.001,
        ("cm", "mm"): 10, ("cm", "m"): 0.01,
        ("g", "kg"): 0.001, ("kg", "g"): 1000,
    }
    factor = conversions.get((src, tgt))
    if factor is None:
        import dataclasses
        w = dataclasses.replace(parsed, warnings=list(parsed.warnings) + [f"unit_mismatch: cannot convert {src} to {tgt}"])
        return w

    new_num = round(parsed.numeric * factor, 6)
    result = ParsedSotValue(raw_value=parsed.raw_value, parsed_value=new_num,
                            value_type="measurement", unit=tgt, numeric=new_num)
    return result
