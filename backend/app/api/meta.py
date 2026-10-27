"""Metadados: fontes, importações, premissas, versões de rede e tarefas."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.common import DB
from app.core.assumptions import DEFAULTS
from app.models import Assumption, DataSource, Facility, Flow, ImportRun, InfraSegment, Job, NetworkVersion

router = APIRouter(tags=["meta"])


@router.get("/sources")
def sources(db: DB) -> list[dict[str, Any]]:
    out = []
    for s in db.scalars(select(DataSource).order_by(DataSource.id)):
        last = db.scalars(select(ImportRun).where(ImportRun.source_id == s.id).order_by(ImportRun.id.desc()).limit(1)).first()
        out.append({
            "key": s.key, "name": s.name, "publisher": s.publisher, "url": s.url, "license": s.license,
            "attribution": s.attribution, "coverage": s.coverage, "reference_date": s.reference_date,
            "update_method": s.update_method, "limitations": s.limitations, "reliability": s.reliability,
            "facilities": db.scalar(select(func.count()).where(Facility.source_id == s.id)),
            "segments": db.scalar(select(func.count()).where(InfraSegment.source_id == s.id)),
            "flows": db.scalar(select(func.count()).where(Flow.source_id == s.id)),
            "last_import": None if last is None else {"id": last.id, "dataset": last.dataset, "status": last.status,
                                                      "finished_at": last.finished_at, "sha256": last.file_sha256},
        })
    return out


@router.get("/imports")
def imports(db: DB, limit: int = 100) -> list[dict[str, Any]]:
    rows = db.execute(
        select(ImportRun, DataSource.key).join(DataSource, DataSource.id == ImportRun.source_id).order_by(ImportRun.id.desc()).limit(limit)
    ).all()
    return [{
        "id": r.id, "source": key, "dataset": r.dataset, "file": r.file_name, "sha256": r.file_sha256, "status": r.status,
        "started_at": r.started_at, "finished_at": r.finished_at, "rows_read": r.rows_read, "inserted": r.rows_inserted,
        "updated": r.rows_updated, "unchanged": r.rows_unchanged, "rejected": r.rows_rejected,
        "report": {k: v for k, v in (r.report or {}).items() if k in ("rejected_total", "warnings_total", "duplicates", "missing_total")},
    } for r, key in rows]


@router.get("/imports/{run_id}")
def import_detail(db: DB, run_id: int) -> dict[str, Any]:
    r = db.get(ImportRun, run_id)
    if r is None:
        raise HTTPException(404, "Importação não encontrada")
    return {"id": r.id, "dataset": r.dataset, "status": r.status, "report": r.report, "error": r.error}


@router.get("/assumptions")
def assumptions(db: DB) -> list[dict[str, Any]]:
    defaults = {d["key"]: d["value"] for d in DEFAULTS}
    return [{"key": a.key, "value": a.value, "default": defaults.get(a.key), "unit": a.unit, "category": a.category,
             "description": a.description, "rationale": a.rationale, "updated_at": a.updated_at}
            for a in db.scalars(select(Assumption).order_by(Assumption.category, Assumption.key))]


class AssumptionUpdate(BaseModel):
    value: float


@router.put("/assumptions/{key}")
def update_assumption(db: DB, key: str, body: AssumptionUpdate) -> dict[str, Any]:
    """Altera o valor padrão global. Execuções anteriores mantêm o snapshot das premissas usadas."""
    a = db.get(Assumption, key)
    if a is None:
        raise HTTPException(404, "Premissa inexistente")
    if body.value < 0 or (key.startswith("speed.") and body.value <= 0):
        raise HTTPException(400, "Valor inválido para a premissa")
    a.value = body.value
    db.commit()
    return {"key": key, "value": a.value}


@router.get("/network/versions")
def network_versions(db: DB) -> list[dict[str, Any]]:
    return [{"id": v.id, "label": v.label, "created_at": v.created_at, "status": v.status, "nodes": v.node_count,
             "edges": v.edge_count, "stats": v.stats, "params": v.params, "checksum": v.checksum,
             "import_runs": v.import_runs}
            for v in db.scalars(select(NetworkVersion).order_by(NetworkVersion.id.desc()))]


@router.get("/jobs/{job_id}")
def job(db: DB, job_id: int) -> dict[str, Any]:
    j = db.get(Job, job_id)
    if j is None:
        raise HTTPException(404, "Tarefa não encontrada")
    return {"id": j.id, "kind": j.kind, "status": j.status, "progress": j.progress, "message": j.message,
            "ref_type": j.ref_type, "ref_id": j.ref_id, "error": j.error, "created_at": j.created_at,
            "started_at": j.started_at, "finished_at": j.finished_at}
