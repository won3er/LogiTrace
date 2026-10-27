"""Topologia do grafo (junções, divisão em T, contração) e validações de ingestão."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, MultiLineString, Point, Polygon

from app.ingestion.common import ValidationReport, as_multiline, as_multipolygon, content_hash, fix_text, validate_line, validate_point
from app.network.builder import Edge, _cluster, _contract, _GraphAccumulator, _topology
from app.network.classes import CLASSES
from app.scenarios.des import simulate_operations


# ------------------------------------------------------------------ ingestão
def test_fix_text_recovers_latin1_and_utf8():
    assert fix_text("SÃ£o Paulo") == "São Paulo"  # UTF-8 lido como latin-1
    assert fix_text("Belém") == "Belém"
    assert fix_text("  ") is None
    assert fix_text(float("nan")) is None


@pytest.mark.parametrize(
    "geom,ok,reason",
    [
        (Point(-46.6, -23.5), True, None),
        (Point(0, 0), False, "(0,0)"),
        (Point(10, 45), False, "fora do território"),
        (None, False, "ausente"),
        (LineString([(-46, -23), (-45, -22)]), False, "Point"),
    ],
)
def test_validate_point(geom, ok, reason):
    r = ValidationReport()
    assert validate_point("x", geom, r) is ok
    if reason:
        assert reason in r.rejected[0]["reason"]


def test_validate_line_rejects_outside_brazil_and_converts_to_multiline():
    r = ValidationReport()
    ml = validate_line(1, LineString([(-46, -23), (-45, -22)]), r)
    assert isinstance(ml, MultiLineString)
    assert validate_line(2, LineString([(5, 40), (6, 41)]), r) is None
    assert r.rejected[0]["ref"] == "2"


def test_as_multipolygon_repairs_invalid_bowtie():
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    assert not bowtie.is_valid
    mp = as_multipolygon(bowtie)
    assert mp is not None and mp.is_valid and mp.area > 0


def test_content_hash_changes_with_attributes_and_geometry():
    h1 = content_hash({"a": 1}, Point(0, 0))
    assert h1 == content_hash({"a": 1}, Point(0, 0))
    assert h1 != content_hash({"a": 2}, Point(0, 0))
    assert h1 != content_hash({"a": 1}, Point(0, 1))
    assert as_multiline(Point(0, 0)) is None


# ------------------------------------------------------------------ topologia
def test_cluster_merges_points_within_tolerance():
    pts = np.array([[0, 0], [100, 0], [100.5, 0.2], [500, 0]])
    labels, centers = _cluster(pts, tol=1.0)
    assert labels[1] == labels[2]
    assert len(set(labels)) == 3
    assert centers[labels[1]][0] == pytest.approx(100.25)


def test_t_junction_splits_line_and_crossing_without_endpoint_does_not():
    # linha horizontal de 0 a 1000 m; uma vertical termina em (500, 0) (junção em T);
    # outra cruza em x=800 sem extremidade comum (viaduto) e não deve virar junção
    gdf = gpd.GeoDataFrame(
        {"id": [1, 2, 3], "surface": ["Pavimentada"] * 3, "jurisdiction": ["federal"] * 3, "code": ["a", "b", "c"]},
        geometry=[LineString([(0, 0), (1000, 0)]), LineString([(500, 0.5), (500, 400)]), LineString([(800, -300), (800, 300)])],
        crs=5880,
    )
    parts, _ = _topology(gdf, tol=2.0, anchors=None, anchor_max=0)
    horiz = [p for src, p in parts if src == 0]
    assert len(horiz) == 2
    assert sorted(round(p.length) for p in horiz) == [500, 500]
    assert len([p for src, p in parts if src == 2]) == 1


def test_anchor_projection_splits_edge_interior():
    gdf = gpd.GeoDataFrame({"id": [1], "surface": ["Duplicada"], "jurisdiction": ["federal"], "code": ["x"]},
                           geometry=[LineString([(0, 0), (10_000, 0)])], crs=5880)
    parts, attach = _topology(gdf, tol=2.0, anchors=np.array([[4000.0, 2000.0]]), anchor_max=5000)
    assert attach[0][0] == pytest.approx((4000.0, 0.0))
    assert len(attach[0]) == 1  # só existe uma via: sem conector secundário
    assert len(parts) == 2


def _edge(u: int, v: int, km: float, coords: list[tuple[float, float]]) -> Edge:
    lbc = np.zeros(len(CLASSES))
    lbc[1] = km
    return Edge(u=u, v=v, modal="road", coords=np.array(coords, dtype=float), len_by_class=lbc, segment_ids=[u * 10 + v])


def test_contract_merges_degree_two_chain_preserving_length():
    acc = _GraphAccumulator()
    acc.add_nodes(np.array([[0, 0], [1, 0], [2, 0], [3, 0]], dtype=float), "junction")
    acc.edges = [_edge(0, 1, 1, [(0, 0), (1, 0)]), _edge(1, 2, 2, [(1, 0), (2, 0)]), _edge(2, 3, 3, [(2, 0), (3, 0)])]
    out = _contract(acc)
    assert len(out) == 1
    assert {out[0].u, out[0].v} == {0, 3}
    assert out[0].len_by_class.sum() == pytest.approx(6)
    assert len(out[0].segment_ids) == 3


def test_contract_keeps_protected_nodes_and_avoids_parallel_edges():
    acc = _GraphAccumulator()
    acc.add_nodes(np.array([[0, 0], [1, 1], [2, 0], [1, -1]], dtype=float), "junction")
    # ciclo 0-1-2-3-0: contrair 1 e 3 geraria duas arestas paralelas 0-2
    acc.edges = [_edge(0, 1, 1, [(0, 0), (1, 1)]), _edge(1, 2, 1, [(1, 1), (2, 0)]),
                 _edge(2, 3, 1, [(2, 0), (1, -1)]), _edge(3, 0, 1, [(1, -1), (0, 0)])]
    acc.protected = {0}
    out = _contract(acc)
    pairs = [tuple(sorted((e.u, e.v))) for e in out]
    assert len(pairs) == len(set(pairs))
    assert sum(e.len_by_class.sum() for e in out) == pytest.approx(4)


# ------------------------------------------------------------------ simulação
def test_des_is_reproducible_and_flags_saturation():
    fac = [{"key": "a", "name": "A", "capacity_t": 365_000, "load_t": 180_000},
           {"key": "b", "name": "B", "capacity_t": 365_000, "load_t": 364_000}]
    r1 = simulate_operations(fac, days=30, seed=7)
    r2 = simulate_operations(fac, days=30, seed=7)
    assert r1 == r2
    a, b = r1["facilities"]
    assert a["dock_utilization"] < b["dock_utilization"]
    assert b["p95_wait_h"] >= a["p95_wait_h"]
