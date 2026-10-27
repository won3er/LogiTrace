"""Catálogo das fontes de dados utilizadas, com licença, cobertura e limitações documentadas."""

from __future__ import annotations

from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DataSource


class SourceDef(TypedDict):
    key: str
    name: str
    publisher: str
    url: str
    license: str
    attribution: str
    coverage: str
    reference_date: str
    update_method: str
    limitations: str
    reliability: str


IBGE_LICENSE = (
    "Dados públicos do IBGE. Uso livre com citação da fonte (Política de Difusão do IBGE / "
    "Lei de Acesso à Informação)."
)
IBGE_LOG_URL = (
    "https://geoftp.ibge.gov.br/organizacao_do_territorio/redes_e_fluxos_geograficos/"
    "logistica_dos_transportes/"
)

SOURCES: list[SourceDef] = [
    {
        "key": "ibge_localidades",
        "name": "API de Localidades (municípios, UFs, regiões, regiões imediatas e intermediárias)",
        "publisher": "IBGE",
        "url": "https://servicodados.ibge.gov.br/api/v1/localidades/municipios",
        "license": IBGE_LICENSE,
        "attribution": "Fonte: IBGE, API de Localidades.",
        "coverage": "Brasil, 5.570 municípios",
        "reference_date": "Divisão territorial vigente na data do download",
        "update_method": "Download JSON via API REST; reimportação idempotente por código IBGE",
        "limitations": "Não contém coordenadas; a geometria vem da API de Malhas.",
        "reliability": "alta",
    },
    {
        "key": "ibge_malhas",
        "name": "API de Malhas Territoriais (qualidade intermediária)",
        "publisher": "IBGE",
        "url": "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR",
        "license": IBGE_LICENSE,
        "attribution": "Fonte: IBGE, Malhas Territoriais.",
        "coverage": "Brasil: limites de UFs e municípios",
        "reference_date": "Malha vigente na data do download",
        "update_method": "Download GeoJSON via API REST",
        "limitations": (
            "Geometria simplificada (qualidade 'intermediaria'); adequada para análise "
            "nacional/regional, não para medições cadastrais. O ponto representativo do município é "
            "calculado (ST_PointOnSurface) e não corresponde à sede municipal."
        ),
        "reliability": "alta",
    },
    {
        "key": "ibge_censo2022_pop",
        "name": "Censo Demográfico 2022 - População residente (SIDRA tabela 4709)",
        "publisher": "IBGE",
        "url": "https://apisidra.ibge.gov.br/values/t/4709/n6/all/v/93/p/2022",
        "license": IBGE_LICENSE,
        "attribution": "Fonte: IBGE, Censo Demográfico 2022.",
        "coverage": "Brasil, municípios",
        "reference_date": "2022",
        "update_method": "Download via API SIDRA",
        "limitations": "População é usada como proxy de demanda de consumo; não mede demanda logística.",
        "reliability": "alta",
    },
    {
        "key": "ibge_pib_municipal",
        "name": "PIB dos Municípios (SIDRA tabela 5938, variável 37)",
        "publisher": "IBGE",
        "url": "https://apisidra.ibge.gov.br/values/t/5938/n6/all/v/37/p/last",
        "license": IBGE_LICENSE,
        "attribution": "Fonte: IBGE, PIB dos Municípios.",
        "coverage": "Brasil, municípios",
        "reference_date": "Último ano disponível na tabela no download",
        "update_method": "Download via API SIDRA",
        "limitations": (
            "PIB a preços correntes (mil R$). 'Polos econômicos' são derivados por limiar de PIB, "
            "não por cadastro de indústrias."
        ),
        "reliability": "alta",
    },
    {
        "key": "ibge_logistica_2014",
        "name": "Logística dos Transportes no Brasil 2014 - base de dados geográficos",
        "publisher": "IBGE",
        "url": IBGE_LOG_URL + "2014/base_de_dados_2014.zip",
        "license": IBGE_LICENSE,
        "attribution": "Fonte: IBGE, Logística dos Transportes no Brasil 2014.",
        "coverage": (
            "Brasil: rodovias (SNV), ferrovias, hidrovias, portos, terminais portuários, portos "
            "secos, armazéns, aeroportos, aeródromos, pontos de fronteira e eixos estruturantes"
        ),
        "reference_date": "2014 (aeroportos: movimento 2010)",
        "update_method": "Download do ZIP de shapefiles; importador específico por camada",
        "limitations": (
            "Base de 2014: não reflete obras, concessões e novas instalações posteriores. "
            "Rodovias sem velocidade, capacidade ou pedágio. Armazéns sem nome e sem operador; "
            "capacidade estática em toneladas. Hidrovias sem atributos de calado ou sazonalidade."
        ),
        "reliability": "média",
    },
    {
        "key": "ibge_fluxos_2024",
        "name": "Logística dos Transportes 2024 - Fluxos consolidados de mercadorias",
        "publisher": "IBGE",
        "url": IBGE_LOG_URL + "2024/Base_de_dados/Fluxos_Consolidados_de_Mercadorias/",
        "license": IBGE_LICENSE,
        "attribution": "Fonte: IBGE, Logística dos Transportes 2024 (fluxos consolidados).",
        "coverage": (
            "Ligações bidirecionais entre municípios: rodoviário (contagem de CIOT 2023), "
            "ferroviário (TU), aquaviário cabotagem/interior por mercadoria (t), aéreo doméstico (kg)"
        ),
        "reference_date": "Publicação IBGE 2024; rodoviário = CIOT 2023 (demais períodos conforme nota técnica do IBGE)",
        "update_method": "Download dos GeoPackages; importador específico por modal",
        "limitations": (
            "Ligações bidirecionais agregadas: não indicam sentido nem rota percorrida. O "
            "rodoviário mede número de operações (CIOT), não toneladas. A linha desenhada entre "
            "municípios é representação esquemática e não a rota física."
        ),
        "reliability": "média",
    },
    {
        "key": "openfreemap",
        "name": "Mapa base vetorial (OpenStreetMap via OpenFreeMap)",
        "publisher": "OpenStreetMap contributors / OpenFreeMap",
        "url": "https://openfreemap.org",
        "license": "ODbL 1.0 (dados OSM)",
        "attribution": "© OpenStreetMap contributors, OpenFreeMap",
        "coverage": "Mundial (apenas visualização de fundo)",
        "reference_date": "Contínua",
        "update_method": "Consumido como estilo de mapa no navegador; configurável",
        "limitations": "Usado somente como fundo cartográfico; não alimenta cálculos.",
        "reliability": "média",
    },
    {
        "key": "logitrace_user",
        "name": "Cadastro do usuário",
        "publisher": "Usuário do LogiTrace",
        "url": "-",
        "license": "Definida pelo usuário",
        "attribution": "Dado inserido pelo usuário",
        "coverage": "Variável",
        "reference_date": "Data do cadastro",
        "update_method": "API / importação CSV ou GeoJSON",
        "limitations": "Não validado por fonte oficial.",
        "reliability": "baixa",
    },
]


def ensure_sources(db: Session) -> dict[str, DataSource]:
    existing = {s.key: s for s in db.scalars(select(DataSource))}
    for d in SOURCES:
        src = existing.get(d["key"])
        if src is None:
            src = DataSource(**d)
            db.add(src)
            existing[d["key"]] = src
        else:
            for k, v in d.items():
                setattr(src, k, v)
    db.flush()
    return existing
