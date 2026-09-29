"""Application configuration loaded from environment variables (.env supported)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent

load_dotenv(BACKEND_DIR / ".env")
load_dotenv(PROJECT_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    ensembledata_api_key: str = field(repr=False)
    ensembledata_base_url: str
    ensembledata_daily_units: int
    provider_mode_setting: str
    app_env: str
    request_timeout: float
    request_retries: int
    rate_limit_requests: int
    rate_limit_window_seconds: int
    trust_proxy_headers: bool
    cors_origins: list[str]
    database_path: Path
    log_level: str
    frontend_dir: Path

    @property
    def api_key_configured(self) -> bool:
        return bool(self.ensembledata_api_key)

    @property
    def provider_mode(self) -> str:
        """Effective provider mode: 'live' or 'mock'."""
        mode = self.provider_mode_setting
        if mode == "mock":
            return "mock"
        if mode == "live":
            return "live"
        return "live" if self.api_key_configured else "mock"


def load_settings() -> Settings:
    db_path = Path(os.getenv("DATABASE_PATH", "data/intel.db"))
    if not db_path.is_absolute():
        db_path = BACKEND_DIR / db_path
    mode = os.getenv("PROVIDER_MODE", "auto").strip().lower()
    if mode not in {"auto", "live", "mock"}:
        mode = "auto"
    return Settings(
        ensembledata_api_key=os.getenv("ENSEMBLEDATA_API_KEY", "").strip(),
        ensembledata_base_url=(
            os.getenv("ENSEMBLEDATA_BASE_URL", "").strip() or "https://ensembledata.com/apis"
        ).rstrip("/"),
        ensembledata_daily_units=_int("ENSEMBLEDATA_DAILY_UNITS", 1000),
        provider_mode_setting=mode,
        app_env=os.getenv("APP_ENV", "development"),
        request_timeout=min(_float("REQUEST_TIMEOUT", 15.0), 15.0),
        request_retries=max(0, min(_int("REQUEST_RETRIES", 1), 3)),
        rate_limit_requests=max(1, _int("RATE_LIMIT_REQUESTS", 10)),
        rate_limit_window_seconds=max(1, _int("RATE_LIMIT_WINDOW_SECONDS", 60)),
        trust_proxy_headers=_bool("TRUST_PROXY_HEADERS", False),
        cors_origins=_list("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"),
        database_path=db_path,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        frontend_dir=Path(os.getenv("FRONTEND_DIR", str(PROJECT_DIR / "frontend"))),
    )


@lru_cache
def get_settings() -> Settings:
    return load_settings()
