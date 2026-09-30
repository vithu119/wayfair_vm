"""Tests for SOT integration — all run without a live DB connection."""
from __future__ import annotations
import os
import pytest


# ---------------------------------------------------------------------------
# postgres_guard
# ---------------------------------------------------------------------------

def test_postgres_guard_blocks_insert():
    from app.sources.postgres_guard import assert_read_only
    with pytest.raises(ValueError, match="write operation"):
        assert_read_only("INSERT INTO foo VALUES (1)")


def test_postgres_guard_blocks_update():
    from app.sources.postgres_guard import assert_read_only
    with pytest.raises(ValueError):
        assert_read_only("UPDATE foo SET bar = 1 WHERE id = 2")


def test_postgres_guard_blocks_delete():
    from app.sources.postgres_guard import assert_read_only
    with pytest.raises(ValueError):
        assert_read_only("DELETE FROM foo WHERE id = 1")


def test_postgres_guard_blocks_drop():
    from app.sources.postgres_guard import assert_read_only
    with pytest.raises(ValueError):
        assert_read_only("DROP TABLE foo")


def test_postgres_guard_allows_select():
    from app.sources.postgres_guard import assert_read_only
    # Should not raise
    assert_read_only("SELECT * FROM public.components_sot_attributes WHERE key = 'foo'")


# ---------------------------------------------------------------------------
# postgres_connection — env not configured
# ---------------------------------------------------------------------------

def test_env_not_configured(monkeypatch):
    """Missing env vars should raise EnvironmentError with expected code."""
    monkeypatch.delenv("CONFIGURATOR_DB_HOST", raising=False)
    monkeypatch.delenv("CONFIGURATOR_DB_NAME", raising=False)
    monkeypatch.delenv("CONFIGURATOR_DB_USER", raising=False)
    from app.sources.postgres_connection import _get_dsn
    with pytest.raises(EnvironmentError, match="configurator_sot_not_configured"):
        _get_dsn()


# ---------------------------------------------------------------------------
# sot_value_parser
# ---------------------------------------------------------------------------

def test_parse_25mm():
    from app.sources.sot_value_parser import parse_sot_value
    r = parse_sot_value("25mm")
    assert r.value_type == "measurement"
    assert r.numeric == 25.0
    assert r.unit == "mm"


def test_parse_0_8mm():
    from app.sources.sot_value_parser import parse_sot_value
    r = parse_sot_value("0.8mm")
    assert r.value_type == "measurement"
    assert r.numeric == 0.8
    assert r.unit == "mm"


def test_parse_5kg():
    from app.sources.sot_value_parser import parse_sot_value
    r = parse_sot_value("5Kg")
    assert r.value_type == "measurement"
    assert r.unit == "kg"
    assert r.numeric == 5.0


def test_parse_range_5_8mm():
    from app.sources.sot_value_parser import parse_sot_value
    r = parse_sot_value("5-8mm")
    assert r.value_type == "measurement_range"
    assert r.range_min == 5.0
    assert r.range_max == 8.0


def test_parse_boolean_yes():
    from app.sources.sot_value_parser import parse_sot_value
    r = parse_sot_value("YES")
    assert r.value_type == "boolean"
    assert r.parsed_value is True


def test_parse_boolean_no():
    from app.sources.sot_value_parser import parse_sot_value
    r = parse_sot_value("No")
    assert r.value_type == "boolean"
    assert r.parsed_value is False


def test_parse_ip_rating():
    from app.sources.sot_value_parser import parse_sot_value
    r = parse_sot_value("IP20")
    assert r.value_type == "ip_rating"
    assert r.parsed_value == "IP20"


def test_parse_hex():
    from app.sources.sot_value_parser import parse_sot_value
    r = parse_sot_value("#3A6F8F")
    assert r.value_type == "colour_hex"


def test_unit_conversion_mm_to_cm():
    from app.sources.sot_value_parser import parse_sot_value, convert_unit
    parsed = parse_sot_value("100mm")
    result = convert_unit(parsed, "cm")
    assert result.parsed_value == pytest.approx(10.0)
    assert result.unit == "cm"


def test_unit_conversion_g_to_kg():
    from app.sources.sot_value_parser import parse_sot_value, convert_unit
    parsed = parse_sot_value("250g")
    result = convert_unit(parsed, "kg")
    assert result.parsed_value == pytest.approx(0.25)
    assert result.unit == "kg"


def test_unit_mismatch_warning():
    from app.sources.sot_value_parser import parse_sot_value, convert_unit
    parsed = parse_sot_value("25mm")
    result = convert_unit(parsed, "oz")
    assert any("unit_mismatch" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# configurator_sot_source — resolve_asin without DB
# ---------------------------------------------------------------------------

def test_resolve_asin_no_env(monkeypatch):
    """resolve_asin with no DB env vars should return asin_not_found with warning."""
    monkeypatch.delenv("CONFIGURATOR_DB_HOST", raising=False)
    monkeypatch.delenv("CONFIGURATOR_DB_NAME", raising=False)
    monkeypatch.delenv("CONFIGURATOR_DB_USER", raising=False)
    from app.sources.configurator_sot_source import resolve_asin
    result = resolve_asin("B0H6MBRQDR")
    assert result.status == "asin_not_found"
    assert any("configurator_sot_not_configured" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# sot_models
# ---------------------------------------------------------------------------

def test_sot_models_product_identity_defaults():
    from app.sources.sot_models import ProductIdentity
    pi = ProductIdentity(input_asin="B0TEST")
    assert pi.status == "asin_not_found"
    assert pi.asin is None
    assert pi.component_skus == []
    assert pi.evidence == []
    assert pi.warnings == []


def test_sot_models_parsed_value():
    from app.sources.sot_models import ParsedSotValue
    pv = ParsedSotValue(raw_value="25mm", parsed_value=25.0)
    assert pv.raw_value == "25mm"
    assert pv.parsed_value == 25.0
