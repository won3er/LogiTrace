"""Construção do grafo logístico multimodal a partir dos segmentos importados.

Etapas (por modal, em EPSG:5880 - SIRGAS 2000 / Brazil Polyconic, em metros):
 1. Segmentos válidos (exclui rodovias planejadas/em implantação e ferrovias urbanas de passageiros).
 2. Agrupamento de extremidades próximas (tolerância configurável) => nós.
 3. Extremidades soltas próximas ao interior de outra linha => divisão da linha (junção em T).
 4. Pontos de ancoragem (municípios e instalações) projetados sobre a rodovia mais próxima.
 5. Conectores de acesso (modal 'access') e transbordos intermodais (modal 'transfer').
 6. Contração de nós de grau 2 do mesmo modal, preservando nós de ancoragem.
Cruzamentos sem extremidade comum NÃO viram junção (evita falsas conexões em viadutos).
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import geopandas as gpd
import numpy as np
import shapely
from pyproj import Transformer
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from shapely.geometry import LineString
from shapely.ops import substring
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.assumptions import load_assumptions
from app.db.session import get_engine
from app.models import ImportRun, NetworkVersion
from app.network.classes import (
    CLASS_INDEX,
    CLASSES,
    EXCLUDED_SURFACES,
    SURFACE_TO_CLASS,
    edge_cost_brl_t,
    edge_time_h,
)

log = logging.getLogger("logitrace.network")

SECOND_ACCESS_M = 15_000
INTERMODAL_CATEGORIES = {"porto", "terminal_portuario", "porto_seco", "terminal_ferroviario"}
TO_WGS84 = Transformer.from_crs(5880, 4326, always_xy=True)


@dataclass
class Edge:
    u: int
    v: int
    modal: str
    coords: np.ndarray  # (n,2) em metros, orientado u->v
    len_by_class: np.ndarray
    federal_km: float = 0.0
    transfers: int = 0
    segment_ids: list[int] = field(default_factory=list)
    code: str | None = None
    surface: str | None = None


def _cluster(points: np.ndarray, tol: float) -> tuple[np.ndarray, np.ndarray]:
    """Agrupa pontos a menos de `tol` metros (fecho transitivo). Retorna rótulos e centróides."""
    tree = cKDTree(points)
    pairs = tree.query_pairs(r=tol, output_type="ndarray")
    n = len(points)
    if len(pairs):
        g = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
        _, labels = connected_components(g, directed=False)
    else:
        labels = np.arange(n)
    k = labels.max() + 1
    cx = np.bincount(labels, weights=points[:, 0], minlength=k) / np.bincount(labels, minlength=k)
    cy = np.bincount(labels, weights=points[:, 1], minlength=k) / np.bincount(labels, minlength=k)
    return labels, np.column_stack([cx, cy])


def _load_segments(db: Session) -> gpd.GeoDataFrame:
    sql = text(
        """
        SELECT id, modal, code, surface, jurisdiction, attributes, geom
        FROM infra_segment
        WHERE record_class = 'official' AND modal IN ('road','rail','waterway')
        """
    )
    gdf = gpd.read_postgis(sql, get_engine(), geom_col="geom")
    gdf = gdf[~gdf["surface"].isin(EXCLUDED_SURFACES)]
    urban = gdf["attributes"].apply(lambda a: bool(a and a.get("urbano_passageiros")))
    gdf = gdf[~((gdf["modal"] == "rail") & urban)]
    gdf = gdf.explode(index_parts=False).reset_index(drop=True)
    gdf = gdf.to_crs(5880)
    return gdf[~gdf.geometry.is_empty & (gdf.geometry.length > 1.0)]


def _split_lines(
    geoms: list[LineString], splits: dict[int, list[float]], min_gap: float
) -> list[tuple[int, LineString]]:
    out: list[tuple[int, LineString]] = []
    for i, g in enumerate(geoms):
        cuts = splits.get(i)
        if not cuts:
            out.append((i, g))
            continue
        L = g.length
        ds = sorted({round(d, 1) for d in cuts if min_gap < d < L - min_gap})
        bounds = [0.0, *ds, L]
        for a, b in zip(bounds[:-1], bounds[1:]):
            if b - a > 0.5:
                part = substring(g, a, b)
                if isinstance(part, LineString) and part.length > 0.5:
                    out.append((i, part))
    return out


def _topology(
    gdf: gpd.GeoDataFrame, tol: float, anchors: np.ndarray | None, anchor_max: float
) -> tuple[list[tuple[int, LineString]], dict[int, list[tuple[float, float]]]]:
    """Retorna partes de linha já divididas e, para cada âncora, os pontos de ligação na rede (1 ou 2)."""
    geoms: list[LineString] = list(gdf.geometry.values)
    starts = shapely.get_coordinates(shapely.get_point(np.array(geoms), 0))
    ends = shapely.get_coordinates(shapely.get_point(np.array(geoms), -1))
    pts = np.vstack([starts, ends])
    labels, _ = _cluster(pts, tol)
    counts = np.bincount(labels)
    n = len(geoms)
    owner = np.concatenate([np.arange(n), np.arange(n)])
    dangling = np.where(counts[labels] == 1)[0]

    tree = shapely.STRtree(geoms)
    splits: dict[int, list[float]] = defaultdict(list)
    if len(dangling):
        dpts = shapely.points(pts[dangling])
        pi, li = tree.query(dpts, predicate="dwithin", distance=tol)
        best: dict[int, tuple[float, int]] = {}
        for p, l in zip(pi, li):
            if owner[dangling[p]] == l:
                continue
            d = shapely.distance(dpts[p], geoms[l])
            if p not in best or d < best[p][0]:
                best[p] = (d, l)
        for p, (_, l) in best.items():
            splits[l].append(float(shapely.line_locate_point(geoms[l], dpts[p])))

    attach: dict[int, list[tuple[float, float]]] = {}
    if anchors is not None and len(anchors):
        apts = shapely.points(anchors)

        def project(a: int, li: int) -> tuple[float, float]:
            g = geoms[li]
            s_ = float(shapely.line_locate_point(g, apts[a]))
            if 300 < s_ < g.length - 300:
                splits[li].append(s_)
                p = g.interpolate(s_)
                return (p.x, p.y)
            return g.coords[0] if s_ <= 300 else g.coords[-1]

        idx, _ = tree.query_nearest(apts, max_distance=anchor_max, return_distance=True, all_matches=False)
        first: dict[int, int] = {}
        for a, li in zip(*idx):
            if int(a) not in first:
                first[int(a)] = int(li)
                attach[int(a)] = [project(int(a), int(li))]
        # Conector secundário: via distinta a até SECOND_ACCESS_M, com ponto de ligação a > 2 km do primeiro.
        # Evita que a interdição de um único trecho isole artificialmente o município/instalação.
        pi, li = tree.query(apts, predicate="dwithin", distance=SECOND_ACCESS_M)
        d = shapely.distance(apts[pi], np.array(geoms, dtype=object)[li])
        best: dict[int, tuple[float, int]] = {}
        for a, l_, dist in zip(pi.tolist(), li.tolist(), d.tolist()):
            if a not in first or l_ == first[a]:
                continue
            g = geoms[l_]
            proj = g.interpolate(float(shapely.line_locate_point(g, apts[a])))
            if np.hypot(proj.x - attach[a][0][0], proj.y - attach[a][0][1]) < 2000:
                continue
            if a not in best or dist < best[a][0]:
                best[a] = (dist, l_)
        for a, (_, l_) in best.items():
            attach[a].append(project(a, l_))
    parts = _split_lines(geoms, splits, min_gap=1.0)
    return parts, attach


def _road_class(surface: str | None) -> int:
    return CLASS_INDEX[SURFACE_TO_CLASS.get(surface or "", "road_desconhecida")]


class _GraphAccumulator:
    def __init__(self) -> None:
        self.node_xy: list[tuple[float, float]] = []
        self.node_kind: list[str] = []
        self.node_ref: list[int | None] = []
        self.edges: list[Edge] = []
        self.protected: set[int] = set()

    def add_nodes(self, xy: np.ndarray, kind: str, refs: list[int | None] | None = None) -> int:
        off = len(self.node_xy)
        self.node_xy.extend(map(tuple, xy))
        self.node_kind.extend([kind] * len(xy))
        self.node_ref.extend(refs if refs is not None else [None] * len(xy))
        return off


def _mode_graph(
    acc: _GraphAccumulator, gdf: gpd.GeoDataFrame, modal: str, tol: float,
    anchors: np.ndarray | None = None, anchor_max: float = 0.0,
) -> tuple[cKDTree | None, int, dict[int, list[int]]]:
    if gdf.empty:
        log.warning("nenhum segmento do modal %s: modal ausente do grafo", modal)
        return None, len(acc.node_xy), {}
    parts, attach = _topology(gdf, tol, anchors, anchor_max)
    pg = [p for _, p in parts]
    s = shapely.get_coordinates(shapely.get_point(np.array(pg), 0))
    e = shapely.get_coordinates(shapely.get_point(np.array(pg), -1))
    labels, centers = _cluster(np.vstack([s, e]), tol)
    off = acc.add_nodes(centers, "junction")
    n = len(pg)
    rows = gdf.reset_index(drop=True)
    for k, (src, geom) in enumerate(parts):
        u, v = off + int(labels[k]), off + int(labels[k + n])
        if u == v:
            continue  # laço degenerado após o agrupamento
        r = rows.iloc[src]
        lbc = np.zeros(len(CLASSES))
        km = geom.length / 1000.0
        if modal == "road":
            lbc[_road_class(r["surface"])] = km
        else:
            lbc[CLASS_INDEX[modal]] = km
        coords = np.asarray(geom.coords)[:, :2].copy()
        coords[0], coords[-1] = centers[labels[k]], centers[labels[k + n]]
        acc.edges.append(
            Edge(
                u=u, v=v, modal=modal, coords=coords, len_by_class=lbc,
                federal_km=km if (modal == "road" and r["jurisdiction"] == "federal") else 0.0,
                segment_ids=[int(r["id"])], code=r["code"], surface=r["surface"] if modal == "road" else None,
            )
        )
    tree = cKDTree(centers)
    att_nodes: dict[int, list[int]] = {}
    for a, xys in attach.items():
        nodes = []
        for xy in xys:
            _, j = tree.query(xy)
            if off + int(j) not in nodes:
                nodes.append(off + int(j))
        att_nodes[a] = nodes
    return tree, off, att_nodes


def _connector(acc: _GraphAccumulator, a: int, b: int, modal: str, factor: float, transfer: bool) -> None:
    pa, pb = np.array(acc.node_xy[a]), np.array(acc.node_xy[b])
    km = float(np.linalg.norm(pa - pb)) / 1000.0 * factor
    lbc = np.zeros(len(CLASSES))
    lbc[CLASS_INDEX["access"]] = max(km, 0.01)
    acc.edges.append(
        Edge(u=a, v=b, modal=modal, coords=np.vstack([pa, pb]), len_by_class=lbc, transfers=1 if transfer else 0)
    )
    acc.protected.update((a, b))


def _contract(acc: _GraphAccumulator) -> list[Edge]:
    """Remove nós de grau 2 (mesmo modal) fundindo arestas; mantém o grafo simples (sem paralelas)."""
    edges: dict[int, Edge | None] = dict(enumerate(acc.edges))
    inc: dict[int, set[int]] = defaultdict(set)
    pair: dict[tuple[int, int], int] = {}
    for i, ed in list(edges.items()):
        assert ed is not None
        key = (min(ed.u, ed.v), max(ed.u, ed.v))
        if key in pair:
            # aresta paralela: mantém ambas inserindo um nó intermediário na segunda
            mid = len(ed.coords) // 2 if len(ed.coords) > 2 else None
            if mid is None:
                c = (ed.coords[0] + ed.coords[-1]) / 2
                ed.coords = np.vstack([ed.coords[0], c, ed.coords[-1]])
                mid = 1
            m = acc.add_nodes(ed.coords[mid : mid + 1], "junction")
            seglen = np.linalg.norm(np.diff(ed.coords, axis=0), axis=1)
            frac = float(seglen[:mid].sum() / seglen.sum()) if seglen.sum() > 0 else 0.5
            second = Edge(
                u=m, v=ed.v, modal=ed.modal, coords=ed.coords[mid:].copy(),
                len_by_class=ed.len_by_class * (1 - frac), federal_km=ed.federal_km * (1 - frac),
                transfers=0, segment_ids=list(ed.segment_ids), code=ed.code, surface=ed.surface,
            )
            ed.coords, ed.v = ed.coords[: mid + 1].copy(), m
            ed.len_by_class = ed.len_by_class * frac
            ed.federal_km *= frac
            j = len(edges)
            edges[j] = second
            for k_, e_ in ((i, ed), (j, second)):
                inc[e_.u].add(k_)
                inc[e_.v].add(k_)
                pair[(min(e_.u, e_.v), max(e_.u, e_.v))] = k_
            continue
        pair[key] = i
        inc[ed.u].add(i)
        inc[ed.v].add(i)

    for node in list(inc.keys()):
        if node in acc.protected or len(inc[node]) != 2:
            continue
        i, j = tuple(inc[node])
        a, b = edges[i], edges[j]
        if a is None or b is None or a.modal != b.modal or a.modal in ("access", "transfer"):
            continue
        ca = a.coords if a.v == node else a.coords[::-1]
        cb = b.coords if b.u == node else b.coords[::-1]
        x = a.u if a.v == node else a.v
        y = b.v if b.u == node else b.u
        if x == y or (min(x, y), max(x, y)) in pair:
            continue  # evitaria laço ou aresta paralela
        merged = Edge(
            u=x, v=y, modal=a.modal, coords=np.vstack([ca, cb[1:]]),
            len_by_class=a.len_by_class + b.len_by_class, federal_km=a.federal_km + b.federal_km,
            segment_ids=sorted(set(a.segment_ids) | set(b.segment_ids)),
            code=a.code if a.code == b.code else (a.code or b.code),
            surface=a.surface if a.surface == b.surface else "mista",
        )
        k = len(edges)
        edges[k] = merged
        edges[i] = edges[j] = None
        del pair[(min(a.u, a.v), max(a.u, a.v))]
        del pair[(min(b.u, b.v), max(b.u, b.v))]
        pair[(min(x, y), max(x, y))] = k
        inc[x].discard(i)
        inc[x].add(k)
        inc[y].discard(j)
        inc[y].add(k)
        inc[node] = set()
    return [e for e in edges.values() if e is not None]


def build_network(db: Session, label: str = "Rede multimodal IBGE 2014") -> NetworkVersion:
    t0 = time.perf_counter()
    a = load_assumptions(db)
    tol = a["network.snap_tolerance_m"]
    access_max = a["network.access_max_km"] * 1000
    transfer_max = a["network.transfer_radius_km"] * 1000
    detour = a["network.access_detour_factor"]

    version = NetworkVersion(label=label, status="building", assumptions=a,
                             params={"snap_tolerance_m": tol, "access_max_km": a["network.access_max_km"],
                                     "transfer_radius_km": a["network.transfer_radius_km"], "crs_metric": 5880})
    db.add(version)
    db.flush()

    seg = _load_segments(db)
    mun = gpd.read_postgis(
        text("SELECT code, centroid AS geom FROM municipality ORDER BY code"), get_engine(), geom_col="geom"
    ).to_crs(5880)
    fac = gpd.read_postgis(
        text("SELECT id, category, geom FROM facility WHERE record_class IN ('official','user') ORDER BY id"),
        get_engine(), geom_col="geom",
    ).to_crs(5880)

    mun_xy = shapely.get_coordinates(mun.geometry.values)
    fac_xy = shapely.get_coordinates(fac.geometry.values)
    anchors = np.vstack([mun_xy, fac_xy])

    acc = _GraphAccumulator()
    _, _, road_attach = _mode_graph(acc, seg[seg.modal == "road"], "road", tol, anchors, access_max)
    rail_tree, rail_off, _ = _mode_graph(acc, seg[seg.modal == "rail"], "rail", tol)
    water_tree, water_off, _ = _mode_graph(acc, seg[seg.modal == "waterway"], "waterway", tol)

    mun_off = acc.add_nodes(mun_xy, "municipality", [int(c) for c in mun.code])
    fac_off = acc.add_nodes(fac_xy, "facility", [int(i) for i in fac.id])
    n_mun = len(mun_xy)
    unconnected = {"municipality": 0, "facility": 0}
    dual_access = 0
    for ai in range(len(anchors)):
        node = mun_off + ai if ai < n_mun else fac_off + (ai - n_mun)
        targets = road_attach.get(ai)
        if not targets:
            unconnected["municipality" if ai < n_mun else "facility"] += 1
            continue
        for target in targets:
            _connector(acc, node, target, "access", detour, transfer=False)
        if len(targets) > 1:
            dual_access += 1

    transfers = 0
    for k, row in enumerate(fac.itertuples()):
        if row.category not in INTERMODAL_CATEGORIES:
            continue
        node = fac_off + k
        for tree, off in ((rail_tree, rail_off), (water_tree, water_off)):
            if tree is None:
                continue
            d, j = tree.query(fac_xy[k])
            if d <= transfer_max:
                _connector(acc, node, off + int(j), "transfer", detour, transfer=True)
                transfers += 1

    edges = _contract(acc)
    used = sorted({e.u for e in edges} | {e.v for e in edges} | set(range(mun_off, len(acc.node_xy))))
    remap = {old: new for new, old in enumerate(used)}

    # Persistência via COPY
    nx_, ny_ = TO_WGS84.transform(np.array([acc.node_xy[i][0] for i in used]), np.array([acc.node_xy[i][1] for i in used]))
    degree = defaultdict(int)
    for e in edges:
        degree[remap[e.u]] += 1
        degree[remap[e.v]] += 1
    lbc = np.array([e.len_by_class for e in edges])
    fed = np.array([e.federal_km for e in edges])
    trn = np.array([e.transfers for e in edges], dtype=float)
    times = edge_time_h(lbc, trn, a)
    costs = edge_cost_brl_t(lbc, fed, trn, a)
    conn = db.connection().connection.driver_connection
    assert conn is not None
    h = hashlib.sha256()
    with conn.cursor() as cur:
        with cur.copy("COPY network_node (version_id, node_idx, kind, ref_id, degree, geom) FROM STDIN") as cp:
            for new, old in enumerate(used):
                ref = acc.node_ref[old]
                cp.write_row((version.id, new, acc.node_kind[old], ref, degree[new],
                              f"SRID=4326;POINT({nx_[new]:.6f} {ny_[new]:.6f})"))
        with cur.copy(
            "COPY network_edge (version_id, edge_idx, u, v, modal, segment_ids, code, surface, length_km, "
            "speed_kmh, time_h, cost_brl_t, capacity, attr_source, geom) FROM STDIN"
        ) as cp:
            for i, e in enumerate(edges):
                lon, lat = TO_WGS84.transform(e.coords[:, 0], e.coords[:, 1])
                wkt = "SRID=4326;LINESTRING(" + ",".join(f"{x:.5f} {y:.5f}" for x, y in zip(lon, lat)) + ")"
                km = float(lbc[i].sum())
                attrs = {
                    "len_by_class": {CLASSES[c]: round(float(v), 4) for c, v in enumerate(lbc[i]) if v > 0},
                    "federal_km": round(float(fed[i]), 4), "transfers": int(trn[i]),
                    "geometry": "importada" if e.modal in ("road", "rail", "waterway") else "conector sintético (linha reta × fator)",
                }
                u, v = remap[e.u], remap[e.v]
                h.update(f"{u},{v},{e.modal},{km:.4f};".encode())
                cp.write_row((version.id, i, u, v, e.modal, _json(e.segment_ids), e.code, e.surface, km,
                              km / times[i] if times[i] > 0 else None, float(times[i]), float(costs[i]), None,
                              _json(attrs), wkt))

    runs = [r for (r,) in db.execute(select(ImportRun.id).where(ImportRun.status.in_(["success", "partial"])))]
    modal_km: dict[str, float] = defaultdict(float)
    for i, e in enumerate(edges):
        modal_km[e.modal] += float(lbc[i].sum())
    version.node_count = len(used)
    version.edge_count = len(edges)
    version.import_runs = runs
    version.checksum = h.hexdigest()
    version.stats = {
        "km_by_modal": {k: round(v, 1) for k, v in modal_km.items()},
        "unconnected_anchors": unconnected,
        "anchors_with_two_connectors": dual_access,
        "transfer_edges": transfers,
        "facilities_anchored": int(len(fac)),
        "build_seconds": round(time.perf_counter() - t0, 1),
    }
    version.status = "ready"
    db.flush()
    log.info("rede %s construída: %s nós, %s arestas", version.id, version.node_count, version.edge_count)
    return version


def _json(v: Any) -> str:
    import json

    return json.dumps(v, ensure_ascii=False)


from app.network.versions import latest_version_id  # noqa: E402,F401
