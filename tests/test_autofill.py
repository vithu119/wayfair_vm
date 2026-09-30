"""Unit tests for the auto-fill engine (Phase 2 + Phase 3)."""
from __future__ import annotations
import csv
import json
import shutil
import tempfile
from pathlib import Path

import openpyxl
import pytest

from tests.conftest import make_standard_wb, save_wb_to_temp
from app.autofill.source_reader import read_source, _norm_key
from app.autofill.transformer import apply as transform_value
from app.autofill.mapper import MappingRule, FixedValueRule, resolve_row
from app.autofill.validator import validate_row
from app.autofill.writer import write_filled_template
from app.autofill.write_policy import WritePlan, build_write_plan, VALID_POLICIES
from app.autofill.row_detector import classify_data_area, RowClassification
from app.analyser.integrity import snapshot_directory, verify_snapshot


# ── Helpers ──────────────────────────────────────────────────────────────────

def _mr(wayfair_field: str, final_value: str):
    from app.autofill.mapper import MappingResult
    return MappingResult(
        wayfair_field=wayfair_field,
        source_field=None,
        raw_value=final_value,
        final_value=final_value,
        transform_applied=None,
        transform_warning=None,
        source="source_data",
        is_required=False,
        is_empty=(final_value == ""),
    )


def _make_plan(target_rows: list[int], policy: str = "append") -> WritePlan:
    return WritePlan(
        policy=policy,
        target_rows=target_rows,
        first_write_row=target_rows[0] if target_rows else 1,
        existing_product_rows=[],
        sample_rows=[],
        blank_rows=target_rows,
    )


def _save_wb(wb, tmp_path, name="tpl.xlsx") -> Path:
    p = tmp_path / name
    wb.save(str(p))
    return p


# ── Source Reader ────────────────────────────────────────────────────────────

class TestSourceReader:
    def test_csv_keys_normalised(self, tmp_path):
        p = tmp_path / "test.csv"
        p.write_text("SKU,Product Name,Base Cost\nABC,Lamp,29.99\n", encoding="utf-8")
        rows = read_source(p)
        assert rows[0]["sku"] == "ABC"
        assert rows[0]["product_name"] == "Lamp"
        assert rows[0]["base_cost"] == "29.99"

    def test_csv_strips_whitespace(self, tmp_path):
        p = tmp_path / "test.csv"
        p.write_text("sku , brand\n  ABC  ,  ACME  \n", encoding="utf-8")
        rows = read_source(p)
        assert rows[0]["sku"] == "ABC"
        assert rows[0]["brand"] == "ACME"

    def test_json_object_wrapped_in_list(self, tmp_path):
        p = tmp_path / "test.json"
        p.write_text('{"sku": "XYZ", "brand": "Test"}', encoding="utf-8")
        rows = read_source(p)
        assert len(rows) == 1
        assert rows[0]["sku"] == "XYZ"

    def test_json_array(self, tmp_path):
        p = tmp_path / "test.json"
        p.write_text('[{"sku":"A"},{"sku":"B"}]', encoding="utf-8")
        rows = read_source(p)
        assert len(rows) == 2

    def test_unsupported_format_raises(self, tmp_path):
        p = tmp_path / "data.xlsx"
        p.write_bytes(b"fake")
        with pytest.raises(ValueError, match="Unsupported"):
            read_source(p)


# ── Transformer ──────────────────────────────────────────────────────────────

