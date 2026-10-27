"""Modelos de otimização logística com OR-Tools.

Cada função retorna um `Solution` com o status do solver traduzido para a qualidade da solução:
  OPTIMAL     solução comprovadamente ótima (gap nulo dentro da tolerância do solver)
  FEASIBLE    solução viável sem prova de otimalidade (limite de tempo); informa o gap
  HEURISTIC   solução de metaheurística (roteamento), sem limitante inferior
  INFEASIBLE  modelo sem solução viável
  NOT_SOLVED  solver não encontrou solução no tempo
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from ortools.linear_solver import pywraplp

from app.optimization.data import ProblemData

BIG = 1e12


@dataclass
class Solution:
    problem: str
    quality: str
    solver: str
    objective: str
    objective_value: float | None
    best_bound: float | None
    gap: float | None
    solve_time_ms: float
    constraints: list[str]
    assumptions: list[str]
    results: dict[str, Any] = field(default_factory=dict)


def _status(solver: pywraplp.Solver, status: int, mip: bool) -> tuple[str, float | None, float | None, float | None]:
    if status == pywraplp.Solver.OPTIMAL:
        obj = solver.Objective().Value()
        bound = solver.Objective().BestBound() if mip else obj
        return "OPTIMAL", obj, bound, 0.0
    if status == pywraplp.Solver.FEASIBLE:
        obj = solver.Objective().Value()
        bound = solver.Objective().BestBound()
        gap = abs(obj - bound) / max(abs(obj), 1e-9)
        return "FEASIBLE", obj, bound, gap
    if status == pywraplp.Solver.INFEASIBLE:
        return "INFEASIBLE", None, None, None
    return "NOT_SOLVED", None, None, None


def _mip(name: str, time_limit_s: float) -> pywraplp.Solver:
    s = pywraplp.Solver.CreateSolver(name)
    if s is None:
        raise RuntimeError(f"Solver {name} indisponível")
    s.SetTimeLimit(int(time_limit_s * 1000))
    if name == "SCIP":
        s.SetSolverSpecificParametersAsString("randomization/randomseedshift = 0\n")
    return s


def _assignment(pd_: ProblemData, open_idx: list[int]) -> dict[str, Any]:
    """Atribui cada demanda à instalação aberta de menor custo e calcula indicadores."""
    d = np.array([p.demand_t for p in pd_.demand])
    sub = pd_.cost[open_idx]
    best = np.argmin(sub, axis=0)
    c = sub[best, np.arange(len(d))]
    km = pd_.km[open_idx][best, np.arange(len(d))]
    ok = np.isfinite(c)
    return {
        "assign": [open_idx[b] if ok[i] else None for i, b in enumerate(best)],
        "unit_cost": c,
        "km": km,
        "total_cost": float((c[ok] * d[ok]).sum()),
        "weighted_km": float((km[ok] * d[ok]).sum() / max(d[ok].sum(), 1e-9)),
    }


def _report(pd_: ProblemData, open_idx: list[int], flows: np.ndarray | None, coverage_km: float | None) -> dict[str, Any]:
    d = np.array([p.demand_t for p in pd_.demand])
    if flows is None:
        a = _assignment(pd_, open_idx)
        flows = np.zeros((len(pd_.candidates), len(d)))
        for i, j in enumerate(a["assign"]):
            if j is not None:
                flows[j, i] = d[i]
    served = flows.sum(axis=0)
    with np.errstate(invalid="ignore"):
        trans_cost = float(np.nansum(np.where(flows > 0, flows * pd_.cost, 0)))
        km_w = float(np.nansum(np.where(flows > 0, flows * pd_.km, 0)) / max(served.sum(), 1e-9))
    facilities = []
    for j in open_idx:
        c = pd_.candidates[j]
        load = float(flows[j].sum())
        facilities.append({
            "key": c.key, "name": c.name, "uf": c.uf, "lon": c.lon, "lat": c.lat,
            "facility_id": c.facility_id, "municipality_code": c.municipality_code,
            "capacity_t": c.capacity_t, "capacity_source": c.capacity_source, "load_t": round(load, 2),
            "utilization": round(load / c.capacity_t, 4) if c.capacity_t else None,
            "fixed_cost": c.fixed_cost, "demand_points": int((flows[j] > 1e-6).sum()),
        })
    demand_rows = []
    for i, p in enumerate(pd_.demand):
        js = np.where(flows[:, i] > 1e-6)[0]
        main = int(js[np.argmax(flows[js, i])]) if len(js) else None
        demand_rows.append({
            "key": p.key, "name": p.name, "uf": p.uf, "lon": p.lon, "lat": p.lat, "demand_t": round(p.demand_t, 2),
            "served_t": round(float(served[i]), 2), "unmet_t": round(float(p.demand_t - served[i]), 2),
            "facility": pd_.candidates[main].key if main is not None else None,
            "km": round(float(pd_.km[main, i]), 1) if main is not None and np.isfinite(pd_.km[main, i]) else None,
            "unit_cost": round(float(pd_.cost[main, i]), 4) if main is not None and np.isfinite(pd_.cost[main, i]) else None,
        })
    covered = None
    if coverage_km is not None:
        km_open = pd_.km[open_idx] if open_idx else np.full((1, len(d)), np.inf)
        within = (km_open <= coverage_km).any(axis=0)
        covered = float(d[within].sum() / max(d.sum(), 1e-9))
    return {
        "open_facilities": facilities,
        "demand": demand_rows,
        "kpis": {
            "facilities_open": len(open_idx),
            "total_demand_t": round(float(d.sum()), 2),
            "served_t": round(float(served.sum()), 2),
            "unmet_t": round(float(d.sum() - served.sum()), 2),
            "service_level": round(float(served.sum() / max(d.sum(), 1e-9)), 4),
            "transport_cost": round(trans_cost, 2),
            "fixed_cost": round(sum(pd_.candidates[j].fixed_cost for j in open_idx), 2),
            "weighted_avg_km": round(km_w, 1),
            "coverage_share": round(covered, 4) if covered is not None else None,
            "coverage_km": coverage_km,
        },
        "excluded_demand": pd_.excluded_demand,
    }


def p_median(pd_: ProblemData, p: int, time_limit_s: float, coverage_km: float | None = None,
             forced_open: list[int] | None = None) -> Solution:
    nC, nD = pd_.cost.shape
    if p < 1 or p > nC:
        raise ValueError(f"p deve estar entre 1 e {nC}")
    d = np.array([x.demand_t for x in pd_.demand])
    s = _mip("SCIP", time_limit_s)
    y = [s.BoolVar(f"y{j}") for j in range(nC)]
    x: dict[tuple[int, int], Any] = {}
    for i in range(nD):
        reach = [j for j in range(nC) if np.isfinite(pd_.cost[j, i])]
        for j in reach:
            x[j, i] = s.NumVar(0, 1, f"x{j}_{i}")
            s.Add(x[j, i] <= y[j])
        s.Add(sum(x[j, i] for j in reach) == 1)
    s.Add(sum(y) == p)
    for j in forced_open or []:
        s.Add(y[j] == 1)
    s.Minimize(sum(float(d[i] * pd_.cost[j, i]) * var for (j, i), var in x.items()))
    t = time.perf_counter()
    st = s.Solve()
    ms = (time.perf_counter() - t) * 1000
    quality, obj, bound, gap = _status(s, st, mip=True)
    res: dict[str, Any] = {}
    if obj is not None:
        open_idx = [j for j in range(nC) if y[j].solution_value() > 0.5]
        res = _report(pd_, open_idx, None, coverage_km)
    return Solution(
        problem="p_median", quality=quality, solver="SCIP (MIP)",
        objective=f"Minimizar Σ demanda × custo unitário ({pd_.metric}) até a instalação atribuída",
        objective_value=obj, best_bound=bound, gap=gap, solve_time_ms=ms,
        constraints=[
            "Cada ponto de demanda é atendido integralmente por instalações abertas",
            f"Exatamente p = {p} instalações abertas",
            "Atribuição apenas a instalações abertas (x ≤ y)",
            "Sem restrição de capacidade (modelo não capacitado)",
            *(["Instalações pré-existentes forçadas a permanecer abertas"] if forced_open else []),
        ],
        assumptions=[], results=res,
    )


def capacitated(pd_: ProblemData, time_limit_s: float, max_open: int | None, unmet_penalty: float,
                coverage_km: float | None = None, forced_open: list[int] | None = None,
                single_sourcing: bool = False) -> Solution:
    nC, nD = pd_.cost.shape
    d = np.array([x.demand_t for x in pd_.demand])
    s = _mip("SCIP", time_limit_s)
    y = [s.BoolVar(f"y{j}") for j in range(nC)]
    x: dict[tuple[int, int], Any] = {}
    u = [s.NumVar(0, 1, f"u{i}") for i in range(nD)]
    for i in range(nD):
        for j in range(nC):
            if np.isfinite(pd_.cost[j, i]):
                x[j, i] = s.BoolVar(f"x{j}_{i}") if single_sourcing else s.NumVar(0, 1, f"x{j}_{i}")
                s.Add(x[j, i] <= y[j])
        s.Add(sum(x[j, i] for j in range(nC) if (j, i) in x) + u[i] == 1)
    for j in range(nC):
        s.Add(sum(float(d[i]) * x[j, i] for i in range(nD) if (j, i) in x) <= pd_.candidates[j].capacity_t * y[j])
    if max_open:
        s.Add(sum(y) <= max_open)
    for j in forced_open or []:
        s.Add(y[j] == 1)
    s.Minimize(
        sum(pd_.candidates[j].fixed_cost * y[j] for j in range(nC))
        + sum(float(d[i] * pd_.cost[j, i]) * var for (j, i), var in x.items())
        + sum(unmet_penalty * float(d[i]) * u[i] for i in range(nD))
    )
    t = time.perf_counter()
    st = s.Solve()
    ms = (time.perf_counter() - t) * 1000
    quality, obj, bound, gap = _status(s, st, mip=True)
    res: dict[str, Any] = {}
    if obj is not None:
        open_idx = [j for j in range(nC) if y[j].solution_value() > 0.5]
        flows = np.zeros((nC, nD))
        for (j, i), var in x.items():
            flows[j, i] = var.solution_value() * d[i]
        res = _report(pd_, open_idx, flows, coverage_km)
    return Solution(
        problem="capacitated_location", quality=quality, solver="SCIP (MIP)",
        objective="Minimizar custo fixo das instalações + custo de transporte + penalidade por demanda não atendida",
        objective_value=obj, best_bound=bound, gap=gap, solve_time_ms=ms,
        constraints=[
            "Fluxo atribuído a cada instalação ≤ capacidade × abertura",
            "Demanda atendida + demanda não atendida = demanda total de cada ponto",
            f"Penalidade de R$ {unmet_penalty:,.2f} por t não atendida (torna explícito o trade-off)",
            *( [f"No máximo {max_open} instalações abertas"] if max_open else []),
            "Fonte única por ponto de demanda" if single_sourcing else "Atendimento fracionado permitido",
        ],
        assumptions=[], results=res,
    )


def max_coverage(pd_: ProblemData, p: int, coverage_km: float, time_limit_s: float,
                 forced_open: list[int] | None = None) -> Solution:
    nC, nD = pd_.cost.shape
    d = np.array([x.demand_t for x in pd_.demand])
    cover = pd_.km <= coverage_km
    s = _mip("SCIP", time_limit_s)
    y = [s.BoolVar(f"y{j}") for j in range(nC)]
    z = [s.NumVar(0, 1, f"z{i}") for i in range(nD)]
    for i in range(nD):
        js = np.where(cover[:, i])[0]
        s.Add(z[i] <= sum(y[int(j)] for j in js) if len(js) else z[i] <= 0)
    s.Add(sum(y) == p)
    for j in forced_open or []:
        s.Add(y[j] == 1)
    s.Maximize(sum(float(d[i]) * z[i] for i in range(nD)))
    t = time.perf_counter()
    st = s.Solve()
    ms = (time.perf_counter() - t) * 1000
    quality, obj, bound, gap = _status(s, st, mip=True)
    res: dict[str, Any] = {}
    if obj is not None:
        open_idx = [j for j in range(nC) if y[j].solution_value() > 0.5]
        res = _report(pd_, open_idx, None, coverage_km)
    return Solution(
        problem="max_coverage", quality=quality, solver="SCIP (MIP)",
        objective=f"Maximizar a demanda a até {coverage_km:.0f} km (distância na rede) de uma instalação aberta",
        objective_value=obj, best_bound=bound, gap=gap, solve_time_ms=ms,
        constraints=[f"Exatamente p = {p} instalações abertas",
                     "Ponto coberto somente se houver instalação aberta dentro do raio"],
        assumptions=["A atribuição pós-otimização segue a instalação aberta de menor custo"], results=res,
    )


def transportation(pd_: ProblemData, open_idx: list[int], unmet_penalty: float,
                   coverage_km: float | None = None) -> Solution:
    """Alocação de demanda (problema de transporte) como LP: solução ótima comprovada pelo GLOP."""
    nD = len(pd_.demand)
    d = np.array([x.demand_t for x in pd_.demand])
    s = pywraplp.Solver.CreateSolver("GLOP")
    x: dict[tuple[int, int], Any] = {}
    u = [s.NumVar(0, float(d[i]), f"u{i}") for i in range(nD)]
    for j in open_idx:
        for i in range(nD):
            if np.isfinite(pd_.cost[j, i]):
                x[j, i] = s.NumVar(0, s.infinity(), f"x{j}_{i}")
    for i in range(nD):
        s.Add(sum(x[j, i] for j in open_idx if (j, i) in x) + u[i] == float(d[i]))
    cap_cons = {}
    for j in open_idx:
        cap_cons[j] = s.Add(sum(x[j, i] for i in range(nD) if (j, i) in x) <= pd_.candidates[j].capacity_t)
    s.Minimize(sum(float(pd_.cost[j, i]) * v for (j, i), v in x.items()) + sum(unmet_penalty * ui for ui in u))
    t = time.perf_counter()
    st = s.Solve()
    ms = (time.perf_counter() - t) * 1000
    quality, obj, bound, gap = _status(s, st, mip=False)
    res: dict[str, Any] = {}
    if obj is not None:
        flows = np.zeros(pd_.cost.shape)
        for (j, i), v in x.items():
            flows[j, i] = v.solution_value()
        res = _report(pd_, open_idx, flows, coverage_km)
        # preço-sombra da capacidade: quanto o custo total cairia por t adicional de capacidade
        for f, j in zip(res["open_facilities"], open_idx):
            f["capacity_shadow_price"] = round(-cap_cons[j].dual_value(), 4)
            f["binding"] = f["utilization"] is not None and f["utilization"] >= 0.999
    return Solution(
        problem="transportation", quality=quality, solver="GLOP (LP)",
        objective="Minimizar custo de transporte + penalidade por demanda não atendida",
        objective_value=obj, best_bound=bound, gap=gap, solve_time_ms=ms,
        constraints=["Capacidade de cada instalação", "Balanço de demanda com variável de não atendimento",
                     f"Penalidade de R$ {unmet_penalty:,.2f} por t não atendida"],
        assumptions=[], results=res,
    )


def vrp(dist_km: np.ndarray, demands: list[float], vehicles: int, capacity: float, time_limit_s: float,
        max_route_km: float | None = None) -> Solution:
    """Roteamento capacitado (CVRP) a partir do depósito (índice 0): metaheurística do OR-Tools."""
    n = len(dist_km)
    scale = 10  # resolução de 0,1 km
    big = int(1e9)
    m = np.where(np.isfinite(dist_km), np.round(dist_km * scale), big).astype(np.int64)
    manager = pywrapcp.RoutingIndexManager(n, vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    def dist_cb(a: int, b: int) -> int:
        return int(m[manager.IndexToNode(a), manager.IndexToNode(b)])

    cb = routing.RegisterTransitCallback(dist_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(cb)
    dem = [0, *[int(math.ceil(q)) for q in demands]]
    dcb = routing.RegisterUnaryTransitCallback(lambda i: dem[manager.IndexToNode(i)])
    routing.AddDimensionWithVehicleCapacity(dcb, 0, [int(capacity)] * vehicles, True, "Capacity")
    if max_route_km:
        routing.AddDimension(cb, 0, int(max_route_km * scale), True, "Distance")
    for node in range(1, n):
        routing.AddDisjunction([manager.NodeToIndex(node)], big // 100)
    prm = pywrapcp.DefaultRoutingSearchParameters()
    prm.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    prm.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    prm.time_limit.FromMilliseconds(int(time_limit_s * 1000))
    t = time.perf_counter()
    sol = routing.SolveWithParameters(prm)
    ms = (time.perf_counter() - t) * 1000
    if sol is None:
        return Solution("vrp", "NOT_SOLVED", "OR-Tools Routing", "Minimizar distância total", None, None, None, ms, [], [])
    routes = []
    visited: set[int] = set()
    total = 0.0
    for vh in range(vehicles):
        idx = routing.Start(vh)
        seq: list[int] = []
        km = 0.0
        load = 0
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            seq.append(node)
            load += dem[node]
            nxt = sol.Value(routing.NextVar(idx))
            km += dist_cb(idx, nxt) / scale
            idx = nxt
        seq.append(0)
        if len(seq) > 2:
            routes.append({"vehicle": vh, "sequence": seq, "km": round(km, 1), "load": load})
            visited.update(seq)
            total += km
    dropped = [i for i in range(1, n) if i not in visited]
    return Solution(
        problem="vrp", quality="HEURISTIC", solver="OR-Tools Routing (Guided Local Search)",
        objective="Minimizar a distância total percorrida na rede (km)", objective_value=round(total, 1),
        best_bound=None, gap=None, solve_time_ms=ms,
        constraints=[f"{vehicles} veículos de capacidade {capacity:g}", "Rotas iniciam e terminam no depósito",
                     *( [f"Distância máxima por rota: {max_route_km:g} km"] if max_route_km else []),
                     "Clientes podem ser descartados com penalidade alta se inviáveis"],
        assumptions=["Distâncias = menor caminho na rede entre os pontos (simétricas)",
                     "Solução heurística: não há prova de otimalidade"],
        results={"routes": routes, "dropped": dropped},
    )
