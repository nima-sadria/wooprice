"""Tests for app.beta.config.profiles."""

import pytest

from app.beta.config.profiles import ConfigProfile


class TestConfigProfileFromString:
    def test_beta_lower(self):
        assert ConfigProfile.from_string("beta") == ConfigProfile.BETA

    def test_dev_lower(self):
        assert ConfigProfile.from_string("dev") == ConfigProfile.DEV

    def test_production_lower(self):
        assert ConfigProfile.from_string("production") == ConfigProfile.PRODUCTION

    def test_case_insensitive(self):
        assert ConfigProfile.from_string("BETA") == ConfigProfile.BETA
        assert ConfigProfile.from_string("DEV") == ConfigProfile.DEV
        assert ConfigProfile.from_string("PRODUCTION") == ConfigProfile.PRODUCTION

    def test_strips_whitespace(self):
        assert ConfigProfile.from_string("  beta  ") == ConfigProfile.BETA

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="not valid"):
            ConfigProfile.from_string("staging")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            ConfigProfile.from_string("")


class TestConfigProfileMethods:
    def test_is_production(self):
        assert ConfigProfile.PRODUCTION.is_production() is True
        assert ConfigProfile.BETA.is_production() is False
        assert ConfigProfile.DEV.is_production() is False

    def test_is_dev(self):
        assert ConfigProfile.DEV.is_dev() is True
        assert ConfigProfile.BETA.is_dev() is False
        assert ConfigProfile.PRODUCTION.is_dev() is False

    def test_banner_beta(self):
        assert ConfigProfile.BETA.banner() == "[BETA ENVIRONMENT]"

    def test_banner_dev(self):
        assert ConfigProfile.DEV.banner() == "[DEVELOPMENT ENVIRONMENT]"

    def test_banner_production(self):
        assert "[PRODUCTION]" in ConfigProfile.PRODUCTION.banner()

    def test_str_value(self):
        assert ConfigProfile.BETA.value == "beta"
        assert ConfigProfile.DEV.value == "dev"
        assert ConfigProfile.PRODUCTION.value == "production"
