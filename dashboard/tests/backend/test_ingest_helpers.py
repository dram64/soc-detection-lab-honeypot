"""Direct tests for the ingest module's small pure helpers (no AWS)."""

from __future__ import annotations

import pytest

from functions.ingest.handler import _to_ddb_attr, _chunked, _ingest_id, _ttl_for


def test_to_ddb_attr_string():
    assert _to_ddb_attr("hello") == {"S": "hello"}


def test_to_ddb_attr_int():
    assert _to_ddb_attr(42) == {"N": "42"}


def test_to_ddb_attr_float():
    out = _to_ddb_attr(3.5)
    assert out == {"N": "3.5"}


def test_to_ddb_attr_bool():
    assert _to_ddb_attr(True) == {"BOOL": True}
    assert _to_ddb_attr(False) == {"BOOL": False}


def test_to_ddb_attr_none():
    assert _to_ddb_attr(None) == {"NULL": True}


def test_to_ddb_attr_list():
    assert _to_ddb_attr(["a", 1]) == {"L": [{"S": "a"}, {"N": "1"}]}


def test_to_ddb_attr_dict():
    assert _to_ddb_attr({"k": "v"}) == {"M": {"k": {"S": "v"}}}


def test_to_ddb_attr_nested():
    out = _to_ddb_attr({"items": [{"name": "x", "n": 7}]})
    assert out == {
        "M": {
            "items": {
                "L": [
                    {"M": {"name": {"S": "x"}, "n": {"N": "7"}}},
                ]
            }
        }
    }


def test_to_ddb_attr_unsupported_raises():
    with pytest.raises(TypeError):
        _to_ddb_attr(object())


def test_chunked_empty():
    assert list(_chunked([], 25)) == []


def test_chunked_partial():
    assert list(_chunked([1, 2, 3], 2)) == [[1, 2], [3]]


def test_chunked_exact():
    out = list(_chunked(list(range(50)), 25))
    assert len(out) == 2
    assert all(len(c) == 25 for c in out)


def test_ingest_id_deterministic():
    a = _ingest_id({"session": "abcd", "timestamp": "2026-04-27T00:00:00.000000Z",
                    "eventid": "cowrie.session.connect"})
    b = _ingest_id({"session": "abcd", "timestamp": "2026-04-27T00:00:00.000000Z",
                    "eventid": "cowrie.session.connect"})
    c = _ingest_id({"session": "abcd", "timestamp": "2026-04-27T00:00:01.000000Z",
                    "eventid": "cowrie.session.connect"})
    assert a == b
    assert a != c
    assert len(a) == 40  # SHA-1 hex


def test_ttl_for_returns_future_epoch():
    ttl = _ttl_for("2026-04-27T00:00:00.000000Z")
    # 2026-04-27 + 90 days = 2026-07-26; > 2026-04-27 epoch
    assert ttl > 1745712000  # 2025-04-27 epoch — anything later than that
