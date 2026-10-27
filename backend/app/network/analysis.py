"""Análises estruturais da rede: conectividade, pontes, articulações e criticidade por uso/impacto."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import networkx as nx
import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.network.engine import Metric, ModalMode, NetworkGraph

CAPITALS = [
    1100205, 1200401, 1302603, 1400100, 1501402, 1600303, 1721000, 2111300, 2211001, 2304400, 2408102,
    2507507, 2611606, 2704302, 2800308, 2927408, 3106200, 3205309, 3304557, 3550308, 4106902, 4205407,
    4314902, 5002704, 5103403, 5208707, 5300108,
]


def municipality_info(db: Session, codes: list[int] | None = None) -> dict[int, dict[str, Any]]:
    sql = "SELECT code, name, uf, population FROM municipality"
    params: dict[str, Any] = {}
    if codes is not None:
        sql += " WHERE code = ANY(:c)"
        params["c"] = codes
    return {r.code: {"name": r.name, "uf": r.uf, "population": r.population or 0} for r in db.execute(text(sql), params)}


def connectivity(db: Session, g: NetworkGraph, mode: ModalMode, closed: set[int] | None = None) -> dict[str, Any]:
    labels = g.components(mode, closed)
    mun_nodes = g.node_of_kind("municipality")
    counts = np.bincount(labels[mun_nodes], minlength=labels.max() + 1)
    main = int(counts.argmax())
    info = municipality_info(db)
    isolated: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for n in mun_nodes:
        if labels[n] != main:
            code = int(g.node_ref[n])
            m = info.get(code, {})
            isolated[int(labels[n])].append({"code": code, "name": m.get("name"), "uf": m.get("uf"), "population": m.get("population", 0)})
    groups = sorted(
        ({"component": k, "municipalities": v, "population": sum(x["population"] for x in v)} for k, v in isolated.items()),
        key=lambda x: -x["population"],
    )
    total_pop = sum(m["population"] for m in info.values())
    off_pop = sum(gr["population"] for gr in groups)
    return {
        "mode": mode,
        "components_total": int(labels.max() + 1),
        "components_with_municipalities": int((counts > 0).sum()),
        "main_component_municipalities": int(counts[main]),
        "municipalities_outside_main": int(len(mun_nodes) - counts[main]),
        "population_outside_main": off_pop,
        "population_outside_main_share": round(off_pop / max(total_pop, 1), 5),
        "isolated_groups": groups[:100],
        "note": ("Componentes fora do principal incluem municípios sem rodovia mapeada na base IBGE 2014 "
                 "(ex.: acesso apenas fluvial/aéreo) e ilhas."),
    }


def bridges(db: Session, g: NetworkGraph, mode: ModalMode = "road", top: int = 50) -> list[dict[str, Any]]:
    """Pontes do grafo: arestas cuja remoção separa a rede. Ordenadas pela população isolada."""
    G = g.to_networkx(mode)
    br = list(nx.bridges(G))
    H = G.copy()
    H.remove_edges_from(br)
    comp_of: dict[int, int] = {}
    for k, comp in enumerate(nx.connected_components(H)):
        for n in comp:
            comp_of[n] = k
    pop_by_comp: dict[int, int] = defaultdict(int)
    mun_by_comp: dict[int, int] = defaultdict(int)
    info = municipality_info(db)
    for n in g.node_of_kind("municipality"):
        c = comp_of[int(n)]
        pop_by_comp[c] += info.get(int(g.node_ref[n]), {}).get("population", 0)
        mun_by_comp[c] += 1
    T = nx.Graph()
    for a, b in br:
        T.add_edge(comp_of[a], comp_of[b], edge=G[a][b]["idx"])
    out = []
    for tree in (T.subgraph(c) for c in nx.connected_components(T)):
        root = max(tree.nodes, key=lambda c: pop_by_comp[c])
        sub_pop: dict[int, int] = {}
        sub_mun: dict[int, int] = {}
        for node in nx.dfs_postorder_nodes(tree, root):
            sub_pop[node] = pop_by_comp[node] + sum(sub_pop[ch] for ch in tree.neighbors(node) if ch in sub_pop and ch != node)
            sub_mun[node] = mun_by_comp[node] + sum(sub_mun[ch] for ch in tree.neighbors(node) if ch in sub_mun and ch != node)
        parent = dict(nx.bfs_predecessors(tree, root))
        for child, par in parent.items():
            e = tree[child][par]["edge"]
            if sub_mun[child] == 0:
                continue
            out.append({
                "edge": int(e), "code": g.code[e], "km": round(float(g.lbc[e].sum()), 2),
                "isolated_municipalities": int(sub_mun[child]), "isolated_population": int(sub_pop[child]),
                "lon": float(np.mean([p[0] for p in g.geometry[e]])), "lat": float(np.mean([p[1] for p in g.geometry[e]])),
            })
    out.sort(key=lambda x: -x["isolated_population"])
    return out[:top]


def articulation_points(db: Session, g: NetworkGraph, mode: ModalMode = "road", top: int = 30) -> list[dict[str, Any]]:
    G = g.to_networkx(mode)
    G.remove_nodes_from([int(n) for n in g.node_of_kind("municipality")])
    pts = list(nx.articulation_points(G))
    deg = dict(G.degree(pts))
    pts.sort(key=lambda n: -deg[n])
    return [{"node": int(n), "degree": int(deg[n]), "lon": float(g.node_lon[n]), "lat": float(g.node_lat[n])} for n in pts[:top]]


def od_benchmark(db: Session, g: NetworkGraph, codes: list[int] | None = None) -> tuple[list[int], np.ndarray, dict[int, dict[str, Any]]]:
    codes = [c for c in (codes or CAPITALS) if c in g._mun_node]
    info = municipality_info(db, codes)
    pop = np.array([info[c]["population"] for c in codes], dtype=float)
    weight = np.outer(pop, pop)
    np.fill_diagonal(weight, 0)
    weight = np.triu(weight)
    weight /= weight.sum()
    return codes, weight, info


def edge_usage(g: NetworkGraph, nodes: list[int], weight: np.ndarray, metric: Metric, a: dict[str, float],
               mode: ModalMode, closed: set[int] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Carrega cada par OD (peso gravitacional) no menor caminho e acumula o uso por aresta."""
    w = g.weights(metric, a)
    mask = g.edge_mask(mode, closed)
    dist, pred = g.sssp(nodes, metric, a, mode, closed, return_predecessors=True, w=w)
    usage = np.zeros(g.n_edges)
    n = len(nodes)
    for i in range(n):
        for j in range(i + 1, n):
            if weight[i, j] <= 0 or not np.isfinite(dist[i, nodes[j]]):
                continue
            path = g.path_from_predecessors(pred[i], nodes[i], nodes[j])
            if path:
                usage[g.edges_of_path(path, w, mask)] += weight[i, j]
    return usage, dist[:, nodes]


