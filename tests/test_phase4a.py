"""
Phase 4A tests — dynamic template analysis, purpose classification,
fill status determination, template registry, and registration workflow.
"""
from __future__ import annotations
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

import openpyxl
import pytest

from app.analyser.findings import (
    Finding,
    has_blocking,
    has_review_required,
    blocking_messages,
    warning_messages,
    blocking_findings,
)
from app.analyser.purpose_classifier import classify_purpose, PurposeClassification
from app.analyser.fill_status import determine_fill_status, HEADER_CONFIDENCE_THRESHOLD
from app.analyser.template_registry import (
    TemplateRegistry, RegistryEntry, make_template_id,
)
from app.analyser.registration_workflow import register_workbook, register_bulk, RegistrationResult
from app.autofill.row_detector import classify_data_area


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_finding(severity: str, code: str = "TEST") -> Finding:
    return Finding(severity=severity, code=code, message="test finding")


def _make_sheet_classification(sheet_type: str = "listing", confidence: float = 0.9,
                                sheet_name: str = "Sheet1", is_hidden: bool = False):
    from app.analyser.sheet_classifier import SheetClassification
    return SheetClassification(
        sheet_name=sheet_name,
        sheet_type=sheet_type,
        confidence=confidence,
        is_hidden=is_hidden,
        reasons=[],
    )


def _make_header_detection(header_row: int = 4, confidence: float = 0.85):
    from app.analyser.header_detector import HeaderDetectionResult
    return HeaderDetectionResult(
        header_row=header_row,
        headers=["Supplier Part Number", "Product Name", "Description",
                 "Color", "Price", "Weight", "Material"],
        method="core_keys",
        confidence=confidence,
        warnings=[],
        internal_key_row=1,
        group_row=2,
        required_row=3,
        instructions_row=5,
        data_type_row=6,
        default_row=7,
    )


def _make_column_meta(header: str, position: int = 1):
    from app.analyser.column_metadata import ColumnMeta
    return ColumnMeta(
        original_header=header,
        normalized_header=header.lower().replace(" ", "_"),
        sheet_name="Product Listing",
        column_position=position,
        internal_key=f"core::{header.lower()}",
        group="",
        required_status="required",
        instructions="",
        data_type="Text",
        default_value="",
        char_limit=None,
        unit_required=False,
        is_controlled=False,
        valid_values=[],
        has_formula=False,
        is_duplicate_header=False,
        mapping_status="mapped",
    )


@dataclass
class _FakeSheetProfile:
    name: str
    classification: object
    max_row: int = 7
    max_col: int = 10
    detection: object = None
    columns: list = field(default_factory=list)
    valid_value_tables: list = field(default_factory=list)
    has_merged_cells: bool = False
    has_formulas: bool = False
    has_data_validation: bool = False
    frozen_pane: object = None


@dataclass
class _FakeProfile:
    source_file: str = "test_template.xlsx"
    category_name: str = "Test Category"
    file_hash: str = "abc123"
    analysis_timestamp: str = "2026-07-15T00:00:00+00:00"
    analysis_status: str = "ok"
    sheets: list = field(default_factory=list)
    listing_sheet: object = None
    valid_value_sheets: list = field(default_factory=list)
    image_sheets: list = field(default_factory=list)
    document_sheets: list = field(default_factory=list)
    instruction_sheets: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    template_purpose: str = "requires_review"
    template_purpose_confidence: float = 0.0
    template_purpose_reasons: list = field(default_factory=list)
    template_fill_status: str = "requires_review"
    category_resolution_status: str = "unknown"
    blocking_reasons: list = field(default_factory=list)
    safe_write_start_row: object = None
    row_classification_summary: dict = field(default_factory=dict)


