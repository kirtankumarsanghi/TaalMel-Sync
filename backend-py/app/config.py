from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TAALMEL_", extra="ignore")

    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'taalmel.db'}"
    redis_url: str = "redis://localhost:6379"
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    ocr_inline: bool = True
    # 'auto' uses real OCR when installed, otherwise the deterministic stub.
    # 'easyocr' requires it and fails loudly if missing. 'stub' forces the stub.
    ocr_engine: str = "auto"
    ocr_languages: str = "en"
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    login_rate_limit: str = "10/minute"
    doctor_link_minutes: int = 120
    # Comma-separated browser origins allowed to call the API.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
