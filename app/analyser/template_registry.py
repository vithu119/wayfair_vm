"""
Template registry — persistent store of every registered workbook.

Each registered entry describes one specific version (identified by SHA-256 hash)
of a workbook. Re-uploading the same file (same hash) does NOT create a duplicate.
Uploading a new version (different hash, same filename) creates a new entry and
marks the previous one as superseded.

Persisted as:
  outputs/template_registry/template_registry.json
  outputs/template_registry/template_registry.csv
"""
from __future__ import annotations
import csv
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class RegistryEntry:
    template_id: str                 # tpl_<first12_of_sha256>
    filename: str
    file_hash: str                   # SHA-256 hex
    category: str
    category_status: str             # resolved | provisional | unknown | requires_review
    template_purpose: str
    template_purpose_confidence: float
    fill_status: str                 # fillable | fillable_with_warnings | not_fillable | requires_review
    listing_sheet: str | None
    header_row: int | None
    safe_write_start_row: int | None
    profile_path: str                # relative path to JSON profile
    analysis_timestamp: str
    registration_timestamp: str
    is_active: bool = True
    is_superseded: bool = False
    warnings: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["warnings"] = " | ".join(self.warnings)
        d["blocking_reasons"] = " | ".join(self.blocking_reasons)
        return d


_CSV_FIELDS = [
    "template_id", "filename", "file_hash", "category", "category_status",
    "template_purpose", "template_purpose_confidence", "fill_status",
    "listing_sheet", "header_row", "safe_write_start_row",
    "profile_path", "analysis_timestamp", "registration_timestamp",
    "is_active", "is_superseded", "warnings", "blocking_reasons",
]


class TemplateRegistry:
    def __init__(self) -> None:
        self._entries: list[RegistryEntry] = []

    # ── Persistence ────────────────────────────────────────────────────────

    @classmethod
    def load(cls, json_path: Path) -> "TemplateRegistry":
        reg = cls()
        if json_path.exists():
            raw = json.loads(json_path.read_text(encoding="utf-8"))
            for item in raw.get("entries", []):
                # Coerce pipe-delimited string format (legacy) to lists
                for field in ("warnings", "blocking_reasons"):
                    val = item.get(field, [])
                    if isinstance(val, str):
                        item[field] = [v.strip() for v in val.split(" | ") if v.strip()] if val else []
                    else:
                        item.setdefault(field, [])
                item.setdefault("template_purpose_confidence", 0.0)
                item.setdefault("safe_write_start_row", None)
                item.setdefault("registration_timestamp", item.get("analysis_timestamp", ""))
                reg._entries.append(RegistryEntry(**item))
        return reg

    def save(self, json_path: Path, csv_path: Path | None = None) -> None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "entry_count": len(self._entries),
            "entries": [asdict(e) for e in self._entries],
        }
        json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        if csv_path is not None:
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            rows = [e.to_dict() for e in self._entries]
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
                writer.writeheader()
                writer.writerows(rows)

    # ── Registration ───────────────────────────────────────────────────────

    def register(self, entry: RegistryEntry) -> RegistryEntry:
        """
        Add entry to registry.
        - Same hash: return existing entry without duplication.
        - Different hash, same filename: supersede old active entry, add new.
        """
        # Exact duplicate by hash
        existing = self.find_by_hash(entry.file_hash)
        if existing is not None:
            return existing  # idempotent

        # Supersede previous active entries for the same filename
        for old in self._entries:
            if (old.filename == entry.filename
                    and old.is_active
                    and not old.is_superseded
                    and old.file_hash != entry.file_hash):
                old.is_active = False
                old.is_superseded = True

        self._entries.append(entry)
        return entry

    # ── Queries ────────────────────────────────────────────────────────────

    def find_by_hash(self, file_hash: str) -> RegistryEntry | None:
        return next((e for e in self._entries if e.file_hash == file_hash), None)

    def find_by_id(self, template_id: str) -> RegistryEntry | None:
        return next((e for e in self._entries if e.template_id == template_id), None)

    def get_active(self) -> list[RegistryEntry]:
        return [e for e in self._entries if e.is_active and not e.is_superseded]

    def get_fillable(self) -> list[RegistryEntry]:
        return [
            e for e in self.get_active()
            if e.fill_status in ("fillable", "fillable_with_warnings")
        ]

    def get_by_fill_status(self, status: str) -> list[RegistryEntry]:
        return [e for e in self.get_active() if e.fill_status == status]

    def summary(self) -> dict:
        active = self.get_active()
        return {
            "total_registered": len(self._entries),
            "active": len(active),
            "fillable": sum(1 for e in active if e.fill_status == "fillable"),
            "fillable_with_warnings": sum(1 for e in active if e.fill_status == "fillable_with_warnings"),
            "requires_review": sum(1 for e in active if e.fill_status == "requires_review"),
            "not_fillable": sum(1 for e in active if e.fill_status == "not_fillable"),
            "superseded": sum(1 for e in self._entries if e.is_superseded),
        }

    @property
    def entries(self) -> list[RegistryEntry]:
        return list(self._entries)


def make_template_id(file_hash: str) -> str:
    return f"tpl_{file_hash[:12]}"
