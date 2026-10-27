"""Simulação de eventos discretos (SimPy) da operação diária das instalações.

Complementa a alocação (LP, que trabalha com médias anuais) mostrando o efeito de filas quando a
utilização se aproxima da capacidade. Modelo:
  - chegadas de unidades de carga seguem processo de Poisson com taxa = carga anual alocada / 365;
  - cada instalação tem k docas; cada doca processa uma unidade de carga em tempo fixo;
  - k é dimensionado pela capacidade anual (premissa: operação 24 h/dia).
Semente fixa => resultados reprodutíveis.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import simpy

DOCK_HOURS_PER_DAY = 24.0
BASE_UNIT_T = 25.0  # carga de uma carreta
MAX_UNITS_PER_DAY = 150  # agrega unidades para limitar o custo computacional


def _simulate_one(load_t: float, capacity_t: float, days: int, rng: np.random.Generator) -> dict[str, Any]:
    daily_load = load_t / 365.0
    daily_cap = capacity_t / 365.0
    unit_t = max(BASE_UNIT_T, daily_load / MAX_UNITS_PER_DAY, daily_cap / MAX_UNITS_PER_DAY)
    docks = max(1, round(daily_cap / unit_t / DOCK_HOURS_PER_DAY))
    # tempo de serviço calibrado para que k docas processem exatamente a capacidade diária
    service_h = docks * DOCK_HOURS_PER_DAY * unit_t / daily_cap
    rate_per_h = daily_load / unit_t / 24.0
    horizon = days * 24.0
    env = simpy.Environment()
    res = simpy.Resource(env, capacity=docks)
    waits: list[float] = []
    busy = [0.0]
    queue_max = [0]

    def unit(arrival: float):  # type: ignore[no-untyped-def]
        with res.request() as req:
            queue_max[0] = max(queue_max[0], len(res.queue))
            yield req
            waits.append(env.now - arrival)
            yield env.timeout(service_h)
            busy[0] += service_h

    def source():  # type: ignore[no-untyped-def]
        if rate_per_h <= 0:
            return
        while True:
            yield env.timeout(float(rng.exponential(1.0 / rate_per_h)))
            env.process(unit(env.now))

    env.process(source())
    env.run(until=horizon)
    w = np.array(waits) if waits else np.zeros(1)
    return {
        "docks": docks,
        "unit_t": round(unit_t, 1),
        "service_h": round(service_h, 3),
        "units_served": len(waits),
        "dock_utilization": round(min(busy[0] / (docks * horizon), 1.0), 4),
        "avg_wait_h": round(float(w.mean()), 2),
        "p95_wait_h": round(float(np.percentile(w, 95)), 2),
        "max_queue": int(queue_max[0]),
        "queue_at_end": len(res.queue),
    }


def simulate_operations(facilities: list[dict[str, Any]], days: int = 60, seed: int = 42) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    rows = []
    for f in facilities:
        if not f.get("capacity_t") or f.get("load_t", 0) <= 0:
            continue
        r = _simulate_one(float(f["load_t"]), float(f["capacity_t"]), days, rng)
        r.update({"key": f["key"], "name": f["name"],
                  "bottleneck": r["p95_wait_h"] > 24 or r["queue_at_end"] > r["docks"] * 24})
        rows.append(r)
    return {
        "method": "SimPy — chegadas Poisson, k docas, serviço determinístico calibrado pela capacidade",
        "days": days, "seed": seed,
        "assumptions": [f"Operação {DOCK_HOURS_PER_DAY:.0f} h/dia", f"Unidade de carga mínima {BASE_UNIT_T:.0f} t",
                        "Nº de docas ≈ capacidade diária ÷ (unidade × 24 h); tempo de serviço ajustado para reproduzir a capacidade",
                        "Sem sazonalidade"],
        "facilities": rows,
    }
