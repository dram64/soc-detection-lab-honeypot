from __future__ import annotations

import pytest

from functions.shared.password_classifier import (
    DICTIONARY_PATH,
    classify_password,
    load_dictionary,
)


@pytest.fixture(scope="module")
def dictionary() -> frozenset[str]:
    return load_dictionary()


def test_dictionary_file_exists():
    assert DICTIONARY_PATH.exists()
    assert DICTIONARY_PATH.is_file()


def test_dictionary_contains_canonical_attack_strings(dictionary):
    for canonical in ("123456", "password", "admin", "root", "raspberry"):
        assert canonical in dictionary, f"{canonical!r} should be in the dictionary"


def test_dictionary_size_at_least_5000(dictionary):
    # ADR-005 specifies ~5000 entries.
    assert len(dictionary) >= 5000, f"got {len(dictionary)} entries"


def test_dictionary_is_frozenset(dictionary):
    assert isinstance(dictionary, frozenset)


def test_classify_dictionary_hit_returns_original(dictionary):
    public, raw = classify_password("123456", dictionary)
    assert public == "123456"
    assert raw is None


def test_classify_non_match_redacts_to_length_marker(dictionary):
    needle = "this-is-clearly-not-in-the-attack-dictionary-7392"
    public, raw = classify_password(needle, dictionary)
    assert public == f"<filtered:len={len(needle)}>"
    assert raw == needle


def test_classify_preserves_zero_length():
    public, raw = classify_password("", frozenset())
    # Empty string isn't a dictionary hit; treat as filtered with length 0.
    assert public == "<filtered:len=0>"
    assert raw == ""


def test_classify_handles_none():
    public, raw = classify_password(None, frozenset({"x"}))
    assert public is None
    assert raw is None


def test_classify_is_case_sensitive(dictionary):
    # Dictionary entries are lowercase; an uppercase variant is a non-match.
    public_upper, raw_upper = classify_password("PASSWORD", dictionary)
    if "PASSWORD" in dictionary:
        assert public_upper == "PASSWORD"
    else:
        assert public_upper.startswith("<filtered:")
        assert raw_upper == "PASSWORD"


def test_classify_non_match_with_unicode(dictionary):
    # Cyrillic chars in the literal are intentional — this test verifies the
    # classifier correctly handles non-Latin-script passwords. Replacing them
    # with visually-similar Latin chars defeats the test's purpose.
    needle = "пароль123"  # Russian for "password" + digits — not in our dictionary  # noqa: RUF001
    public, raw = classify_password(needle, dictionary)
    assert public.startswith("<filtered:len=")
    assert raw == needle


def test_load_dictionary_strips_blank_lines_and_comments(tmp_path):
    fixture = tmp_path / "dict.txt"
    fixture.write_text(
        "# header comment\nfoo\n\n  bar  \n# inline comment\nbaz\n",
        encoding="utf-8",
    )
    result = load_dictionary(fixture)
    assert result == frozenset({"foo", "bar", "baz"})


def test_load_dictionary_default_path():
    # Calling with no argument loads the bundled production dictionary.
    result = load_dictionary()
    assert "123456" in result


def test_classify_does_not_log_raw_value(dictionary, caplog):
    # The classifier must never emit log output containing a non-match raw value.
    needle = "should-never-be-in-logs-9173"
    with caplog.at_level("DEBUG"):
        classify_password(needle, dictionary)
    for record in caplog.records:
        assert needle not in record.getMessage()