class TestTransformer:
    def test_truncate(self):
        val, warn = transform_value("A" * 600, "truncate:500")
        assert len(val) == 500
        assert warn is not None

    def test_truncate_short_no_warn(self):
        val, warn = transform_value("short", "truncate:500")
        assert val == "short"
        assert warn is None

    def test_number_strips_currency(self):
        assert transform_value("£29.99", "number")[0] == "29.99"
        assert transform_value("$1,299.00", "number")[0] == "1299"

    def test_integer_rounds(self):
        assert transform_value("3.7", "integer")[0] == "3"

    def test_yes_no_truthy(self):
        for v in ["yes", "Yes", "YES", "1", "true", "True", "y"]:
            assert transform_value(v, "yes_no")[0] == "Yes"

    def test_yes_no_falsy(self):
        for v in ["no", "No", "0", "false", "n", ""]:
            assert transform_value(v, "yes_no")[0] == "No"

    def test_none_transform_passthrough(self):
        val, warn = transform_value("hello", None)
        assert val == "hello"
        assert warn is None

    def test_unknown_transform_warns(self):
        val, warn = transform_value("x", "magic_transform")
        assert warn is not None
        assert "Unknown" in warn


# ── Mapper ───────────────────────────────────────────────────────────────────

def _make_rules(entries: list[dict]) -> list[MappingRule]:
    return [
        MappingRule(
            wayfair_field=e["wayfair_field"],
            aliases=e.get("aliases", []),
            categories=e.get("categories", ["all"]),
            transform=e.get("transform"),
            fixed_value=e.get("fixed_value"),
            default_value=e.get("default_value"),
            required=e.get("required", False),
            notes="",
        )
        for e in entries
    ]


class TestMapper:
    def test_alias_match(self):
        rules = _make_rules([{
            "wayfair_field": "Supplier Part Number",
            "aliases": ["sku", "part_number"],
            "required": True,
        }])
        results = resolve_row(
            {"sku": "ABC123"},
            rules, [], "Chandeliers",
            ["Supplier Part Number"],
        )
        assert results[0].final_value == "ABC123"
        assert results[0].source == "source_data"
        assert results[0].source_field == "sku"

    def test_first_alias_wins(self):
        rules = _make_rules([{
            "wayfair_field": "Supplier Part Number",
            "aliases": ["sku", "part_number"],
        }])
        results = resolve_row(
            {"sku": "FIRST", "part_number": "SECOND"},
            rules, [], "Chandeliers",
            ["Supplier Part Number"],
        )
        assert results[0].final_value == "FIRST"

    def test_default_value_used_when_source_empty(self):
        rules = _make_rules([{
            "wayfair_field": "Minimum Order Quantity",
            "aliases": ["moq"],
            "default_value": "1",
        }])
        results = resolve_row(
            {"moq": ""},
            rules, [], "Chandeliers",
            ["Minimum Order Quantity"],
        )
        assert results[0].final_value == "1"
        assert results[0].source == "default"

    def test_unmapped_field_is_empty(self):
        results = resolve_row(
            {"sku": "X"},
            [], [], "Chandeliers",
            ["Unknown Special Field"],
        )
        assert results[0].is_empty is True
        assert results[0].source == "unmapped"

    def test_fixed_value_overrides_source(self):
        rules = _make_rules([{
            "wayfair_field": "Brand",
            "aliases": ["brand"],
        }])
        fixed = [FixedValueRule(wayfair_field="Brand", value="LEDSone", categories=["all"])]
        results = resolve_row(
            {"brand": "Other Brand"},
            rules, fixed, "Chandeliers",
            ["Brand"],
        )
        assert results[0].final_value == "LEDSone"
        assert results[0].source == "fixed_value"

    def test_transform_applied(self):
        rules = _make_rules([{
            "wayfair_field": "Base Cost",
            "aliases": ["cost"],
            "transform": "number",
        }])
        results = resolve_row(
            {"cost": "£49.99"},
            rules, [], "Chandeliers",
            ["Base Cost"],
        )
        assert results[0].final_value == "49.99"

    def test_category_filter_respected(self):
        rules = _make_rules([{
            "wayfair_field": "Number of Lights",
            "aliases": ["num_lights"],
            "categories": ["Chandeliers"],
        }])
        results_match = resolve_row(
            {"num_lights": "5"},
            rules, [], "Chandeliers",
            ["Number of Lights"],
        )
        results_no_match = resolve_row(
            {"num_lights": "5"},
            rules, [], "Lampshades",
            ["Number of Lights"],
        )
        assert results_match[0].final_value == "5"
        assert results_no_match[0].is_empty is True


