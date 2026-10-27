"""Fluxos de mercadorias: filtros, matrizes OD, concentração e fluxos hipotéticos do usuário."""

from __future__ import annotations

from typing import Annotated, Any, Literal

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.common import DB
from app.models import Flow

router = APIRouter(prefix="/flows", tags=["fluxos"])
Multi = Annotated[list[str] | None, Query()]

CLASS_LABELS = {
    "observed": "Observado em fonte real",
    "modeled": "Calculado por modelo",
    "hypothetical": "Hipotético (inserido pelo usuário)",
    "synthetic": "Sintético (demonstração)",
}


def _where(dataset: list[str] | None, flow_class: list[str] | None, modal: list[str] | None, uf: list[str] | None,
           product_group: list[str] | None, origin: str | None, dest: str | None, min_value: float | None,
           period: str | None, international: bool | None) -> tuple[str, dict[str, Any]]:
    w, p = ["TRUE"], {}
    if dataset:
        w.append("dataset = ANY(:ds)")
        p["ds"] = dataset
    if flow_class:
        w.append("flow_class = ANY(:fc)")
        p["fc"] = flow_class
    if modal:
        w.append("modal = ANY(:md)")
        p["md"] = modal
    if uf:
        w.append("(origin_uf = ANY(:uf) OR dest_uf = ANY(:uf))")
        p["uf"] = [u.upper() for u in uf]
    if product_group:
        w.append("product_group = ANY(:pg)")
        p["pg"] = product_group
    if origin:
        w.append("(origin_code = :o OR dest_code = :o)")
        p["o"] = origin
    if dest:
        w.append("(origin_code = :d OR dest_code = :d)")
        p["d"] = dest
    if min_value is not None:
        w.append("value >= :mv")
        p["mv"] = min_value
    if period:
        w.append("period = :per")
        p["per"] = period
    if international is not None:
        w.append("(origin_uf IS NULL OR dest_uf IS NULL)" if international else "(origin_uf IS NOT NULL AND dest_uf IS NOT NULL)")
    return " AND ".join(w), p


@router.get("/datasets")
def datasets(db: DB) -> list[dict[str, Any]]:
    rows = db.execute(text(
        """SELECT dataset, flow_class, modal, unit, period, count(*) AS links, sum(value) AS total,
                  max(notes) AS notes FROM flow GROUP BY dataset, flow_class, modal, unit, period ORDER BY dataset""")).mappings()
    return [{**dict(r), "class_label": CLASS_LABELS[r["flow_class"]]} for r in rows]


@router.get("/products")
def products(db: DB, dataset: str = "ibge_2024_aquaviario_cabotagem_interior") -> list[dict[str, Any]]:
    return [dict(r) for r in db.execute(text(
        "SELECT product_group, count(*) links, sum(value) total FROM flow WHERE dataset=:d AND product_group IS NOT NULL "
        "GROUP BY 1 ORDER BY total DESC"), {"d": dataset}).mappings()]


@router.get("")
def list_flows(
    db: DB, dataset: Multi = None, flow_class: Multi = None, modal: Multi = None, uf: Multi = None,
    product_group: Multi = None, origin: str | None = None, dest: str | None = None, min_value: float | None = None,
    period: str | None = None, international: bool | None = None, limit: int = Query(2000, ge=1, le=20000),
) -> dict[str, Any]:
    """Maiores ligações segundo os filtros. Unidades diferentes nunca são somadas entre si."""
    where, p = _where(dataset, flow_class, modal, uf, product_group, origin, dest, min_value, period, international)
    units = [r[0] for r in db.execute(text(f"SELECT DISTINCT unit FROM flow WHERE {where}"), p)]
    if len(units) > 1:
        raise HTTPException(400, f"Os filtros misturam unidades incompatíveis ({', '.join(units)}). Selecione um único conjunto.")
    agg = """SELECT flow_class, dataset, modal, unit, period, origin_code, max(origin_name) origin_name, max(origin_uf) origin_uf,
                    dest_code, max(dest_name) dest_name, max(dest_uf) dest_uf, avg(origin_lon) olon, avg(origin_lat) olat,
                    avg(dest_lon) dlon, avg(dest_lat) dlat, sum(value) AS value, count(*) AS records
             FROM flow WHERE {w}
             GROUP BY flow_class, dataset, modal, unit, period, origin_code, dest_code
             ORDER BY value DESC LIMIT :lim"""
    rows = db.execute(text(agg.format(w=where)), {**p, "lim": limit}).mappings().all()
    total = db.execute(text(f"SELECT count(*) n, coalesce(sum(value),0) v FROM flow WHERE {where}"), p).mappings().first()
    assert total is not None
    shown = sum(r["value"] for r in rows)
    return {
        "unit": units[0] if units else None, "total_links": total["n"], "total_value": float(total["v"]),
        "shown_links": len(rows), "shown_share": round(shown / float(total["v"]), 4) if total["v"] else None,
        "items": [{**dict(r), "class_label": CLASS_LABELS[r["flow_class"]]} for r in rows],
        "caveat": ("Cada linha liga origem e destino de forma esquemática. Ela não prova a existência de uma rota "
                   "comercial específica nem indica o trajeto físico percorrido."),
    }


