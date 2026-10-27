"""Grafo de referência pequeno, com resultados calculáveis à mão.

        B(10,0)
   10 /        \\ 10          A–B 10 km, B–C 10 km (duplicada)
  A(0,0)        C(20,0) — 5 — E    A–D 15 km, D–C 15 km (pavimentada)
   15 \\        / 15         C–E 5 km (ponte: única ligação de E)
        D(10,-5)
  M1 = município ligado a A por conector de 1 km; M2 ligado a C por conector de 1 km.
"""

from __future__ import annotations

import numpy as np

from app.core.assumptions import DEFAULTS
from app.network.classes import CLASS_INDEX, CLASSES, MODAL_CODES
from app.network.engine import NetworkGraph

A, B, C, D, E, M1, M2 = range(7)
EDGES = [  # (u, v, classe, km)
    (A, B, "road_duplicada", 10.0),
    (B, C, "road_duplicada", 10.0),
    (A, D, "road_pavimentada", 15.0),
    (D, C, "road_pavimentada", 15.0),
    (C, E, "road_pavimentada", 5.0),
    (M1, A, "access", 1.0),
    (M2, C, "access", 1.0),
]
COORDS = [(0.0, 0.0), (0.09, 0.0), (0.18, 0.0), (0.09, -0.045), (0.225, 0.0), (-0.01, 0.0), (0.19, 0.0)]


def assumptions(**over: float) -> dict[str, float]:
    a = {d["key"]: float(d["value"]) for d in DEFAULTS}
    a.update(over)
    return a


def reference_graph() -> NetworkGraph:
    lbc = np.zeros((len(EDGES), len(CLASSES)))
    for i, (_, _, cls, km) in enumerate(EDGES):
        lbc[i, CLASS_INDEX[cls]] = km
    g = NetworkGraph(
        version_id=0,
        u=np.array([e[0] for e in EDGES]),
        v=np.array([e[1] for e in EDGES]),
        modal=np.array([MODAL_CODES["access" if e[2] == "access" else "road"] for e in EDGES], dtype=np.int8),
        lbc=lbc,
        federal_km=np.array([e[3] if e[2] == "road_duplicada" else 0.0 for e in EDGES]),
        transfers=np.zeros(len(EDGES)),
        code=["001BSP0010", "001BSP0020", "002ESP0010", "002ESP0020", "003ESP0010", None, None],
        segment_ids=[[101], [102], [103], [104], [105], [], []],
        node_kind=np.array(["junction"] * 5 + ["municipality"] * 2),
        node_ref=np.array([-1] * 5 + [1000001, 1000002]),
        node_lon=np.array([c[0] for c in COORDS]),
        node_lat=np.array([c[1] for c in COORDS]),
        geometry=[[list(COORDS[e[0]]), list(COORDS[e[1]])] for e in EDGES],
    )
    g._index()
    return g