# ── Validator ─────────────────────────────────────────────────────────────────

class TestValidator:
    def _make_mr(self, wayfair_field, final_value, is_required=False, source="source_data"):
        from app.autofill.mapper import MappingResult
        return MappingResult(
            wayfair_field=wayfair_field,
            source_field=None,
            raw_value=final_value,
            final_value=final_value,
            transform_applied=None,
            transform_warning=None,
            source=source,
            is_required=is_required,
            is_empty=(final_value == ""),
        )

    def test_missing_required_is_error(self):
        mr = self._make_mr("Supplier Part Number", "", is_required=True)
        issues = validate_row([mr], 0, "ROW0", {}, {})
        assert any(i.issue_type == "missing_required" and i.severity == "error" for i in issues)

    def test_valid_value_passes(self):
        mr = self._make_mr("Finish", "Brushed Nickel")
        issues = validate_row([mr], 0, "SKU1", {"finish": ["Brushed Nickel", "Chrome"]}, {})
        bad = [i for i in issues if i.issue_type == "invalid_value"]
        assert not bad

    def test_invalid_value_is_warning(self):
        mr = self._make_mr("Finish", "PurpleHaze")
        issues = validate_row([mr], 0, "SKU1", {"finish": ["Brushed Nickel", "Chrome"]}, {})
        assert any(i.issue_type == "invalid_value" and i.severity == "warning" for i in issues)

    def test_char_limit_exceeded_is_warning(self):
        mr = self._make_mr("Product Name", "A" * 600)
        issues = validate_row([mr], 0, "SKU1", {}, {"product_name": 500})
        assert any(i.issue_type == "char_limit" for i in issues)


# ── Writer (updated — no first_data_row) ─────────────────────────────────────

