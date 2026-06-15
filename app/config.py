from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    nextcloud_url: str
    nextcloud_user: str
    nextcloud_password: str
    nextcloud_file_path: str

    wc_url: str
    wc_key: str
    wc_secret: str

    database_url: str = "sqlite:///./wooprice.db"

    # Auth — set JWT_SECRET to a long random string in production
    jwt_secret: str = "change-me-in-production"
    # Comma-separated Nextcloud usernames that are always super-admin, bypass app_users table.
    super_admin_users: str = ""

    # Bootstrap seed — users created in app_users on startup if not already present.
    # Never overwrites existing rows. Comma-separated Nextcloud usernames.
    bootstrap_app_admins: str = ""   # seeded with is_admin=True
    bootstrap_app_users: str = ""    # seeded with is_admin=False (price operators)

    # Product cache TTL in hours (default 6h). Set to 0 to disable caching.
    wc_cache_ttl_hours: int = 6
    # Auto-fetch interval in hours (default 4h). Set to 0 to disable auto-fetch.
    wc_auto_fetch_hours: int = 4

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
