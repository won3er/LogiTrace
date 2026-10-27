"""Exportações (CSV, GeoJSON, Excel) e relatórios PDF."""

from __future__ import annotations

import io
import json
from typing import Annotated, Any, Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.api import flows as flows_api
from app.api import territory as territory_api
from app.api.common import DB, graph_or_404
from app.api.facilities import _base_query, _out
from app.models import OptimizationRun, ScenarioRun
from app.reports.pdf import optimization_report, scenario_report, territory_report

router = APIRouter(tags=["exportação"])
Multi = Annotated[list[str] | None, Query()]
Fmt = Literal["csv", "xlsx", "geojson"]
MEDIA = {"csv": "text/csv; charset=utf-8", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "geojson": "application/geo+json", "pdf": "application/pdf"}
ATTRIBUTION = "Fonte dos dados: IBGE (Logística dos Transportes 2014/2024, Censo 2022, Malhas). Processamento: LogiTrace."


def _file(content: bytes | str, name: str, fmt: str) -> Response:
    body = content.encode("utf-8-sig") if isinstance(content, str) else content
    return Response(body, media_type=MEDIA[fmt], headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _tabular(sheets: dict[str, pd.DataFrame], name: str, fmt: str, meta: dict[str, Any]) -> Response:
    if fmt == "csv":
        first = next(iter(sheets.values()))
        return _file(first.to_csv(index=False, sep=";", decimal=","), f"{name}.csv", "csv")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for sheet, df in sheets.items():
            df.to_excel(xw, sheet_name=sheet[:31], index=False)
        pd.DataFrame([{"campo": k, "valor": json.dumps(v, ensure_ascii=False, default=str) if not isinstance(v, str) else v}
                      for k, v in {**meta, "atribuicao": ATTRIBUTION}.items()]).to_excel(xw, sheet_name="metadados", index=False)
    return _file(buf.getvalue(), f"{name}.xlsx", "xlsx")


@router.get("/exports/facilities.{fmt}")
def export_facilities(db: DB, fmt: Fmt, q: str | None = None, category: Multi = None, modal: Multi = None,
                      uf: Multi = None, record_class: Multi = None, bbox: str | None = None) -> Response:
    rows = db.execute(_base_query(q, category, modal, uf, record_class, bbox, None, None).limit(50000)).all()
    items = [_out(r).model_dump() for r in rows]
    if fmt == "geojson":
        fc = {"type": "FeatureCollection", "attribution": ATTRIBUTION, "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [i["lon"], i["lat"]]},
             "properties": {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in i.items() if k not in ("lon", "lat")}}
            for i in items]}
        return _file(json.dumps(fc, ensure_ascii=False, default=str), "instalacoes.geojson", "geojson")
    df = pd.DataFrame(items)
    if not df.empty:
        df["attributes"] = df["attributes"].apply(lambda a: json.dumps(a, ensure_ascii=False))
        df["updated_at"] = df["updated_at"].astype(str)
    return _tabular({"instalacoes": df}, "instalacoes", fmt, {"filtros": {"q": q, "category": category, "uf": uf}})


@router.get("/exports/territory/indicators.{fmt}")
def export_indicators(db: DB, fmt: Literal["csv", "xlsx"], level: territory_api.Level = "state",
                      category: Multi = None, modal: Multi = None, uf: Multi = None) -> Response:
    res = territory_api.indicators(db, level=level, category=category, modal=modal, uf=uf, sort="population", limit=6000)
    meta = pd.DataFrame([{"indicador": k, **v} for k, v in res["metrics"].items()])
    return _tabular({"indicadores": pd.DataFrame(res["items"]), "definicoes": meta}, f"indicadores_{level}", fmt,
                    {"nivel": level, "filtros": res["filters"], "concentracao": res["concentration"]})


@router.get("/exports/flows.{fmt}")
def export_flows(db: DB, fmt: Literal["csv", "xlsx", "geojson"], dataset: Multi = None, flow_class: Multi = None,
                 modal: Multi = None, uf: Multi = None, product_group: Multi = None, min_value: float | None = None,
                 limit: int = Query(20000, le=100000)) -> Response:
    res = flows_api.list_flows(db, dataset=dataset, flow_class=flow_class, modal=modal, uf=uf, product_group=product_group,
                               origin=None, dest=None, min_value=min_value, period=None, international=None, limit=limit)
    if fmt == "geojson":
        fc = {"type": "FeatureCollection", "caveat": res["caveat"], "attribution": ATTRIBUTION, "features": [
            {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[i["olon"], i["olat"]], [i["dlon"], i["dlat"]]]},
             "properties": {k: v for k, v in i.items() if k not in ("olon", "olat", "dlon", "dlat")}} for i in res["items"]]}
        return _file(json.dumps(fc, ensure_ascii=False, default=str), "fluxos.geojson", "geojson")
    return _tabular({"fluxos": pd.DataFrame(res["items"])}, "fluxos", fmt, {"unidade": res["unit"], "aviso": res["caveat"]})


