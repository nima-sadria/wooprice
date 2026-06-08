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
    # Comma-separated Nextcloud usernames that get the "admin" role, e.g. "alice,bob"
    super_admin_users: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
