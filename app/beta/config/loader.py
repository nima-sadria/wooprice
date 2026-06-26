"""WooPrice Beta — Environment loader.

Loads environment variables from .env files and the process environment.
Process environment always takes priority over .env file values.
"""

import os
from pathlib import Path


class ConfigurationError(Exception):
    """Raised when configuration cannot be loaded or is fundamentally broken."""


class EnvironmentLoader:
    """Loads BETA_* environment variables from .env files and os.environ."""

    def load(self, env_file: Path | None = None) -> dict[str, str]:
        """Load all environment variables, optionally merging a .env file.

        Priority: process environment > .env file.
        Returns all environment variables as a flat string dict.
        """
        result: dict[str, str] = {}

        if env_file is not None:
            if not env_file.exists():
                raise ConfigurationError(f".env file not found: {env_file}")
            result.update(self._load_dotenv_file(env_file))

        # Process environment overrides .env values
        result.update({k: v for k, v in os.environ.items() if isinstance(v, str)})
        return result

    def load_beta_only(self, env_file: Path | None = None) -> dict[str, str]:
        """Like load() but returns only BETA_* variables."""
        return {k: v for k, v in self.load(env_file).items() if k.startswith("BETA_")}

    @staticmethod
    def _load_dotenv_file(env_file: Path) -> dict[str, str]:
        try:
            from dotenv import dotenv_values
            parsed = dotenv_values(env_file)
            return {k: v for k, v in parsed.items() if v is not None}
        except ImportError:
            # Fallback: manual parse if python-dotenv unavailable
            result: dict[str, str] = {}
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    result[key] = value
            return result
