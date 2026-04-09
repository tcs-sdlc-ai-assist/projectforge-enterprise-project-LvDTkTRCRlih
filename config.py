import logging
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    SECRET_KEY: str = "change-me-in-production-use-a-strong-random-key"
    DATABASE_URL: str = f"sqlite+aiosqlite:///{BASE_DIR / 'projectforge.db'}"
    DEFAULT_ADMIN_USERNAME: str = "admin"
    DEFAULT_ADMIN_PASSWORD: str = "admin123"
    TOKEN_EXPIRY_SECONDS: int = 3600

    def validate_settings(self) -> None:
        if self.SECRET_KEY == "change-me-in-production-use-a-strong-random-key":
            logger.warning(
                "SECRET_KEY is using the default value. "
                "Set a strong random SECRET_KEY environment variable for production."
            )
        if self.DEFAULT_ADMIN_PASSWORD == "admin123":
            logger.warning(
                "DEFAULT_ADMIN_PASSWORD is using the default value. "
                "Set a strong password via environment variable for production."
            )
        if self.TOKEN_EXPIRY_SECONDS <= 0:
            raise ValueError("TOKEN_EXPIRY_SECONDS must be a positive integer.")
        if not self.DATABASE_URL:
            raise ValueError("DATABASE_URL must not be empty.")
        if not self.DEFAULT_ADMIN_USERNAME:
            raise ValueError("DEFAULT_ADMIN_USERNAME must not be empty.")
        if not self.DEFAULT_ADMIN_PASSWORD:
            raise ValueError("DEFAULT_ADMIN_PASSWORD must not be empty.")


settings = Settings()
settings.validate_settings()