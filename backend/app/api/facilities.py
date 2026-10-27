"""Explorador de infraestrutura: busca, filtros, detalhe, cadastro de instalações do usuário e importação."""

from __future__ import annotations

import io
import json
from datetime import datetime
from typing import Annotated, Any, Literal

import pandas as pd
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from geoalchemy2.shape import from_shape
from pydantic import BaseModel, Field, field_validator
from shapely.geometry import Point, shape
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.common import DB, Page, PageParams, graph_or_404, parse_bbox
from app.ingestion.common import ValidationReport, content_hash, fix_text, in_brazil
from app.ingestion.sources import ensure_sources
from app.models import DataSource, Facility
from app.network.engine import haversine_km

router = APIRouter(prefix="/facilities", tags=["instalações"])

CATEGORY_LABELS = {
    "porto": "Porto público",
    "terminal_portuario": "Terminal portuário",
    "porto_seco": "Porto seco",
    "terminal_ferroviario": "Terminal ferroviário",
    "armazem": "Armazenagem (agregada por município)",
    "aeroporto": "Aeroporto",
    "aerodromo": "Aeródromo",
    "ponto_fronteira": "Ponto de fronteira",
    "centro_distribuicao": "Centro de distribuição",
    "instalacao_usuario": "Instalação do usuário",
}
SORTS = {"name": Facility.name, "category": Facility.category, "uf": Facility.uf,
         "capacity": Facility.capacity_value, "updated": Facility.updated_at}


class FacilityOut(BaseModel):
    id: int
    external_id: str
    record_class: str
    name: str
    category: str
    category_label: str
    subcategory: str | None
    modal: str
    operator: str | None
    capacity_value: float | None
    capacity_unit: str | None
    status: str | None
    address: str | None
    municipality_code: int | None
    municipality_name: str | None
    uf: str | None
    lon: float
    lat: float
    reliability: str
    limitations: str | None
    source_key: str | None
    source_name: str | None
    source_reference: str | None
    attributes: dict[str, Any]
    updated_at: datetime


class FacilityIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    category: str = Field(default="centro_distribuicao", max_length=48)
    subcategory: str | None = None
    modal: Literal["rodoviario", "ferroviario", "aquaviario", "aereo", "intermodal"] = "rodoviario"
    operator: str | None = None
    capacity_value: float | None = Field(default=None, ge=0)
    capacity_unit: str | None = Field(default=None, description="ex.: 't/ano', 't (estática)', 'm²'")
    status: str | None = None
    address: str | None = None
    lon: float
    lat: float
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("lat")
    @classmethod
    def _lat(cls, v: float) -> float:
        if not -34.5 <= v <= 5.9:
            raise ValueError("latitude fora do território brasileiro")
        return v

    @field_validator("lon")
    @classmethod
    def _lon(cls, v: float) -> float:
        if not -74.5 <= v <= -28.0:
            raise ValueError("longitude fora do território brasileiro")
        return v


def _base_query(
    q: str | None, category: list[str] | None, modal: list[str] | None, uf: list[str] | None,
    record_class: list[str] | None, bbox: str | None, municipality: int | None, has_capacity: bool | None,
    within: str | None = None,
) -> Any:
    stmt = select(Facility, DataSource.key, DataSource.name, func.ST_X(Facility.geom), func.ST_Y(Facility.geom)).outerjoin(
        DataSource, DataSource.id == Facility.source_id
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            Facility.name.ilike(like) | Facility.municipality_name.ilike(like) | Facility.operator.ilike(like)
            | Facility.uf.ilike(q.strip())
        )
    if category:
        stmt = stmt.where(Facility.category.in_(category))
    if modal:
        stmt = stmt.where(Facility.modal.in_(modal))
    if uf:
        stmt = stmt.where(Facility.uf.in_([u.upper() for u in uf]))
    if record_class:
        stmt = stmt.where(Facility.record_class.in_(record_class))
    if municipality:
        stmt = stmt.where(Facility.municipality_code == municipality)
    if has_capacity is not None:
        stmt = stmt.where(Facility.capacity_value.is_not(None) if has_capacity else Facility.capacity_value.is_(None))
    b = parse_bbox(bbox)
    if b:
        stmt = stmt.where(func.ST_Intersects(Facility.geom, func.ST_MakeEnvelope(*b, 4326)))
    if within:
        try:
            geom = shape(json.loads(within))
        except Exception as exc:
            raise HTTPException(400, "Geometria 'within' inválida (GeoJSON)") from exc
        stmt = stmt.where(func.ST_Intersects(Facility.geom, func.ST_GeomFromText(geom.wkt, 4326)))
    return stmt


