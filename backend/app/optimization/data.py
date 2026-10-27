"""Montagem dos pontos de demanda e dos candidatos para os modelos de localização/alocação."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.network.engine import Metric, ModalMode, NetworkGraph

DemandLevel = Literal["municipality", "immediate_region", "intermediate_region", "state"]


class DemandSpec(BaseModel):
    level: DemandLevel = "immediate_region"
    ufs: list[str] | None = None
    per_capita_t: float | None = Field(default=None, gt=0, description="t/hab·ano; padrão = premissa")
    global_factor: float = Field(default=1.0, gt=0)
    uf_factors: dict[str, float] = Field(default_factory=dict)
    min_population: int = 0


class CandidateSpec(BaseModel):
    type: Literal["facilities", "municipalities"] = "municipalities"
    categories: list[str] | None = None
    facility_ids: list[int] | None = None
    ufs: list[str] | None = None
    top_n_by_population: int | None = Field(default=60, ge=1, le=400)
    min_population: int = 0
    default_capacity_t: float = Field(default=2_000_000, gt=0, description="t/ano")
    fixed_cost_brl: float = Field(default=5_000_000, ge=0)
    max_candidates: int = Field(default=300, ge=1, le=600)


@dataclass
class DemandPoint:
    key: str
    name: str
    uf: str
    node: int
    lon: float
    lat: float
    population: int
    demand_t: float
    municipalities: int


@dataclass
class Candidate:
    key: str
    name: str
    uf: str | None
    node: int
    lon: float
    lat: float
    capacity_t: float
    fixed_cost: float
    facility_id: int | None = None
    municipality_code: int | None = None
    capacity_source: str = "premissa"


@dataclass
class ProblemData:
    demand: list[DemandPoint]
    candidates: list[Candidate]
    cost: np.ndarray  # candidatos x demanda, na métrica escolhida (por t)
    km: np.ndarray  # candidatos x demanda, distância na rede (km)
    excluded_demand: list[dict[str, Any]] = field(default_factory=list)
    metric: Metric = "cost"
    notes: list[str] = field(default_factory=list)


def build_demand(db: Session, g: NetworkGraph, spec: DemandSpec, per_capita_default: float) -> tuple[list[DemandPoint], list[dict[str, Any]]]:
    pc = spec.per_capita_t or per_capita_default
    where = ["population IS NOT NULL", "population >= :minpop"]
    params: dict[str, Any] = {"minpop": spec.min_population}
    if spec.ufs:
        where.append("uf = ANY(:ufs)")
        params["ufs"] = spec.ufs
    rows = db.execute(
        text(
            f"SELECT code, name, uf, population, immediate_region_code, immediate_region_name, "
            f"intermediate_region_code, intermediate_region_name, state_code, ST_X(centroid), ST_Y(centroid) "
            f"FROM municipality WHERE {' AND '.join(where)} ORDER BY code"
        ),
        params,
    ).all()
    groups: dict[str, list[Any]] = {}
    labels: dict[str, tuple[str, str]] = {}
    for r in rows:
        if spec.level == "municipality":
            key, label = f"mun:{r.code}", f"{r.name}/{r.uf}"
        elif spec.level == "immediate_region":
            key, label = f"rgi:{r.immediate_region_code}", f"RGI {r.immediate_region_name}"
        elif spec.level == "intermediate_region":
            key, label = f"rgint:{r.intermediate_region_code}", f"RGInt {r.intermediate_region_name}"
        else:
            key, label = f"uf:{r.uf}", r.uf
        groups.setdefault(key, []).append(r)
        labels[key] = (label, r.uf)
    main = _main_component(g)
    out: list[DemandPoint] = []
    excluded: list[dict[str, Any]] = []
    for key, members in groups.items():
        members.sort(key=lambda r: -(r.population or 0))
        rep = next((m for m in members if m.code in g._mun_node and main[g._mun_node[m.code]]), None)
        pop = int(sum(m.population for m in members))
        factor = spec.global_factor * spec.uf_factors.get(labels[key][1], 1.0)
        if rep is None:
            excluded.append({"key": key, "name": labels[key][0], "population": pop, "reason": "sem acesso à rede principal"})
            continue
        out.append(DemandPoint(
            key=key, name=labels[key][0], uf=labels[key][1], node=g._mun_node[rep.code],
            lon=float(rep[9]), lat=float(rep[10]), population=pop, demand_t=pop * pc * factor,
            municipalities=len(members),
        ))
    return out, excluded


def build_candidates(db: Session, g: NetworkGraph, spec: CandidateSpec, turnover: float = 1.0) -> list[Candidate]:
    """Capacidades em t/ano. Capacidade estática da fonte é convertida por `turnover` (giros/ano)."""
    main = _main_component(g)
    out: list[Candidate] = []
    if spec.type == "facilities":
        where = ["record_class IN ('official','user')"]
        params: dict[str, Any] = {}
        if spec.facility_ids:
            where.append("id = ANY(:ids)")
            params["ids"] = spec.facility_ids
        if spec.categories:
            where.append("category = ANY(:cats)")
            params["cats"] = spec.categories
        if spec.ufs:
            where.append("uf = ANY(:ufs)")
            params["ufs"] = spec.ufs
        rows = db.execute(
            text(f"SELECT id, name, uf, capacity_value, capacity_unit, ST_X(geom), ST_Y(geom) FROM facility "
                 f"WHERE {' AND '.join(where)} ORDER BY coalesce(capacity_value,0) DESC, id LIMIT :lim"),
            {**params, "lim": spec.max_candidates},
        ).all()
        for r in rows:
            node = g._fac_node.get(r.id)
            if node is None or not main[node]:
                continue
            has_cap = r.capacity_value is not None and (r.capacity_unit or "").startswith("t")
            out.append(Candidate(
                key=f"fac:{r.id}", name=r.name, uf=r.uf, node=node, lon=r[5], lat=r[6],
                capacity_t=float(r.capacity_value) * turnover if has_cap else spec.default_capacity_t,
                fixed_cost=spec.fixed_cost_brl, facility_id=r.id,
                capacity_source=f"fonte: estática × {turnover:g} giros/ano" if has_cap else "premissa",
            ))
    else:
        where = ["population >= :minpop"]
        params = {"minpop": spec.min_population}
        if spec.ufs:
            where.append("uf = ANY(:ufs)")
            params["ufs"] = spec.ufs
        rows = db.execute(
            text(f"SELECT code, name, uf, ST_X(centroid), ST_Y(centroid) FROM municipality WHERE {' AND '.join(where)} "
                 f"ORDER BY population DESC NULLS LAST LIMIT :lim"),
            {**params, "lim": min(spec.top_n_by_population or spec.max_candidates, spec.max_candidates)},
        ).all()
        for r in rows:
            node = g._mun_node.get(r.code)
            if node is None or not main[node]:
                continue
            out.append(Candidate(
                key=f"mun:{r.code}", name=f"{r.name}/{r.uf}", uf=r.uf, node=node, lon=r[3], lat=r[4],
                capacity_t=spec.default_capacity_t, fixed_cost=spec.fixed_cost_brl, municipality_code=r.code,
            ))
    return out


def _main_component(g: NetworkGraph) -> np.ndarray:
    labels = g.components("multimodal")
    mun = g.node_of_kind("municipality")
    big = np.bincount(labels[mun]).argmax()
    return labels == big


def build_problem(
    db: Session, g: NetworkGraph, demand: list[DemandPoint], candidates: list[Candidate],
    metric: Metric, mode: ModalMode, assumptions: dict[str, float], closed: set[int] | None = None,
) -> ProblemData:
    if not candidates:
        raise ValueError("Nenhum candidato válido (verifique filtros e conexão à rede)")
    if not demand:
        raise ValueError("Nenhum ponto de demanda válido")
    src = [c.node for c in candidates]
    dn = np.array([d.node for d in demand])
    cost = g.distance_matrix(src, metric, assumptions, mode, closed)[:, dn]
    km = cost if metric == "distance" else g.distance_matrix(src, "distance", assumptions, mode, closed)[:, dn]
    return ProblemData(demand=demand, candidates=candidates, cost=cost, km=km, metric=metric)
