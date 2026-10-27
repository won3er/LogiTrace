"""Premissas paramétricas padrão.

Nenhuma destas grandezas foi observada nas bases importadas: são parâmetros de referência
explicitamente identificados, persistidos na tabela `assumption`, exibidos na interface e
sobrescrevíveis por cenário. Toda execução registra o conjunto de premissas usado.
"""

from __future__ import annotations

from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Assumption


class AssumptionDef(TypedDict):
    key: str
    value: float
    unit: str
    category: str
    description: str
    rationale: str


_ORDER = "Ordem de grandeza de referência, não derivada de fonte oficial; ajuste com dados próprios."

DEFAULTS: list[AssumptionDef] = [
    # Velocidades médias de caminhão por condição da via (TipoPNV do SNV/IBGE)
    {"key": "speed.road.duplicada", "value": 75, "unit": "km/h", "category": "velocidade",
     "description": "Velocidade média de caminhão em rodovia duplicada",
     "rationale": "Inferior ao limite legal de 90 km/h para veículos de carga, considerando travessias urbanas e rampas. " + _ORDER},
    {"key": "speed.road.pavimentada", "value": 60, "unit": "km/h", "category": "velocidade",
     "description": "Velocidade média de caminhão em pista simples pavimentada",
     "rationale": "Pista simples com ultrapassagens restritas. " + _ORDER},
    {"key": "speed.road.obras", "value": 40, "unit": "km/h", "category": "velocidade",
     "description": "Velocidade média em trechos em obras (duplicação/pavimentação)",
     "rationale": "Redução por desvios e sinalização de obra. " + _ORDER},
    {"key": "speed.road.implantada", "value": 35, "unit": "km/h", "category": "velocidade",
     "description": "Velocidade média em rodovia implantada (não pavimentada, com leito construído)",
     "rationale": _ORDER},
    {"key": "speed.road.leito_natural", "value": 25, "unit": "km/h", "category": "velocidade",
     "description": "Velocidade média em leito natural",
     "rationale": "Sujeita a intrafegabilidade sazonal não modelada. " + _ORDER},
    {"key": "speed.road.travessia", "value": 10, "unit": "km/h", "category": "velocidade",
     "description": "Velocidade equivalente em travessias (balsas)",
     "rationale": "Inclui espera média de embarque. " + _ORDER},
    {"key": "speed.road.desconhecida", "value": 50, "unit": "km/h", "category": "velocidade",
     "description": "Velocidade para trechos sem classificação de superfície",
     "rationale": _ORDER},
    {"key": "speed.rail", "value": 25, "unit": "km/h", "category": "velocidade",
     "description": "Velocidade comercial média do trem de carga",
     "rationale": "Velocidades comerciais de ferrovias de carga no Brasil costumam ficar na faixa de 20–30 km/h. " + _ORDER},
    {"key": "speed.waterway", "value": 12, "unit": "km/h", "category": "velocidade",
     "description": "Velocidade média de comboio hidroviário",
     "rationale": _ORDER},
    {"key": "speed.access", "value": 40, "unit": "km/h", "category": "velocidade",
     "description": "Velocidade em conectores de acesso (município/instalação até a rede)",
     "rationale": "Conectores são artificiais e representam vias locais não mapeadas. " + _ORDER},
    # Custos
    {"key": "cost.road.brl_tkm", "value": 0.20, "unit": "R$/t·km", "category": "custo",
     "description": "Custo variável do transporte rodoviário por tonelada-quilômetro",
     "rationale": _ORDER},
    {"key": "cost.rail.brl_tkm", "value": 0.10, "unit": "R$/t·km", "category": "custo",
     "description": "Custo variável do transporte ferroviário por tonelada-quilômetro",
     "rationale": _ORDER},
    {"key": "cost.waterway.brl_tkm", "value": 0.06, "unit": "R$/t·km", "category": "custo",
     "description": "Custo variável do transporte hidroviário por tonelada-quilômetro",
     "rationale": _ORDER},
    {"key": "cost.road.unpaved_factor", "value": 1.35, "unit": "×", "category": "custo",
     "description": "Multiplicador de custo em vias não pavimentadas (implantada/leito natural)",
     "rationale": "Maior desgaste e consumo. " + _ORDER},
    {"key": "cost.toll.brl_tkm", "value": 0.0, "unit": "R$/t·km", "category": "custo",
     "description": "Pedágio médio por t·km em rodovias federais",
     "rationale": "Zero por padrão: a base não traz praças de pedágio. Ajustável por cenário."},
    {"key": "cost.transfer.brl_t", "value": 15.0, "unit": "R$/t", "category": "custo",
     "description": "Custo de transbordo intermodal por tonelada",
     "rationale": _ORDER},
    {"key": "time.transfer.h", "value": 6.0, "unit": "h", "category": "tempo",
     "description": "Tempo médio de transbordo intermodal",
     "rationale": _ORDER},
    {"key": "cost.value_of_time.brl_th", "value": 0.0, "unit": "R$/t·h", "category": "custo",
     "description": "Valor do tempo da carga (somado ao custo generalizado)",
     "rationale": "Zero por padrão para não misturar custo monetário e tempo sem decisão explícita do usuário."},
    # Rede
    {"key": "network.access_detour_factor", "value": 1.3, "unit": "×", "category": "rede",
     "description": "Fator de sinuosidade aplicado à distância em linha reta dos conectores de acesso",
     "rationale": "Conectores ligam o ponto representativo do município/instalação ao nó de rede mais próximo; não são rotas reais."},
    {"key": "network.snap_tolerance_m", "value": 250, "unit": "m", "category": "rede",
     "description": "Tolerância para unir extremidades de segmentos próximos",
     "rationale": "Fecha descontinuidades de digitalização; pode criar ligações espúrias em trechos paralelos."},
    {"key": "network.transfer_radius_km", "value": 15, "unit": "km", "category": "rede",
     "description": "Raio máximo para conectar terminais intermodais às redes ferroviária e hidroviária",
     "rationale": "Terminais fora do raio não recebem conexão intermodal."},
    {"key": "network.access_max_km", "value": 60, "unit": "km", "category": "rede",
     "description": "Distância máxima de um conector de acesso",
     "rationale": "Municípios sem nó rodoviário dentro do raio ficam desconectados (ex.: localidades fluviais da Amazônia)."},
    # Demanda / cobertura
    {"key": "demand.per_capita_t_year", "value": 1.0, "unit": "t/hab·ano", "category": "demanda",
     "description": "Demanda de distribuição por habitante (proxy de consumo)",
     "rationale": "Proxy linear da população; NÃO é medição de demanda logística. Ajuste ao produto analisado."},
    {"key": "capacity.static_turnover_per_year", "value": 4, "unit": "giros/ano", "category": "capacidade",
     "description": "Giro anual aplicado à capacidade estática de armazenagem para obter vazão anual (t/ano)",
     "rationale": "A base IBGE informa capacidade estática (t). Vazão = estática × giro. Armazéns de grãos giram "
                  "poucas vezes por ano; CDs de bens de consumo, muito mais. " + _ORDER},
    {"key": "coverage.default_km", "value": 300, "unit": "km", "category": "cobertura",
     "description": "Raio de cobertura padrão (distância na rede) de um centro de distribuição",
     "rationale": "Referência para entregas em até um dia de viagem rodoviária. Ajustável."},
]


def seed_assumptions(db: Session) -> int:
    existing = {a.key for a in db.scalars(select(Assumption))}
    n = 0
    for d in DEFAULTS:
        if d["key"] not in existing:
            db.add(Assumption(**d))
            n += 1
    db.flush()
    return n


def load_assumptions(db: Session) -> dict[str, float]:
    values = {d["key"]: float(d["value"]) for d in DEFAULTS}
    for a in db.scalars(select(Assumption)):
        values[a.key] = float(a.value)
    return values
