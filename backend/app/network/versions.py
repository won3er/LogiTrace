"""Consulta da versão de rede vigente (módulo leve: não importa as bibliotecas de construção do grafo)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NetworkVersion


def latest_version_id(db: Session) -> int | None:
    return db.scalar(
        select(NetworkVersion.id).where(NetworkVersion.status == "ready").order_by(NetworkVersion.id.desc()).limit(1)
    )
