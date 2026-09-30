"""Unit tests for sheet classification."""
import pytest
from app.analyser.sheet_classifier import classify_sheet


def _cls(name, is_hidden=False, max_row=10, max_col=10, first_row=None, sample=None):
    return classify_sheet(
        sheet_name=name,
        is_hidden=is_hidden,
        max_row=max_row,
        max_col=max_col,
        first_row_values=first_row or [],
        all_sample_text=sample or [],
    )


class TestListingSheetDetection:
    def test_numeric_prefix_sheet_is_listing(self):
        r = _cls("6085 - Chandeliers", max_col=137, first_row=["core::supplierPartNumber"])
        assert r.sheet_type == "listing"

    def test_high_column_count_boosts_listing(self):
        r = _cls("6085 - Chandeliers", max_col=120)
        assert r.sheet_type == "listing"

    def test_core_key_in_first_row_boosts_listing(self):
        r = _cls("Sheet1", max_col=100, first_row=["core::supplierPartNumber", "core::productName"])
        assert r.sheet_type == "listing"

    def test_listing_template_name(self):
        r = _cls("listing template", max_col=141)
        assert r.sheet_type == "listing"


class TestInstructionSheetDetection:
    def test_instructions_name(self):
        r = _cls("Instructions", max_row=41, max_col=4)
        assert r.sheet_type == "instruction"

    def test_read_me_name(self):
        r = _cls("Read Me", max_row=50, max_col=3)
        assert r.sheet_type == "instruction"


class TestValidValueSheetDetection:
    def test_valid_values_name(self):
        r = _cls("Valid Values", max_row=533, max_col=57)
        assert r.sheet_type == "valid_values"


class TestImageSheetDetection:
    def test_additional_images_name(self):
        r = _cls("Additional Images", max_row=7, max_col=26)
        assert r.sheet_type == "image"


class TestDocumentSheetDetection:
    def test_additional_documents_name(self):
        r = _cls("Additional Documents", max_row=7, max_col=26)
        assert r.sheet_type == "document"


class TestInternalSheetDetection:
    def test_wayfair_use_only_hidden(self):
        r = _cls("WAYFAIR_USE_ONLY", is_hidden=True)
        assert r.sheet_type == "internal"


class TestConfidenceScores:
    def test_confidence_between_0_and_1(self):
        for name in ["Instructions", "Valid Values", "6085 - Chandeliers", "WAYFAIR_USE_ONLY"]:
            r = _cls(name)
            assert 0.0 <= r.confidence <= 1.0