def criticality(db: Session, g: NetworkGraph, a: dict[str, float], metric: Metric = "cost", mode: ModalMode = "road",
                top_k: int = 15, codes: list[int] | None = None) -> dict[str, Any]:
    codes, weight, info = od_benchmark(db, g, codes)
    nodes = [g.municipality_node(c) for c in codes]
    usage, base = edge_usage(g, nodes, weight, metric, a, mode)
    ranked = np.argsort(-usage)
    results = []
    for e in ranked[:top_k]:
        if usage[e] <= 0:
            break
        _, alt = edge_usage(g, nodes, weight, metric, a, mode, closed={int(e)})
        iu = np.triu_indices(len(nodes), 1)
        b, c = base[iu], alt[iu]
        wt = weight[iu]
        disconnected = np.isfinite(b) & ~np.isfinite(c)
        both = np.isfinite(b) & np.isfinite(c)
        delta = float(((c[both] - b[both]) * wt[both]).sum() / max(wt[both].sum(), 1e-12))
        affected = int((both & (c > b + 1e-9)).sum())
        results.append({
            "edge": int(e), "code": g.code[e], "modal": ["road", "rail", "waterway", "access", "transfer"][int(g.modal[e])],
            "km": round(float(g.lbc[e].sum()), 2), "usage_share": round(float(usage[e]), 5),
            "affected_pairs": affected, "disconnected_pairs": int(disconnected.sum()),
            "weighted_delta": round(delta, 4), "weighted_base": round(float((b[np.isfinite(b)] * wt[np.isfinite(b)]).sum()), 4),
            "segment_ids": g.segment_ids[e][:20],
            "lon": float(np.mean([p[0] for p in g.geometry[e]])), "lat": float(np.mean([p[1] for p in g.geometry[e]])),
        })
    return {
        "metric": metric, "mode": mode, "od_set": [{"code": c, **info[c]} for c in codes],
        "method": ("Pares OD entre capitais com peso gravitacional (pop_i × pop_j). Uso = soma dos pesos dos pares "
                   "cujo menor caminho passa pela aresta. Impacto = variação média ponderada do custo dos pares "
                   "quando a aresta é removida e as rotas são recalculadas."),
        "edges": results,
    }
