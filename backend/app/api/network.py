"""Motor de redes: rotas, alternativas, conectividade, pontes, criticidade e alcance."""

from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from app import jobs
from app.api.common import DB, graph_or_404, jsonable
from app.core.assumptions import load_assumptions
from app.db.session import SessionLocal
from app.network import analysis
from app.network.engine import METRIC_UNITS, Metric, ModalMode, haversine_km
from app.scenarios.engine import Endpoint, _resolve_endpoint

router = APIRouter(prefix="/network", tags=["rede"])


class RouteRequest(BaseModel):
    origin: Endpoint
    dest: Endpoint
    metric: Metric = "cost"
    mode: ModalMode = "road"
    alternatives: int = Field(default=3, ge=1, le=5)
    closed_segment_ids: list[int] = Field(default_factory=list)
    closed_edge_ids: list[int] = Field(default_factory=list)
    assumptions_override: dict[str, float] = Field(default_factory=dict)
    version_id: int | None = None


SNV_CODE = re.compile(r"^(\d{3})([BELDAC])([A-Z]{2})")


def road_label(code: str | None) -> str | None:
    """Converte o código SNV (ex.: 050BMG9150) na denominação usual (BR-050, SP-348, LMG-664)."""
    m = SNV_CODE.match(code or "")
    if not m:
        return None
    num, kind, uf = m.groups()
    if kind == "B":
        return f"BR-{num}"
    if kind == "L":
        return f"L{uf}-{num}"
    if kind == "D":
        return f"DF-{num}"
    if kind == "E":
        return f"{uf}-{num}"
    return None


def _route_payload(g: Any, p: Any, rank: int, base: Any | None) -> dict[str, Any]:
    codes: list[str] = []
    for e in p.edges:
        label = road_label(g.code[e]) if int(g.modal[e]) == 0 else None
        if label and (not codes or codes[-1] != label):
            codes.append(label)
    out = {"rank": rank, **p.as_dict(), "roads": codes[:40], "geojson": {"type": "FeatureCollection", "features": [g.path_feature(p.edges, {"rank": rank}, 0.001)]}, "edges": p.edges}
    if base is not None:
        overlap = len(set(p.edges) & set(base.edges)) / max(len(set(p.edges)), 1)
        out["overlap_with_best"] = round(overlap, 3)
        out["delta_vs_best"] = {"distance_km": round(p.distance_km - base.distance_km, 2),
                                "time_h": round(p.time_h - base.time_h, 2),
                                "cost_brl_t": round(p.cost_brl_t - base.cost_brl_t, 2)}
    return out


@router.post("/route")
def route(db: DB, body: RouteRequest) -> dict[str, Any]:
    g = graph_or_404(db, body.version_id)
    a = {**load_assumptions(db), **body.assumptions_override}
    o, on, osnap = _resolve_endpoint(db, g, body.origin)
    d, dn, dsnap = _resolve_endpoint(db, g, body.dest)
    closed = g.edges_for_segments(set(body.closed_segment_ids)) | set(body.closed_edge_ids)
    alts = g.alternatives(o, d, body.metric, a, k=body.alternatives, mode=body.mode, closed=closed or None)
    straight = haversine_km(g.node_lon[o], g.node_lat[o], g.node_lon[d], g.node_lat[d])
    if not alts:
        return {"connected": False, "origin": on, "dest": dn, "straight_km": round(straight, 1), "routes": [],
                "message": "Origem e destino em componentes desconectados da rede (sob as restrições informadas)."}
    best = alts[0]
    return {
        "connected": True, "origin": on, "dest": dn, "metric": body.metric, "metric_unit": METRIC_UNITS[body.metric],
        "mode": body.mode, "network_version_id": g.version_id, "straight_km": round(straight, 1),
        "detour_index": round(best.distance_km / straight, 3) if straight > 0 else None,
        "snap_km": round(osnap + dsnap, 2), "closed_edges": len(closed),
        "routes": [_route_payload(g, p, i, best if i else None) for i, p in enumerate(alts)],
        "assumptions_used": {k: v for k, v in a.items() if k.startswith(("speed.", "cost.", "time."))},
        "notes": [
            "Distância em linha reta exibida apenas para comparação; as rotas usam a malha da base IBGE 2014.",
            "Alternativas pelo método de penalização: cada rota encontrada torna suas arestas 60% mais caras na busca seguinte.",
            "Tempo e custo derivam de premissas paramétricas (ver /api/assumptions), não de observação.",
        ],
    }


