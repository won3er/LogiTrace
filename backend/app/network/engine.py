"""Motor de rede em memória.

Carrega uma versão do grafo em arrays NumPy. Caminhos mínimos e matrizes usam o Dijkstra em C do
SciPy (csgraph); análises estruturais (pontes, articulações, componentes, alternativas) usam NetworkX.
Interrupções são aplicadas como máscaras sobre as arestas, sem alterar a versão base.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Any, Literal

import networkx as nx
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.network.classes import CLASS_INDEX, CLASSES, MODAL_CODES, edge_cost_brl_t, edge_time_h

Metric = Literal["distance", "time", "cost"]

# Penalidade aditiva nos conectores de acesso de municípios e instalações não intermodais.
# Um caminho legítimo usa no máximo um conector em cada extremidade; atravessar um nó-âncora
# (entrar por um conector e sair por outro) somaria mais penalidades e só ocorre se não houver
# alternativa: nesse caso o resultado é decodificado como "sem ligação real".
# Distâncias, tempos e custos reportados vêm sempre das arestas, nunca dos pesos penalizados.
ANCHOR_PENALTY = 1e6
ModalMode = Literal["road", "multimodal"]
METRIC_UNITS = {"distance": "km", "time": "h", "cost": "R$/t"}


@dataclass
class PathResult:
    nodes: list[int]
    edges: list[int]
    distance_km: float
    time_h: float
    cost_brl_t: float
    km_by_modal: dict[str, float]
    transfers: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "distance_km": round(self.distance_km, 2),
            "time_h": round(self.time_h, 2),
            "cost_brl_t": round(self.cost_brl_t, 2),
            "km_by_modal": {k: round(v, 1) for k, v in self.km_by_modal.items() if v > 0},
            "transfers": self.transfers,
            "edge_count": len(self.edges),
        }


@dataclass
class NetworkGraph:
    version_id: int
    u: np.ndarray
    v: np.ndarray
    modal: np.ndarray
    lbc: np.ndarray
    federal_km: np.ndarray
    transfers: np.ndarray
    code: list[str | None]
    segment_ids: list[list[int]]
    node_kind: np.ndarray
    node_ref: np.ndarray
    node_lon: np.ndarray
    node_lat: np.ndarray
    geometry: list[list[list[float]]]
    _pair: dict[tuple[int, int], int] = field(default_factory=dict)
    _mun_node: dict[int, int] = field(default_factory=dict)
    _fac_node: dict[int, int] = field(default_factory=dict)
    _tree: cKDTree | None = None
    _road_nodes: np.ndarray | None = None
    pen_node: np.ndarray | None = None
    pen_edge: np.ndarray | None = None

    # ----------------------------------------------------------------- construção
    @classmethod
    def load(cls, db: Session, version_id: int) -> NetworkGraph:
        nodes = db.execute(
            text(
                "SELECT node_idx, kind, coalesce(ref_id, -1), ST_X(geom), ST_Y(geom) FROM network_node "
                "WHERE version_id = :v ORDER BY node_idx"
            ),
            {"v": version_id},
        ).all()
        edges = db.execute(
            text(
                "SELECT edge_idx, u, v, modal, code, segment_ids, attr_source, "
                "ST_AsGeoJSON(geom, 5)::json->'coordinates' FROM network_edge WHERE version_id = :v ORDER BY edge_idx"
            ),
            {"v": version_id},
        ).all()
        if not nodes or not edges:
            raise LookupError(f"Versão de rede {version_id} inexistente ou vazia")
        lbc = np.zeros((len(edges), len(CLASSES)))
        for i, e in enumerate(edges):
            for k, km in (e[6].get("len_by_class") or {}).items():
                lbc[i, CLASS_INDEX[k]] = km
        g = cls(
            version_id=version_id,
            u=np.array([e[1] for e in edges], dtype=np.int64),
            v=np.array([e[2] for e in edges], dtype=np.int64),
            modal=np.array([MODAL_CODES[e[3]] for e in edges], dtype=np.int8),
            lbc=lbc,
            federal_km=np.array([e[6].get("federal_km", 0.0) for e in edges]),
            transfers=np.array([e[6].get("transfers", 0) for e in edges], dtype=float),
            code=[e[4] for e in edges],
            segment_ids=[list(e[5] or []) for e in edges],
            node_kind=np.array([n[1] for n in nodes]),
            node_ref=np.array([n[2] for n in nodes], dtype=np.int64),
            node_lon=np.array([n[3] for n in nodes]),
            node_lat=np.array([n[4] for n in nodes]),
            geometry=[e[7] if isinstance(e[7], list) else json.loads(e[7]) for e in edges],
        )
        g._index()
        return g

    def _index(self) -> None:
        self._pair = {}
        for i, (a, b) in enumerate(zip(self.u.tolist(), self.v.tolist())):
            self._pair[(a, b)] = i
            self._pair[(b, a)] = i
        self._mun_node = {int(r): i for i, (k, r) in enumerate(zip(self.node_kind, self.node_ref)) if k == "municipality"}
        self._fac_node = {int(r): i for i, (k, r) in enumerate(zip(self.node_kind, self.node_ref)) if k == "facility"}
        tr = self.modal == MODAL_CODES["transfer"]
        intermodal = np.zeros(self.n_nodes, dtype=bool)
        intermodal[self.u[tr]] = True
        intermodal[self.v[tr]] = True
        self.pen_node = (self.node_kind == "municipality") | ((self.node_kind == "facility") & ~intermodal)
        acc = self.modal == MODAL_CODES["access"]
        self.pen_edge = acc & (self.pen_node[self.u] | self.pen_node[self.v])
        road_mask = np.zeros(self.n_nodes, dtype=bool)
        sel = self.modal == MODAL_CODES["road"]
        road_mask[self.u[sel]] = True
        road_mask[self.v[sel]] = True
        self._road_nodes = np.where(road_mask)[0]
        self._tree = cKDTree(np.column_stack([self.node_lon[self._road_nodes], self.node_lat[self._road_nodes] * 1.0]))

    @property
    def n_nodes(self) -> int:
        return len(self.node_kind)

    @property
    def n_edges(self) -> int:
        return len(self.u)

    # ----------------------------------------------------------------- pesos
    def km(self) -> np.ndarray:
        return self.lbc.sum(axis=1)

    def weights(self, metric: Metric, assumptions: dict[str, float]) -> np.ndarray:
        if metric == "distance":
            w = self.km()
        elif metric == "time":
            w = edge_time_h(self.lbc, self.transfers, assumptions)
        else:
            w = edge_cost_brl_t(self.lbc, self.federal_km, self.transfers, assumptions)
        assert self.pen_edge is not None
        return np.maximum(w, 1e-9) + ANCHOR_PENALTY * self.pen_edge

    def decode(self, raw: np.ndarray, src_pen: Any, dst_pen: Any) -> np.ndarray:
        """Remove as penalidades dos conectores; caminhos que atravessam âncoras viram infinito."""
        out = np.array(raw, dtype=float, copy=True)
        fin = np.isfinite(out)
        k = np.zeros_like(out)
        k[fin] = np.floor(out[fin] / ANCHOR_PENALTY + 1e-9)
        out[fin] -= k[fin] * ANCHOR_PENALTY
        allowed = np.broadcast_to(np.asarray(src_pen, dtype=float) + np.asarray(dst_pen, dtype=float), out.shape)
        out[fin & (k > allowed)] = np.inf
        return out

    def sssp(
        self, sources: Any, metric: Metric, assumptions: dict[str, float], mode: ModalMode = "multimodal",
        closed: set[int] | None = None, limit: float | None = None, min_only: bool = False,
        return_predecessors: bool = False, w: np.ndarray | None = None,
    ) -> Any:
        """Dijkstra (SciPy) com decodificação das penalidades de âncora. Retorna distâncias reais na métrica."""
        assert self.pen_node is not None
        w = self.weights(metric, assumptions) if w is None else w
        lim = np.inf if limit is None else limit + 2 * ANCHOR_PENALTY + 1.0
        res = dijkstra(self.csr(w, self.edge_mask(mode, closed)), indices=sources, directed=False, limit=lim,
                       min_only=min_only, return_predecessors=return_predecessors)
        raw = res[0] if return_predecessors else res
        pen = self.pen_node.astype(float)
        if min_only:
            src_pen: Any = float(pen[np.atleast_1d(sources)].max())
            dst_pen: Any = pen
        elif np.ndim(sources) == 0:
            src_pen, dst_pen = float(pen[int(sources)]), pen
        else:
            src_pen, dst_pen = pen[np.asarray(sources)][:, None], pen[None, :]
        dist = self.decode(raw, src_pen, dst_pen)
        if limit is not None:
            dist[dist > limit] = np.inf
        if return_predecessors:
            return (dist, *res[1:])
        return dist

    def path_is_artificial(self, edges: list[int], source: int, target: int) -> bool:
        """True se o caminho atravessa um nó-âncora (usa mais conectores penalizados que as extremidades)."""
        assert self.pen_node is not None and self.pen_edge is not None
        used = int(self.pen_edge[edges].sum()) if edges else 0
        return used > int(self.pen_node[source]) + int(self.pen_node[target])

    def edge_mask(self, mode: ModalMode, closed: set[int] | None = None) -> np.ndarray:
        mask = np.ones(self.n_edges, dtype=bool)
        if mode == "road":
            mask &= np.isin(self.modal, [MODAL_CODES["road"], MODAL_CODES["access"]])
        if closed:
            mask[list(closed)] = False
        return mask

    def csr(self, w: np.ndarray, mask: np.ndarray) -> csr_matrix:
        u, v, ww = self.u[mask], self.v[mask], w[mask]
        n = self.n_nodes
        return csr_matrix((np.concatenate([ww, ww]), (np.concatenate([u, v]), np.concatenate([v, u]))), shape=(n, n))

    # ----------------------------------------------------------------- localização
    def municipality_node(self, code: int) -> int:
        if code not in self._mun_node:
            raise KeyError(f"Município {code} sem nó na rede")
        return self._mun_node[code]

    def facility_node(self, fid: int) -> int:
        if fid not in self._fac_node:
            raise KeyError(f"Instalação {fid} sem nó na rede (cadastrada após a construção da versão?)")
        return self._fac_node[fid]

    def nearest_road_node(self, lon: float, lat: float) -> tuple[int, float]:
        assert self._tree is not None and self._road_nodes is not None
        _, j = self._tree.query([lon, lat])
        node = int(self._road_nodes[j])
        return node, haversine_km(lon, lat, float(self.node_lon[node]), float(self.node_lat[node]))

    def node_of_kind(self, kind: str) -> np.ndarray:
        return np.where(self.node_kind == kind)[0]

    # ----------------------------------------------------------------- caminhos
    def path_from_predecessors(self, pred: np.ndarray, source: int, target: int) -> list[int] | None:
        if source == target:
            return [source]
        if pred[target] < 0:
            return None
        path = [target]
        while path[-1] != source:
            p = int(pred[path[-1]])
            if p < 0:
                return None
            path.append(p)
        return path[::-1]

    def edges_of_path(self, nodes: list[int], w: np.ndarray, mask: np.ndarray) -> list[int]:
        out = []
        for a, b in zip(nodes[:-1], nodes[1:]):
            out.append(self._pair[(a, b)])
        return out

    def summarize(self, edges: list[int], assumptions: dict[str, float]) -> PathResult:
        idx = np.array(edges, dtype=np.int64)
        lbc = self.lbc[idx] if len(idx) else np.zeros((0, len(CLASSES)))
        tm = edge_time_h(lbc, self.transfers[idx], assumptions).sum() if len(idx) else 0.0
        cs = edge_cost_brl_t(lbc, self.federal_km[idx], self.transfers[idx], assumptions).sum() if len(idx) else 0.0
        by_modal: dict[str, float] = {}
        for code, name in ((0, "road"), (1, "rail"), (2, "waterway"), (3, "access")):
            by_modal[name] = float(lbc[self.modal[idx] == code].sum()) if len(idx) else 0.0
        return PathResult(
            nodes=[], edges=edges, distance_km=float(lbc.sum()), time_h=float(tm), cost_brl_t=float(cs),
            km_by_modal=by_modal, transfers=int(self.transfers[idx].sum()) if len(idx) else 0,
        )

    def shortest_path(
        self, source: int, target: int, metric: Metric, assumptions: dict[str, float],
        mode: ModalMode = "multimodal", closed: set[int] | None = None, w: np.ndarray | None = None,
    ) -> PathResult | None:
        w = self.weights(metric, assumptions) if w is None else w
        mask = self.edge_mask(mode, closed)
        _, pred = dijkstra(self.csr(w, mask), indices=source, return_predecessors=True, directed=False)
        nodes = self.path_from_predecessors(pred, source, target)
        if nodes is None:
            return None
        edges = self.edges_of_path(nodes, w, mask)
        if self.path_is_artificial(edges, source, target):
            return None
        res = self.summarize(edges, assumptions)
        res.nodes = nodes
        return res

    def alternatives(
        self, source: int, target: int, metric: Metric, assumptions: dict[str, float], k: int = 3,
        mode: ModalMode = "multimodal", closed: set[int] | None = None, penalty: float = 1.6,
    ) -> list[PathResult]:
        """Rotas alternativas pelo método de penalização: arestas já usadas ficam mais caras.

        Rotas com sobreposição > 90% com uma anterior são descartadas.
        """
        base_w = self.weights(metric, assumptions)
        w = base_w.copy()
        found: list[PathResult] = []
        for _ in range(k * 3):
            p = self.shortest_path(source, target, metric, assumptions, mode, closed, w=w)
            if p is None:
                break
            es = set(p.edges)
            if all(len(es & set(q.edges)) / max(len(es), 1) < 0.9 for q in found):
                found.append(p)
            if len(found) >= k:
                break
            w[list(es)] *= penalty
        return found

    def distance_matrix(
        self, sources: list[int], metric: Metric, assumptions: dict[str, float],
        mode: ModalMode = "multimodal", closed: set[int] | None = None,
    ) -> np.ndarray:
        return self.sssp(sources, metric, assumptions, mode, closed)

    def components(self, mode: ModalMode = "multimodal", closed: set[int] | None = None) -> np.ndarray:
        g = self.csr(np.ones(self.n_edges), self.edge_mask(mode, closed))
        _, labels = connected_components(g, directed=False)
        return labels

    def to_networkx(self, mode: ModalMode = "multimodal", closed: set[int] | None = None) -> nx.Graph:
        mask = self.edge_mask(mode, closed)
        g = nx.Graph()
        g.add_nodes_from(range(self.n_nodes))
        km = self.km()
        for i in np.where(mask)[0]:
            g.add_edge(int(self.u[i]), int(self.v[i]), idx=int(i), km=float(km[i]))
        return g

    def edges_for_segments(self, segment_ids: set[int]) -> set[int]:
        return {i for i, segs in enumerate(self.segment_ids) if segment_ids.intersection(segs)}

    def path_feature(self, edges: list[int], props: dict[str, Any] | None = None, tolerance: float = 0.003) -> dict[str, Any]:
        """Um único MultiLineString simplificado (≈300 m) para exibição; cálculos usam a geometria completa."""
        from shapely.geometry import MultiLineString, mapping

        lines = [self.geometry[e] for e in edges if len(self.geometry[e]) >= 2]
        geom = MultiLineString(lines).simplify(tolerance, preserve_topology=False) if lines else None
        km_by_modal: dict[str, float] = {}
        for e in edges:
            m = _MODAL_NAME[int(self.modal[e])]
            km_by_modal[m] = km_by_modal.get(m, 0.0) + float(self.lbc[e].sum())
        return {"type": "Feature", "geometry": mapping(geom) if geom is not None else None,
                "properties": {"edges": len(edges), "km_by_modal": {k: round(v, 1) for k, v in km_by_modal.items()}, **(props or {})}}

    def path_geojson(self, edges: list[int], props: dict[str, Any] | None = None) -> dict[str, Any]:
        feats = []
        for e in edges:
            feats.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": self.geometry[e]},
                "properties": {"edge": e, "modal": _MODAL_NAME[int(self.modal[e])], "code": self.code[e],
                               "km": round(float(self.lbc[e].sum()), 2), **(props or {})},
            })
        return {"type": "FeatureCollection", "features": feats}


_MODAL_NAME = {v: k for k, v in MODAL_CODES.items()}


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0088
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return float(2 * r * np.arcsin(np.sqrt(a)))


_cache: dict[int, NetworkGraph] = {}
_lock = threading.Lock()


def get_graph(db: Session, version_id: int) -> NetworkGraph:
    with _lock:
        g = _cache.get(version_id)
        if g is None:
            g = NetworkGraph.load(db, version_id)
            _cache.clear()  # mantém uma versão em memória
            _cache[version_id] = g
        return g


def clear_cache() -> None:
    with _lock:
        _cache.clear()
