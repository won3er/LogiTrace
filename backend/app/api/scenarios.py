"""Cenários: criação, alterações, execução assíncrona, comparação e reexecução reprodutível."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app import jobs
from app.api.common import DB, graph_or_404
from app.db.session import SessionLocal
from app.models import Scenario, ScenarioChange, ScenarioRun
from app.scenarios.engine import ChangeIn, ScenarioConfig, run_scenario

router = APIRouter(prefix="/scenarios", tags=["cenários"])

TEMPLATES = [
    {"key": "interruption", "name": "Interrupção de infraestrutura",
     "description": "Interdite rodovias, conexões ou terminais e veja rotas afetadas e variações de distância, tempo e custo.",
     "change_types": ["closure"]},
    {"key": "new_dc", "name": "Novo centro de distribuição",
     "description": "Adicione uma localização candidata e meça cobertura, distribuição da demanda e custo de transporte.",
     "change_types": ["new_facility"]},
    {"key": "redistribution", "name": "Redistribuição de demanda",
     "description": "Configure instalações e demanda; a alocação ótima (LP) indica gargalos e regiões com atendimento insuficiente.",
     "change_types": ["remove_facility", "capacity", "demand"]},
    {"key": "costs", "name": "Alteração de custos",
     "description": "Altere custos por km, modal, tempo, pedágio e transbordo.", "change_types": ["cost"]},
    {"key": "demand", "name": "Aumento ou redução da demanda",
     "description": "Aplique fatores de demanda globais ou por UF.", "change_types": ["demand"]},
    {"key": "capacity", "name": "Alteração da capacidade",
     "description": "Altere capacidades de instalações (t/ano).", "change_types": ["capacity"]},
]


class ScenarioIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = None
    config: ScenarioConfig = Field(default_factory=ScenarioConfig)
    network_version_id: int | None = None
    changes: list[ChangeIn] = Field(default_factory=list)


def _scenario_out(db: DB, sc: Scenario) -> dict[str, Any]:
    changes = db.scalars(select(ScenarioChange).where(ScenarioChange.scenario_id == sc.id).order_by(ScenarioChange.id)).all()
    runs = db.scalars(select(ScenarioRun).where(ScenarioRun.scenario_id == sc.id).order_by(ScenarioRun.id.desc()).limit(20)).all()
    return {
        "id": sc.id, "name": sc.name, "description": sc.description, "config": sc.config,
        "network_version_id": sc.network_version_id, "created_at": sc.created_at, "updated_at": sc.updated_at,
        "changes": [{"id": c.id, "change_type": c.change_type, "payload": c.payload, "note": c.note, "created_at": c.created_at}
                    for c in changes],
        "runs": [{"id": r.id, "status": r.status, "started_at": r.started_at, "finished_at": r.finished_at,
                  "duration_ms": r.duration_ms, "network_version_id": r.network_version_id, "input_hash": r.input_hash,
                  "result_hash": r.result_hash, "rerun_of": r.rerun_of, "summary": r.summary, "error": r.error} for r in runs],
    }


@router.get("/templates")
def templates() -> list[dict[str, Any]]:
    return TEMPLATES


@router.get("")
def list_scenarios(db: DB) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Scenario, func.count(ScenarioRun.id), func.max(ScenarioRun.finished_at))
        .outerjoin(ScenarioRun, ScenarioRun.scenario_id == Scenario.id).group_by(Scenario.id).order_by(Scenario.id.desc())
    ).all()
    return [{"id": s.id, "name": s.name, "description": s.description, "created_at": s.created_at, "runs": n,
             "last_run_at": last} for s, n, last in rows]


@router.post("", status_code=201)
def create_scenario(db: DB, body: ScenarioIn) -> dict[str, Any]:
    sc = Scenario(name=body.name, description=body.description, config=body.config.model_dump(),
                  network_version_id=body.network_version_id)
    db.add(sc)
    db.flush()
    for ch in body.changes:
        db.add(ScenarioChange(scenario_id=sc.id, change_type=ch.change_type, payload=ch.payload, note=ch.note))
    db.commit()
    return _scenario_out(db, sc)


@router.get("/{scenario_id}")
def get_scenario(db: DB, scenario_id: int) -> dict[str, Any]:
    sc = db.get(Scenario, scenario_id)
    if sc is None:
        raise HTTPException(404, "Cenário não encontrado")
    return _scenario_out(db, sc)


@router.put("/{scenario_id}")
def update_scenario(db: DB, scenario_id: int, body: ScenarioIn) -> dict[str, Any]:
    """Atualiza configuração e substitui a lista de alterações. Execuções anteriores mantêm seus snapshots."""
    sc = db.get(Scenario, scenario_id)
    if sc is None:
        raise HTTPException(404, "Cenário não encontrado")
    sc.name, sc.description, sc.config = body.name, body.description, body.config.model_dump()
    sc.network_version_id = body.network_version_id
    for c in db.scalars(select(ScenarioChange).where(ScenarioChange.scenario_id == sc.id)):
        db.delete(c)
    for ch in body.changes:
        db.add(ScenarioChange(scenario_id=sc.id, change_type=ch.change_type, payload=ch.payload, note=ch.note))
    db.commit()
    return _scenario_out(db, sc)


@router.delete("/{scenario_id}", status_code=204)
def delete_scenario(db: DB, scenario_id: int) -> None:
    sc = db.get(Scenario, scenario_id)
    if sc is None:
        raise HTTPException(404, "Cenário não encontrado")
    db.delete(sc)
    db.commit()


@router.post("/{scenario_id}/changes", status_code=201)
def add_change(db: DB, scenario_id: int, body: ChangeIn) -> dict[str, Any]:
    if db.get(Scenario, scenario_id) is None:
        raise HTTPException(404, "Cenário não encontrado")
    c = ScenarioChange(scenario_id=scenario_id, change_type=body.change_type, payload=body.payload, note=body.note)
    db.add(c)
    db.commit()
    return {"id": c.id}


@router.delete("/{scenario_id}/changes/{change_id}", status_code=204)
def delete_change(db: DB, scenario_id: int, change_id: int) -> None:
    c = db.get(ScenarioChange, change_id)
    if c is None or c.scenario_id != scenario_id:
        raise HTTPException(404, "Alteração não encontrada")
    db.delete(c)
    db.commit()


def _submit(scenario_id: int, rerun_of: int | None = None) -> int:
    def work(ctx: jobs.JobContext) -> tuple[str, int]:
        with SessionLocal() as s:
            ctx.progress(0.1, "avaliando base e cenário")
            run = run_scenario(s, scenario_id, rerun_of=rerun_of)
            return ("scenario_run", run.id)

    return jobs.submit("scenario_run", work, {"scenario_id": scenario_id, "rerun_of": rerun_of},
                       ref_type="scenario", ref_id=scenario_id)


@router.post("/{scenario_id}/run")
def run(db: DB, scenario_id: int) -> dict[str, Any]:
    if db.get(Scenario, scenario_id) is None:
        raise HTTPException(404, "Cenário não encontrado")
    graph_or_404(db)
    return {"job_id": _submit(scenario_id)}


@router.post("/runs/{run_id}/rerun")
def rerun(db: DB, run_id: int) -> dict[str, Any]:
    """Repete uma execução com exatamente as mesmas entradas (configuração, alterações, premissas e versão de rede)."""
    r = db.get(ScenarioRun, run_id)
    if r is None:
        raise HTTPException(404, "Execução não encontrada")
    return {"job_id": _submit(r.scenario_id, rerun_of=run_id)}


@router.get("/runs/{run_id}")
def get_run(db: DB, run_id: int) -> dict[str, Any]:
    r = db.get(ScenarioRun, run_id)
    if r is None:
        raise HTTPException(404, "Execução não encontrada")
    reproduced = None
    if r.rerun_of:
        prev = db.get(ScenarioRun, r.rerun_of)
        reproduced = prev is not None and prev.result_hash == r.result_hash
    return {"id": r.id, "scenario_id": r.scenario_id, "status": r.status, "started_at": r.started_at,
            "finished_at": r.finished_at, "duration_ms": r.duration_ms, "network_version_id": r.network_version_id,
            "input_hash": r.input_hash, "result_hash": r.result_hash, "rerun_of": r.rerun_of, "reproduced": reproduced,
            "inputs": r.inputs, "results": r.results, "summary": r.summary, "error": r.error}


@router.get("/runs/{run_id}/routes")
def run_routes(db: DB, run_id: int, limit: int = 20) -> dict[str, Any]:
    """GeoJSON das rotas base x cenário dos pares OD afetados (para o mapa)."""
    r = db.get(ScenarioRun, run_id)
    if r is None or r.status != "success":
        raise HTTPException(404, "Execução não encontrada ou sem sucesso")
    g = graph_or_404(db, r.network_version_id)
    feats: list[dict[str, Any]] = []
    for i, p in enumerate(r.results["comparison"]["pairs"][:limit]):
        for kind in ("base", "scenario"):
            edges = p.get(f"{kind}_edges")
            if edges:
                feats.append(g.path_feature(edges, {"pair": i, "kind": kind, "label": f"{p['origin']} → {p['dest']}",
                                                    "delta_cost_brl_t": p.get("delta_cost_brl_t"), "delta_km": p.get("delta_km")}))
    closed_ids = r.results["scenario"].get("closed_edge_ids") or []
    closed = [g.path_feature(closed_ids, {"kind": "closed"}, tolerance=0.0005)] if closed_ids else []
    return {"type": "FeatureCollection", "features": feats + closed}
