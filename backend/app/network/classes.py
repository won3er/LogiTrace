"""Classes de comprimento das arestas e cálculo vetorizado de tempo/custo sob um conjunto de premissas.

Cada aresta guarda quantos km possui em cada classe (ex.: 12 km duplicada + 3 km pavimentada).
Assim, tempo e custo são recalculados para qualquer conjunto de premissas sem reconstruir a rede.
"""

from __future__ import annotations

import numpy as np

CLASSES = [
    "road_duplicada",
    "road_pavimentada",
    "road_obras_duplicacao",
    "road_obras_pavimentacao",
    "road_implantada",
    "road_leito_natural",
    "road_travessia",
    "road_desconhecida",
    "rail",
    "waterway",
    "access",
]
CLASS_INDEX = {c: i for i, c in enumerate(CLASSES)}

# TipoPNV (SNV/IBGE) -> classe. Trechos 'Planejada' e 'Em obras de implantação' não existem fisicamente.
SURFACE_TO_CLASS = {
    "Duplicada": "road_duplicada",
    "Pavimentada": "road_pavimentada",
    "Em obras de duplicação": "road_obras_duplicacao",
    "Em obras de pavimentação": "road_obras_pavimentacao",
    "Implantada": "road_implantada",
    "Leito Natural": "road_leito_natural",
    "Travessia": "road_travessia",
}
EXCLUDED_SURFACES = {"Planejada", "Em obras de implantação"}

MODAL_CODES = {"road": 0, "rail": 1, "waterway": 2, "access": 3, "transfer": 4}
MODAL_NAMES = {v: k for k, v in MODAL_CODES.items()}


def class_speeds(a: dict[str, float]) -> np.ndarray:
    return np.array(
        [
            a["speed.road.duplicada"],
            a["speed.road.pavimentada"],
            a["speed.road.obras"],
            a["speed.road.obras"],
            a["speed.road.implantada"],
            a["speed.road.leito_natural"],
            a["speed.road.travessia"],
            a["speed.road.desconhecida"],
            a["speed.rail"],
            a["speed.waterway"],
            a["speed.access"],
        ],
        dtype=float,
    )


def class_costs(a: dict[str, float]) -> np.ndarray:
    road = a["cost.road.brl_tkm"]
    unpaved = road * a["cost.road.unpaved_factor"]
    return np.array(
        [road, road, road, unpaved, unpaved, unpaved, road, road,
         a["cost.rail.brl_tkm"], a["cost.waterway.brl_tkm"], road],
        dtype=float,
    )


def edge_time_h(len_by_class: np.ndarray, transfers: np.ndarray, a: dict[str, float]) -> np.ndarray:
    return len_by_class @ (1.0 / class_speeds(a)) + transfers * a["time.transfer.h"]


def edge_cost_brl_t(
    len_by_class: np.ndarray, federal_km: np.ndarray, transfers: np.ndarray, a: dict[str, float]
) -> np.ndarray:
    money = len_by_class @ class_costs(a) + federal_km * a["cost.toll.brl_tkm"] + transfers * a["cost.transfer.brl_t"]
    vot = a.get("cost.value_of_time.brl_th", 0.0)
    if vot:
        money = money + vot * edge_time_h(len_by_class, transfers, a)
    return money
