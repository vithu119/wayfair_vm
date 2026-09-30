"""
Value transformations applied during field mapping.

All transforms receive and return a string (or return "" for empty/error).
"""
from __future__ import annotations
import re

_TRUTHY = {"yes", "true", "1", "y", "on", "x"}
_FALSY  = {"no",  "false", "0", "n", "off", ""}

# Amazon short code → Wayfair full name (case-insensitive key lookup)
_BULB_BASE_MAP: dict[str, str] = {
    "e5":    "E5/Midget",
    "e10":   "E10/Mini",
    "e11":   "E11/Mini Candelabra",
    "e12":   "E12/Candelabra",
    "e14":   "E14/Small",
    "e17":   "E17/Intermediate",
    "e26":   "E26/Medium (US Standard)",
    "e27":   "E27/Medium (Standard)",
    "e39":   "E39/Mogul",
    "e40":   "E40/Mogul",
    "b15":   "BA15d/Small Bayonet Cap",
    "ba15":  "BA15d/Small Bayonet Cap",
    "ba15d": "BA15d/Small Bayonet Cap",
    "b22":   "BA22d/Bayonet Cap",
    "ba22":  "BA22d/Bayonet Cap",
    "ba22d": "BA22d/Bayonet Cap",
    "g4":    "G4/Bi-pin",
    "gu4":   "GU4/Bi-pin",
    "gx4":   "GX4/Bi-pin",
    "g9":    "G9/Bi-pin",
    "gu10":  "GU10/Bi-pin",
    "g13":   "G13/Bi-pin",
    "g23":   "G23",
    "g53":   "G53",
    "gx53":  "GX53",
    "r7s":   "R7s",
    "rx7s":  "RX7s",
    "2g7":   "2G7",
    "2g11":  "2G11",
    "2gx13": "2GX13",
    "gu5.3": "GU5.3/Bi-pin",
    "gx5.3": "GX5.3/Bi-pin",
    "gy6.35":"GY6.35/Bi-pin",
    "gz6.35":"GZ6.35/Bi-pin",
    "g6.35": "G6.35/Bi-pin",
    "g8":    "G8/Bi-pin",
    "g8.5":  "G8.5/Bi-pin",
    "gz10":  "GZ10/Bi-pin",
    "gu24":  "GU24/Twist and Lock",
    "ba9s":  "BA9s/Miniature Bayonet",
    "wedge": "Wedge",
}


def apply(value: str, transform: str | None) -> tuple[str, str | None]:
    """
    Apply a named transform to value.
    Returns (transformed_value, error_message_or_None).
    """
    if not transform:
        return value.strip(), None

    directive = transform.strip().lower()

    if directive == "strip":
        return value.strip(), None

    if directive == "upper":
        return value.strip().upper(), None

    if directive == "lower":
        return value.strip().lower(), None

    if directive == "title_case":
        return value.strip().title(), None

    if directive.startswith("truncate:"):
        try:
            limit = int(directive.split(":")[1])
        except (IndexError, ValueError):
            return value.strip(), f"Invalid truncate directive: {transform!r}"
        v = value.strip()
        if len(v) > limit:
            return v[:limit], f"Truncated to {limit} chars (was {len(v)})"
        return v, None

    if directive == "number":
        return _to_number(value)

    if directive == "integer":
        return _to_integer(value)

    if directive == "yes_no":
        return _to_yes_no(value)

    if directive == "bulb_base":
        return _to_bulb_base(value)

    return value.strip(), f"Unknown transform: {transform!r}"


def _to_number(value: str) -> tuple[str, str | None]:
    v = value.strip()
    if not v:
        return "", None
    # Remove currency symbols, commas, spaces
    cleaned = re.sub(r"[£$€,\s]", "", v)
    try:
        n = float(cleaned)
        # Return as int if whole number, else float
        return str(int(n)) if n == int(n) else str(n), None
    except ValueError:
        return v, f"Could not convert {v!r} to a number"


def _to_integer(value: str) -> tuple[str, str | None]:
    v = value.strip()
    if not v:
        return "", None
    cleaned = re.sub(r"[£$€,\s]", "", v)
    try:
        return str(int(float(cleaned))), None
    except ValueError:
        return v, f"Could not convert {v!r} to an integer"


def _to_bulb_base(value: str) -> tuple[str, str | None]:
    v = value.strip()
    mapped = _BULB_BASE_MAP.get(v.lower())
    return (mapped, None) if mapped else (v, None)


def _to_yes_no(value: str) -> tuple[str, str | None]:
    v = value.strip().lower()
    if v in _TRUTHY:
        return "Yes", None
    if v in _FALSY or not v:
        return "No", None
    # Partial match
    if v.startswith("y"):
        return "Yes", None
    if v.startswith("n"):
        return "No", None
    return value.strip(), f"Could not convert {value!r} to Yes/No"