class CompareRequest(BaseModel):
    pairs: list[dict[str, Endpoint]] = Field(min_length=1, max_length=50)
    metric: Metric = "cost"
    mode: ModalMode = "road"


@router.post("/compare")
def compare_routes(db: DB, body: CompareRequest) -> list[dict[str, Any]]:
    g = graph_or_404(db)
    a = load_assumptions(db)
    out = []
    for pair in body.pairs:
        o, on, _ = _resolve_endpoint(db, g, pair["origin"])
        d, dn, _ = _resolve_endpoint(db, g, pair["dest"])
        row: dict[str, Any] = {"origin": on, "dest": dn}
        for mode in ("road", "multimodal"):
            p = g.shortest_path(o, d, body.metric, a, mode)  # type: ignore[arg-type]
            row[mode] = p.as_dict() if p else None
        row["straight_km"] = round(haversine_km(g.node_lon[o], g.node_lat[o], g.node_lon[d], g.node_lat[d]), 1)
        out.append(row)
    return out


@router.get("/stats")
def stats(db: DB) -> dict[str, Any]:
    g = graph_or_404(db)
    v = db.execute(text("SELECT label, stats, created_at, checksum, assumptions FROM network_version WHERE id=:v"), {"v": g.version_id}).first()
    assert v is not None
    return {"version_id": g.version_id, "label": v.label, "created_at": v.created_at, "checksum": v.checksum,
            "nodes": g.n_nodes, "edges": g.n_edges, **(v.stats or {})}


@router.get("/connectivity")
def connectivity(db: DB, mode: ModalMode = "road") -> dict[str, Any]:
    g = graph_or_404(db)
    return analysis.connectivity(db, g, mode)


@router.get("/bridges")
def bridges(db: DB, mode: ModalMode = "road", top: int = Query(40, le=200)) -> dict[str, Any]:
    g = graph_or_404(db)
    items = analysis.bridges(db, g, mode, top)
    return {"mode": mode, "method": "Pontes (NetworkX) agregadas em árvore de componentes 2-aresta-conexos; "
                                     "população isolada = municípios do lado separado da rede principal.",
            "items": items}


@router.get("/articulation-points")
def articulation(db: DB, mode: ModalMode = "road") -> list[dict[str, Any]]:
    return analysis.articulation_points(db, graph_or_404(db), mode)


class CriticalityRequest(BaseModel):
    metric: Metric = "cost"
    mode: ModalMode = "road"
    top_k: int = Field(default=15, ge=1, le=40)
    municipality_codes: list[int] | None = Field(default=None, description="conjunto OD; padrão = capitais")


@router.post("/criticality")
def criticality(db: DB, body: CriticalityRequest) -> dict[str, Any]:
    g = graph_or_404(db)
    vid = g.version_id

    def work(ctx: jobs.JobContext) -> tuple[str, int]:
        from app.models import Job

        with SessionLocal() as s:
            gg = graph_or_404(s, vid)
            res = analysis.criticality(s, gg, load_assumptions(s), body.metric, body.mode, body.top_k, body.municipality_codes)
            j = s.get(Job, ctx.job_id)
            assert j is not None
            j.params = {**body.model_dump(), "result": jsonable(res)}
            s.commit()
        return ("job", ctx.job_id)

    job_id = jobs.submit("criticality", work, body.model_dump())
    return {"job_id": job_id}


