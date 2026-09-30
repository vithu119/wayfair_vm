"""
Structured finding model for template analysis.

severity levels (ordered from least to most severe):
  info            - informational, no action required
  warning         - non-blocking; fill can proceed with awareness
  review_required - human confirmation recommended before filling
  blocking        - fill must NOT proceed until resolved
"""
from __future__ import annotations
from dataclasses import dataclass, field

SEVERITY_ORDER = ["info", "warning", "review_required", "blocking"]


@dataclass
class Finding:
    severity: str       # info | warning | review_required | blocking
    code: str           # machine-readable slug, e.g. NO_LISTING_SHEET
    message: str        # human-readable summary
    detail: str = ""    # extra context
    sheet: str | None = None
    row: int | None = None

    def is_blocking(self) -> bool:
        return self.severity == "blocking"

    def is_review_required(self) -> bool:
        return self.severity in ("blocking", "review_required")

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
            "sheet": self.sheet,
            "row": self.row,
        }


def has_blocking(findings: list[Finding]) -> bool:
    return any(f.is_blocking() for f in findings)


def has_review_required(findings: list[Finding]) -> bool:
    return any(f.is_review_required() for f in findings)


def blocking_findings(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.is_blocking()]


def warning_messages(findings: list[Finding]) -> list[str]:
    return [f.message for f in findings if f.severity == "warning"]


def blocking_messages(findings: list[Finding]) -> list[str]:
    return [f.message for f in findings if f.is_blocking()]