def _out(row: Any) -> FacilityOut:
    f: Facility = row[0]
    return FacilityOut(
        id=f.id, external_id=f.external_id, record_class=f.record_class, name=f.name, category=f.category,
        category_label=CATEGORY_LABELS.get(f.category, f.category), subcategory=f.subcategory, modal=f.modal,
        operator=f.operator, capacity_value=f.capacity_value, capacity_unit=f.capacity_unit, status=f.status,
        address=f.address, municipality_code=f.municipality_code, municipality_name=f.municipality_name, uf=f.uf,
        lon=row[3], lat=row[4], reliability=f.reliability, limitations=f.limitations, source_key=row[1],
        source_name=row[2], source_reference=f.source_reference, attributes=f.attributes or {}, updated_at=f.updated_at,
    )


Multi = Annotated[list[str] | None, Query()]


@router.get("", response_model=Page[FacilityOut])
def list_facilities(
    db: DB, pg: PageParams, q: str | None = None, category: Multi = None, modal: Multi = None, uf: Multi = None,
    record_class: Multi = None, bbox: str | None = None, municipality: int | None = None,
    has_capacity: bool | None = None, sort: str = "name", order: Literal["asc", "desc"] = "asc",
) -> Page[FacilityOut]:
    stmt = _base_query(q, category, modal, uf, record_class, bbox, municipality, has_capacity)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    col = SORTS.get(sort, Facility.name)
    stmt = stmt.order_by(col.desc().nulls_last() if order == "desc" else col.asc().nulls_last(), Facility.id)
    page, size = pg
    rows = db.execute(stmt.offset((page - 1) * size).limit(size)).all()
    return Page(items=[_out(r) for r in rows], total=total, page=page, page_size=size)


@router.get("/geojson")
def facilities_geojson(
    db: DB, q: str | None = None, category: Multi = None, modal: Multi = None, uf: Multi = None,
    record_class: Multi = None, bbox: str | None = None, has_capacity: bool | None = None,
) -> dict[str, Any]:
    """Camada de pontos para o mapa (propriedades enxutas; detalhes via /facilities/{id})."""
    stmt = _base_query(q, category, modal, uf, record_class, bbox, None, has_capacity)
    rows = db.execute(stmt.limit(20000)).all()
    feats = [{
        "type": "Feature", "id": r[0].id,
        "geometry": {"type": "Point", "coordinates": [round(r[3], 5), round(r[4], 5)]},
        "properties": {"id": r[0].id, "name": r[0].name, "category": r[0].category, "modal": r[0].modal,
                       "uf": r[0].uf, "record_class": r[0].record_class, "capacity": r[0].capacity_value},
    } for r in rows]
    return {"type": "FeatureCollection", "features": feats}


@router.get("/facets")
def facets(db: DB, uf: Multi = None, category: Multi = None) -> dict[str, Any]:
    def count(col: Any, extra: Any = None) -> list[dict[str, Any]]:
        stmt = select(col, func.count()).group_by(col).order_by(func.count().desc())
        if uf:
            stmt = stmt.where(Facility.uf.in_(uf))
        if category and col is not Facility.category:
            stmt = stmt.where(Facility.category.in_(category))
        return [{"value": v, "count": c, "label": CATEGORY_LABELS.get(v, v) if col is Facility.category else v}
                for v, c in db.execute(stmt) if v is not None]

    return {"category": count(Facility.category), "modal": count(Facility.modal), "uf": count(Facility.uf),
            "record_class": count(Facility.record_class), "reliability": count(Facility.reliability)}


