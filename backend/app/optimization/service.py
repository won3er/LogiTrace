"""Orquestração das otimizações: monta dados, resolve, registra execução e premissas."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.core.assumptions import load_assumptions
from app.core.config import get_settings
from app.db.base import utcnow
from app.models import OptimizationRun
from app.network.versions import latest_version_id
from app.network.engine import Metric, ModalMode, NetworkGraph, get_graph
from app.optimization.data import (
    CandidateSpec,
    DemandSpec,
    ProblemData,
    build_candidates,
    build_demand,
    build_problem,
)
from app.optimization.solvers import Solution, capacitated, max_coverage, p_median, transportation, vrp

Problem = Literal["p_median", "capacitated_location", "max_coverage", "transportation", "pareto", "vrp"]


class VRPSpec(BaseModel):
    depot_municipality: int | None = None
    depot_facility_id: int | None = None
    customers: list[int] = Field(default_factory=list, description="códigos IBGE dos municípios clientes")
    demand_t: dict[str, float] = Field(default_factory=dict, description="demanda por cliente (código -> t)")
    default_demand_t: float = 10.0
    vehicles: int = Field(default=3, ge=1, le=50)
    vehicle_capacity_t: float = Field(default=30.0, gt=0)
    max_route_km: float | None = None

    @model_validator(mode="after")
    def _check(self) -> VRPSpec:
        if not (self.depot_municipality or self.depot_facility_id):
            raise ValueError("Informe o depósito (município ou instalação)")
        if not 1 <= len(self.customers) <= 80:
            raise ValueError("Informe entre 1 e 80 clientes")
        return self


class OptimizationRequest(BaseModel):
    problem: Problem
    label: str | None = None
    network_version_id: int | None = None
    scenario_id: int | None = None
    metric: Metric = "cost"
    mode: ModalMode = "road"
    demand: DemandSpec = Field(default_factory=DemandSpec)
    candidates: CandidateSpec = Field(default_factory=CandidateSpec)
    p: int = Field(default=5, ge=1, le=100)
    max_open: int | None = Field(default=None, ge=1)
    coverage_km: float | None = Field(default=None, gt=0)
    unmet_penalty_brl_t: float = Field(default=1000.0, ge=0)
    single_sourcing: bool = False
    forced_open_keys: list[str] = Field(default_factory=list)
    open_keys: list[str] = Field(default_factory=list, description="instalações abertas (problema de transporte)")
    pareto_p_min: int = Field(default=1, ge=1)
    pareto_p_max: int = Field(default=8, ge=1, le=30)
    assumptions_override: dict[str, float] = Field(default_factory=dict)
    closed_segment_ids: list[int] = Field(default_factory=list)
    time_limit_s: float | None = Field(default=None, gt=0, le=600)
    vrp: VRPSpec | None = None


def input_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _sol_to_run(run: OptimizationRun, sol: Solution) -> None:
    run.solution_quality = sol.quality
    run.status = "success" if sol.quality not in ("NOT_SOLVED", "INFEASIBLE") else "no_solution"
    run.solver = sol.solver
    run.objective = sol.objective
    run.objective_value = sol.objective_value
    run.best_bound = sol.best_bound
    run.gap = sol.gap
    run.solve_time_ms = sol.solve_time_ms
    run.constraints = sol.constraints
    run.results = _jsonable(sol.results)


def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, list | tuple):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return _jsonable(o.tolist())
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating | float):
        f = float(o)
        return None if not np.isfinite(f) else f
    return o


def create_run(db: Session, req: OptimizationRequest) -> OptimizationRun:
    vid = req.network_version_id or latest_version_id(db)
    if vid is None:
        raise ValueError("Nenhuma versão de rede disponível. Execute `python -m app.cli build-network`.")
    a = {**load_assumptions(db), **req.assumptions_override}
    payload = {"request": req.model_dump(), "network_version_id": vid, "assumptions": a}
    run = OptimizationRun(
        problem=req.problem, label=req.label, network_version_id=vid, scenario_id=req.scenario_id,
        params=payload, input_hash=input_hash(payload), status="queued",
    )
    db.add(run)
    db.commit()
    return run


def execute_run(db: Session, run_id: int) -> OptimizationRun:
    run = db.get(OptimizationRun, run_id)
    if run is None:
        raise LookupError(run_id)
    req = OptimizationRequest.model_validate(run.params["request"])
    a: dict[str, float] = run.params["assumptions"]
    assert run.network_version_id is not None
    g = get_graph(db, run.network_version_id)
    tl = req.time_limit_s or get_settings().solver_time_limit_s
    run.status = "running"
    db.commit()
    closed = g.edges_for_segments(set(req.closed_segment_ids)) if req.closed_segment_ids else None
    notes: list[str] = []
    try:
        if req.problem == "vrp":
            sol = _run_vrp(db, g, req, a, closed, tl)
        else:
            demand, excluded = build_demand(db, g, req.demand, a["demand.per_capita_t_year"])
            cands = build_candidates(db, g, req.candidates, a["capacity.static_turnover_per_year"])
            pd_ = build_problem(db, g, demand, cands, req.metric, req.mode, a, closed)
            pd_.excluded_demand = excluded
            keys = {c.key: i for i, c in enumerate(cands)}
            forced = [keys[k] for k in req.forced_open_keys if k in keys]
            cov = req.coverage_km or a["coverage.default_km"]
            if req.problem == "p_median":
                sol = p_median(pd_, min(req.p, len(cands)), tl, cov, forced)
            elif req.problem == "capacitated_location":
                sol = capacitated(pd_, tl, req.max_open, req.unmet_penalty_brl_t, cov, forced, req.single_sourcing)
            elif req.problem == "max_coverage":
                sol = max_coverage(pd_, min(req.p, len(cands)), cov, tl, forced)
            elif req.problem == "transportation":
                open_idx = [keys[k] for k in req.open_keys if k in keys] or list(range(len(cands)))
                sol = transportation(pd_, open_idx, req.unmet_penalty_brl_t, cov)
            else:
                sol = _pareto(pd_, req, cov, tl)
            sol.results["inputs_summary"] = {
                "demand_points": len(demand), "candidates": len(cands), "metric": req.metric, "mode": req.mode,
                "demand_level": req.demand.level, "excluded_demand_points": len(excluded),
                "excluded_demand_population": sum(e["population"] for e in excluded),
            }
            notes = _standard_assumptions(req, a)
        _sol_to_run(run, sol)
        run.assumptions = notes + sol.assumptions
    except Exception as exc:
        run.status, run.solution_quality, run.error = "error", "ERROR", f"{type(exc).__name__}: {exc}"
        db.commit()
        raise
    run.finished_at = utcnow()
    db.commit()
    return run


def _standard_assumptions(req: OptimizationRequest, a: dict[str, float]) -> list[str]:
    unit = {"cost": "R$/t", "time": "h", "distance": "km"}[req.metric]
    out = [
        f"Demanda = população (Censo 2022) × {req.demand.per_capita_t or a['demand.per_capita_t_year']} t/hab·ano "
        f"× fator {req.demand.global_factor} (proxy de consumo, não medição)",
        f"Demanda agregada no nível '{req.demand.level}', representada pelo município mais populoso de cada grupo",
        f"Custo unitário = menor caminho na rede ({'somente rodoviária' if req.mode == 'road' else 'multimodal'}) na métrica '{req.metric}' ({unit})",
        "Cobertura medida pela menor distância na rede (km), não em linha reta",
    ]
    if req.metric == "cost":
        out.append(
            f"Custos por t·km: rodovia R$ {a['cost.road.brl_tkm']}, ferrovia R$ {a['cost.rail.brl_tkm']}, "
            f"hidrovia R$ {a['cost.waterway.brl_tkm']}; transbordo R$ {a['cost.transfer.brl_t']}/t (premissas)"
        )
    if req.candidates.type == "municipalities":
        out.append(f"Candidatos: municípios mais populosos; capacidade {req.candidates.default_capacity_t:,.0f} t e custo fixo "
                   f"R$ {req.candidates.fixed_cost_brl:,.0f} por instalação (premissas)")
    if req.closed_segment_ids:
        out.append(f"{len(req.closed_segment_ids)} segmentos interditados considerados")
    return out


def _pareto(pd_: ProblemData, req: OptimizationRequest, cov: float, tl: float) -> Solution:
    pts: list[dict[str, Any]] = []
    per = max(tl / max(2 * (req.pareto_p_max - req.pareto_p_min + 1), 1), 2.0)
    worst = "OPTIMAL"
    total_ms = 0.0
    for p in range(req.pareto_p_min, min(req.pareto_p_max, len(pd_.candidates)) + 1):
        for model, fn in (("p_median", lambda: p_median(pd_, p, per, cov)),
                          ("max_coverage", lambda: max_coverage(pd_, p, cov, per))):
            s = fn()
            total_ms += s.solve_time_ms
            if s.quality != "OPTIMAL":
                worst = s.quality if worst == "OPTIMAL" else worst
            if not s.results:
                continue
            k = s.results["kpis"]
            pts.append({"p": p, "model": model, "quality": s.quality,
                        "transport_cost": k["transport_cost"], "coverage_share": k["coverage_share"],
                        "weighted_avg_km": k["weighted_avg_km"],
                        "open": [f["key"] for f in s.results["open_facilities"]],
                        "open_names": [f["name"] for f in s.results["open_facilities"]]})
    # Dominância em três objetivos: menos instalações, menor custo, maior cobertura
    for q in pts:
        q["dominated"] = any(
            (o["p"] <= q["p"] and o["transport_cost"] <= q["transport_cost"] and o["coverage_share"] >= q["coverage_share"])
            and (o["p"] < q["p"] or o["transport_cost"] < q["transport_cost"] or o["coverage_share"] > q["coverage_share"])
            for o in pts
        )
    return Solution(
        problem="pareto", quality=worst, solver="SCIP (MIP) — série de p-mediana e máxima cobertura",
        objective=("Fronteira custo × cobertura: para cada p, minimiza custo (p-mediana) e maximiza cobertura "
                   "(MCLP); não há ponderação implícita entre os objetivos"),
        objective_value=None, best_bound=None, gap=None, solve_time_ms=total_ms,
        constraints=[f"p de {req.pareto_p_min} a {req.pareto_p_max}", f"Raio de cobertura {cov:g} km"],
        assumptions=["Pontos não dominados formam a fronteira eficiente; a escolha final depende do peso dado a cada objetivo"],
        results={"points": pts, "coverage_km": cov},
    )


def _run_vrp(db: Session, g: NetworkGraph, req: OptimizationRequest, a: dict[str, float],
             closed: set[int] | None, tl: float) -> Solution:
    from sqlalchemy import text

    assert req.vrp is not None
    v = req.vrp
    depot = g.facility_node(v.depot_facility_id) if v.depot_facility_id else g.municipality_node(int(v.depot_municipality or 0))
    nodes = [depot]
    names = ["Depósito"]
    rows = {r.code: r for r in db.execute(text("SELECT code, name, uf FROM municipality WHERE code = ANY(:c)"), {"c": v.customers})}
    custs = []
    for c in v.customers:
        if c in g._mun_node and c in rows:
            nodes.append(g.municipality_node(c))
            names.append(f"{rows[c].name}/{rows[c].uf}")
            custs.append(c)
    mat = g.distance_matrix(nodes, "distance", a, req.mode, closed)[:, nodes]
    demands = [float(v.demand_t.get(str(c), v.default_demand_t)) for c in custs]
    sol = vrp(mat, demands, v.vehicles, v.vehicle_capacity_t, tl, v.max_route_km)
    w = g.weights("distance", a)
    for r in sol.results.get("routes", []):
        r["stops"] = [{"name": names[i], "node": nodes[i], "lon": float(g.node_lon[nodes[i]]), "lat": float(g.node_lat[nodes[i]]),
                       "municipality_code": custs[i - 1] if i > 0 else None} for i in r["sequence"]]
        edges: list[int] = []
        for s_, t_ in zip(r["sequence"][:-1], r["sequence"][1:]):
            p = g.shortest_path(nodes[s_], nodes[t_], "distance", a, req.mode, closed, w=w)
            if p:
                edges.extend(p.edges)
        r["edges"] = edges
        r["cost_brl_t"] = round(g.summarize(edges, a).cost_brl_t, 2)
    sol.results["dropped_names"] = [names[i] for i in sol.results.get("dropped", [])]
    return sol
