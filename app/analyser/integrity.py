"""SHA-256 integrity checking for original template files."""
import hashlib
import os
from pathlib import Path


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_directory(input_dir: str | Path) -> dict[str, str]:
    """Return {filename: sha256} for every .xlsx/.csv in input_dir."""
    result: dict[str, str] = {}
    for entry in sorted(Path(input_dir).iterdir()):
        if entry.name.startswith("~$"):
            continue
        if entry.suffix.lower() in (".xlsx", ".csv"):
            result[entry.name] = sha256_file(entry)
    return result


def verify_snapshot(before: dict[str, str], input_dir: str | Path) -> dict[str, str]:
    """
    Re-hash all files and return a dict of filename -> status.
    Status values: "unchanged", "modified", "missing", "new".
    """
    after = snapshot_directory(input_dir)
    results: dict[str, str] = {}
    for name, digest in before.items():
        if name not in after:
            results[name] = "missing"
        elif after[name] == digest:
            results[name] = "unchanged"
        else:
            results[name] = "modified"
    for name in after:
        if name not in before:
            results[name] = "new"
    return results
