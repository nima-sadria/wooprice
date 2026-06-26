"""WooPrice Beta — Configuration file migration.

Detects when a managed TOML config file is from an older Beta version
and applies schema changes in-place, preserving existing values.

In B3 (first version), no migration steps exist yet. Steps are added
in future phases when the config schema evolves between Beta releases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CURRENT_CONFIG_VERSION = "beta-1.0.0"


@dataclass
class MigrationStep:
    from_version: str
    to_version: str
    description: str

    def apply(self, config: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            f"Migration step {self.from_version} → {self.to_version} not implemented"
        )


@dataclass
class MigrationRecord:
    from_version: str
    to_version: str
    changes: list[str] = field(default_factory=list)


class ConfigMigration:
    """Applies version-to-version migrations on the managed TOML config dict.

    New steps are added here when the config schema changes between Beta releases.
    Each step is responsible for exactly one version transition.
    """

    CURRENT_VERSION: str = CURRENT_CONFIG_VERSION

    _STEPS: list[MigrationStep] = []

    def detect_version(self, config: dict[str, Any]) -> str:
        """Read the version from the config dict's [meta] section."""
        meta = config.get("meta", {})
        if not isinstance(meta, dict):
            return "unknown"
        version = meta.get("version")
        return str(version) if version else "unknown"

    def needs_migration(self, config: dict[str, Any]) -> bool:
        return self.detect_version(config) != self.CURRENT_VERSION

    def migrate(self, config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """Apply all required migration steps to the config dict.

        Returns the updated config dict and a list of applied change descriptions.
        The input dict is never modified in-place — a copy is returned.
        """
        version = self.detect_version(config)
        changes: list[str] = []

        if version == self.CURRENT_VERSION:
            return config, changes

        config = dict(config)

        if version == "unknown":
            config.setdefault("meta", {})
            if not isinstance(config["meta"], dict):
                config["meta"] = {}
            config["meta"]["version"] = self.CURRENT_VERSION
            changes.append(
                f"Added meta.version = {self.CURRENT_VERSION!r} (was absent)"
            )
            return config, changes

        applicable = [s for s in self._STEPS if s.from_version == version]
        if not applicable:
            changes.append(
                f"No migration path from version {version!r}. "
                "Config preserved as-is — manual review may be needed."
            )
            return config, changes

        for step in applicable:
            config = step.apply(config)
            changes.append(f"{step.from_version} → {step.to_version}: {step.description}")
            version = step.to_version

        return config, changes