def _make_good_listing_sheet(max_row: int = 7) -> _FakeSheetProfile:
    headers = ["Supplier Part Number", "Product Name", "Description",
               "Color", "Price", "Weight", "Material"]
    cols = [_make_column_meta(h, i + 1) for i, h in enumerate(headers)]
    det = _make_header_detection(header_row=4, confidence=0.90)
    cls = _make_sheet_classification("listing", 0.9, "6085 - Chandeliers")
    sp = _FakeSheetProfile(
        name="6085 - Chandeliers",
        classification=cls,
        max_row=max_row,
        max_col=len(headers),
        detection=det,
        columns=cols,
    )
    return sp


def _make_good_profile(max_row: int = 7) -> _FakeProfile:
    ls = _make_good_listing_sheet(max_row=max_row)
    p = _FakeProfile(
        source_file="6085 - Chandeliers.xlsx",
        category_name="6085 - Chandeliers",
    )
    p.listing_sheet = ls
    p.sheets = [ls]
    return p


def _make_registry_entry(**kwargs) -> RegistryEntry:
    defaults = dict(
        template_id="tpl_abc123def456",
        filename="test.xlsx",
        file_hash="abc123def456abc123def456abc123def456abc123def456abc123def456abc1",
        category="Test",
        category_status="provisional",
        template_purpose="fillable_template",
        template_purpose_confidence=0.85,
        fill_status="fillable",
        listing_sheet="Sheet1",
        header_row=4,
        safe_write_start_row=8,
        profile_path="outputs/template_profiles/Test.json",
        analysis_timestamp="2026-07-15T00:00:00+00:00",
        registration_timestamp="2026-07-15T00:00:00+00:00",
        warnings=[],
        blocking_reasons=[],
    )
    defaults.update(kwargs)
    return RegistryEntry(**defaults)


# ─── Finding Tests ─────────────────────────────────────────────────────────────

class TestFindings:
    def test_blocking_detection(self):
        findings = [
            _make_finding("info"),
            _make_finding("warning"),
            _make_finding("blocking"),
        ]
        assert has_blocking(findings) is True

    def test_no_blocking_when_only_warnings(self):
        findings = [_make_finding("info"), _make_finding("warning")]
        assert has_blocking(findings) is False

    def test_review_required_detection(self):
        findings = [_make_finding("review_required")]
        assert has_review_required(findings) is True

    def test_blocking_also_counts_as_review_required(self):
        findings = [_make_finding("blocking")]
        assert has_review_required(findings) is True

    def test_blocking_messages_filtered(self):
        findings = [
            _make_finding("blocking", "BLOCK_A"),
            _make_finding("warning", "WARN_A"),
            _make_finding("blocking", "BLOCK_B"),
        ]
        msgs = blocking_messages(findings)
        assert len(msgs) == 2

    def test_warning_messages_filtered(self):
        findings = [
            _make_finding("warning", "WARN_A"),
            _make_finding("blocking", "BLOCK_A"),
            _make_finding("warning", "WARN_B"),
        ]
        msgs = warning_messages(findings)
        assert len(msgs) == 2

    def test_finding_to_dict(self):
        f = Finding(severity="blocking", code="NO_LISTING", message="msg",
                    detail="extra", sheet="Sheet1", row=4)
        d = f.to_dict()
        assert d["severity"] == "blocking"
        assert d["code"] == "NO_LISTING"
        assert d["sheet"] == "Sheet1"
        assert d["row"] == 4

    def test_empty_findings_not_blocking(self):
        assert has_blocking([]) is False
        assert has_review_required([]) is False


# ─── Purpose Classifier Tests ─────────────────────────────────────────────────