class TestWriter:
    def test_writes_values_to_correct_cells(self, tmp_path):
        headers = ["Supplier Part Number", "Product Name", "Brand"]
        wb = make_standard_wb(headers)
        tpl = _save_wb(wb, tmp_path)

        mapped_rows = [[
            _mr("Supplier Part Number", "SKU-001"),
            _mr("Product Name", "Test Lamp"),
            _mr("Brand", "TestBrand"),
        ]]
        plan = _make_plan([8])

        result = write_filled_template(
            template_path=tpl,
            output_dir=tmp_path / "out",
            category_name="Test",
            listing_sheet_name="9999 - Test Category",
            header_row=4,
            write_plan=plan,
            max_col=3,
            mapped_rows=mapped_rows,
        )

        out_wb = openpyxl.load_workbook(str(result.output_path), data_only=True)
        ws = out_wb.active
        assert ws.cell(8, 1).value == "SKU-001"
        assert ws.cell(8, 2).value == "Test Lamp"
        assert ws.cell(8, 3).value == "TestBrand"
        out_wb.close()

    def test_original_template_unchanged(self, tmp_path):
        headers = ["Supplier Part Number", "Product Name"]
        wb = make_standard_wb(headers)
        tpl = _save_wb(wb, tmp_path)

        before = snapshot_directory(tmp_path)

        write_filled_template(
            template_path=tpl,
            output_dir=tmp_path / "out",
            category_name="Test",
            listing_sheet_name="9999 - Test Category",
            header_row=4,
            write_plan=_make_plan([8]),
            max_col=2,
            mapped_rows=[[_mr("Supplier Part Number", "SKU-001")]],
        )

        results = verify_snapshot(before, tmp_path)
        assert results["tpl.xlsx"] == "unchanged"

    def test_multiple_rows_written(self, tmp_path):
        headers = ["Supplier Part Number", "Product Name"]
        wb = make_standard_wb(headers)
        tpl = _save_wb(wb, tmp_path)

        mapped_rows = [[_mr("Supplier Part Number", f"SKU-{i:03d}")] for i in range(5)]
        plan = _make_plan([8, 9, 10, 11, 12])

        result = write_filled_template(
            template_path=tpl,
            output_dir=tmp_path / "out",
            category_name="Test",
            listing_sheet_name="9999 - Test Category",
            header_row=4,
            write_plan=plan,
            max_col=2,
            mapped_rows=mapped_rows,
        )

        assert result.rows_written == 5
        out_wb = openpyxl.load_workbook(str(result.output_path), data_only=True)
        ws = out_wb.active
        for i in range(5):
            assert ws.cell(8 + i, 1).value == f"SKU-{i:03d}"
        out_wb.close()

    def test_header_rows_preserved(self, tmp_path):
        headers = ["Supplier Part Number"]
        wb = make_standard_wb(headers)
        tpl = _save_wb(wb, tmp_path)

        write_filled_template(
            template_path=tpl,
            output_dir=tmp_path / "out",
            category_name="Test",
            listing_sheet_name="9999 - Test Category",
            header_row=4,
            write_plan=_make_plan([8]),
            max_col=1,
            mapped_rows=[[_mr("Supplier Part Number", "SKU-001")]],
        )

        out_path = next((tmp_path / "out").glob("*.xlsx"))
        out_wb = openpyxl.load_workbook(str(out_path), data_only=True)
        ws = out_wb.active
        assert ws.cell(4, 1).value == "Supplier Part Number"
        assert ws.cell(7, 1).value == "N/A"
        out_wb.close()

    def test_preview_only_writes_no_cells(self, tmp_path):
        headers = ["Supplier Part Number"]
        wb = make_standard_wb(headers)
        tpl = _save_wb(wb, tmp_path)

        plan = WritePlan(
            policy="preview-only",
            target_rows=[8],
            first_write_row=8,
            existing_product_rows=[],
            sample_rows=[],
            blank_rows=[8],
            is_preview=True,
        )

        result = write_filled_template(
            template_path=tpl,
            output_dir=tmp_path / "out",
            category_name="Test",
            listing_sheet_name="9999 - Test Category",
            header_row=4,
            write_plan=plan,
            max_col=1,
            mapped_rows=[[_mr("Supplier Part Number", "SKU-PREVIEW")]],
        )

        assert result.rows_written == 0
        out_wb = openpyxl.load_workbook(str(result.output_path), data_only=True)
        ws = out_wb.active
        # Row 8 must remain empty because preview-only must not write
        assert ws.cell(8, 1).value is None
        out_wb.close()

    def test_write_result_carries_write_plan(self, tmp_path):
        headers = ["Supplier Part Number"]
        wb = make_standard_wb(headers)
        tpl = _save_wb(wb, tmp_path)
        plan = _make_plan([8])

        result = write_filled_template(
            template_path=tpl,
            output_dir=tmp_path / "out",
            category_name="Test",
            listing_sheet_name="9999 - Test Category",
            header_row=4,
            write_plan=plan,
            max_col=1,
            mapped_rows=[[_mr("Supplier Part Number", "SKU-001")]],
        )

        assert result.write_plan is plan
        assert result.write_plan.policy == "append"


# ── Row Detector ─────────────────────────────────────────────────────────────

