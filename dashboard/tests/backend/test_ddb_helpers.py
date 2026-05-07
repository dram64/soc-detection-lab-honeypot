"""Tests for the shared DynamoDB helpers."""

from __future__ import annotations

from functions.shared.ddb_helpers import (
    make_ddb_client_config,
    unmarshal_dynamodb_value,
    unmarshal_image,
)


def test_unmarshal_string():
    assert unmarshal_dynamodb_value({"S": "hello"}) == "hello"


def test_unmarshal_int():
    assert unmarshal_dynamodb_value({"N": "42"}) == 42


def test_unmarshal_float():
    assert unmarshal_dynamodb_value({"N": "3.5"}) == 3.5


def test_unmarshal_null():
    assert unmarshal_dynamodb_value({"NULL": True}) is None


def test_unmarshal_bool():
    assert unmarshal_dynamodb_value({"BOOL": True}) is True
    assert unmarshal_dynamodb_value({"BOOL": False}) is False


def test_unmarshal_list():
    assert unmarshal_dynamodb_value({"L": [{"S": "a"}, {"N": "1"}]}) == ["a", 1]


def test_unmarshal_map():
    out = unmarshal_dynamodb_value({"M": {"k": {"S": "v"}, "n": {"N": "7"}}})
    assert out == {"k": "v", "n": 7}


def test_unmarshal_unknown_type_returns_none():
    """Defensive: an unknown type-tag (e.g. binary) is silently skipped."""
    assert unmarshal_dynamodb_value({"B": "binary"}) is None


def test_unmarshal_image_round_trip():
    out = unmarshal_image(
        {
            "pk": {"S": "SESSION#abc"},
            "count": {"N": "42"},
            "active": {"BOOL": True},
            "miss": {"NULL": True},
        }
    )
    assert out == {"pk": "SESSION#abc", "count": 42, "active": True, "miss": None}


def test_make_config_default_pool_size():
    cfg = make_ddb_client_config()
    assert cfg.max_pool_connections == 25


def test_make_config_overridable():
    cfg = make_ddb_client_config(max_pool_connections=50)
    assert cfg.max_pool_connections == 50


def test_make_config_includes_retries():
    cfg = make_ddb_client_config()
    assert cfg.retries["mode"] == "standard"
    assert cfg.retries["max_attempts"] == 3