class TestPurposeClassifier:
    def test_standard_blank_template_classified_as_fillable(self):
        profile = _make_good_profile(max_row=7)
        row_summary = {
            "existing_product_count": 0,
            "sample_count": 1,
            "metadata_row_count": 1,
            "template_control_count": 1,
            "blank_count": 0,
        }
        result = classify_purpose(profile, row_summary)
        assert result.purpose == "fillable_template"
        assert result.confidence >= 0.45

    def test_populated_sheet_reasons_mention_data_density(self):
        profile = _make_good_profile(max_row=1003)
        row_summary = {
            "existing_product_count": 1000,
            "sample_count": 0,
            "metadata_row_count": 0,
            "template_control_count": 0,
            "blank_count": 0,
        }
        result = classify_purpose(profile, row_summary)
        # Classifier must at minimum flag substantial data in reasons
        has_data_mention = any(
            "existing" in r.lower() or "substantial" in r.lower() or "rows below" in r.lower()
            for r in result.reasons
        )
        assert has_data_mention, f"Expected data-density signal in reasons: {result.reasons}"

    def test_low_confidence_listing_with_many_products_is_reference(self):
        """Weak listing structure + many products → reference_workbook."""
        profile = _make_good_profile(max_row=1003)
        # Weaken listing and header confidence below thresholds
        profile.listing_sheet.classification = _make_sheet_classification(
            "listing", 0.40, "Product Listing"  # below 0.5 threshold
        )
        profile.listing_sheet.detection = _make_header_detection(confidence=0.35)
        row_summary = {
            "existing_product_count": 1000,
            "sample_count": 0,
            "metadata_row_count": 0,
            "template_control_count": 0,
            "blank_count": 0,
        }
        result = classify_purpose(profile, row_summary)
        assert result.purpose == "reference_workbook"

    def test_no_listing_sheet_classified_as_unsupported(self):
        profile = _FakeProfile()
        profile.listing_sheet = None
        profile.sheets = []
        result = classify_purpose(profile)
        assert result.purpose == "unsupported"
        assert has_blocking(result.findings)

    def test_no_listing_with_instruction_sheets_classified_as_instruction_workbook(self):
        profile = _FakeProfile()
        profile.listing_sheet = None
        inst_cls = _make_sheet_classification("instruction", 0.8, "How to Use")
        inst_sheet = _FakeSheetProfile(name="How to Use", classification=inst_cls)
        profile.sheets = [inst_sheet]
        profile.instruction_sheets = [inst_sheet]
        result = classify_purpose(profile)
        assert result.purpose == "instruction_workbook"

    def test_category_resolution_from_numeric_sheet_name(self):
        profile = _make_good_profile()
        result = classify_purpose(profile)
        assert result.category_resolution_status == "resolved"

    def test_provisional_category_from_filename(self):
        profile = _make_good_profile()
        profile.listing_sheet.name = "Product Listing"
        profile.listing_sheet.classification = _make_sheet_classification(
            "listing", 0.9, "Product Listing"
        )
        profile.category_name = "MyCategory"
        result = classify_purpose(profile)
        assert result.category_resolution_status in ("provisional", "unknown")

    def test_blank_template_has_low_data_density(self):
        profile = _make_good_profile(max_row=7)
        result = classify_purpose(profile)
        # rows_below_header = 7 - 4 = 3, well below 30
        assert any("blank" in r.lower() or "template" in r.lower() for r in result.reasons)

    def test_purpose_without_row_summary(self):
        profile = _make_good_profile(max_row=7)
        result = classify_purpose(profile)
        # Should still classify without row_summary
        assert result.purpose in ("fillable_template", "requires_review")


# ─── Fill Status Tests ─────────────────────────────────────────────────────────

