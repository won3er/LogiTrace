"""Inteligência territorial: indicadores com denominadores, hexágonos, cobertura pela rede e áreas candidatas."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from shapely.geometry import shape
from sqlalchemy import text

from app.api.common import DB, graph_or_404
from app.core.assumptions import load_assumptions
from app.network.engine import ModalMode

router = APIRouter(prefix="/territory", tags=["território"])
Multi = Annotated[list[str] | None, Query()]
Level = Literal["region", "state", "intermediate_region", "immediate_region", "municipality"]

LEVEL_SQL = {
    "region": ("m.region_code", "r.name", "JOIN region r ON r.code = m.region_code"),
    "state": ("m.state_code", "s.name || ' (' || s.uf || ')'", "JOIN state s ON s.code = m.state_code"),
    "intermediate_region": ("m.intermediate_region_code", "max(m.intermediate_region_name) || ' (' || max(m.uf) || ')'", ""),
    "immediate_region": ("m.immediate_region_code", "max(m.immediate_region_name) || ' (' || max(m.uf) || ')'", ""),
    "municipality": ("m.code", "max(m.name) || '/' || max(m.uf)", ""),
}

METRIC_META: dict[str, dict[str, str]] = {
    "population": {"label": "População residente", "unit": "hab.", "period": "2022", "source": "IBGE, Censo 2022",
                   "definition": "Pessoas residentes"},
    "area_km2": {"label": "Área", "unit": "km²", "period": "malha vigente", "source": "IBGE, Malhas (área calculada)",
                 "definition": "Área geodésica calculada da malha simplificada"},
    "gdp_million_brl": {"label": "PIB", "unit": "R$ milhões (correntes)", "period": "último ano SIDRA", "source": "IBGE, PIB dos Municípios",
                        "definition": "Produto Interno Bruto a preços correntes"},
    "facilities": {"label": "Instalações", "unit": "nº", "period": "2014 / 2024 (por camada)", "source": "IBGE Logística dos Transportes",
                   "definition": "Contagem de instalações (filtros aplicados) localizadas na unidade",
                   "limitations": "Armazéns são um registro agregado por município."},
    "facilities_per_100k": {"label": "Instalações por 100 mil hab.", "unit": "nº/100 mil hab.", "period": "instalações 2014–2024; pop. 2022",
                            "source": "IBGE", "definition": "Instalações ÷ população × 100.000", "denominator": "População 2022"},
    "facilities_per_10k_km2": {"label": "Instalações por 10 mil km²", "unit": "nº/10 mil km²", "period": "2014–2024",
                               "source": "IBGE", "definition": "Instalações ÷ área × 10.000", "denominator": "Área (km²)"},
    "storage_t": {"label": "Capacidade estática de armazenagem", "unit": "t", "period": "2014", "source": "IBGE Logística 2014",
                  "definition": "Soma da capacidade estática dos registros de armazenagem"},
    "storage_t_per_capita": {"label": "Armazenagem por habitante", "unit": "t/hab.", "period": "2014 / pop. 2022",
                             "source": "IBGE", "definition": "Capacidade estática ÷ população", "denominator": "População 2022",
                             "limitations": "Períodos diferentes no numerador e no denominador."},
    "road_km": {"label": "Rodovias", "unit": "km", "period": "2014", "source": "IBGE Logística 2014 (SNV)",
                "definition": "Extensão de rodovias existentes (exclui planejadas) dentro da unidade"},
    "road_paved_share": {"label": "Rodovias pavimentadas", "unit": "%", "period": "2014", "source": "IBGE Logística 2014 (SNV)",
                         "definition": "Extensão pavimentada/duplicada ÷ extensão total", "denominator": "Extensão rodoviária"},
    "road_density": {"label": "Densidade rodoviária", "unit": "km/1.000 km²", "period": "2014", "source": "IBGE",
                     "definition": "Extensão rodoviária ÷ área × 1.000", "denominator": "Área (km²)"},
    "rail_km": {"label": "Ferrovias", "unit": "km", "period": "2014", "source": "IBGE Logística 2014",
                "definition": "Extensão ferroviária dentro da unidade (inclui linhas urbanas de passageiros)"},
    "waterway_km": {"label": "Vias navegáveis", "unit": "km", "period": "2014", "source": "IBGE Logística 2014",
                    "definition": "Extensão de hidrovias mapeadas dentro da unidade"},
}


def _fac_filter(category: list[str] | None, modal: list[str] | None) -> tuple[str, dict[str, Any]]:
    where, p = ["f.record_class IN ('official','user')"], {}
    if category:
        where.append("f.category = ANY(:cats)")
        p["cats"] = category
    if modal:
        where.append("f.modal = ANY(:modals)")
        p["modals"] = modal
    return " AND ".join(where), p


@router.get("/indicators")
def indicators(db: DB, level: Level = "state", category: Multi = None, modal: Multi = None, uf: Multi = None,
               sort: str = "population", limit: int = Query(6000, le=6000)) -> dict[str, Any]:
    key, label, join = LEVEL_SQL[level]
    fwhere, params = _fac_filter(category, modal)
    mwhere = "TRUE"
    if uf:
        mwhere = "m.uf = ANY(:ufs)"
        params["ufs"] = [u.upper() for u in uf]
    sql = f"""
    WITH fac AS (
        SELECT f.municipality_code AS code, count(*) AS n,
               sum(CASE WHEN f.category='armazem' THEN f.capacity_value ELSE 0 END) AS storage
        FROM facility f WHERE {fwhere} GROUP BY 1
    ), inf AS (
        SELECT code, sum(km) FILTER (WHERE modal='road') AS road, sum(km_paved) FILTER (WHERE modal='road') AS road_paved,
               sum(km) FILTER (WHERE modal='rail') AS rail, sum(km) FILTER (WHERE modal='waterway') AS water
        FROM mv_municipality_infra GROUP BY code
    )
    SELECT {key} AS code, {label} AS name, max(m.uf) AS uf, sum(m.population) AS population, sum(m.area_km2) AS area_km2,
           sum(m.gdp_thousand_brl)/1000 AS gdp_million_brl, coalesce(sum(fac.n),0) AS facilities,
           coalesce(sum(fac.storage),0) AS storage_t, coalesce(sum(inf.road),0) AS road_km,
           coalesce(sum(inf.road_paved),0) AS road_paved_km, coalesce(sum(inf.rail),0) AS rail_km,
           coalesce(sum(inf.water),0) AS waterway_km, count(*) AS municipalities
    FROM municipality m {join}
    LEFT JOIN fac ON fac.code = m.code LEFT JOIN inf ON inf.code = m.code
    WHERE {mwhere}
    GROUP BY {key}{', ' + label if level in ('region', 'state') else ''}
    """
    rows = [{k: _num(v) for k, v in r.items()} for r in db.execute(text(sql), params).mappings()]
    for r in rows:
        pop, area = r["population"] or 0, r["area_km2"] or 0
        r["facilities_per_100k"] = round(r["facilities"] / pop * 1e5, 3) if pop else None
        r["facilities_per_10k_km2"] = round(r["facilities"] / area * 1e4, 3) if area else None
        r["storage_t_per_capita"] = round(r["storage_t"] / pop, 4) if pop else None
        r["road_paved_share"] = round(100 * r["road_paved_km"] / r["road_km"], 1) if r["road_km"] else None
        r["road_density"] = round(r["road_km"] / area * 1000, 2) if area else None
        for k in ("area_km2", "gdp_million_brl", "road_km", "road_paved_km", "rail_km", "waterway_km", "storage_t"):
            r[k] = round(float(r[k]), 1) if r[k] is not None else None
    rows.sort(key=lambda r: -(r.get(sort) or 0) if isinstance(r.get(sort), int | float) else 0)
    total_fac = sum(r["facilities"] for r in rows)
    for r in rows:
        r["facilities_share"] = round(r["facilities"] / total_fac, 5) if total_fac else None
    return {"level": level, "filters": {"category": category, "modal": modal, "uf": uf}, "metrics": METRIC_META,
            "items": rows[:limit], "concentration": _concentration([r["facilities"] for r in rows])}


def _num(v: Any) -> Any:
    """Converte Decimal do PostgreSQL em int/float para cálculo e serialização."""
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def _concentration(values: list[float]) -> dict[str, Any]:
    v = np.array(sorted([x for x in values if x], reverse=True), dtype=float)
    if not len(v):
        return {}
    s = v / v.sum()
    gini = 1 - 2 * np.sum(np.cumsum(np.sort(v)) / v.sum()) / len(v) + 1 / len(v)
    return {"hhi": round(float((s ** 2).sum() * 10000), 1), "top5_share": round(float(s[:5].sum()), 4),
            "top10_share": round(float(s[:10].sum()), 4), "gini": round(float(gini), 4), "units_with_facilities": int(len(v)),
            "definition": "HHI = Σ(participação²)×10.000 entre unidades com ≥1 instalação; Gini sobre as mesmas unidades."}


@router.get("/states")
def states(db: DB) -> list[dict[str, Any]]:
    return [dict(r) for r in db.execute(text(
        "SELECT s.code, s.uf, s.name, r.name AS region, round(s.area_km2::numeric,1)::float8 AS area_km2 FROM state s "
        "JOIN region r ON r.code=s.region_code ORDER BY s.uf")).mappings()]


@router.get("/states/geojson")
def states_geojson(db: DB) -> dict[str, Any]:
    rows = db.execute(text("SELECT code, uf, name, ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.01), 4)::json AS g FROM state")).all()
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": r.code, "geometry": r.g, "properties": {"code": r.code, "uf": r.uf, "name": r.name}} for r in rows]}


@router.get("/municipalities")
def search_municipalities(db: DB, q: str = Query("", max_length=80), uf: str | None = None, limit: int = Query(20, le=100)) -> list[dict[str, Any]]:
    sql = """SELECT code, name, uf, population, ST_X(centroid) AS lon, ST_Y(centroid) AS lat FROM municipality
             WHERE (unaccent_name(name) ILIKE unaccent_name(:q) OR CAST(code AS text) = :raw) {uf}
             ORDER BY (lower(name) = lower(:raw)) DESC, population DESC NULLS LAST LIMIT :lim"""
    params: dict[str, Any] = {"q": f"%{q}%", "raw": q.strip(), "lim": limit}
    sql = sql.replace("{uf}", "AND uf = :uf" if uf else "")
    if uf:
        params["uf"] = uf.upper()
    return [dict(r) for r in db.execute(text(sql), params).mappings()]


@router.get("/municipalities/{code}")
def municipality_detail(db: DB, code: int) -> dict[str, Any]:
    m = db.execute(text(
        """SELECT m.code, m.name, m.uf, m.population, m.population_year, m.gdp_thousand_brl, m.gdp_year,
                  round(m.area_km2::numeric,1)::float8 AS area_km2, m.immediate_region_name, m.intermediate_region_name,
                  r.name AS region, ST_X(m.centroid) AS lon, ST_Y(m.centroid) AS lat
           FROM municipality m JOIN region r ON r.code=m.region_code WHERE m.code=:c"""), {"c": code}).mappings().first()
    if m is None:
        raise HTTPException(404, "Município não encontrado")
    infra = {r.modal: {"km": round(r.km, 1), "km_paved": round(r.km_paved, 1)}
             for r in db.execute(text("SELECT modal, km, km_paved FROM mv_municipality_infra WHERE code=:c"), {"c": code})}
    facs = [dict(r) for r in db.execute(text(
        "SELECT id, name, category, capacity_value, capacity_unit FROM facility WHERE municipality_code=:c ORDER BY category, name"), {"c": code}).mappings()]
    nearest = [dict(r) for r in db.execute(text(
        """SELECT DISTINCT ON (f.category) f.category, f.id, f.name,
                  round((ST_Distance(f.geom::geography, m.centroid::geography)/1000)::numeric, 1)::float8 AS straight_km
           FROM facility f, municipality m WHERE m.code=:c
             AND ST_DWithin(f.geom::geography, m.centroid::geography, 600000)
           ORDER BY f.category, f.geom::geography <-> m.centroid::geography"""), {"c": code}).mappings()]
    flows = [dict(r) for r in db.execute(text(
        """SELECT dataset, unit, count(*) AS links, sum(value) AS total FROM flow
           WHERE flow_class='observed' AND (origin_code=:s OR dest_code=:s) GROUP BY dataset, unit"""), {"s": str(code)}).mappings()]
    return {**dict(m), "infrastructure": infra, "facilities": facs, "nearest_by_category": nearest, "observed_flows": flows,
            "notes": ["Distâncias 'straight_km' são em linha reta; use /network/route para distância na rede.",
                      "Fluxos são ligações bidirecionais agregadas (IBGE 2024)."]}


@router.get("/hex")
def hexbin(db: DB, size_km: float = Query(40, ge=5, le=300), metric: Literal["facilities", "population", "storage"] = "facilities",
           category: Multi = None, modal: Multi = None) -> dict[str, Any]:
    """Agregação em hexágonos (ST_HexagonGrid em SIRGAS 2000 / Brazil Polyconic; tamanho = lado do hexágono)."""
    if metric == "population":
        pts = "SELECT ST_Transform(centroid, 5880) AS g, population::float AS w FROM municipality WHERE population IS NOT NULL"
        params: dict[str, Any] = {}
    else:
        fwhere, params = _fac_filter(category, modal)
        w = "coalesce(f.capacity_value,0)" if metric == "storage" else "1.0"
        pts = f"SELECT ST_Transform(f.geom, 5880) AS g, {w} AS w FROM facility f WHERE {fwhere}"
    sql = f"""
    WITH pts AS ({pts}),
    grid AS (SELECT (ST_HexagonGrid(:s, ST_Transform(ST_MakeEnvelope(-74.5,-34.5,-28.0,5.9,4326),5880))).geom)
    SELECT ST_AsGeoJSON(ST_Transform(grid.geom, 4326), 4)::json AS g, sum(pts.w) AS v, count(*) AS n
    FROM grid JOIN pts ON ST_Intersects(grid.geom, pts.g) GROUP BY grid.geom
    """
    rows = db.execute(text(sql), {**params, "s": size_km * 1000}).all()
    return {"type": "FeatureCollection", "metric": metric, "size_km": size_km,
            "unit": {"facilities": "instalações", "population": "hab. (2022)", "storage": "t (capacidade estática)"}[metric],
            "features": [{"type": "Feature", "geometry": r.g, "properties": {"value": float(r.v), "points": r.n}} for r in rows]}


@router.get("/poles")
def economic_poles(db: DB, top: int = Query(150, ge=10, le=1000)) -> dict[str, Any]:
    rows = db.execute(text(
        """SELECT code, name, uf, gdp_thousand_brl, gdp_year, population, ST_X(centroid) lon, ST_Y(centroid) lat,
                  gdp_thousand_brl / sum(gdp_thousand_brl) OVER () AS share
           FROM municipality WHERE gdp_thousand_brl IS NOT NULL ORDER BY gdp_thousand_brl DESC LIMIT :t"""), {"t": top}).mappings().all()
    cum = 0.0
    items = []
    for r in rows:
        cum += float(r["share"])
        items.append({**dict(r), "share": round(float(r["share"]), 5), "cumulative_share": round(cum, 4)})
    return {"definition": f"Polos econômicos = {top} municípios de maior PIB (IBGE, preços correntes). Não identifica setores "
                          "industriais ou agrícolas específicos.", "period": str(rows[0]["gdp_year"]) if rows else None,
            "items": items}


class CoverageRequest(BaseModel):
    categories: list[str] = Field(default_factory=lambda: ["armazem"])
    facility_ids: list[int] | None = None
    threshold_km: float | None = Field(default=None, gt=0)
    mode: ModalMode = "road"
    level: Literal["municipality", "immediate_region"] = "immediate_region"
    ufs: list[str] | None = None


def _coverage_distances(db: DB, body: CoverageRequest) -> tuple[Any, np.ndarray, np.ndarray, list[int]]:
    g = graph_or_404(db)
    a = load_assumptions(db)
    if body.facility_ids:
        ids = body.facility_ids
    else:
        ids = [r[0] for r in db.execute(text("SELECT id FROM facility WHERE category = ANY(:c)"), {"c": body.categories})]
    nodes = [g._fac_node[i] for i in ids if i in g._fac_node]
    if not nodes:
        raise HTTPException(400, "Nenhuma instalação conectada à rede com os filtros informados")
    dist = g.sssp(nodes, "distance", a, body.mode, min_only=True)
    mun_nodes = g.node_of_kind("municipality")
    return g, dist, mun_nodes, nodes


@router.post("/coverage")
def coverage(db: DB, body: CoverageRequest) -> dict[str, Any]:
    """Cobertura pela rede: distância na rede até a instalação mais próxima, por município ou região imediata.

    A classificação considera população, oferta relativa (quociente locacional), distância na rede e
    conectividade — não apenas o número de instalações.
    """
    a = load_assumptions(db)
    thr = body.threshold_km or a["coverage.default_km"]
    g, dist, mun_nodes, nodes = _coverage_distances(db, body)
    km = {int(g.node_ref[n]): float(dist[n]) for n in mun_nodes}
    ufs_clause = "AND m.uf = ANY(:ufs)" if body.ufs else ""
    params: dict[str, Any] = {"ufs": [u.upper() for u in body.ufs]} if body.ufs else {}
    rows = db.execute(text(
        f"""SELECT m.code, m.name, m.uf, m.population, m.immediate_region_code AS rgi, m.immediate_region_name AS rgi_name,
                   (SELECT count(*) FROM facility f WHERE f.municipality_code = m.code AND f.category = ANY(:cats)) AS nfac
            FROM municipality m WHERE TRUE {ufs_clause}"""), {**params, "cats": body.categories}).mappings().all()
    method = (f"Distância = menor caminho na rede ({'rodoviária' if body.mode == 'road' else 'multimodal'}) até a instalação "
              f"mais próxima das categorias {body.categories}. Limiar de cobertura: {thr:g} km. "
              "Quociente locacional (QL) = participação na oferta ÷ participação na população.")
    if body.level == "municipality":
        items = []
        for r in rows:
            d = km.get(r["code"], float("inf"))
            cls = "sem_conexao" if not np.isfinite(d) else ("coberto" if d <= thr else "distante")
            items.append({"code": r["code"], "name": r["name"], "uf": r["uf"], "population": r["population"],
                          "network_km": round(d, 1) if np.isfinite(d) else None, "class": cls})
        return {"level": "municipality", "threshold_km": thr, "method": method, "items": items,
                "summary": _cov_summary(items, "population")}
    groups: dict[int, dict[str, Any]] = {}
    for r in rows:
        gr = groups.setdefault(r["rgi"], {"code": r["rgi"], "name": r["rgi_name"], "uf": r["uf"], "population": 0,
                                         "facilities": 0, "pop_within": 0, "pop_connected": 0, "wkm": 0.0})
        pop = r["population"] or 0
        d = km.get(r["code"], float("inf"))
        gr["population"] += pop
        gr["facilities"] += r["nfac"]
        if np.isfinite(d):
            gr["pop_connected"] += pop
            gr["wkm"] += pop * d
            if d <= thr:
                gr["pop_within"] += pop
    tot_pop = sum(g_["population"] for g_ in groups.values()) or 1
    tot_fac = sum(g_["facilities"] for g_ in groups.values()) or 1
    items = []
    for gr in groups.values():
        pop = gr["population"]
        lq = (gr["facilities"] / tot_fac) / (pop / tot_pop) if pop else None
        within = gr["pop_within"] / pop if pop else None
        conn = gr["pop_connected"] / pop if pop else None
        avg = gr["wkm"] / gr["pop_connected"] if gr["pop_connected"] else None
        if not pop:
            cls = "dados_insuficientes"
        elif conn is not None and conn < 0.5:
            cls = "sem_conexao"
        elif within is not None and within < 0.5 and (lq or 0) < 0.5:
            cls = "baixa_cobertura_relativa"
        elif (lq or 0) < 0.5 and within is not None and within >= 0.8:
            cls = "atendida_por_vizinhas"
        else:
            cls = "adequada"
        items.append({"code": gr["code"], "name": gr["name"], "uf": gr["uf"], "population": pop, "facilities": gr["facilities"],
                      "location_quotient": round(lq, 3) if lq is not None else None,
                      "share_within_threshold": round(within, 4) if within is not None else None,
                      "share_connected": round(conn, 4) if conn is not None else None,
                      "avg_network_km": round(avg, 1) if avg is not None else None, "class": cls})
    items.sort(key=lambda x: (x["class"] != "baixa_cobertura_relativa", -(x["population"] or 0)))
    return {"level": "immediate_region", "threshold_km": thr, "method": method,
            "classes": {
                "baixa_cobertura_relativa": "QL < 0,5 e menos de 50% da população dentro do limiar na rede",
                "atendida_por_vizinhas": "QL < 0,5, mas ≥ 80% da população alcança instalação dentro do limiar (em outra região)",
                "sem_conexao": "Mais de 50% da população sem ligação terrestre na base (avaliar modal fluvial/aéreo)",
                "adequada": "Demais casos", "dados_insuficientes": "Sem população"},
            "items": items, "summary": _cov_summary(items, "population")}


def _cov_summary(items: list[dict[str, Any]], wkey: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    tot = sum(i[wkey] or 0 for i in items) or 1
    for i in items:
        c = out.setdefault(i["class"], {"units": 0, "population": 0})
        c["units"] += 1
        c["population"] += i[wkey] or 0
    for c in out.values():
        c["population_share"] = round(c["population"] / tot, 4)
    return out


class CandidatesRequest(CoverageRequest):
    n: int = Field(default=5, ge=1, le=30)
    candidate_pool: int = Field(default=300, ge=10, le=800)


@router.post("/candidates")
def candidate_areas(db: DB, body: CandidatesRequest) -> dict[str, Any]:
    """Áreas candidatas a novas instalações por heurística gulosa de máxima cobertura incremental.

    A cada passo escolhe o município candidato que mais aumenta a população coberta pela rede dentro do
    limiar, dado o que já existe. Garantia teórica: ≥ (1 − 1/e) ≈ 63% do ótimo da cobertura máxima.
    Para solução exata, use /optimization (MCLP).
    """
    a = load_assumptions(db)
    thr = body.threshold_km or a["coverage.default_km"]
    g, dist, mun_nodes, _ = _coverage_distances(db, body)
    ufs = [u.upper() for u in body.ufs] if body.ufs else None
    rows = db.execute(text(
        f"SELECT code, name, uf, population FROM municipality WHERE population IS NOT NULL {'AND uf = ANY(:u)' if ufs else ''}"),
        {"u": ufs} if ufs else {}).mappings().all()
    dem = [r for r in rows if r["code"] in g._mun_node]
    dn = np.array([g._mun_node[r["code"]] for r in dem])
    pop = np.array([r["population"] for r in dem], dtype=float)
    covered = dist[dn] <= thr
    pool = sorted(dem, key=lambda r: -r["population"])[: body.candidate_pool]
    cand_nodes = [g._mun_node[r["code"]] for r in pool]
    km = g.sssp(cand_nodes, "distance", a, body.mode, limit=thr)[:, dn]
    reach = km <= thr
    base_cov = float(pop[covered].sum())
    picks = []
    for _ in range(body.n):
        gain = (reach & ~covered) @ pop
        j = int(np.argmax(gain))
        if gain[j] <= 0:
            break
        covered |= reach[j]
        r = pool[j]
        picks.append({"code": r["code"], "name": r["name"], "uf": r["uf"], "population": r["population"],
                      "lon": float(g.node_lon[cand_nodes[j]]), "lat": float(g.node_lat[cand_nodes[j]]),
                      "marginal_population": int(gain[j]), "cumulative_coverage": round(float(pop[covered].sum() / pop.sum()), 4)})
        reach[j] = False
    return {"threshold_km": thr, "base_coverage": round(base_cov / pop.sum(), 4) if pop.sum() else None,
            "method": "Heurística gulosa de máxima cobertura sobre distâncias na rede (garantia ≥ 63% do ótimo).",
            "assumptions": ["População (Censo 2022) como proxy de demanda", "Candidatos = municípios mais populosos do recorte",
                            "Cobertura = alcance na rede dentro do limiar, não tempo de entrega"],
            "items": picks}


class AreaRequest(BaseModel):
    geometry: dict[str, Any]


@router.post("/area")
def area_analysis(db: DB, body: AreaRequest) -> dict[str, Any]:
    try:
        geom = shape(body.geometry)
    except Exception as exc:
        raise HTTPException(400, "Geometria GeoJSON inválida") from exc
    if geom.geom_type not in ("Polygon", "MultiPolygon") or not geom.is_valid:
        raise HTTPException(400, "Informe um polígono válido")
    wkt = geom.wkt
    p = {"wkt": wkt}
    area = db.scalar(text("SELECT ST_Area(ST_GeomFromText(:wkt,4326)::geography)/1e6"), p)
    if area and area > 3_000_000:
        raise HTTPException(400, "Área acima de 3 milhões de km²; use os indicadores por UF/região")
    muns = db.execute(text(
        """SELECT count(*) n, coalesce(sum(population),0) pop, coalesce(sum(gdp_thousand_brl),0)/1000 gdp
           FROM municipality WHERE ST_Intersects(centroid, ST_GeomFromText(:wkt,4326))"""), p).mappings().first()
    facs = [dict(r) for r in db.execute(text(
        """SELECT category, count(*) n, sum(capacity_value) cap FROM facility
           WHERE ST_Intersects(geom, ST_GeomFromText(:wkt,4326)) GROUP BY category ORDER BY n DESC"""), p).mappings()]
    seg = [dict(r) for r in db.execute(text(
        """SELECT modal, round((sum(ST_Length(ST_Intersection(geom, ST_GeomFromText(:wkt,4326))::geography))/1000)::numeric,1)::float8 km
           FROM infra_segment WHERE ST_Intersects(geom, ST_GeomFromText(:wkt,4326)) AND modal IN ('road','rail','waterway','road_axis')
           GROUP BY modal"""), p).mappings()]
    flows = [dict(r) for r in db.execute(text(
        """SELECT dataset, unit, count(*) links, sum(value) total FROM flow
           WHERE flow_class='observed' AND (ST_Intersects(ST_SetSRID(ST_Point(origin_lon,origin_lat),4326), ST_GeomFromText(:wkt,4326))
              OR ST_Intersects(ST_SetSRID(ST_Point(dest_lon,dest_lat),4326), ST_GeomFromText(:wkt,4326)))
           GROUP BY dataset, unit"""), p).mappings()]
    assert muns is not None
    return {"area_km2": round(float(area or 0), 1), "municipalities": muns["n"], "population": int(muns["pop"]),
            "gdp_million_brl": round(float(muns["gdp"]), 1), "facilities": facs, "infrastructure_km": seg,
            "observed_flows_touching": flows,
            "notes": ["Municípios contados pelo ponto representativo dentro da área (população integral do município).",
                      "Extensões calculadas pela interseção geométrica com a base IBGE 2014.",
                      "Cobertura dos dados: instalações listadas são apenas as presentes nas fontes importadas."]}


@router.get("/compare")
def compare_regions(db: DB, uf: Annotated[list[str], Query()], category: Multi = None) -> dict[str, Any]:
    res = indicators(db, level="state", category=category, modal=None, uf=uf, sort="population", limit=60)
    return {"metrics": res["metrics"], "items": res["items"]}

