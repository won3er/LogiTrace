"""Painel analítico: indicadores derivados de dados e cálculos reais, cada um com seus metadados."""

from __future__ import annotations

from typing import Any

import numpy as np
from fastapi import APIRouter
from sqlalchemy import select, text

from app.api.common import DB, Metric, graph_or_404
from app.core.assumptions import load_assumptions
from app.models import Job, OptimizationRun, ScenarioRun
from app.network.analysis import CAPITALS
from app.network.engine import haversine_km

router = APIRouter(prefix="/analytics", tags=["painel"])
_detour_cache: dict[tuple[int, str], dict[str, Any]] = {}

IBGE_LOG = "IBGE — Logística dos Transportes 2014"


def _detour(db: DB) -> dict[str, Any]:
    g = graph_or_404(db)
    a = load_assumptions(db)
    key = (g.version_id, str(sorted(a.items())))
    if key in _detour_cache:
        return _detour_cache[key]
    codes = [c for c in CAPITALS if c in g._mun_node]
    nodes = [g._mun_node[c] for c in codes]
    dist = g.sssp(nodes, "distance", a, "road")[:, nodes]
    ratios, kms = [], []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            if np.isfinite(dist[i, j]):
                s = haversine_km(g.node_lon[nodes[i]], g.node_lat[nodes[i]], g.node_lon[nodes[j]], g.node_lat[nodes[j]])
                ratios.append(dist[i, j] / s)
                kms.append(dist[i, j])
    out = {"avg_km": float(np.mean(kms)), "median_detour": float(np.median(ratios)), "pairs": len(kms),
           "disconnected": len(nodes) * (len(nodes) - 1) // 2 - len(kms)}
    _detour_cache.clear()
    _detour_cache[key] = out
    return out


@router.get("/overview")
def overview(db: DB) -> dict[str, Any]:
    fac = db.execute(text("SELECT record_class, count(*) FROM facility GROUP BY 1")).all()
    cats = [dict(r) for r in db.execute(text(
        "SELECT category, modal, count(*) n, sum(capacity_value) cap FROM facility GROUP BY 1,2 ORDER BY n DESC")).mappings()]
    seg = {r.modal: float(r.km) for r in db.execute(text("SELECT modal, sum(length_km) km FROM infra_segment GROUP BY 1"))}
    paved = db.scalar(text("SELECT sum(length_km) FROM infra_segment WHERE modal='road' AND surface IN ('Duplicada','Pavimentada','Em obras de duplicação')")) or 0
    top_states = [dict(r) for r in db.execute(text(
        """SELECT m.uf, count(f.id) AS n, p.pop::bigint AS pop, round(count(f.id) * 1e5 / p.pop, 2)::float8 AS per_100k
           FROM facility f JOIN municipality m ON m.code = f.municipality_code
           JOIN (SELECT uf, sum(population) AS pop FROM municipality GROUP BY uf) p ON p.uf = m.uf
           GROUP BY m.uf, p.pop ORDER BY n DESC LIMIT 8""")).mappings()]
    flows = [dict(r) for r in db.execute(text(
        "SELECT dataset, flow_class, unit, count(*) links, sum(value) total FROM flow GROUP BY 1,2,3 ORDER BY 1")).mappings()]
    det = _detour(db)
    g = graph_or_404(db)
    v = db.execute(text("SELECT id, label, stats, created_at FROM network_version WHERE id=:v"), {"v": g.version_id}).mappings().first()
    assert v is not None
    stats = v["stats"] or {}
    labels = g.components("road")
    mun = g.node_of_kind("municipality")
    main = np.bincount(labels[mun]).argmax()
    off_codes = [int(g.node_ref[n]) for n in mun if labels[n] != main]
    pop_off = db.scalar(text("SELECT coalesce(sum(population),0) FROM municipality WHERE code = ANY(:c)"), {"c": off_codes}) or 0
    pop_tot = db.scalar(text("SELECT sum(population) FROM municipality")) or 1

    metrics: list[Metric] = [
        Metric(key="facilities_official", label="Instalações oficiais cadastradas",
               value=sum(n for c, n in fac if c == "official"), unit="instalações",
               definition="Registros importados de fontes oficiais (portos, terminais, portos secos, armazéns, aeroportos, aeródromos, fronteiras)",
               period="2014 (IBGE) e 2024 (terminais identificados nos fluxos)", source="IBGE",
               limitations="Armazenagem é um registro agregado por município; não há cadastro público nacional de CDs privados."),
        Metric(key="facilities_user", label="Instalações cadastradas pelo usuário", value=sum(n for c, n in fac if c == "user"),
               unit="instalações", definition="Registros editáveis inseridos via API/importação", period="contínuo",
               source="Usuário", limitations="Não validados por fonte oficial."),
        Metric(key="road_km", label="Malha rodoviária existente", value=round(seg.get("road", 0)), unit="km",
               definition="Extensão de trechos rodoviários do SNV (exclui 'Planejada')", period="2014", source=IBGE_LOG),
        Metric(key="road_paved_share", label="Rodovias pavimentadas", value=round(100 * paved / max(seg.get("road", 1), 1), 1),
               unit="%", definition="Duplicada + pavimentada + em duplicação ÷ extensão rodoviária total", period="2014",
               source=IBGE_LOG, denominator="Extensão rodoviária total"),
        Metric(key="rail_km", label="Malha ferroviária", value=round(seg.get("rail", 0)), unit="km",
               definition="Extensão ferroviária (inclui linhas urbanas de passageiros)", period="2014", source=IBGE_LOG),
        Metric(key="waterway_km", label="Vias navegáveis", value=round(seg.get("waterway", 0)), unit="km",
               definition="Extensão de hidrovias mapeadas", period="2014", source=IBGE_LOG,
               limitations="Sem calado nem sazonalidade."),
        Metric(key="network_nodes", label="Nós do grafo logístico", value=g.n_nodes, unit="nós",
               definition="Junções, municípios e instalações na versão de rede em uso", period=str(v["created_at"])[:10],
               source=f"LogiTrace — rede v{g.version_id}"),
        Metric(key="pop_outside_road_network", label="População fora da rede rodoviária principal",
               value=round(100 * pop_off / pop_tot, 2), unit="%",
               definition="População de municípios sem ligação ao componente rodoviário principal na base", period="pop. 2022; malha 2014",
               source="Cálculo LogiTrace sobre IBGE", denominator="População total 2022",
               limitations="Inclui municípios com acesso apenas fluvial/aéreo ou não mapeados na base de 2014."),
        Metric(key="avg_capital_km", label="Distância rodoviária média entre capitais", value=round(det["avg_km"]),
               unit="km", definition=f"Média do menor caminho rodoviário entre {det['pairs']} pares de capitais conectadas",
               period="malha 2014", source="Cálculo LogiTrace (Dijkstra)",
               limitations=f"{det['disconnected']} pares sem ligação rodoviária na base."),
        Metric(key="median_detour", label="Índice de sinuosidade mediano", value=round(det["median_detour"], 3),
               unit="×", definition="Distância na rede ÷ distância em linha reta, mediana entre pares de capitais",
               period="malha 2014", source="Cálculo LogiTrace", denominator="Distância geodésica em linha reta"),
    ]
    scen = db.scalars(select(ScenarioRun).where(ScenarioRun.status == "success").order_by(ScenarioRun.id.desc()).limit(5)).all()
    opt = db.scalars(select(OptimizationRun).where(OptimizationRun.status == "success").order_by(OptimizationRun.id.desc()).limit(5)).all()
    crit = db.scalars(select(Job).where(Job.kind == "criticality", Job.status == "success").order_by(Job.id.desc()).limit(1)).first()
    return {
        "metrics": [m.model_dump() for m in metrics],
        "by_category": cats,
        "top_states_by_facilities": top_states,
        "network": {"version_id": g.version_id, "label": v["label"], "km_by_modal": stats.get("km_by_modal"),
                    "unconnected_anchors": stats.get("unconnected_anchors"), "transfer_edges": stats.get("transfer_edges")},
        "flows": flows,
        "recent_scenarios": [{"run_id": r.id, "scenario_id": r.scenario_id, "finished_at": r.finished_at, "summary": r.summary} for r in scen],
        "recent_optimizations": [{"run_id": r.id, "problem": r.problem, "label": r.label, "quality": r.solution_quality,
                                  "kpis": (r.results or {}).get("kpis"), "finished_at": r.finished_at} for r in opt],
        "critical_edges": ((crit.params or {}).get("result", {}).get("edges", [])[:10] if crit else []),
        "critical_job_id": crit.id if crit else None,
    }
