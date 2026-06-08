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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
