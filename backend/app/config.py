from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[2] / ".env", extra="ignore")

    app_env: str = "development"
    bot_token: str = ""
    public_url: str = "http://localhost:5173"
    database_url: str = "sqlite:///./workout.db"
    webhook_secret: str = ""
    dev_telegram_id: int = 0


@lru_cache
def get_settings() -> Settings:
    return Settings()