@router.get("/criticality/{job_id}")
def criticality_result(db: DB, job_id: int) -> dict[str, Any]:
    from app.models import Job

    j = db.get(Job, job_id)
    if j is None or j.kind != "criticality":
        raise HTTPException(404, "Análise não encontrada")
    if j.status != "success":
        return {"status": j.status, "error": j.error}
    res = j.params.get("result", {})
    g = graph_or_404(db)
    for e in res.get("edges", []):
        e["geometry"] = {"type": "LineString", "coordinates": g.geometry[e["edge"]]}
    return {"status": "success", **res}


@router.get("/reach")
def reach(db: DB, lon: float, lat: float, hours: float = Query(6, gt=0, le=48), mode: ModalMode = "road") -> dict[str, Any]:
    g = graph_or_404(db)
    a = load_assumptions(db)
    node, snap = g.nearest_road_node(lon, lat)
    dist = g.sssp(node, "time", a, mode, limit=hours)
    mun = g.node_of_kind("municipality")
    sel = mun[dist[mun] <= hours]
    codes = [int(g.node_ref[n]) for n in sel]
    pop = db.scalar(text("SELECT coalesce(sum(population),0) FROM municipality WHERE code = ANY(:c)"), {"c": codes}) or 0
    return {"hours": hours, "snap_km": round(snap, 2), "municipalities": len(codes), "population": int(pop),
            "times_h": {int(g.node_ref[n]): round(float(dist[n]), 2) for n in sel},
            "note": "Tempo estimado por velocidades-premissa; ponto de partida ligado ao nó rodoviário mais próximo."}


@router.get("/segments/{segment_id}")
def segment(db: DB, segment_id: int) -> dict[str, Any]:
    r = db.execute(text(
        """SELECT s.id, s.external_id, s.modal, s.code, s.name, s.jurisdiction, s.surface, s.situation, s.uf, s.length_km,
                  s.attributes, d.name AS source, d.reference_date, d.limitations, ST_AsGeoJSON(s.geom, 5)::json AS geometry
           FROM infra_segment s LEFT JOIN data_source d ON d.id=s.source_id WHERE s.id=:id"""), {"id": segment_id}).mappings().first()
    if r is None:
        raise HTTPException(404, "Segmento não encontrado")
    g = graph_or_404(db)
    edges = sorted(g.edges_for_segments({segment_id}))
    return {**dict(r), "network_edges": edges}


@router.get("/nearest")
def nearest(db: DB, lon: float, lat: float, kind: Literal["segment", "municipality"] = "segment") -> dict[str, Any]:
    if kind == "municipality":
        r = db.execute(text("SELECT code, name, uf FROM municipality WHERE ST_Contains(geom, ST_SetSRID(ST_Point(:x,:y),4326))"),
                       {"x": lon, "y": lat}).mappings().first()
        return dict(r) if r else {}
    r = db.execute(text(
        """SELECT id, modal, code, name, surface, ST_Distance(geom::geography, ST_SetSRID(ST_Point(:x,:y),4326)::geography)/1000 AS km
           FROM infra_segment WHERE modal IN ('road','rail','waterway')
           ORDER BY geom <-> ST_SetSRID(ST_Point(:x,:y),4326) LIMIT 1"""), {"x": lon, "y": lat}).mappings().first()
    return dict(r) if r else {}


@router.post("/build")
def build(db: DB) -> dict[str, Any]:
    """Constrói nova versão do grafo (ex.: após importar instalações do usuário)."""
    from app.core.config import get_settings

    if not get_settings().allow_network_build:
        raise HTTPException(409, "Construção da rede indisponível neste ambiente: rode `python -m app.cli build-network` "
                                 "na instalação completa e publique o banco.")
    from app.network.builder import build_network
    from app.network.engine import clear_cache

    def work(ctx: jobs.JobContext) -> tuple[str, int]:
        with SessionLocal() as s:
            v = build_network(s)
            s.commit()
            clear_cache()
            return ("network_version", v.id)

    return {"job_id": jobs.submit("build_network", work)}
