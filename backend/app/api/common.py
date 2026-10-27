from __future__ import annotations

from typing import Annotated, Any, Generic, TypeVar

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.network.builder import latest_version_id
from app.network.engine import NetworkGraph, get_graph

DB = Annotated[Session, Depends(get_db)]
T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class Metric(BaseModel):
    """Indicador com metadados obrigatórios (definição, unidade, período, fonte, limitações)."""

    key: str
    label: str
    value: float | int | None
    unit: str
    definition: str
    period: str
    source: str
    denominator: str | None = None
    limitations: str | None = None


def page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1)] = 50,
) -> tuple[int, int]:
    return page, min(page_size, get_settings().max_page_size)


PageParams = Annotated[tuple[int, int], Depends(page_params)]


def parse_bbox(bbox: str | None) -> tuple[float, float, float, float] | None:
    if not bbox:
        return None
    try:
        parts = [float(x) for x in bbox.split(",")]
    except ValueError as exc:
        raise HTTPException(400, "bbox deve ser 'minLon,minLat,maxLon,maxLat'") from exc
    if len(parts) != 4 or parts[0] >= parts[2] or parts[1] >= parts[3]:
        raise HTTPException(400, "bbox deve ser 'minLon,minLat,maxLon,maxLat' com mín < máx")
    return parts[0], parts[1], parts[2], parts[3]


def graph_or_404(db: Session, version_id: int | None = None) -> NetworkGraph:
    vid = version_id or latest_version_id(db)
    if vid is None:
        raise HTTPException(409, "Nenhuma versão de rede construída. Execute `python -m app.cli build-network`.")
    return get_graph(db, vid)


def jsonable(o: Any) -> Any:
    from app.optimization.service import _jsonable

    return _jsonable(o)
