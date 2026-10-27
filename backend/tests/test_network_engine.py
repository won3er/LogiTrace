"""Cálculo de rotas, alternativas, interrupções, conectividade e consistência de custos no grafo de referência."""

from __future__ import annotations

import networkx as nx
import numpy as np
import pytest

from app.network.classes import edge_cost_brl_t, edge_time_h
from tests.helpers import A, B, C, D, E, M1, M2, assumptions, reference_graph


@pytest.fixture
def g():
    return reference_graph()


def test_shortest_distance_matches_hand_calculation(g):
    p = g.shortest_path(M1, M2, "distance", assumptions())
    assert p is not None
    assert p.nodes == [M1, A, B, C, M2]
    assert p.distance_km == pytest.approx(1 + 10 + 10 + 1)
    assert p.km_by_modal["road"] == pytest.approx(20)
    assert p.km_by_modal["access"] == pytest.approx(2)


def test_time_and_cost_follow_assumptions(g):
    a = assumptions()
    p = g.shortest_path(M1, M2, "time", a)
    # 20 km duplicada a 75 km/h + 2 km de acesso a 40 km/h
    assert p.time_h == pytest.approx(20 / a["speed.road.duplicada"] + 2 / a["speed.access"])
    # custo: 22 km × R$ 0,20/t·km (pedágio padrão zero)
    assert p.cost_brl_t == pytest.approx(22 * a["cost.road.brl_tkm"])


def test_toll_applies_only_to_federal_km(g):
    a = assumptions(**{"cost.toll.brl_tkm": 0.05})
    p = g.shortest_path(M1, M2, "cost", a)
    assert p.cost_brl_t == pytest.approx(22 * 0.20 + 20 * 0.05)


def test_interruption_reroutes_and_increases_cost(g):
    a = assumptions()
    closed = g.edges_for_segments({101})  # A–B
    assert closed == {0}
    p = g.shortest_path(M1, M2, "distance", a, closed=closed)
    assert p.nodes == [M1, A, D, C, M2]
    assert p.distance_km == pytest.approx(1 + 15 + 15 + 1)


def test_interruption_can_disconnect(g):
    closed = g.edges_for_segments({105})  # C–E é ponte
    assert g.shortest_path(M1, E, "distance", assumptions(), closed=closed) is None
    labels = g.components("road", closed)
    assert labels[E] != labels[A]


def test_alternatives_are_distinct_and_ordered(g):
    alts = g.alternatives(M1, M2, "distance", assumptions(), k=3)
    assert len(alts) == 2  # só existem dois caminhos simples A→C
    assert alts[0].distance_km < alts[1].distance_km
    assert set(alts[0].edges) != set(alts[1].edges)


def test_distance_matrix_symmetry(g):
    m = g.distance_matrix([M1, M2], "distance", assumptions())
    assert m[0, M2] == pytest.approx(22)
    assert m[1, M1] == pytest.approx(22)


def test_bridges_detected_with_networkx(g):
    G = g.to_networkx("road")
    bridges = {tuple(sorted(b)) for b in nx.bridges(G)}
    assert (C, E) in bridges
    assert (A, B) not in bridges


def test_vectorized_cost_matches_sum_of_edges(g):
    a = assumptions(**{"cost.road.brl_tkm": 0.3, "cost.road.unpaved_factor": 2.0})
    costs = edge_cost_brl_t(g.lbc, g.federal_km, g.transfers, a)
    times = edge_time_h(g.lbc, g.transfers, a)
    p = g.summarize([0, 1], a)
    assert p.cost_brl_t == pytest.approx(costs[[0, 1]].sum())
    assert p.time_h == pytest.approx(times[[0, 1]].sum())
    assert np.all(costs > 0)


def test_nearest_road_node(g):
    node, km = g.nearest_road_node(0.181, 0.001)
    assert node == C
    assert km < 1


def test_anchor_with_two_connectors_is_not_a_shortcut():
    """Duas vias desconectadas (ex.: margens de um rio) ligadas só pelos conectores de um município."""
    from app.network.classes import CLASS_INDEX, CLASSES, MODAL_CODES
    from app.network.engine import NetworkGraph

    edges = [(0, 1, "road_pavimentada", 10.0), (2, 3, "road_pavimentada", 10.0), (4, 1, "access", 2.0), (4, 2, "access", 2.0)]
    lbc = np.zeros((len(edges), len(CLASSES)))
    for i, (_, _, c, km) in enumerate(edges):
        lbc[i, CLASS_INDEX[c]] = km
    g = NetworkGraph(
        version_id=0, u=np.array([e[0] for e in edges]), v=np.array([e[1] for e in edges]),
        modal=np.array([MODAL_CODES["access" if e[2] == "access" else "road"] for e in edges], dtype=np.int8),
        lbc=lbc, federal_km=np.zeros(4), transfers=np.zeros(4), code=[None] * 4, segment_ids=[[1], [2], [], []],
        node_kind=np.array(["junction"] * 4 + ["municipality"]), node_ref=np.array([-1] * 4 + [1]),
        node_lon=np.array([0.0, 0.1, 0.2, 0.3, 0.15]), node_lat=np.zeros(5),
        geometry=[[[0, 0], [0.1, 0]], [[0.2, 0], [0.3, 0]], [[0.15, 0], [0.1, 0]], [[0.15, 0], [0.2, 0]]],
    )
    g._index()
    a = assumptions()
    assert g.shortest_path(0, 3, "distance", a) is None  # atravessar o município não é rota real
    assert g.shortest_path(4, 3, "distance", a).distance_km == pytest.approx(12)  # mas o município alcança as duas vias
    m = g.distance_matrix([0, 4], "distance", a)
    assert np.isinf(m[0, 3]) and m[1, 3] == pytest.approx(12) and m[1, 0] == pytest.approx(12)
