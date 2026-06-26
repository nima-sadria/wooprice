"""WooPrice Beta — Configuration profiles (DEV / BETA / PRODUCTION)."""

from enum import Enum


class ConfigProfile(str, Enum):
    DEV = "dev"
    BETA = "beta"
    PRODUCTION = "production"

    @classmethod
    def from_string(cls, value: str) -> "ConfigProfile":
        try:
            return cls(value.strip().lower())
        except ValueError:
            valid = ", ".join(m.value for m in cls)
            raise ValueError(
                f"BETA_ENV {value!r} is not valid. Must be one of: {valid}"
            )

    def is_production(self) -> bool:
        return self == ConfigProfile.PRODUCTION

    def is_dev(self) -> bool:
        return self == ConfigProfile.DEV

    def banner(self) -> str:
        banners = {
            ConfigProfile.DEV: "[DEVELOPMENT ENVIRONMENT]",
            ConfigProfile.BETA: "[BETA ENVIRONMENT]",
            ConfigProfile.PRODUCTION: "[PRODUCTION]",
        }
        return banners[self]
