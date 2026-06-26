"""Tests for app.beta.config.migration."""

import pytest

from app.beta.config.migration import CURRENT_CONFIG_VERSION, ConfigMigration


class TestConfigMigration:
    def test_detect_version_present(self):
        m = ConfigMigration()
        config = {"meta": {"version": "beta-1.0.0"}}
        assert m.detect_version(config) == "beta-1.0.0"

    def test_detect_version_missing_returns_unknown(self):
        m = ConfigMigration()
        assert m.detect_version({}) == "unknown"
        assert m.detect_version({"meta": {}}) == "unknown"

    def test_detect_version_non_dict_meta(self):
        m = ConfigMigration()
        assert m.detect_version({"meta": "bad"}) == "unknown"

    def test_needs_migration_false_for_current(self):
        m = ConfigMigration()
        config = {"meta": {"version": CURRENT_CONFIG_VERSION}}
        assert m.needs_migration(config) is False

    def test_needs_migration_true_for_unknown(self):
        m = ConfigMigration()
        assert m.needs_migration({}) is True

    def test_no_migration_for_current_version(self):
        m = ConfigMigration()
        config = {"meta": {"version": CURRENT_CONFIG_VERSION}, "app": {"env": "beta"}}
        updated, changes = m.migrate(config)
        assert updated is config
        assert changes == []

    def test_migration_adds_version_when_absent(self):
        m = ConfigMigration()
        config = {"app": {"env": "beta"}}
        updated, changes = m.migrate(config)
        assert updated["meta"]["version"] == CURRENT_CONFIG_VERSION
        assert len(changes) == 1
        assert "meta.version" in changes[0]

    def test_input_not_modified_in_place(self):
        m = ConfigMigration()
        original = {"app": {"env": "beta"}}
        original_id = id(original)
        updated, _ = m.migrate(original)
        assert id(updated) != original_id

    def test_unknown_version_gets_stamped(self):
        m = ConfigMigration()
        config = {"meta": {"version": "unknown-old"}}
        updated, changes = m.migrate(config)
        assert len(changes) == 1
        assert "No migration path" in changes[0]

    def test_current_version_constant(self):
        assert CURRENT_CONFIG_VERSION == "beta-1.0.0"
