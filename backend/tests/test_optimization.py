"""Otimização: casos pequenos com ótimo conhecido, restrições de capacidade e consistência de custos."""

from __future__ import annotations

import numpy as np
import pytest

from app.optimization.data import Candidate, DemandPoint, ProblemData
from app.optimization.solvers import capacitated, max_coverage, p_median, transportation, vrp


def _problem(cost: list[list[float]], demand: list[float], caps: list[float] | None = None, fixed: list[float] | None = None) -> ProblemData:
    c = np.array(cost, dtype=float)
    cands = [Candidate(key=f"c{j}", name=f"C{j}", uf="SP", node=j, lon=0, lat=0,
                       capacity_t=(caps or [1e9] * len(c))[j], fixed_cost=(fixed or [0] * len(c))[j]) for j in range(len(c))]
    dem = [DemandPoint(key=f"d{i}", name=f"D{i}", uf="SP", node=100 + i, lon=0, lat=0, population=0,
                       demand_t=demand[i], municipalities=1) for i in range(len(demand))]
    return ProblemData(demand=dem, candidates=cands, cost=c, km=c.copy())


# custos (candidato x demanda). Ótimo com p=1: C1 (10*1 + 10*1 + 10*2 = 40 contra C0: 0+10*5+10*9 = 140)
COST = [[0.0, 5.0, 9.0], [1.0, 1.0, 2.0], [9.0, 5.0, 0.0]]
DEM = [10.0, 10.0, 10.0]


def test_p_median_p1_known_optimum():
    s = p_median(_problem(COST, DEM), 1, time_limit_s=10)
    assert s.quality == "OPTIMAL"
    assert s.objective_value == pytest.approx(40.0)
    assert [f["key"] for f in s.results["open_facilities"]] == ["c1"]


def test_p_median_p2_known_optimum():
    # p=2: {C0, C2} => 0 + min(5,5)*10 + 0 = 50 ; {C1,C2} => 10+10+0 = 20 ; {C0,C1} => 0+10+20 = 30
    s = p_median(_problem(COST, DEM), 2, time_limit_s=10)
    assert s.objective_value == pytest.approx(20.0)
    assert sorted(f["key"] for f in s.results["open_facilities"]) == ["c1", "c2"]


def test_capacitated_respects_capacity_and_reports_unmet():
    pd_ = _problem(COST, DEM, caps=[12, 12, 0.0], fixed=[0, 0, 0])
    s = capacitated(pd_, time_limit_s=10, max_open=None, unmet_penalty=1000)
    assert s.quality == "OPTIMAL"
    for f in s.results["open_facilities"]:
        assert f["load_t"] <= f["capacity_t"] + 1e-6
    k = s.results["kpis"]
    assert k["served_t"] == pytest.approx(24, abs=1e-4)
    assert k["unmet_t"] == pytest.approx(6, abs=1e-4)


def test_capacitated_fixed_cost_tradeoff():
    # abrir C1 custa 100: é mais barato atender tudo por C0 e C2 (custo 50) do que por C1 (20 + 100)
    s = capacitated(_problem(COST, DEM, fixed=[0, 100, 0]), time_limit_s=10, max_open=None, unmet_penalty=1000)
    assert sorted(f["key"] for f in s.results["open_facilities"]) == ["c0", "c2"]
    assert s.objective_value == pytest.approx(50.0)


def test_max_coverage_known_optimum():
    km = [[0, 50, 300], [400, 400, 400], [300, 50, 0]]
    pd_ = _problem(km, [10, 1, 10])
    s = max_coverage(pd_, p=1, coverage_km=100, time_limit_s=10)
    assert s.objective_value == pytest.approx(11.0)  # C0 ou C2 cobrem 10 + 1


def test_transportation_cost_consistency_and_shadow_price():
    pd_ = _problem(COST, DEM, caps=[15, 1e9, 15])
    s = transportation(pd_, [0, 1, 2], unmet_penalty=1000)
    assert s.quality == "OPTIMAL"
    # cada demanda vai ao candidato de menor custo: D0->C0 (0), D1->C1 (1), D2->C2 (0) => 10
    assert s.objective_value == pytest.approx(10.0)
    k = s.results["kpis"]
    assert k["transport_cost"] == pytest.approx(s.objective_value)
    assert k["unmet_t"] == pytest.approx(0)


def test_transportation_capacity_binding_raises_cost():
    pd_ = _problem(COST, DEM, caps=[5, 1e9, 15])
    s = transportation(pd_, [0, 1, 2], unmet_penalty=1000)
    # D0: 5 t por C0 (0) + 5 t por C1 (1) => 5 ; D1 por C1 => 10 ; D2 por C2 => 0
    assert s.objective_value == pytest.approx(15.0)
    c0 = next(f for f in s.results["open_facilities"] if f["key"] == "c0")
    assert c0["utilization"] == pytest.approx(1.0)
    assert c0["capacity_shadow_price"] == pytest.approx(1.0)  # cada t extra em C0 economiza R$ 1


def test_vrp_is_heuristic_and_respects_capacity():
    d = np.array([[0, 10, 10, 20], [10, 0, 15, 15], [10, 15, 0, 15], [20, 15, 15, 0]], dtype=float)
    s = vrp(d, demands=[10, 10, 10], vehicles=2, capacity=20, time_limit_s=2)
    assert s.quality == "HEURISTIC"
    visited = {n for r in s.results["routes"] for n in r["sequence"] if n}
    assert visited == {1, 2, 3}
    assert all(r["load"] <= 20 for r in s.results["routes"])
