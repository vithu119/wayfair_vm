"""Tests for robustness: broken workbooks don't stop others; originals unchanged."""
import os
import shutil
import tempfile
from pathlib import Path

import openpyxl
import pytest

from tests.conftest import make_standard_wb, save_wb_to_temp
from app.analyser.inspector import inspect_workbook
from app.analyser.integrity import snapshot_directory, verify_snapshot


class TestBrokenWorkbookIsolation:
    def test_broken_workbook_returns_failed_profile(self, tmp_path):
        bad = tmp_path / "bad.xlsx"
        bad.write_bytes(b"this is not a valid xlsx file")
        profile = inspect_workbook(bad)
        assert profile.analysis_status == "failed"
        assert len(profile.errors) > 0

    def test_broken_workbook_does_not_affect_good_one(self, tmp_path):
        bad = tmp_path / "bad.xlsx"
        bad.write_bytes(b"not valid")

        wb = make_standard_wb(["Supplier Part Number", "Product Name", "Brand"])
        good = tmp_path / "good.xlsx"
        wb.save(str(good))

        bad_profile = inspect_workbook(bad)
        good_profile = inspect_workbook(good)

        assert bad_profile.analysis_status == "failed"
        assert good_profile.analysis_status in ("ok", "partial")
        assert good_profile.listing_sheet is not None


class TestOriginalFileIntegrity:
    def test_inspect_does_not_modify_file(self, tmp_path):
        wb = make_standard_wb(["SKU", "Name", "Brand"])
        path = tmp_path / "template.xlsx"
        wb.save(str(path))

        before = snapshot_directory(tmp_path)
        inspect_workbook(path)
        results = verify_snapshot(before, tmp_path)

        assert results["template.xlsx"] == "unchanged"

    def test_multiple_inspects_leave_files_unchanged(self, tmp_path):
        paths = []
        for i in range(3):
            wb = make_standard_wb([f"Header{j}" for j in range(5)])
            p = tmp_path / f"template_{i}.xlsx"
            wb.save(str(p))
            paths.append(p)

        before = snapshot_directory(tmp_path)
        for p in paths:
            inspect_workbook(p)
        results = verify_snapshot(before, tmp_path)

        assert all(v == "unchanged" for v in results.values())


class TestFuzzyMatchNotAutoApproved:
    def test_fuzzy_suggestions_are_only_suggestions(self):
        from app.analyser.comparator import compare_profiles, FuzzyMatch
        # Two profiles with similar but distinct headers
        wb1 = make_standard_wb(["Supplier Part Number", "Unique Field Alpha"])
        p1 = save_wb_to_temp(wb1)
        profile1 = inspect_workbook(p1)
        profile1.category_name = "Category A"

        wb2 = make_standard_wb(["Supplier Part Number", "Unique Field Alfa"])
        p2 = save_wb_to_temp(wb2)
        profile2 = inspect_workbook(p2)
        profile2.category_name = "Category B"

        result = compare_profiles([profile1, profile2])

        # Fuzzy matches must have the note field
        for fm in result.fuzzy_suggestions:
            assert isinstance(fm, FuzzyMatch)
            assert "human review" in fm.note.lower() or "suggestion" in fm.note.lower()

        # Fuzzy matches must NOT automatically merge into shared_by_all
        shared_norm = set(result.shared_by_all)
        assert "unique field alpha" not in shared_norm
        assert "unique field alfa" not in shared_norm