@router.get("/{facility_id}")
def get_facility(db: DB, facility_id: int) -> dict[str, Any]:
    row = db.execute(_base_query(None, None, None, None, None, None, None, None).where(Facility.id == facility_id)).first()
    if row is None:
        raise HTTPException(404, "Instalação não encontrada")
    out = _out(row).model_dump()
    src = db.get(DataSource, row[0].source_id) if row[0].source_id else None
    out["source"] = None if src is None else {
        "key": src.key, "name": src.name, "publisher": src.publisher, "url": src.url, "license": src.license,
        "attribution": src.attribution, "reference_date": src.reference_date, "limitations": src.limitations,
    }
    out["import_run_id"] = row[0].import_run_id
    near = db.execute(text(
        """SELECT m.code, m.name, m.uf, m.population, ST_Distance(m.centroid::geography, f.geom::geography)/1000 AS km
           FROM facility f JOIN municipality m ON ST_DWithin(m.centroid::geography, f.geom::geography, 100000)
           WHERE f.id=:id ORDER BY km LIMIT 1"""), {"id": facility_id}).first()
    out["nearest_municipality"] = None if near is None else {"code": near.code, "name": near.name, "uf": near.uf,
                                                             "population": near.population, "straight_km": round(near.km, 2)}
    out["editable"] = row[0].record_class == "user"
    return out


@router.get("/{facility_id}/reach")
def facility_reach(db: DB, facility_id: int, hours: float = Query(8, gt=0, le=72), mode: Literal["road", "multimodal"] = "road") -> dict[str, Any]:
    """Municípios alcançáveis pela rede em até N horas (tempo estimado sob as premissas vigentes)."""

    from app.core.assumptions import load_assumptions

    g = graph_or_404(db)
    node = g.facility_node(facility_id)
    a = load_assumptions(db)
    dist = g.sssp(node, "time", a, mode, limit=hours)
    mun = g.node_of_kind("municipality")
    reach = mun[dist[mun] <= hours]
    codes = [int(g.node_ref[n]) for n in reach]
    pop = db.scalar(text("SELECT coalesce(sum(population),0) FROM municipality WHERE code = ANY(:c)"), {"c": codes}) or 0
    return {"facility_id": facility_id, "hours": hours, "mode": mode, "municipalities": len(codes), "population": int(pop),
            "codes": codes, "times_h": {int(g.node_ref[n]): round(float(dist[n]), 2) for n in reach},
            "note": "Tempo de viagem estimado a partir de velocidades-premissa por tipo de via; não considera congestionamento."}


@router.get("/{facility_id}/distances")
def facility_distances(db: DB, facility_id: int, municipality: Annotated[list[int], Query()]) -> list[dict[str, Any]]:
    """Distância em linha reta x distância na rede entre a instalação e municípios."""
    from app.core.assumptions import load_assumptions

    g = graph_or_404(db)
    a = load_assumptions(db)
    src = g.facility_node(facility_id)
    out = []
    for code in municipality[:50]:
        try:
            dst = g.municipality_node(code)
        except KeyError:
            out.append({"municipality": code, "connected": False})
            continue
        p = g.shortest_path(src, dst, "time", a, "road")
        straight = haversine_km(g.node_lon[src], g.node_lat[src], g.node_lon[dst], g.node_lat[dst])
        out.append({"municipality": code, "connected": p is not None, "straight_km": round(straight, 1),
                    **(p.as_dict() if p else {})})
    return out


def _user_record(db: Session, body: FacilityIn) -> dict[str, Any]:
    src = ensure_sources(db)["logitrace_user"]
    pt = Point(body.lon, body.lat)
    mun = db.execute(text("SELECT code, name, uf FROM municipality WHERE ST_Contains(geom, ST_SetSRID(ST_Point(:x,:y),4326)) LIMIT 1"),
                     {"x": body.lon, "y": body.lat}).first()
    rec = {
        **body.model_dump(exclude={"lon", "lat"}), "record_class": "user", "source_id": src.id,
        "municipality_code": mun.code if mun else None, "municipality_name": mun.name if mun else None,
        "uf": mun.uf if mun else None, "reliability": "baixa", "limitations": "Cadastro do usuário; não validado por fonte oficial.",
        "source_reference": datetime.now().strftime("%Y-%m-%d"),
    }
    rec["content_hash"] = content_hash(rec, pt)
    rec["geom"] = from_shape(pt, srid=4326)
    return rec


@router.post("", status_code=201)
def create_facility(db: DB, body: FacilityIn) -> dict[str, Any]:
    rec = _user_record(db, body)
    rec["external_id"] = f"user:{datetime.now().timestamp():.6f}"
    f = Facility(**rec)
    db.add(f)
    db.commit()
    return {"id": f.id, "note": "Instalações novas entram no grafo após `build-network` (nova versão de rede)."}


