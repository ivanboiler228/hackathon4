"""Конфигурация приложения. Секреты берутся только из окружения."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    app_name: str = "Фотопринт · AI-ассистент"
    base_dir: Path = BASE_DIR
    static_dir: Path = BASE_DIR / "static"
    data_dir: Path = BASE_DIR / "data"
    db_path: Path = Path(os.getenv("DB_PATH", str(BASE_DIR / "data" / "app.db")))

    # Если SECRET_KEY не задан, сессии будут сбрасываться при перезапуске.
    secret_key: str = os.getenv("SECRET_KEY") or secrets.token_urlsafe(48)
    session_cookie: str = "fp_session"
    session_max_age: int = int(os.getenv("SESSION_MAX_AGE", str(8 * 3600)))
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "0") == "1"

    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "").strip()
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    llm_timeout: float = float(os.getenv("LLM_TIMEOUT", "30"))
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "700"))

    demo_user: str = os.getenv("DEMO_USER", "anna")
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))
    demo_mode: bool = os.getenv("DEMO_MODE", "1") == "1"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.deepseek_api_key)


settings = Settings()