class TestFillStatus:
    def test_good_template_is_fillable(self):
        profile = _make_good_profile()
        pc = PurposeClassification(
            purpose="fillable_template",
            confidence=0.90,
            reasons=["test"],
            findings=[],
            category_resolution_status="resolved",
        )
        status, findings = determine_fill_status(profile, pc)
        assert status in ("fillable", "fillable_with_warnings")

    def test_reference_workbook_is_not_fillable(self):
        profile = _make_good_profile(max_row=1003)
        pc = PurposeClassification(
            purpose="reference_workbook",
            confidence=0.85,
            reasons=[],
            findings=[Finding(severity="blocking", code="REFERENCE_WORKBOOK", message="ref")],
            category_resolution_status="provisional",
        )
        status, findings = determine_fill_status(profile, pc)
        assert status == "not_fillable"

    def test_no_listing_sheet_is_not_fillable(self):
        profile = _FakeProfile()
        profile.listing_sheet = None
        pc = PurposeClassification(
            purpose="fillable_template",
            confidence=0.5,
            reasons=[],
            findings=[],
            category_resolution_status="unknown",
        )
        status, findings = determine_fill_status(profile, pc)
        assert status == "not_fillable"
        assert has_blocking(findings)

    def test_low_header_confidence_is_not_fillable(self):
        profile = _make_good_profile()
        profile.listing_sheet.detection = _make_header_detection(
            confidence=HEADER_CONFIDENCE_THRESHOLD - 0.05
        )
        pc = PurposeClassification(
            purpose="fillable_template",
            confidence=0.70,
            reasons=[],
            findings=[],
            category_resolution_status="provisional",
        )
        status, findings = determine_fill_status(profile, pc)
        assert status == "not_fillable"

    def test_header_confidence_exactly_at_threshold_is_fillable(self):
        profile = _make_good_profile()
        profile.listing_sheet.detection = _make_header_detection(
            confidence=HEADER_CONFIDENCE_THRESHOLD
        )
        pc = PurposeClassification(
            purpose="fillable_template",
            confidence=0.70,
            reasons=[],
            findings=[],
            category_resolution_status="resolved",
        )
        status, findings = determine_fill_status(profile, pc)
        # At exactly threshold, should NOT be blocked for low confidence
        blocking_codes = [f.code for f in findings if f.severity == "blocking"]
        assert "LOW_HEADER_CONFIDENCE" not in blocking_codes

    def test_mixed_workbook_requires_review(self):
        profile = _make_good_profile()
        pc = PurposeClassification(
            purpose="mixed_workbook",
            confidence=0.60,
            reasons=[],
            findings=[Finding(severity="review_required", code="MIXED_WORKBOOK", message="mixed")],
            category_resolution_status="provisional",
        )
        status, findings = determine_fill_status(profile, pc)
        assert status == "requires_review"

    def test_partial_analysis_does_not_block(self):
        profile = _make_good_profile()
        profile.analysis_status = "partial"
        pc = PurposeClassification(
            purpose="fillable_template",
            confidence=0.85,
            reasons=[],
            findings=[],
            category_resolution_status="resolved",
        )
        status, findings = determine_fill_status(profile, pc)
        # partial analysis_status must not become blocking
        assert status in ("fillable", "fillable_with_warnings")
        blocking_codes = [f.code for f in findings if f.severity == "blocking"]
        assert not blocking_codes

    def test_provisional_category_yields_warning(self):
        profile = _make_good_profile()
        profile.category_resolution_status = "provisional"
        pc = PurposeClassification(
            purpose="fillable_template",
            confidence=0.85,
            reasons=[],
            findings=[],
            category_resolution_status="provisional",
        )
        status, findings = determine_fill_status(profile, pc)
        warn_codes = [f.code for f in findings if f.severity == "warning"]
        assert "PROVISIONAL_CATEGORY" in warn_codes

    def test_duplicate_headers_are_blocking(self):
        profile = _make_good_profile()
        # Add duplicate header
        profile.listing_sheet.columns.append(
            _make_column_meta("Product Name", 2)
        )
        pc = PurposeClassification(
            purpose="fillable_template",
            confidence=0.85,
            reasons=[],
            findings=[],
            category_resolution_status="resolved",
        )
        status, findings = determine_fill_status(profile, pc)
        assert status == "not_fillable"
        codes = [f.code for f in findings if f.severity == "blocking"]
        assert "DUPLICATE_HEADERS" in codes


# ─── Template Registry Tests ──────────────────────────────────────────────────