@router.get("/exports/scenario-runs/{run_id}.{fmt}")
def export_scenario(db: DB, run_id: int, fmt: Fmt) -> Response:
    r = db.get(ScenarioRun, run_id)
    if r is None or r.status != "success":
        raise HTTPException(404, "Execução não encontrada ou sem sucesso")
    res = r.results
    if fmt == "geojson":
        from app.api.scenarios import run_routes

        return _file(json.dumps(run_routes(db, run_id, limit=40), ensure_ascii=False), f"cenario_{run_id}_rotas.geojson", "geojson")
    pairs = pd.DataFrame([{k: v for k, v in p.items() if not k.endswith("_edges") and k not in ("base", "scenario")}
                          for p in res["comparison"]["pairs"]])
    od_b = pd.DataFrame([{k: v for k, v in p.items() if k not in ("edges",)} for p in res["baseline"]["od"]["pairs"]])
    od_s = pd.DataFrame([{k: v for k, v in p.items() if k not in ("edges",)} for p in res["scenario"]["od"]["pairs"]])
    sheets = {"comparacao_od": pairs, "od_base": od_b, "od_cenario": od_s}
    svc = res["scenario"].get("service")
    if svc:
        sheets["instalacoes_cenario"] = pd.DataFrame(svc["open_facilities"])
        sheets["demanda_cenario"] = pd.DataFrame(svc["demand"])
    if res["baseline"].get("service"):
        sheets["instalacoes_base"] = pd.DataFrame(res["baseline"]["service"]["open_facilities"])
    return _tabular(sheets, f"cenario_{run_id}", fmt, {"run": run_id, "input_hash": r.input_hash, "result_hash": r.result_hash,
                                                       "rede": r.network_version_id, "entradas": r.inputs})


@router.get("/exports/optimization-runs/{run_id}.{fmt}")
def export_optimization(db: DB, run_id: int, fmt: Fmt) -> Response:
    r = db.get(OptimizationRun, run_id)
    if r is None or not r.results:
        raise HTTPException(404, "Execução não encontrada ou sem resultado")
    if fmt == "geojson":
        from app.api.optimization import run_geojson

        return _file(json.dumps(run_geojson(db, run_id), ensure_ascii=False, default=str), f"otimizacao_{run_id}.geojson", "geojson")
    res = r.results
    sheets: dict[str, pd.DataFrame] = {}
    if res.get("open_facilities") is not None:
        sheets["instalacoes"] = pd.DataFrame(res["open_facilities"])
        sheets["demanda"] = pd.DataFrame(res["demand"])
    if res.get("points"):
        sheets["fronteira"] = pd.DataFrame(res["points"]).assign(open=lambda d: d["open"].apply(", ".join), open_names=lambda d: d["open_names"].apply(", ".join))
    if res.get("routes"):
        sheets["rotas"] = pd.DataFrame([{"veiculo": x["vehicle"], "km": x["km"], "carga": x["load"],
                                         "sequencia": " > ".join(s["name"] for s in x["stops"])} for x in res["routes"]])
    if not sheets:
        sheets["resultado"] = pd.DataFrame([res.get("kpis") or {}])
    return _tabular(sheets, f"otimizacao_{run_id}", fmt, {
        "problema": r.problem, "qualidade": r.solution_quality, "solver": r.solver, "objetivo": r.objective,
        "valor_objetivo": r.objective_value, "gap": r.gap, "restricoes": r.constraints, "premissas": r.assumptions})


@router.get("/reports/scenario-runs/{run_id}.pdf")
def pdf_scenario(db: DB, run_id: int) -> Response:
    r = db.get(ScenarioRun, run_id)
    if r is None or r.status != "success":
        raise HTTPException(404, "Execução não encontrada ou sem sucesso")
    return _file(scenario_report(db, r, graph_or_404(db, r.network_version_id)), f"relatorio_cenario_{run_id}.pdf", "pdf")


@router.get("/reports/optimization-runs/{run_id}.pdf")
def pdf_optimization(db: DB, run_id: int) -> Response:
    r = db.get(OptimizationRun, run_id)
    if r is None or not r.results:
        raise HTTPException(404, "Execução não encontrada ou sem resultado")
    return _file(optimization_report(db, r), f"relatorio_otimizacao_{run_id}.pdf", "pdf")


@router.get("/reports/territory.pdf")
def pdf_territory(db: DB, level: territory_api.Level = "state", category: Multi = None, uf: Multi = None,
                  coverage_categories: Multi = None) -> Response:
    ind = territory_api.indicators(db, level=level, category=category, modal=None, uf=uf, sort="population", limit=6000)
    cov = None
    if coverage_categories:
        cov = territory_api.coverage(db, territory_api.CoverageRequest(categories=coverage_categories, ufs=uf))
    return _file(territory_report(db, ind, cov), "relatorio_territorial.pdf", "pdf")
