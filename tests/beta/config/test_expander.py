"""Tests for app.beta.config.expander."""

import pytest

from app.beta.config.expander import expand_placeholders, find_unexpanded


class TestExpandPlaceholders:
    def test_simple_substitution(self):
        result = expand_placeholders("${FOO}", env={"FOO": "bar"})
        assert result == "bar"

    def test_multiple_substitutions(self):
        result = expand_placeholders(
            "host=${HOST} port=${PORT}",
            env={"HOST": "localhost", "PORT": "5432"},
        )
        assert result == "host=localhost port=5432"

    def test_unknown_placeholder_left_as_is(self):
        result = expand_placeholders("${UNKNOWN_VAR}", env={})
        assert result == "${UNKNOWN_VAR}"

    def test_no_placeholders(self):
        text = "plain text without any placeholders"
        assert expand_placeholders(text, env={}) == text

    def test_partial_expansion(self):
        result = expand_placeholders(
            "${KNOWN} and ${UNKNOWN}",
            env={"KNOWN": "value"},
        )
        assert result == "value and ${UNKNOWN}"

    def test_empty_text(self):
        assert expand_placeholders("", env={}) == ""

    def test_nested_toml_style(self):
        text = 'url = "${BETA_NEXTCLOUD_URL}/api"'
        result = expand_placeholders(text, env={"BETA_NEXTCLOUD_URL": "https://cloud.example.com"})
        assert result == 'url = "https://cloud.example.com/api"'

    def test_underscore_in_var_name(self):
        result = expand_placeholders("${BETA_POSTGRES_PASSWORD}", env={"BETA_POSTGRES_PASSWORD": "secret"})
        assert result == "secret"

    def test_uses_os_environ_when_env_is_none(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_VAR_12345", "injected_value")
        result = expand_placeholders("${MY_TEST_VAR_12345}", env=None)
        assert result == "injected_value"


class TestFindUnexpanded:
    def test_finds_unknown_vars(self):
        missing = find_unexpanded("${A} ${B} ${C}", env={"A": "1"})
        assert set(missing) == {"B", "C"}

    def test_empty_when_all_known(self):
        missing = find_unexpanded("${A} ${B}", env={"A": "x", "B": "y"})
        assert missing == []

    def test_no_placeholders(self):
        assert find_unexpanded("plain text", env={}) == []

    def test_uses_os_environ_when_none(self, monkeypatch):
        monkeypatch.setenv("EXPAND_TEST_VAR_XYZ", "present")
        missing = find_unexpanded("${EXPAND_TEST_VAR_XYZ} ${ABSENT_VAR_XYZ_999}", env=None)
        assert "ABSENT_VAR_XYZ_999" in missing
        assert "EXPAND_TEST_VAR_XYZ" not in missing