class TestTemplateRegistry:
    def test_make_template_id(self):
        h = "abcdef123456789abcdef"
        tid = make_template_id(h)
        assert tid == "tpl_abcdef123456"

    def test_register_single_entry(self):
        reg = TemplateRegistry()
        e = _make_registry_entry()
        reg.register(e)
        assert len(reg.get_active()) == 1

    def test_idempotent_same_hash(self):
        reg = TemplateRegistry()
        e = _make_registry_entry()
        reg.register(e)
        reg.register(e)
        assert len(reg.entries) == 1

    def test_supersede_on_new_hash_same_filename(self):
        reg = TemplateRegistry()
        e1 = _make_registry_entry(file_hash="hash1" + "a" * 60, template_id="tpl_hash1")
        e2 = _make_registry_entry(file_hash="hash2" + "b" * 60, template_id="tpl_hash2",
                                   filename="test.xlsx")
        reg.register(e1)
        reg.register(e2)
        assert len(reg.entries) == 2
        old = reg.find_by_id("tpl_hash1")
        assert old.is_superseded is True
        assert old.is_active is False
        active = reg.get_active()
        assert len(active) == 1
        assert active[0].template_id == "tpl_hash2"

    def test_find_by_hash(self):
        reg = TemplateRegistry()
        e = _make_registry_entry(file_hash="findme" + "x" * 58)
        reg.register(e)
        found = reg.find_by_hash("findme" + "x" * 58)
        assert found is not None
        assert found.template_id == e.template_id

    def test_find_by_id(self):
        reg = TemplateRegistry()
        e = _make_registry_entry(template_id="tpl_uniqueid12")
        reg.register(e)
        found = reg.find_by_id("tpl_uniqueid12")
        assert found is not None

    def test_get_fillable(self):
        reg = TemplateRegistry()
        reg.register(_make_registry_entry(template_id="tpl_f1", fill_status="fillable",
                                          file_hash="f1" + "a" * 62))
        reg.register(_make_registry_entry(template_id="tpl_f2", fill_status="fillable_with_warnings",
                                          file_hash="f2" + "b" * 62, filename="other.xlsx"))
        reg.register(_make_registry_entry(template_id="tpl_f3", fill_status="not_fillable",
                                          file_hash="f3" + "c" * 62, filename="third.xlsx"))
        fillable = reg.get_fillable()
        assert len(fillable) == 2
        statuses = {e.fill_status for e in fillable}
        assert statuses == {"fillable", "fillable_with_warnings"}

    def test_summary(self):
        reg = TemplateRegistry()
        reg.register(_make_registry_entry(template_id="tpl_a1", fill_status="fillable",
                                          file_hash="a1" + "x" * 62))
        reg.register(_make_registry_entry(template_id="tpl_a2", fill_status="not_fillable",
                                          file_hash="a2" + "y" * 62, filename="other.xlsx"))
        s = reg.summary()
        assert s["total_registered"] == 2
        assert s["fillable"] == 1
        assert s["not_fillable"] == 1

    def test_persist_and_reload(self, tmp_path):
        reg = TemplateRegistry()
        e = _make_registry_entry()
        reg.register(e)
        json_path = tmp_path / "registry.json"
        csv_path = tmp_path / "registry.csv"
        reg.save(json_path, csv_path)

        reg2 = TemplateRegistry.load(json_path)
        assert len(reg2.entries) == 1
        loaded = reg2.entries[0]
        assert loaded.template_id == e.template_id
        assert loaded.fill_status == e.fill_status

    def test_load_nonexistent_file_returns_empty(self, tmp_path):
        reg = TemplateRegistry.load(tmp_path / "nonexistent.json")
        assert len(reg.entries) == 0

    def test_csv_written_on_save(self, tmp_path):
        reg = TemplateRegistry()
        reg.register(_make_registry_entry())
        json_path = tmp_path / "registry.json"
        csv_path = tmp_path / "registry.csv"
        reg.save(json_path, csv_path)
        assert csv_path.exists()
        content = csv_path.read_text(encoding="utf-8")
        assert "template_id" in content


# ─── Row Detector Phase 4A Classifications ────────────────────────────────────

