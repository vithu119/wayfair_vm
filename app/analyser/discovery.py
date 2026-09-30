"""Discover all supported template files in a directory."""
from __future__ import annotations
from pathlib import Path

SUPPORTED_EXTENSIONS = {".xlsx", ".csv"}


def discover_templates(input_dir: str | Path) -> list[Path]:
    """Return sorted list of supported template paths, ignoring ~$ temp files."""
    base = Path(input_dir)
    results: list[Path] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_file():
            continue
        if entry.name.startswith("~$"):
            continue
        if entry.suffix.lower() in SUPPORTED_EXTENSIONS:
            results.append(entry)
    return results
