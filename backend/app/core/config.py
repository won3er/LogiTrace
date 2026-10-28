"""Configuração da aplicação via variáveis de ambiente (arquivo backend/.env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import model_validator
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
    # "thread": tarefas pesadas em segundo plano (servidor tradicional);
    # "inline": executadas dentro da própria requisição (Vercel/serverless, onde threads morrem após a resposta)
    job_mode: str = "thread"
    # Se definido, a API só aceita requisições com o cabeçalho x-logitrace-key igual a este valor
    internal_api_secret: str = ""
    # Reconstruir o grafo exige GeoPandas/GDAL, disponíveis só na instalação completa
    allow_network_build: bool = True

    # Otimização
    solver_time_limit_s: float = 60.0

    @model_validator(mode="before")
    @classmethod
    def _strip(cls, data: Any) -> Any:
        """Remove BOM e espaços que ferramentas de linha de comando podem inserir nas variáveis de ambiente."""
        if isinstance(data, dict):
            return {k: v.strip().lstrip("﻿").strip() if isinstance(v, str) else v for k, v in data.items()}
        return data


@lru_cache
def get_settings() -> Settings:
    return Settings()