class TestRowDetectorPhase4A:
    def _make_ws(self, headers: list[str], rows: list[list]):
        wb = openpyxl.Workbook()
        ws = wb.active
        for c, h in enumerate(headers, 1):
            ws.cell(1, c).value = h
        for r_idx, row_data in enumerate(rows, 2):
            for c, v in enumerate(row_data, 1):
                ws.cell(r_idx, c).value = v
        return ws, {h: i + 1 for i, h in enumerate(headers)}

    def test_metadata_row_data_type_keywords(self):
        ws, col_map = self._make_ws(
            ["Supplier Part Number", "Product Name"],
            [["Text", "Select"]],
        )
        results = classify_data_area(ws, header_row=1, col_map=col_map)
        assert results[0].status == "metadata"

    def test_required_row_is_template_control(self):
        ws, col_map = self._make_ws(
            ["Supplier Part Number", "Product Name"],
            [["Required", "Optional"]],
        )
        results = classify_data_area(ws, header_row=1, col_map=col_map)
        assert results[0].status == "template_control_row"

    def test_default_row_marker_is_template_control(self):
        ws, col_map = self._make_ws(
            ["Supplier Part Number", "Product Name"],
            [["Default Row:", "N/A"]],
        )
        results = classify_data_area(ws, header_row=1, col_map=col_map)
        assert results[0].status == "template_control_row"

    def test_real_product_is_existing_product(self):
        ws, col_map = self._make_ws(
            ["Supplier Part Number", "Product Name"],
            [["SKU-12345", "My Product"]],
        )
        results = classify_data_area(ws, header_row=1, col_map=col_map)
        assert results[0].status == "existing_product"

    def test_blank_row_is_blank(self):
        ws, col_map = self._make_ws(
            ["Supplier Part Number", "Product Name"],
            [["", ""]],
        )
        results = classify_data_area(ws, header_row=1, col_map=col_map)
        assert results[0].status == "blank"

    def test_na_values_are_sample_candidate(self):
        ws, col_map = self._make_ws(
            ["Supplier Part Number", "Product Name"],
            [["N/A", "N/A"]],
        )
        results = classify_data_area(ws, header_row=1, col_map=col_map)
        assert results[0].status == "sample_candidate"


# ─── Registration Workflow Tests ───────────────────────────────────────────────

