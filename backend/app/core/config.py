"""Configuração da aplicação via variáveis de ambiente (arquivo backend/.env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_prefix="LOGITRACE_", extra="ignore"
    )

    env: str = "development"
    database_url: str = "postgresql+psycopg://logitrace:logitrace@localhost:5433/logitrace"
    test_database_url: str = "postgresql+psycopg://logitrace:logitrace@localhost:5433/logitrace_test"
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    log_level: str = "INFO"

    data_dir: Path = PROJECT_DIR / "data"
    raw_dir: Path = PROJECT_DIR / "data" / "raw"
    cache_dir: Path = PROJECT_DIR / "data" / "cache"
    export_dir: Path = PROJECT_DIR / "data" / "exports"

    # Limites de proteção das consultas interativas
    max_page_size: int = 500
    max_features_per_request: int = 20000
    job_workers: int = 2

    # Otimização
    solver_time_limit_s: float = 60.0

    @field_validator("database_url", "test_database_url")
    @classmethod
    def _psycopg_driver(cls, v: str) -> str:
        # Provedores (Render, Neon) entregam postgres:// ou postgresql://; o SQLAlchemy precisa do driver psycopg
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