def _make_ws_with_rows(headers: list[str], data_rows: list[list]) -> tuple:
    """
    Returns (ws, col_map) where the workbook has:
      row 1: headers
      rows 2+: data_rows content
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    for c, h in enumerate(headers, 1):
        ws.cell(1, c).value = h
    for r_offset, row_vals in enumerate(data_rows):
        for c, v in enumerate(row_vals, 1):
            ws.cell(2 + r_offset, c).value = v
    col_map = {h: i + 1 for i, h in enumerate(headers)}
    return ws, col_map


class TestRowDetector:
    def test_blank_rows_classified_blank(self):
        ws, col_map = _make_ws_with_rows(
            ["Supplier Part Number", "Product Name"],
            [["", ""], ["", ""]],
        )
        results = classify_data_area(ws, header_row=1, col_map=col_map)
        assert all(rc.status == "blank" for rc in results)

    def test_real_sku_is_existing_product(self):
        ws, col_map = _make_ws_with_rows(
            ["Supplier Part Number", "Product Name"],
            [["REAL-SKU-001", "Crystal Chandelier"]],
        )
        results = classify_data_area(ws, header_row=1, col_map=col_map)
        assert results[0].status == "existing_product"
        assert "REAL-SKU-001" in str(results[0].existing_identifiers)

    def test_na_values_are_sample_candidate(self):
        ws, col_map = _make_ws_with_rows(
            ["Supplier Part Number", "Product Name"],
            [["N/A", "N/A"]],
        )
        results = classify_data_area(ws, header_row=1, col_map=col_map)
        assert results[0].status == "sample_candidate"

    def test_default_row_marker_is_instruction(self):
        ws, col_map = _make_ws_with_rows(
            ["Supplier Part Number", "Product Name"],
            [["Default Row:", "N/A"]],
        )
        results = classify_data_area(ws, header_row=1, col_map=col_map)
        assert results[0].status == "template_control_row"

    def test_artificial_sku_is_not_existing_product(self):
        # "SKU-001" style names are template placeholders, not real products
        ws, col_map = _make_ws_with_rows(
            ["Supplier Part Number", "Product Name"],
            [["SKU-001", "Sample Product"]],
        )
        results = classify_data_area(ws, header_row=1, col_map=col_map)
        # Should NOT be classified as existing_product
        assert results[0].status != "existing_product"

    def test_stops_after_consecutive_blanks(self):
        rows = [["", ""]] * 35  # more than MAX_CONSECUTIVE_BLANK (30)
        ws, col_map = _make_ws_with_rows(["Supplier Part Number", "Product Name"], rows)
        results = classify_data_area(ws, header_row=1, col_map=col_map)
        # Should stop before row 35 (after 30 consecutive blanks)
        assert len(results) <= 30

    def test_mixed_rows(self):
        ws, col_map = _make_ws_with_rows(
            ["Supplier Part Number", "Product Name"],
            [
                ["Default Row:", "N/A"],   # row 2 -> template_control_row
                ["N/A", "N/A"],            # row 3 -> sample_candidate
                ["", ""],                  # row 4 -> blank
                ["REAL-001", "Real Lamp"], # row 5 -> existing_product
                ["", ""],                  # row 6 -> blank
            ],
        )
        results = classify_data_area(ws, header_row=1, col_map=col_map)
        statuses = [rc.status for rc in results]
        assert statuses[0] == "template_control_row"
        assert statuses[1] == "sample_candidate"
        assert statuses[2] == "blank"
        assert statuses[3] == "existing_product"
        assert statuses[4] == "blank"

    def test_row_numbers_are_one_based(self):
        ws, col_map = _make_ws_with_rows(
            ["Supplier Part Number"],
            [["SKU-REAL-001"]],
        )
        results = classify_data_area(ws, header_row=1, col_map=col_map)
        # header is row 1, first data row is row 2
        assert results[0].row_number == 2

    def test_standard_wb_row7_is_instruction(self, tmp_path):
        # Use the make_standard_wb fixture to check the real standard format
        headers = ["Supplier Part Number", "Product Name"]
        wb = make_standard_wb(headers)
        tpl = _save_wb(wb, tmp_path)

        wb2 = openpyxl.load_workbook(str(tpl))
        ws = wb2.active
        col_map = {"Supplier Part Number": 1, "Product Name": 2}
        results = classify_data_area(ws, header_row=4, col_map=col_map)

        # First scanned row is row 5 (instruction), then 6 (type), then 7 (N/A)
        row7 = next(rc for rc in results if rc.row_number == 7)
        # Row 7 has "N/A" in all cells - should be sample_candidate or instruction
        assert row7.status in ("sample_candidate", "instruction_or_note")

        # Rows 8+ should be blank
        blank_rows = [rc for rc in results if rc.row_number >= 8]
        assert all(rc.status == "blank" for rc in blank_rows)
        wb2.close()


# ── Write Policy ─────────────────────────────────────────────────────────────

def _rc(row_number: int, status: str) -> RowClassification:
    return RowClassification(row_number=row_number, status=status, confidence=0.9)


class TestWritePolicy:
    def test_append_no_existing_uses_first_blank(self):
        classifications = [
            _rc(5, "instruction_or_note"),
            _rc(6, "sample_candidate"),
            _rc(7, "blank"),
            _rc(8, "blank"),
        ]
        plan = build_write_plan(classifications, "append", 2)
        assert plan.first_write_row == 7
        assert plan.target_rows == [7, 8]

    def test_append_with_existing_starts_after_last(self):
        classifications = [
            _rc(5, "existing_product"),
            _rc(6, "existing_product"),
            _rc(7, "blank"),
        ]
        plan = build_write_plan(classifications, "append", 2)
        assert plan.first_write_row == 7
        assert plan.target_rows == [7, 8]

    def test_fill_first_blank(self):
        classifications = [
            _rc(5, "sample_candidate"),
            _rc(6, "blank"),
            _rc(7, "blank"),
        ]
        plan = build_write_plan(classifications, "fill-first-blank", 2)
        assert plan.first_write_row == 6
        assert plan.target_rows == [6, 7]

    def test_replace_samples_within_capacity(self):
        classifications = [
            _rc(5, "sample_candidate"),
            _rc(6, "sample_candidate"),
            _rc(7, "blank"),
        ]
        plan = build_write_plan(classifications, "replace-samples", 2)
        assert set(plan.target_rows) == {5, 6}

    def test_replace_samples_exceeds_capacity_appends(self):
        classifications = [
            _rc(5, "sample_candidate"),
            _rc(6, "blank"),
        ]
        plan = build_write_plan(classifications, "replace-samples", 3)
        assert 5 in plan.target_rows
        assert len(plan.target_rows) == 3
        assert plan.warnings  # should warn about overflow

    def test_replace_all_products_within_capacity(self):
        classifications = [
            _rc(5, "existing_product"),
            _rc(6, "existing_product"),
            _rc(7, "blank"),
        ]
        plan = build_write_plan(classifications, "replace-all-products", 2)
        assert set(plan.target_rows) == {5, 6}

    def test_replace_all_products_no_existing_falls_back_to_append(self):
        classifications = [
            _rc(5, "blank"),
        ]
        plan = build_write_plan(classifications, "replace-all-products", 1)
        assert plan.policy == "append"
        assert plan.warnings

    def test_preview_only_has_is_preview_true(self):
        classifications = [_rc(5, "blank")]
        plan = build_write_plan(classifications, "preview-only", 1)
        assert plan.is_preview is True
        assert plan.target_rows == [5]

    def test_invalid_policy_raises(self):
        with pytest.raises(ValueError, match="Unknown write policy"):
            build_write_plan([], "not-a-real-policy", 1)

    def test_all_valid_policies_accepted(self):
        classifications = [_rc(5, "blank"), _rc(6, "blank")]
        for p in VALID_POLICIES:
            plan = build_write_plan(classifications, p, 1)
            assert plan.policy in (p, "append")  # fallbacks may switch to append

    def test_empty_classifications_appends_from_row1(self):
        plan = build_write_plan([], "append", 2)
        assert plan.first_write_row == 1
        assert plan.target_rows == [1, 2]


# ── Integration: row detection drives the engine ──────────────────────────────

class TestEngineRowDetection:
    """Integration tests: use make_standard_wb, detect rows, verify write target."""

    def test_standard_wb_detects_row8_as_first_write(self, tmp_path):
        """Standard template: row 8 is the first blank, so append must target row 8."""
        headers = ["Supplier Part Number", "Product Name"]
        wb = make_standard_wb(headers)
        tpl = _save_wb(wb, tmp_path)

        wb2 = openpyxl.load_workbook(str(tpl))
        ws = wb2.active
        col_map = {"Supplier Part Number": 1, "Product Name": 2}
        classifications = classify_data_area(ws, header_row=4, col_map=col_map)
        plan = build_write_plan(classifications, "append", 1)
        wb2.close()

        assert plan.first_write_row == 8, (
            f"Expected first_write_row=8 for a fresh standard template, got {plan.first_write_row}. "
            f"classifications: {[(rc.row_number, rc.status) for rc in classifications]}"
        )

    def test_write_plan_target_rows_driven_by_classifications(self, tmp_path):
        """Three incoming products -> target_rows must be [8, 9, 10]."""
        headers = ["Supplier Part Number", "Product Name"]
        wb = make_standard_wb(headers)
        tpl = _save_wb(wb, tmp_path)

        wb2 = openpyxl.load_workbook(str(tpl))
        ws = wb2.active
        col_map = {"Supplier Part Number": 1, "Product Name": 2}
        classifications = classify_data_area(ws, header_row=4, col_map=col_map)
        plan = build_write_plan(classifications, "append", 3)
        wb2.close()

        assert plan.target_rows == [8, 9, 10]

    def test_existing_products_push_append_down(self, tmp_path):
        """If rows 8-10 already have products, append must target row 11+."""
        headers = ["Supplier Part Number", "Product Name"]
        wb = make_standard_wb(headers)
        ws = wb.active
        ws.cell(8, 1).value = "EXISTING-001"
        ws.cell(9, 1).value = "EXISTING-002"
        ws.cell(10, 1).value = "EXISTING-003"
        tpl = _save_wb(wb, tmp_path)

        wb2 = openpyxl.load_workbook(str(tpl))
        ws2 = wb2.active
        col_map = {"Supplier Part Number": 1, "Product Name": 2}
        classifications = classify_data_area(ws2, header_row=4, col_map=col_map)
        plan = build_write_plan(classifications, "append", 2)
        wb2.close()

        assert plan.first_write_row == 11, (
            f"Expected first_write_row=11 after 3 existing products at rows 8-10, "
            f"got {plan.first_write_row}"
        )
        assert plan.target_rows == [11, 12]

    def test_fill_first_blank_uses_first_blank_after_metadata(self, tmp_path):
        """fill-first-blank on a fresh standard template must also target row 8."""
        headers = ["Supplier Part Number"]
        wb = make_standard_wb(headers)
        tpl = _save_wb(wb, tmp_path)

        wb2 = openpyxl.load_workbook(str(tpl))
        ws = wb2.active
        col_map = {"Supplier Part Number": 1}
        classifications = classify_data_area(ws, header_row=4, col_map=col_map)
        plan = build_write_plan(classifications, "fill-first-blank", 1)
        wb2.close()

        assert plan.first_write_row == 8

    def test_full_write_produces_data_at_detected_row(self, tmp_path):
        """End-to-end: classify -> build plan -> write -> verify cell."""
        headers = ["Supplier Part Number", "Product Name"]
        wb = make_standard_wb(headers)
        tpl = _save_wb(wb, tmp_path)

        # Detect
        wb2 = openpyxl.load_workbook(str(tpl))
        ws = wb2.active
        col_map = {"Supplier Part Number": 1, "Product Name": 2}
        classifications = classify_data_area(ws, header_row=4, col_map=col_map)
        plan = build_write_plan(classifications, "append", 1)
        wb2.close()

        # Write
        write_result = write_filled_template(
            template_path=tpl,
            output_dir=tmp_path / "out",
            category_name="Test",
            listing_sheet_name="9999 - Test Category",
            header_row=4,
            write_plan=plan,
            max_col=2,
            mapped_rows=[[
                _mr("Supplier Part Number", "DETECTED-SKU-001"),
                _mr("Product Name", "Dynamic Lamp"),
            ]],
        )

        # Verify
        out_wb = openpyxl.load_workbook(str(write_result.output_path), data_only=True)
        ws_out = out_wb.active
        assert ws_out.cell(plan.first_write_row, 1).value == "DETECTED-SKU-001"
        assert ws_out.cell(plan.first_write_row, 2).value == "Dynamic Lamp"
        out_wb.close()