class TestRegistrationWorkflow:
    def _make_real_template_wb(self, tmp_path: Path, filename: str = "test_template.xlsx",
                                rows: int = 7) -> Path:
        """Create a realistic Wayfair-style template workbook."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Product Listing"

        # Row 1: core:: keys
        ws.cell(1, 1).value = "core::supplier_part_number"
        ws.cell(1, 2).value = "core::product_name"
        ws.cell(1, 3).value = "core::description"
        # Row 2: groups
        ws.cell(2, 1).value = "General"
        ws.cell(2, 2).value = "General"
        ws.cell(2, 3).value = "General"
        # Row 3: required status
        ws.cell(3, 1).value = "Required"
        ws.cell(3, 2).value = "Required"
        ws.cell(3, 3).value = "Optional"
        # Row 4: headers
        ws.cell(4, 1).value = "Supplier Part Number"
        ws.cell(4, 2).value = "Product Name"
        ws.cell(4, 3).value = "Description"
        # Row 5: instructions
        ws.cell(5, 1).value = "Enter your part number"
        ws.cell(5, 2).value = "Enter product name"
        ws.cell(5, 3).value = "Enter description"
        # Row 6: data types
        ws.cell(6, 1).value = "Text"
        ws.cell(6, 2).value = "Text"
        ws.cell(6, 3).value = "Text"
        # Row 7: default row (blank template ends here)
        ws.cell(7, 1).value = "Default Row:"
        ws.cell(7, 2).value = "N/A"
        ws.cell(7, 3).value = "N/A"

        path = tmp_path / filename
        wb.save(str(path))
        return path

    def test_register_single_blank_template(self, tmp_path):
        template_path = self._make_real_template_wb(tmp_path)
        profile_dir = tmp_path / "profiles"
        registry = TemplateRegistry()

        result = register_workbook(template_path, profile_dir, registry)

        assert result.error is None
        assert result.template_id.startswith("tpl_")
        assert result.fill_status in (
            "fillable", "fillable_with_warnings", "requires_review"
        )
        assert profile_dir.exists()

    def test_idempotent_registration_same_hash(self, tmp_path):
        template_path = self._make_real_template_wb(tmp_path)
        profile_dir = tmp_path / "profiles"
        registry = TemplateRegistry()

        r1 = register_workbook(template_path, profile_dir, registry)
        r2 = register_workbook(template_path, profile_dir, registry)

        assert r1.template_id == r2.template_id
        assert len(registry.entries) == 1

    def test_register_nonexistent_file_returns_error(self, tmp_path):
        fake_path = tmp_path / "nonexistent.xlsx"
        registry = TemplateRegistry()
        result = register_workbook(fake_path, tmp_path / "profiles", registry)
        assert result.error is not None
        assert result.fill_status == "not_fillable"

    def test_register_bulk_processes_all(self, tmp_path):
        t1 = self._make_real_template_wb(tmp_path, "template_a.xlsx")
        t2 = self._make_real_template_wb(tmp_path, "template_b.xlsx")
        profile_dir = tmp_path / "profiles"
        registry_dir = tmp_path / "registry"

        results, registry = register_bulk([t1, t2], profile_dir, registry_dir)

        assert len(results) == 2
        assert all(r.error is None for r in results)
        assert (registry_dir / "template_registry.json").exists()

    def test_bulk_one_failure_does_not_stop_batch(self, tmp_path):
        t1 = self._make_real_template_wb(tmp_path, "template_good.xlsx")
        t_bad = tmp_path / "nonexistent.xlsx"
        profile_dir = tmp_path / "profiles"
        registry_dir = tmp_path / "registry"

        results, registry = register_bulk([t1, t_bad], profile_dir, registry_dir)

        assert len(results) == 2
        good = next(r for r in results if r.filename == "template_good.xlsx")
        bad = next(r for r in results if r.filename == "nonexistent.xlsx")
        assert good.error is None
        assert bad.error is not None

    def test_register_bulk_skips_unsupported_extension(self, tmp_path):
        bad = tmp_path / "document.docx"
        bad.write_text("not an excel file")
        profile_dir = tmp_path / "profiles"
        registry_dir = tmp_path / "registry"

        results, _ = register_bulk([bad], profile_dir, registry_dir)

        assert len(results) == 1
        assert results[0].fill_status == "not_fillable"
        assert "unsupported" in (results[0].error or "").lower()

    def test_profile_json_written(self, tmp_path):
        template_path = self._make_real_template_wb(tmp_path)
        profile_dir = tmp_path / "profiles"
        registry = TemplateRegistry()

        register_workbook(template_path, profile_dir, registry)

        profiles = list(profile_dir.glob("*.json"))
        assert len(profiles) == 1

    def test_profile_json_contains_phase4a_fields(self, tmp_path):
        template_path = self._make_real_template_wb(tmp_path)
        profile_dir = tmp_path / "profiles"
        registry = TemplateRegistry()

        register_workbook(template_path, profile_dir, registry)

        profiles = list(profile_dir.glob("*.json"))
        data = json.loads(profiles[0].read_text(encoding="utf-8"))
        assert "template_purpose" in data
        assert "template_fill_status" in data
        assert "category_resolution_status" in data
        assert "blocking_reasons" in data
        assert "safe_write_start_row" in data
        assert "row_classification_summary" in data

    def test_registry_saved_after_bulk(self, tmp_path):
        t = self._make_real_template_wb(tmp_path)
        registry_dir = tmp_path / "registry"
        register_bulk([t], tmp_path / "profiles", registry_dir)
        assert (registry_dir / "template_registry.json").exists()
        assert (registry_dir / "template_registry.csv").exists()

    def test_safe_write_start_row_populated(self, tmp_path):
        template_path = self._make_real_template_wb(tmp_path)
        profile_dir = tmp_path / "profiles"
        registry = TemplateRegistry()

        result = register_workbook(template_path, profile_dir, registry)

        assert result.safe_write_start_row is not None
        assert result.safe_write_start_row >= 5  # must be after header and metadata rows
