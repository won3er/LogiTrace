"""Motor de cenários.

Todo cenário é a base + uma lista de alterações (interdições, novas instalações, capacidades, custos,
demanda). A mesma rotina avalia a base e o cenário, e o resultado é a comparação entre os dois.
Nada é gravado sobre a base: alterações vivem apenas na execução.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field
from shapely.geometry import box, shape
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.assumptions import load_assumptions
from app.db.base import utcnow
from app.models import Facility, Scenario, ScenarioChange, ScenarioRun
from app.network.analysis import CAPITALS, municipality_info
from app.network.versions import latest_version_id
from app.network.engine import Metric, ModalMode, NetworkGraph, get_graph, haversine_km
from app.optimization.data import Candidate, DemandSpec, ProblemData, build_demand
from app.optimization.solvers import transportation
from app.scenarios.des import simulate_operations

ChangeType = Literal["closure", "new_facility", "remove_facility", "capacity", "cost", "demand"]


class Endpoint(BaseModel):
    type: Literal["municipality", "facility", "point"]
    id: int | None = None
    lon: float | None = None
    lat: float | None = None
    label: str | None = None


class ODPair(BaseModel):
    origin: Endpoint
    dest: Endpoint
    volume_t: float = Field(default=1.0, gt=0)


class ScenarioConfig(BaseModel):
    metric: Metric = "cost"
    mode: ModalMode = "road"
    od_pairs: list[ODPair] = Field(default_factory=list)
    od_benchmark: Literal["none", "capitals"] = "capitals"
    service_facility_ids: list[int] = Field(default_factory=list)
    demand: DemandSpec = Field(default_factory=DemandSpec)
    coverage_km: float | None = Field(default=None, gt=0)
    unmet_penalty_brl_t: float = Field(default=1000.0, ge=0)
    default_capacity_t: float = Field(default=2_000_000, gt=0)
    run_des: bool = True
    des_days: int = Field(default=60, ge=7, le=365)
    des_seed: int = 42


class ChangeIn(BaseModel):
    change_type: ChangeType
    payload: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


@dataclass
class State:
    assumptions: dict[str, float]
    closed: set[int] = field(default_factory=set)
    closed_nodes: set[int] = field(default_factory=set)
    services: list[Candidate] = field(default_factory=list)
    demand: DemandSpec = field(default_factory=DemandSpec)
    applied: list[dict[str, Any]] = field(default_factory=list)


def _hash(o: Any) -> str:
    return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()


def _round(o: Any) -> Any:
    """Arredonda floats para a comparação de reprodutibilidade não depender de ruído numérico."""
    if isinstance(o, dict):
        return {k: _round(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_round(v) for v in o]
    if isinstance(o, float | np.floating):
        f = float(o)
        return None if not np.isfinite(f) else round(f, 6)
    if isinstance(o, np.integer):
        return int(o)
    return o


def result_hash(results: dict[str, Any]) -> str:
    """Hash dos resultados sem campos de tempo de execução (para verificar reprodutibilidade)."""

    def strip(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k not in ("elapsed_ms", "solve_time_ms")}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o

    return _hash(strip(results))


def _resolve_endpoint(db: Session, g: NetworkGraph, ep: Endpoint) -> tuple[int, str, float]:
    if ep.type == "municipality":
        assert ep.id is not None
        name = db.scalar(text("SELECT name || '/' || uf FROM municipality WHERE code=:c"), {"c": ep.id}) or str(ep.id)
        return g.municipality_node(ep.id), ep.label or name, 0.0
    if ep.type == "facility":
        assert ep.id is not None
        f = db.get(Facility, ep.id)
        return g.facility_node(ep.id), ep.label or (f.name if f else str(ep.id)), 0.0
    assert ep.lon is not None and ep.lat is not None
    node, snap = g.nearest_road_node(ep.lon, ep.lat)
    return node, ep.label or f"Ponto ({ep.lat:.4f}, {ep.lon:.4f})", snap


def _service_candidates(db: Session, g: NetworkGraph, ids: list[int], default_cap: float, turnover: float) -> list[Candidate]:
    out = []
    for f in db.scalars(select(Facility).where(Facility.id.in_(ids)).order_by(Facility.id)):
        node = g._fac_node.get(f.id)
        if node is None:
            continue
        has_cap = f.capacity_value is not None and (f.capacity_unit or "").startswith("t")
        out.append(Candidate(
            key=f"fac:{f.id}", name=f.name, uf=f.uf, node=node, lon=float(g.node_lon[node]), lat=float(g.node_lat[node]),
            capacity_t=float(f.capacity_value) * turnover if has_cap else default_cap, fixed_cost=0.0, facility_id=f.id,
            capacity_source=f"fonte: estática × {turnover:g} giros/ano" if has_cap else "premissa (t/ano)",
        ))
    return out


def apply_changes(db: Session, g: NetworkGraph, base: State, changes: list[ChangeIn], default_cap: float) -> State:
    st = State(assumptions=dict(base.assumptions), closed=set(base.closed), services=list(base.services),
               demand=base.demand.model_copy(deep=True))
    for ch in changes:
        p = ch.payload
        info: dict[str, Any] = {"type": ch.change_type, "payload": p}
        if ch.change_type == "closure":
            edges: set[int] = set()
            if p.get("segment_ids"):
                edges |= g.edges_for_segments({int(s) for s in p["segment_ids"]})
            if p.get("edge_ids"):
                edges |= {int(e) for e in p["edge_ids"] if 0 <= int(e) < g.n_edges}
            if p.get("facility_id") is not None:
                node = g._fac_node.get(int(p["facility_id"]))
                if node is not None:
                    edges |= {i for i in range(g.n_edges) if g.u[i] == node or g.v[i] == node}
                    st.services = [s for s in st.services if s.facility_id != int(p["facility_id"])]
            if p.get("bbox") or p.get("geometry"):
                area = box(*p["bbox"]) if p.get("bbox") else shape(p["geometry"])
                rows = db.execute(
                    text("SELECT edge_idx FROM network_edge WHERE version_id=:v AND modal = ANY(:m) "
                         "AND ST_Intersects(geom, ST_GeomFromText(:wkt, 4326))"),
                    {"v": g.version_id, "wkt": area.wkt, "m": p.get("modals") or ["road", "rail", "waterway"]},
                ).scalars()
                edges |= set(rows)
            st.closed |= edges
            info["edges_closed"] = len(edges)
        elif ch.change_type == "new_facility":
            node, snap = g.nearest_road_node(float(p["lon"]), float(p["lat"]))
            st.services.append(Candidate(
                key=f"new:{len(st.services)}:{p.get('name', 'Nova instalação')}", name=p.get("name", "Nova instalação (cenário)"),
                uf=p.get("uf"), node=node, lon=float(p["lon"]), lat=float(p["lat"]),
                capacity_t=float(p.get("capacity_t", default_cap)), fixed_cost=float(p.get("fixed_cost", 0.0)),
                capacity_source="cenário",
            ))
            info["snap_km"] = round(snap, 2)
        elif ch.change_type == "remove_facility":
            st.services = [s for s in st.services if s.facility_id != int(p["facility_id"])]
        elif ch.change_type == "capacity":
            for s in st.services:
                if (p.get("facility_id") is not None and s.facility_id == int(p["facility_id"])) or (p.get("key") and s.key == p["key"]):
                    if "capacity_t" in p:
                        s.capacity_t = float(p["capacity_t"])
                    elif "factor" in p:
                        s.capacity_t *= float(p["factor"])
                    s.capacity_source = "cenário"
        elif ch.change_type == "cost":
            for k, v in (p.get("overrides") or {}).items():
                if k not in st.assumptions:
                    raise ValueError(f"Premissa desconhecida: {k}")
                st.assumptions[k] = float(v)
        elif ch.change_type == "demand":
            if "global_factor" in p:
                st.demand.global_factor *= float(p["global_factor"])
            for uf, f in (p.get("uf_factors") or {}).items():
                st.demand.uf_factors[uf] = st.demand.uf_factors.get(uf, 1.0) * float(f)
        st.applied.append(info)
    # copia candidatos para não compartilhar objetos com a base
    st.services = [Candidate(**vars(s)) for s in st.services]
    return st


def _od_eval(db: Session, g: NetworkGraph, cfg: ScenarioConfig, st: State) -> dict[str, Any]:
    pairs: list[tuple[int, str, int, str, float, float]] = []
    explicit = bool(cfg.od_pairs)
    if explicit:
        for p in cfg.od_pairs:
            o, on, osnap = _resolve_endpoint(db, g, p.origin)
            d, dn, dsnap = _resolve_endpoint(db, g, p.dest)
            pairs.append((o, on, d, dn, p.volume_t, osnap + dsnap))
    elif cfg.od_benchmark == "capitals":
        codes = [c for c in CAPITALS if c in g._mun_node]
        info = municipality_info(db, codes)
        for i, a in enumerate(codes):
            for b in codes[i + 1:]:
                pairs.append((g.municipality_node(a), f"{info[a]['name']}/{info[a]['uf']}",
                              g.municipality_node(b), f"{info[b]['name']}/{info[b]['uf']}", 1.0, 0.0))
    if not pairs:
        return {"pairs": [], "totals": {}}
    origins = sorted({p[0] for p in pairs})
    w = g.weights(cfg.metric, st.assumptions)
    mask = g.edge_mask(cfg.mode, st.closed)
    _, pred = g.sssp(origins, cfg.metric, st.assumptions, cfg.mode, st.closed, return_predecessors=True, w=w)
    row = {o: i for i, o in enumerate(origins)}
    out = []
    for o, on, d, dn, vol, snap in pairs:
        nodes = g.path_from_predecessors(pred[row[o]], o, d)
        straight = haversine_km(g.node_lon[o], g.node_lat[o], g.node_lon[d], g.node_lat[d])
        if nodes is not None and g.path_is_artificial(g.edges_of_path(nodes, w, mask), o, d):
            nodes = None
        if nodes is None:
            out.append({"origin": on, "dest": dn, "volume_t": vol, "connected": False, "straight_km": round(straight, 1)})
            continue
        edges = g.edges_of_path(nodes, w, mask)
        s = g.summarize(edges, st.assumptions)
        out.append({
            "origin": on, "dest": dn, "origin_node": o, "dest_node": d, "volume_t": vol, "connected": True,
            **s.as_dict(), "total_cost_brl": round(s.cost_brl_t * vol, 2), "straight_km": round(straight, 1),
            "snap_km": round(snap, 2), "edges": edges if explicit else None, "edge_hash": _hash(edges)[:16],
            "_edges": edges,
        })
    con = [p for p in out if p["connected"]]
    totals = {
        "pairs": len(out), "connected": len(con), "disconnected": len(out) - len(con),
        "sum_km": round(sum(p["distance_km"] for p in con), 1),
        "sum_time_h": round(sum(p["time_h"] for p in con), 2),
        "sum_cost_brl": round(sum(p["total_cost_brl"] for p in con), 2),
        "avg_km": round(sum(p["distance_km"] for p in con) / max(len(con), 1), 1),
    }
    return {"pairs": out, "totals": totals}


def _service_eval(db: Session, g: NetworkGraph, cfg: ScenarioConfig, st: State) -> dict[str, Any] | None:
    if not st.services:
        return None
    a = st.assumptions
    demand, excluded = build_demand(db, g, st.demand, a["demand.per_capita_t_year"])
    src = [s.node for s in st.services]
    dn = np.array([d.node for d in demand])
    cost = g.distance_matrix(src, cfg.metric, a, cfg.mode, st.closed)[:, dn]
    km = g.distance_matrix(src, "distance", a, cfg.mode, st.closed)[:, dn]
    # nova instalação fora da rede: acrescenta o trecho de acesso (linha reta × fator de sinuosidade)
    for j, s in enumerate(st.services):
        if s.key.startswith("new:"):
            extra = haversine_km(s.lon, s.lat, float(g.node_lon[s.node]), float(g.node_lat[s.node])) * a["network.access_detour_factor"]
            km[j] += extra
            if cfg.metric == "cost":
                cost[j] += extra * a["cost.road.brl_tkm"]
            elif cfg.metric == "time":
                cost[j] += extra / a["speed.access"]
            else:
                cost[j] += extra
    pd_ = ProblemData(demand=demand, candidates=st.services, cost=cost, km=km, excluded_demand=excluded, metric=cfg.metric)
    cov = cfg.coverage_km or a["coverage.default_km"]
    sol = transportation(pd_, list(range(len(st.services))), cfg.unmet_penalty_brl_t, cov)
    res = sol.results
    res["solver"] = {"quality": sol.quality, "solver": sol.solver, "objective": sol.objective,
                     "objective_value": sol.objective_value, "solve_time_ms": round(sol.solve_time_ms, 1),
                     "constraints": sol.constraints}
    under = [d for d in res["demand"] if d["unmet_t"] > 1e-6 or (d["km"] is None) or (d["km"] > cov)]
    res["underserved"] = sorted(under, key=lambda d: -(d["unmet_t"] + (d["demand_t"] if d["km"] and d["km"] > cov else 0)))[:60]
    res["overloaded"] = [f for f in res["open_facilities"] if f.get("binding")]
    if cfg.run_des:
        res["operations"] = simulate_operations(res["open_facilities"], days=cfg.des_days, seed=cfg.des_seed)
    return res


def evaluate(db: Session, g: NetworkGraph, cfg: ScenarioConfig, st: State) -> dict[str, Any]:
    t = time.perf_counter()
    od = _od_eval(db, g, cfg, st)
    svc = _service_eval(db, g, cfg, st)
    return {"od": od, "service": svc, "closed_edges": len(st.closed), "closed_edge_ids": sorted(st.closed)[:5000],
            "applied_changes": st.applied,
            "elapsed_ms": round((time.perf_counter() - t) * 1000, 1)}


def compare(base: dict[str, Any], scen: dict[str, Any]) -> dict[str, Any]:
    pairs = []
    for b, s in zip(base["od"]["pairs"], scen["od"]["pairs"]):
        row: dict[str, Any] = {"origin": b["origin"], "dest": b["dest"], "base_connected": b["connected"],
                               "scenario_connected": s["connected"]}
        if b["connected"] and s["connected"]:
            row.update({
                "delta_km": round(s["distance_km"] - b["distance_km"], 2),
                "delta_time_h": round(s["time_h"] - b["time_h"], 2),
                "delta_cost_brl_t": round(s["cost_brl_t"] - b["cost_brl_t"], 2),
                "route_changed": b["edge_hash"] != s["edge_hash"],
                "base": {k: b[k] for k in ("distance_km", "time_h", "cost_brl_t")},
                "scenario": {k: s[k] for k in ("distance_km", "time_h", "cost_brl_t")},
            })
        row["affected"] = (not s["connected"] and b["connected"]) or row.get("route_changed", False) or \
            abs(row.get("delta_cost_brl_t", 0)) > 1e-6
        pairs.append(row)
    affected = [p for p in pairs if p["affected"]]
    # Deltas somados apenas sobre pares conectados nos dois estados; desconexões são contadas à parte
    both = [(b, s) for b, s in zip(base["od"]["pairs"], scen["od"]["pairs"]) if b["connected"] and s["connected"]]
    out: dict[str, Any] = {
        "od_pairs_affected": len(affected),
        "od_pairs_disconnected": sum(1 for p in pairs if p["base_connected"] and not p["scenario_connected"]),
        "od_pairs_compared": len(both),
        "od_delta_sum_cost_brl": round(sum((s["total_cost_brl"] - b["total_cost_brl"]) for b, s in both), 2),
        "od_delta_sum_km": round(sum((s["distance_km"] - b["distance_km"]) for b, s in both), 1),
        "od_delta_sum_time_h": round(sum((s["time_h"] - b["time_h"]) for b, s in both), 2),
        "pairs": sorted(affected, key=lambda p: -abs(p.get("delta_cost_brl_t", 1e9 if not p["scenario_connected"] else 0)))[:200],
    }
    if base["service"] and scen["service"]:
        kb, ks = base["service"]["kpis"], scen["service"]["kpis"]
        out["service"] = {k: {"base": kb[k], "scenario": ks[k],
                              "delta": round(ks[k] - kb[k], 6) if isinstance(kb[k], int | float) and isinstance(ks[k], int | float) else None}
                          for k in ("facilities_open", "served_t", "unmet_t", "service_level", "transport_cost",
                                    "weighted_avg_km", "coverage_share")}
    elif scen["service"]:
        out["service"] = {k: {"base": None, "scenario": v, "delta": None} for k, v in scen["service"]["kpis"].items()}
    return out


def run_scenario(db: Session, scenario_id: int, rerun_of: int | None = None) -> ScenarioRun:
    sc = db.get(Scenario, scenario_id)
    if sc is None:
        raise LookupError(f"Cenário {scenario_id} inexistente")
    if rerun_of:
        prev = db.get(ScenarioRun, rerun_of)
        if prev is None:
            raise LookupError(f"Execução {rerun_of} inexistente")
        inputs = prev.inputs
        vid = prev.network_version_id
    else:
        vid = sc.network_version_id or latest_version_id(db)
        if vid is None:
            raise ValueError("Nenhuma versão de rede disponível")
        changes = db.scalars(select(ScenarioChange).where(ScenarioChange.scenario_id == sc.id).order_by(ScenarioChange.id)).all()
        inputs = {
            "config": ScenarioConfig.model_validate(sc.config or {}).model_dump(),
            "changes": [{"change_type": c.change_type, "payload": c.payload, "note": c.note} for c in changes],
            "assumptions": load_assumptions(db),
            "network_version_id": vid,
        }
    run = ScenarioRun(scenario_id=sc.id, network_version_id=vid, status="running", inputs=inputs,
                      input_hash=_hash(inputs), rerun_of=rerun_of)
    db.add(run)
    db.commit()
    t = time.perf_counter()
    try:
        g = get_graph(db, vid)
        cfg = ScenarioConfig.model_validate(inputs["config"])
        changes_in = [ChangeIn.model_validate(c) for c in inputs["changes"]]
        base_state = State(assumptions=dict(inputs["assumptions"]), demand=cfg.demand.model_copy(deep=True),
                           services=_service_candidates(db, g, cfg.service_facility_ids, cfg.default_capacity_t,
                                                             inputs["assumptions"].get("capacity.static_turnover_per_year", 4.0)))
        scen_state = apply_changes(db, g, base_state, changes_in, cfg.default_capacity_t)
        base = evaluate(db, g, cfg, base_state)
        scen = evaluate(db, g, cfg, scen_state)
        cmp_ = compare(base, scen)
        _attach_route_edges(base, scen, cmp_)
        for r in (base, scen):
            for p in r["od"]["pairs"]:
                p.pop("_edges", None)
        results = _round({"baseline": base, "scenario": scen, "comparison": cmp_})
        run.results = results
        run.result_hash = result_hash(results)
        run.summary = {
            "od_pairs": base["od"]["totals"].get("pairs", 0),
            "od_pairs_affected": cmp_["od_pairs_affected"],
            "od_pairs_disconnected": cmp_["od_pairs_disconnected"],
            "od_delta_sum_cost_brl": cmp_["od_delta_sum_cost_brl"],
            "closed_edges": scen["closed_edges"],
            "service": {k: v for k, v in (cmp_.get("service") or {}).items()},
        }
        run.status = "success"
    except Exception as exc:
        run.status, run.error = "failed", f"{type(exc).__name__}: {exc}"
        db.commit()
        raise
    finally:
        run.duration_ms = (time.perf_counter() - t) * 1000
        run.finished_at = utcnow()
        db.commit()
    return run


def _attach_route_edges(base: dict[str, Any], scen: dict[str, Any], cmp_: dict[str, Any]) -> None:
    """Para os pares afetados, guarda as arestas das rotas base e cenário (para o mapa)."""
    idx = {(p["origin"], p["dest"]): (b, s) for p, b, s in zip(base["od"]["pairs"], base["od"]["pairs"], scen["od"]["pairs"])}
    for row in cmp_["pairs"][:40]:
        b, s = idx[(row["origin"], row["dest"])]
        row["base_edges"] = b.get("_edges")
        row["scenario_edges"] = s.get("_edges")