@router.patch("/{facility_id}")
def update_facility(db: DB, facility_id: int, body: FacilityIn) -> dict[str, Any]:
    f = db.get(Facility, facility_id)
    if f is None:
        raise HTTPException(404, "Instalação não encontrada")
    if f.record_class != "user":
        raise HTTPException(403, "Registros oficiais importados são somente leitura")
    for k, v in _user_record(db, body).items():
        setattr(f, k, v)
    db.commit()
    return {"id": f.id}


@router.delete("/{facility_id}", status_code=204)
def delete_facility(db: DB, facility_id: int) -> None:
    f = db.get(Facility, facility_id)
    if f is None:
        raise HTTPException(404, "Instalação não encontrada")
    if f.record_class != "user":
        raise HTTPException(403, "Registros oficiais importados são somente leitura")
    db.delete(f)
    db.commit()


@router.post("/import")
async def import_user_facilities(db: DB, file: UploadFile = File(...), dry_run: bool = False) -> dict[str, Any]:
    """Importa instalações do usuário de CSV (colunas name, lon, lat, ...) ou GeoJSON (pontos), com validação."""
    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "Arquivo acima de 10 MB")
    report = ValidationReport()
    rows: list[dict[str, Any]] = []
    name = (file.filename or "").lower()
    try:
        if name.endswith((".geojson", ".json")):
            gj = json.loads(raw)
            for i, ft in enumerate(gj.get("features", [])):
                geom = ft.get("geometry") or {}
                if geom.get("type") != "Point":
                    report.reject(i, "geometria não é Point")
                    continue
                props = ft.get("properties") or {}
                rows.append({**props, "lon": geom["coordinates"][0], "lat": geom["coordinates"][1], "_ref": i})
        elif name.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(raw), sep=None, engine="python", encoding_errors="replace")
            df.columns = [c.strip().lower() for c in df.columns]
            for i, r in df.iterrows():
                rows.append({**{k: (None if pd.isna(v) else v) for k, v in r.items()}, "_ref": int(i) + 2})
        else:
            raise HTTPException(415, "Formato não suportado: use .csv ou .geojson")
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, f"Arquivo ilegível: {exc}") from exc
    seen: set[tuple[str, float, float]] = set()
    valid: list[FacilityIn] = []
    for r in rows:
        ref = r.pop("_ref")
        try:
            lon, lat = float(r.get("lon") or r.get("longitude")), float(r.get("lat") or r.get("latitude"))
        except (TypeError, ValueError):
            report.reject(ref, "lon/lat ausente ou não numérico")
            continue
        if not in_brazil(lon, lat):
            report.reject(ref, "coordenada fora do Brasil")
            continue
        if not r.get("name"):
            report.reject(ref, "campo obrigatório 'name' ausente")
            continue
        key = (str(r["name"]).strip().lower(), round(lon, 4), round(lat, 4))
        if key in seen:
            report.duplicates += 1
            report.warn(ref, "duplicado no arquivo (mesmo nome e coordenada)")
            continue
        seen.add(key)
        try:
            valid.append(FacilityIn(
                name=fix_text(r["name"]) or "", category=r.get("category") or "centro_distribuicao",
                modal=r.get("modal") or "rodoviario", operator=r.get("operator"),
                capacity_value=float(r["capacity_value"]) if r.get("capacity_value") not in (None, "") else None,
                capacity_unit=r.get("capacity_unit"), status=r.get("status"), address=r.get("address"), lon=lon, lat=lat,
            ))
        except Exception as exc:
            report.reject(ref, f"registro inválido: {exc}")
    created = 0
    if not dry_run:
        for i, body in enumerate(valid):
            rec = _user_record(db, body)
            rec["external_id"] = f"user-import:{file.filename}:{i}:{rec['content_hash'][:12]}"
            exists = db.scalar(select(Facility.id).where(Facility.content_hash == rec["content_hash"], Facility.record_class == "user"))
            if exists:
                report.duplicates += 1
                continue
            db.add(Facility(**rec))
            created += 1
        db.commit()
    return {"file": file.filename, "rows": len(rows), "valid": len(valid), "created": created, "dry_run": dry_run,
            **report.as_dict()}
