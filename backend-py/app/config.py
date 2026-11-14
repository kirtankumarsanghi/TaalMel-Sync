from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TAALMEL_", extra="ignore")

    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'taalmel.db'}"
    redis_url: str = "redis://localhost:6379"
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    # 'inline' runs jobs in the request; 'arq' enqueues them to Redis.
    job_queue: str = "inline"
    ocr_inline: bool = True
    # Notification delivery. Rows are always written; these channels are best-effort.
    notification_webhook_url: str = ""
    notification_webhook_token: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True
    # Pharmacy ordering. Empty means the safe mock provider is used.
    pharmacy_api_url: str = ""
    pharmacy_api_key: str = ""
    # 'auto' uses real OCR when installed, otherwise the deterministic stub.
    # 'easyocr' requires it and fails loudly if missing. 'google' uses Cloud Vision;
    # 'trocr' uses a local handwritten-text model; 'stub' forces the stub.
    ocr_engine: str = "auto"
    ocr_languages: str = "en"
    google_vision_api_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    trocr_model: str = "microsoft/trocr-small-handwritten"
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    login_rate_limit: str = "10/minute"
    doctor_link_minutes: int = 120
    # Comma-separated browser origins allowed to call the API.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"
    # Origin used when building doctor links and QR codes. Empty means relative paths,
    # which is correct behind a same-origin proxy; set it for shared links.
    public_base_url: str = ""
    # 'auto' uses Whisper when installed, otherwise the deterministic stub.
    speech_engine: str = "auto"
    whisper_model: str = "base"


@lru_cache
def get_settings() -> Settings:
    return Settings()
