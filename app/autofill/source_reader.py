"""
Read product data from CSV or JSON into a list of normalised dicts.

Each dict has lowercase-stripped keys (for alias matching) and original
string values.  No type coercion here — transformers handle that.
"""
from __future__ import annotations
import csv
import json
import re
from pathlib import Path


def _norm_key(k: str) -> str:
    """Normalise a source column name: lowercase, strip, collapse whitespace/punctuation."""
    k = k.strip().lower()
    k = re.sub(r"[\s\-/]+", "_", k)
    k = re.sub(r"[^\w]", "", k)
    return k


def read_source(path: str | Path) -> list[dict[str, str]]:
    """
    Return a list of product rows.  Keys are normalised; values are raw strings.
    Raises ValueError for unsupported formats.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".csv":
        return _read_csv(path)
    elif suffix == ".json":
        return _read_json(path)
    else:
        raise ValueError(f"Unsupported source format: {suffix!r}. Use .csv or .json")


def _read_csv(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw_row in reader:
            rows.append({_norm_key(k): (v.strip() if v else "") for k, v in raw_row.items()})
    return rows


def _read_json(path: Path) -> list[dict[str, str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError("JSON source must be an object or an array of objects")
    rows: list[dict[str, str]] = []
    for item in raw:
        rows.append({_norm_key(k): (str(v).strip() if v is not None else "") for k, v in item.items()})
    return rows
