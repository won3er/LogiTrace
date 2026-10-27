"""Otimização logística (OR-Tools): execução assíncrona, consulta e comparação de soluções."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app import jobs
from app.api.common import DB, graph_or_404
from app.db.session import SessionLocal
from app.models import OptimizationRun
from app.optimization.service import OptimizationRequest, create_run, execute_run

router = APIRouter(prefix="/optimization", tags=["otimização"])

PROBLEMS = [
    {"key": "p_median", "name": "Localização de instalações (p-mediana)",
     "description": "Escolhe p instalações que minimizam o custo ponderado pela demanda. Não capacitado.", "solver": "SCIP (MIP)"},
    {"key": "capacitated_location", "name": "Localização com capacidades",
     "description": "Custo fixo + transporte + penalidade de não atendimento, com capacidade por instalação.", "solver": "SCIP (MIP)"},
    {"key": "max_coverage", "name": "Máxima cobertura (MCLP)",
     "description": "Escolhe p instalações que maximizam a demanda dentro do raio de cobertura na rede.", "solver": "SCIP (MIP)"},
    {"key": "transportation", "name": "Alocação de demanda / fluxos",
     "description": "Distribui a demanda entre instalações abertas minimizando custo (LP), com preços-sombra de capacidade.", "solver": "GLOP (LP)"},
    {"key": "pareto", "name": "Custo × cobertura (fronteira)",
     "description": "Compara soluções p-mediana e MCLP para vários p e marca as não dominadas.", "solver": "SCIP (MIP)"},
    {"key": "vrp", "name": "Roteirização de veículos (CVRP)",
     "description": "Rotas a partir de um depósito com capacidade de veículo, sobre distâncias da rede.", "solver": "OR-Tools Routing (heurística)"},
]


@router.get("/problems")
def problems() -> list[dict[str, Any]]:
    return PROBLEMS


@router.post("/runs")
def submit(db: DB, body: OptimizationRequest) -> dict[str, Any]:
    graph_or_404(db, body.network_version_id)
    run = create_run(db, body)
    run_id = run.id

    def work(ctx: jobs.JobContext) -> tuple[str, int]:
        with SessionLocal() as s:
            execute_run(s, run_id)
        return ("optimization_run", run_id)

    job_id = jobs.submit("optimization", work, {"run_id": run_id}, ref_type="optimization_run", ref_id=run_id)
    return {"job_id": job_id, "run_id": run_id}


@router.get("/runs")
def list_runs(db: DB, limit: int = 50) -> list[dict[str, Any]]:
    return [{"id": r.id, "problem": r.problem, "label": r.label, "status": r.status, "quality": r.solution_quality,
             "objective_value": r.objective_value, "gap": r.gap, "solve_time_ms": r.solve_time_ms,
             "created_at": r.created_at, "kpis": (r.results or {}).get("kpis")}
            for r in db.scalars(select(OptimizationRun).order_by(OptimizationRun.id.desc()).limit(limit))]


@router.get("/runs/{run_id}")
def get_run(db: DB, run_id: int) -> dict[str, Any]:
    r = db.get(OptimizationRun, run_id)
    if r is None:
        raise HTTPException(404, "Execução não encontrada")
    return {
        "id": r.id, "problem": r.problem, "label": r.label, "status": r.status, "quality": r.solution_quality,
        "quality_explanation": {
            "OPTIMAL": "Solução comprovadamente ótima para o modelo formulado (gap nulo).",
            "FEASIBLE": "Solução viável sem prova de otimalidade (limite de tempo); veja o gap em relação ao limitante.",
            "HEURISTIC": "Solução de metaheurística; não há garantia de otimalidade nem limitante inferior.",
            "INFEASIBLE": "O modelo não possui solução viável com as restrições informadas.",
            "NOT_SOLVED": "O solver não encontrou solução no tempo disponível.",
            "ERROR": "A execução falhou.",
        }.get(r.solution_quality or "", None),
        "solver": r.solver, "objective": r.objective, "objective_value": r.objective_value, "best_bound": r.best_bound,
        "gap": r.gap, "solve_time_ms": r.solve_time_ms, "constraints": r.constraints, "assumptions": r.assumptions,
        "params": r.params, "input_hash": r.input_hash, "network_version_id": r.network_version_id,
        "results": r.results, "error": r.error, "created_at": r.created_at, "finished_at": r.finished_at,
    }


@router.get("/runs/{run_id}/geojson")
def run_geojson(db: DB, run_id: int) -> dict[str, Any]:
    """Instalações abertas, pontos de demanda e linhas de atribuição (esquemáticas) ou rotas de veículos."""
    r = db.get(OptimizationRun, run_id)
    if r is None or not r.results:
        raise HTTPException(404, "Execução não encontrada ou sem resultado")
    feats: list[dict[str, Any]] = []
    res = r.results
    if r.problem == "vrp":
        g = graph_or_404(db, r.network_version_id)
        for route in res.get("routes", []):
            feats.append(g.path_feature(route.get("edges", []), {"kind": "route", "vehicle": route["vehicle"], "km": route["km"]}, 0.001))
            for k, s in enumerate(route["stops"][:-1]):
                feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                              "properties": {"kind": "stop", "vehicle": route["vehicle"], "order": k, "name": s["name"]}})
        return {"type": "FeatureCollection", "features": feats}
    fac = {f["key"]: f for f in res.get("open_facilities", [])}
    for f in fac.values():
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [f["lon"], f["lat"]]},
                      "properties": {"kind": "facility", **{k: v for k, v in f.items() if k not in ("lon", "lat")}}})
    for d in res.get("demand", []):
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [d["lon"], d["lat"]]},
                      "properties": {"kind": "demand", **{k: v for k, v in d.items() if k not in ("lon", "lat")}}})
        if d.get("facility") in fac:
            f = fac[d["facility"]]
            feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[f["lon"], f["lat"]], [d["lon"], d["lat"]]]},
                          "properties": {"kind": "assignment", "facility": d["facility"], "demand_t": d["served_t"],
                                         "note": "linha esquemática de atribuição; o custo usa a rota na rede"}})
    return {"type": "FeatureCollection", "features": feats}


@router.get("/compare")
def compare(db: DB, ids: str) -> list[dict[str, Any]]:
    out = []
    for i in [int(x) for x in ids.split(",") if x.strip().isdigit()][:10]:
        r = db.get(OptimizationRun, i)
        if r is None:
            continue
        out.append({"id": r.id, "problem": r.problem, "label": r.label, "quality": r.solution_quality,
                    "objective": r.objective, "objective_value": r.objective_value,
                    "kpis": (r.results or {}).get("kpis"),
                    "open": [f["name"] for f in (r.results or {}).get("open_facilities", [])]})
    return out