@router.get("/matrix")
def od_matrix(db: DB, dataset: Annotated[list[str], Query()], level: Literal["uf", "region"] = "uf",
              product_group: Multi = None, flow_class: Multi = None) -> dict[str, Any]:
    where, p = _where(dataset, flow_class, None, None, product_group, None, None, None, None, False)
    units = [r[0] for r in db.execute(text(f"SELECT DISTINCT unit FROM flow WHERE {where}"), p)]
    if len(units) != 1:
        raise HTTPException(400, "Selecione conjuntos com uma única unidade")
    if level == "uf":
        o, d = "origin_uf", "dest_uf"
        join = ""
    else:
        o, d = "ro.abbrev", "rd.abbrev"
        join = "JOIN state so ON so.uf=f.origin_uf JOIN region ro ON ro.code=so.region_code JOIN state sd ON sd.uf=f.dest_uf JOIN region rd ON rd.code=sd.region_code"
    rows = db.execute(text(f"SELECT {o} o, {d} d, sum(value) v FROM flow f {join} WHERE {where} GROUP BY 1,2"), p).all()
    labels = sorted({r.o for r in rows} | {r.d for r in rows})
    idx = {k: i for i, k in enumerate(labels)}
    m = np.zeros((len(labels), len(labels)))
    for r in rows:
        m[idx[r.o], idx[r.d]] += r.v
    sym = m + m.T - np.diag(np.diag(m))  # ligações são bidirecionais: matriz simétrica
    total = float(np.triu(sym).sum())
    intra = float(np.trace(sym))
    shares = np.triu(sym).flatten() / total if total else np.zeros(1)
    return {
        "unit": units[0], "labels": labels, "matrix": np.round(sym, 2).tolist(), "total": total,
        "intra_share": round(intra / total, 4) if total else None,
        "hhi_pairs": round(float((shares ** 2).sum() * 10000), 1),
        "top_pairs": sorted(({"a": labels[i], "b": labels[j], "value": float(sym[i, j])}
                             for i in range(len(labels)) for j in range(i, len(labels)) if sym[i, j] > 0),
                            key=lambda x: -x["value"])[:15],
        "note": "Matriz simétrica: as ligações do IBGE são bidirecionais e não distinguem sentido.",
    }


@router.get("/concentration")
def concentration(db: DB, dataset: Annotated[list[str], Query()], by: Literal["municipality", "uf"] = "municipality",
                  top: int = Query(20, le=100)) -> dict[str, Any]:
    where, p = _where(dataset, None, None, None, None, None, None, None, None, None)
    col_o, col_d = ("origin_code", "dest_code") if by == "municipality" else ("origin_uf", "dest_uf")
    name_o, name_d = ("origin_name", "dest_name") if by == "municipality" else ("origin_uf", "dest_uf")
    rows = db.execute(text(
        f"""SELECT k, max(n) AS name, sum(v) AS v FROM (
              SELECT {col_o} k, {name_o} n, value v FROM flow WHERE {where}
              UNION ALL SELECT {col_d}, {name_d}, value FROM flow WHERE {where}) t
            WHERE k IS NOT NULL GROUP BY k ORDER BY v DESC"""), p).all()
    v = np.array([r.v for r in rows], dtype=float)
    s = v / v.sum() if v.sum() else v
    return {"by": by, "units": len(v), "hhi": round(float((s ** 2).sum() * 10000), 1),
            "top5_share": round(float(s[:5].sum()), 4), "top10_share": round(float(s[:10].sum()), 4),
            "top": [{"key": r.k, "name": r.name, "value": float(r.v), "share": round(float(r.v / v.sum()), 5)} for r in rows[:top]],
            "definition": "Movimento associado = soma das ligações em que a unidade é ponta (cada ligação conta para as duas pontas)."}


class HypotheticalFlow(BaseModel):
    origin_code: str
    dest_code: str
    value: float = Field(gt=0)
    unit: str = "t/ano"
    modal: Literal["rodoviario", "ferroviario", "aquaviario", "aereo", "multimodal"] = "rodoviario"
    product_group: str | None = None
    notes: str | None = None


@router.post("/hypothetical", status_code=201)
def add_hypothetical(db: DB, body: HypotheticalFlow) -> dict[str, Any]:
    pts = {r.code: r for r in db.execute(text(
        "SELECT code::text code, name || '/' || uf AS name, uf, ST_X(centroid) x, ST_Y(centroid) y FROM municipality "
        "WHERE code::text = ANY(:c)"), {"c": [body.origin_code, body.dest_code]})}
    if body.origin_code not in pts or body.dest_code not in pts:
        raise HTTPException(400, "Use códigos IBGE de municípios válidos para origem e destino")
    o, d = pts[body.origin_code], pts[body.dest_code]
    f = Flow(flow_class="hypothetical", dataset="usuario_hipotetico", modal=body.modal, direction="origin_to_dest",
             origin_code=o.code, origin_name=o.name, origin_uf=o.uf, dest_code=d.code, dest_name=d.name, dest_uf=d.uf,
             origin_lon=o.x, origin_lat=o.y, dest_lon=d.x, dest_lat=d.y, product_group=body.product_group,
             period=None, value=body.value, unit=body.unit, notes=body.notes, attributes={})
    db.add(f)
    db.commit()
    return {"id": f.id, "flow_class": "hypothetical"}


@router.delete("/hypothetical/{flow_id}", status_code=204)
def delete_hypothetical(db: DB, flow_id: int) -> None:
    f = db.get(Flow, flow_id)
    if f is None or f.flow_class != "hypothetical":
        raise HTTPException(404, "Fluxo hipotético não encontrado (fluxos observados não podem ser removidos)")
    db.delete(f)
    db.commit()
